"""T092 (US4): real end-to-end coverage for the six frozen evaluation classes.

Every test drives the real isolated pipeline (scope policy -> admission ->
window seal -> adjudication -> fenced publication -> audit report) and records
what actually happened through the T094 ``consolidation_evidence`` fixture. No
test substitutes a pre-set pass flag or a fabricated metric for an observation.

The six coverage classes required by
``specs/013-memory-consolidation-loop/tasks.md`` T092 are:

1. batch distillation          -> ``test_e2e_batch_distillation_...``
2. deterministic merge/correct -> ``test_e2e_deterministic_merge_...`` and
                                  ``test_e2e_support_withdrawal_...``
3. soft overturn of hard       -> ``test_e2e_soft_overturn_of_hard_...``
4. model/schema fault degrade  -> ``test_e2e_model_schema_fault_...``
5. gate pass/fail control      -> ``test_e2e_benefit_gate_...``
6. manual candidate promotion  -> ``test_e2e_candidate_promotion_...``
"""
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from rag_mcp.orchestration.consolidation_pipeline import (
    ProposalBatch,
    deterministic_proposals,
    run_pipeline,
    thaw,
)
from rag_mcp.services.consolidation_adjudicator import (
    AdjudicationContext,
    adjudicate_batch,
    memory_ref,
)
from rag_mcp.services.consolidation_gate import TRACE_VERSION, binary_metrics, validate_report
from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_policy import MemoryPolicy
from rag_mcp.services.memory_service import MemoryService
from tests.integration.consolidation_commit_fixtures import commit, prepared
from tests.integration.consolidation_fixtures import StableEmbedding, create_scope, recorded_episode
from tests.integration.phase7_fixtures import episodes, scope_with_policy
from tests.integration.promotion_fixtures import committed_candidate, promote
from tests.integration.test_013_consolidation_dependencies import (
    admit,
    evidence_scope,
    evidence_trigger,
    lineage,
    published_chunk,
    run_propagation,
    set_policy,
    support_maintenance_context,
    withdraw,
)
from tests.unit.consolidation_cases import facts


async def _report(db_session, token):
    from rag_mcp.services import consolidation_report

    report = await consolidation_report.get_run_report(db_session, run_id=token.run_id,
                                                       scope_id=token.scope_id)
    await db_session.rollback()
    return report


def _consolidate_events(events):
    return [event for event in events if event['event_type'] == 'consolidate']


# ---------------------------------------------------------------------------
# Class 1: real batch distillation of several episodes in one accepted group.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_batch_distillation_publishes_real_authority(db_session, memory_writer_owner,
                                                               consolidation_evidence):
    scope = await scope_with_policy(db_session)
    identifiers = await episodes(db_session, scope, 2)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    token = await runtime.admit(scope, trigger='manual')
    current = await runtime.read_snapshot(scope)
    sources = [current.entries[identifier] for identifier in identifiers]
    proposals = [
        {'proposal_id': 'p0', 'action': 'extract_fact', 'source_refs': [memory_ref(sources[0])],
         'kind': 'semantic', 'content': 'Batch distilled semantic conclusion',
         'confidence': .91, 'evidence_refs': [], 'justification': 'Observed episodes'},
        {'proposal_id': 'p1', 'action': 'distill_procedure', 'source_refs': [memory_ref(sources[1])],
         'kind': 'procedural', 'content': 'Batch distilled reusable procedure',
         'confidence': .88, 'evidence_refs': [], 'justification': 'Observed episodes'},
    ]
    seen = {}

    async def batch_stage(window, distiller, *, current, context, policy, now, provider=None):
        seen['window'] = window
        return ProposalBatch(proposals)

    await db_session.rollback()
    outcome = await run_pipeline(runtime, token, distiller=None, propose_stage=batch_stage)
    assert len(seen['window'].input_episode_refs) >= 2
    assert outcome.status == 'completed', outcome.reason_codes
    assert len(outcome.output_memory_ids) == 2 and len(outcome.output_event_ids) == 2, outcome
    rebuilt = await service.inspect_projections(scope)
    assert all(row['matches_replay'] for row in rebuilt.values())
    report = await _report(db_session, token)
    assert report['status'] == 'succeeded'
    assert report['counts'] == {'proposed': 2, 'accepted': 2, 'rejected': 0, 'committed': 2,
                                'pending': 0, 'failed': 0, 'unprocessed': 0}
    assert set(report['output_memory_ids']) == {str(item) for item in outcome.output_memory_ids}
    events = await MemoryEventStore(db_session).replay(scope)
    assert {str(event['event_id']) for event in _consolidate_events(events)} == {
        str(item) for item in outcome.output_event_ids}
    published = await runtime.read_snapshot(scope)
    kinds = {published.entries[item]['kind'] for item in outcome.output_memory_ids}
    assert kinds == {'semantic', 'procedural'}

    consolidation_evidence.record(
        'batch_distillation', scope_id=scope, run_id=str(token.run_id),
        eligibility_id=str(token.eligibility_id),
        event_ids=[str(item) for item in outcome.output_event_ids],
        memory_ids=[str(item) for item in outcome.output_memory_ids],
        counts=dict(report['counts']), status=report['status'],
        model_calls=report['provider_usage']['llm_calls'],
        adjudications=[row['decision'] for row in report.get('adjudications', [])])
    consolidation_evidence.check('cross_scope_leaks', 0)
    consolidation_evidence.check('projection_integrity_rate',
                                 1.0 if all(row['matches_replay'] for row in rebuilt.values()) else 0.0)
    snapshot = await consolidation_evidence.capture_authority(db_session, scope)
    assert snapshot['cutoff'] >= max(outcome.output_event_ids)
    assert all(str(item) in snapshot['memory_ids'] for item in outcome.output_memory_ids)


