import pytest

from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_reducer import projection_fingerprint, reduce_events
from tests.integration.consolidation_commit_fixtures import commit, prepared


@pytest.mark.asyncio
async def test_nonempty_context_full_and_delta_replay_rebuild_all_six_outputs(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner, count=2)
    service, _runtime, token, *_ = fixture
    result = await commit(fixture)
    assert result.status == 'completed'
    events = await MemoryEventStore(db_session).replay(token.scope_id)
    full = reduce_events(events)
    split = next(i for i, e in enumerate(events) if e['event_type'] == 'consolidate')
    delta = reduce_events(events[split:], initial_state=reduce_events(events[:split]))
    assert projection_fingerprint(full) == projection_fingerprint(delta)
    assert all(full['entries'][mid]['context_digest'] for mid in result.output_memory_ids)
    await db_session.rollback()
    rebuilt = await service.rebuild(token.scope_id, actor='management')
    assert len(rebuilt) == 6 and all(row['matches_replay'] for row in rebuilt.values())
