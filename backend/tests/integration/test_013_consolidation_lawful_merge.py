from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch, deterministic_proposals, thaw
from rag_mcp.services.consolidation_adjudicator import AdjudicationContext, adjudicate_batch
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_policy import MemoryPolicy
from tests.integration.consolidation_commit_fixtures import commit, prepared
from tests.integration.consolidation_fixtures import recorded_episode
from tests.integration.test_013_consolidation_operation_matrix import assert_each_prefix
from tests.unit.consolidation_cases import facts


@pytest.mark.asyncio
async def test_lawful_normalized_merge_uses_approved_history_and_keeps_unrelated_episode(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner, count=2, shared=True)
    service, runtime, token, batch, context, _ = fixture
    proposals = thaw(batch.proposals)
    for proposal, body in zip(proposals, ('alpha\r\nbeta', 'alpha\nbeta'), strict=True):
        proposal['content'] = body
        proposal.pop('context')
    batch = ProposalBatch(proposals)
    context = replace(context, inferences={p['proposal_id']: facts(p) for p in proposals})
    current = await runtime.read_snapshot(token.scope_id)
    policy = MemoryPolicy.model_validate(thaw(context.window.policy))
    decisions = adjudicate_batch(batch, current, policy, current.vocabulary,
        {'count': current.quota_count, 'limit': 5000}, context, datetime.now(UTC))
    assert len(decisions.groups) == 1
    assert len(decisions.groups[0].event_plan) == 2
    await db_session.rollback()
    created = await commit((service, runtime, token, batch, context, decisions))
    assert created.status == 'completed' and len(created.output_memory_ids) == 2
    assert await runtime.release(token)

    latest = await runtime.read_snapshot(token.scope_id)
    before = {mid: thaw(latest.entries[mid]) for mid in created.output_memory_ids}
    assert {entry['content_text'] for entry in before.values()} == {'alpha\r\nbeta', 'alpha\nbeta'}
    for entry in before.values():
        assert entry['content_hash'] == sha256(entry['content_text'].encode()).hexdigest()
        assert entry['source_lineage']
    history = await MemoryEventStore(db_session).replay(token.scope_id)
    outputs = [e for e in history if e['event_id'] in created.output_event_ids]
    assert all(e['payload']['adjudication']['decision'] == 'accept' for e in outputs)
    assert all(e['payload']['adjudication']['proofs'] for e in outputs)
    await db_session.rollback()

    unrelated = await recorded_episode(service, token.scope_id, 'Unrelated new episode enabling the next window')
    token = await runtime.admit(token.scope_id, trigger='manual')
    window = await runtime.select_and_seal(token)
    current = await runtime.read_snapshot(token.scope_id)
    assert unrelated['memory_id'] in {ref.memory_id for ref in window.input_episode_refs}
    assert set(created.output_memory_ids) <= {ref.memory_id for ref in window.reference_refs}
    context = AdjudicationContext(window=window)
    now = datetime.now(UTC)
    proposals = deterministic_proposals(current, context=context, policy=policy, now=now)
    assert len(proposals) == 1 and proposals[0]['action'] == 'merge_duplicate'
    batch = ProposalBatch([], deterministic_proposals=proposals)
    decisions = adjudicate_batch(batch, current, policy, current.vocabulary,
        {'count': current.quota_count, 'limit': 5000}, context, now)
    assert decisions.groups and all(d.decision == 'accept' for d in decisions.decisions)
    await db_session.rollback()
    merged = await commit((service, runtime, token, batch, context, decisions))
    assert merged.status == 'completed' and not merged.output_memory_ids
    assert len(merged.output_event_ids) == 1
    latest = await runtime.read_snapshot(token.scope_id)
    assert sorted(latest.entries[mid]['status'] for mid in created.output_memory_ids) == ['active', 'retired']
    for mid, entry in before.items():
        after = thaw(latest.entries[mid])
        assert after['source_event_id'] == entry['source_event_id']
        assert after['content_text'] == entry['content_text']
        assert after['content_hash'] == entry['content_hash']
        assert after['source_lineage'] == entry['source_lineage']
    assert latest.entries[unrelated['memory_id']]['status'] == 'active'
    assert all(outcome['source_version'][0] != unrelated['memory_id']
        for outcome in latest.consolidation_state['potential_source_outcomes'].values())
    await assert_each_prefix(db_session, token.scope_id)
