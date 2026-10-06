import pytest
from sqlalchemy import select, text

from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.services.memory_event_store import MemoryEventStore
from tests.integration.consolidation_commit_fixtures import commit, prepared


@pytest.mark.asyncio
async def test_commit_preserves_approved_content_confidence_context_and_consumes_only_complete(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner)
    service, runtime, token, batch, _context, _decisions = fixture
    result = await commit(fixture)
    assert result.status == 'completed'
    assert len(result.output_memory_ids) == 1 and len(result.output_event_ids) == 2
    current = await runtime.read_snapshot(token.scope_id)
    output = current.entries[result.output_memory_ids[0]]
    assert output['content_text'] == batch.proposals[0]['content']
    assert output['confidence'] == output['inference_meta']['confidence'] == .87
    assert output['context_digest'] == 'Navigation summary 0'
    assert list(output['keywords']) == ['second', 'first']
    assert output['source_lineage'] and not output['evidence_refs']
    assert not output.get('candidate_version')
    assert current.consolidation_state['potential_source_outcomes']
    assert all(v['matches_replay'] for v in (await service.inspect_projections(token.scope_id)).values())


@pytest.mark.asyncio
@pytest.mark.parametrize('change,reason', [('retire', 'SOURCE_NOT_ELIGIBLE'), ('threshold', 'CONFIDENCE_BELOW_THRESHOLD'),
    ('quota', 'QUOTA_EXCEEDED'), ('switch', 'CONSOLIDATION_DISABLED'), ('eligibility', 'ELIGIBILITY_LOST')])
async def test_commit_rechecks_actual_changed_authority(db_session, memory_writer_owner, change, reason):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, _batch, context, _decisions = fixture
    if change == 'retire':
        await service.govern('retire', scope_id=token.scope_id, memory_id=context.window.input_episode_refs[0].memory_id,
                             actor='management', reason='Changed before commit')
    elif change == 'eligibility':
        await db_session.execute(text("UPDATE consolidation_eligibilities SET expires_at=clock_timestamp()-interval '1 second' WHERE eligibility_id=:id"), {'id': token.eligibility_id})
        await db_session.commit()
    else:
        scope = await db_session.get(KnowledgeScope, token.scope_id)
        profile = await db_session.get(DomainProfile, scope.domain_key)
        policy = dict(profile.memory_policy)
        if change == 'threshold':
            policy['consolidation'] = {'min_confidence': .99, 'candidate_min_confidence': .99}
        elif change == 'quota':
            policy['per_scope_memory_quota'] = 1
        else:
            policy['consolidation_enabled'] = False
        profile.memory_policy = policy
        await db_session.commit()
    result = await commit(fixture)
    assert result.status == 'rejected' and reason in result.reason_codes
    assert not result.output_memory_ids
    assert not (await db_session.execute(select(MemoryEvent).where(MemoryEvent.knowledge_scope_id == token.scope_id,
        MemoryEvent.event_type == 'consolidate'))).scalars().all()


@pytest.mark.asyncio
@pytest.mark.parametrize('path,expected', [('relation', 'rolled_back'), ('links', 'rolled_back'),
    ('summary', 'rolled_back'), ('dense', 'pending'), ('files', 'pending')])
async def test_group_failure_is_atomic_and_old_complete_prefix_readable(db_session, memory_writer_owner, monkeypatch, path, expected):
    fixture = await prepared(db_session, memory_writer_owner, count=2)
    service, runtime, token, _batch, _context, decisions = fixture
    previous = await runtime.read_snapshot(token.scope_id)
    await db_session.rollback()
    async def fail(*args, **kwargs):
        raise RuntimeError('injected adapter failure')
    monkeypatch.setattr(service.projections, f'_materialize_{path}', fail)
    result = await commit(fixture)
    assert result.status == expected and not result.output_memory_ids and not result.output_event_ids
    visible = await runtime.read_snapshot(token.scope_id)
    assert visible.high_water_mark == previous.high_water_mark
    assert visible.entries == previous.entries
    assert not visible.consolidation_state['potential_source_outcomes']
    events = [e for e in await MemoryEventStore(db_session).replay(token.scope_id) if e['event_type'] == 'consolidate']
    assert len(events) == (4 if expected == 'pending' else 0)
    if events:
        assert {e['payload']['group_key'] for e in events} == {decisions.groups[0].group_key}


@pytest.mark.asyncio
async def test_final_fence_runs_before_receipt_and_manifest(db_session, memory_writer_owner, monkeypatch):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, *_ = fixture
    old = await service.projections.current(token.scope_id)
    previous = old.source_event_id
    await db_session.rollback()
    original = service.projections.inspect
    async def expire_after_inspection(*args, **kwargs):
        report = await original(*args, **kwargs)
        await db_session.execute(text('RESET ROLE'))
        await db_session.execute(text("UPDATE consolidation_eligibilities SET expires_at=clock_timestamp()-interval '1 second' WHERE eligibility_id=:id"), {'id': token.eligibility_id})
        return report
    monkeypatch.setattr(service.projections, 'inspect', expire_after_inspection)
    result = await commit(fixture)
    assert result.status == 'rejected' and 'ELIGIBILITY_LOST' in result.reason_codes
    assert (await service.projections.current(token.scope_id)).source_event_id == previous
