from copy import deepcopy

import pytest

from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_reducer import reduce_events
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
async def test_six_projection_write_verifies_full_authority_once_per_transaction(db_session, monkeypatch):
    sid, payload = await scope_and_payload(db_session)
    original = MemoryEventStore.replay
    observed = []

    async def replay(store, scope, **kwargs):
        result = await original(store, scope, **kwargs)
        if scope == sid:
            observed.append(len(result))
        return result

    monkeypatch.setattr(MemoryEventStore, "replay", replay)
    service = MemoryService(db_session)
    await service.record(payload)
    assert observed.count(1) == 2, "one state construction and one authority validation; adapters must not refetch the full log"
    assert all(row["matches_replay"] for row in (await service.inspect_projections(sid)).values())


@pytest.mark.asyncio
async def test_authority_revalidation_rejects_forged_state_and_does_not_survive_savepoint(db_session, monkeypatch):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    first = await service.record(payload)
    events = await MemoryEventStore(db_session).replay(sid)
    state = reduce_events(events)
    original = MemoryEventStore.replay
    calls = []

    async def replay(store, scope, **kwargs):
        calls.append(scope)
        return await original(store, scope, **kwargs)

    monkeypatch.setattr(MemoryEventStore, "replay", replay)
    async with db_session.begin_nested():
        await service.projections._authorize(state, sid, first["memory_id"])
        await service.projections._authorize(state, sid, first["memory_id"])
    assert calls == [sid]
    await service.projections._authorize(state, sid, first["memory_id"])
    assert calls == [sid, sid], "savepoint authorization must not authorize a different transaction"
    forged = deepcopy(events)
    forged[0]["payload"]["content_text"] = "forged authority"
    with pytest.raises(ValueError, match="immutable log"):
        await service.projections._authorize(reduce_events(forged), sid, first["memory_id"])
