from rag_mcp.services.memory_reducer import reduce_events


def test_aoep_invariants_authority_scope_deletion_provenance_rollback():
    state = reduce_events([{ "event_id": 1, "event_type": "assert", "aggregate_id": 1, "knowledge_scope_id": 1, "payload": {"provenance": "hard", "evidence_refs": ["e"]}}, {"event_id": 2, "event_type": "retract", "aggregate_id": 1, "knowledge_scope_id": 1, "payload": {}}])
    entry = state["entries"][1]
    assert entry["status"] == "retired"
    assert entry["knowledge_scope_id"] == 1
    assert entry["evidence_refs"] == ["e"]


import pytest
from sqlalchemy import select, func
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
@pytest.mark.parametrize("forbidden", ["raw_event", "untrusted_rollback"])
async def test_authority_monotonicity_forbidden_commands_never_append(db_session, forbidden):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    first = await service.record(payload)
    before = await service.projections.current(sid)
    fingerprint = before.fingerprint
    with pytest.raises(PermissionError):
        if forbidden == "raw_event":
            await service.apply_event({"knowledge_scope_id": sid, "event_type": "assert", "payload": {"provenance": "hard"}})
        else:
            await service.govern("rollback", scope_id=sid, event_point=first["memory_id"], actor="mcp", reason="untrusted command")
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent).where(MemoryEvent.knowledge_scope_id == sid)) == 1
    assert (await service.projections.current(sid)).fingerprint == fingerprint


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["retire", "rollback"])
async def test_scope_expansion_rejects_foreign_identity(db_session, command):
    a, payload = await scope_and_payload(db_session)
    b, _ = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    first = await service.record(payload)
    params = {"memory_id" if command == "retire" else "event_point": first["memory_id"]}
    with pytest.raises(PermissionError):
        await service.govern(command, scope_id=b, actor="management", reason="foreign identity", **params)
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent).where(MemoryEvent.knowledge_scope_id == b)) == 0
    assert (await service.recall(scope_ref=[str(b)], memory_ids=[first["memory_id"]]))["memories"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["retire", "purge"])
async def test_deletion_propagates_to_all_consumable_views_without_losing_log(db_session, action):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    first = await service.record(payload)
    await service.govern(action, scope_id=sid, memory_id=first["memory_id"], actor="management", reason="deletion propagation")
    manifest = await service.projections.current(sid)
    state = manifest.payload["state"]
    assert state["entries"][str(first["memory_id"])]["status"] == "retired"
    assert all(not state[key] for key in ("dense", "links", "summary", "files"))
    assert await db_session.get(MemoryEvent, first["memory_id"]) is not None
    assert all(row["matches_replay"] for row in (await service.inspect_projections(sid)).values())
    assert (await service.recall(scope_ref=[str(sid)]))["memories"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["access", "retire"])
async def test_provenance_preserved_across_state_transitions(db_session, action):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    first = await service.record(payload)
    manifest = await service.projections.current(sid)
    original = manifest.payload["state"]["entries"][str(first["memory_id"])]
    await service.govern(action, scope_id=sid, memory_id=first["memory_id"], actor="management", reason="preserve attribution")
    current = (await service.projections.current(sid)).payload["state"]["entries"][str(first["memory_id"])]
    for field in ("content_text", "provenance", "confidence", "inference_meta", "evidence_refs", "provenance_validation"):
        assert current[field] == original[field]
    assert all(row["matches_replay"] for row in (await service.inspect_projections(sid)).values())


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["event", "time"])
async def test_rollback_is_traceable_and_keeps_access_events(db_session, target):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    first = await service.record(payload)
    initial = await db_session.get(MemoryEvent, first["memory_id"])
    point = initial.occurred_at
    second = await service.record({**payload, "content": "Correction", "supersedes_memory_id": first["memory_id"]})
    accessed = await service.govern("access", scope_id=sid, memory_id=second["memory_id"], actor="management", reason="observed read")
    parameters = {"event_point": first["memory_id"]} if target == "event" else {"time_point": point}
    rollback = await service.govern("rollback", scope_id=sid, actor="management", reason="human rollback", **parameters)
    event = await db_session.get(MemoryEvent, rollback["event_id"])
    assert event.event_type == "rollback" and event.request_id == rollback["request_id"]
    assert event.payload["reason"] == "human rollback"
    assert all(event.payload[field] == rollback[field] for field in ("before_fingerprint", "after_fingerprint", "impact"))
    assert await db_session.get(MemoryEvent, accessed["event_id"]) is not None
    assert [row["memory_id"] for row in (await service.recall(scope_ref=[str(sid)]))["memories"]] == [first["memory_id"]]
    assert all(row["matches_replay"] for row in (await service.inspect_projections(sid)).values())

