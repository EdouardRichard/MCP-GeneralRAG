"""Read actual completed PG projections and actual BGE/Qdrant candidates."""
import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_recall_run import MemoryRecallRun
from rag_mcp.models.session import MemorySession
from rag_mcp.indexing.memory_vectors import revision_point_id
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.utils.snowflake import generate_id


async def scope_and_payload(session):
    identifier = generate_id()
    scope = KnowledgeScope(scope_id=identifier, name=f"reader-{uuid4()}",
                           slug=f"reader-{identifier}", scope_type="project", domain_key="generic")
    session.add(scope)
    await session.commit()
    return identifier, {"scope_id": identifier, "kind": "procedural", "content": "Use an explicit scope for each memory request.",
        "provenance": "soft", "inference_meta": {"source": "012 reader acceptance", "confidence": .8,
        "model_version": "acceptance-v1", "time": datetime.now(timezone.utc).isoformat(), "supporting_evidence": []}}


def require_reader(service):
    assert callable(getattr(service, "recall", None)), "real persisted recall is missing"
    assert callable(getattr(service, "start_work", None)), "real persisted work package is missing"


@pytest.mark.asyncio
async def test_pg_modes_history_scope_and_delivered_are_real(db_session, monkeypatch):
    service = MemoryService(db_session)
    require_reader(service)
    sid, payload = await scope_and_payload(db_session)
    first = await service.record(payload)
    original = await service.projections.current(sid)
    as_of = original.payload["state"]["entries"][str(first["memory_id"])]["valid_from"]
    second = await service.record({**payload, "content": "Always keep the requested scope explicit.",
                                   "supersedes_memory_id": first["memory_id"], "agent_id": "reader-agent"})
    def forbidden(*args, **kwargs):
        pytest.fail("a PG-only request accessed Qdrant")
    monkeypatch.setattr(service.projections.qdrant._client, "query_points", forbidden)
    result = await service.recall(scope_ref=[str(sid)], memory_ids=[second["memory_id"], first["memory_id"]], include_superseded=True)
    assert [row["memory_id"] for row in result["memories"]] == [second["memory_id"], first["memory_id"]]
    assert result["counts"]["mode"] == "by_id"
    historic = await service.recall(scope_ref=[str(sid)], as_of=as_of, include_superseded=True)
    assert [row["memory_id"] for row in historic["memories"]] == [first["memory_id"]]
    current = await service.recall(scope_ref=[str(sid)], agent_id="reader-agent")
    assert [row["memory_id"] for row in current["memories"]] == [second["memory_id"]]
    assert current["counts"]["mode"] == "filtered"
    other, _ = await scope_and_payload(db_session)
    isolated = await service.recall(scope_ref=[str(other)], memory_ids=[second["memory_id"]])
    assert isolated["completion_status"] == "no_evidence" and isolated["memories"] == []
    with pytest.raises(ValueError, match="MEMORY_IDS_QUERY_CONFLICT"):
        await service.recall(scope_ref=[str(sid)], query="scope", memory_ids=[second["memory_id"]])
    session_id = str(uuid4())
    delivered = await service.recall(scope_ref=[str(sid)], session_id=session_id, include_delivered=False)
    assert delivered["memories"] == []  # session filter is never relaxed
    session_payload = {**payload, "content": "Session-scoped procedure", "session_id": session_id}
    session_memory = await service.record(session_payload)
    one = await service.recall(scope_ref=[str(sid)], session_id=session_id)
    two = await service.recall(scope_ref=[str(sid)], session_id=session_id)
    assert [row["memory_id"] for row in one["memories"]] == [session_memory["memory_id"]]
    assert two["completion_status"] == "no_evidence" and two["counts"]["dropped_delivered"] == 1
    again = await service.recall(scope_ref=[str(sid)], session_id=session_id, include_delivered=True)
    assert [row["memory_id"] for row in again["memories"]] == [session_memory["memory_id"]]
    audit = await db_session.get(MemoryRecallRun, one["request_id"])
    assert audit.scope_ids == [sid] and audit.returned_count == 1


