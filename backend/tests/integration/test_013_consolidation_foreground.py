"""T080 (US1): consolidation never touches the foreground, and readers stay readers.

While a consolidation run is in flight (real provider thread blocked), the
ordinary search/recall/record/start_work paths keep their original budgets and
call graphs: no foreground path synchronously waits for, or calls, the
Distiller. Request activity is constant-time, is counted for real HTTP and MCP
dispatch, is released on success, error and cancellation, ignores passive
traffic, and always ends at zero. The reader surface gains no management or
control entry.
"""
import asyncio
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from rag_mcp.runtime.activity import get_runtime_activity
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.services.scope_resolver import MemoryScopeResolver
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


@pytest_asyncio.fixture(autouse=True)
async def _hermetic_activity(db_session):
    await reset_activity_state(db_session)
    yield
    await reset_activity_state(db_session)


async def foreground_payload(db_session, scope, service):
    await episodes(db_session, scope, 1)
    return await service.record({'scope_id': scope, 'kind': 'episodic', 'content': 'foreground observation',
                                 'provenance': 'soft',
                                 'inference_meta': {'source': 'T080 foreground', 'confidence': .8,
                                                    'model_version': 'fixture-v1',
                                                    'time': datetime.now(UTC).isoformat(),
                                                    'supporting_evidence': []}})


@pytest.mark.asyncio
async def test_foreground_paths_keep_working_while_a_run_is_blocked(db_session, engine, monkeypatch):
    from rag_mcp.agents.memory_distiller import MemoryDistiller

    async with writer_owner(engine) as owner:
        scope = await scope_with_policy(db_session)
        service = MemoryService(db_session, embedding_provider=StableEmbedding())
        await foreground_payload(db_session, scope, service)

        gate = threading.Event()
        distiller = SpyDistiller(gate=gate)
        supervisor = supervisor_for(engine, owner, distiller=distiller)
        token = await supervisor.submit(scope, trigger='manual')
        for _ in range(1500):
            if distiller.calls:
                break
            await asyncio.sleep(.02)
        assert distiller.calls, 'the consolidation provider call never entered'

        def forbidden(*args, **kwargs):
            raise AssertionError('the foreground must never call the Distiller synchronously')

        monkeypatch.setattr(MemoryDistiller, 'run', forbidden)
        provider_calls = len(distiller.calls)
        tracker = get_runtime_activity()
        budget = []

        async def timed(call):
            started = asyncio.get_running_loop().time()
            result = await call
            budget.append(asyncio.get_running_loop().time() - started)
            return result

        mocked = await timed(service.record({'scope_id': scope, 'kind': 'episodic', 'content': 'bg write',
                                             'provenance': 'soft',
                                             'inference_meta': {'source': 'T080 foreground', 'confidence': .8,
                                                                'model_version': 'fixture-v1',
                                                                'time': datetime.now(UTC).isoformat(),
                                                                'supporting_evidence': []}}))
        assert mocked['memory_id']
        recalled = await timed(MemoryService(db_session, embedding_provider=StableEmbedding()).recall(
            scope_ref=[str(scope)], memory_ids=[mocked['memory_id']]))
        assert recalled['memories'][0]['memory_id'] == mocked['memory_id']
        work = await timed(MemoryService(db_session, embedding_provider=StableEmbedding()).start_work(
            scope_ref=str(scope)))
        # start_work keeps its documented envelope and standard 2000-character
        # budget; which rows survive that budget is the reader's existing policy,
        # not something consolidation may change.
        assert {'package_fingerprint', 'counts', 'digest', 'working_set'} <= set(work)
        assert work['counts']['characters'] <= 2000
        assert max(budget) < 15, f'foreground latency regressed: {budget}'
        assert len(distiller.calls) == provider_calls, 'foreground work entered the consolidation provider'
        assert tracker.snapshot().foreground_active == 0
        assert supervisor.active_run(scope) == token.run_id

        gate.set()
        await settle(supervisor, scope)
        assert supervisor.active_run(scope) is None
        await supervisor.shutdown()


@pytest.mark.asyncio
async def test_http_activity_is_counted_released_and_passive_traffic_ignored(db_session, engine, monkeypatch):
    from rag_mcp.server import create_app

    tracker = get_runtime_activity()
    tracker.reset()
    app = create_app()
    observed = []
    original = MemoryScopeResolver.resolve

    async def watched(self, scope_ref):
        observed.append(tracker.snapshot().foreground_active)
        if scope_ref == 'fail-now':
            raise ValueError('MISSING_KNOWLEDGE_SCOPE')
        return await original(self, scope_ref)

    monkeypatch.setattr(MemoryScopeResolver, 'resolve', watched)
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
        assert (await client.get('/health')).status_code == 200
        assert (await client.get('/openapi.json')).status_code == 200
        assert tracker.snapshot().foreground_active == 0

        failed = await client.get('/api/memories', params={'scope_ref': 'fail-now'})
        assert failed.status_code == 400, failed.text
        assert observed == [1]
        assert tracker.snapshot().foreground_active == 0
    assert tracker.snapshot().foreground_active == 0
    tracker.reset()


