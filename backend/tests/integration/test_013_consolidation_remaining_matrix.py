from dataclasses import replace
from datetime import UTC
from uuid import uuid4

import pytest
from sqlalchemy import text

from rag_mcp.orchestration.consolidation_pipeline import thaw
from rag_mcp.services.memory_event_store import MemoryEventStore
from tests.integration.consolidation_commit_fixtures import commit, prepared
from tests.integration.test_013_consolidation_live_boundaries import anchored


@pytest.mark.asyncio
@pytest.mark.parametrize('ceiling,expected', [(2, 'completed'), (1, 'rejected')])
async def test_exact_create_plus_derive_ceiling_at_commit(db_session, memory_writer_owner, ceiling, expected):
    fixture = await prepared(db_session, memory_writer_owner)
    assert len(fixture[-1].groups[0].event_plan) == 2
    await db_session.execute(text("UPDATE domain_profiles SET memory_policy=jsonb_set(memory_policy,'{consolidation,max_events_per_group}',CAST(:n AS jsonb)) WHERE domain_key=(SELECT domain_key FROM knowledge_scopes WHERE scope_id=:scope)"),
        {'n': str(ceiling), 'scope': fixture[2].scope_id})
    await db_session.commit()
    outcome = await commit(fixture)
    assert outcome.status == expected
    if ceiling == 1:
        assert 'GROUP_BUDGET_EXCEEDED' in outcome.reason_codes
        assert not outcome.output_event_ids
    else:
        assert len(outcome.output_event_ids) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('component', ['eligibility_id', 'scope_id', 'run_id', 'holder_instance_id', 'writer_lease_id', 'eligibility_version'])
async def test_commit_rejects_each_mismatched_token_component(db_session, memory_writer_owner, component):
    fixture = await prepared(db_session, memory_writer_owner)
    token = fixture[2]
    value = getattr(token, component)
    forged = replace(token, **{component: value + 1 if isinstance(value, int) else uuid4()})
    outcome = await commit((*fixture[:2], forged, *fixture[3:]))
    assert outcome.status == 'rejected' and outcome.reason_codes == ('ELIGIBILITY_LOST',)
    assert not outcome.output_memory_ids
    assert await fixture[1].heartbeat(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('table,key', [('knowledge_sources', 'source_id'), ('knowledge_versions', 'version_id'), ('chunks', 'chunk_id')])
async def test_evidence_each_authoritative_scope_change_fails(db_session, memory_writer_owner, table, key):
    fixture, identifiers = await anchored(await prepared(db_session, memory_writer_owner), db_session)
    from tests.integration.consolidation_fixtures import create_scope
    other = await create_scope(db_session)
    identifier = identifiers[['source_id', 'version_id', 'chunk_id'].index(key)]
    await db_session.execute(text(f'UPDATE {table} SET knowledge_scope_id=:scope WHERE {key}=:id'), {'scope': other, 'id': identifier})
    await db_session.commit()
    outcome = await commit(fixture)
    assert outcome.status == 'rejected' and 'SCOPE_MISMATCH' in outcome.reason_codes
    assert not outcome.output_event_ids


@pytest.mark.asyncio
async def test_rejected_context_does_not_replace_existing_value(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner)
    service, runtime, token, batch, context, _ = fixture
    published = await commit(fixture)
    current = await runtime.read_snapshot(token.scope_id)
    before = thaw(current.entries[published.output_memory_ids[0]])
    await db_session.rollback()
    # A rejected follow-up cannot overwrite the published context or retain its text.
    rejected = replace(batch, proposals=[{**thaw(batch.proposals[0]), 'confidence': .1,
        'context': {'context_digest': 'REJECTED_CONTEXT_SENTINEL', 'keywords': ['not-approved']}}])
    from datetime import datetime

    from rag_mcp.services.consolidation_adjudicator import adjudicate_batch
    from rag_mcp.services.memory_policy import MemoryPolicy
    decisions = adjudicate_batch(rejected, current, MemoryPolicy.model_validate(thaw(context.window.policy)),
        current.vocabulary, {'count': current.quota_count, 'limit': 5000}, context, datetime.now(UTC))
    assert not decisions.groups
    outcome = await service.commit_approved(decisions, token, runtime=runtime, batch=rejected, context=context)
    assert not outcome.output_event_ids
    after = (await runtime.read_snapshot(token.scope_id)).entries[published.output_memory_ids[0]]
    assert thaw(after) == before
    assert 'REJECTED_CONTEXT_SENTINEL' not in str(await MemoryEventStore(db_session).replay(token.scope_id))
