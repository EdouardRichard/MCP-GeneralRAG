from dataclasses import replace

import pytest

from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch
from rag_mcp.services.consolidation_adjudicator import adjudicate_batch
from tests.unit.consolidation_cases import NOW, POLICY, VOCAB, proposal, ref, rejected, row, setup


def batch(proposals, *, current=None, context=None, quota=None, max_events=128):
    if current is None:
        current, context = setup(*proposals)
    policy = POLICY.model_copy(update={'consolidation': POLICY.consolidation.model_copy(
        update={'max_events_per_group': max_events})})
    return adjudicate_batch(ProposalBatch(tuple(proposals)), current, policy, VOCAB,
                            quota or {'count': 0, 'limit': 5000}, context, NOW)


def linked(identifier, dependency, *, source=1):
    return proposal(identifier, source=row(source), content=identifier, link_suggestions=[{
        'from_ref': {'local': 'output'}, 'to_ref': {'proposal_ref': dependency},
        'relation_type': 'related', 'confidence': .8, 'description': 'related'}])


def test_unique_proposal_ids_required():
    result = batch([proposal(), proposal(content='different')])
    assert len(result.decisions) == 2
    for d in result.decisions:
        rejected(d, 'PROPOSAL_ID_DUPLICATE')
    assert result.groups == ()


@pytest.mark.parametrize('proposals,reason', [([linked('p0', 'absent')], 'PROPOSAL_REF_UNKNOWN'),
    ([linked('p0', 'p0')], 'PROPOSAL_REF_SELF'),
    ([linked('p0', 'p1'), linked('p1', 'p0')], 'PROPOSAL_REF_CYCLE')])
def test_distinct_unknown_self_and_cycle_references(proposals, reason):
    result = batch(proposals)
    for d in result.decisions:
        rejected(d, reason)
    assert result.groups == ()


def test_forward_reference_topology_uses_approved_output():
    result = batch([linked('p1', 'p0', source=2), proposal('p0')])
    assert all(d.decision == 'accept' for d in result.decisions)
    assert len(result.groups) == 1
    assert [e['operation'] for e in result.groups[0].event_plan] == ['create', 'create', 'derive']
    assert result.groups[0].event_plan[-1]['value']['links'][0]['to_ref']['output_key']


@pytest.mark.parametrize('creator', [proposal('p0', confidence=.1),
    proposal('p0', action='merge_duplicate', survivor_ref=ref(row(2)), duplicate_refs=[ref(row(3))],
             equivalence_basis='exact')])
def test_rejected_and_noncreating_outputs_cannot_be_referenced(creator):
    result = batch([creator, linked('p1', 'p0')])
    rejected(result.decisions[1], 'OUTPUT_NOT_APPROVED')


def test_transitive_source_overlap_and_output_edges_form_single_atomic_group():
    proposals = [proposal('a'), proposal('b', content='other'), linked('c', 'b', source=2),
                 proposal('d', source=row(3), content='independent')]
    result = batch(proposals)
    assert sorted(len(g.decision_ids) for g in result.groups) == [1, 3]
    assert sum(len(g.event_plan) for g in result.groups) == 5


@pytest.mark.parametrize('count,want', [(128, 'accept'), (129, 'reject')])
def test_exact_event_plan_128_129_includes_create_and_derive(count, want):
    # 127 creates + one independently lowered derive = 128, then one more derive = 129.
    proposals = [proposal(f'p{i}', content=f'fact {i}') for i in range(127)]
    for i in range(count - 127):
        proposals[i]['context'] = {'context_digest': 'context', 'keywords': []}
    result = batch(proposals)
    if want == 'accept':
        assert len(result.groups) == 1
        assert len(result.groups[0].event_plan) == 128
        assert sum(e['operation'] == 'create' for e in result.groups[0].event_plan) == 127
        assert sum(e['operation'] == 'derive' for e in result.groups[0].event_plan) == 1
    else:
        assert result.groups == ()
        for d in result.decisions:
            rejected(d, 'GROUP_BUDGET_EXCEEDED')


def test_configured_event_ceiling_rejects_whole_group_without_reservation_leak():
    proposals = [proposal('a', content='one'), proposal('b', content='two'),
                 proposal('c', source=row(2), content='three')]
    result = batch(proposals, quota={'count': 0, 'limit': 2}, max_events=1)
    rejected(result.decisions[0], 'GROUP_BUDGET_EXCEEDED')
    rejected(result.decisions[1], 'GROUP_BUDGET_EXCEEDED')
    assert result.decisions[2].decision == 'accept'
    assert len(result.groups) == 1


def test_cumulative_quota_and_atomic_group_rejection():
    a, b = proposal('a', content='a'), proposal('b', source=row(2), content='b')
    result = batch([a, b], quota={'count': 4, 'limit': 5})
    assert sorted(d.decision for d in result.decisions) == ['accept', 'reject']
    rejected(next(d for d in result.decisions if d.decision == 'reject'), 'QUOTA_EXCEEDED')
    b['source_refs'] = a['source_refs']
    result = batch([a, b], quota={'count': 4, 'limit': 5})
    for d in result.decisions:
        rejected(d, 'QUOTA_EXCEEDED')