@pytest.mark.asyncio
async def test_mcp_dispatch_is_activity_visible_and_releases_on_failure(db_session, monkeypatch):
    from rag_mcp.mcp import create_mcp_server
    from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider

    tracker = get_runtime_activity()
    tracker.reset()
    server = create_mcp_server(embedding_provider=LocalCPUEmbeddingProvider(), mode='writer')
    observed = []

    async def watched(self, **parameters):
        observed.append(tracker.snapshot().foreground_active)
        raise RuntimeError('reader failure')

    monkeypatch.setattr(MemoryService, 'recall', watched)
    result = await server.call_tool('recall_memory', {'scope_ref': ['1']})
    _content, structured = result if isinstance(result, tuple) else (result.content, result.structuredContent)
    assert observed == [1] and structured and structured.get('error')
    assert tracker.snapshot().foreground_active == 0
    tracker.reset()

    server = create_mcp_server(embedding_provider=LocalCPUEmbeddingProvider(), mode='writer')
    ok = await server.call_tool('list_knowledge_domains', {})
    _content, structured = ok if isinstance(ok, tuple) else (ok.content, ok.structuredContent)
    assert not (structured or {}).get('error')
    assert tracker.snapshot().foreground_active == 0
    tracker.reset()


@pytest.mark.asyncio
async def test_reader_surface_has_no_management_or_control_entry(db_session, monkeypatch):
    from rag_mcp.api import memory as memory_api
    from rag_mcp.mcp import create_mcp_server
    from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider
    from rag_mcp.server import create_app

    writer = create_mcp_server(embedding_provider=LocalCPUEmbeddingProvider(), mode='writer')
    reader = create_mcp_server(embedding_provider=LocalCPUEmbeddingProvider(), mode='reader')
    writer_tools = {tool.name for tool in await writer.list_tools()}
    reader_tools = {tool.name for tool in await reader.list_tools()}
    assert 'record_memory' in writer_tools and 'record_memory' not in reader_tools
    assert not {name for name in reader_tools if 'consolidat' in name or 'promot' in name}
    assert not {name for name in writer_tools if 'consolidat' in name}

    # A reader-mode management app cannot accept a consolidation run at all.
    monkeypatch.setattr(memory_api, 'get_settings', lambda: SimpleNamespace(instance_mode='reader'))
    app = create_app()
    app.state.writer_lease = SimpleNamespace(lease_id=1, holder_instance_id=uuid4())
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
        started = await client.post('/api/memories/consolidation',
                                    json={'scope_id': 1, 'reason': 'manual review'})
        assert started.status_code == 503, started.text
        assert started.json()['detail']['code'] == 'MEMORY_WRITE_UNAVAILABLE'


@pytest.mark.asyncio
async def test_ingestion_and_rebuild_activity_are_real_and_always_released(db_session, engine, monkeypatch):
    from rag_mcp.api import knowledge_sources
    from rag_mcp.runtime import scheduling

    tracker = get_runtime_activity()
    tracker.reset()
    started, released = threading.Event(), threading.Event()

    async def running(source_id, graph_ready=False, retry=False, initial_run_id=None):
        started.set()
        await asyncio.to_thread(released.wait, 60)
        raise RuntimeError('ingestion failed')

    monkeypatch.setattr(knowledge_sources, '_run_ingestion', running)
    monkeypatch.setattr(scheduling, 'get_settings',
                        lambda: SimpleNamespace(ingestion_background=True))
    assert scheduling.schedule_ingestion(4242) is True
    await asyncio.wait_for(asyncio.to_thread(started.wait, 30), 40)
    assert tracker.snapshot().ingestion_active == 1
    released.set()
    for _ in range(400):
        if tracker.snapshot().ingestion_active == 0:
            break
        await asyncio.sleep(.05)
    assert tracker.snapshot().ingestion_active == 0

    # The real rebuild lifetime is tracked through failures as well.
    scope = await create_scope(db_session)
    await episodes(db_session, scope, 1)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    original = service.projections.materialize

    async def broken(state, scope_id, source_event_id):
        assert tracker.snapshot().rebuild_active == 1
        raise RuntimeError('rebuild failed')

    monkeypatch.setattr(service.projections, 'materialize', broken)
    with pytest.raises(RuntimeError):
        await service.rebuild(scope, actor='management', reason='T080 activity probe')
    assert tracker.snapshot().rebuild_active == 0
    assert original is not None
    tracker.reset()
