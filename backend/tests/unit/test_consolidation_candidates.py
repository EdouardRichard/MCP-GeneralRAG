"""T065 (US6): candidate eligibility, per-anchor attribution and candidate version.

These are pure behavior tests for the trusted candidate surface: only an active
semantic distilled entry at or above the policy threshold whose every corpus
anchor re-verifies as a same-scope published hard citation with position and
content attribution can become a promotion candidate. Marking never changes
provenance/confidence, and a withdrawn or changed anchor makes an already
marked candidate non-promotable.
"""
import pytest

from rag_mcp.services.consolidation_adjudicator import candidate_eligibility, candidate_version
from tests.unit.consolidation_cases import (
    NOW,
    decide,
    proposal,
    rejected,
    setup,
    support_fact,
)

ATTRIBUTION = {'evidence_id': '7', 'version_id': 9, 'version': 1, 'position': 'section/1',
               'content_hash': 'a' * 64, 'source_id': 8}
CANDIDATE_VERSION = 'c' * 64


def marked(**changes):
    value = {'memory_id': 5, 'knowledge_scope_id': 1, 'kind': 'semantic', 'provenance': 'distilled',
             'status': 'active', 'confidence': .97, 'evidence_refs': ['7'],
             'candidate_version': CANDIDATE_VERSION,
             'candidate_basis': {'promote_candidate_at': NOW.isoformat(),
                                 'candidate_version': CANDIDATE_VERSION,
                                 'evidence_attributions': [ATTRIBUTION]}}
    value.update(changes)
    return value


def test_active_semantic_at_threshold_with_fully_attributed_anchor_is_promotable():
    assert candidate_eligibility(marked(), {'7': support_fact()}, scope_id=1, threshold=.95) == (True, ())


def test_threshold_boundary_is_inclusive():
    assert candidate_eligibility(marked(confidence=.95), {'7': support_fact()},
                                 scope_id=1, threshold=.95)[0] is True
    eligible, reasons = candidate_eligibility(marked(confidence=.949999), {'7': support_fact()},
                                              scope_id=1, threshold=.95)
    assert eligible is False and reasons == ('CANDIDATE_NOT_ELIGIBLE',)


@pytest.mark.parametrize('change,fact,reason', [
    ('status', None, 'CANDIDATE_NOT_ELIGIBLE'),
    ('kind', None, 'CANDIDATE_NOT_ELIGIBLE'),
    ('provenance', None, 'CANDIDATE_NOT_ELIGIBLE'),
    ('confidence', None, 'CANDIDATE_NOT_ELIGIBLE'),
    ('anchors', None, 'CANDIDATE_NOT_ELIGIBLE'),
    ('scope', None, 'SCOPE_MISMATCH'),
    ('withdrawn', None, 'EVIDENCE_UNAVAILABLE'),
    ('source_failed', None, 'EVIDENCE_UNAVAILABLE'),
    ('missing_fact', None, 'EVIDENCE_UNAVAILABLE'),
    ('position', None, 'ATTRIBUTION_FAILED'),
    ('attributed', None, 'ATTRIBUTION_FAILED'),
    ('content_hash', None, 'ATTRIBUTION_FAILED'),
    ('version_id', None, 'ATTRIBUTION_FAILED'),
])
def test_each_invalid_condition_is_refused_with_its_reason(change, fact, reason):
    entry, facts = marked(), {'7': support_fact()}
    if change == 'status':
        entry = marked(status='retired')
    elif change == 'kind':
        entry = marked(kind='procedural')
    elif change == 'provenance':
        entry = marked(provenance='hard', confidence=None)
    elif change == 'confidence':
        entry = marked(confidence=.5)
    elif change == 'anchors':
        entry = marked(evidence_refs=[])
    elif change == 'scope':
        facts = {'7': support_fact(knowledge_scope_id=2)}
    elif change == 'withdrawn':
        facts = {'7': support_fact(status='withdrawn')}
    elif change == 'source_failed':
        facts = {'7': support_fact(source_status='failed')}
    elif change == 'missing_fact':
        facts = {}
    elif change == 'position':
        facts = {'7': support_fact(position='')}
    elif change == 'attributed':
        facts = {'7': support_fact(attributed=False)}
    elif change == 'content_hash':
        facts = {'7': support_fact(content_hash='b' * 64)}
    elif change == 'version_id':
        facts = {'7': support_fact(version_id=11)}
    eligible, reasons = candidate_eligibility(entry, facts, scope_id=1, threshold=.95)
    assert eligible is False and reason in reasons


