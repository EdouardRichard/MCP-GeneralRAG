"""T093 (US4): the five AOEP invariants with at least two real cases each.

Invariants (``specs/013-memory-consolidation-loop/contracts`` and T093):

1. authority boundary - a consolidation effect never widens what authority may
   be appended or overwritten, and a stale holder commits nothing;
2. scope non-expansion - no 013 output, source or recall reaches another scope;
3. provenance preservation - the original attribution/lineage survives every
   state transition, including retirement, purge and audit TTL;
4. deletion propagation - deleting or withdrawing the necessary support removes
   the derived output from every consumable view without losing the log;
5. traceable rollback - a rollback is recorded with its exact fingerprints and
   never erases the permanent consolidation audit; a non-empty derived state is
   rebuildable with zero model calls.

Every case drives the real isolated pipeline; the ``consolidation_evidence``
fixture records the actual observation and the observed hard counts.
"""
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from rag_mcp.models.consolidation_run import ConsolidationRunObservation
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.orchestration.consolidation_pipeline import (
    ProposalBatch,
    run_pipeline,
    support_maintenance_context,
)
from rag_mcp.services.consolidation_adjudicator import memory_ref
from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_reducer import projection_fingerprint, reduce_events
from rag_mcp.services.memory_service import MemoryService
from tests.integration.consolidation_commit_fixtures import commit, prepared
from tests.integration.consolidation_fixtures import StableEmbedding
from tests.integration.phase7_fixtures import episodes, scope_with_policy
from tests.integration.test_013_consolidation_dependencies import (
    admit,
    evidence_scope,
    evidence_trigger,
    lineage,
    run_propagation,
    set_policy,
    withdraw,
)


def _consolidate_events(events):
    return [event for event in events if event['event_type'] == 'consolidate']


def _exposes(value, needle):
    """True when a consumable view still exposes the deleted identity."""
    if isinstance(value, dict):
        return any(_exposes(key, needle) or _exposes(item, needle) for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_exposes(item, needle) for item in value)
    return str(value) == needle


# ---------------------------------------------------------------------------
# Invariant 1: authority boundary.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('forbidden', ['raw_event', 'untrusted_rollback'])
@pytest.mark.asyncio
async def test_aoep_authority_boundary_refuses_forbidden_commands(db_session, memory_writer_owner,
                                                                  consolidation_evidence, forbidden):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, *_ = fixture
    outcome = await commit(fixture)
    assert outcome.status == 'completed' and outcome.output_memory_ids
    scope = token.scope_id
    await db_session.rollback()
    before = await db_session.scalar(select(func.count()).select_from(MemoryEvent).where(
        MemoryEvent.knowledge_scope_id == scope))
    fingerprint = (await service.projections.current(scope)).fingerprint
    with pytest.raises(PermissionError):
        if forbidden == 'raw_event':
            await service.apply_event({'knowledge_scope_id': scope, 'event_type': 'assert',
                                       'payload': {'provenance': 'hard'}})
        else:
            await service.govern('rollback', scope_id=scope, event_point=outcome.output_memory_ids[0],
                                 actor='mcp', reason='untrusted command')
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent).where(
        MemoryEvent.knowledge_scope_id == scope)) == before
    assert (await service.projections.current(scope)).fingerprint == fingerprint

    consolidation_evidence.record(
        'aoep_authority_boundary', scope_id=scope, refused=forbidden,
        event_count=before, request_ids=[str(token.run_id)])
    consolidation_evidence.check('stale_holder_commits', 0)


@pytest.mark.asyncio
async def test_aoep_authority_boundary_stale_holder_publishes_nothing(db_session, memory_writer_owner,
                                                                      consolidation_evidence):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, *_ = fixture
    await db_session.execute(text("UPDATE consolidation_eligibilities SET expires_at="
                                  "clock_timestamp()-interval '1 second' WHERE eligibility_id=:id"),
                             {'id': token.eligibility_id})
    await db_session.commit()
    outcome = await commit(fixture)
    assert outcome.status == 'rejected' and not outcome.output_event_ids
    assert {'ELIGIBILITY_LOST', 'WRITER_LEASE_LOST'} & set(outcome.reason_codes), outcome.reason_codes
    assert _consolidate_events(await MemoryEventStore(db_session).replay(token.scope_id)) == []
    assert (await service.projections.current(token.scope_id)).source_event_id is not None

    consolidation_evidence.record(
        'aoep_stale_holder_boundary', scope_id=token.scope_id, run_id=str(token.run_id),
        reason_codes=list(outcome.reason_codes), published_events=0)
    consolidation_evidence.check('stale_holder_commits', 0)


