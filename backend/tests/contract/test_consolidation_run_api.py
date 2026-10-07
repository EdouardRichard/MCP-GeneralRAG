"""T077 (US1): writer management contract for consolidation runs.

POST /api/memories/consolidation is a short admission (202, window initially
null, fixed execution_context=distiller_window) that never waits for window
selection or a model call. GET /consolidation/runs and /{run_id} are same-scope
writer management reads: strict query shapes, append-only history, 404 for
unknown/cross-scope identity, and 410 only when a same-scope long-term run
identity proves the run existed. REST can never submit internal maintenance
control fields.
"""
import asyncio
import re
from datetime import UTC, datetime
from unittest import mock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_mcp.db import get_session
from rag_mcp.orchestration.consolidation_pipeline import support_maintenance_context
from rag_mcp.server import create_app
from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
from rag_mcp.services.memory_service import MemoryService
from tests.integration.consolidation_fixtures import StableEmbedding, create_scope
from tests.integration.memory_acceptance import writer_owner
from tests.integration.phase7_fixtures import (
    SpyDistiller,
    episodes,
    reset_activity_state,
    scope_with_policy,
    settle,
    supervisor_for,
)

UUID4 = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


@pytest_asyncio.fixture(autouse=True)
async def _hermetic_activity(db_session):
    await reset_activity_state(db_session)
    yield
    await reset_activity_state(db_session)