@pytest.mark.asyncio
async def test_real_semantic_status_staleness_and_filter_intersection(db_session, monkeypatch):
    service = MemoryService(db_session)
    require_reader(service)
    sid, payload = await scope_and_payload(db_session)
    memory = await service.record(payload)
    manifest = await service.projections.current(sid)
    await asyncio.to_thread(service.projections.qdrant._client.set_payload,
        collection_name=manifest.payload["collection"], points=[revision_point_id(sid, manifest.source_event_id, memory["memory_id"])], payload={"status": "retired"})
    original = service.projections.qdrant._client.query_points
    calls = []
    def observed(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(service.projections.qdrant._client, "query_points", observed)
    result = await service.recall(scope_ref=[str(sid)], query="explicit memory scope")
    assert [row["memory_id"] for row in result["memories"]] == [memory["memory_id"]]
    assert calls[0]["limit"] >= 40
    filters = calls[0]["query_filter"].model_dump_json()
    assert "knowledge_scope_id" in filters and str(sid) in filters and "status" not in filters
    assert result["memories"][0]["match"]["dense_similarity"] is not None
    assert "relevance_score" not in result["memories"][0]
    empty = await service.recall(scope_ref=[str(sid)], query="explicit scope", agent_id="absent")
    assert empty["completion_status"] == "no_evidence" and empty["memories"] == []
    def unavailable(**kwargs):
        raise OSError("Qdrant unavailable")
    monkeypatch.setattr(service.projections.qdrant._client, "query_points", unavailable)
    partial = await service.recall(scope_ref=[str(sid)], query="scope")
    assert partial["completion_status"] == "partial"
    assert partial["memory_notice"]["failed_paths"] == ["dense_unavailable"]
    assert [row["memory_id"] for row in partial["memories"]] == [memory["memory_id"]]
    still_empty = await service.recall(scope_ref=[str(sid)], query="scope", agent_id="absent")
    assert still_empty["memories"] == []


@pytest.mark.asyncio
async def test_failed_revision_is_not_consumed_and_package_is_stable_read_only(db_session, monkeypatch):
    service = MemoryService(db_session)
    require_reader(service)
    sid, payload = await scope_and_payload(db_session)
    first = await service.record(payload)
    async def unavailable(*args, **kwargs):
        raise OSError("injected file failure")
    monkeypatch.setattr(service.projections, "_materialize_files", unavailable)
    with pytest.raises(ValueError, match="MEMORY_WRITE_UNAVAILABLE"):
        await service.record({**payload, "content": "Pending replacement must stay hidden.", "supersedes_memory_id": first["memory_id"]})
    recall = await service.recall(scope_ref=[str(sid)])
    assert [row["memory_id"] for row in recall["memories"]] == [first["memory_id"]]
    assert recall["completion_status"] == "partial"
    assert recall["memory_notice"]["failed_paths"] == ["files"]
    before = await db_session.scalar(select(func.count()).select_from(MemoryEvent))
    sessions = await db_session.scalar(select(func.count()).select_from(MemorySession))
    for mode, budget in (("standard", 2000), ("compact", 800), ("minimal", 300)):
        one = await service.start_work(scope_ref=str(sid), budget=mode)
        two = await service.start_work(scope_ref=str(sid), budget=mode)
        assert one.pop("request_id") != two.pop("request_id")
        assert one == two
        assert one["read_guidance"] and one["package_fingerprint"]
        assert all(isinstance(one[key], dict) for key in ("scope", "domain_brief", "digest", "working_set"))
        assert one["counts"]["characters"] <= budget
        assert "Pending replacement" not in json.dumps(one)
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent)) == before
    assert await db_session.scalar(select(func.count()).select_from(MemorySession)) == sessions
    old_package = await service.start_work(scope_ref=str(sid))
    monkeypatch.undo()
    await service.rebuild(sid, actor="management")
    new_package = await service.start_work(scope_ref=str(sid))
    assert old_package["package_fingerprint"] != new_package["package_fingerprint"]


@pytest.mark.asyncio
async def test_nonsemantic_reads_never_construct_vector_client(db_session, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("nonsemantic read constructed a network vector client")
    monkeypatch.setattr("rag_mcp.services.memory_service.QdrantStore", forbidden)
    sid, _ = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    assert (await service.recall(scope_ref=[str(sid)]))["completion_status"] == "no_evidence"
    assert (await service.start_work(scope_ref=str(sid)))["counts"]["returned"] == 0


@pytest.mark.asyncio
async def test_dense_timeout_returns_filtered_partial_inside_recall_budget(db_session, monkeypatch):
    from time import monotonic
    service = MemoryService(db_session)
    sid, payload = await scope_and_payload(db_session)
    memory = await service.record(payload)
    async def blocked(query):
        await asyncio.sleep(10)
    monkeypatch.setattr(service.projections.embedding, "embed_query", blocked)
    started = monotonic()
    result = await service.recall(scope_ref=[str(sid)], query="scope", kind="procedural")
    assert monotonic() - started < 3
    assert result["completion_status"] == "partial"
    assert [row["memory_id"] for row in result["memories"]] == [memory["memory_id"]]
