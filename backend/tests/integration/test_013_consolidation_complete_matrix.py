import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
from rag_mcp.orchestration.consolidation_pipeline import thaw
from rag_mcp.services.consolidation_commit import locked_approval, lower_group
from rag_mcp.services.memory_event_store import MemoryEventStore
from tests.integration.consolidation_commit_fixtures import commit, prepared


@pytest.mark.asyncio
@pytest.mark.parametrize('role', ['source', 'target'])
@pytest.mark.parametrize('change,reason', [('quarantined', 'SOURCE_NOT_ELIGIBLE'), ('superseded', 'SOURCE_NOT_ELIGIBLE'),
    ('retired', 'SOURCE_NOT_ELIGIBLE'), ('state_version', 'TARGET_VERSION_CHANGED'), ('source_version', 'TARGET_VERSION_CHANGED'),
    ('scope', 'SCOPE_MISMATCH'), ('expires', 'SOURCE_NOT_ELIGIBLE')])
async def test_locked_snapshot_boundary_rechecks_each_source_and_target_fact(db_session, memory_writer_owner, monkeypatch, role, change, reason):
    fixture = await prepared(db_session, memory_writer_owner, links=True)
    _service, runtime, _token, _batch, context, _ = fixture
    original = runtime.read_snapshot
    identifier = (context.window.input_episode_refs if role == 'source' else context.window.reference_refs)[0].memory_id
    # Quarantine has no existing active-to-quarantine governance command. This
    # explicit trusted-snapshot fault tests the commit adapter's changed fact,
    # while separate cases exercise persisted retirement and supersession.
    async def changed(scope):
        current = await original(scope)
        entries = thaw(current.entries)
        if change in ('quarantined', 'superseded', 'retired'):
            entries[identifier]['status'] = change
        elif change == 'scope':
            entries[identifier]['knowledge_scope_id'] = scope + 1
        elif change == 'expires':
            entries[identifier]['expires_at'] = '2000-01-01T00:00:00+00:00'
        elif change == 'state_version':
            entries[identifier]['state_event_id'] = entries[identifier]['source_event_id'] + 1
        else:
            entries[identifier]['source_event_id'] += 1
        return replace(current, entries=entries)
    monkeypatch.setattr(runtime, 'read_snapshot', changed)
    result = await commit(fixture)
    assert result.status == 'rejected' and reason in result.reason_codes
    assert not result.output_memory_ids and not result.output_event_ids