# ---------------------------------------------------------------------------
# Invariant 2: scope non-expansion.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aoep_scope_non_expansion_rejects_foreign_sources(db_session, memory_writer_owner,
                                                                consolidation_evidence):
    scope_a = await scope_with_policy(db_session)
    await episodes(db_session, scope_a, 1)
    scope_b = await scope_with_policy(db_session)
    identifiers_b = await episodes(db_session, scope_b, 1)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    current_b = await runtime.read_snapshot(scope_b)
    foreign = current_b.entries[identifiers_b[0]]
    await db_session.rollback()
    token = await runtime.admit(scope_a, trigger='manual')
    await runtime.select_and_seal(token)

    async def foreign_stage(window, distiller, *, current, context, policy, now, provider=None):
        return ProposalBatch([{'proposal_id': 'p0', 'action': 'extract_fact',
                               'source_refs': [memory_ref(foreign)], 'kind': 'semantic',
                               'content': 'Conclusion built from a foreign scope',
                               'confidence': .9, 'evidence_refs': [],
                               'justification': 'foreign identity'}])

    outcome = await run_pipeline(runtime, token, distiller=None, propose_stage=foreign_stage)
    assert outcome.status == 'rejected' and not outcome.output_event_ids
    await db_session.rollback()
    latest = await runtime.latest_observation(token.run_id)
    reasons = [code for row in latest.adjudications for code in row['reason_codes']]
    # The foreign identity is refused as an ineligible source; no foreign scope
    # identity is ever consumed or published.
    assert reasons and set(reasons) <= {'SCOPE_MISMATCH', 'SOURCE_NOT_ELIGIBLE'}, reasons
    assert _consolidate_events(await MemoryEventStore(db_session).replay(scope_a)) == []
    assert _consolidate_events(await MemoryEventStore(db_session).replay(scope_b)) == []
    assert foreign['knowledge_scope_id'] == scope_b

    consolidation_evidence.record(
        'aoep_scope_non_expansion', scope_id=scope_a, foreign_scope_id=scope_b,
        run_id=str(token.run_id), reason_codes=reasons)
    consolidation_evidence.check('cross_scope_leaks', 0)


@pytest.mark.asyncio
async def test_aoep_scope_non_expansion_never_leaks_output_to_another_scope(db_session, memory_writer_owner,
                                                                            consolidation_evidence):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, *_ = fixture
    outcome = await commit(fixture)
    assert outcome.status == 'completed' and outcome.output_memory_ids
    other = await scope_with_policy(db_session)
    await episodes(db_session, other, 1)
    await db_session.rollback()
    foreign_recall = await service.recall(scope_ref=[str(other)],
                                          memory_ids=list(outcome.output_memory_ids),
                                          include_superseded=True, include_delivered=True)
    assert foreign_recall['memories'] == []
    own_recall = await service.recall(scope_ref=[str(token.scope_id)],
                                      memory_ids=list(outcome.output_memory_ids),
                                      include_superseded=True, include_delivered=True)
    assert {row['memory_id'] for row in own_recall['memories']} == set(outcome.output_memory_ids)
    assert _consolidate_events(await MemoryEventStore(db_session).replay(other)) == []

    consolidation_evidence.record(
        'aoep_scope_isolation_recall', scope_id=token.scope_id, other_scope_id=other,
        isolated_memory_ids=[str(item) for item in outcome.output_memory_ids])
    consolidation_evidence.check('cross_scope_leaks', 0)


# ---------------------------------------------------------------------------
# Invariant 3: provenance preservation.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aoep_provenance_preserved_when_distilled_output_is_retired(db_session, memory_writer_owner,
                                                                          consolidation_evidence):
    fixture = await prepared(db_session, memory_writer_owner)
    service, runtime, token, *_ = fixture
    outcome = await commit(fixture)
    output = outcome.output_memory_ids[0]
    await db_session.rollback()
    snapshot = await runtime.read_snapshot(token.scope_id)
    fields = ('content_text', 'content_hash', 'provenance', 'confidence', 'inference_meta',
              'source_lineage', 'evidence_refs', 'kind')
    original = {key: snapshot.entries[output][key] for key in fields}
    assert original['provenance'] == 'distilled' and original['source_lineage']
    await db_session.rollback()
    await service.govern('retire', scope_id=token.scope_id, memory_id=output, actor='management',
                         reason='AOEP provenance retention')
    current = await runtime.read_snapshot(token.scope_id)
    entry = current.entries[output]
    assert entry['status'] == 'retired'
    assert {key: entry[key] for key in fields} == original
    assert all(row['matches_replay'] for row in
               (await service.inspect_projections(token.scope_id)).values())

    consolidation_evidence.record(
        'aoep_provenance_retire', scope_id=token.scope_id, memory_id=str(output),
        preserved_fields=list(fields))
    consolidation_evidence.check('source_chain_complete_rate', 1.0)
    await consolidation_evidence.capture_authority(db_session, token.scope_id)


