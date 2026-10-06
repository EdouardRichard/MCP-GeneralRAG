from dataclasses import replace

import pytest

from rag_mcp.services.consolidation_adjudicator import _governed_command, guard_effect
from tests.unit.consolidation_cases import NOW, decide, proposal, ref, rejected, row, setup, support_fact

EFFECTS = ('replace', 'invalidate', 'merge', 'shorten_validity', 'downgrade', 'propagate')


def hard_target():
    return row(2, kind='semantic', provenance='hard', confidence=None, evidence_refs=['7'],
               authority={'source': 'validated_evidence'},
               provenance_meta={'provenance': 'hard', 'validated': True, 'attributions': [support_fact()]})


def command_event(path, target):
    manual = path == 'manual'
    return {'event_id': 40, 'aggregate_id': target['memory_id'] if manual else 41,
            'knowledge_scope_id': 1, 'event_type': 'retract' if manual else 'revise',
            'actor': 'management' if manual else 'memory_tool', 'request_id': 'governed-request',
            'authority': {'source': 'management' if manual else 'validated_evidence'},
            'scope_meta': {'knowledge_scope_id': 1}, 'occurred_at': NOW.isoformat(),
            'payload': {'reason': 'explicit retirement'} if manual else {
                'provenance': 'hard', 'confidence': None, 'evidence_refs': ['7'],
                'supersedes_memory_id': target['memory_id']}}


def trusted_command(event, *, target, validation=None):
    # Use the existing governed modules' private post-authorization adapters.
    if event['actor'] == 'management':
        from rag_mcp.services.memory_governance import _management_effect_command
        return _management_effect_command(event, target)
    from rag_mcp.services.memory_service import _hard_replacement_command
    return _hard_replacement_command(event, target, validation)


@pytest.mark.parametrize('effect', EFFECTS)
@pytest.mark.parametrize('path', ['soft', 'raw_hard', 'manual_claim'])
def test_all_hard_effects_reject_untrusted_three_paths(effect, path):
    target = hard_target()
    claim = None if path == 'soft' else ({'evidence_refs': ['7'], 'provenance': 'hard'}
            if path == 'raw_hard' else {'actor': 'management', 'authority': {'source': 'management'},
                                      'reason': 'retire', 'proof': 'approved'})
    d = guard_effect({'operation': effect, 'aggregate_id': 2}, target, command=claim)
    rejected(d, 'HARD_MEMORY_PROTECTED')
    assert target['confidence'] is None


@pytest.mark.parametrize('effect', EFFECTS)
def test_soft_target_counterpart_accepts_effect_guard(effect):
    assert guard_effect({'operation': effect, 'aggregate_id': 2}, row(2)).decision == 'accept'


@pytest.mark.parametrize('path,allowed', [('hard', 'replace'), ('manual', 'invalidate')])
@pytest.mark.parametrize('effect', EFFECTS)
def test_governed_commands_authorize_only_exact_existing_command_effect(path, allowed, effect):
    target = hard_target()
    event = command_event(path, target)
    validation = {'provenance': 'hard', 'validated': True, 'attributions': [
        {'evidence_id': '7', **support_fact()}]}
    command = trusted_command(event, target=target, validation=validation)
    d = guard_effect({'operation': effect, 'aggregate_id': 2,
                      **({'replacement_id': 41} if effect == 'replace' else {})}, target, command=command)
    if effect == allowed:
        assert d.decision == 'accept'
    else:
        rejected(d, 'HARD_MEMORY_PROTECTED')


@pytest.mark.parametrize('change', [{'memory_id': 3}, {'state_event_id': 19}, {'knowledge_scope_id': 2},
                                     {'content_hash': 'f' * 64}])
def test_governed_capability_is_bound_to_object_scope_and_version(change):
    target = hard_target()
    command = trusted_command(command_event('manual', target), target=target)
    rejected(guard_effect({'operation': 'invalidate', 'aggregate_id': 2}, {**target, **change},
                          command=command), 'HARD_MEMORY_PROTECTED')


