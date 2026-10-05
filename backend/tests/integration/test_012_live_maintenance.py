from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import gzip

import pytest
from sqlalchemy import select, func

from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.models.memory_recall_run import MemoryRecallRun
from rag_mcp.models.session import MemorySession
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
async def test_writer_maintenance_compresses_archives_and_tombstones_only_expired_memory(db_session):
    import rag_mcp.services.maintenance_service as module
    maintain = getattr(module, "run_memory_maintenance", None)
    assert callable(maintain), "memory lifecycle is not connected to writer maintenance"
    sid, payload = await scope_and_payload(db_session)
    seed = await db_session.get(DomainProfile, "generic")
    key = f"maintenance-{uuid4()}"
    db_session.add(DomainProfile(domain_key=key, name=key, supported_formats=["markdown"],
        graph_relations={}, default_capabilities={}, memory_policy={**seed.memory_policy, "episodic_ttl_days": 0}))
    await db_session.flush()
    (await db_session.get(KnowledgeScope, sid)).domain_key = key
    await db_session.commit()
    service = MemoryService(db_session)
    expired = await service.record({**payload, "kind": "episodic", "content": "Historical task. " * 200})
    eternal = await service.record({**payload, "content": "This procedure has no expiry."})
    for stage in ("compressed", "archived", "tombstone"):
        result = await maintain(db_session, scope_ids=[sid], service=service)
        entry = await db_session.get(MemoryEntry, expired["memory_id"], populate_existing=True)
        assert entry.retention_stage == stage
        assert result[stage] == 1
        assert (await db_session.get(MemoryEntry, eternal["memory_id"])).status == "active"
        manifest = await service.projections.current(sid)
        files = [row for row in manifest.payload["state"]["files"].values() if row["memory_id"] == expired["memory_id"]]
        if stage != "tombstone":
            assert len(files) == 1 and files[0]["path"].endswith(".gz")
            path = Path(manifest.payload["root"]) / str(sid) / str(manifest.source_event_id) / files[0]["path"]
            assert gzip.decompress(path.read_bytes()).decode("utf-8") == files[0]["body"]
            assert path.stat().st_size < len(files[0]["body"].encode("utf-8"))
        else:
            assert files == [] and entry.status == "retired"
        assert all(row["matches_replay"] for row in (await service.inspect_projections(sid)).values())
    events = (await db_session.execute(select(MemoryEvent).where(MemoryEvent.knowledge_scope_id == sid))).scalars().all()
    assert len(events) == 5
    assert [event.payload["retention_stage"] for event in events if event.event_type == "grant"] == ["compressed", "archived", "tombstone"]
    assert (await service.recall(scope_ref=[str(sid)]))["memories"][0]["memory_id"] == eternal["memory_id"]


@pytest.mark.asyncio
async def test_memory_runtime_ttl_purges_only_expired_audits_and_sessions(db_session):
    import rag_mcp.services.maintenance_service as module
    purge = getattr(module, "purge_expired_memory_runtime", None)
    assert callable(purge), "7-day memory runtime TTL is missing"
    sid, _ = await scope_and_payload(db_session)
    now = datetime.now(timezone.utc)
    old_id, live_id = str(uuid4()), str(uuid4())
    db_session.add_all([MemoryRecallRun(request_id=identifier, tool="recall_memory", mode="timeline", scope_ids=[sid],
        expires_at=expiry) for identifier, expiry in ((old_id, now-timedelta(days=1)), (live_id, now+timedelta(days=1)))])
    db_session.add_all([MemorySession(session_id=identifier, primary_scope_id=sid, agent_id="acceptance", status="active",
        expires_at=expiry) for identifier, expiry in ((old_id, now-timedelta(days=1)), (live_id, now+timedelta(days=1)))])
    await db_session.commit()
    before = await db_session.scalar(select(func.count()).select_from(MemoryEvent))
    result = await purge(db_session, now=now)
    await db_session.commit()
    assert result["audits"] >= 1 and result["sessions"] >= 1
    assert await db_session.get(MemoryRecallRun, old_id, populate_existing=True) is None
    assert await db_session.get(MemorySession, old_id, populate_existing=True) is None
    assert await db_session.get(MemoryRecallRun, live_id, populate_existing=True) is not None
    assert await db_session.get(MemorySession, live_id, populate_existing=True) is not None
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent)) == before


@pytest.mark.asyncio
async def test_retention_history_invalid_transition_and_rollback(db_session):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    memory = await service.record(payload)
    original = await service.projections.current(sid)
    as_of = original.payload["state"]["entries"][str(memory["memory_id"])]["valid_from"]
    command = dict(scope_id=sid, memory_id=memory["memory_id"], actor="management", reason="retention acceptance")
    before = await db_session.scalar(select(func.count()).select_from(MemoryEvent).where(MemoryEvent.knowledge_scope_id == sid))
    with pytest.raises(ValueError, match="invalid retention transition"):
        await service.govern("lifecycle", **command, retention_stage="archived")
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent).where(MemoryEvent.knowledge_scope_id == sid)) == before
    await db_session.rollback()
    await service.govern("lifecycle", **command, retention_stage="compressed")
    await service.govern("lifecycle", **command, retention_stage="archived")
    assert (await service.recall(scope_ref=[str(sid)]))["memories"] == []
    assert (await service.start_work(scope_ref=str(sid)))["digest"]["memories"] == []
    historic = await service.recall(scope_ref=[str(sid)], memory_ids=[memory["memory_id"]], as_of=as_of)
    assert [row["memory_id"] for row in historic["memories"]] == [memory["memory_id"]]
    await service.govern("rollback", scope_id=sid, event_point=memory["memory_id"], actor="management", reason="restore prior retention")
    entry = await db_session.get(MemoryEntry, memory["memory_id"], populate_existing=True)
    assert entry.retention_stage == "active" and entry.content_text == payload["content"]
    assert [row["memory_id"] for row in (await service.recall(scope_ref=[str(sid)]))["memories"]] == [memory["memory_id"]]
    assert all(item["matches_replay"] for item in (await service.inspect_projections(sid)).values())