def _install(app, engine):
    """Serve each request from its own session so writer-lease locks are released."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def sessions():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    return app


def _client(app):
    return AsyncClient(transport=ASGITransport(app), base_url='http://test')


@pytest.mark.asyncio
async def test_consolidation_routes_require_a_live_writer_lease(db_session):
    app = create_app()
    async with _client(app) as client:
        started = await client.post('/api/memories/consolidation',
                                    json={'scope_id': 1, 'reason': 'manual review'})
        assert started.status_code == 503, started.text
        assert started.json()['detail']['code'] == 'MEMORY_WRITE_UNAVAILABLE'
        listed = await client.get('/api/memories/consolidation/runs', params={'scope_ref': '1'})
        assert listed.status_code == 503, listed.text
        assert listed.json()['detail']['code'] == 'MEMORY_WRITE_UNAVAILABLE'
        detail = await client.get(f'/api/memories/consolidation/runs/{uuid4()}', params={'scope_ref': '1'})
        assert detail.status_code == 503, detail.text


@pytest.mark.asyncio
async def test_consolidation_request_shape_is_strict(db_session, engine):
    app = _install(create_app(), engine)
    async with writer_owner(engine) as owner:
        app.state.writer_lease = owner
        async with _client(app) as client:
            base = {'scope_id': 1, 'reason': 'manual review'}
            for change in ({'trigger': 'idle'}, {'execution_context': 'distiller_window'},
                           {'propagation_trigger': {'kind': 'evidence_withdrawn'}}, {'proof': {'kind': 'x'}},
                           {'run_id': str(uuid4())}, {'holder_instance_id': str(uuid4())},
                           {'policy': {'consolidation_enabled': True}}, {'proposals': []},
                           {'actor': 'management'}, {'request_id': 'r-1'}, {'scope_id': True},
                           {'scope_id': '1'}, {'scope_id': 0}, {'reason': ''}, {'extra': 'control'}):
                response = await client.post('/api/memories/consolidation', json={**base, **change})
                assert response.status_code == 422, (change, response.text)
            assert (await client.post('/api/memories/consolidation', json={'reason': 'x'})).status_code == 422
            assert (await client.post('/api/memories/consolidation', content=b'{')).status_code == 422
            assert (await client.get('/api/memories/consolidation/runs')).status_code == 422
            assert (await client.get('/api/memories/consolidation/runs',
                                     params={'scope_ref': '1', 'limit': 0})).status_code == 422
            assert (await client.get('/api/memories/consolidation/runs',
                                     params={'scope_ref': '1', 'limit': 101})).status_code == 422
            assert (await client.get('/api/memories/consolidation/runs',
                                     params={'scope_ref': '1', 'offset': -1})).status_code == 422
            unresolved = await client.get('/api/memories/consolidation/runs', params={'scope_ref': 'no-such-scope'})
            assert unresolved.status_code == 400, unresolved.text
            assert unresolved.json()['detail']['code'] == 'MISSING_KNOWLEDGE_SCOPE'


@pytest.mark.asyncio
async def test_manual_admission_returns_short_202_without_selecting_or_calling_the_model(db_session, engine,
                                                                                        monkeypatch):
    app = _install(create_app(), engine)
    async with writer_owner(engine) as owner:
        app.state.writer_lease = owner
        scope = await scope_with_policy(db_session)
        await episodes(db_session, scope, 1)
        distiller = SpyDistiller()
        supervisor = supervisor_for(engine, owner, distiller=distiller)
        app.state.consolidation_supervisor = supervisor

        release, entered = asyncio.Event(), asyncio.Event()
        original = ConsolidationRuntime.select_and_seal

        async def blocked(self, token):
            entered.set()
            await release.wait()
            return await original(self, token)

        monkeypatch.setattr(ConsolidationRuntime, 'select_and_seal', blocked)

        async with _client(app) as client:
            started = await client.post('/api/memories/consolidation',
                                        json={'scope_id': scope, 'reason': 'manual review'})
            assert started.status_code == 202, started.text
            body = started.json()
            run_id = body['run_id']
            assert body['schema_version'] == 1 and UUID4.match(run_id)
            assert body['scope_id'] == str(scope)
            assert body['trigger'] == 'manual' and body['execution_context'] == 'distiller_window'
            assert body['status'] == 'admitted' and body['window'] is None
            assert body['request_id'] and run_id in body['report_url'] and str(scope) in body['report_url']
            # Admission is durable before HTTP 202 and nothing waited for window
            # selection or a model call while the request was in flight.
            assert entered.is_set() is False and distiller.calls == []
            row = (await db_session.execute(text(
                'SELECT status, "window", trigger, execution_context FROM consolidation_runs '
                'WHERE run_id=:id'), {'id': run_id})).one()
            assert (row.status, row.window, row.trigger, row.execution_context) == (
                'admitted', None, 'manual', 'distiller_window')

            busy = await client.post('/api/memories/consolidation',
                                     json={'scope_id': scope, 'reason': 'second attempt'})
            assert busy.status_code == 409, busy.text
            assert busy.json()['detail']['code'] == 'CONSOLIDATION_BUSY'
            assert busy.json()['detail']['run_id'] == run_id

            release.set()
            await settle(supervisor, scope)
            report = await client.get(f'/api/memories/consolidation/runs/{run_id}',
                                      params={'scope_ref': str(scope)})
            assert report.status_code == 200, report.text
            assert report.json()['status'] == 'no_change'
            assert report.json()['window'] is not None
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_disabled_unconfigured_scope_write_busy_and_capacity_are_distinct(db_session, engine):
    app = _install(create_app(), engine)
    async with writer_owner(engine) as owner:
        app.state.writer_lease = owner
        app.state.consolidation_supervisor = supervisor_for(engine, owner, distiller=SpyDistiller())
        disabled = await create_scope(db_session, enabled=False)
        unconfigured = await scope_with_policy(db_session, policy={'consolidation_enabled': True})
        async with _client(app) as client:
            blocked_disabled = await client.post('/api/memories/consolidation',
                                                 json={'scope_id': disabled, 'reason': 'manual review'})
            assert blocked_disabled.status_code == 403, blocked_disabled.text
            assert blocked_disabled.json()['detail']['code'] == 'CONSOLIDATION_DISABLED'
            blocked_config = await client.post('/api/memories/consolidation',
                                               json={'scope_id': unconfigured, 'reason': 'manual review'})
            assert blocked_config.status_code == 409, blocked_config.text
            assert blocked_config.json()['detail']['code'] == 'CONSOLIDATION_CONFIG_REQUIRED'
            for scope in (disabled, unconfigured):
                assert (await db_session.scalar(text(
                    'SELECT count(*) FROM consolidation_eligibilities WHERE knowledge_scope_id=:s'),
                    {'s': scope})) == 0

            # Contested scope lock: the short admission transaction is rejected
            # instead of waiting for the running scope writer.
            contended = await scope_with_policy(db_session)
            await episodes(db_session, contended, 1)
            app.state.consolidation_supervisor = supervisor_for(engine, owner, distiller=SpyDistiller())
            async with async_sessionmaker(engine, class_=AsyncSession)() as other:
                await other.execute(text('SELECT pg_advisory_xact_lock(:s)'), {'s': contended})
                contested = await client.post('/api/memories/consolidation',
                                              json={'scope_id': contended, 'reason': 'manual review'})
                assert contested.status_code == 409, contested.text
                assert contested.json()['detail']['code'] == 'CONSOLIDATION_SCOPE_WRITE_BUSY'
                await other.rollback()

    # Capacity: two real scope workers occupy both slots; a third scope is
    # rejected outright with no run row and no queue entry, while the same
    # scope reconciles to BUSY before the generic capacity error.
    async with writer_owner(engine) as owner:
        app.state.writer_lease = owner
        scopes = []
        for _ in range(3):
            scope = await scope_with_policy(db_session)
            await episodes(db_session, scope, 1)
            scopes.append(scope)
        release, entered = asyncio.Event(), asyncio.Event()
        original = ConsolidationRuntime.select_and_seal
        started = []

        async def blocked(self, token):
            started.append(token.scope_id)
            if len(started) >= 2:
                entered.set()
            await release.wait()
            return await original(self, token)

        with mock.patch.object(ConsolidationRuntime, 'select_and_seal', blocked):
            supervisor = supervisor_for(engine, owner, distiller=SpyDistiller())
            app.state.consolidation_supervisor = supervisor
            first = await supervisor.submit(scopes[0], trigger='manual')
            await supervisor.submit(scopes[1], trigger='manual')
            await asyncio.wait_for(entered.wait(), 60)
            async with _client(app) as client:
                third = await client.post('/api/memories/consolidation',
                                          json={'scope_id': scopes[2], 'reason': 'manual review'})
                assert third.status_code == 429, third.text
                assert third.json()['detail']['code'] == 'CONSOLIDATION_CAPACITY_EXCEEDED'
                same = await client.post('/api/memories/consolidation',
                                         json={'scope_id': scopes[0], 'reason': 'manual review'})
                assert same.status_code == 409, same.text
                assert same.json()['detail']['code'] == 'CONSOLIDATION_BUSY'
                assert same.json()['detail']['run_id'] == str(first.run_id)
            assert (await db_session.scalar(text(
                'SELECT count(*) FROM consolidation_eligibilities WHERE knowledge_scope_id=:s'),
                {'s': scopes[2]})) == 0
            release.set()
            await asyncio.gather(settle(supervisor, scopes[0]), settle(supervisor, scopes[1]))
            assert supervisor.active_run(scopes[0]) is None and supervisor.active_run(scopes[1]) is None
            reused = await supervisor.submit(scopes[2], trigger='manual')
            assert reused.scope_id == scopes[2]
            await settle(supervisor, scopes[2])
            assert supervisor.active_run(scopes[2]) is None
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_run_list_detail_history_and_purged_identity(db_session, engine):
    app = _install(create_app(), engine)
    async with writer_owner(engine) as owner:
        app.state.writer_lease = owner
        scope = await scope_with_policy(db_session)
        await episodes(db_session, scope, 1)
        other_scope = await create_scope(db_session)
        service = MemoryService(db_session, embedding_provider=StableEmbedding())
        runtime = ConsolidationRuntime(db_session, owner=owner, memory_service=service)
        first = await runtime.admit(scope, trigger='manual', request_id='req-first')
        await runtime.observe(first, status='selecting', window={
            'window_id': '1', 'start': '2026-01-01T00:00:00+00:00', 'end': '2026-01-02T00:00:00+00:00',
            'high_water_mark': 1}, input_event_ids=[1])
        await runtime.observe(first, status='no_change', degradation_reasons=['empty_window'])
        await runtime.release(first)
        second = await runtime.admit(scope, trigger='idle', request_id='req-second')
        await runtime.release(second)

        async with _client(app) as client:
            listed = await client.get('/api/memories/consolidation/runs',
                                      params={'scope_ref': str(scope), 'limit': 20})
            assert listed.status_code == 200, listed.text
            body = listed.json()
            assert body['scope_id'] == str(scope) and body['total'] == 2
            assert len(body['items']) == 2
            by_run = {item['run_id']: item for item in body['items']}
            assert set(by_run) == {str(first.run_id), str(second.run_id)}
            # One item per run: the latest cumulative observation only.
            assert by_run[str(first.run_id)]['status'] == 'no_change'
            assert by_run[str(first.run_id)]['observation_seq'] > 1
            assert by_run[str(second.run_id)]['status'] == 'admitted'
            assert [item['created_at'] for item in body['items']] == sorted(
                (item['created_at'] for item in body['items']), reverse=True)

            detail = await client.get(f'/api/memories/consolidation/runs/{first.run_id}',
                                      params={'scope_ref': str(scope)})
            assert detail.status_code == 200, detail.text
            report = detail.json()
            assert report['run_id'] == str(first.run_id) and report['scope_id'] == str(scope)
            assert report['request_id'] == 'req-first'
            assert report['execution_context'] == 'distiller_window'
            assert report['window']['window_id'] == '1'
            assert report['input_event_ids'] == ['1']
            assert report['counts'] == {'proposed': 0, 'accepted': 0, 'rejected': 0, 'committed': 0,
                                        'pending': 0, 'failed': 0, 'unprocessed': 0}
            assert report['degradation_reasons'] == ['empty_window']
            assert report['provider_usage']['llm_calls'] == 0
            assert report['provider_usage']['input_tokens'] is None
            assert [item['eligibility_version'] for item in report['eligibility_history']] == [1]
            assert report['current_generation']['eligibility_version'] == 1
            assert report['current_generation']['is_current'] is True
            assert report['created_at'] and report['ttl_expires_at']
            assert report.get('history', []) == []
            assert 'password' not in detail.text and 'api_key' not in detail.text

            history = await client.get(f'/api/memories/consolidation/runs/{first.run_id}',
                                       params={'scope_ref': str(scope), 'include_history': 'true'})
            assert history.status_code == 200, history.text
            entries = history.json()['history']
            assert [entry['observation_seq'] for entry in entries] == sorted(
                entry['observation_seq'] for entry in entries)
            assert len(entries) == 4
            assert entries[-1]['status'] == 'no_change' and entries[-1]['eligibility_state'] == 'released'

            foreign = await client.get(f'/api/memories/consolidation/runs/{first.run_id}',
                                       params={'scope_ref': str(other_scope)})
            assert foreign.status_code == 404, foreign.text
            assert foreign.json()['detail']['code'] == 'CONSOLIDATION_RUN_NOT_FOUND'
            assert str(scope) not in foreign.text
            assert (await client.get(f'/api/memories/consolidation/runs/{uuid4()}',
                                     params={'scope_ref': str(scope)})).status_code == 404
            assert (await client.get('/api/memories/consolidation/runs/not-a-uuid',
                                     params={'scope_ref': str(scope)})).status_code == 404

        # A purged audit trail with retained same-scope eligibility history is
        # 410; a run with no long-term identity proof at all stays 404.
        purged = uuid4()
        await db_session.execute(text(
            'INSERT INTO consolidation_eligibilities (eligibility_id, knowledge_scope_id, run_id,'
            ' holder_instance_id, writer_lease_id, eligibility_version, observation_seq_high_water, state,'
            ' acquired_at, renewed_at, expires_at, released_at) VALUES'
            ' (:eid, :scope, :run, :holder, :lease, :version, 1, \'released\','
            ' now(), now(), now(), now())'),
            {'eid': str(uuid4()), 'scope': scope, 'run': str(purged), 'holder': str(uuid4()),
             'lease': owner.lease_id, 'version': first.eligibility_version + 10})
        await db_session.commit()
        async with _client(app) as client:
            expired = await client.get(f'/api/memories/consolidation/runs/{purged}',
                                       params={'scope_ref': str(scope)})
            assert expired.status_code == 410, expired.text
            assert expired.json()['detail']['code'] == 'CONSOLIDATION_RUN_EXPIRED'
            unproven = await client.get(f'/api/memories/consolidation/runs/{uuid4()}',
                                        params={'scope_ref': str(scope)})
            assert unproven.status_code == 404, unproven.text


@pytest.mark.asyncio
async def test_internal_support_maintenance_report_is_not_a_manual_request(db_session, engine):
    app = _install(create_app(), engine)
    async with writer_owner(engine) as owner:
        app.state.writer_lease = owner
        scope = await create_scope(db_session, enabled=False)
        service = MemoryService(db_session, embedding_provider=StableEmbedding())
        runtime = ConsolidationRuntime(db_session, owner=owner, memory_service=service)
        context = support_maintenance_context(
            historical_source_refs=[{'memory_id': 1, 'source_event_id': 2, 'state_event_id': 2,
                                     'content_hash': 'a' * 64,
                                     'observed_at': datetime.now(UTC).isoformat()}],
            propagation_trigger={'kind': 'evidence_revocation', 'event_id': 7, 'evidence_id': None,
                                 'version': '1', 'observed_at': datetime.now(UTC).isoformat(),
                                 'proof': {'kind': 'evidence_revocation', 'memory_id': 1, 'evidence_id': 7}})
        token = await runtime.admit(scope, trigger='support_maintenance', context=context, actor='management')
        await runtime.release(token)
        async with _client(app) as client:
            report = await client.get(f'/api/memories/consolidation/runs/{token.run_id}',
                                      params={'scope_ref': str(scope)})
            assert report.status_code == 200, report.text
            body = report.json()
            assert body['trigger'] == 'support_maintenance'
            assert body['execution_context'] == 'deterministic_propagation'
            assert body['window'] is None and body['input_event_ids'] == []
            assert body['historical_source_refs'] and body['propagation_trigger']['event_id'] == 7
            assert body['proof'] == body['propagation_trigger']['proof']
            rejected = await client.post('/api/memories/consolidation', json={
                'scope_id': scope, 'reason': 'x', 'trigger': 'support_maintenance'})
            assert rejected.status_code == 422, rejected.text
        assert token.writer_lease_id == owner.lease_id
        latest_window = await db_session.scalar(text(
            'SELECT "window" FROM consolidation_runs WHERE run_id=:id '
            'ORDER BY observation_seq DESC LIMIT 1'), {'id': str(token.run_id)})
        assert latest_window is None
