from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from tests.integration.consolidation_fixtures import create_scope


@pytest.mark.asyncio
async def test_observations_append_cumulative_usage_unknown_null_and_seven_day_ttl(db_session, memory_writer_owner):
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, ConsolidationUsage
    from rag_mcp.models.consolidation_run import ConsolidationRunObservation, ConsolidationEligibility
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
    from rag_mcp.models.consolidation_run import ConsolidationRunObservation
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
    from rag_mcp.models.consolidation_run import ConsolidationRunObservation
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
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
    from rag_mcp.models.consolidation_run import ConsolidationRunObservation, ConsolidationEligibility
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
