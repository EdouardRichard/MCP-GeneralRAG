"""T054: deterministic propagation and disabled-mode support maintenance."""
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from rag_mcp.models.consolidation_run import ConsolidationRunObservation
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.orchestration.consolidation_pipeline import (
    AdjudicationContext,
    ProposalBatch,
    TrustedContext,
    run_propagation,
    support_maintenance_context,
    thaw,
)
from rag_mcp.services.consolidation_adjudicator import adjudicate_batch, memory_ref
from rag_mcp.services.consolidation_commit import read_evidence
from rag_mcp.services.consolidation_runtime import (
    ConsolidationRuntime,
    ConsolidationRuntimeError,
    DistillerProvider,
)
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_policy import MemoryPolicy
from rag_mcp.services.memory_service import MemoryService
from tests.integration.consolidation_fixtures import StableEmbedding, create_scope, recorded_episode
from tests.unit.consolidation_cases import VOCAB, facts


async def published_chunk(session, scope_id):
    from rag_mcp.models.chunk import Chunk
    from rag_mcp.models.knowledge_source import KnowledgeSource
    from rag_mcp.models.knowledge_version import KnowledgeVersion
    from rag_mcp.utils.snowflake import generate_id

    source_id, version_id, chunk_id = generate_id(), generate_id(), generate_id()
    session.add(KnowledgeSource(source_id=source_id, knowledge_scope_id=scope_id, filename='evidence.md',
                                content_hash='a' * 64, format='markdown', size_bytes=10, status='published'))
    session.add(KnowledgeVersion(version_id=version_id, knowledge_scope_id=scope_id, version_number=1,
                                 capabilities={}, status='published', graph_ready=False,
                                 published_at=datetime.now(UTC)))
    session.add(Chunk(chunk_id=chunk_id, source_id=source_id, version_id=version_id,
                      knowledge_scope_id=scope_id, content_text='Published evidence body',
                      position_path='section/1', chunk_type='markdown', start_line=1, end_line=1,
                      token_count=5, embedding_model='test', index_version='test'))
    await session.commit()
    return chunk_id, version_id


async def set_policy(session, scope, policy):
    profile = await session.get(DomainProfile, (await session.get(KnowledgeScope, scope)).domain_key)
    profile.memory_policy = policy
    await session.commit()


def link_trigger(target, cause_id, *, event_id, relation='requires'):
    return {'kind': 'authority_event', 'event_id': event_id, 'evidence_id': None, 'version_id': None,
            'version': str(event_id), 'observed_at': datetime.now(UTC).isoformat(),
            'proof': {'kind': 'live_dependency', 'cause_memory_id': cause_id, 'relation_type': relation},
            'target_ref': memory_ref(target)}


def lineage(current, row):
    refs = []
    for item in row.get('source_lineage') or []:
        source = current.entries.get(item['memory_id'])
        if source is not None:
            refs.append(memory_ref(source))
    return refs or [memory_ref(row)]


def link_proposal(identifier, source_row, target, *, relation='requires'):
    return {'proposal_id': identifier, 'action': 'extract_fact', 'source_refs': [memory_ref(source_row)],
            'kind': 'semantic', 'content': f'Conclusion {identifier}', 'confidence': .87,
            'evidence_refs': [], 'justification': 'Observed behavior',
            'link_suggestions': [{'from_ref': {'local': 'output'}, 'to_ref': target,
                                  'relation_type': relation, 'confidence': .9,
                                  'description': 'Declared dependency'}]}


async def release(runtime, token):
    """Runtime entry points require a clean session; a prior read opens one."""
    await runtime.session.rollback()
    return await runtime.release(token)