# ---------------------------------------------------------------------------
# Class 2a: deterministic duplicate merge over real CRLF/LF-normalized outputs.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_deterministic_merge_deduplicates_equivalent_outputs(db_session, memory_writer_owner,
                                                                       consolidation_evidence):
    fixture = await prepared(db_session, memory_writer_owner, count=2, shared=True)
    service, runtime, token, batch, context, _ = fixture
    proposals = thaw(batch.proposals)
    for proposal, body in zip(proposals, ('alpha\r\nbeta', 'alpha\nbeta'), strict=True):
        proposal['content'] = body
        proposal.pop('context')
    batch = ProposalBatch(proposals)
    context = replace(context, inferences={p['proposal_id']: facts(p) for p in proposals})
    current = await runtime.read_snapshot(token.scope_id)
    policy = MemoryPolicy.model_validate(thaw(context.window.policy))
    decisions = adjudicate_batch(batch, current, policy, current.vocabulary,
                                 {'count': current.quota_count, 'limit': policy.per_scope_memory_quota},
                                 context, datetime.now(UTC))
    assert decisions.groups and all(d.decision == 'accept' for d in decisions.decisions)
    await db_session.rollback()
    created = await commit((service, runtime, token, batch, context, decisions))
    assert created.status == 'completed' and len(created.output_memory_ids) == 2
    assert await runtime.release(token)

    await recorded_episode(service, token.scope_id, 'Unrelated episode for the merge window')
    token = await runtime.admit(token.scope_id, trigger='manual')
    window = await runtime.select_and_seal(token)
    current = await runtime.read_snapshot(token.scope_id)
    context = AdjudicationContext(window=window)
    proposals = deterministic_proposals(current, context=context, policy=policy,
                                        now=datetime.now(UTC))
    assert len(proposals) == 1 and proposals[0]['action'] == 'merge_duplicate', proposals
    batch = ProposalBatch([], deterministic_proposals=proposals)
    decisions = adjudicate_batch(batch, current, policy, current.vocabulary,
                                 {'count': current.quota_count, 'limit': policy.per_scope_memory_quota},
                                 context, datetime.now(UTC))
    assert decisions.groups and all(d.decision == 'accept' for d in decisions.decisions)
    await db_session.rollback()
    merged = await commit((service, runtime, token, batch, context, decisions))
    assert merged.status == 'completed' and not merged.output_memory_ids
    assert len(merged.output_event_ids) == 1
    latest = await runtime.read_snapshot(token.scope_id)
    assert sorted(latest.entries[item]['status'] for item in created.output_memory_ids) == ['active', 'retired']
    assert all(latest.entries[item]['source_lineage'] for item in created.output_memory_ids)
    for item in created.output_memory_ids:
        assert latest.entries[item]['content_hash']

    consolidation_evidence.record(
        'deterministic_merge', scope_id=token.scope_id, run_id=str(token.run_id),
        event_ids=[str(item) for item in merged.output_event_ids],
        merged_memory_ids=[str(item) for item in created.output_memory_ids],
        status=merged.status, deterministic_actions=[p['action'] for p in thaw(proposals)])
    consolidation_evidence.check('invalid_outputs_applied', 0)
    await consolidation_evidence.capture_authority(db_session, token.scope_id)


