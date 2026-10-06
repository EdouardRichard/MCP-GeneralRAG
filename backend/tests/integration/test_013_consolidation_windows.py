from datetime import timedelta
import json
from copy import deepcopy

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from tests.integration.consolidation_fixtures import create_scope, recorded_episode, StableEmbedding


@pytest.mark.asyncio
async def test_permanent_window_retry_preserves_frozen_versions_after_new_inputs_and_audit_purge(db_session, memory_writer_owner, monkeypatch):
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
    from rag_mcp.services.memory_service import MemoryService
    from rag_mcp.models.domain_profile import DomainProfile
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    from rag_mcp.models.consolidation_run import ConsolidationRunObservation
    from rag_mcp.models.memory_event import MemoryEvent
    from rag_mcp.services.memory_reducer import reduce_events
    from rag_mcp.services.memory_event_store import MemoryEventStore
    scope = await create_scope(db_session)
    profile = await db_session.get(DomainProfile, (await db_session.get(KnowledgeScope, scope)).domain_key)
    profile.memory_policy = {'consolidation_enabled': True, 'consolidation': {'batch_size': 1}}
    await db_session.commit()
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    one = await recorded_episode(service, scope, 'First episode')
    await recorded_episode(service, scope, 'Second episode')
    reference = await recorded_episode(service, scope, 'Stable reference', kind='semantic')
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    token = await runtime.admit(scope, trigger='manual')
    window = await runtime.select_and_seal(token)
    assert [ref.memory_id for ref in window.input_episode_refs] == [one['memory_id']]
    assert [ref.memory_id for ref in window.reference_refs] == [reference['memory_id']]
    assert window.truncated
    await runtime.observe(token, status='no_change', degradation_reasons=['all_rejected'])
    assert await runtime.release(token)
    await recorded_episode(service, scope, 'Later episode outside original high water')
    resumed_token = await runtime.admit(scope, trigger='manual')
    resumed = await runtime.select_and_seal(resumed_token)
    assert resumed.window_id == window.window_id
    assert (resumed.start, resumed.end, resumed.high_water_mark) == (window.start, window.end, window.high_water_mark)
    assert await runtime.release(resumed_token)
    now = await db_session.scalar(text('SELECT clock_timestamp()'))
    db_session.add(ConsolidationRunObservation(run_id=token.run_id, observation_seq=99, knowledge_scope_id=scope,
        trigger='manual', execution_context='distiller_window', status='no_change',
        created_at=now-timedelta(days=8), ttl_expires_at=now-timedelta(days=1)))
    await db_session.commit()
    assert await runtime.purge_expired_observations() == 1

    async def no_audit_dependency(*args, **kwargs):
        pytest.fail('permanent window recovery read expiring observations')
    monkeypatch.setattr(runtime, 'latest_observation', no_audit_dependency)
    retry = await runtime.retry_window(scope, window.window_id)
    assert (retry.start, retry.end, retry.frozen_at, retry.high_water_mark) == (
        window.start, window.end, window.frozen_at, window.high_water_mark)
    assert retry.input_episode_refs == window.input_episode_refs
    assert retry.episodes == window.episodes
    assert retry.original_window_id == window.window_id
    state = reduce_events(await MemoryEventStore(db_session).replay(scope))
    assert state['consolidation_state']['potential_checkpoint'] is None
    assert state['consolidation_state']['potential_source_outcomes'] == {}
    sql_state = await db_session.scalar(text('SELECT memory_log_state(:scope,:event)'),
        {'scope': scope, 'event': await db_session.scalar(select(MemoryEvent.event_id).where(
            MemoryEvent.knowledge_scope_id == scope).order_by(MemoryEvent.event_id.desc()).limit(1))})
    assert sql_state == json.loads(json.dumps(state.export()))
    assert all(row['matches_replay'] for row in (await service.inspect_projections(scope)).values())