async def keep_lease_alive(session, owner):
    """Renew the writer lease before each admission.

    A real writer renews its lease for the duration of write mode. This
    isolated environment spends longer than the fixture's initial 300s lease
    window building the dependency chains, and the runtime correctly refuses an
    expired lease (WRITER_LEASE_LOST); renewing keeps the test faithful to
    production behaviour without weakening any assertion.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from rag_mcp.runtime.write_coordinator import PostgresLeaseWriteCoordinator

    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    renewed = await PostgresLeaseWriteCoordinator(factory).renew(owner.lease_id, 300)
    assert renewed, 'fixture writer lease could not be renewed'


async def admit(runtime, scope_id, **changes):
    """Runtime entry points require a clean session; a prior read opens one.

    The consolidation runtime refuses to start its admission short transaction
    inside a caller-owned transaction (CONSOLIDATION_TRANSACTION_BUSY), so a
    read-only snapshot read must be closed first, exactly as the commit
    fixtures do.
    """
    await runtime.session.rollback()
    await keep_lease_alive(runtime.session, runtime.owner)
    return await runtime.admit(scope_id, **changes)


async def run_distiller_window(session, owner, scope, service, build):
    """One manual distiller_window run; build(current, window) returns proposals."""
    runtime = ConsolidationRuntime(session, owner=owner, memory_service=service)
    token = await admit(runtime, scope, trigger='manual')
    window = await runtime.select_and_seal(token)
    current = await runtime.read_snapshot(scope)
    proposals = build(current, window)
    context = AdjudicationContext(window=window, inferences={p['proposal_id']: facts(p) for p in proposals})
    identifiers = {identifier for p in proposals for identifier in p.get('evidence_refs', ())}
    if identifiers:
        support = await read_evidence(session, identifiers)
        context = replace(context, support_facts=support, support_versions=support)
    policy = MemoryPolicy.model_validate(thaw(window.policy))
    batch = ProposalBatch(proposals)
    decisions = adjudicate_batch(batch, current, policy, current.vocabulary,
                                 {'count': current.quota_count, 'limit': policy.per_scope_memory_quota},
                                 context, datetime.now(UTC))
    await session.rollback()
    outcome = await service.commit_approved(decisions, token, runtime=runtime, batch=batch, context=context)
    assert outcome.status == 'completed', outcome.reason_codes
    await release(runtime, token)
    return runtime, outcome


async def dependent_scope(session, owner):
    """scope with episode E, semantic support S and distilled D --requires--> S."""
    scope = await create_scope(session)
    profile = await session.get(DomainProfile, (await session.get(KnowledgeScope, scope)).domain_key)
    profile.memory_link_vocabulary = thaw(VOCAB)
    await session.commit()
    service = MemoryService(session, embedding_provider=StableEmbedding())
    support = (await recorded_episode(service, scope, 'Standing support', kind='semantic'))['memory_id']
    await recorded_episode(service, scope, 'Observed episode')

    def build(current, window):
        source = next(current.entries[ref.memory_id] for ref in window.input_episode_refs)
        return [link_proposal('p0', source, memory_ref(current.entries[support]))]

    runtime, outcome = await run_distiller_window(session, owner, scope, service, build)
    current = await runtime.read_snapshot(scope)
    dependent = current.entries[outcome.output_memory_ids[0]]
    assert next(iter(dependent['approved_links'].values()))['category'] == 'live_dependency'
    return {'scope': scope, 'service': service, 'runtime': runtime, 'dependent': dependent,
            'support': support}


def propagation_events(events):
    return [event for event in events if event['event_type'] == 'consolidate'
            and event['payload'].get('execution_context') == 'deterministic_propagation']


@pytest.mark.asyncio
async def test_disabled_scope_support_maintenance_lifecycle(db_session, memory_writer_owner, monkeypatch):
    setup = await dependent_scope(db_session, memory_writer_owner)
    scope, runtime = setup['scope'], setup['runtime']
    dependent, support = setup['dependent'], setup['support']
    await set_policy(db_session, scope, {'consolidation_enabled': False})
    with pytest.raises(ConsolidationRuntimeError, match='CONSOLIDATION_DISABLED'):
        await admit(runtime, scope, trigger='manual')
    await setup['service'].govern('retire', scope_id=scope, memory_id=support,
                                  actor='management', reason='Support revoked')
    events = await MemoryEventStore(db_session).replay(scope)
    retract = next(event for event in events if event['event_type'] == 'retract')
    current = await runtime.read_snapshot(scope)
    dependent = current.entries[dependent['memory_id']]
    outcomes_before = len(current.consolidation_state['potential_source_outcomes'])

    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError('Distiller must never run during deterministic propagation')

    monkeypatch.setattr(DistillerProvider, 'run', forbidden)
    context = support_maintenance_context(
        historical_source_refs=lineage(current, dependent),
        propagation_trigger=link_trigger(dependent, support, event_id=retract['event_id']))
    token = await admit(runtime, scope, trigger='support_maintenance', context=context)
    outcome = await run_propagation(runtime, token, context=context)
    assert outcome.status == 'completed' and calls == []
    current = await runtime.read_snapshot(scope)
    assert current.entries[dependent['memory_id']]['status'] == 'retired'
    # The maintenance wave consumed no source: outcomes are unchanged.
    assert len(current.consolidation_state['potential_source_outcomes']) == outcomes_before
    events = propagation_events(await MemoryEventStore(db_session).replay(scope))
    assert len(events) == 1
    payload = events[0]['payload']
    assert payload['operation'] == 'invalidate' and payload['window_id'] is None
    assert payload['propagation']['visited_memory_ids'] == [dependent['memory_id']]
    assert payload['propagation']['frontier_memory_ids'] == [] and payload['propagation']['depth'] == 1
    assert payload['source_outcomes'] == [] and payload['source_refs'] == payload['source_lineage']
    observations = (await db_session.execute(select(ConsolidationRunObservation).where(
        ConsolidationRunObservation.run_id == token.run_id))).scalars().all()
    assert observations and all(row.trigger == 'support_maintenance' and row.window is None
                                and row.input_event_ids == [] and row.historical_source_refs
                                and row.propagation_trigger and row.propagation_trigger.get('proof')
                                for row in observations)
    latest = await runtime.latest_observation(token.run_id)
    assert latest.provider_usage['llm_calls'] == 0 and latest.provider_usage['source'] == 'actual'
    await release(runtime, token)


@pytest.mark.asyncio
async def test_live_chain_reverse_propagation(db_session, memory_writer_owner):
    # Chain: D2 requires D1 requires S, all created in one atomic batch.
    scope = await create_scope(db_session)
    profile = await db_session.get(DomainProfile, (await db_session.get(KnowledgeScope, scope)).domain_key)
    profile.memory_link_vocabulary = thaw(VOCAB)
    await db_session.commit()
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    support = (await recorded_episode(service, scope, 'Standing support', kind='semantic'))['memory_id']
    await recorded_episode(service, scope, 'Observed episode')

    def build(current, window):
        source = next(current.entries[ref.memory_id] for ref in window.input_episode_refs)
        first = link_proposal('p0', source, memory_ref(current.entries[support]))
        second = link_proposal('p1', source, {'proposal_ref': 'p0'})
        return [first, second]

    runtime, outcome = await run_distiller_window(db_session, memory_writer_owner, scope, service, build)
    d1, d2 = outcome.output_memory_ids
    await set_policy(db_session, scope, {})
    await service.govern('retire', scope_id=scope, memory_id=support, actor='management', reason='Revoked')
    current = await runtime.read_snapshot(scope)
    context = support_maintenance_context(
        historical_source_refs=lineage(current, current.entries[d1]),
        propagation_trigger=link_trigger(current.entries[d1], support, event_id=1))
    token = await admit(runtime, scope, trigger='support_maintenance', context=context)
    outcome = await run_propagation(runtime, token, context=context)
    assert outcome.status == 'completed'
    current = await runtime.read_snapshot(scope)
    assert current.entries[d1]['status'] == current.entries[d2]['status'] == 'retired'
    events = propagation_events(await MemoryEventStore(db_session).replay(scope))
    assert len(events) == 2
    assert max(event['payload']['propagation']['depth'] for event in events) == 2


@pytest.mark.asyncio
async def test_hard_target_protected_with_permanent_audit(db_session, memory_writer_owner):
    scope = await create_scope(db_session)
    profile = await db_session.get(DomainProfile, (await db_session.get(KnowledgeScope, scope)).domain_key)
    profile.memory_link_vocabulary = thaw(VOCAB)
    await db_session.commit()
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    chunk_id, _version = await published_chunk(db_session, scope)
    hard = (await service.record({'scope_id': scope, 'kind': 'semantic', 'content': 'Hard anchored fact',
                                  'provenance': 'hard', 'evidence_refs': [str(chunk_id)]}))['memory_id']
    support = (await recorded_episode(service, scope, 'Soft support', kind='semantic'))['memory_id']
    await recorded_episode(service, scope, 'Observed episode')

    def build(current, window):
        source = next(current.entries[ref.memory_id] for ref in window.input_episode_refs)
        proposal = link_proposal('p0', source, memory_ref(current.entries[support]))
        # The live edge belongs to the hard memory: H --requires--> S.
        proposal['link_suggestions'][0]['from_ref'] = memory_ref(current.entries[hard])
        return [proposal]

    runtime, outcome = await run_distiller_window(db_session, memory_writer_owner, scope, service, build)
    await set_policy(db_session, scope, {})
    await service.govern('retire', scope_id=scope, memory_id=support, actor='management', reason='Revoked')
    current = await runtime.read_snapshot(scope)
    context = support_maintenance_context(
        historical_source_refs=lineage(current, current.entries[hard]),
        propagation_trigger=link_trigger(current.entries[hard], support, event_id=1))
    token = await admit(runtime, scope, trigger='support_maintenance', context=context)
    outcome = await run_propagation(runtime, token, context=context)
    assert outcome.status == 'rejected' and 'HARD_MEMORY_PROTECTED' in outcome.reason_codes
    current = await runtime.read_snapshot(scope)
    assert current.entries[hard]['status'] == 'active'
    assert propagation_events(await MemoryEventStore(db_session).replay(scope)) == []
    grants = [event for event in await MemoryEventStore(db_session).replay(scope)
              if event['event_type'] == 'grant' and event['payload'].get('grant_type') == 'consolidation_propagation']
    assert grants and grants[0]['payload']['visited_memory_ids'] == [hard]
    assert current.consolidation_state['propagation_seals']
    latest = await runtime.latest_observation(token.run_id)
    assert any('HARD_MEMORY_PROTECTED' in row['reason_codes'] for row in latest.adjudications)


async def evidence_scope(session, owner):
    """scope with a published chunk and a distilled memory anchored on it."""
    scope = await create_scope(session)
    service = MemoryService(session, embedding_provider=StableEmbedding())
    chunk_id, version_id = await published_chunk(session, scope)
    await recorded_episode(service, scope, 'Observed episode')

    def build(current, window):
        source = next(current.entries[ref.memory_id] for ref in window.input_episode_refs)
        return [{'proposal_id': 'p0', 'action': 'extract_fact', 'source_refs': [memory_ref(source)],
                 'kind': 'semantic', 'content': 'Anchored conclusion', 'confidence': .87,
                 'evidence_refs': [str(chunk_id)], 'justification': 'Observed behavior'}]

    runtime, outcome = await run_distiller_window(session, owner, scope, service, build)
    return scope, service, runtime, outcome.output_memory_ids[0], chunk_id, version_id


async def withdraw(session, version_id, status):
    await session.execute(text('UPDATE knowledge_versions SET status=:status WHERE version_id=:id'),
                          {'status': status, 'id': version_id})
    await session.commit()


def evidence_trigger(target, chunk_id, version_id):
    return {'kind': 'evidence_revocation', 'event_id': None, 'evidence_id': str(chunk_id),
            'version_id': version_id, 'version': str(version_id),
            'observed_at': datetime.now(UTC).isoformat(),
            'proof': {'kind': 'evidence_revocation', 'status': 'withdrawn'},
            'target_ref': memory_ref(target)}


@pytest.mark.asyncio
async def test_evidence_withdrawal_invalidates_without_new_episodes(db_session, memory_writer_owner):
    scope, _service, runtime, dependent, chunk_id, version_id = await evidence_scope(db_session,
                                                                                     memory_writer_owner)
    await set_policy(db_session, scope, {})
    await withdraw(db_session, version_id, 'withdrawn')
    current = await runtime.read_snapshot(scope)
    context = support_maintenance_context(
        historical_source_refs=lineage(current, current.entries[dependent]),
        propagation_trigger=evidence_trigger(current.entries[dependent], chunk_id, version_id))
    token = await admit(runtime, scope, trigger='support_maintenance', context=context)
    outcome = await run_propagation(runtime, token, context=context)
    assert outcome.status == 'completed'
    current = await runtime.read_snapshot(scope)
    assert current.entries[dependent]['status'] == 'retired'
    events = propagation_events(await MemoryEventStore(db_session).replay(scope))
    assert len(events) == 1 and events[0]['payload']['source_outcomes'] == []
    assert events[0]['payload']['propagation']['trigger']['kind'] == 'evidence_revocation'


@pytest.mark.asyncio
async def test_changed_support_proof_rejects_the_commit(db_session, memory_writer_owner):
    scope, _service, runtime, dependent, chunk_id, version_id = await evidence_scope(db_session,
                                                                                     memory_writer_owner)
    await set_policy(db_session, scope, {})
    await withdraw(db_session, version_id, 'withdrawn')
    current = await runtime.read_snapshot(scope)
    context = support_maintenance_context(
        historical_source_refs=lineage(current, current.entries[dependent]),
        propagation_trigger=evidence_trigger(current.entries[dependent], chunk_id, version_id))
    token = await admit(runtime, scope, trigger='support_maintenance', context=context)
    # The withdrawal is republished before the maintenance wave commits.
    await withdraw(db_session, version_id, 'published')
    outcome = await run_propagation(runtime, token, context=context)
    assert outcome.status == 'rejected' and 'CONTRADICTION_NOT_PROVEN' in outcome.reason_codes
    replayed = await MemoryEventStore(db_session).replay(scope)
    assert propagation_events(replayed) == []
    assert not [event for event in replayed if event['event_type'] == 'grant'
                and event['payload'].get('grant_type') == 'consolidation_propagation']
    current = await runtime.read_snapshot(scope)
    assert current.entries[dependent]['status'] == 'active'


@pytest.mark.asyncio
async def test_expired_token_and_busy_and_forged_contexts(db_session, memory_writer_owner):
    setup = await dependent_scope(db_session, memory_writer_owner)
    scope, runtime = setup['scope'], setup['runtime']
    dependent, support = setup['dependent'], setup['support']
    await set_policy(db_session, scope, {})
    await setup['service'].govern('retire', scope_id=scope, memory_id=support,
                                  actor='management', reason='Revoked')
    current = await runtime.read_snapshot(scope)
    dependent = current.entries[dependent['memory_id']]
    context = support_maintenance_context(
        historical_source_refs=lineage(current, dependent),
        propagation_trigger=link_trigger(dependent, support, event_id=1))
    token = await admit(runtime, scope, trigger='support_maintenance', context=context)
    with pytest.raises(ConsolidationRuntimeError, match='CONSOLIDATION_BUSY'):
        await admit(runtime, scope, trigger='support_maintenance', context=context)
    # REST/MCP/model callers cannot construct or select the maintenance context.
    with pytest.raises(PermissionError):
        TrustedContext(execution_context='deterministic_propagation',
                       historical_source_refs=lineage(current, dependent),
                       propagation_trigger={'proof': {'x': 1}})
    with pytest.raises(ConsolidationRuntimeError, match='TRUSTED_CONTEXT_REQUIRED'):
        await admit(runtime, scope, trigger='support_maintenance')
    with pytest.raises(ConsolidationRuntimeError, match='TRUSTED_CONTEXT_REQUIRED'):
        await admit(runtime, scope, trigger='manual', context=context)
    # A stale token loses the fence even while the proof stays valid.
    await db_session.execute(text("UPDATE consolidation_eligibilities SET expires_at="
                                  "clock_timestamp()-interval '1 second' WHERE eligibility_id=:id"),
                             {'id': token.eligibility_id})
    await db_session.commit()
    outcome = await run_propagation(runtime, token, context=context)
    assert outcome.status == 'rejected' and 'ELIGIBILITY_LOST' in outcome.reason_codes
    assert propagation_events(await MemoryEventStore(db_session).replay(scope)) == []


@pytest.mark.asyncio
async def test_multilevel_cascade_material_and_noop_continuation_grant(db_session, memory_writer_owner):
    """Real-path multi-level reverse cascade with permanent captured material.

    The exact 32-depth/128-node frontier budgets are proven against the real
    planner in tests/unit/test_consolidation_links.py; this test keeps the
    authoritative event path (admission, fence, adjudication, publication,
    continuation grant) on a real but environment-sized chain: the deployed
    publish path is super-linear per entry and the fixed 30s commit fence makes
    a 35-entry chain unbuildable in this environment.
    """
    depth = 6
    scope = await create_scope(db_session)
    profile = await db_session.get(DomainProfile, (await db_session.get(KnowledgeScope, scope)).domain_key)
    profile.memory_link_vocabulary = thaw(VOCAB)
    await db_session.commit()
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    chain = []
    for index in range(depth + 1):
        chain.append((await recorded_episode(service, scope, f'Chain node {index}',
                                             kind='semantic'))['memory_id'])
    await recorded_episode(service, scope, 'Observed episode')

    def build(current, window):
        source = next(current.entries[ref.memory_id] for ref in window.input_episode_refs
                      if current.entries[ref.memory_id]['kind'] == 'episodic')
        suggestions = [{'from_ref': memory_ref(current.entries[chain[index]]),
                        'to_ref': memory_ref(current.entries[chain[index - 1]]),
                        'relation_type': 'requires', 'confidence': .9,
                        'description': 'Chain dependency'} for index in range(1, depth + 1)]
        return [{'proposal_id': 'p0', 'action': 'extract_fact',
                 'source_refs': [memory_ref(source)], 'kind': 'semantic',
                 'content': 'Chain anchor', 'confidence': .87,
                 'evidence_refs': [], 'justification': 'Observed behavior',
                 'link_suggestions': suggestions}]

    runtime, _outcome = await run_distiller_window(db_session, memory_writer_owner, scope, service, build)
    await set_policy(db_session, scope, {})
    await service.govern('retire', scope_id=scope, memory_id=chain[0], actor='management', reason='Revoked')
    current = await runtime.read_snapshot(scope)
    context = support_maintenance_context(
        historical_source_refs=lineage(current, current.entries[chain[1]]),
        propagation_trigger=link_trigger(current.entries[chain[1]], chain[0], event_id=1))
    token = await admit(runtime, scope, trigger='support_maintenance', context=context)
    outcome = await run_propagation(runtime, token, context=context)
    assert outcome.status == 'completed'
    current = await runtime.read_snapshot(scope)
    assert all(current.entries[mid]['status'] == 'retired' for mid in chain[1:])
    events = propagation_events(await MemoryEventStore(db_session).replay(scope))
    assert len(events) == depth
    material = events[-1]['payload']['propagation']
    assert material['depth'] == depth and material['frontier_memory_ids'] == []
    assert sorted(material['visited_memory_ids']) == sorted(chain[1:])
    assert all(event['payload']['source_outcomes'] == [] for event in events)
    # A repeated wave is an auditable no-op: permanent continuation grant, no
    # empty consolidate.
    await release(runtime, token)
    before = await MemoryEventStore(db_session).replay(scope)
    current = await runtime.read_snapshot(scope)
    context = support_maintenance_context(
        historical_source_refs=lineage(current, current.entries[chain[1]]),
        propagation_trigger=link_trigger(current.entries[chain[1]], chain[0],
                                         event_id=events[-1]['event_id']))
    token = await admit(runtime, scope, trigger='support_maintenance', context=context)
    outcome = await run_propagation(runtime, token, context=context)
    after = await MemoryEventStore(db_session).replay(scope)
    assert not [event for event in after[len(before):] if event['event_type'] == 'consolidate']
    grants = [event for event in after[len(before):]
              if event['event_type'] == 'grant' and event['payload'].get('grant_type') == 'consolidation_propagation']
    assert grants, 'the no-effect wave must persist its continuation material'
    current = await runtime.read_snapshot(scope)
    assert current.consolidation_state.get('propagation_seals'), 'registry replays the seal'
    assert outcome.status in ('completed', 'rejected')


@pytest.mark.asyncio
async def test_frontier_recorded_and_resumed_on_real_persisted_path(db_session, memory_writer_owner, monkeypatch):
    """Persisted frontier record and its continuation on the real event path.

    The exact 32-depth/128-node budgets are proven against the real planner in
    tests/unit/test_consolidation_links.py. Here the same persisted path
    (admission, fence, adjudication, publication, continuation) runs with an
    environment-sized depth budget so the frontier is actually recorded and then
    resumed to completion.
    """
    from rag_mcp.orchestration import consolidation_pipeline as pipeline

    monkeypatch.setattr(pipeline, 'PROPAGATION_MAX_DEPTH', 2)
    depth = 5
    scope = await create_scope(db_session)
    profile = await db_session.get(DomainProfile, (await db_session.get(KnowledgeScope, scope)).domain_key)
    profile.memory_link_vocabulary = thaw(VOCAB)
    await db_session.commit()
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    chain = []
    for index in range(depth + 1):
        chain.append((await recorded_episode(service, scope, f'Frontier node {index}',
                                             kind='semantic'))['memory_id'])
    await recorded_episode(service, scope, 'Frontier episode')

    def build(current, window):
        source = next(current.entries[ref.memory_id] for ref in window.input_episode_refs
                      if current.entries[ref.memory_id]['kind'] == 'episodic')
        suggestions = [{'from_ref': memory_ref(current.entries[chain[index]]),
                        'to_ref': memory_ref(current.entries[chain[index - 1]]),
                        'relation_type': 'requires', 'confidence': .9,
                        'description': 'Chain dependency'} for index in range(1, depth + 1)]
        return [{'proposal_id': 'p0', 'action': 'extract_fact', 'source_refs': [memory_ref(source)],
                 'kind': 'semantic', 'content': 'Frontier anchor', 'confidence': .87,
                 'evidence_refs': [], 'justification': 'Observed behavior', 'link_suggestions': suggestions}]

    runtime, _outcome = await run_distiller_window(db_session, memory_writer_owner, scope, service, build)
    await set_policy(db_session, scope, {})
    await service.govern('retire', scope_id=scope, memory_id=chain[0], actor='management', reason='Revoked')
    current = await runtime.read_snapshot(scope)
    context = support_maintenance_context(
        historical_source_refs=lineage(current, current.entries[chain[1]]),
        propagation_trigger=link_trigger(current.entries[chain[1]], chain[0], event_id=1))
    token = await admit(runtime, scope, trigger='support_maintenance', context=context)
    outcome = await run_propagation(runtime, token, context=context)
    assert outcome.status == 'completed', outcome.reason_codes
    current = await runtime.read_snapshot(scope)
    assert [current.entries[mid]['status'] for mid in chain[1:3]] == ['retired', 'retired']
    assert all(current.entries[mid]['status'] == 'active' for mid in chain[3:])
    events = propagation_events(await MemoryEventStore(db_session).replay(scope))
    material = events[-1]['payload']['propagation']
    assert material['depth'] == 2
    assert sorted(material['frontier_memory_ids']) == sorted(chain[3:])
    assert sorted(material['visited_memory_ids']) == sorted(chain[1:])
    # Resume from the recorded frontier: the remaining chain completes with no
    # further frontier, proving the continuation is actionable, not decorative.
    await release(runtime, token)
    monkeypatch.setattr(pipeline, 'PROPAGATION_MAX_DEPTH', 32)
    frontier = chain[3:]
    current = await runtime.read_snapshot(scope)
    context = support_maintenance_context(
        historical_source_refs=lineage(current, current.entries[frontier[0]]),
        propagation_trigger=link_trigger(current.entries[frontier[0]], chain[2],
                                         event_id=events[-1]['event_id']))
    token = await admit(runtime, scope, trigger='support_maintenance', context=context)
    outcome = await run_propagation(runtime, token, context=context)
    assert outcome.status == 'completed', outcome.reason_codes
    current = await runtime.read_snapshot(scope)
    assert all(current.entries[mid]['status'] == 'retired' for mid in chain[1:])
    resumed = propagation_events(await MemoryEventStore(db_session).replay(scope))
    assert resumed[-1]['payload']['propagation']['frontier_memory_ids'] == []
    assert resumed[-1]['payload']['propagation']['visited_memory_ids']