# ---------------------------------------------------------------------------
# Class 2b: deterministic correction through a real support/evidence withdrawal.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_support_withdrawal_corrects_the_dependent_without_new_episodes(
        db_session, memory_writer_owner, consolidation_evidence):
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
    assert not [event for event in after[len(before):] if event['event_type'] == 'assert'], \
        'a deterministic correction never records a new episode'
    propagated = [event for event in after[len(before):] if event['event_type'] == 'consolidate']
    assert len(propagated) == 1
    assert propagated[0]['payload']['source_outcomes'] == []
    current = await runtime.read_snapshot(scope)
    assert current.entries[dependent]['status'] == 'retired'
    report = await _report(db_session, token)
    assert report['provider_usage']['llm_calls'] == 0
    assert report['provider_usage']['source'] == 'actual'

    consolidation_evidence.record(
        'deterministic_correction', scope_id=scope, run_id=str(token.run_id),
        event_ids=[str(event['event_id']) for event in propagated],
        corrected_memory_id=str(dependent), trigger=report['trigger'],
        execution_context=report['execution_context'],
        model_calls=report['provider_usage']['llm_calls'])
    consolidation_evidence.check('soft_overturns_hard', 0)
    consolidation_evidence.check('rebuild_llm_calls', 0)
    await consolidation_evidence.capture_authority(db_session, scope)


# ---------------------------------------------------------------------------
# Class 3: a soft proposal can never overturn a hard fact, and the refusal is
# permanently audited.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_soft_overturn_of_hard_fact_is_rejected_and_audited(db_session, memory_writer_owner,
                                                                      consolidation_evidence):
    scope = await create_scope(db_session)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    chunk_id, _version_id = await published_chunk(db_session, scope)
    hard = (await service.record({'scope_id': scope, 'kind': 'semantic',
                                  'content': 'Protected hard fact anchored on published evidence',
                                  'provenance': 'hard', 'evidence_refs': [str(chunk_id)]}))['memory_id']
    soft = (await recorded_episode(service, scope, 'Soft episode claiming the hard fact changed'))['memory_id']
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    token = await runtime.admit(scope, trigger='manual')
    current = await runtime.read_snapshot(scope)
    overturn = {'proposal_id': 'p0', 'action': 'invalidate_contradiction',
                'source_refs': [memory_ref(current.entries[soft])],
                'target_ref': memory_ref(current.entries[hard]), 'correcting_ref': None,
                'contradiction_basis': 'soft claim against a protected hard fact',
                'confidence': .9, 'evidence_refs': [], 'justification': 'Observed contradiction'}

    async def overturn_stage(window, distiller, *, current, context, policy, now, provider=None):
        return ProposalBatch([overturn])

    await db_session.rollback()
    outcome = await run_pipeline(runtime, token, distiller=None, propose_stage=overturn_stage)
    assert outcome.status == 'rejected' and not outcome.output_event_ids
    await db_session.rollback()
    latest = await runtime.latest_observation(token.run_id)
    adjudications = [row for row in latest.adjudications if row['decision'] == 'reject']
    assert adjudications and any('HARD_MEMORY_PROTECTED' in row['reason_codes'] for row in adjudications), \
        [row['reason_codes'] for row in latest.adjudications]
    report = await _report(db_session, token)
    assert report['status'] == 'no_change' and 'all_rejected' in report['degradation_reasons']
    assert report['counts']['accepted'] == 0 and report['counts']['committed'] == 0
    current = await runtime.read_snapshot(scope)
    assert current.entries[hard]['status'] == 'active'
    assert _consolidate_events(await MemoryEventStore(db_session).replay(scope)) == []

    consolidation_evidence.record(
        'soft_overturn_refusal', scope_id=scope, run_id=str(token.run_id),
        eligibility_id=str(token.eligibility_id), protected_memory_id=str(hard),
        reason_codes=list(adjudications[0]['reason_codes']), status=report['status'],
        counts=dict(report['counts']))
    consolidation_evidence.check('soft_overturns_hard', 0)
    consolidation_evidence.check('invalid_outputs_applied', 0)


