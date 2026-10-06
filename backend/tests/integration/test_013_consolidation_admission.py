from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.integration.consolidation_fixtures import create_scope


@pytest.mark.asyncio
async def test_two_scopes_independent_same_scope_busy_and_database_uniqueness(db_session, memory_writer_owner):
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, ConsolidationRuntimeError
    from rag_mcp.models.consolidation_run import ConsolidationEligibility
    one, two = await create_scope(db_session), await create_scope(db_session)
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner)
    token = await runtime.admit(one, trigger='manual')
    second = await runtime.admit(two, trigger='idle')
    assert token.scope_id != second.scope_id
    with pytest.raises(ConsolidationRuntimeError) as busy:
        await runtime.admit(one, trigger='volume')
    assert busy.value.code == 'CONSOLIDATION_BUSY'
    assert busy.value.run_id == token.run_id
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            row = await db_session.get(ConsolidationEligibility, token.eligibility_id)
            db_session.add(ConsolidationEligibility(**{column.name: getattr(row, column.name)
                for column in row.__table__.columns if column.name not in ('eligibility_id', 'eligibility_version')},
                eligibility_id=uuid4(), eligibility_version=99))
            await db_session.flush()
    await db_session.rollback()
    assert await runtime.release(token)
    assert await runtime.release(second)


@pytest.mark.asyncio
async def test_ttl_heartbeat_takeover_fences_every_token_field(db_session, memory_writer_owner):
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, ConsolidationRuntimeError
    from rag_mcp.models.consolidation_run import ConsolidationEligibility
    scope = await create_scope(db_session)
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner)
    first = await runtime.admit(scope, trigger='manual')
    row = await db_session.get(ConsolidationEligibility, first.eligibility_id)
    assert row.expires_at - row.renewed_at == timedelta(seconds=120)
    assert runtime.heartbeat_interval_seconds == 20
    await db_session.rollback()
    renewed = await runtime.heartbeat(first)
    assert renewed.eligibility_version == first.eligibility_version
    await db_session.execute(text('UPDATE consolidation_eligibilities SET expires_at=clock_timestamp()-interval \'1 second\' WHERE eligibility_id=:id'), {'id': first.eligibility_id})
    await db_session.commit()
    second = await runtime.takeover(first)
    assert second.run_id == first.run_id
    assert second.eligibility_id != first.eligibility_id
    assert second.eligibility_version == first.eligibility_version + 1
    assert not await runtime.release(first)
    for stale in (first, replace(second, run_id=uuid4()), replace(second, holder_instance_id=uuid4()),
                  replace(second, writer_lease_id=second.writer_lease_id + 1), replace(second, scope_id=scope + 1)):
        with pytest.raises(ConsolidationRuntimeError, match='ELIGIBILITY_LOST'):
            async with runtime.commit_fence(stale):
                pytest.fail('stale token entered commit')
        await db_session.rollback()
    async with runtime.commit_fence(second) as fence:
        await fence.validate_before_publish()
    assert await runtime.release(second)


@pytest.mark.asyncio
async def test_final_fence_uses_db_clock_and_requires_live_writer_lease(db_session, memory_writer_owner):
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, ConsolidationRuntimeError
    scope = await create_scope(db_session)
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner)
    token = await runtime.admit(scope, trigger='manual')
    with pytest.raises(ConsolidationRuntimeError, match='ELIGIBILITY_LOST'):
        async with runtime.commit_fence(token) as fence:
            await db_session.execute(text('UPDATE consolidation_eligibilities SET expires_at=clock_timestamp()+interval \'0.05 second\' WHERE eligibility_id=:id'), {'id': token.eligibility_id})
            await db_session.execute(text('SELECT pg_sleep(0.1)'))
            await fence.validate_before_publish()
    await db_session.execute(text('UPDATE writer_lease SET expires_at=clock_timestamp()-interval \'1 second\' WHERE lease_id=:id'), {'id': memory_writer_owner.lease_id})
    await db_session.commit()
    with pytest.raises(ConsolidationRuntimeError, match='WRITER_LEASE_LOST'):
        async with runtime.commit_fence(token):
            pytest.fail('expired lease entered commit')
    await db_session.rollback()


