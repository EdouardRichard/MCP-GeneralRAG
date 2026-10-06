from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import DBAPIError

from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch, run_pipeline, thaw
from rag_mcp.services.consolidation_adjudicator import adjudicate_batch
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_policy import MemoryPolicy
from tests.integration.consolidation_commit_fixtures import commit, prepared


@pytest.mark.asyncio
async def test_same_description_rejected_link_is_not_persisted(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner, links=True)
    service, runtime, token, batch, context, _ = fixture
    proposals = thaw(batch.proposals)
    accepted = proposals[0]['link_suggestions'][0]
    rejected = {**accepted, 'to_ref': {**accepted['to_ref'], 'state_event_id': 1}}
    proposals[0]['link_suggestions'].append(rejected)
    batch = ProposalBatch(proposals)
    current = await runtime.read_snapshot(token.scope_id)
    decisions = adjudicate_batch(batch, current, MemoryPolicy.model_validate(thaw(context.window.policy)), current.vocabulary,
        {'count': current.quota_count, 'limit': 5000}, context, datetime.now(UTC))
    assert decisions.decisions[0].children[2].reason_codes == ('TARGET_VERSION_CHANGED',)
    await db_session.rollback()
    assert (await commit((service, runtime, token, batch, context, decisions))).status == 'completed'
    events = [e for e in await MemoryEventStore(db_session).replay(token.scope_id) if e['event_type'] == 'consolidate']
    for event in events:
        recovery = event['payload']['adjudication']['proofs'][-1]['recovery']
        assert len(recovery['proposals'][0]['link_suggestions']) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('count', [2, 3])
async def test_partial_relational_failure_observation_preserves_published_prefix(db_session, memory_writer_owner, monkeypatch, count):
    fixture = await prepared(db_session, memory_writer_owner, count=count, shared=False)
    service, runtime, token, batch, context, _ = fixture
    async def selector(token):
        return context.window
    async def proposer(*args, **kwargs):
        return batch
    original = service.projections._materialize_links
    calls = 0
    async def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise DBAPIError('injected link SQL', {}, RuntimeError('second group relation failed'), False)
        return await original(*args, **kwargs)
    monkeypatch.setattr(service.projections, '_materialize_links', fail)
    outcome = await run_pipeline(runtime, token, distiller=None, select=selector, propose_stage=proposer)
    observation = await runtime.latest_observation(token.run_id)
    assert outcome.status == 'rolled_back' and len(outcome.output_memory_ids) == 1
    assert observation.status == 'partial'
    assert len(outcome.failed_result_keys) == 1 and calls == 2
    assert sorted(d['publication'] for d in observation.adjudications) == sorted(
        ['committed', 'failed'] + ['not_committed'] * (count - 2))
