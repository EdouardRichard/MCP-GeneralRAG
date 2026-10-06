"""T067 (US6): explicit human promotion, idempotence, recovery and compatibility.

Covers: consolidation/maintenance/threshold paths create zero promotion sources,
one explicit human request creates exactly one stable task/source/pending initial
run while the original memory is untouched, concurrent duplicates converge on the
same identities, an undispatched authorized task is recovered by maintenance only
after candidate/scope revalidation, real publication observations and explicit
retry attempts preserve the stable task/source, unpublished states never report
published, the legacy upload flow keeps its behaviour, and a memory rollback does
not claim to undo the external publication.
"""
import asyncio
import io

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_mcp.models.knowledge_source import KnowledgeSource
from rag_mcp.models.knowledge_version import KnowledgeVersion
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.models.processing_run import ProcessingRun
from rag_mcp.services.memory_service import MemoryService
from tests.integration.consolidation_fixtures import StableEmbedding
from tests.integration.promotion_fixtures import committed_candidate, promote


async def _count(session, model, **conditions):
    statement = select(func.count()).select_from(model)
    for key, value in conditions.items():
        statement = statement.where(getattr(model, key) == value)
    return await session.scalar(statement)


async def _promotion_events(session, scope_id):
    return (await session.execute(select(MemoryEvent).where(
        MemoryEvent.knowledge_scope_id == scope_id, MemoryEvent.event_type == 'grant',
        MemoryEvent.payload['grant_type'].astext.in_(['promotion_requested', 'promotion_observed']))
        .order_by(MemoryEvent.event_id))).scalars().all()


@pytest.mark.asyncio
async def test_consolidation_maintenance_and_threshold_paths_create_no_promotion_source(db_session, memory_writer_owner):
    from rag_mcp.services.maintenance_service import resume_promotions, run_memory_maintenance

    fixture = await committed_candidate(db_session, memory_writer_owner)
    scope = fixture['scope']
    await db_session.rollback()
    assert await _count(db_session, KnowledgeSource, knowledge_scope_id=scope) == 1, 'only the published anchor'
    assert not await _promotion_events(db_session, scope)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    assert await resume_promotions(db_session, scopes=[scope], service=service) == {'resumed': [], 'failed': []}
    assert await _count(db_session, KnowledgeSource, knowledge_scope_id=scope) == 1
    assert not await _promotion_events(db_session, scope)
    await db_session.rollback()
    await run_memory_maintenance(db_session, scope_ids=[scope], service=service)
    assert await _count(db_session, KnowledgeSource, knowledge_scope_id=scope) == 1
    assert not await _promotion_events(db_session, scope)
    entry = await db_session.get(MemoryEntry, fixture['memory_id'])
    assert entry.promotion_pointer is None and entry.candidate_version == fixture['candidate_version']