@pytest.mark.asyncio
async def test_window_control_source_guard_rejects_raw_actor_and_forged_qualification(db_session, memory_writer_owner):
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
    from rag_mcp.services.memory_service import MemoryService
    from rag_mcp.models.memory_event import MemoryEvent
    from rag_mcp.utils.snowflake import generate_id
    scope = await create_scope(db_session)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    await recorded_episode(service, scope, 'Guard fixture')
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    token = await runtime.admit(scope, trigger='manual')
    window = await runtime.select_and_seal(token)
    saved = await db_session.get(MemoryEvent, window.window_id)
    for actor in ('memory_tool', 'management'):
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                fields = {column.name: getattr(saved, column.name) for column in saved.__table__.columns
                          if column.name not in ('event_id', 'aggregate_id', 'created_at')}
                identifier = generate_id()
                db_session.add(MemoryEvent(**{**fields, 'event_id': identifier, 'aggregate_id': identifier, 'actor': actor}))
                await db_session.flush()
    await db_session.rollback()
    assert await runtime.release(token)


@pytest.mark.asyncio
async def test_selection_does_not_read_pending_tail_and_empty_windows_create_no_control_event(db_session, memory_writer_owner, monkeypatch):
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
    from rag_mcp.services.memory_service import MemoryService
    from rag_mcp.models.memory_event import MemoryEvent
    from sqlalchemy import func
    scope = await create_scope(db_session)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    token = await runtime.admit(scope, trigger='manual')
    empty = await runtime.select_and_seal(token)
    assert empty.input_episode_refs == () and empty.window_id is None
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent).where(MemoryEvent.knowledge_scope_id == scope)) == 0
    await db_session.rollback()
    assert await runtime.release(token)
    first = await recorded_episode(service, scope, 'Completed episode')
    before = await service.projections.current(scope)
    high_water = before.source_event_id
    async def unavailable(*args, **kwargs):
        raise OSError('controlled external failure')
    monkeypatch.setattr(service.projections, '_materialize_dense', unavailable)
    with pytest.raises(ValueError, match='MEMORY_WRITE_UNAVAILABLE'):
        await recorded_episode(service, scope, 'Pending episode')
    current = await runtime.read_snapshot(scope)
    assert current.high_water_mark == high_water
    assert list(current.entries) == [first['memory_id']]


