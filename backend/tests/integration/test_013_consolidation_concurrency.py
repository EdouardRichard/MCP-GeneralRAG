"""T079 (US1): bounded scope workers and real provider capacity.

Scope workers are capped at two with independent DB sessions; the real
synchronous provider pool is separately capped at two, and a timed-out or
cancelled waiter keeps its provider slot until the underlying call really
returns. Cancellation, worker faults, lease loss and generation takeover append
an honest terminal outcome and release exactly the matching eligibility — a
later generation is never touched (or masked) by a late old-generation result.
"""
import asyncio
import threading

import pytest
import pytest_asyncio
from sqlalchemy import text

from rag_mcp.services.consolidation_runtime import (
    ConsolidationRuntime,
    ConsolidationRuntimeError,
    DistillerProvider,
)
from rag_mcp.services.memory_service import MemoryService
from tests.integration.consolidation_fixtures import StableEmbedding
from tests.integration.memory_acceptance import writer_owner
from tests.integration.phase7_fixtures import (
    SpyDistiller,
    episodes,
    reset_activity_state,
    scope_with_policy,
    settle,
    supervisor_for,
)


@pytest_asyncio.fixture(autouse=True)
async def _hermetic_activity(db_session):
    await reset_activity_state(db_session)
    yield
    await reset_activity_state(db_session)


async def _wait_for_threads(agent, count, timeout=30):
    for _ in range(int(timeout * 50)):
        if len(agent.calls) >= count:
            return
        await asyncio.sleep(.02)
    raise AssertionError(f'only {len(agent.calls)} provider calls entered, expected {count}')


@pytest.mark.asyncio
async def test_real_provider_pool_is_separately_capped_at_two():
    async def scenario():
        gate = threading.Event()
        agent = SpyDistiller(gate=gate)
        provider = DistillerProvider()
        first = asyncio.ensure_future(provider.run(agent, {'window': {'a': 1}}, timeout_s=30))
        second = asyncio.ensure_future(provider.run(agent, {'window': {'a': 1}}, timeout_s=30))
        await _wait_for_threads(agent, 2)
        # A third real call is refused boundedly instead of waiting in an executor queue.
        refused = await provider.run(agent, {'window': {'a': 1}}, timeout_s=5)
        assert refused.reason == 'PROVIDER_CAPACITY' and len(agent.calls) == 2
        gate.set()
        outcomes = await asyncio.gather(first, second)
        assert all(outcome.reason is None for outcome in outcomes)
        accepted = await provider.run(agent, {'window': {'a': 1}}, timeout_s=5)
        assert accepted.reason is None and len(agent.calls) == 3
        assert len(agent.calls) == 3

    await scenario()


@pytest.mark.asyncio
async def test_timed_out_waiter_keeps_its_provider_slot_until_the_call_returns():
    async def scenario():
        gate = threading.Event()
        agent = SpyDistiller(gate=gate)
        provider = DistillerProvider()
        first = await provider.run(agent, {'window': {'a': 1}}, timeout_s=.1)
        second = await provider.run(agent, {'window': {'a': 1}}, timeout_s=.1)
        assert (first.reason, second.reason) == ('PROVIDER_TIMEOUT', 'PROVIDER_TIMEOUT')
        # Both abandoned threads are still inside the real synchronous call, so
        # both slots stay occupied: a third attempt is refused, not queued.
        await _wait_for_threads(agent, 2)
        refused = await provider.run(agent, {'window': {'a': 1}}, timeout_s=5)
        assert refused.reason == 'PROVIDER_CAPACITY' and len(agent.calls) == 2
        gate.set()
        for _ in range(200):
            probe = await provider.run(agent, {'window': {'a': 1}}, timeout_s=2)
            if probe.reason is None:
                break
            await asyncio.sleep(.05)
        assert probe.reason is None and len(agent.calls) == 3

    await scenario()


