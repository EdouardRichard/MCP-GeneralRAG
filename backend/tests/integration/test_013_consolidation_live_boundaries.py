from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from sqlalchemy import text

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch, thaw
from rag_mcp.services.consolidation_adjudicator import adjudicate_batch
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_policy import MemoryPolicy
from rag_mcp.utils.snowflake import generate_id
from tests.integration.consolidation_commit_fixtures import commit, prepared
from tests.unit.consolidation_cases import facts


async def anchored(fixture, session):
    service, runtime, token, batch, context, _ = fixture
    source, version, chunk = generate_id(), generate_id(), generate_id()
    await session.execute(text("INSERT INTO knowledge_sources(source_id,knowledge_scope_id,filename,content_hash,format,size_bytes,status) VALUES (:id,:scope,'approved.md',:hash,'markdown',15,'published')"),
        {'id': source, 'scope': token.scope_id, 'hash': sha256(b'Published support').hexdigest()})
    await session.execute(text("INSERT INTO knowledge_versions(version_id,knowledge_scope_id,version_number,status) VALUES (:id,:scope,1,'published')"), {'id': version, 'scope': token.scope_id})
    await session.execute(text("INSERT INTO chunks(chunk_id,source_id,version_id,knowledge_scope_id,content_text,position_path,chunk_type,start_line,end_line,token_count,embedding_model,index_version) VALUES (:id,:source,:version,:scope,'Published support','section/1','paragraph',1,1,2,'fixture-v1','fixture-v1')"),
        {'id': chunk, 'source': source, 'version': version, 'scope': token.scope_id})
    await session.commit()
    proposals = thaw(batch.proposals)
    proposals[0].update(evidence_refs=[str(chunk)], confidence=.97)
    support = {str(chunk): {'knowledge_scope_id': token.scope_id, 'source_scope_id': token.scope_id,
        'version_scope_id': token.scope_id, 'status': 'published', 'source_status': 'published',
        'version_id': version, 'source_id': source, 'version': 1, 'position': 'section/1',
        'content_hash': sha256(b'Published support').hexdigest(), 'attributed': True}}
    context = replace(context, inferences={'p0': facts(proposals[0])}, support_facts=support, support_versions=support)
    batch = ProposalBatch(proposals)
    current = await runtime.read_snapshot(token.scope_id)
    decisions = adjudicate_batch(batch, current, MemoryPolicy.model_validate(thaw(context.window.policy)), current.vocabulary,
        {'count': current.quota_count, 'limit': 5000}, context, datetime.now(UTC))
    assert decisions.groups and any(e['value'].get('promotion_candidate') for e in decisions.decisions[0].approved_effects)
    await session.rollback()
    return (service, runtime, token, batch, context, decisions), (source, version, chunk)


@pytest.mark.asyncio
@pytest.mark.parametrize('change,reason', [(None, None), ('source_status', 'EVIDENCE_UNAVAILABLE'),
    ('version_status', 'EVIDENCE_UNAVAILABLE'), ('version', 'TARGET_VERSION_CHANGED'),
    ('position', 'ATTRIBUTION_FAILED'), ('hash', 'TARGET_VERSION_CHANGED')])
async def test_locked_evidence_attribution_and_candidate_basis(db_session, memory_writer_owner, change, reason):
    fixture, ids = await anchored(await prepared(db_session, memory_writer_owner), db_session)
    source, version, chunk = ids
    if change:
        query, params = {
            'source_status': ("UPDATE knowledge_sources SET status='failed' WHERE source_id=:id", {'id': source}),
            'version_status': ("UPDATE knowledge_versions SET status='failed' WHERE version_id=:id", {'id': version}),
            'version': ("UPDATE knowledge_versions SET version_number=2 WHERE version_id=:id", {'id': version}),
            'position': ("UPDATE chunks SET position_path='' WHERE chunk_id=:id", {'id': chunk}),
            'hash': ("UPDATE chunks SET content_text='Changed published support' WHERE chunk_id=:id", {'id': chunk})}[change]
        await db_session.execute(text(query), params)
        await db_session.commit()
    result = await commit(fixture)
    if change:
        assert result.status == 'rejected' and reason in result.reason_codes
        assert not result.output_memory_ids
    else:
        assert result.status == 'completed', result.reason_codes
        current = await fixture[1].read_snapshot(fixture[2].scope_id)
        output = current.entries[result.output_memory_ids[0]]
        assert output['candidate_version'] and output['candidate_basis']['evidence_attributions'][0]['evidence_id'] == str(chunk)
        assert output['provenance'] == 'distilled' and output['confidence'] == .97