@pytest.mark.asyncio
async def test_human_promotion_is_idempotent_and_preserves_the_original_memory(db_session, memory_writer_owner):
    fixture = await committed_candidate(db_session, memory_writer_owner)
    scope, memory_id = fixture['scope'], fixture['memory_id']
    await db_session.rollback()
    before = await db_session.get(MemoryEntry, memory_id)
    original = {key: getattr(before, key) for key in (
        'content_text', 'confidence', 'provenance', 'kind', 'status', 'candidate_version', 'state_event_id',
        'source_event_id', 'content_hash')}
    result = await promote(db_session, fixture)
    assert result['reused'] is False and result['version_id'] is None
    assert result['status'] == 'uploaded'
    assert int(result['task_id']) > 0 and int(result['source_id']) > 0 and int(result['initial_processing_run_id']) > 0

    source = await db_session.get(KnowledgeSource, int(result['source_id']))
    assert source.status == 'uploaded' and source.knowledge_scope_id == scope and source.format == 'markdown'
    runs = (await db_session.execute(select(ProcessingRun).where(
        ProcessingRun.source_id == int(result['source_id'])))).scalars().all()
    assert [(run.run_type, run.status) for run in runs] == [('initial', 'pending')]

    after = await db_session.get(MemoryEntry, memory_id, populate_existing=True)
    assert {key: getattr(after, key) for key in original} == original
    assert after.promotion_pointer['task_id'] == result['task_id']
    assert after.promotion_pointer['source_id'] == int(result['source_id'])
    assert after.promotion_pointer['initial_processing_run_id'] == int(result['initial_processing_run_id'])
    assert after.promotion_pointer['status'] == 'uploaded'
    assert after.promotion_pointer['published_version_id'] is None
    assert after.provenance == 'distilled' and after.confidence == .97
    assert await _count(db_session, MemoryEvent, knowledge_scope_id=scope, event_type='consolidate') >= 1

    repeated = await promote(db_session, fixture)
    assert repeated['reused'] is True
    assert (repeated['task_id'], repeated['source_id'], repeated['initial_processing_run_id']) == (
        result['task_id'], result['source_id'], result['initial_processing_run_id'])
    assert await _count(db_session, KnowledgeSource, knowledge_scope_id=scope) == 2
    assert len([e for e in await _promotion_events(db_session, scope)
                if e.payload['grant_type'] == 'promotion_requested']) == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_promotion_yields_one_task_source_and_initial_run(db_session, memory_writer_owner):
    fixture = await committed_candidate(db_session, memory_writer_owner)
    scope = fixture['scope']
    await db_session.rollback()
    factory = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)

    async def request():
        async with factory() as session:
            return await MemoryService(session, embedding_provider=StableEmbedding()).promote_candidate(
                scope_id=scope, memory_id=fixture['memory_id'],
                candidate_version=fixture['candidate_version'], actor='management',
                reason='concurrent operator request')

    first, second = await asyncio.gather(request(), request())
    assert {first['task_id'], second['task_id']} == {first['task_id']}
    assert (first['source_id'], first['initial_processing_run_id']) == (
        second['source_id'], second['initial_processing_run_id'])
    assert sorted([first['reused'], second['reused']]) == [False, True]
    assert await _count(db_session, KnowledgeSource, knowledge_scope_id=scope) == 2
    assert len([e for e in await _promotion_events(db_session, scope)
                if e.payload['grant_type'] == 'promotion_requested']) == 1
    assert await _count(db_session, ProcessingRun, source_id=int(first['source_id'])) == 1


@pytest.mark.asyncio
async def test_crash_between_registration_and_scheduling_is_recovered_by_maintenance(db_session, memory_writer_owner):
    from rag_mcp.services.maintenance_service import resume_promotions

    fixture = await committed_candidate(db_session, memory_writer_owner)
    scope = fixture['scope']
    result = await promote(db_session, fixture)          # committed, never scheduled
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    scheduled = []
    resumed = await resume_promotions(db_session, scopes=[scope], schedule=scheduled.append, service=service)
    assert [item['task_id'] for item in resumed['resumed']] == [result['task_id']]
    assert scheduled == [int(result['source_id'])]
    assert resumed['failed'] == []
    assert await _count(db_session, KnowledgeSource, knowledge_scope_id=scope) == 2

    # The candidate becomes ineligible before dispatch: the same authorized task is
    # recorded as failed and never scheduled again.
    await db_session.execute(text("UPDATE knowledge_versions SET status='failed' WHERE version_id=:id"),
                             {'id': fixture['anchor']['version_id']})
    await db_session.commit()
    scheduled.clear()
    failed = await resume_promotions(db_session, scopes=[scope], schedule=scheduled.append, service=service)
    assert [item['task_id'] for item in failed['failed']] == [result['task_id']]
    assert failed['resumed'] == [] and scheduled == []
    entry = await db_session.get(MemoryEntry, fixture['memory_id'], populate_existing=True)
    assert entry.promotion_pointer['status'] == 'failed'
    assert entry.promotion_pointer['result'] == 'MEMORY_CANDIDATE_NOT_ELIGIBLE'


