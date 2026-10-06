import json

import pytest
from sqlalchemy import text

from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_reducer import reduce_events
from tests.integration.consolidation_commit_fixtures import commit, prepared


@pytest.mark.asyncio
async def test_every_prefix_python_sql_parity_and_inside_group_has_no_partial_effects(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner, count=2)
    result = await commit(fixture)
    assert result.status == 'completed'
    events = await MemoryEventStore(db_session).replay(fixture[2].scope_id)
    for index, event in enumerate(events):
        state = reduce_events(events[:index + 1])
        sql = await db_session.scalar(text('SELECT memory_log_state(:scope,:event)'),
            {'scope': fixture[2].scope_id, 'event': event['event_id']})
        assert sql == json.loads(json.dumps(state.export()))
        if event['event_type'] == 'consolidate' and event['payload']['effect_index'] < event['payload']['effect_count'] - 1:
            assert not state['consolidation_state']['potential_source_outcomes']


@pytest.mark.asyncio
async def test_group_retry_is_stable_and_has_unique_root(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner, count=2)
    first = await commit(fixture)
    second = await commit(fixture)
    assert first.status == second.status == 'completed'
    assert first.output_memory_ids == second.output_memory_ids
    assert first.output_event_ids == second.output_event_ids