@pytest.mark.asyncio
@pytest.mark.parametrize('change,reason', [('source_expired', 'SOURCE_NOT_ELIGIBLE'), ('lease', 'WRITER_LEASE_LOST'),
    ('scope', 'MISSING_KNOWLEDGE_SCOPE'), ('configuration', 'CONSOLIDATION_CONFIGURATION_REQUIRED')])
async def test_live_expiry_lease_scope_and_configuration(db_session, memory_writer_owner, monkeypatch, change, reason):
    fixture = await prepared(db_session, memory_writer_owner)
    _service, _runtime, token, *_ = fixture
    if change == 'source_expired':
        import rag_mcp.services.consolidation_commit as boundary
        original = boundary.adjudicate_batch
        def after_expiry(batch, current, policy, vocabulary, quota, context, now):
            return original(batch, current, policy, vocabulary, quota, context, now + timedelta(days=181))
        monkeypatch.setattr(boundary, 'adjudicate_batch', after_expiry)
    else:
        query, params = {
            'lease': ("UPDATE writer_lease SET expires_at=clock_timestamp()-interval '1 second' WHERE lease_id=:id", {'id': token.writer_lease_id}),
            'scope': ("UPDATE knowledge_scopes SET status='inactive' WHERE scope_id=:id", {'id': token.scope_id}),
            'configuration': ("UPDATE domain_profiles SET memory_policy=jsonb_build_object('consolidation_enabled',true) WHERE domain_key=(SELECT domain_key FROM knowledge_scopes WHERE scope_id=:id)", {'id': token.scope_id})}[change]
        await db_session.execute(text(query), params)
        await db_session.commit()
    result = await commit(fixture)
    assert result.status == 'rejected' and reason in result.reason_codes
    assert not result.output_event_ids


@pytest.mark.asyncio
async def test_pending_recovery_observes_later_authority_retirement(db_session, memory_writer_owner, monkeypatch):
    fixture = await prepared(db_session, memory_writer_owner)
    service, runtime, token, _batch, context, _ = fixture
    original = service.projections._materialize_dense
    async def fail(*args, **kwargs):
        raise RuntimeError('external failure')
    monkeypatch.setattr(service.projections, '_materialize_dense', fail)
    assert (await commit(fixture)).status == 'pending'
    monkeypatch.setattr(service.projections, '_materialize_dense', original)
    now = datetime.now(UTC)
    event = MemoryEvent(event_id=generate_id(), aggregate_id=context.window.input_episode_refs[0].memory_id,
        knowledge_scope_id=token.scope_id, event_type='retract', payload={'reason': 'later governed retirement'},
        actor='management', request_id='later-governed-retirement', occurred_at=now,
        authority={'source': 'management'}, scope_meta={'knowledge_scope_id': token.scope_id},
        mutability={'correction': 'append_event'}, provenance_meta={'source': 'management'},
        recoverability={'source': 'event_log'}, actionability='audit')
    await MemoryEventStore(db_session).append(event)
    await db_session.commit()
    assert await runtime.release(token)
    new_token = await runtime.admit(token.scope_id, trigger='manual')
    result = await service.recover_consolidation(new_token, runtime=runtime)
    assert result.status == 'pending' and 'PENDING_REQUIRES_GOVERNANCE' in result.reason_codes
    assert not (await runtime.read_snapshot(token.scope_id)).consolidation_state['potential_source_outcomes']


@pytest.mark.asyncio
async def test_disjoint_groups_preserve_actual_partial_publication(db_session, memory_writer_owner, monkeypatch):
    fixture = await prepared(db_session, memory_writer_owner, count=2, shared=False)
    service, runtime, token, *_ = fixture
    original = service.projections._materialize_dense
    calls = 0
    async def second_fails(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('second external failure')
        return await original(*args, **kwargs)
    monkeypatch.setattr(service.projections, '_materialize_dense', second_fails)
    result = await commit(fixture)
    assert result.status == 'pending' and len(result.output_memory_ids) == 1 and len(result.pending_result_keys) == 1
    current = await runtime.read_snapshot(token.scope_id)
    assert len(current.consolidation_state['potential_source_outcomes']) == 1
    assert len(current.consolidation_state['potential_results']) == 1


@pytest.mark.asyncio
async def test_database_receipt_requires_full_live_consolidation_fence(db_session, memory_writer_owner, monkeypatch):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, _token, *_ = fixture
    original = service.projections.inspect
    async def drop_token(*args, **kwargs):
        result = await original(*args, **kwargs)
        await db_session.execute(text("SELECT set_config('rag_memory.consolidation_token','',true)"))
        return result
    monkeypatch.setattr(service.projections, 'inspect', drop_token)
    result = await commit(fixture)
    assert result.status in ('rejected', 'rolled_back') and not result.output_memory_ids