@pytest.mark.asyncio
async def test_real_publication_observation_and_explicit_retry_keep_task_and_source(db_session, memory_writer_owner):
    from rag_mcp.indexing.qdrant_client import QdrantStore
    from rag_mcp.services.ingestion_service import IngestionService

    fixture = await committed_candidate(db_session, memory_writer_owner)
    scope = fixture['scope']
    result = await promote(db_session, fixture)
    source_id = int(result['source_id'])
    await db_session.rollback()

    observed = await MemoryService(db_session, embedding_provider=StableEmbedding()).observe_promotion(
        source_id=source_id)
    assert observed['status'] == 'uploaded' and observed['published_version_id'] is None

    service = IngestionService(db_session, embedding_provider=StableEmbedding(), qdrant_store=QdrantStore())
    await service.ingest(source_id, graph_ready=False)
    await db_session.rollback()
    source = await db_session.get(KnowledgeSource, source_id, populate_existing=True)
    assert source.status == 'published'
    observed = await MemoryService(db_session, embedding_provider=StableEmbedding()).observe_promotion(
        source_id=source_id)
    assert observed['status'] == 'published' and observed['published_version_id']
    assert observed['attempt_run_ids'] == [int(result['initial_processing_run_id'])]
    assert observed['task_id'] == result['task_id']
    assert await _count(db_session, KnowledgeSource, knowledge_scope_id=scope) == 2

    await service.reprocess(source_id, graph_ready=False)
    await db_session.rollback()
    retried = await MemoryService(db_session, embedding_provider=StableEmbedding()).observe_promotion(
        source_id=source_id)
    assert retried['task_id'] == result['task_id'] and retried['source_id'] == source_id
    assert retried['initial_processing_run_id'] == int(result['initial_processing_run_id'])
    assert len(retried['attempt_run_ids']) == 2
    assert await _count(db_session, KnowledgeSource, knowledge_scope_id=scope) == 2
    assert len([e for e in await _promotion_events(db_session, scope)
                if e.payload['grant_type'] == 'promotion_requested']) == 1
    observations = [e for e in await _promotion_events(db_session, scope)
                    if e.payload['grant_type'] == 'promotion_observed']
    assert observations[-1].payload['pointer']['status'] == 'published'
    assert observations[-1].payload['pointer']['attempt_run_ids'][-1] == retried['attempt_run_ids'][-1]
    entry = await db_session.get(MemoryEntry, fixture['memory_id'], populate_existing=True)
    assert entry.promotion_pointer['status'] == 'published'


@pytest.mark.asyncio
async def test_unpublished_source_states_never_report_published(db_session, memory_writer_owner):
    fixture = await committed_candidate(db_session, memory_writer_owner)
    result = await promote(db_session, fixture)
    source_id = int(result['source_id'])
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    await db_session.rollback()
    assert (await service.promotion_status(task_id=result['task_id'], scope_id=fixture['scope']))['status'] == 'uploaded'
    assert (await service.observe_promotion(source_id=source_id))['published_version_id'] is None

    await db_session.execute(text("UPDATE knowledge_sources SET status='processing' WHERE source_id=:id"),
                             {'id': source_id})
    await db_session.execute(text("UPDATE processing_runs SET status='running' WHERE source_id=:id"),
                             {'id': source_id})
    await db_session.commit()
    processing = await service.observe_promotion(source_id=source_id)
    assert processing['status'] == 'processing' and processing['published_version_id'] is None

    await db_session.execute(text("UPDATE knowledge_sources SET status='failed' WHERE source_id=:id"),
                             {'id': source_id})
    await db_session.execute(text("UPDATE processing_runs SET status='failed' WHERE source_id=:id"),
                             {'id': source_id})
    await db_session.commit()
    failed = await service.observe_promotion(source_id=source_id)
    assert failed['status'] == 'failed' and failed['published_version_id'] is None
    assert (await service.promotion_status(task_id=result['task_id'], scope_id=fixture['scope']))['status'] == 'failed'
    assert await _count(db_session, KnowledgeVersion,
                        knowledge_scope_id=fixture['scope']) == 1  # only the anchor version


