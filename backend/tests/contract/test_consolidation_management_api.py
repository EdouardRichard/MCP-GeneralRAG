"""T066 (US6): writer-only management contract for candidates and promotion.

The candidate list, POST /promote and GET /promotions/{task_id} are writer
management surfaces: they require a live writer lease, forbid extra control
fields, are idempotent for the same candidate version, expose the stable task
identity, and never leak another scope. Status only ever reflects the actual
source/run/version facts.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_mcp.db import get_session
from rag_mcp.server import create_app
from tests.integration.consolidation_fixtures import create_scope
from tests.integration.memory_acceptance import writer_owner
from tests.integration.promotion_fixtures import committed_candidate


def _install(app, engine):
    """Serve each request from its own session so writer-lease locks are released."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def sessions():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    return app


@pytest.mark.asyncio
async def test_candidate_and_promotion_routes_require_a_live_writer_lease(db_session):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
        listed = await client.get('/api/memories/promotion-candidates', params={'scope_ref': '1'})
        assert listed.status_code == 503 and listed.json()['detail']['code'] == 'MEMORY_WRITE_UNAVAILABLE'
        promoted = await client.post('/api/memories/promote', json={
            'scope_id': 1, 'memory_id': 2, 'candidate_version': 'a' * 64, 'reason': 'operator'})
        assert promoted.status_code == 503 and promoted.json()['detail']['code'] == 'MEMORY_WRITE_UNAVAILABLE'
        report = await client.get('/api/memories/promotions/2', params={'scope_ref': '1'})
        assert report.status_code == 503 and report.json()['detail']['code'] == 'MEMORY_WRITE_UNAVAILABLE'


@pytest.mark.asyncio
async def test_promotion_request_shape_is_strict(db_session, engine):
    app = _install(create_app(), engine)
    async with writer_owner(engine) as owner:
        app.state.writer_lease = owner
        async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
            base = {'scope_id': 1, 'memory_id': 2, 'candidate_version': 'a' * 64, 'reason': 'operator'}
            for change in ({'extra': 'control'}, {'candidate_version': None}, {'reason': ''},
                           {'scope_id': True}, {'memory_id': 'not-an-int'},
                           {'candidate_version': 'short'}, {'trigger': 'idle'}):
                response = await client.post('/api/memories/promote', json={**base, **change})
                assert response.status_code == 422, (change, response.text)
            assert (await client.get('/api/memories/promotion-candidates')).status_code == 422
            assert (await client.get('/api/memories/promotions/2')).status_code == 422
            unresolved = await client.get('/api/memories/promotions/2', params={'scope_ref': 'no-such-scope'})
            assert unresolved.status_code == 400
            assert unresolved.json()['detail']['code'] == 'MISSING_KNOWLEDGE_SCOPE'


@pytest.mark.asyncio
async def test_candidate_list_promote_and_promotion_report_contract(db_session, engine):
    app = _install(create_app(), engine)
    async with writer_owner(engine) as owner:
        app.state.writer_lease = owner
        fixture = await committed_candidate(db_session, owner)
        scope, memory_id = fixture['scope'], fixture['memory_id']
        other = await create_scope(db_session)
        await db_session.rollback()
        async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
            listed = await client.get('/api/memories/promotion-candidates', params={'scope_ref': str(scope)})
            assert listed.status_code == 200, listed.text
            body = listed.json()
            assert body['scope_id'] == str(scope) and body['total'] == 1
            item = body['items'][0]
            assert item['memory_id'] == str(memory_id) and item['kind'] == 'semantic'
            assert item['provenance'] == 'distilled' and item['confidence'] == .97
            assert item['candidate_version'] == fixture['candidate_version']
            assert item['promotable'] is True and item['ineligibility_reasons'] == []
            assert item['evidence_attributions'][0]['position'] == fixture['anchor']['position']
            assert item['evidence_attributions'][0]['content_hash'] == fixture['anchor']['content_hash']
            assert item['promotion_pointer'] is None

            request = {'scope_id': scope, 'memory_id': memory_id,
                       'candidate_version': fixture['candidate_version'], 'reason': 'approved by operator'}
            cross = await client.post('/api/memories/promote', json={**request, 'scope_id': other})
            assert cross.status_code == 404, cross.text
            assert cross.json()['detail']['code'] == 'MEMORY_PROMOTION_NOT_FOUND'

            await db_session.execute(text("UPDATE knowledge_versions SET status='failed' WHERE version_id=:id"),
                                     {'id': fixture['anchor']['version_id']})
            await db_session.commit()
            ineligible = await client.post('/api/memories/promote', json=request)
            assert ineligible.status_code == 409, ineligible.text
            assert ineligible.json()['detail']['code'] == 'MEMORY_CANDIDATE_NOT_ELIGIBLE'
            stale = await client.post('/api/memories/promote', json={**request, 'candidate_version': 'b' * 64})
            assert stale.status_code == 409 and stale.json()['detail']['code'] == 'MEMORY_CANDIDATE_VERSION_CHANGED'
            demoted = (await client.get('/api/memories/promotion-candidates',
                                        params={'scope_ref': str(scope)})).json()['items'][0]
            assert demoted['promotable'] is False and demoted['ineligibility_reasons']

            await db_session.execute(text("UPDATE knowledge_versions SET status='published' WHERE version_id=:id"),
                                     {'id': fixture['anchor']['version_id']})
            await db_session.commit()
            accepted = await client.post('/api/memories/promote', json=request)
            assert accepted.status_code == 202, accepted.text
            created = accepted.json()
            assert created['schema_version'] and created['request_id']
            assert created['status'] == 'uploaded' and created['version_id'] is None
            assert created['reused'] is False
            assert created['scope_id'] == str(scope) and created['memory_id'] == str(memory_id)
            assert created['candidate_version'] == fixture['candidate_version']
            assert int(created['task_id']) > 0 and int(created['source_id']) > 0
            assert int(created['initial_processing_run_id']) > 0

            repeated = await client.post('/api/memories/promote', json=request)
            assert repeated.status_code == 200, repeated.text
            duplicate = repeated.json()
            assert duplicate['reused'] is True and duplicate['status'] == 'uploaded'
            assert (duplicate['task_id'], duplicate['source_id'], duplicate['initial_processing_run_id']) == (
                created['task_id'], created['source_id'], created['initial_processing_run_id'])

            report = await client.get(f'/api/memories/promotions/{created["task_id"]}',
                                      params={'scope_ref': str(scope)})
            assert report.status_code == 200, report.text
            detail = report.json()
            assert detail['task_id'] == created['task_id']
            assert detail['memory_id'] == str(memory_id) and detail['candidate_version'] == fixture['candidate_version']
            assert detail['source_id'] == created['source_id']
            assert detail['initial_processing_run_id'] == created['initial_processing_run_id']
            assert detail['attempt_run_ids'] == [created['initial_processing_run_id']]
            assert detail['status'] == 'uploaded' and detail['published_version_id'] is None
            assert detail['authority_event_ids'] and detail['result'] is None

            foreign = await client.get(f'/api/memories/promotions/{created["task_id"]}',
                                       params={'scope_ref': str(other)})
            assert foreign.status_code == 404, foreign.text
            assert foreign.json()['detail']['code'] == 'MEMORY_PROMOTION_NOT_FOUND'
            missing = await client.get('/api/memories/promotions/999999999', params={'scope_ref': str(scope)})
            assert missing.status_code == 404
            assert (await client.get('/api/memories/promotions/not-a-number',
                                     params={'scope_ref': str(scope)})).status_code == 422