@pytest.mark.asyncio
async def test_aoep_provenance_retained_in_log_when_output_is_purged(db_session, memory_writer_owner,
                                                                     consolidation_evidence):
    fixture = await prepared(db_session, memory_writer_owner)
    service, runtime, token, *_ = fixture
    outcome = await commit(fixture)
    output = outcome.output_memory_ids[0]
    await db_session.rollback()
    await service.govern('purge', scope_id=token.scope_id, memory_id=output, actor='management',
                         reason='AOEP deletion retention')
    events = await MemoryEventStore(db_session).replay(token.scope_id)
    consolidate = [event for event in events if event['event_id'] in outcome.output_event_ids]
    assert consolidate and consolidate[0]['payload']['content_text']
    assert consolidate[0]['payload']['source_lineage'] or consolidate[0]['payload'].get('source_refs')
    current = await runtime.read_snapshot(token.scope_id)
    assert current.entries[output]['status'] == 'retired'
    assert all(row['matches_replay'] for row in
               (await service.inspect_projections(token.scope_id)).values())
    assert not _exposes({key: value for key, value in current.entries.items() if key != output},
                        str(output))

    consolidation_evidence.record(
        'aoep_provenance_purge', scope_id=token.scope_id, memory_id=str(output),
        retained_event_ids=[str(item) for item in outcome.output_event_ids])
    consolidation_evidence.check('source_chain_complete_rate', 1.0)


# ---------------------------------------------------------------------------
# Invariant 4: deletion propagation.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('action', ['retire', 'purge'])
@pytest.mark.asyncio
async def test_aoep_deletion_propagates_to_consumable_views(db_session, memory_writer_owner,
                                                            consolidation_evidence, action):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, *_ = fixture
    outcome = await commit(fixture)
    output = outcome.output_memory_ids[0]
    await db_session.rollback()
    await service.govern(action, scope_id=token.scope_id, memory_id=output, actor='management',
                         reason=f'AOEP deletion propagation via {action}')
    manifest = await service.projections.current(token.scope_id)
    state = manifest.payload['state']
    assert state['entries'][str(output)]['status'] == 'retired'
    for view in ('dense', 'summary', 'files'):
        assert not _exposes(state.get(view), str(output)), f'{view} still exposes the deleted memory'
    assert all(row['matches_replay'] for row in
               (await service.inspect_projections(token.scope_id)).values())
    recalled = await service.recall(scope_ref=[str(token.scope_id)], include_superseded=True,
                                    include_delivered=True)
    assert output not in {row['memory_id'] for row in recalled['memories']}
    events = await MemoryEventStore(db_session).replay(token.scope_id)
    assert any(event['event_id'] in outcome.output_event_ids for event in events)

    consolidation_evidence.record(
        'aoep_deletion_propagation', scope_id=token.scope_id, memory_id=str(output), action=action,
        recalled_memory_ids=[str(row['memory_id']) for row in recalled['memories']])
    consolidation_evidence.check('incomplete_outputs_consumed', 0)


@pytest.mark.asyncio
async def test_aoep_support_withdrawal_propagates_without_new_episodes(db_session, memory_writer_owner,
                                                                       consolidation_evidence):
    scope, _service, runtime, dependent, chunk_id, version_id = await evidence_scope(
        db_session, memory_writer_owner)
    await set_policy(db_session, scope, {})
    before = await MemoryEventStore(db_session).replay(scope)
    await withdraw(db_session, version_id, 'withdrawn')
    current = await runtime.read_snapshot(scope)
    context = support_maintenance_context(
        historical_source_refs=lineage(current, current.entries[dependent]),
        propagation_trigger=evidence_trigger(current.entries[dependent], chunk_id, version_id))
    token = await admit(runtime, scope, trigger='support_maintenance', context=context)
    outcome = await run_propagation(runtime, token, context=context)
    assert outcome.status == 'completed', outcome.reason_codes
    after = await MemoryEventStore(db_session).replay(scope)
    appended = after[len(before):]
    assert not [event for event in appended if event['event_type'] == 'assert']
    propagated = _consolidate_events(appended)
    assert len(propagated) == 1
    assert propagated[0]['payload']['execution_context'] == 'deterministic_propagation'
    assert propagated[0]['payload']['source_outcomes'] == []
    current = await runtime.read_snapshot(scope)
    assert current.entries[dependent]['status'] == 'retired'

    consolidation_evidence.record(
        'aoep_support_withdrawal', scope_id=scope, run_id=str(token.run_id),
        dependent_memory_id=str(dependent),
        propagated_event_ids=[str(event['event_id']) for event in propagated],
        new_episodes=0)
    consolidation_evidence.check('rebuild_llm_calls', 0)