@pytest.mark.asyncio
async def test_two_scope_workers_use_independent_sessions_and_reject_the_third(db_session, engine):
    from unittest import mock

    async with writer_owner(engine) as owner:
        scopes = []
        for _ in range(3):
            scope = await scope_with_policy(db_session)
            await episodes(db_session, scope, 1)
            scopes.append(scope)
        supervisor = supervisor_for(engine, owner, distiller=SpyDistiller(), capacity=2)
        sessions, barrier = [], asyncio.Event()
        original = ConsolidationRuntime.select_and_seal

        async def blocked(self, token):
            sessions.append(id(self.session))
            if len(sessions) >= 2:
                barrier.set()
            await barrier.wait()
            return await original(self, token)

        with mock.patch.object(ConsolidationRuntime, 'select_and_seal', blocked):
            first = await supervisor.submit(scopes[0], trigger='manual')
            second = await supervisor.submit(scopes[1], trigger='manual')
            await asyncio.wait_for(barrier.wait(), 60)
            assert len(set(sessions)) == 2
            with pytest.raises(ConsolidationRuntimeError) as refused:
                await supervisor.submit(scopes[2], trigger='manual')
            assert refused.value.code == 'CONSOLIDATION_CAPACITY_EXCEEDED'
            assert (await db_session.scalar(text(
                'SELECT count(*) FROM consolidation_eligibilities WHERE knowledge_scope_id=:s'),
                {'s': scopes[2]})) == 0
            assert first.run_id != second.run_id
            await asyncio.gather(settle(supervisor, scopes[0]), settle(supervisor, scopes[1]))
        assert supervisor.active_run(scopes[0]) is None and supervisor.active_run(scopes[1]) is None
        third = await supervisor.submit(scopes[2], trigger='manual')
        await settle(supervisor, scopes[2])
        assert third.scope_id == scopes[2]
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_cancelled_worker_appends_interrupted_and_releases_only_its_token(db_session, engine):
    async with writer_owner(engine) as owner:
        scope = await scope_with_policy(db_session)
        await episodes(db_session, scope, 1)
        gate = threading.Event()
        distiller = SpyDistiller(gate=gate)
        supervisor = supervisor_for(engine, owner, distiller=distiller)
        token = await supervisor.submit(scope, trigger='manual')
        await _wait_for_threads(distiller, 1)
        task = supervisor.worker_task(scope)
        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            gate.set()
        assert supervisor.active_run(scope) is None
        assert (await db_session.scalar(text(
            'SELECT state FROM consolidation_eligibilities WHERE eligibility_id=:id'),
            {'id': str(token.eligibility_id)})) == 'released'
        row = (await db_session.execute(text(
            'SELECT status, degradation_reasons, eligibility_state FROM consolidation_runs '
            'WHERE run_id=:id ORDER BY observation_seq DESC LIMIT 1'), {'id': str(token.run_id)})).one()
        assert row.status == 'interrupted' and row.eligibility_state == 'released'
        assert any('CANCEL' in reason or 'INTERRUPT' in reason for reason in row.degradation_reasons)

        # The freed slot is reusable and a fresh run gets a new generation.
        again = await supervisor.submit(scope, trigger='manual')
        assert again.eligibility_version == token.eligibility_version + 1
        await settle(supervisor, scope)
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_generation_takeover_blocks_old_commit_release_and_late_terminal(db_session, engine):
    async with writer_owner(engine) as owner:
        scope = await scope_with_policy(db_session)
        await episodes(db_session, scope, 1)
        service = MemoryService(db_session, embedding_provider=StableEmbedding())
        runtime = ConsolidationRuntime(db_session, owner=owner, memory_service=service)
        old = await runtime.admit(scope, trigger='manual')
        await db_session.execute(text(
            "UPDATE consolidation_eligibilities SET expires_at=clock_timestamp()-interval '1 minute' "
            'WHERE eligibility_id=:id'), {'id': str(old.eligibility_id)})
        await db_session.commit()

        # An expired token cannot be revived by its own heartbeat.
        with pytest.raises(ConsolidationRuntimeError) as lost:
            await runtime.heartbeat(old)
        assert lost.value.code == 'ELIGIBILITY_LOST'

        replacement = await runtime.takeover(old)
        assert replacement.run_id == old.run_id and replacement.eligibility_id != old.eligibility_id
        assert replacement.eligibility_version == old.eligibility_version + 1

        # The old generation cannot commit, observe or release the successor.
        with pytest.raises(ConsolidationRuntimeError):
            async with runtime.commit_fence(old):
                pass
        with pytest.raises(ConsolidationRuntimeError):
            await runtime.observe(old, status='succeeded')
        assert await runtime.release(old) is False
        assert (await db_session.scalar(text(
            'SELECT state FROM consolidation_eligibilities WHERE eligibility_id=:id'),
            {'id': str(replacement.eligibility_id)})) == 'active'
        await db_session.rollback()

        # A late old-generation terminal record cannot mask the newer generation.
        masked = await runtime.finalize_terminal(old, status='interrupted',
                                                 degradation_reasons=['WRITER_LEASE_LOST'])
        assert masked is None
        latest = (await db_session.execute(text(
            'SELECT status, eligibility_version FROM consolidation_runs WHERE run_id=:id '
            'ORDER BY observation_seq DESC LIMIT 1'), {'id': str(old.run_id)})).one()
        assert (latest.status, latest.eligibility_version) == ('admitted', replacement.eligibility_version)
        await db_session.rollback()
        assert await runtime.release(replacement) is True