@pytest.mark.asyncio
async def test_scope_lock_contention_returns_immediately_and_disabled_admission_rejects(db_session, engine, memory_writer_owner):
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, ConsolidationRuntimeError
    scope = await create_scope(db_session)
    disabled = await create_scope(db_session, enabled=False)
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner)
    factory = async_sessionmaker(engine)
    async with factory() as other:
        await other.execute(text('SELECT pg_advisory_xact_lock(:scope)'), {'scope': scope})
        with pytest.raises(ConsolidationRuntimeError, match='CONSOLIDATION_SCOPE_WRITE_BUSY'):
            await runtime.admit(scope, trigger='manual')
        await db_session.rollback()
    with pytest.raises(ConsolidationRuntimeError, match='CONSOLIDATION_DISABLED'):
        await runtime.admit(disabled, trigger='manual')
    await db_session.rollback()
    with pytest.raises(ConsolidationRuntimeError, match='TRUSTED_CONTEXT_REQUIRED'):
        await runtime.admit(scope, trigger='support_maintenance')


@pytest.mark.asyncio
async def test_takeover_after_audit_ttl_preserves_run_and_observation_sequence(db_session, memory_writer_owner):
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, EligibilityToken
    from rag_mcp.models.consolidation_run import ConsolidationEligibility, ConsolidationRunObservation
    scope = await create_scope(db_session)
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner)
    now = await db_session.scalar(text('SELECT clock_timestamp()'))
    token = EligibilityToken(uuid4(), scope, uuid4(), memory_writer_owner.holder_instance_id, memory_writer_owner.lease_id, 1)
    db_session.add(ConsolidationEligibility(eligibility_id=token.eligibility_id, knowledge_scope_id=scope,
        run_id=token.run_id, holder_instance_id=token.holder_instance_id, writer_lease_id=token.writer_lease_id,
        eligibility_version=1, observation_seq_high_water=5, acquired_at=now-timedelta(days=8), renewed_at=now-timedelta(days=8),
        expires_at=now-timedelta(days=8), state='active'))
    db_session.add(ConsolidationRunObservation(run_id=token.run_id, observation_seq=5, knowledge_scope_id=scope,
        eligibility_id=token.eligibility_id, trigger='manual', execution_context='distiller_window', status='interrupted',
        created_at=now-timedelta(days=8), ttl_expires_at=now-timedelta(days=1)))
    await db_session.commit()
    assert await runtime.purge_expired_observations() == 1
    assert await runtime.latest_observation(token.run_id) is None
    await db_session.rollback()
    renewed = await runtime.takeover(token)
    assert renewed.run_id == token.run_id and renewed.eligibility_version == 2
    assert (await runtime.latest_observation(token.run_id)).observation_seq > 5
    await db_session.rollback()
    assert await runtime.release(renewed)


@pytest.mark.asyncio
@pytest.mark.parametrize('caller_work', ['flushed_orm', 'raw_sql', 'read'])
async def test_control_transactions_reject_caller_owned_transactions(db_session, memory_writer_owner, caller_work):
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, ConsolidationRuntimeError

    scope = await create_scope(db_session)
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner)
    token = await runtime.admit(scope, trigger='manual')
    row = await db_session.get(KnowledgeScope, scope)
    original_name = row.name
    if caller_work == 'flushed_orm':
        row.name = 'caller-owned change'
        await db_session.flush()
    elif caller_work == 'raw_sql':
        await db_session.execute(text('UPDATE knowledge_scopes SET name=:name WHERE scope_id=:scope'),
                                 {'name': 'caller-owned change', 'scope': scope})
    assert not (db_session.new or db_session.dirty or db_session.deleted)
    with pytest.raises(ConsolidationRuntimeError, match='CONSOLIDATION_TRANSACTION_BUSY'):
        await runtime.heartbeat(token)
    assert db_session.in_transaction()
    await db_session.rollback()
    assert await db_session.scalar(select(KnowledgeScope.name).where(KnowledgeScope.scope_id == scope)) == original_name
    await db_session.rollback()
    assert await runtime.heartbeat(token) == token
    assert await runtime.release(token)