@pytest.mark.asyncio
async def test_persisted_supersede_after_proposal_is_rejected(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, _batch, context, _ = fixture
    await service.record({'scope_id': token.scope_id, 'kind': 'episodic', 'provenance': 'soft',
        'content': 'Corrected source replaces proposed input', 'supersedes_memory_id': context.window.input_episode_refs[0].memory_id,
        'inference_meta': {'source': 'governed correction', 'confidence': .8, 'model_version': 'fixture-v1',
            'time': datetime.now(UTC).isoformat(), 'supporting_evidence': []}})
    outcome = await commit(fixture)
    assert outcome.status == 'rejected' and 'SOURCE_NOT_ELIGIBLE' in outcome.reason_codes


@pytest.mark.asyncio
@pytest.mark.parametrize('change,reason', [('removed', 'LINK_TYPE_NOT_ALLOWED'), ('direction', 'LINK_DIRECTION_INVALID'),
    ('category', None)])
async def test_current_vocabulary_rechecked_after_valid_proposal(db_session, memory_writer_owner, change, reason):
    fixture = await prepared(db_session, memory_writer_owner, links=True)
    from rag_mcp.models.domain_profile import DomainProfile
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    token = fixture[2]
    profile = await db_session.get(DomainProfile, (await db_session.get(KnowledgeScope, token.scope_id)).domain_key)
    vocabulary = deepcopy(profile.memory_link_vocabulary)
    if change == 'removed':
        vocabulary = []
    elif change == 'direction':
        vocabulary[0]['from_kinds'] = ['episodic']
        reason = 'LINK_KIND_NOT_ALLOWED'
    else:
        vocabulary[0].update(category='live_dependency', propagation='to_to_from')
    profile.memory_link_vocabulary = vocabulary
    await db_session.commit()
    outcome = await commit(fixture)
    assert outcome.status == 'rejected' and not outcome.output_memory_ids
    if reason is not None:
        assert reason in outcome.reason_codes
    else:
        # T058: a live link is itself the support declaration, so a category
        # change no longer fails a rule check; it changes the captured approved
        # effect, the group key, and therefore the commit rejects the stale
        # approval without publishing the edge.
        current = await fixture[1].read_snapshot(token.scope_id)
        assert not any(link.get('relation_type') == 'related'
                       for row in current.entries.values()
                       for link in (row.get('approved_links') or {}).values())


@pytest.mark.asyncio
@pytest.mark.parametrize('point', ['append', 'receipt', 'manifest', 'summary_file'])
async def test_append_receipt_and_publication_failures_have_exact_atomic_outcomes(db_session, memory_writer_owner, monkeypatch, point):
    fixture = await prepared(db_session, memory_writer_owner)
    service, runtime, token, *_ = fixture
    old = (await service.projections.current(token.scope_id)).source_event_id
    await db_session.rollback()
    if point == 'append':
        async def fail(*args, **kwargs):
            raise DBAPIError('injected append', {}, RuntimeError('append failed'), False)
        monkeypatch.setattr(MemoryEventStore, 'append_many', fail)
    elif point == 'receipt':
        original = db_session.execute
        async def fail(statement, *args, **kwargs):
            if str(statement).startswith('INSERT INTO memory_projection_receipts'):
                raise DBAPIError('injected receipt', {}, RuntimeError('receipt failed'), False)
            return await original(statement, *args, **kwargs)
        monkeypatch.setattr(db_session, 'execute', fail)
    elif point == 'summary_file':
        async def fail(*args, **kwargs):
            raise OSError('summary filesystem unavailable')
        monkeypatch.setattr(service.projections, '_materialize_summary', fail)
    else:
        original = service.projections._upsert
        async def fail(state, scope, event, model, values, key, **kwargs):
            if model is MemoryProjectionMeta and values.get('projection_type') == 'manifest':
                raise DBAPIError('injected manifest', {}, RuntimeError('manifest failed'), False)
            return await original(state, scope, event, model, values, key, **kwargs)
        monkeypatch.setattr(service.projections, '_upsert', fail)
    result = await commit(fixture)
    assert result.status == ('pending' if point == 'summary_file' else 'rolled_back')
    assert not result.output_memory_ids and not result.output_event_ids
    assert (await service.projections.current(token.scope_id)).source_event_id == old
    assert not (await runtime.read_snapshot(token.scope_id)).consolidation_state['potential_source_outcomes']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,reason', [('lease', 'WRITER_LEASE_LOST'), ('deadline', 'CONSOLIDATION_COMMIT_TIMEOUT')])
async def test_actual_final_lease_and_transaction_deadline(db_session, memory_writer_owner, monkeypatch, failure, reason):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, *_ = fixture
    if failure == 'lease':
        original = service.projections.inspect
        async def expired(*args, **kwargs):
            result = await original(*args, **kwargs)
            await db_session.execute(text('RESET ROLE'))
            await db_session.execute(text("UPDATE writer_lease SET expires_at=clock_timestamp()-interval '1 second' WHERE lease_id=:id"), {'id': token.writer_lease_id})
            return result
        monkeypatch.setattr(service.projections, 'inspect', expired)
    else:
        from rag_mcp.services.consolidation_runtime import CommitFence
        original = CommitFence.validate_before_publish
        async def elapsed(self):
            self.started_at -= timedelta(seconds=31)
            return await original(self)
        elapsed.__name__ = 'validate_before_publish'
        monkeypatch.setattr(CommitFence, 'validate_before_publish', elapsed)
    result = await commit(fixture)
    assert result.status == 'rejected' and reason in result.reason_codes
    assert not result.output_memory_ids


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'gapped', 'group_id', 'count', 'aggregate', 'confidence', 'body', 'source_hash', 'outcome_group'])
async def test_database_group_and_payload_guards(db_session, memory_writer_owner, mutation):
    fixture = await prepared(db_session, memory_writer_owner)
    _service, runtime, token, batch, context, _decisions = fixture
    with pytest.raises(DBAPIError):
        async with runtime.commit_fence(token, context=context) as fence:
            checked, current, policy, fresh, now = await locked_approval(runtime, token, batch, context)
            fields = lower_group(checked.groups[0], checked, batch, fresh, policy, current, token, now)
            if mutation == 'missing':
                fields.pop()
            elif mutation == 'duplicate':
                fields[-1]['payload']['effect_index'] = 0
            elif mutation == 'gapped':
                fields[-1]['payload']['effect_index'] = 2
            elif mutation == 'group_id':
                from uuid import uuid4
                fields[-1]['payload']['group_id'] = str(uuid4())
            elif mutation == 'count':
                fields[-1]['payload']['effect_count'] = 3
            elif mutation == 'aggregate':
                fields[0]['aggregate_id'] += 123
            elif mutation == 'confidence':
                fields[0]['payload']['inference_meta']['confidence'] = .1
            elif mutation == 'body':
                fields[0]['payload']['content_text'] = 'Forged content without its approval hash'
            elif mutation == 'source_hash':
                fields[0]['payload']['source_refs'][0]['content_hash'] = 'a' * 64
            else:
                fields[0]['payload']['source_outcomes'][0]['required_group_key'] = 'f' * 64
            await db_session.execute(text("SELECT set_config('rag_memory.consolidation_token',:token,true)"), {'token': str(token.eligibility_id)})
            await db_session.execute(text("SELECT set_config('rag_memory.consolidation_fence',:fence,true),set_config('rag_memory.consolidation_started_at',:started,true)"),
                {'fence': json.dumps(token.to_dict()), 'started': fence.started_at.isoformat()})
            await db_session.execute(text('SET LOCAL ROLE rag_memory_reducer'))
            db_session.add_all(MemoryEvent(**value) for value in fields)
            await db_session.flush()
    assert not [e for e in await MemoryEventStore(db_session).replay(token.scope_id) if e['event_type'] == 'consolidate']