# ---------------------------------------------------------------------------
# Class 4: a real provider/schema fault degrades instead of publishing.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_model_schema_fault_degrades_without_publishing(db_session, memory_writer_owner,
                                                                  monkeypatch, tmp_path,
                                                                  consolidation_evidence):
    from tests.unit.distiller_cases import transport

    scope = await scope_with_policy(db_session)
    await episodes(db_session, scope, 1)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    token = await runtime.admit(scope, trigger='manual')
    await runtime.select_and_seal(token)
    # The real synchronous httpx boundary answers with a package that violates
    # the packaged Distiller schema; no network and no pre-set degraded flag.
    agent, _client, calls = transport(
        monkeypatch, content=json.dumps({'proposals': [{'proposal_id': 'p0', 'action': 'extract_fact'}]}),
        cache_dir=str(tmp_path))
    outcome = await run_pipeline(runtime, token, distiller=agent)
    assert len(calls) == 1
    assert not outcome.output_memory_ids and not outcome.output_event_ids
    report = await _report(db_session, token)
    assert 'MODEL_SCHEMA_INVALID' in report['degradation_reasons']
    assert report['status'] in ('degraded', 'no_change')
    assert report['counts']['committed'] == 0
    assert _consolidate_events(await MemoryEventStore(db_session).replay(scope)) == []
    entries = list((tmp_path / 'strict-v1').glob('*.json'))
    assert len(entries) == 1
    stored = json.loads(entries[0].read_text(encoding='utf-8'))
    assert stored == {'parser': 'strict-v1', 'output': None, 'reason': 'MODEL_SCHEMA_INVALID'}

    consolidation_evidence.record(
        'model_schema_fault', scope_id=scope, run_id=str(token.run_id),
        status=report['status'], degradation_reasons=list(report['degradation_reasons']),
        transport_calls=len(calls), cache_entry=str(entries[0].name),
        counts=dict(report['counts']))
    consolidation_evidence.check('incomplete_outputs_consumed', 0)
    consolidation_evidence.check('invalid_outputs_applied', 0)


# ---------------------------------------------------------------------------
# Class 5: the shared benefit gate fails closed on real evidence and accepts
# only complete, internally consistent evidence.
# ---------------------------------------------------------------------------

def _install_trace(report, traces, units, k=5):
    """Recompute every per-query/aggregate rate from a frozen physical-rank trace."""
    for query in report['queries']:
        query['relevance_units'] = list(units)
        query['result_trace'] = {'trace_version': TRACE_VERSION, 'k': k,
                                 'variants': {name: list(ranked) for name, ranked in traces.items()}}
        for name, ranked in traces.items():
            query[name].update(binary_metrics(ranked, units, k))
    for name in traces:
        for metric in ('mrr', 'ndcg', 'hit_rate', 'recall_at_k', 'precision_at_k'):
            report['aggregates'][name][metric] = sum(
                query[name][metric] for query in report['queries']) / len(report['queries'])
    baseline = report['aggregates']['baseline']
    expansion = report['aggregates']['consolidated_candidate_expansion']
    zero = baseline['mrr'] == 0 or baseline['ndcg'] == 0
    report['relative_gains'] = {
        'baseline_zero': zero,
        'mrr': None if zero else (expansion['mrr'] - baseline['mrr']) / baseline['mrr'],
        'ndcg': None if zero else (expansion['ndcg'] - baseline['ndcg']) / baseline['ndcg']}
    return report