@pytest.mark.asyncio
async def test_failed_window_publication_retains_control_but_cannot_return_successful_selection(db_session, memory_writer_owner, monkeypatch):
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, ConsolidationRuntimeError
    from rag_mcp.services.memory_service import MemoryService
    from rag_mcp.models.memory_event import MemoryEvent
    scope = await create_scope(db_session)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    await recorded_episode(service, scope, 'Publication fault fixture')
    before = (await service.projections.current(scope)).source_event_id
    await db_session.rollback()
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    token = await runtime.admit(scope, trigger='manual')
    async def unavailable(*args, **kwargs):
        raise OSError('controlled dense failure')
    monkeypatch.setattr(service.projections, '_materialize_dense', unavailable)
    with pytest.raises(ConsolidationRuntimeError, match='CONSOLIDATION_WINDOW_PUBLICATION_PENDING'):
        await runtime.select_and_seal(token)
    assert (await service.projections.current(scope)).source_event_id == before
    pending = await db_session.scalar(select(MemoryEvent).where(MemoryEvent.knowledge_scope_id == scope,
        MemoryEvent.event_type == 'grant').order_by(MemoryEvent.event_id.desc()).limit(1))
    assert pending is not None
    assert (await runtime.latest_observation(token.run_id)).status == 'failed'
    with pytest.raises(ConsolidationRuntimeError, match='CONSOLIDATION_WINDOW_UNAVAILABLE'):
        await runtime.retry_window(scope, pending.event_id)
    monkeypatch.undo()
    await service.rebuild(scope, actor='management', reason='Restore pending window control')
    retry = await runtime.retry_window(scope, pending.event_id)
    assert retry.window_id == pending.event_id
    await db_session.rollback()
    assert await runtime.release(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('malformation', ['unknown_permission', 'null_timeline', 'missing_token_scope'])
async def test_trusted_database_window_guard_rejects_malformed_control(db_session, memory_writer_owner, malformation):
    from rag_mcp.models.memory_event import MemoryEvent
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
    from rag_mcp.services.memory_service import MemoryService
    from rag_mcp.utils.snowflake import generate_id

    scope = await create_scope(db_session)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    await recorded_episode(service, scope, 'Malformed control guard fixture')
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    token = await runtime.admit(scope, trigger='manual')
    window = await runtime.select_and_seal(token)
    saved = await db_session.get(MemoryEvent, window.window_id)
    fields = {column.name: deepcopy(getattr(saved, column.name)) for column in saved.__table__.columns
              if column.name not in ('event_id', 'aggregate_id', 'created_at')}
    if malformation == 'unknown_permission':
        fields['payload']['writer_permission'] = True
    elif malformation == 'null_timeline':
        for field in ('start', 'end', 'frozen_at'):
            fields['payload'][field] = None
    else:
        del fields['payload']['eligibility_token']['scope_id']
    try:
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(text('SET LOCAL ROLE rag_memory_reducer'))
                await db_session.execute(text("SELECT set_config('rag_memory.consolidation_token',:token,true)"),
                                         {'token': str(token.eligibility_id)})
                identifier = generate_id()
                db_session.add(MemoryEvent(**{**fields, 'event_id': identifier, 'aggregate_id': identifier}))
                await db_session.flush()
    finally:
        await db_session.rollback()
    assert await runtime.release(token)


@pytest.mark.asyncio
async def test_first_publication_failure_requires_recovery_instead_of_empty_window(db_session, memory_writer_owner, monkeypatch):
    from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, ConsolidationRuntimeError
    from rag_mcp.services.memory_service import MemoryService

    scope = await create_scope(db_session)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    async def unavailable(*args, **kwargs):
        raise OSError('controlled first publication failure')
    monkeypatch.setattr(service.projections, '_materialize_dense', unavailable)
    with pytest.raises(ValueError, match='MEMORY_WRITE_UNAVAILABLE'):
        await recorded_episode(service, scope, 'First unpublished episode')
    assert await db_session.get(MemoryProjectionMeta, f'current:{scope}') is None
    await db_session.rollback()
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    token = await runtime.admit(scope, trigger='manual')
    with pytest.raises(ConsolidationRuntimeError, match='CONSOLIDATION_COMPLETE_MANIFEST_REQUIRED'):
        await runtime.select_and_seal(token)
    assert (await runtime.latest_observation(token.run_id)).status == 'admitted'
    await db_session.rollback()
    assert await runtime.release(token)


@pytest.mark.asyncio
async def test_budget_exclusion_is_reported_separately_from_empty_window(db_session, memory_writer_owner):
    from rag_mcp.models.domain_profile import DomainProfile
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
    from rag_mcp.services.memory_service import MemoryService

    scope = await create_scope(db_session)
    profile = await db_session.get(DomainProfile, (await db_session.get(KnowledgeScope, scope)).domain_key)
    profile.memory_policy = {'consolidation_enabled': True, 'consolidation': {'max_input_chars': 4000}}
    await db_session.commit()
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    oversized = await recorded_episode(service, scope, 'x' * 4000)
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    token = await runtime.admit(scope, trigger='manual')
    window = await runtime.select_and_seal(token)
    assert window.input_episode_refs == () and window.truncated and window.window_id is None
    assert (await runtime.latest_observation(token.run_id)).degradation_reasons == ['input_budget_excluded']
    current = await runtime.read_snapshot(scope)
    assert current.entries[oversized['memory_id']]['status'] == 'active'
    assert current.consolidation_state['potential_source_outcomes'] == {}
    await db_session.rollback()
    assert await runtime.release(token)
    fitting = await recorded_episode(service, scope, 'A later fitting episode')
    token = await runtime.admit(scope, trigger='manual')
    window = await runtime.select_and_seal(token)
    assert [ref.memory_id for ref in window.input_episode_refs] == [fitting['memory_id']]
    assert window.truncated and window.window_id is not None
    current = await runtime.read_snapshot(scope)
    assert current.entries[oversized['memory_id']]['status'] == 'active'
    assert current.consolidation_state['potential_source_outcomes'] == {}
    await db_session.rollback()
    assert await runtime.release(token)