def test_lifecycle_does_not_free_uncommitted_quota():
    merge = proposal('a', action='merge_duplicate', survivor_ref=ref(row(2)),
                     duplicate_refs=[ref(row(3))], equivalence_basis='equal')
    result = batch([merge, proposal('b')], quota={'count': 5, 'limit': 5})
    rejected(result.decisions[1], 'QUOTA_EXCEEDED')


def test_keys_ignore_labels_order_run_and_request_identity():
    first = [proposal('a'), linked('b', 'a', source=2)]
    second = [linked('renamed_b', 'renamed_a', source=2), proposal('renamed_a')]
    second[0]['content'] = 'b'
    a, b = batch(first), batch(second)
    assert a.groups[0].group_key == b.groups[0].group_key
    assert {d.decision_id for d in a.decisions} == {d.decision_id for d in b.decisions}
    c, ctx = setup(*first)
    c = replace(c, consolidation_state={'run_id': 'another', 'request_id': 'another'})
    assert batch(first, current=c, context=ctx).groups == a.groups


def test_rejected_attachments_never_enter_event_plan():
    p = proposal(context={'context_digest': 'x' * 513, 'keywords': []})
    result = batch([p])
    assert [e['operation'] for e in result.groups[0].event_plan] == ['create']


def test_invalid_confidence_in_batch_is_a_decision_not_json_serialization_crash():
    result = batch([proposal(confidence=float('nan'))])
    rejected(result.decisions[0], 'CONFIDENCE_INVALID')


def test_different_attachments_share_one_derive_event_on_same_aggregate():
    p = linked('b', 'a', source=2)
    p['context'] = {'context_digest': 'context', 'keywords': []}
    result = batch([proposal('a'), p])
    assert len(result.groups[0].event_plan) == 3
    assert set(result.groups[0].event_plan[-1]['value']) == {'links', 'context'}


def test_disjoint_proposal_shuffle_keeps_stable_group_keys():
    proposals = [proposal('a', content='a'), proposal('b', source=row(2), content='b')]
    assert batch(proposals).groups == batch(list(reversed(proposals))).groups


def test_changed_target_version_changes_decision_key():
    p = proposal(action='merge_duplicate', survivor_ref=ref(row(2)), duplicate_refs=[ref(row(3))],
                 equivalence_basis='equal')
    first = batch([p])
    c, ctx = setup(p, entries={1: row(1), 2: row(2, state_event_id=20), 3: row(3)})
    p['survivor_ref']['state_event_id'] = 20
    second = batch([p], current=c, context=ctx)
    assert first.decisions[0].decision == second.decisions[0].decision == 'accept'
    assert first.decisions[0].decision_id != second.decisions[0].decision_id
    assert first.groups[0].group_key != second.groups[0].group_key


def test_identical_creates_cannot_plan_two_events_for_one_new_identity():
    result = batch([proposal('a'), proposal('b')])
    assert sum(e['operation'] == 'create' for g in result.groups for e in g.event_plan) == 1
    assert sorted(d.decision for d in result.decisions) == ['accept', 'reject']
    rejected(next(d for d in result.decisions if d.decision == 'reject'), 'OUTPUT_DUPLICATE')


def test_closed_output_in_provisional_snapshot_is_not_a_live_link_endpoint():
    # Both creates have equal values but different source versions, hence distinct identities.
    a = proposal('a')
    b = proposal('b', source=row(2))
    c = proposal('c', link_suggestions=[{'from_ref': {'proposal_ref': 'b'}, 'to_ref': {'proposal_ref': 'a'},
        'relation_type': 'related', 'confidence': .8, 'description': 'still active?'}])
    first = batch([a, b])
    from rag_mcp.services.consolidation_adjudicator import adjudicate
    created = first.decisions[1].approved_effects[0]
    output_key = created['aggregate_id']['output_key']
    current, context = setup(c)
    context = replace(context, provisional={output_key: {**created['value'], 'memory_id': created['aggregate_id'],
                      'output_key': output_key, 'status': 'retired', 'write_status': 'complete'}})
    c['link_suggestions'] = [{'from_ref': {'output_key': output_key}, 'to_ref': ref(row(2)),
        'relation_type': 'related', 'confidence': .8, 'description': 'closed output'}]
    d = adjudicate(c, current, POLICY, VOCAB, {'count': 0, 'limit': 5000}, context, NOW)
    rejected(d.children[1], 'SOURCE_NOT_ELIGIBLE')


def test_event_plan_carries_contiguous_indexes_and_proposal_keys_for_commit():
    result = batch([proposal('a'), linked('b', 'a', source=2)])
    plan = result.groups[0].event_plan
    assert [e['effect_index'] for e in plan] == [0, 1, 2]
    assert {e['effect_count'] for e in plan} == {3}
    assert {e['proposal_key'] for e in plan} == {d.decision_id for d in result.decisions}


def test_double_lifecycle_mutation_is_rejected_before_event_plan():
    first = proposal('a', action='merge_duplicate', survivor_ref=ref(row(2)),
                     duplicate_refs=[ref(row(3))], equivalence_basis='equal')
    second = {**first, 'proposal_id': 'b', 'justification': 'second proposed exit'}
    result = batch([first, second])
    assert result.groups == ()
    for d in result.decisions:
        rejected(d, 'EFFECT_CONFLICT')
