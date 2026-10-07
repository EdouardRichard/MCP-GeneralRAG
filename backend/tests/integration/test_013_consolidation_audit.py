from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from rag_mcp.models.consolidation_run import ConsolidationEligibility, ConsolidationRunObservation
from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, ConsolidationUsage
from rag_mcp.services.memory_service import MemoryService
from tests.integration.consolidation_fixtures import StableEmbedding, create_scope
from tests.integration.phase7_fixtures import (
    FakeClock,
    SpyDistiller,
    episodes,
    quiet_tracker,
    reset_activity_state,
    run_maintenance,
    scope_with_policy,
    session_factory_for,
    settle,
    supervisor_for,
)


@pytest_asyncio.fixture(autouse=True)
async def _hermetic_activity(db_session):
    await reset_activity_state(db_session)
    yield
    await reset_activity_state(db_session)


@pytest.mark.asyncio
async def test_observations_append_cumulative_usage_unknown_null_and_seven_day_ttl(db_session, memory_writer_owner):
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner)
    token = await runtime.admit(await create_scope(db_session), trigger='manual')
    usage = ConsolidationUsage()
    usage.record_cache_hit()
    usage.record_transport(prompt_chars=10, completion_chars=20)
    await runtime.observe(token, status='proposing', provider_usage=usage,
                          proposals=[{'justification': 'api_key=sk-abcdefghijklmnopqrstuvwxyz123456'}])
    latest = await runtime.latest_observation(token.run_id)
    assert latest.observation_seq == 2
    assert latest.status == 'proposing'
    assert latest.provider_usage['llm_calls'] == 1
    assert latest.provider_usage['cache_hits'] == 1
    assert latest.provider_usage['input_tokens'] is None
    assert latest.provider_usage['cost_usd'] is None
    assert 'sk-abcdefghijklmnopqrstuvwxyz123456' not in str(latest.proposals)
    assert latest.ttl_expires_at - latest.created_at == timedelta(days=7)
    for statement in ('UPDATE consolidation_runs SET status=\'failed\' WHERE run_id=:run',
                      'DELETE FROM consolidation_runs WHERE run_id=:run'):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(text(statement), {'run': token.run_id})
    await db_session.rollback()
    assert (await db_session.get(ConsolidationEligibility, token.eligibility_id)).state == 'active'
    await db_session.rollback()
    assert await runtime.release(token)
    latest = await runtime.latest_observation(token.run_id)
    assert latest.observation_seq == 3
    assert latest.eligibility_state == 'released'
    history = (await db_session.execute(select(ConsolidationRunObservation).where(
        ConsolidationRunObservation.run_id == token.run_id).order_by(ConsolidationRunObservation.observation_seq))).scalars().all()
    assert [row.observation_seq for row in history] == [1, 2, 3]


@pytest.mark.asyncio
async def test_database_trigger_context_combinations_and_maintenance_lineage_proof(db_session, memory_writer_owner):
    scope = await create_scope(db_session)
    common = {'run_id': uuid4(), 'observation_seq': 1, 'knowledge_scope_id': scope, 'status': 'admitted',
              'trigger': 'support_maintenance', 'execution_context': 'deterministic_propagation',
              'historical_source_refs': [{'memory_id': 1}], 'propagation_trigger': {'event_id': 1, 'proof': {'revoked': True}},
              'input_event_ids': [], 'window': None}
    row = ConsolidationRunObservation(**common)
    db_session.add(row)
    await db_session.commit()
    for patch in ({'execution_context': 'distiller_window'}, {'historical_source_refs': []},
                  {'propagation_trigger': {}}, {'propagation_trigger': None},
                  {'propagation_trigger': {'event_id': 1, 'proof': None}},
                  {'input_event_ids': [1]}, {'window': {'start': 'invalid'}},
                  {'trigger': 'manual'}):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                db_session.add(ConsolidationRunObservation(**{**common, 'run_id': uuid4(), **patch}))
                await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_observation_database_defaults_keep_unknown_usage_null(db_session):
    row = ConsolidationRunObservation(run_id=uuid4(), observation_seq=1,
        knowledge_scope_id=await create_scope(db_session), trigger='manual',
        execution_context='distiller_window', status='admitted')
    db_session.add(row)
    await db_session.commit()
    assert row.provider_usage['source'] == 'unavailable'
    assert all(row.provider_usage[key] is None for key in ('input_tokens', 'output_tokens', 'cost_usd'))
    assert row.provider_usage['llm_calls'] == row.provider_usage['cache_hits'] == 0


