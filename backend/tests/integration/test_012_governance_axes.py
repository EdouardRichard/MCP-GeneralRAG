"""Six governance axes in real stores, SQL replay and lifecycle transitions."""
import asyncio
import gzip
import json
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from rag_mcp.indexing.memory_vectors import revision_filter
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.models.memory_salience import MemorySalience
from rag_mcp.models.memory_views import MemoryLink, MemorySummaryNode
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_reducer import projection_fingerprint, reduce_events
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_persisted_write_loop import published_payload


AXES = ("authority", "scope_meta", "mutability", "provenance_meta", "recoverability", "actionability")


async def assert_real_axes(service, scope_id, *, require_nonempty=False):
    session = service.session
    history = await MemoryEventStore(session).replay(scope_id)
    state = reduce_events(history)
    current = await service.projections.current(scope_id)
    sql_state = await session.scalar(text("SELECT memory_log_state(:scope, :event)"),
                                     {"scope": scope_id, "event": history[-1]["event_id"]})
    assert sql_state == json.loads(state._serialized), "SQL reducer lost governance axes"
    source_axes = {event["aggregate_id"]: {axis: event[axis] for axis in AXES}
                   for event in history if event["event_type"] in {"assert", "revise", "consolidate"}}
    actual = {}
    for name, model in (("relation", MemoryEntry), ("salience", MemorySalience)):
        statement = select(model)
        if model is MemorySalience:
            statement = statement.join(MemoryEntry).where(MemoryEntry.knowledge_scope_id == scope_id)
        else:
            statement = statement.where(MemoryEntry.knowledge_scope_id == scope_id)
        rows = (await session.execute(statement.execution_options(populate_existing=True))).scalars().all()
        actual[name] = [{"memory_id": row.memory_id, **{axis: getattr(row, axis, None) for axis in AXES}} for row in rows]
    points, _ = await asyncio.to_thread(service.projections.qdrant._client.scroll,
        collection_name=current.payload["collection"], scroll_filter=revision_filter(scope_id, current.source_event_id),
        limit=10000, with_payload=True)
    actual["dense"] = [point.payload for point in points]
    for name, model in (("links", MemoryLink), ("summary", MemorySummaryNode)):
        rows = (await session.execute(select(model).where(model.knowledge_scope_id == scope_id,
                                     model.revision_id == current.source_event_id))).scalars().all()
        actual[name] = [item for row in rows for item in (row.data if name == "summary" else [row.data])]
    directory = Path(current.payload["root"]) / str(scope_id) / str(current.source_event_id)
    actual["file"] = []
    for key in state["files"]:
        path = directory / key
        body = gzip.decompress(path.read_bytes()).decode("utf-8") if key.endswith(".gz") else path.read_text(encoding="utf-8")
        actual["file"].append(json.loads(body.split("\n\n", 1)[1]))
    assert set(actual) == {"relation", "dense", "links", "summary", "file", "salience"}
    for name, rows in actual.items():
        if require_nonempty:
            assert rows, f"{name} is an empty placeholder"
        for row in rows:
            assert {axis: row.get(axis) for axis in AXES} == source_axes[int(row["memory_id"])], name
    report = await service.inspect_projections(scope_id)
    assert all(row["matches_replay"] for row in report.values()), report
    return state, actual


@pytest.mark.asyncio
async def test_actual_six_views_keep_governance_through_lifecycle_rebuild_and_rollback(db_session):
    payload = await published_payload(db_session)
    scope_id = payload["scope_id"]
    service = MemoryService(db_session)
    first = await service.record(payload)
    point = first["memory_id"]
    await assert_real_axes(service, scope_id, require_nonempty=True)
    await service.govern("access", scope_id=scope_id, actor="management", reason="usage", memory_id=point)
    await assert_real_axes(service, scope_id, require_nonempty=True)
    second = await service.record({**payload, "content": payload["content"] + " Revised.", "supersedes_memory_id": point})
    await assert_real_axes(service, scope_id, require_nonempty=True)
    for stage in ("compressed", "archived", "tombstone"):
        await service.govern("lifecycle", scope_id=scope_id, actor="management", reason="retention", memory_id=second["memory_id"], retention_stage=stage)
        state, actual = await assert_real_axes(service, scope_id)
        assert state["entries"][second["memory_id"]]["retention_stage"] == stage
        if stage in {"archived", "tombstone"}:
            for name in ("dense", "links", "summary"):
                assert all(int(row["memory_id"]) != second["memory_id"] for row in actual[name])
        if stage == "tombstone":
            assert all(int(row["memory_id"]) != second["memory_id"] for row in actual["file"])
    await service.govern("retire", scope_id=scope_id, actor="management", reason="delete old", memory_id=point)
    before, actual = await assert_real_axes(service, scope_id)
    assert all(not actual[name] for name in ("dense", "links", "summary", "file"))
    await service.rebuild(scope_id, actor="management")
    after, _ = await assert_real_axes(service, scope_id)
    assert projection_fingerprint(after) == projection_fingerprint(before)
    await service.govern("rollback", scope_id=scope_id, actor="management", reason="restore original", event_point=point)
    restored, _ = await assert_real_axes(service, scope_id, require_nonempty=True)
    assert restored["entries"][point]["status"] == "active"
    assert restored["salience"][point]["access_count"] == 1
    assert restored["entries"][second["memory_id"]]["status"] == "retired"
    await service.rebuild(scope_id, actor="management")
    rebuilt, _ = await assert_real_axes(service, scope_id, require_nonempty=True)
    assert projection_fingerprint(rebuilt) == projection_fingerprint(restored)


@pytest.mark.asyncio
async def test_database_guards_reject_each_forged_axis_with_current_event_authority(db_session):
    payload = await published_payload(db_session)
    service = MemoryService(db_session)
    result = await service.record(payload)
    await db_session.execute(text("SET LOCAL ROLE rag_memory_reducer"))
    await db_session.execute(text("SELECT set_config('rag_memory.reducer_event', :event, true)"), {"event": str(result["memory_id"])})
    for table in ("memory_entries", "memory_salience"):
        for axis in AXES:
            assignment = "'forged'" if axis == "actionability" else "'{\"source\":\"forged\"}'::jsonb"
            with pytest.raises(DBAPIError, match="replay|authority|immutable"):
                async with db_session.begin_nested():
                    await db_session.execute(text(f"UPDATE {table} SET {axis}={assignment} WHERE memory_id=:memory"),
                                             {"memory": result["memory_id"]})
    await db_session.rollback()
