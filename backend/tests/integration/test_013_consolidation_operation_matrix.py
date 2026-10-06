import json
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from sqlalchemy import text

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch, thaw
from rag_mcp.services.consolidation_adjudicator import AdjudicationContext, adjudicate_batch, memory_ref
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_policy import MemoryPolicy
from rag_mcp.services.memory_reducer import reduce_events
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.utils.snowflake import generate_id
from tests.integration.consolidation_commit_fixtures import commit, prepared
from tests.integration.consolidation_fixtures import StableEmbedding, create_scope, recorded_episode
from tests.integration.test_013_consolidation_live_boundaries import anchored


async def assert_each_prefix(session, scope):
    events = await MemoryEventStore(session).replay(scope)
    for index, event in enumerate(events):
        python = reduce_events(events[:index + 1]).export()
        sql = await session.scalar(text('SELECT memory_log_state(:scope,:event)'), {'scope': scope, 'event': event['event_id']})
        assert sql == json.loads(json.dumps(python)), (index, event['event_type'], event['payload'].get('operation'))


@pytest.mark.asyncio
async def test_valid_distinct_body_legacy_flat_create_preserves_replay(db_session):
    scope = await create_scope(db_session)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    original = await recorded_episode(service, scope, 'Exact equivalent observation')
    source_event = await db_session.get(MemoryEvent, original['memory_id'])
    fields = {column.name: deepcopy(getattr(source_event, column.name)) for column in MemoryEvent.__table__.columns
              if column.name != 'created_at'}
    legacy_id = generate_id()
    fields.update(event_id=legacy_id, aggregate_id=legacy_id, request_id='legacy-flat-distinct', event_type='consolidate')
    fields['payload'].update(content_text='A distinct legacy observation',
        content_hash=sha256(b'A distinct legacy observation').hexdigest())
    await MemoryEventStore(db_session).append(MemoryEvent(**fields))
    await db_session.commit()
    await service.rebuild(scope, actor='management')
    state = reduce_events(await MemoryEventStore(db_session).replay(scope))
    assert state['entries'][legacy_id]['source_event_id'] == legacy_id
    assert state['entries'][legacy_id]['content_text'] == 'A distinct legacy observation'
    assert state['entries'][original['memory_id']]['status'] == 'active'
    await assert_each_prefix(db_session, scope)


@pytest.mark.asyncio
async def test_v2_invalidate_published_support_withdrawal_has_no_new_identity(db_session, memory_writer_owner):
    fixture, (_, version, chunk) = await anchored(await prepared(db_session, memory_writer_owner), db_session)
    service, runtime, token, batch, _old_context, _ = fixture
    first = await commit(fixture)
    assert first.status == 'completed'
    assert await runtime.release(token)
    await recorded_episode(service, token.scope_id, 'Independent observation after support withdrawal')
    await db_session.execute(text("UPDATE knowledge_versions SET status='withdrawn' WHERE version_id=:id"), {'id': version})
    await db_session.commit()
    token = await runtime.admit(token.scope_id, trigger='manual')
    window = await runtime.select_and_seal(token)
    current = await runtime.read_snapshot(token.scope_id)
    target = current.entries[first.output_memory_ids[0]]
    from rag_mcp.services.consolidation_commit import read_evidence
    support = await read_evidence(db_session, [str(chunk)])
    context = AdjudicationContext(window=window, support_facts=support, support_versions=support)
    proposal = {'proposal_id': 'r0', 'action': 'invalidate_contradiction', 'confidence': 1., 'evidence_refs': [],
        'justification': 'required published support withdrawn', 'contradiction_basis': 'current authoritative support withdrawal',
        'source_refs': [memory_ref(current.entries[window.input_episode_refs[0].memory_id])],
        'target_ref': memory_ref(target), 'correcting_ref': None}
    batch = ProposalBatch([], deterministic_proposals=[proposal])
    policy = MemoryPolicy.model_validate(thaw(window.policy))
    decisions = adjudicate_batch(batch, current, policy, current.vocabulary, {'count': current.quota_count, 'limit': 5000},
                                 context, datetime.now(UTC))
    assert decisions.groups, [d.reason_codes for d in decisions.decisions]
    await db_session.rollback()
    result = await service.commit_approved(decisions, token, runtime=runtime, batch=batch, context=context)
    assert result.status == 'completed' and not result.output_memory_ids
    current = await runtime.read_snapshot(token.scope_id)
    after = current.entries[first.output_memory_ids[0]]
    assert after['status'] == 'retired' and after['source_event_id'] == target['source_event_id']
    assert after['content_text'] == target['content_text'] and after['provenance'] == 'distilled'
    await assert_each_prefix(db_session, token.scope_id)