@pytest.mark.asyncio
async def test_pending_a_cannot_be_opened_or_consumed_by_disjoint_b(db_session, memory_writer_owner, monkeypatch):
    fixture = await prepared(db_session, memory_writer_owner, count=2, shared=False)
    service, runtime, token, batch, context, decisions = fixture
    first, second = decisions.groups
    original = service.projections._materialize_dense
    async def fail(*args, **kwargs):
        raise OSError('external pending A')
    monkeypatch.setattr(service.projections, '_materialize_dense', fail)
    a = await service.commit_approved(replace(decisions, groups=(first,)), token, runtime=runtime, batch=batch, context=context)
    assert a.status == 'pending'
    monkeypatch.setattr(service.projections, '_materialize_dense', original)
    b = await service.commit_approved(replace(decisions, groups=(second,)), token, runtime=runtime, batch=batch, context=context)
    assert b.status == 'pending' and b.pending_result_keys == (first.group_key,)
    assert not b.output_memory_ids and not (await runtime.read_snapshot(token.scope_id)).consolidation_state['potential_source_outcomes']


@pytest.mark.asyncio
async def test_sql_final_manifest_fence_after_receipt(db_session, memory_writer_owner, monkeypatch):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, *_ = fixture
    original = service.projections._upsert
    seen = []
    async def expire(state, scope, event, model, values, key, **kwargs):
        if model is MemoryProjectionMeta and values.get('projection_type') == 'manifest':
            await db_session.execute(text('RESET ROLE'))
            await db_session.execute(text("UPDATE consolidation_eligibilities SET expires_at=clock_timestamp()-interval '1 second' WHERE eligibility_id=:id"), {'id': token.eligibility_id})
            try:
                await original(state, scope, event, model, values, key, **kwargs)
            except DBAPIError as error:
                assert 'CONSOLIDATION_PUBLICATION_FENCE_LOST' in str(error)
                seen.append('sql final fence')
                raise
            return
        return await original(state, scope, event, model, values, key, **kwargs)
    monkeypatch.setattr(service.projections, '_upsert', expire)
    result = await commit(fixture)
    assert result.status == 'rolled_back' and seen == ['sql final fence'] and not result.output_memory_ids