@pytest.mark.asyncio
async def test_legacy_upload_keeps_validation_and_registers_one_pending_initial_run(test_client, db_session):
    project = await test_client.post('/api/projects', json={'name': 'Phase6 Legacy Upload'})
    assert project.status_code == 201
    scope_id = project.json()['knowledge_scope_id']
    content = b'# Legacy upload\n\nUnchanged upload behaviour.'
    response = await test_client.post(f'/api/knowledge-sources?scope_id={scope_id}',
                                      files={'file': ('legacy.md', io.BytesIO(content), 'text/markdown')})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['status'] == 'uploaded' and body['format'] == 'markdown'
    assert body['size_bytes'] == len(content) and body['content_hash']
    runs = (await db_session.execute(select(ProcessingRun).where(
        ProcessingRun.source_id == int(body['source_id'])))).scalars().all()
    assert [(run.run_type, run.status) for run in runs] == [('initial', 'pending')]
    from pathlib import Path

    from rag_mcp.config import get_settings

    raw = Path(get_settings().data_root) / str(scope_id) / str(body['source_id']) / 'legacy.md'
    assert raw.read_bytes() == content
    empty = await test_client.post(f'/api/knowledge-sources?scope_id={scope_id}',
                                   files={'file': ('empty.md', io.BytesIO(b''), 'text/markdown')})
    assert empty.status_code == 400
    unsupported = await test_client.post(f'/api/knowledge-sources?scope_id={scope_id}',
                                         files={'file': ('bad.exe', io.BytesIO(b'MZ binary'), 'application/octet-stream')})
    assert unsupported.status_code == 400
    assert (await test_client.post('/api/knowledge-sources/999999999999/reprocess')).status_code == 404


@pytest.mark.asyncio
async def test_audit_ttl_purge_and_projection_rebuild_retain_candidate_and_pointer(db_session, memory_writer_owner):
    from datetime import timedelta
    from uuid import uuid4

    from rag_mcp.models.consolidation_run import ConsolidationRunObservation
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime

    fixture = await committed_candidate(db_session, memory_writer_owner)
    scope, memory_id = fixture['scope'], fixture['memory_id']
    result = await promote(db_session, fixture)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    # Audit TTL only ever deletes expired observations; the permanent candidate
    # marker and promotion pointer live in the authority log and must survive.
    expired_run, now = uuid4(), await db_session.scalar(text('SELECT clock_timestamp()'))
    db_session.add(ConsolidationRunObservation(run_id=expired_run, observation_seq=1,
        knowledge_scope_id=scope, trigger='manual', execution_context='distiller_window',
        status='succeeded', created_at=now - timedelta(days=8), ttl_expires_at=now - timedelta(seconds=1)))
    await db_session.commit()
    assert await runtime.purge_expired_observations() >= 1
    assert await db_session.get(ConsolidationRunObservation, (expired_run, 1)) is None
    entry = await db_session.get(MemoryEntry, memory_id, populate_existing=True)
    assert entry.candidate_version == fixture['candidate_version']
    assert entry.promotion_pointer['task_id'] == result['task_id']
    assert [e.payload['grant_type'] for e in await _promotion_events(db_session, scope)] == ['promotion_requested']
    await db_session.rollback()

    report = await service.rebuild(scope, actor='management')
    assert all(row['matches_replay'] for row in report.values())
    entry = await db_session.get(MemoryEntry, memory_id, populate_existing=True)
    assert entry.candidate_version == fixture['candidate_version']
    assert entry.candidate_basis['evidence_attributions'][0]['position'] == fixture['anchor']['position']
    assert entry.promotion_pointer['source_id'] == int(result['source_id'])
    assert entry.promotion_pointer['initial_processing_run_id'] == int(result['initial_processing_run_id'])
    assert (await service.promotion_status(task_id=result['task_id'], scope_id=scope))['status'] == 'uploaded'


@pytest.mark.asyncio
async def test_memory_rollback_retains_external_promotion_history(db_session, memory_writer_owner):
    fixture = await committed_candidate(db_session, memory_writer_owner)
    scope, memory_id = fixture['scope'], fixture['memory_id']
    result = await promote(db_session, fixture)
    await db_session.rollback()
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    origin = fixture['memory']['source_lineage'][0]['source_event_id']
    await service.govern('rollback', scope_id=scope, actor='management',
                         reason='restore the pre-promotion memory state', event_point=origin)
    entry = await db_session.get(MemoryEntry, memory_id, populate_existing=True)
    assert entry.status == 'retired'
    events = await _promotion_events(db_session, scope)
    assert [e.payload['grant_type'] for e in events] == ['promotion_requested']
    status = await service.promotion_status(task_id=result['task_id'], scope_id=scope)
    assert status['status'] == 'uploaded' and status['published_version_id'] is None
    assert status['task_id'] == result['task_id'] and status['source_id'] == int(result['source_id'])
    assert await _count(db_session, KnowledgeSource, knowledge_scope_id=scope) == 2
    assert (await service.promotion_status(task_id=result['task_id'], scope_id=scope))['result'] is None
