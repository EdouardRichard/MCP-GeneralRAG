"""Archive/truncation and rollback must remain one reproducible trajectory."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from rag_mcp.models.memory_history import MemoryArchive, MemorySnapshot
from rag_mcp.runtime.projection_rebuild import MemoryHistory, ProjectionRebuilder, SNAPSHOT_VIEWS
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_reducer import projection_fingerprint, reduce_events
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
async def test_archived_assert_then_correction_and_repeated_rollback_preserve_six_views(db_session):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    original = await service.record({**payload, "evidence_refs": ["123"]})
    first_id = original["memory_id"]
    usage = await service.govern("access", scope_id=sid, memory_id=first_id, actor="management", reason="before archive")
    history = MemoryHistory(service)
    checkpoint = await history.capture(sid, force=True)
    archived = await history.archive(sid, now=datetime.now(timezone.utc) + timedelta(days=91))
    assert archived["assert_count"] == 1 and archived["access_count"] == 1
    assert await MemoryEventStore(db_session).replay_online(sid) == []
    correction = await service.record({**payload, "content": "A correction after online truncation.",
        "evidence_refs": ["123"], "supersedes_memory_id": first_id})
    await service.govern("access", scope_id=sid, memory_id=correction["memory_id"], actor="management", reason="post-point access")
    rollback = await service.govern("rollback", scope_id=sid, event_point=first_id, actor="management", reason="restore archived identity")
    restored = (await history.load(sid)).state
    assert restored["entries"][first_id]["status"] == "active"
    assert restored["salience"][first_id]["access_count"] == 1
    assert restored["salience"][correction["memory_id"]]["access_count"] == 1
    assert all(restored[key] for key in SNAPSHOT_VIEWS.values()), "each business projection must contain real data"
    events = await MemoryEventStore(db_session).replay(sid)
    full = reduce_events(events)
    assert projection_fingerprint(restored) == projection_fingerprint(full)
    for name, key in SNAPSHOT_VIEWS.items():
        assert projection_fingerprint(restored[key]) == projection_fingerprint(full[key]), name
    report = await service.rebuild(sid, actor="management")
    assert all(row["matches_replay"] for row in report.values())
    twice = await service.govern("rollback", scope_id=sid, event_point=correction["memory_id"], actor="management", reason="restore pre-rollback correction")
    current = await service.recall(scope_ref=[str(sid)])
    assert [row["memory_id"] for row in current["memories"]] == [correction["memory_id"]]
    await service.govern("rollback", scope_id=sid, event_point=rollback["event_id"], actor="management", reason="replay an earlier rollback")
    current = await service.recall(scope_ref=[str(sid)])
    assert [row["memory_id"] for row in current["memories"]] == [first_id]
    all_events = await MemoryEventStore(db_session).replay(sid)
    assert any(event["event_id"] == usage["event_id"] for event in all_events)
    assert any(event["event_id"] == twice["event_id"] for event in all_events)
    damaged = {**checkpoint, "fingerprints": {**checkpoint["fingerprints"], "file": "corrupt"}}
    recovered = ProjectionRebuilder().rebuild(all_events, snapshot=damaged)
    assert recovered.source == "full_log"
    assert recovered.fingerprint == projection_fingerprint(reduce_events(all_events))
    assert all(row["matches_replay"] for row in (await service.rebuild(sid, actor="management")).values())


@pytest.mark.asyncio
async def test_persisted_corrupt_snapshot_falls_back_but_corrupt_archive_fails_closed(db_session):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    await service.record(payload)
    history = MemoryHistory(service)
    await history.capture(sid, force=True)
    archived = await history.archive(sid, now=datetime.now(timezone.utc) + timedelta(days=91))
    from rag_mcp.utils.snowflake import generate_id
    await service.record({**payload, "content": "An incremental identity after the archived checkpoint."})
    events = await MemoryEventStore(db_session).replay(sid)
    db_session.add(MemorySnapshot(snapshot_id=generate_id(), knowledge_scope_id=sid,
        covered_through_event_id=events[-1]["event_id"], payload={"status": "corrupt"}, fingerprint="0" * 64))
    await db_session.commit()
    assert (await history.load(sid)).source == "full_log"
    archive = await db_session.get(MemoryArchive, archived["archive_id"])
    path = Path(archive.path)
    original = path.read_bytes()
    try:
        path.write_bytes(b"corrupt archive")
        with pytest.raises(ValueError, match="MEMORY_WRITE_UNAVAILABLE.*archive"):
            await service.rebuild(sid, actor="management")
    finally:
        path.write_bytes(original)
        await db_session.rollback()
    assert all(row["matches_replay"] for row in (await service.rebuild(sid, actor="management")).values())


@pytest.mark.asyncio
async def test_snapshot_and_rebuild_report_actual_schema_projection_and_index_versions(db_session):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    await service.record({**payload, "evidence_refs": ["123"]})
    snapshot = await MemoryHistory(service).capture(sid, force=True)
    manifest = await service.projections.current(sid)
    assert snapshot["schema_version"] == 1
    assert snapshot["index_version"] == manifest.payload["collection"]
    assert set(snapshot["projection_versions"]) == set(SNAPSHOT_VIEWS)
    from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
    registry = (await db_session.execute(select(MemoryProjectionMeta).where(
        MemoryProjectionMeta.knowledge_scope_id == sid,
        MemoryProjectionMeta.source_event_id == manifest.source_event_id,
        MemoryProjectionMeta.projection_type.in_(SNAPSHOT_VIEWS)))).scalars().all()
    assert snapshot["projection_versions"] == {row.projection_type: row.projection_version for row in registry}
    assert all(snapshot["projection_versions"].values())
    report = await service.rebuild(sid, actor="management")
    for name, row in report.items():
        assert row["schema_version"] == snapshot["schema_version"]
        assert row["projection_version"] == snapshot["projection_versions"][name]
        assert row["matches_replay"]
    assert report["dense"]["index_version"] == snapshot["index_version"]