@pytest.mark.asyncio
async def test_audit_purge_requires_live_maintenance_and_does_not_release_eligibility(db_session, memory_writer_owner):
    scope = await create_scope(db_session)
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner)
    token = await runtime.admit(scope, trigger='manual')
    now = await db_session.scalar(text('SELECT clock_timestamp()'))
    db_session.add(ConsolidationRunObservation(run_id=token.run_id, observation_seq=2, knowledge_scope_id=scope,
        trigger='manual', execution_context='distiller_window', status='selecting',
        created_at=now - timedelta(days=8), ttl_expires_at=now - timedelta(days=1)))
    await db_session.commit()
    assert await runtime.purge_expired_observations() == 1
    assert (await db_session.get(ConsolidationEligibility, token.eligibility_id)).state == 'active'
    assert await runtime.latest_observation(token.run_id)
    await db_session.rollback()
    assert await runtime.release(token)
    assert await db_session.scalar(text("SELECT count(*) FROM runtime_maintenance_log WHERE purged_consolidation_runs=1")) >= 1


# ---------------------------------------------------------------------------
# T089: every admitted run has a trail, and its report counts match the real
# published authority for each terminal path (US1/US7 acceptance).
# ---------------------------------------------------------------------------

async def _published_authority(runtime, scope_id):
    current = await runtime.read_snapshot(scope_id)
    events, memories = set(), set()
    for group in current.consolidation_state['potential_results'].values():
        if group.get('rolled_back'):
            continue
        events.update(str(item) for item in group.get('event_ids', ()))
        memories.update(str(item) for item in group.get('memory_ids', ()))
    return events, memories


async def _report(db_session, token):
    from rag_mcp.services import consolidation_report

    report = await consolidation_report.get_run_report(db_session, run_id=token.run_id,
                                                       scope_id=token.scope_id)
    await db_session.rollback()
    return report


async def _observe_result(db_session, runtime, token, decisions, outcome, batch):
    await db_session.rollback()
    return await runtime.observe_result(token, decisions, outcome, batch=batch)