@pytest.mark.asyncio
async def test_e2e_benefit_gate_fails_closed_on_real_zero_baseline(db_session, memory_writer_owner,
                                                                   consolidation_evidence):
    from tests.unit.consolidation_gate import binding, build_report

    fixture = await prepared(db_session, memory_writer_owner, count=2, shared=False)
    service, _runtime, token, *_ = fixture
    before = await service.recall(scope_ref=[str(token.scope_id)])
    baseline_ids = {str(row['memory_id']) for row in before['memories']}
    outcome = await commit(fixture)
    assert outcome.status == 'completed' and len(outcome.output_memory_ids) == 2
    units = [str(item) for item in outcome.output_memory_ids]
    # Real measurement: none of the frozen relevance units existed before the
    # run, so the baseline arm has no gain at any physical rank.
    assert not baseline_ids & set(units)
    ranked = [str(row['memory_id']) for row in
              (await service.recall(scope_ref=[str(token.scope_id)]))['memories']]
    expansion_trace = [alias if alias in units else None for alias in ranked[:5]]
    expansion_trace += [None] * (5 - len(expansion_trace))
    traces = {'baseline': [None] * 5, 'consolidated_direct': [None] * 5,
              'consolidated_candidate_expansion': expansion_trace}
    report = _install_trace(build_report(binding(str(token.scope_id)), passed=False), traces, units)
    assert report['relative_gains']['baseline_zero'] is True
    assert report['relative_gains']['mrr'] is None and report['relative_gains']['ndcg'] is None
    assert report['default_enable_eligible'] is False
    # A truthful not-computable baseline is not rejected and is not eligible.
    validate_report(report)

    fabricated = json.loads(json.dumps(report))
    fabricated.update(status='passed', default_enable_eligible=True,
                      gate_binding=binding(str(token.scope_id)))
    with pytest.raises(ValueError, match='schema'):
        validate_report(fabricated)

    # Control: complete evidence with a computable baseline is accepted, proving
    # the gate is not a blanket rejection. This is a fixture-level control, not
    # real benefit evidence (T098/T102 own the real comparison).
    control = build_report(binding('1'))
    validate_report(control)
    assert control['relative_gains']['mrr'] >= .03
    unsupported = json.loads(json.dumps(control))
    unsupported['hard_metrics']['cross_scope_leaks'] = 1
    with pytest.raises(ValueError, match='schema|hard metrics'):
        validate_report(unsupported)
    truncated = json.loads(json.dumps(control))
    truncated['queries'][0]['result_trace']['variants']['baseline'] = [None] * 4
    with pytest.raises(ValueError, match='physical rank'):
        validate_report(truncated)

    consolidation_evidence.record(
        'benefit_gate_control', scope_id=token.scope_id, run_id=str(token.run_id),
        baseline_zero=True, observed_units=units, observed_expansion_trace=expansion_trace,
        rejected_fabricated_gain=True, rejected_nonzero_hard_metric=True,
        rejected_truncated_trace=True, fixture_control_accepted=True)
    consolidation_evidence.check('cross_scope_leaks', 0)
    await consolidation_evidence.capture_authority(db_session, token.scope_id)


# ---------------------------------------------------------------------------
# Class 6: candidate promotion is an explicit human action, never automatic.
# ---------------------------------------------------------------------------

async def _promotion_grants(session, scope_id):
    from sqlalchemy import select

    from rag_mcp.models.memory_event import MemoryEvent

    rows = (await session.execute(select(MemoryEvent).where(
        MemoryEvent.knowledge_scope_id == scope_id, MemoryEvent.event_type == 'grant',
        MemoryEvent.payload['grant_type'].astext.in_(['promotion_requested', 'promotion_observed']))
        .order_by(MemoryEvent.event_id))).scalars().all()
    return list(rows)


@pytest.mark.asyncio
async def test_e2e_candidate_promotion_requires_explicit_human_action(db_session, memory_writer_owner,
                                                                      consolidation_evidence):
    fixture = await committed_candidate(db_session, memory_writer_owner)
    scope, memory_id = fixture['scope'], fixture['memory_id']
    await db_session.rollback()
    assert await _promotion_grants(db_session, scope) == [], \
        'consolidation alone never registers a promotion source'
    result = await promote(db_session, fixture)
    assert result['reused'] is False and result['status'] == 'uploaded'
    assert int(result['task_id']) > 0 and int(result['source_id']) > 0
    grants = await _promotion_grants(db_session, scope)
    assert [grant.payload['grant_type'] for grant in grants] == ['promotion_requested']
    repeated = await promote(db_session, fixture)
    assert repeated['reused'] is True and repeated['task_id'] == result['task_id']
    assert len(await _promotion_grants(db_session, scope)) == 1
    current = await fixture['runtime'].read_snapshot(scope)
    assert current.entries[memory_id]['provenance'] == 'distilled'

    consolidation_evidence.record(
        'manual_candidate_promotion', scope_id=scope,
        task_id=str(result['task_id']), source_id=str(result['source_id']),
        memory_id=str(memory_id), reused_on_repeat=repeated['reused'],
        promotion_grants=[grant.payload['grant_type'] for grant in grants])
    consolidation_evidence.check('automatic_promotions', 0)
    await consolidation_evidence.capture_authority(db_session, scope)
