"""T078 (US1): the three triggers share one admission and never queue.

Manual, idle and volume all compete for the same per-scope DB eligibility and
the same bounded supervisor capacity. Automatic triggers require *current*
evidence: live idle conditions, no real foreground/ingestion/rebuild work, a
fresh cross-process observation, the domain gate and a re-verified real pending
count. A busy/full hint is discarded with a reason — never retained as a future
job — and manual bypasses idle only.
"""
import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from rag_mcp.runtime.activity import (
    STALE_AFTER_SECONDS,
    ActivitySnapshot,
    RuntimeActivity,
    admission_activity_reason,
    get_runtime_activity,
    mark_volume_hint,
    observe_peers,
    peek_volume_hints,
    publish_activity,
)
from rag_mcp.runtime.instance_registry import InstanceRegistryService
from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, ConsolidationRuntimeError
from rag_mcp.services.memory_service import MemoryService
from tests.integration.consolidation_fixtures import StableEmbedding
from tests.integration.memory_acceptance import writer_owner
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


def reasons(report):
    return [skip['reason'] for skip in report['skipped']]


@pytest.mark.asyncio
async def test_manual_idle_and_volume_share_one_admission(db_session, engine):
    async with writer_owner(engine) as owner:
        scope = await scope_with_policy(db_session)
        await episodes(db_session, scope, 1)
        supervisor = supervisor_for(engine, owner, distiller=SpyDistiller())
        manual = await supervisor.submit(scope, trigger='manual')
        for trigger in ('idle', 'volume'):
            with pytest.raises(ConsolidationRuntimeError) as blocked:
                await supervisor.submit(scope, trigger=trigger)
            assert blocked.value.code == 'CONSOLIDATION_BUSY'
            assert blocked.value.run_id == manual.run_id
        await settle(supervisor, scope)
        # Only one run exists for the scope: losers never queued a second run.
        assert (await db_session.scalar(text(
            'SELECT count(*) FROM consolidation_eligibilities WHERE knowledge_scope_id=:s'),
            {'s': scope})) == 1
        fresh = await supervisor.submit(scope, trigger='idle')
        assert fresh.eligibility_version == 2
        await settle(supervisor, scope)
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_manual_bypasses_idle_but_automatic_requires_it(db_session, engine):
    async with writer_owner(engine) as owner:
        clock = FakeClock()
        tracker = RuntimeActivity(monotonic=clock)
        scope = await scope_with_policy(db_session)
        await episodes(db_session, scope, 1)
        supervisor = supervisor_for(engine, owner, distiller=SpyDistiller(), activity=tracker)

        # A real foreground request is in flight: manual still admits, automatic skips.
        tracker.begin()
        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker)
        assert reasons(report) == ['foreground_activity'] and report['admitted'] == []
        manual = await supervisor.submit(scope, trigger='manual')
        assert manual.scope_id == scope
        await settle(supervisor, scope)
        tracker.end()
        assert tracker.snapshot().foreground_active == 0

        # Manual bypassed idle only: with activity cleared but no idle window yet
        # (the clock has not advanced since the request), automatic still waits.
        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker)
        assert reasons(report) == ['idle_seconds_insufficient'] and report['admitted'] == []
        clock.now += 120
        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker)
        assert report['admitted'] and report['admitted'][0]['trigger'] == 'idle'
        await settle(supervisor, scope)
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_automatic_admission_requires_fresh_quiet_activity(db_session, engine):
    async with writer_owner(engine) as owner:
        clock = FakeClock()
        tracker = quiet_tracker(clock)
        scope = await scope_with_policy(db_session)
        await episodes(db_session, scope, 1)
        supervisor = supervisor_for(engine, owner, distiller=SpyDistiller(), activity=tracker)

        peer = uuid4()
        registration = await InstanceRegistryService(session_factory_for(engine)).register(
            peer, 'reader', 'mcp', expiry_window_s=300)
        assert registration.registered

        async def publish(*, snapshot=None, when=None):
            await publish_activity(db_session, identity=(peer, 'mcp', 'reader'),
                                   snapshot=snapshot or ActivitySnapshot(0, None, 0, 0), now=when)
            await db_session.commit()

        # A fresh peer with a real foreground request blocks automatic admission.
        await publish(snapshot=ActivitySnapshot(2, 0.0, 0, 0))
        peers = await observe_peers(db_session, exclude_instance_id=None, stale_after_s=STALE_AFTER_SECONDS)
        assert any(not row.stale and row.foreground_active == 2 for row in peers)
        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker)
        assert reasons(report) == ['foreground_activity'] and report['admitted'] == []

        # A stale publication can never prove idleness: conservative skip.
        await publish(when=datetime.now(UTC) - timedelta(seconds=STALE_AFTER_SECONDS + 30))
        stale = await observe_peers(db_session, exclude_instance_id=None, stale_after_s=STALE_AFTER_SECONDS)
        assert any(row.stale for row in stale)
        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker)
        assert reasons(report) == ['activity_observation_stale'] and report['admitted'] == []

        # Ingestion and rebuild liveness are skipped with their own reasons.
        for snapshot, reason in ((ActivitySnapshot(0, None, 1, 0), 'ingestion_activity'),
                                 (ActivitySnapshot(0, None, 0, 1), 'rebuild_activity')):
            await publish(snapshot=snapshot)
            report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker)
            assert reasons(report) == [reason] and report['admitted'] == []

        # A released peer signal no longer blocks anything.
        await publish(snapshot=ActivitySnapshot(3, 0.0, 1, 1))
        await db_session.execute(text(
            "UPDATE runtime_activity_signals SET state='released' WHERE instance_id=:id"), {'id': str(peer)})
        await db_session.commit()
        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker)
        assert report['admitted'] and report['admitted'][0]['trigger'] == 'idle'
        await settle(supervisor, scope)
        assert supervisor.active_run(scope) is None
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_activity_reason_names_every_blocking_condition():
    quiet = ActivitySnapshot(0, None, 0, 0)
    assert admission_activity_reason(own=quiet, peers=[]) is None
    assert admission_activity_reason(own=ActivitySnapshot(1, 0.0, 0, 0), peers=[]) == 'foreground_activity'
    assert admission_activity_reason(own=ActivitySnapshot(0, None, 1, 0), peers=[]) == 'ingestion_activity'
    assert admission_activity_reason(own=ActivitySnapshot(0, None, 0, 1), peers=[]) == 'rebuild_activity'
    stale = SimpleNamespace(stale=True, foreground_active=0, ingestion_active=False, rebuild_active=False)
    assert admission_activity_reason(own=quiet, peers=[stale]) == 'activity_observation_stale'
    busy = SimpleNamespace(stale=False, foreground_active=1, ingestion_active=False, rebuild_active=False)
    assert admission_activity_reason(own=quiet, peers=[busy]) == 'foreground_activity'
    ingesting = SimpleNamespace(stale=False, foreground_active=0, ingestion_active=True, rebuild_active=False)
    assert admission_activity_reason(own=quiet, peers=[ingesting]) == 'ingestion_activity'
    rebuilding = SimpleNamespace(stale=False, foreground_active=0, ingestion_active=False, rebuild_active=True)
    assert admission_activity_reason(own=quiet, peers=[rebuilding]) == 'rebuild_activity'