@pytest.mark.asyncio
async def test_reports_and_counts_match_published_authority(db_session, memory_writer_owner):
    from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch, run_pipeline
    from rag_mcp.services.consolidation_adjudicator import memory_ref
    from tests.integration.consolidation_commit_fixtures import commit, prepared

    # 1. Normal: a real commit publishes one distilled memory plus its event.
    fixture = await prepared(db_session, memory_writer_owner)
    _service, runtime, token, batch, _context, decisions = fixture
    outcome = await commit(fixture)
    assert outcome.status == 'completed' and outcome.output_event_ids
    await _observe_result(db_session, runtime, token, decisions, outcome, batch)
    report = await _report(db_session, token)
    assert report['status'] == 'succeeded'
    assert report['counts']['accepted'] == 1 and report['counts']['committed'] == 1
    assert report['counts']['rejected'] == 0 and report['counts']['pending'] == 0
    events, memories = await _published_authority(runtime, token.scope_id)
    assert set(report['output_event_ids']) == {str(item) for item in outcome.output_event_ids} <= events
    assert set(report['output_memory_ids']) == {str(item) for item in outcome.output_memory_ids} <= memories
    assert report['pending_result_keys'] == []

    # 2. Every proposal genuinely rejected: no group, no authority change.
    scope = await scope_with_policy(db_session)
    sources = await episodes(db_session, scope, 1)
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner,
                                   memory_service=MemoryService(db_session, embedding_provider=StableEmbedding()))
    token = await runtime.admit(scope, trigger='manual')
    window = await runtime.select_and_seal(token)
    assert window.input_episode_refs

    async def low_confidence_stage(window, distiller, *, current, context, policy, now, provider=None):
        return ProposalBatch([{'proposal_id': 'p0', 'action': 'extract_fact',
                               'source_refs': [memory_ref(current.entries[sources[0]])],
                               'kind': 'semantic', 'content': 'Below threshold conclusion',
                               'confidence': .2, 'evidence_refs': [], 'justification': 'low confidence'}])

    await run_pipeline(runtime, token, distiller=None, propose_stage=low_confidence_stage)
    report = await _report(db_session, token)
    assert report['status'] == 'no_change' and 'all_rejected' in report['degradation_reasons']
    assert report['counts'] == {'proposed': 1, 'accepted': 0, 'rejected': 1, 'committed': 0,
                                'pending': 0, 'failed': 0, 'unprocessed': 0}
    assert report['output_event_ids'] == [] and report['output_memory_ids'] == []

    # 3. Degraded: the model package failed; only deterministic rules ran.
    scope = await scope_with_policy(db_session)
    await episodes(db_session, scope, 1)
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner,
                                   memory_service=MemoryService(db_session, embedding_provider=StableEmbedding()))
    token = await runtime.admit(scope, trigger='idle')

    async def degraded_stage(window, distiller, *, current, context, policy, now, provider=None):
        return ProposalBatch((), degraded=True, degradation_reasons=('MODEL_SCHEMA_INVALID',))

    await run_pipeline(runtime, token, distiller=None, propose_stage=degraded_stage)
    report = await _report(db_session, token)
    assert report['status'] == 'degraded'
    assert 'MODEL_SCHEMA_INVALID' in report['degradation_reasons']
    assert report['counts']['proposed'] == 0 and report['counts']['committed'] == 0
    assert report['output_event_ids'] == []


