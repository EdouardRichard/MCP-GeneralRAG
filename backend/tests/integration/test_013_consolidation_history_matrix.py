import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from qdrant_client.models import FilterSelector

from rag_mcp.indexing.memory_vectors import revision_filter
from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch, thaw
from rag_mcp.runtime.projection_rebuild import SNAPSHOT_VIEWS, MemoryHistory, ProjectionRebuilder
from rag_mcp.services.consolidation_adjudicator import AdjudicationContext, adjudicate_batch, memory_ref
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_policy import MemoryPolicy
from rag_mcp.services.memory_reducer import projection_fingerprint, reduce_events
from tests.integration.consolidation_commit_fixtures import commit, prepared
from tests.integration.consolidation_fixtures import recorded_episode
from tests.integration.test_013_consolidation_live_boundaries import anchored
from tests.unit.consolidation_cases import facts


async def next_fixture(fixture, session, *, same_content=False, add_source=True):
    service, runtime, old_token, batch, context, _ = fixture
    await session.rollback()
    assert await runtime.release(old_token)
    if add_source:
        await recorded_episode(service, old_token.scope_id, 'Later observed episode ' + uuid4().hex)
    token = await runtime.admit(old_token.scope_id, trigger='manual')
    window = await runtime.select_and_seal(token)
    current = await runtime.read_snapshot(token.scope_id)
    proposal = thaw(batch.proposals[0])
    proposal['source_refs'] = [memory_ref(current.entries[window.input_episode_refs[0].memory_id])]
    if not same_content:
        proposal['content'] += ' later'
    proposal['context'] = {'context_digest': 'Second nonempty context version', 'keywords': ['third', 'first']}
    context = AdjudicationContext(window=window, inferences={'p0': facts(proposal)},
                                 support_facts=context.support_facts, support_versions=context.support_versions)
    batch = ProposalBatch([proposal])
    policy = MemoryPolicy.model_validate(thaw(window.policy))
    decisions = adjudicate_batch(batch, current, policy, current.vocabulary,
        {'count': current.quota_count, 'limit': 5000}, context, datetime.now(UTC))
    assert decisions.groups and decisions.decisions[0].decision == 'accept'
    await session.rollback()
    return service, runtime, token, batch, context, decisions


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['full', 'snapshot_delta'])
async def test_nonempty_six_outputs_restore_after_external_deletion_and_audit_ttl(db_session, memory_writer_owner, monkeypatch, path):
    fixture, _ = await anchored(await prepared(db_session, memory_writer_owner, links=True), db_session)
    service, runtime, token, *_ = fixture
    first = await commit(fixture)
    assert first.status == 'completed'
    history = MemoryHistory(service)
    snapshot = await history.capture(token.scope_id, force=True) if path == 'snapshot_delta' else None
    fixture = await next_fixture(fixture, db_session)
    second = await commit(fixture)
    assert second.status == 'completed'
    token = fixture[2]
    events = await MemoryEventStore(db_session).replay(token.scope_id)
    expected = reduce_events(events)
    assert expected['links'] and expected['consolidation_state']['potential_source_outcomes']
    for mid in (*first.output_memory_ids, *second.output_memory_ids):
        row = expected['entries'][mid]
        assert row['context_digest'] and row['context_version'] and row['candidate_version'] and row['source_lineage']
    manifest = await service.projections.current(token.scope_id)
    directory = Path(manifest.payload['root']) / str(token.scope_id) / str(manifest.source_event_id)
    for path_in_revision in directory.rglob('*'):
        if path_in_revision.is_file():
            assert path_in_revision.resolve().is_relative_to(service.projections.root)
            path_in_revision.unlink()
    await asyncio.to_thread(service.projections.qdrant._client.delete,
        collection_name=manifest.payload['collection'], points_selector=FilterSelector(
            filter=revision_filter(token.scope_id, manifest.source_event_id)), wait=True)
    from rag_mcp.models.consolidation_run import ConsolidationRunObservation
    stamp = datetime.now(UTC)
    db_session.add(ConsolidationRunObservation(run_id=token.run_id, observation_seq=99, knowledge_scope_id=token.scope_id,
        trigger='manual', execution_context='distiller_window', status='succeeded',
        created_at=stamp-timedelta(days=9), ttl_expires_at=stamp-timedelta(days=1)))
    await db_session.commit()
    assert await runtime.purge_expired_observations() == 1
    from rag_mcp.agents.memory_distiller import MemoryDistiller
    def no_model(*args, **kwargs):
        pytest.fail('rebuild invoked model')
    monkeypatch.setattr(MemoryDistiller, 'execute', no_model)
    recovered = await history.load(token.scope_id)
    assert recovered.source == ('full_log' if path == 'full' else path)
    assert recovered.state.export() == expected.export()
    if snapshot:
        assert ProjectionRebuilder().rebuild(events, snapshot=snapshot).source == 'snapshot_delta'
    await db_session.rollback()
    report = await service.rebuild(token.scope_id, actor='management')
    assert len(report) == 6 and all(row['matches_replay'] for row in report.values())
    final = reduce_events(await MemoryEventStore(db_session).replay(token.scope_id))
    for name, key in SNAPSHOT_VIEWS.items():
        assert projection_fingerprint(final[key]) == projection_fingerprint(expected[key]), name