@pytest.mark.asyncio
async def test_lease_loss_terminates_the_run_without_touching_a_successor(db_session, engine):
    async with writer_owner(engine) as owner:
        scope = await scope_with_policy(db_session)
        await episodes(db_session, scope, 1)
        gate = threading.Event()
        distiller = SpyDistiller(gate=gate)
        supervisor = supervisor_for(engine, owner, distiller=distiller)
        token = await supervisor.submit(scope, trigger='manual')
        await _wait_for_threads(distiller, 1)
        # The writer lease disappears while the model call is in flight.
        await db_session.execute(text(
            "UPDATE writer_lease SET state='released', released_at=clock_timestamp() WHERE lease_id=:id"),
            {'id': owner.lease_id})
        await db_session.commit()
        gate.set()
        await settle(supervisor, scope)
        assert supervisor.active_run(scope) is None
        latest = (await db_session.execute(text(
            'SELECT status, degradation_reasons, eligibility_state FROM consolidation_runs WHERE run_id=:id '
            'ORDER BY observation_seq DESC LIMIT 1'), {'id': str(token.run_id)})).one()
        assert latest.status in ('interrupted', 'failed')
        assert latest.eligibility_state == 'released'
        # The in-flight model result was never adjudicated or published.
        assert (await db_session.scalar(text(
            'SELECT count(*) FROM memory_events WHERE knowledge_scope_id=:s '
            "AND event_type IN ('assert','revise')"), {'s': scope})) == 1
        assert (await db_session.scalar(text(
            'SELECT state FROM consolidation_eligibilities WHERE eligibility_id=:id'),
            {'id': str(token.eligibility_id)})) == 'released'
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_worker_fault_releases_capacity_and_reports_failed(db_session, engine):
    async with writer_owner(engine) as owner:
        scope = await scope_with_policy(db_session)
        await episodes(db_session, scope, 1)
        supervisor = supervisor_for(engine, owner, distiller=SpyDistiller())
        original = ConsolidationRuntime.select_and_seal

        async def broken(self, token):
            raise RuntimeError('foreign-scope password=secret-value')

        ConsolidationRuntime.select_and_seal = broken
        try:
            token = await supervisor.submit(scope, trigger='manual')
            await settle(supervisor, scope)
        finally:
            ConsolidationRuntime.select_and_seal = original
        latest = (await db_session.execute(text(
            'SELECT status, degradation_reasons, eligibility_state FROM consolidation_runs WHERE run_id=:id '
            'ORDER BY observation_seq DESC LIMIT 1'), {'id': str(token.run_id)})).one()
        assert latest.status == 'failed' and latest.eligibility_state == 'released'
        assert not any('secret-value' in reason for reason in latest.degradation_reasons)
        assert supervisor.active_run(scope) is None
        follow = await supervisor.submit(scope, trigger='manual')
        await settle(supervisor, scope)
        assert follow.eligibility_version == token.eligibility_version + 1
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_total_deadline_interrupts_and_frees_the_slot(db_session, engine):
    async with writer_owner(engine) as owner:
        scope = await scope_with_policy(db_session)
        await episodes(db_session, scope, 1)
        gate = threading.Event()
        supervisor = supervisor_for(engine, owner, distiller=SpyDistiller(gate=gate),
                                    total_deadline_seconds=10)
        token = await supervisor.submit(scope, trigger='manual')
        await _wait_for_threads(supervisor.distiller, 1, timeout=60)
        try:
            await settle(supervisor, scope, timeout=60)
        finally:
            gate.set()
        latest = (await db_session.execute(text(
            'SELECT status, degradation_reasons, eligibility_state FROM consolidation_runs WHERE run_id=:id '
            'ORDER BY observation_seq DESC LIMIT 1'), {'id': str(token.run_id)})).one()
        assert latest.status == 'interrupted' and latest.eligibility_state == 'released'
        assert 'CONSOLIDATION_RUN_TIMEOUT' in latest.degradation_reasons
        assert supervisor.active_run(scope) is None
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_expired_eligibility_recovery_uses_a_new_generation(db_session, engine):
    async with writer_owner(engine) as owner:
        scope = await scope_with_policy(db_session)
        await episodes(db_session, scope, 1)
        service = MemoryService(db_session, embedding_provider=StableEmbedding())
        runtime = ConsolidationRuntime(db_session, owner=owner, memory_service=service)
        stale = await runtime.admit(scope, trigger='manual')
        await db_session.execute(text(
            "UPDATE consolidation_eligibilities SET expires_at=clock_timestamp()-interval '5 minutes',"
            " state='expired' WHERE eligibility_id=:id"), {'id': str(stale.eligibility_id)})
        await db_session.commit()
        recovered = await runtime.takeover(stale)
        assert recovered.run_id == stale.run_id
        assert recovered.eligibility_version > stale.eligibility_version
        assert await runtime.release(recovered) is True
        assert (await db_session.scalar(text(
            'SELECT state FROM consolidation_eligibilities WHERE state=\'active\' '
            'AND knowledge_scope_id=:s'), {'s': scope})) is None