# ---------------------------------------------------------------------------
# Invariant 5: traceable rollback and non-empty rebuild.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aoep_rollback_is_traceable_and_keeps_the_consolidation_audit(db_session, memory_writer_owner,
                                                                           consolidation_evidence):
    fixture = await prepared(db_session, memory_writer_owner)
    service, runtime, token, batch, _context, decisions = fixture
    outcome = await commit(fixture)
    output = outcome.output_memory_ids[0]
    await db_session.rollback()
    await runtime.observe_result(token, decisions, outcome, batch=batch)
    await db_session.rollback()
    accessed = await service.govern('access', scope_id=token.scope_id, memory_id=output,
                                    actor='management', reason='observed read')
    rollback = await service.govern('rollback', scope_id=token.scope_id,
                                    event_point=outcome.output_event_ids[0], actor='management',
                                    reason='AOEP human rollback')
    event = await db_session.get(MemoryEvent, rollback['event_id'])
    assert event.event_type == 'rollback' and event.request_id == rollback['request_id']
    assert all(event.payload[field] == rollback[field]
               for field in ('before_fingerprint', 'after_fingerprint', 'impact'))
    assert await db_session.get(MemoryEvent, accessed['event_id']) is not None
    current = await runtime.read_snapshot(token.scope_id)
    assert current.entries[output]['status'] == 'retired'
    assert current.entries[output]['state_event_id'] == rollback['event_id']
    assert all(row['matches_replay'] for row in
               (await service.inspect_projections(token.scope_id)).values())
    await db_session.rollback()
    latest = await runtime.latest_observation(token.run_id)
    assert latest is not None and latest.status == 'succeeded'
    assert any(row['decision'] == 'accept' for row in latest.adjudications)

    consolidation_evidence.record(
        'aoep_traceable_rollback', scope_id=token.scope_id, run_id=str(token.run_id),
        rollback_event_id=str(rollback['event_id']), access_event_id=str(accessed['event_id']),
        impact=rollback['impact'])
    consolidation_evidence.check('source_chain_complete_rate', 1.0)


@pytest.mark.asyncio
async def test_aoep_nonempty_rebuild_after_ttl_purge_uses_no_model(db_session, memory_writer_owner,
                                                                   consolidation_evidence):
    fixture = await prepared(db_session, memory_writer_owner, count=2)
    service, runtime, token, *_ = fixture
    outcome = await commit(fixture)
    assert outcome.status == 'completed' and len(outcome.output_memory_ids) == 2
    report = await _run_report(db_session, token)
    assert report['provider_usage']['llm_calls'] == 0
    await db_session.rollback()
    now = await db_session.scalar(text('SELECT clock_timestamp()'))
    db_session.add(ConsolidationRunObservation(
        run_id=token.run_id, observation_seq=900, knowledge_scope_id=token.scope_id,
        trigger='manual', execution_context='distiller_window', status='succeeded',
        created_at=now - timedelta(days=8), ttl_expires_at=now - timedelta(seconds=1)))
    await db_session.commit()
    assert await runtime.purge_expired_observations() >= 1
    before = projection_fingerprint(reduce_events(await MemoryEventStore(db_session).replay(token.scope_id)))
    await db_session.rollback()
    # The rebuild entry point accepts no provider/distiller, so a non-empty
    # derived state is reconstructed with zero model calls by construction.
    import inspect

    assert not [name for name in inspect.signature(service.rebuild).parameters
                if 'model' in name or 'distiller' in name or 'llm' in name]
    rebuilt = await service.rebuild(token.scope_id, actor='management')
    assert len(rebuilt) == 6 and all(row['matches_replay'] for row in rebuilt.values())
    state = reduce_events(await MemoryEventStore(db_session).replay(token.scope_id))
    assert projection_fingerprint(state) == before
    assert all(item in state['entries'] and state['entries'][item]['content_text']
               for item in outcome.output_memory_ids)

    consolidation_evidence.record(
        'aoep_nonempty_rebuild', scope_id=token.scope_id, run_id=str(token.run_id),
        rebuilt_views=len(rebuilt), retained_memory_ids=[str(item) for item in outcome.output_memory_ids],
        model_calls=0)
    consolidation_evidence.check('rebuild_llm_calls', 0)
    consolidation_evidence.check('projection_integrity_rate', 1.0)


async def _run_report(db_session, token):
    from rag_mcp.services import consolidation_report

    report = await consolidation_report.get_run_report(db_session, run_id=token.run_id,
                                                       scope_id=token.scope_id)
    await db_session.rollback()
    return report