def test_hard_replacement_requires_attributions_and_exact_replacement():
    target = hard_target()
    with pytest.raises(PermissionError):
        trusted_command(command_event('hard', target), target=target, validation={'validated': True})
    command = trusted_command(command_event('hard', target), target=target,
        validation={'provenance': 'hard', 'validated': True,
                    'attributions': [{'evidence_id': '7', **support_fact()}]})
    rejected(guard_effect({'operation': 'replace', 'aggregate_id': 2, 'replacement_id': 42}, target,
                          command=command), 'HARD_MEMORY_PROTECTED')


def test_hard_anchor_produces_distilled_and_does_not_promote_authority():
    source = row(1, provenance='hard', confidence=None, evidence_refs=['7'],
                 provenance_meta={'validated': True, 'attributions': [{'evidence_id': '7', **support_fact()}]})
    p = proposal(source=source, evidence_refs=['7'])
    c, ctx = setup(p, entries={1: source}, support={'7': support_fact()})
    d = decide(p, c, ctx)
    assert d.decision == 'accept'
    assert d.approved_effects[0]['value']['provenance'] == 'distilled'
    assert c.entries[1]['confidence'] is None
    rejected(decide({**p, 'provenance': 'hard'}, c, ctx), 'AUTHORITY_FIELDS_FORBIDDEN')


@pytest.mark.parametrize('change,reason', [({'status': 'withdrawn'}, 'EVIDENCE_UNAVAILABLE'),
    ({'knowledge_scope_id': 2}, 'SCOPE_MISMATCH'), ({'version_id': 10}, 'TARGET_VERSION_CHANGED'),
    ({'attributed': False}, 'ATTRIBUTION_FAILED')])
def test_hard_source_rechecks_its_evidence_when_proposal_has_no_corpus_anchor(change, reason):
    source = row(1, provenance='hard', confidence=None, evidence_refs=['7'],
                 provenance_meta={'validated': True, 'attributions': [{'evidence_id': '7', **support_fact()}]})
    p = proposal(source=source)
    current, context = setup(p, entries={1: source}, support={'7': support_fact()})
    assert decide(p, current, context).children[0].decision == 'accept'
    rejected(decide(p, current, replace(context, support_facts={'7': support_fact(**change)})), reason)


def test_hard_source_cannot_omit_its_authoritative_evidence_or_original_attribution():
    source = row(1, provenance='hard', confidence=None, evidence_refs=['7'],
                 provenance_meta={'validated': True, 'attributions': [{'evidence_id': '7', **support_fact()}]})
    p = proposal(source=source)
    current, context = setup(p, entries={1: source}, support={'7': support_fact()})
    for change in [{'evidence_refs': []}, {'provenance_meta': {}}]:
        rejected(decide(p, replace(current, entries={1: {**source, **change}}), context), 'ATTRIBUTION_FAILED')


def test_merge_checks_real_hard_provenance_even_without_hard_flag():
    target = hard_target()
    p = proposal(action='merge_duplicate', survivor_ref=ref(row(3)), duplicate_refs=[ref(target)],
                 equivalence_basis='equal')
    c, ctx = setup(p, entries={1: row(1), 2: target, 3: row(3)})
    rejected(decide(p, c, ctx), 'HARD_MEMORY_PROTECTED')


def test_model_rule_proof_and_origin_never_establish_authority():
    p = proposal(origin='deterministic_rule', proof={'approved': True}, rule_id='trusted')
    rejected(decide(p), 'AUTHORITY_FIELDS_FORBIDDEN')


def test_maintenance_context_cannot_be_forged():
    from rag_mcp.services.consolidation_adjudicator import AdjudicationContext
    with pytest.raises(PermissionError):
        AdjudicationContext(execution_context='deterministic_propagation',
                            historical_source_refs=({'memory_id': 1},), propagation_trigger={'withdrawn': 7})


@pytest.mark.parametrize('path', ['hard', 'manual'])
def test_raw_event_and_complete_validation_json_cannot_mint_governed_capability(path):
    with pytest.raises(PermissionError):
        _governed_command(command_event(path, hard_target()), target=hard_target(),
            validation={'provenance': 'hard', 'validated': True,
                        'attributions': [{'evidence_id': '7', **support_fact()}]})