@pytest.mark.asyncio
@pytest.mark.parametrize('damage', ['hash', 'scope', 'prefix', 'inside_group'])
async def test_nonempty_snapshot_damage_uses_full_authority(db_session, memory_writer_owner, damage):
    fixture = await prepared(db_session, memory_writer_owner, links=True)
    service, _runtime, token, *_ = fixture
    assert (await commit(fixture)).status == 'completed'
    snapshot = await MemoryHistory(service).capture(token.scope_id, force=True)
    events = await MemoryEventStore(db_session).replay(token.scope_id)
    bad = deepcopy(snapshot)
    if damage == 'hash':
        bad['state_fingerprint'] = '0' * 64
    elif damage == 'scope':
        bad['scope_id'] += 1
    elif damage == 'prefix':
        bad['source_events'][0]['payload']['content_text'] = 'wrong prefix'
    else:
        bad['source_events'] = events[:-1]
        bad['covered_through_event_id'] = events[-2]['event_id']
        state = reduce_events(events[:-1])
        bad['fingerprints'] = {name: projection_fingerprint(state[key]) for name, key in SNAPSHOT_VIEWS.items()}
        bad['state_fingerprint'] = projection_fingerprint(state)
    rebuilt = ProjectionRebuilder().rebuild(events, snapshot=bad)
    assert rebuilt.source == 'full_log'
    assert rebuilt.state.export() == reduce_events(events).export()


@pytest.mark.asyncio
async def test_rollback_new_source_version_allows_same_content_retry_and_snapshot_fallback(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, _batch, context, decisions = fixture
    result = await commit(fixture)
    assert result.status == 'completed'
    snapshot = await MemoryHistory(service).capture(token.scope_id, force=True)
    rollback = await service.govern('rollback', scope_id=token.scope_id, actor='management', reason='restore input',
                                   event_point=context.window.window_id)
    events = await MemoryEventStore(db_session).replay(token.scope_id)
    replay = ProjectionRebuilder().rebuild(events, snapshot=snapshot)
    assert replay.source == 'full_log'
    assert replay.state['entries'][context.window.input_episode_refs[0].memory_id]['state_event_id'] == rollback['event_id']
    retried = await next_fixture(fixture, db_session, same_content=True, add_source=False)
    assert retried[5].groups[0].group_key != decisions.groups[0].group_key
    again = await commit(retried)
    assert again.status == 'completed' and again.output_memory_ids != result.output_memory_ids


@pytest.mark.asyncio
async def test_retained_recovery_does_not_depend_on_audit_after_ttl(db_session, memory_writer_owner, monkeypatch):
    fixture = await prepared(db_session, memory_writer_owner, links=True)
    service, runtime, token, *_ = fixture
    original = service.projections._materialize_dense
    async def unavailable(*args, **kwargs):
        raise OSError('retain full group')
    monkeypatch.setattr(service.projections, '_materialize_dense', unavailable)
    assert (await commit(fixture)).status == 'pending'
    monkeypatch.setattr(service.projections, '_materialize_dense', original)
    from rag_mcp.models.consolidation_run import ConsolidationRunObservation
    now = datetime.now(UTC)
    db_session.add(ConsolidationRunObservation(run_id=token.run_id, observation_seq=99, knowledge_scope_id=token.scope_id,
        trigger='manual', execution_context='distiller_window', status='failed',
        created_at=now-timedelta(days=8), ttl_expires_at=now-timedelta(days=1)))
    await db_session.commit()
    assert await runtime.purge_expired_observations() == 1
    assert await runtime.release(token)
    new_token = await runtime.admit(token.scope_id, trigger='manual')
    async def forbidden_audit(*args, **kwargs):
        pytest.fail('recovery consulted expiring audit')
    monkeypatch.setattr(runtime, 'latest_observation', forbidden_audit)
    assert (await service.recover_consolidation(new_token, runtime=runtime)).status == 'completed'


@pytest.mark.asyncio
async def test_context_is_excluded_from_body_embedding_and_candidate_ranking(db_session, memory_writer_owner, monkeypatch):
    fixture = await prepared(db_session, memory_writer_owner)
    service, _runtime, token, *_ = fixture
    captured = []
    original = service.projections.embedding.embed_texts
    async def spy(texts):
        captured.extend(texts)
        return await original(texts)
    monkeypatch.setattr(service.projections.embedding, 'embed_texts', spy)
    result = await commit(fixture)
    assert result.status == 'completed'
    assert captured and all('Navigation summary' not in value for value in captured)
    events = await MemoryEventStore(db_session).replay(token.scope_id)
    full = reduce_events(events)
    bare = deepcopy(events)
    bare[-1]['payload']['approved_effect'].pop('context')
    without = reduce_events(bare)
    mid = result.output_memory_ids[0]
    for field in ('content_text', 'content_hash', 'kind', 'provenance', 'confidence', 'evidence_refs', 'inference_meta'):
        assert full['entries'][mid][field] == without['entries'][mid][field]
    from rag_mcp.services.memory_reader import memory_visible, public_entry
    now = datetime.now(UTC)
    assert memory_visible(full['entries'][mid], point=None, now=now) == memory_visible(without['entries'][mid], point=None, now=now)
    assert public_entry(full['entries'][mid]) == public_entry(without['entries'][mid])