@pytest.mark.asyncio
async def test_idle_seconds_and_volume_threshold_are_revalidated(db_session, engine):
    async with writer_owner(engine) as owner:
        clock = FakeClock()
        tracker = quiet_tracker(clock)
        policy = {'consolidation_enabled': True,
                  'consolidation': {'volume_threshold': 3, 'idle_seconds': 60}}
        scope = await scope_with_policy(db_session, policy=policy)
        await episodes(db_session, scope, 1)
        supervisor = supervisor_for(engine, owner, distiller=SpyDistiller(), activity=tracker)

        # Below the volume threshold: the hint is invalidated, nothing is queued.
        mark_volume_hint(scope)
        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker)
        assert reasons(report) == ['below_volume_threshold'] and report['admitted'] == []
        assert report['thresholds'][str(scope)] == {'eligible': 1, 'threshold': 3}
        assert scope not in peek_volume_hints()
        assert (await db_session.scalar(text(
            'SELECT count(*) FROM consolidation_eligibilities WHERE knowledge_scope_id=:s'),
            {'s': scope})) == 0

        # Threshold reached: the still-current hint admits the run.
        await episodes(db_session, scope, 2)
        mark_volume_hint(scope)
        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker)
        assert report['admitted'] and report['admitted'][0]['trigger'] == 'volume'
        assert report['thresholds'][str(scope)]['eligible'] >= 3
        await settle(supervisor, scope)
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_busy_hint_is_discarded_and_not_replayed(db_session, engine):
    async with writer_owner(engine) as owner:
        clock = FakeClock()
        tracker = quiet_tracker(clock)
        policy = {'consolidation_enabled': True, 'consolidation': {'volume_threshold': 1}}
        scope = await scope_with_policy(db_session, policy=policy)
        await episodes(db_session, scope, 1)
        supervisor = supervisor_for(engine, owner, distiller=SpyDistiller(), activity=tracker)
        service = MemoryService(db_session, embedding_provider=StableEmbedding())
        runtime = ConsolidationRuntime(db_session, owner=owner, memory_service=service)
        active = await runtime.admit(scope, trigger='manual')

        mark_volume_hint(scope)
        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker)
        assert reasons(report) == ['CONSOLIDATION_BUSY'] and report['admitted'] == []
        assert scope not in peek_volume_hints()

        # Still busy: the discarded hint is not replayed and no second attempt runs.
        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker)
        assert report['admitted'] == []
        assert (await db_session.scalar(text(
            'SELECT count(*) FROM consolidation_eligibilities WHERE knowledge_scope_id=:s'),
            {'s': scope})) == 1
        await db_session.rollback()

        # Once released, a later tick may observe the still-current work itself —
        # as an independent idle trigger, not as a replayed volume attempt.
        await runtime.release(active)
        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker)
        assert report['admitted'] and report['admitted'][0]['trigger'] == 'idle'
        await settle(supervisor, scope)
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_empty_window_and_all_rejected_release_eligibility(db_session, engine):
    async with writer_owner(engine) as owner:
        supervisor = supervisor_for(engine, owner, distiller=SpyDistiller())
        empty = await scope_with_policy(db_session)
        token = await supervisor.submit(empty, trigger='manual')
        await settle(supervisor, empty)
        assert supervisor.active_run(empty) is None
        row = (await db_session.execute(text(
            'SELECT status, degradation_reasons, eligibility_state FROM consolidation_runs '
            'WHERE run_id=:id ORDER BY observation_seq DESC LIMIT 1'), {'id': str(token.run_id)})).one()
        assert row.status == 'no_change' and 'empty_window' in row.degradation_reasons
        assert row.eligibility_state == 'released'
        assert (await db_session.scalar(text(
            'SELECT state FROM consolidation_eligibilities WHERE eligibility_id=:id'),
            {'id': str(token.eligibility_id)})) == 'released'

        rejected = await scope_with_policy(db_session)
        await episodes(db_session, rejected, 1)
        token = await supervisor.submit(rejected, trigger='manual')
        await settle(supervisor, rejected)
        row = (await db_session.execute(text(
            'SELECT status, degradation_reasons, eligibility_state FROM consolidation_runs '
            'WHERE run_id=:id ORDER BY observation_seq DESC LIMIT 1'), {'id': str(token.run_id)})).one()
        assert row.status == 'no_change' and 'all_rejected' in row.degradation_reasons
        assert row.eligibility_state == 'released'
        assert supervisor.active_run(rejected) is None
        full = await supervisor.submit(rejected, trigger='idle')
        assert full.eligibility_version == 2
        await settle(supervisor, rejected)
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_legacy_housekeeping_runs_before_automatic_admission(db_session, engine):
    async with writer_owner(engine) as owner:
        tracker = quiet_tracker(FakeClock())
        scope = await scope_with_policy(db_session, policy={
            'consolidation_enabled': True, 'consolidation': {'volume_threshold': 1}})
        await episodes(db_session, scope, 1)
        supervisor = supervisor_for(engine, owner, distiller=SpyDistiller(), activity=tracker)
        order = []

        async def legacy():
            order.append('legacy')
            assert (await db_session.scalar(text(
                'SELECT count(*) FROM consolidation_eligibilities WHERE knowledge_scope_id=:s'),
                {'s': scope})) == 0

        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker,
                                       legacy_housekeeping=legacy)
        assert order == ['legacy'] and report['admitted']
        assert report['purged_consolidation_observations'] >= 0
        assert 'purged_consolidation_observations' in report
        await settle(supervisor, scope)
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_promotion_resumption_dispatch_is_activity_tracked(monkeypatch):
    """T084 absorption: resumption dispatch uses the unified tracked scheduler."""
    from rag_mcp.api import knowledge_sources
    from rag_mcp.runtime import scheduling
    from rag_mcp.services.maintenance_service import _default_promotion_schedule

    started, released = threading.Event(), threading.Event()

    async def slow_runner(source_id, graph_ready=False, retry=False, initial_run_id=None):
        started.set()
        await asyncio.to_thread(released.wait, 60)

    monkeypatch.setattr(knowledge_sources, '_run_ingestion', slow_runner)
    monkeypatch.setattr(scheduling, 'get_settings',
                        lambda: SimpleNamespace(ingestion_background=True))
    tracker = get_runtime_activity()
    tracker.reset()
    try:
        _default_promotion_schedule(987654)
        await asyncio.wait_for(asyncio.to_thread(started.wait, 30), 40)
        assert tracker.snapshot().ingestion_active == 1
    finally:
        released.set()
        for _ in range(400):
            if tracker.snapshot().ingestion_active == 0:
                break
            await asyncio.sleep(.05)
        assert tracker.snapshot().ingestion_active == 0
        tracker.reset()


@pytest.mark.asyncio
async def test_real_pending_entries_are_counted_not_raw_rows(db_session, engine):
    async with writer_owner(engine) as owner:
        tracker = quiet_tracker(FakeClock())
        policy = {'consolidation_enabled': True, 'consolidation': {'volume_threshold': 2}}
        scope = await scope_with_policy(db_session, policy=policy)
        await episodes(db_session, scope, 2)
        supervisor = supervisor_for(engine, owner, distiller=SpyDistiller(), activity=tracker)
        mark_volume_hint(scope)
        report = await run_maintenance(engine, owner, supervisor, scopes=[scope], activity=tracker,
                                       now=datetime.now(UTC) + timedelta(days=400))
        # Every episode is past its TTL at that clock: the raw row count is 2 but
        # the real eligible unconsumed count is 0, so the hint is invalidated.
        assert report['thresholds'][str(scope)] == {'eligible': 0, 'threshold': 2}
        assert reasons(report) == ['below_volume_threshold']
        assert scope not in peek_volume_hints()
        await supervisor.shutdown()
