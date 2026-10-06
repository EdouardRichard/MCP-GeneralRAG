from datetime import UTC, datetime

import pytest
from jsonschema import ValidationError
from sqlalchemy import select

from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch, thaw
from rag_mcp.services.consolidation_adjudicator import adjudicate_batch
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_policy import MemoryPolicy
from rag_mcp.services.memory_reducer import reduce_events
from tests.integration.consolidation_commit_fixtures import commit, prepared
from tests.unit.consolidation_cases import VOCAB


@pytest.mark.asyncio
async def test_approved_output_dependency_links_are_typed_and_atomic(db_session, memory_writer_owner):
    fixture = list(await prepared(db_session, memory_writer_owner, count=2, shared=False))
    service, runtime, token, batch, context, _ = fixture
    from rag_mcp.models.domain_profile import DomainProfile
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    profile = await db_session.get(DomainProfile, (await db_session.get(KnowledgeScope, token.scope_id)).domain_key)
    profile.memory_link_vocabulary = thaw(VOCAB)
    await db_session.commit()
    proposals = thaw(batch.proposals)
    proposals[1]['link_suggestions'] = [{'from_ref': {'local': 'output'}, 'to_ref': {'proposal_ref': 'p0'},
        'relation_type': 'related', 'description': 'Approved dependency', 'confidence': .9}]
    batch = ProposalBatch(proposals)
    current = await runtime.read_snapshot(token.scope_id)
    decisions = adjudicate_batch(batch, current, MemoryPolicy.model_validate(thaw(context.window.policy)), current.vocabulary,
        {'count': current.quota_count, 'limit': 5000}, context, datetime.now(UTC))
    assert len(decisions.groups) == 1
    await db_session.rollback()
    fixture[3], fixture[5] = batch, decisions
    result = await commit(fixture)
    assert result.status == 'completed'
    from rag_mcp.models.memory_link import MemoryLink
    links = (await db_session.execute(select(MemoryLink).where(MemoryLink.knowledge_scope_id == token.scope_id,
        MemoryLink.revision_id == max(result.output_event_ids)))).scalars().all()
    assert len(links) == 1
    edge = links[0]
    assert edge.provenance == 'llm_proposed' and edge.confidence == .9 and edge.created_by_run == token.run_id
    assert edge.from_id == str(edge.data['from_id']) and edge.to_id == str(edge.data['to_id'])
    assert all(row['matches_replay'] for row in (await service.inspect_projections(token.scope_id)).values())


@pytest.mark.asyncio
async def test_rollback_restores_context_consumption_and_gives_new_state_version(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner)
    service, runtime, token, _batch, context, _ = fixture
    result = await commit(fixture)
    assert result.status == 'completed'
    rollback = await service.govern('rollback', scope_id=token.scope_id, actor='management', reason='Restore approved prefix',
                                   event_point=context.window.window_id)
    current = await runtime.read_snapshot(token.scope_id)
    source = current.entries[context.window.input_episode_refs[0].memory_id]
    assert source['state_event_id'] == rollback['event_id']
    assert source['source_event_id'] == context.window.input_episode_refs[0].source_event_id
    assert not current.consolidation_state['potential_source_outcomes']
    assert all(v['rolled_back'] for v in current.consolidation_state['potential_results'].values())
    assert current.entries[result.output_memory_ids[0]]['status'] == 'retired'


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['missing_member', 'foreign_group', 'wrong_aggregate', 'confidence', 'lineage', 'body'])
async def test_group_payload_tampering_fails_python_or_sql_before_publication(db_session, memory_writer_owner, case):
    fixture = await prepared(db_session, memory_writer_owner)
    assert (await commit(fixture)).status == 'completed'
    events = await MemoryEventStore(db_session).replay(fixture[2].scope_id)
    v2 = [e for e in events if e['event_type'] == 'consolidate']
    if case == 'missing_member':
        state = reduce_events(events[:-1])
        assert v2[0]['aggregate_id'] not in state['entries']
        assert not state['consolidation_state']['potential_source_outcomes']
        return
    if case == 'foreign_group':
        v2[0]['payload']['source_outcomes'][0]['required_group_key'] = 'f' * 64
    elif case == 'wrong_aggregate':
        v2[0]['aggregate_id'] += 1
    elif case == 'confidence':
        v2[0]['payload']['inference_meta']['confidence'] = .99
    elif case == 'lineage':
        v2[0]['payload']['source_lineage'] = []
    else:
        v2[0]['payload']['content_text'] = 'forged body'
    with pytest.raises((ValueError, KeyError, TypeError, ValidationError)):
        reduce_events(events)


@pytest.mark.asyncio
async def test_pipeline_injected_provider_runs_without_transaction_and_observes_committed_ids(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner)
    _service, runtime, token, batch, context, _ = fixture
    from rag_mcp.orchestration.consolidation_pipeline import run_pipeline
    async def selector(token):
        return context.window
    async def proposer(*args, **kwargs):
        assert not db_session.in_transaction()
        return batch
    result = await run_pipeline(runtime, token, distiller=None, select=selector, propose_stage=proposer)
    assert result.status == 'completed'
    observation = await runtime.latest_observation(token.run_id)
    assert observation.status == 'succeeded'
    assert observation.output_memory_ids == list(result.output_memory_ids)
    assert observation.adjudications and observation.provider_usage['cost_usd'] is None


@pytest.mark.asyncio
async def test_ordinary_materializer_requires_real_fence_for_retained_consolidation(db_session, memory_writer_owner, monkeypatch):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, *_ = fixture
    original = service.projections._materialize_dense
    async def fail(*args, **kwargs):
        raise RuntimeError('pending external materialization')
    monkeypatch.setattr(service.projections, '_materialize_dense', fail)
    assert (await commit(fixture)).status == 'pending'
    monkeypatch.setattr(service.projections, '_materialize_dense', original)
    events = await MemoryEventStore(db_session).replay(token.scope_id)
    with pytest.raises((PermissionError, ValueError), match='CONSOLIDATION'):
        await service.projections.materialize(reduce_events(events), token.scope_id, events[-1]['event_id'], final_fence=lambda: None)
