import json
from datetime import UTC, datetime

import pytest

from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch, thaw
from rag_mcp.services.consolidation_adjudicator import adjudicate_batch
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_policy import MemoryPolicy
from tests.integration.consolidation_commit_fixtures import commit, prepared


async def approved_fixture(session, owner, *, attachment_only=False):
    fixture = await prepared(session, owner, count=2, shared=False, links=True)
    service, runtime, token, batch, context, _ = fixture
    proposals = thaw(batch.proposals)
    if attachment_only:
        proposals = proposals[:1]
        proposals[0]['confidence'] = .1
        proposals[0]['content'] = 'REJECTED_CORE_MUST_NOT_BE_PERMANENT'
        proposals[0]['link_suggestions'][0]['from_ref'] = proposals[0]['source_refs'][0]
    else:
        proposals[1]['link_suggestions'][0]['to_ref'] = {'proposal_ref': 'p0'}
    batch = ProposalBatch(proposals)
    current = await runtime.read_snapshot(token.scope_id)
    decisions = adjudicate_batch(batch, current, MemoryPolicy.model_validate(thaw(context.window.policy)), current.vocabulary,
        {'count': current.quota_count, 'limit': 5000}, context, datetime.now(UTC))
    assert decisions.groups
    if attachment_only:
        assert decisions.decisions[0].children[0].decision == 'reject'
        assert all(e['operation'] == 'derive' for e in decisions.groups[0].event_plan)
    await session.rollback()
    return service, runtime, token, batch, context, decisions


@pytest.mark.asyncio
@pytest.mark.parametrize('attachment_only', [False, True])
async def test_permanent_recovery_has_concrete_refs_and_only_approved_values(db_session, memory_writer_owner, monkeypatch, attachment_only):
    fixture = await approved_fixture(db_session, memory_writer_owner, attachment_only=attachment_only)
    service, runtime, token, *_ = fixture
    original = service.projections._materialize_dense
    async def unavailable(*args, **kwargs):
        raise OSError('external pending for permanent recovery')
    monkeypatch.setattr(service.projections, '_materialize_dense', unavailable)
    result = await commit(fixture)
    assert result.status == 'pending' and not result.output_event_ids
    history = await MemoryEventStore(db_session).replay(token.scope_id)
    payloads = [event['payload'] for event in history if event['event_type'] == 'consolidate']
    serialized = json.dumps(payloads)
    assert 'REJECTED_CORE_MUST_NOT_BE_PERMANENT' not in serialized
    assert '"proposal_ref"' not in serialized and '"local"' not in serialized and '"output_key"' not in serialized
    await db_session.rollback()
    monkeypatch.setattr(service.projections, '_materialize_dense', original)
    assert await runtime.release(token)
    fresh = await runtime.admit(token.scope_id, trigger='manual')
    recovered = await service.recover_consolidation(fresh, runtime=runtime)
    assert recovered.status == 'completed'
    assert await MemoryEventStore(db_session).replay(token.scope_id) == history
    if attachment_only:
        assert not recovered.output_memory_ids
        assert not (await runtime.read_snapshot(token.scope_id)).consolidation_state['potential_source_outcomes']
