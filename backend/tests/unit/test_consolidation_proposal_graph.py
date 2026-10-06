from dataclasses import replace

import pytest

from rag_mcp.config.domain_profiles import validate_memory_link_vocabulary
from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch, deterministic_proposals, thaw
from rag_mcp.services.consolidation_adjudicator import adjudicate_batch
from tests.unit.consolidation_cases import NOW, POLICY, VOCAB, facts, proposal, ref, rejected, row, setup


def batch(proposals, *, current=None, context=None, quota=None, max_events=128, vocabulary=VOCAB, deterministic=()):
    if current is None:
        current, context = setup(*proposals)
    policy = POLICY.model_copy(update={'consolidation': POLICY.consolidation.model_copy(
        update={'max_events_per_group': max_events})})
    return adjudicate_batch(ProposalBatch(tuple(proposals), tuple(deterministic)), current, policy, vocabulary,
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


def trusted_merge():
    return proposal('rule', source=row(3), action='merge_duplicate', survivor_ref=ref(row(2)),
                    duplicate_refs=[ref(row(3))], equivalence_basis='exact')


def test_model_id_collision_preserves_exact_generated_rule_groups_and_outcomes():
    current, context = setup()
    rules = deterministic_proposals(current, context=context, policy=POLICY, now=NOW)
    assert len(rules) == 1
    baseline = batch([], current=current, context=context, deterministic=rules)
    assert baseline.decisions[0].decision == 'accept'
    assert [event['operation'] for event in baseline.groups[0].event_plan] == ['merge', 'merge']
    collision = proposal(rules[0]['proposal_id'], content='model output')
    context = replace(context, inferences={collision['proposal_id']: facts(collision)})
    result = batch([collision], current=current, context=context, deterministic=rules)
    assert result.decisions[0] == baseline.decisions[0]
    assert result.groups == baseline.groups
    assert result.groups[0].source_outcomes == baseline.groups[0].source_outcomes
    rejected(result.decisions[1], 'PROPOSAL_ID_DUPLICATE')


@pytest.mark.parametrize('failure,reason', [
    ('collision', 'PROPOSAL_ID_DUPLICATE'), ('duplicate', 'PROPOSAL_ID_DUPLICATE'),
    ('missing_id', 'PROPOSAL_ID_INVALID'), ('null_id', 'PROPOSAL_ID_INVALID'),
    ('list_id', 'PROPOSAL_ID_INVALID'), ('illegal_id', 'PROPOSAL_ID_INVALID'),
    ('non_object', 'PROPOSAL_INVALID'), ('missing_merge_field', 'PROPOSAL_INVALID'),
    ('unknown_action', 'ACTION_NOT_ALLOWED'),
])
def test_invalid_model_packet_preserves_exact_rule_consumption(failure, reason):
    rule = trusted_merge()
    current, context = setup(rule)
    baseline = batch([], current=current, context=context, deterministic=[rule])
    assert baseline.decisions[0].decision == 'accept'
    assert thaw(baseline.groups[0].source_outcomes) == [
        {'source_version': ref(row(3)), 'outcome': 'consumed_on_complete'}]
    invalid = proposal('model')
    models = [invalid]
    if failure == 'collision':
        invalid['proposal_id'] = 'rule'
    elif failure == 'duplicate':
        models.append(proposal('model', content='second'))
    elif failure == 'missing_id':
        del invalid['proposal_id']
    elif failure == 'null_id':
        invalid['proposal_id'] = None
    elif failure == 'list_id':
        invalid['proposal_id'] = ['model']
    elif failure == 'illegal_id':
        invalid['proposal_id'] = 'Not a legal ID'
    elif failure == 'non_object':
        models = [None]
    elif failure == 'missing_merge_field':
        invalid.update(action='merge_duplicate', survivor_ref=ref(row(2)))
    elif failure == 'unknown_action':
        invalid['action'] = 'not_an_action'
    result = batch(models, current=current, context=context, deterministic=[rule])
    assert result.decisions[0] == baseline.decisions[0]
    assert result.groups == baseline.groups
    for decision in result.decisions[1:]:
        rejected(decision, reason)


def test_model_packet_id_fault_drops_all_model_work_without_harming_rule():
    rule = trusted_merge()
    good, collision = proposal('model'), proposal('rule', content='colliding')
    current, context = setup(rule, good, collision)
    baseline = batch([], current=current, context=context, deterministic=[rule])
    result = batch([good, collision], current=current, context=context, deterministic=[rule])
    assert result.groups == baseline.groups
    assert result.decisions[0] == baseline.decisions[0]
    for decision in result.decisions[1:]:
        rejected(decision, 'PROPOSAL_ID_DUPLICATE')


def test_valid_model_topology_and_origin_survive_alongside_trusted_rule():
    rule = trusted_merge()
    models = [linked('b', 'a'), proposal('a')]
    current, context = setup(rule, *models)
    baseline = batch([], current=current, context=context, deterministic=[rule])
    result = batch(models, current=current, context=context, deterministic=[rule])
    assert result.decisions[0] == baseline.decisions[0]
    assert baseline.groups[0] in result.groups
    assert all(decision.decision == 'accept' for decision in result.decisions)
    assert result.decisions[0].proof['origin'] == 'deterministic_rule'
    assert all(decision.proof['origin'] == 'llm_self' for decision in result.decisions[1:])
    model_group = next(group for group in result.groups if group != baseline.groups[0])
    assert [event['operation'] for event in model_group.event_plan] == ['create', 'create', 'derive']


def test_model_proposal_ref_cannot_resolve_in_trusted_rule_namespace():
    rule, model = trusted_merge(), linked('model', 'rule')
    current, context = setup(rule, model)
    baseline = batch([], current=current, context=context, deterministic=[rule])
    result = batch([model], current=current, context=context, deterministic=[rule])
    assert result.groups == baseline.groups
    assert result.decisions[0] == baseline.decisions[0]
    rejected(result.decisions[1], 'PROPOSAL_REF_UNKNOWN')


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


@pytest.mark.parametrize('side', ['from', 'to'])
@pytest.mark.parametrize('action,kind,want', [('extract_fact', 'semantic', 'accept'),
                                           ('distill_procedure', 'procedural', 'reject')])
def test_provisional_link_vocabulary_uses_approved_output_kind(side, action, kind, want):
    creator = proposal('a', action=action, kind=kind)
    attachment = {'from_ref': {'proposal_ref': 'a'} if side == 'from' else ref(row(3)),
                  'to_ref': {'proposal_ref': 'a'} if side == 'to' else ref(row(3)),
                  'relation_type': 'related', 'confidence': .8, 'description': 'output relation'}
    dependent = proposal('b', source=row(2), content='other fact', link_suggestions=[attachment])
    vocabulary = validate_memory_link_vocabulary([{**VOCAB[0],
        'from_kinds': ['semantic'] if side == 'from' else ['episodic'],
        'to_kinds': ['semantic'] if side == 'to' else ['episodic']}])
    result = batch([dependent, creator], vocabulary=vocabulary)
    assert result.decisions[0].children[0].decision == result.decisions[1].children[0].decision == 'accept'
    if want == 'accept':
        assert result.decisions[0].children[1].decision == 'accept'
        assert [event['operation'] for event in result.groups[0].event_plan] == ['create', 'create', 'derive']
    else:
        rejected(result.decisions[0].children[1], 'LINK_KIND_NOT_ALLOWED')
        assert [event['operation'] for event in result.groups[0].event_plan] == ['create', 'create']


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


def test_rejected_batch_keys_distinguish_contents_and_preserve_retry_relabel():
    proposals = [proposal('a', confidence=.1, content='first'), proposal('b', confidence=.1, content='second')]
    original = batch(proposals)
    assert len({decision.decision_id for decision in original.decisions}) == 2
    renamed = [{**proposals[1], 'proposal_id': 'renamed_b', 'run_id': 'new', 'request_id': 'new'},
               {**proposals[0], 'proposal_id': 'renamed_a'}]
    repeated = batch(renamed)
    assert {decision.decision_id for decision in repeated.decisions} == {
        decision.decision_id for decision in original.decisions}
    assert original.groups == repeated.groups == ()


def test_rejected_output_dependency_keys_are_stable_after_graph_relabel():
    original = [proposal('a', confidence=.1, content='creator'), linked('b', 'a', source=2)]
    renamed = [linked('renamed_b', 'renamed_a', source=2), proposal('renamed_a', confidence=.1, content='creator')]
    renamed[0]['content'] = 'b'
    a, b = batch(original), batch(renamed)
    rejected(a.decisions[1], 'OUTPUT_NOT_APPROVED')
    assert a.decisions[0].decision_id != a.decisions[1].decision_id
    assert {decision.decision_id for decision in a.decisions} == {decision.decision_id for decision in b.decisions}


def test_cycle_rejection_keys_bind_distinct_contents_and_canonical_topology():
    original = [linked('a', 'b'), linked('b', 'a')]
    renamed = [linked('renamed_b', 'renamed_a'), linked('renamed_a', 'renamed_b')]
    renamed[0]['content'], renamed[1]['content'] = 'b', 'a'
    a, b = batch(original), batch(renamed)
    for decision in a.decisions:
        rejected(decision, 'PROPOSAL_REF_CYCLE')
    assert len({decision.decision_id for decision in a.decisions}) == 2
    assert {decision.decision_id for decision in a.decisions} == {decision.decision_id for decision in b.decisions}


def test_invalid_model_packet_rejection_keys_do_not_collapse_distinct_members():
    rule = trusted_merge()
    models = [proposal('duplicate', content='first'), proposal('duplicate', content='second')]
    current, context = setup(rule)
    result = batch(models, current=current, context=context, deterministic=[rule])
    for decision in result.decisions[1:]:
        rejected(decision, 'PROPOSAL_ID_DUPLICATE')
    assert result.decisions[1].decision_id != result.decisions[2].decision_id
    assert batch(models, current=current, context=context, deterministic=[rule]) == result


def test_identical_rejected_members_have_separate_stable_audit_occurrences():
    proposals = [proposal('a', confidence=.1), proposal('b', confidence=.1)]
    result = batch(proposals)
    assert len({decision.decision_id for decision in result.decisions}) == 2
    renamed = batch([{**proposals[1], 'proposal_id': 'x'}, {**proposals[0], 'proposal_id': 'y'}])
    assert {decision.decision_id for decision in result.decisions} == {
        decision.decision_id for decision in renamed.decisions}
    assert result.groups == renamed.groups == ()


@pytest.mark.parametrize('change', [
    {'action': []}, {'action': {'not': 'an action'}}, {'source_refs': None}, {'source_refs': [None]},
    {'link_suggestions': [{'from_ref': ref(row(2))}]},
    {'link_suggestions': [{'from_ref': {'proposal_ref': ['bad']}, 'to_ref': ref(row(2)),
                          'relation_type': 'related', 'confidence': .8, 'description': 'invalid label'}]},
])
def test_nested_malformed_model_output_cannot_stop_deterministic_work(change):
    rule, model = trusted_merge(), proposal('model', **change)
    current, context = setup(rule)
    baseline = batch([], current=current, context=context, deterministic=[rule])
    result = batch([model], current=current, context=context, deterministic=[rule])
    assert result.decisions[0] == baseline.decisions[0]
    assert result.groups == baseline.groups
    rejected(result.decisions[1], 'PROPOSAL_INVALID')


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
