from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, func

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload
from rag_mcp.utils.snowflake import generate_id


@pytest.mark.asyncio
async def test_batch_append_sets_reducer_role_once_and_rolls_back_invalid_batch(db_session, monkeypatch):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    memory = await service.record(payload)
    original = db_session.execute
    role_changes = []
    async def observed(statement, *args, **kwargs):
        if str(statement) == "SET LOCAL ROLE rag_memory_reducer":
            role_changes.append(statement)
        return await original(statement, *args, **kwargs)
    monkeypatch.setattr(db_session, "execute", observed)
    def event(kind="access"):
        identifier = generate_id()
        return MemoryEvent(event_id=identifier, aggregate_id=memory["memory_id"], knowledge_scope_id=sid,
            event_type=kind, payload={}, actor="management", request_id=str(identifier),
            occurred_at=datetime.now(timezone.utc), authority={}, scope_meta={}, mutability={},
            provenance_meta={}, recoverability={}, actionability="audit")
    batch = [event() for _ in range(10)]
    store = MemoryEventStore(db_session)
    await store.append_many(batch)
    await db_session.commit()
    assert len(role_changes) == 1, "one database role roundtrip per event stalls large history tests"
    assert len(await store.replay(sid)) == 11
    with pytest.raises(ValueError, match="MEMORY_KIND_INVALID"):
        await store.append_many([event(), event("assert")])
    assert len(await store.replay(sid)) == 11
    await db_session.rollback()
    await service.rebuild(sid, actor="management")


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
    report = await service.rebuild(sid, actor="management")
    assert all(row.get("recovery_source") == "snapshot_delta" for row in report.values()), "management rebuild ignored its verified snapshot"
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


@pytest.mark.asyncio
@pytest.mark.parametrize("reference_form", ["numeric", "prefixed"])
async def test_archive_preserves_every_accepted_distilled_source_reference(db_session, reference_form):
    from rag_mcp.runtime.projection_rebuild import MemoryHistory
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    source = await service.record(payload)
    reference = str(source["memory_id"])
    if reference_form == "prefixed":
        reference = "memory:" + reference
    distilled = await service.record({**payload, "content": "A distilled procedure with a retained source.",
        "provenance": "distilled", "inference_meta": {**payload["inference_meta"], "supporting_evidence": [reference]}})
    assert distilled["provenance_validation"]["attributions"][0]["source_chain"]["validated"]
    history = MemoryHistory(service)
    await history.capture(sid, force=True)
    await history.archive(sid, now=datetime.now(timezone.utc) + timedelta(days=91))
    online = await MemoryEventStore(db_session).replay_online(sid)
    assert any(event["event_id"] == source["memory_id"] for event in online), "an accepted distilled source reference was truncated"
    assert all(row["matches_replay"] for row in (await service.rebuild(sid, actor="management")).values())


@pytest.mark.asyncio
async def test_management_rebuild_uses_verified_snapshot(db_session):
    from rag_mcp.runtime.projection_rebuild import MemoryHistory
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    first = await service.record(payload)
    history = MemoryHistory(service)
    await history.capture(sid, force=True)
    await service.record({**payload, "content": "An incremental memory after the checkpoint."})
    report = await service.rebuild(sid, actor="management")
    assert all(row.get("recovery_source") == "snapshot_delta" for row in report.values())


@pytest.mark.asyncio
async def test_missing_checkpoint_log_cannot_be_declared_complete(db_session, monkeypatch):
    from rag_mcp.runtime.projection_rebuild import MemoryHistory
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    first = await service.record(payload)
    history = MemoryHistory(service)
    await history.capture(sid, force=True)
    await service.record({**payload, "content": "A second independent identity."})
    original = MemoryEventStore.replay
    async def incomplete(store, scope_id, **kwargs):
        return [event for event in await original(store, scope_id, **kwargs) if event["event_id"] != first["memory_id"]]
    monkeypatch.setattr(MemoryEventStore, "replay", incomplete)
    with pytest.raises(ValueError, match="MEMORY_WRITE_UNAVAILABLE|incomplete"):
        await history.load(sid)
