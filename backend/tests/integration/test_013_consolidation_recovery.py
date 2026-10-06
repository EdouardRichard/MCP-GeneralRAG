import pytest

from rag_mcp.services.memory_event_store import MemoryEventStore
from tests.integration.consolidation_commit_fixtures import commit, prepared


@pytest.mark.asyncio
@pytest.mark.parametrize('stale', [False, True])
async def test_recovery_preserves_ids_and_revalidates_current_protection(db_session, memory_writer_owner, monkeypatch, stale):
    fixture = await prepared(db_session, memory_writer_owner, count=2)
    service, runtime, token, *_ = fixture
    original = service.projections._materialize_dense
    async def fail(*args, **kwargs):
        raise RuntimeError('external failure')
    monkeypatch.setattr(service.projections, '_materialize_dense', fail)
    failed = await commit(fixture)
    assert failed.status == 'pending' and not failed.output_memory_ids
    history = await MemoryEventStore(db_session).replay(token.scope_id)
    await db_session.rollback()
    monkeypatch.setattr(service.projections, '_materialize_dense', original)
    assert await runtime.release(token)
    if stale:
        from sqlalchemy import text
        await db_session.execute(text("UPDATE domain_profiles SET memory_policy=jsonb_set(memory_policy,'{consolidation}', jsonb_build_object('min_confidence',0.99,'candidate_min_confidence',0.99)) WHERE domain_key=(SELECT domain_key FROM knowledge_scopes WHERE scope_id=:scope)"), {'scope': token.scope_id})
        await db_session.commit()
    new_token = await runtime.admit(token.scope_id, trigger='manual')
    recovered = await service.recover_consolidation(new_token, runtime=runtime)
    assert recovered.status == ('pending' if stale else 'completed')
    assert await MemoryEventStore(db_session).replay(token.scope_id) == history
    current = await runtime.read_snapshot(token.scope_id)
    assert bool(current.consolidation_state['potential_source_outcomes']) is not stale


@pytest.mark.asyncio
async def test_plain_rebuild_cannot_publish_pending_consolidation(db_session, memory_writer_owner, monkeypatch):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, *_ = fixture
    original = service.projections._materialize_dense
    async def fail(*args, **kwargs):
        raise RuntimeError('external failure')
    monkeypatch.setattr(service.projections, '_materialize_dense', fail)
    assert (await commit(fixture)).status == 'pending'
    monkeypatch.setattr(service.projections, '_materialize_dense', original)
    with pytest.raises(ValueError, match='CONSOLIDATION_PENDING_RECOVERY_REQUIRED'):
        await service.rebuild(token.scope_id, actor='management')