@pytest.mark.asyncio
async def test_partial_and_failed_reports_never_claim_published_output(db_session, memory_writer_owner, monkeypatch):
    from tests.integration.consolidation_commit_fixtures import commit, prepared

    # Independent groups: the first publishes, the second stays pending -> partial.
    fixture = await prepared(db_session, memory_writer_owner, count=2, shared=False)
    service, runtime, token, batch, _context, decisions = fixture
    assert len(decisions.groups) == 2
    original = service.projections._materialize_dense
    calls = []

    async def fail_second(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError('injected adapter failure')
        return await original(*args, **kwargs)

    monkeypatch.setattr(service.projections, '_materialize_dense', fail_second)
    outcome = await commit(fixture)
    assert outcome.status == 'pending' and outcome.pending_result_keys
    await _observe_result(db_session, runtime, token, decisions, outcome, batch)
    report = await _report(db_session, token)
    assert report['status'] == 'partial'
    assert report['counts']['accepted'] == 2 and report['counts']['committed'] == 1
    assert report['counts']['pending'] == 1
    events, _ = await _published_authority(runtime, token.scope_id)
    assert set(report['output_event_ids']) == {str(item) for item in outcome.output_event_ids} <= events
    assert report['pending_result_keys'] == list(outcome.pending_result_keys)

    # A rolled-back group is a failure and publishes nothing.
    monkeypatch.undo()
    fixture = await prepared(db_session, memory_writer_owner)
    service, runtime, token, batch, _context, decisions = fixture

    async def broken_relation(*args, **kwargs):
        raise RuntimeError('injected relation failure')

    monkeypatch.setattr(service.projections, '_materialize_relation', broken_relation)
    outcome = await commit(fixture)
    assert outcome.status == 'rolled_back' and not outcome.output_event_ids
    await _observe_result(db_session, runtime, token, decisions, outcome, batch)
    report = await _report(db_session, token)
    assert report['status'] == 'failed'
    assert report['counts']['accepted'] == 1 and report['counts']['committed'] == 0
    assert report['output_event_ids'] == []
    events, memories = await _published_authority(runtime, token.scope_id)
    assert events == set() and memories == set()


@pytest.mark.asyncio
async def test_usage_report_keeps_actual_cache_and_unknown_separate(db_session, memory_writer_owner):
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner)
    token = await runtime.admit(await create_scope(db_session), trigger='manual')
    usage = ConsolidationUsage()
    usage.record_cache_hit()
    usage.record_transport(prompt_chars=10, completion_chars=20, input_tokens=5, output_tokens=7, cost_usd=.5)
    await runtime.observe(token, status='proposing', provider_usage=usage)
    report = await _report(db_session, token)
    assert report['provider_usage']['cache_hits'] == 1
    assert report['provider_usage']['llm_calls'] == 1
    assert report['provider_usage']['input_tokens'] == 5
    assert report['provider_usage']['source'] == 'actual'
    usage = ConsolidationUsage()
    usage.record_transport(prompt_chars=3, completion_chars=4)
    await runtime.observe(token, status='proposing', provider_usage=usage)
    report = await _report(db_session, token)
    assert report['provider_usage']['source'] == 'unavailable'
    assert report['provider_usage']['input_tokens'] is None
    assert report['provider_usage']['output_tokens'] is None
    assert report['provider_usage']['cost_usd'] is None
    assert report['provider_usage']['llm_calls'] == 1


@pytest.mark.asyncio
async def test_guarded_ttl_purge_keeps_lineage_and_reports_honest_counts(db_session, engine,
                                                                         memory_writer_owner):
    from tests.integration.consolidation_commit_fixtures import commit, prepared

    fixture = await prepared(db_session, memory_writer_owner)
    _service, runtime, token, batch, _context, decisions = fixture
    outcome = await commit(fixture)
    await _observe_result(db_session, runtime, token, decisions, outcome, batch)
    now = await db_session.scalar(text('SELECT clock_timestamp()'))
    db_session.add(ConsolidationRunObservation(
        run_id=token.run_id, observation_seq=99, knowledge_scope_id=token.scope_id, trigger='manual',
        execution_context='distiller_window', status='selecting',
        created_at=now - timedelta(days=8), ttl_expires_at=now - timedelta(days=1)))
    await db_session.commit()
    before = await db_session.scalar(text(
        'SELECT count(*) FROM consolidation_runs WHERE run_id=:id'), {'id': str(token.run_id)})

    supervisor = supervisor_for(engine, memory_writer_owner, distiller=SpyDistiller())
    report = await run_maintenance(engine, memory_writer_owner, supervisor, scopes=[])
    await supervisor.shutdown()
    assert report['purged_consolidation_observations'] == 1
    after = await db_session.scalar(text(
        'SELECT count(*) FROM consolidation_runs WHERE run_id=:id'), {'id': str(token.run_id)})
    assert after == before - 1
    assert (await db_session.scalar(text(
        'SELECT count(*) FROM runtime_maintenance_log WHERE purged_consolidation_runs=1'))) >= 1
    # Authority, published output and retained identity survive the purge.
    events, memories = await _published_authority(runtime, token.scope_id)
    assert events and memories
    assert (await db_session.scalar(text(
        'SELECT count(*) FROM consolidation_eligibilities WHERE run_id=:id'), {'id': str(token.run_id)})) >= 1
    report_body = await _report(db_session, token)
    assert report_body['status'] == 'succeeded' and report_body['output_event_ids']
    # The maintenance role guard still rejects an ordinary-role delete.
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(text('DELETE FROM consolidation_runs WHERE run_id=:id'),
                                     {'id': str(token.run_id)})
    await db_session.rollback()