def test_candidate_version_binds_memory_content_anchors_and_approval():
    baseline = candidate_version(5, 99, 'a' * 64, [ATTRIBUTION], 'decision')
    assert baseline == candidate_version(5, 99, 'a' * 64, [ATTRIBUTION], 'decision')
    assert len(baseline) == 64
    assert baseline != candidate_version(6, 99, 'a' * 64, [ATTRIBUTION], 'decision')
    assert baseline != candidate_version(5, 100, 'a' * 64, [ATTRIBUTION], 'decision')
    assert baseline != candidate_version(5, 99, 'b' * 64, [ATTRIBUTION], 'decision')
    assert baseline != candidate_version(5, 99, 'a' * 64, [{**ATTRIBUTION, 'position': 'other'}], 'decision')
    assert baseline != candidate_version(5, 99, 'a' * 64, [ATTRIBUTION], 'other-decision')


def test_approved_marking_records_attributions_without_changing_provenance():
    p = proposal(confidence=.97, evidence_refs=['7'],
                 context={'context_digest': 'context', 'keywords': ['fact']})
    current, context = setup(p, support={'7': support_fact()})
    decision = decide(p, current, context)
    candidate = decision.children[-1]
    assert candidate.decision == 'accept'
    value = candidate.approved_effects[0]['value']
    assert value['promotion_candidate'] is True
    captured = [dict(item) for item in value['evidence_attributions']]
    assert len(captured) == 1
    assert {key: captured[0][key] for key in ATTRIBUTION} == ATTRIBUTION
    assert captured[0]['status'] == 'published' and captured[0]['source_status'] == 'published'
    created = next(effect for effect in decision.approved_effects if effect['operation'] == 'create')
    assert created['value']['provenance'] == 'distilled'
    assert created['value']['confidence'] == .97
    assert created['value']['kind'] == 'semantic'


def test_procedural_output_with_hard_anchor_is_not_a_candidate_and_stays_distilled():
    p = proposal(action='distill_procedure', kind='procedural', confidence=.99, evidence_refs=['7'])
    current, context = setup(p, support={'7': support_fact()})
    decision = decide(p, current, context)
    assert decision.children[0].decision == 'accept'
    rejected(decision.children[-1], 'CANDIDATE_NOT_ELIGIBLE')
    created = next(effect for effect in decision.approved_effects if effect['operation'] == 'create')
    assert created['value']['provenance'] == 'distilled' and created['value']['confidence'] == .99


def test_rejected_marking_is_audited_without_any_candidate_effect():
    decision = decide(proposal(confidence=1.))
    assert decision.children[0].decision == 'accept'
    rejected(decision.children[-1], 'CANDIDATE_NOT_ELIGIBLE')
    assert all('promotion_candidate' not in effect.get('value', {}) for effect in decision.approved_effects)
    assert [effect['operation'] for effect in decision.approved_effects] == ['create']


def test_anchor_withdrawal_after_marking_is_not_promotable():
    facts = {'7': support_fact(status='withdrawn')}
    assert candidate_eligibility(marked(), facts, scope_id=1, threshold=.95)[0] is False
    assert candidate_eligibility(marked(), {}, scope_id=1, threshold=.95)[1] == ('EVIDENCE_UNAVAILABLE',)
    changed_anchor = {'7': support_fact(content_hash='b' * 64)}
    assert candidate_eligibility(marked(), changed_anchor, scope_id=1, threshold=.95)[1] == ('ATTRIBUTION_FAILED',)
