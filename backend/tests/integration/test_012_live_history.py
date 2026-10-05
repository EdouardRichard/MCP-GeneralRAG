from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, func

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload
from rag_mcp.utils.snowflake import generate_id


@pytest.mark.asyncio
async def test_snapshot_10000_cadence_archive_and_corrupt_recovery_use_real_log(db_session):
    import rag_mcp.runtime.projection_rebuild as module
    history_type = getattr(module, "MemoryHistory", None)
    assert history_type is not None, "there is no persisted snapshot/archive implementation"
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    first = await service.record(payload)
    events = []
    now = datetime.now(timezone.utc)
    for index in range(10000):
        identifier = generate_id()
        events.append(MemoryEvent(event_id=identifier, aggregate_id=first["memory_id"], knowledge_scope_id=sid,
            event_type="access", payload={"channel": "acceptance"}, actor="management", request_id=str(identifier), occurred_at=now,
            authority={"source": "management"}, scope_meta={"knowledge_scope_id": sid}, mutability={"facts": "immutable"},
            provenance_meta={"source": "observed_access"}, recoverability={"source": "event_log"}, actionability="audit"))
    await MemoryEventStore(db_session).append_many(events)
    await db_session.commit()
    await service.rebuild(sid, actor="management")
    history = history_type(service)
    snapshot = await history.capture(sid)
    assert snapshot is not None and len(snapshot["source_events"]) == 10001
    assert set(snapshot["fingerprints"]) == {"relation", "dense", "links", "summary", "file", "salience"}
    assert await history.capture(sid) is None
    before = await db_session.scalar(select(func.count()).select_from(MemoryEvent))
    archived = await history.archive(sid, now=now + timedelta(days=91))
    assert archived["access_count"] == 10000
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent)) == before
    online = await MemoryEventStore(db_session).replay_online(sid)
    assert not any(event["event_type"] == "access" for event in online)
    restored = await history.load(sid)
    assert restored.status == "complete" and restored.source == "snapshot_delta"
    assert restored.state["salience"][first["memory_id"]]["access_count"] == 10000
    from rag_mcp.runtime.projection_rebuild import ProjectionRebuilder
    damaged = {**snapshot, "fingerprints": {**snapshot["fingerprints"], "dense": "corrupt"}}
    recovered = ProjectionRebuilder().restore(snapshot=damaged, delta=[], full_events=await MemoryEventStore(db_session).replay(sid))
    assert recovered.source == "full_log" and recovered.fingerprint == restored.fingerprint
    assert all(row["matches_replay"] for row in (await service.rebuild(sid, actor="management")).values())


@pytest.mark.asyncio
async def test_24_hour_snapshot_and_archive_preserve_correction_dependencies(db_session):
    import rag_mcp.runtime.projection_rebuild as module
    history_type = getattr(module, "MemoryHistory", None)
    assert history_type is not None, "there is no persisted snapshot/archive implementation"
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    first = await service.record(payload)
    await service.record({**payload, "content": "Correction dependency", "supersedes_memory_id": first["memory_id"]})
    history = history_type(service)
    assert await history.capture(sid) is None
    snapshot = await history.capture(sid, now=datetime.now(timezone.utc) + timedelta(hours=25))
    assert snapshot is not None
    await history.archive(sid, now=datetime.now(timezone.utc) + timedelta(days=91))
    online = await MemoryEventStore(db_session).replay_online(sid)
    assert any(event["event_id"] == first["memory_id"] for event in online), "correction source was truncated"