@pytest.mark.asyncio
async def test_disabled_support_maintenance_runs_a_real_honest_wave(db_session, engine, memory_writer_owner):
    from rag_mcp.orchestration.consolidation_pipeline import support_maintenance_context

    scope = await create_scope(db_session, enabled=False)
    identifiers = await episodes(db_session, scope, 2)
    # The proof is only current while its cause is genuinely no longer live.
    governance = MemoryService(db_session, embedding_provider=StableEmbedding())
    await governance.govern('retire', scope_id=scope, actor='management', memory_id=identifiers[0],
                            reason='T089 revoked support')
    supervised = supervisor_for(engine, memory_writer_owner, distiller=SpyDistiller())
    context = support_maintenance_context(
        historical_source_refs=[{'memory_id': identifiers[0], 'source_event_id': 1, 'state_event_id': 1,
                                 'content_hash': 'a' * 64, 'observed_at': datetime.now(UTC).isoformat()}],
        propagation_trigger={'kind': 'evidence_revocation', 'event_id': 7, 'evidence_id': None,
                             'version': '1', 'observed_at': datetime.now(UTC).isoformat(),
                             'target_ref': {'memory_id': identifiers[1]},
                             'proof': {'kind': 'evidence_revocation', 'memory_id': identifiers[0]}})
    token = await supervised.submit(scope, trigger='support_maintenance', context=context)
    await settle(supervised, scope)
    assert supervised.distiller.calls == []
    await supervised.shutdown()
    report = await _report(db_session, token)
    assert report['trigger'] == 'support_maintenance'
    assert report['execution_context'] == 'deterministic_propagation'
    assert report['window'] is None and report['input_event_ids'] == []
    assert report['historical_source_refs'] and report['propagation_trigger']['proof']
    assert report['status'] in ('no_change', 'succeeded')
    assert report['counts']['committed'] == 0 or report['counts']['committed'] == report['counts']['accepted']
    assert (await db_session.scalar(text(
        'SELECT count(*) FROM consolidation_eligibilities WHERE run_id=:id AND state=\'released\''),
        {'id': str(token.run_id)})) == 1


@pytest.mark.asyncio
async def test_cross_process_volume_hint_is_a_single_shot_nudge(db_session, engine, memory_writer_owner):
    from rag_mcp.runtime.activity import ActivitySnapshot, publish_activity
    from rag_mcp.runtime.instance_registry import InstanceRegistryService

    tracker = quiet_tracker(FakeClock())
    scope = await scope_with_policy(db_session, policy={
        'consolidation_enabled': True, 'consolidation': {'volume_threshold': 1}})
    await episodes(db_session, scope, 1)
    supervisor = supervisor_for(engine, memory_writer_owner, distiller=SpyDistiller(), activity=tracker)
    peer = uuid4()
    registration = await InstanceRegistryService(session_factory_for(engine)).register(
        peer, 'writer', 'mcp', expiry_window_s=300)
    assert registration.registered
    await publish_activity(db_session, identity=(peer, 'mcp', 'writer'),
                           snapshot=ActivitySnapshot(0, None, 0, 0), volume_hints=[scope])
    await db_session.commit()

    first = await run_maintenance(engine, memory_writer_owner, supervisor, scopes=[scope], activity=tracker)
    assert first['admitted'] and first['admitted'][0]['trigger'] == 'volume'
    await settle(supervisor, scope)
    second = await run_maintenance(engine, memory_writer_owner, supervisor, scopes=[scope], activity=tracker)
    # The same published hint is never evaluated twice: a nudge, not a queue. A
    # later tick may still admit the scope as an independent idle observation.
    assert second['admitted'] == [] or second['admitted'][0]['trigger'] == 'idle'
    await supervisor.shutdown()
