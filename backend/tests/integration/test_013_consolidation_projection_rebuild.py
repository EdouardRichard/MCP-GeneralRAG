import pytest

from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_reducer import projection_fingerprint, reduce_events
from tests.integration.consolidation_commit_fixtures import commit, prepared
from tests.integration.consolidation_fixtures import recorded_episode


@pytest.mark.asyncio
async def test_nonempty_context_full_and_delta_replay_rebuild_all_six_outputs(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner, count=2)
    service, _runtime, token, *_ = fixture
    result = await commit(fixture)
    assert result.status == 'completed'
    events = await MemoryEventStore(db_session).replay(token.scope_id)
    full = reduce_events(events)
    split = next(i for i, e in enumerate(events) if e['event_type'] == 'consolidate')
    delta = reduce_events(events[split:], initial_state=reduce_events(events[:split]))
    assert projection_fingerprint(full) == projection_fingerprint(delta)
    assert all(full['entries'][mid]['context_digest'] for mid in result.output_memory_ids)
    await db_session.rollback()
    rebuilt = await service.rebuild(token.scope_id, actor='management')
    assert len(rebuilt) == 6 and all(row['matches_replay'] for row in rebuilt.values())


@pytest.mark.asyncio
async def test_advanced_typed_edges_survive_revision_history_audit_ttl_and_rollback(db_session,
                                                                                    memory_writer_owner):
    from sqlalchemy import select, text

    from rag_mcp.models.memory_link import MemoryLink

    fixture = await prepared(db_session, memory_writer_owner, links=True)
    service, runtime, token = fixture[0], fixture[1], fixture[2]
    reference = fixture[4].window.reference_refs[0].memory_id
    result = await commit(fixture)
    assert result.status == 'completed'
    output = result.output_memory_ids[0]
    # A later ordinary publication re-materializes the same typed edge at a new revision.
    await recorded_episode(service, token.scope_id, 'Later ordinary episode')
    typed = (await db_session.execute(select(MemoryLink).where(
        MemoryLink.knowledge_scope_id == token.scope_id, MemoryLink.relation_type == 'related')
        .order_by(MemoryLink.revision_id))).scalars().all()
    assert len({row.revision_id for row in typed}) >= 2, 'historical revisions repeat the same edge'
    assert {(row.from_id, row.to_id) for row in typed} == {(str(output), str(reference))}
    latest = typed[-1]
    assert latest.to_kind == 'memory' and latest.provenance == 'llm_proposed'
    assert latest.semantic_category == 'association' and latest.propagation == 'none'
    assert len(latest.vocabulary_version) == 64 and latest.created_by_run == token.run_id
    assert latest.source_event_id and latest.data['category'] == latest.semantic_category
    # Base 012 edges stay valid next to the advanced vocabulary.
    base = (await db_session.execute(select(MemoryLink).where(
        MemoryLink.knowledge_scope_id == token.scope_id,
        MemoryLink.relation_type == 'supersedes'))).scalars().all()
    assert all(row.provenance == 'deterministic' and row.vocabulary_version == '012-base-v1' for row in base)

    # Expired run audits purge without touching the permanent typed registry.
    from datetime import timedelta

    from rag_mcp.models.consolidation_run import ConsolidationRunObservation

    now = await db_session.scalar(text('SELECT clock_timestamp()'))
    db_session.add(ConsolidationRunObservation(run_id=token.run_id, observation_seq=900,
        knowledge_scope_id=token.scope_id, trigger='manual', execution_context='distiller_window',
        status='succeeded', created_at=now - timedelta(days=8), ttl_expires_at=now - timedelta(seconds=1)))
    await db_session.commit()
    assert await runtime.purge_expired_observations() >= 1
    before = projection_fingerprint(reduce_events(await MemoryEventStore(db_session).replay(token.scope_id)))
    await db_session.rollback()
    rebuilt = await service.rebuild(token.scope_id, actor='management')
    assert len(rebuilt) == 6 and all(row['matches_replay'] for row in rebuilt.values())
    state = reduce_events(await MemoryEventStore(db_session).replay(token.scope_id))
    assert projection_fingerprint(state) == before
    assert any(value.get('relation_type') == 'related' and value.get('category') == 'association'
               and value.get('propagation') == 'none' for value in state['links'].values())

    # Rollback to the window seal restores the pre-commit registry exactly.
    events = await MemoryEventStore(db_session).replay(token.scope_id)
    seal = next(event for event in events if event['event_type'] == 'grant')
    rollback = await service.govern('rollback', scope_id=token.scope_id, event_point=seal['event_id'],
                                    actor='management', reason='restore pre-commit registry')
    assert rollback['event_id']
    restored = reduce_events(await MemoryEventStore(db_session).replay(token.scope_id))
    assert not any(value.get('relation_type') == 'related' for value in restored['links'].values())
    tombstone = restored['entries'][output]
    assert tombstone['status'] == 'retired'
    assert tombstone['source_event_id'] != tombstone['state_event_id'] == rollback['event_id']
