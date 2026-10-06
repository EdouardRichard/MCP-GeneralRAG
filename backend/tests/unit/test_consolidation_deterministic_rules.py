from dataclasses import replace
from datetime import timedelta

import pytest

from rag_mcp.orchestration.consolidation_pipeline import (
    adjudicate_ttl,
    deterministic_proposals,
    ttl_intents,
)
from tests.unit.consolidation_cases import NOW, POLICY, decide, proposal, ref, rejected, row, setup, support_fact


def merge():
    return proposal(action='merge_duplicate', survivor_ref=ref(row(2)), duplicate_refs=[ref(row(3))],
                    equivalence_basis='semantic claim is not proof')


def test_exact_equality_accepts_one_keeper_and_explicit_duplicate_exit():
    d = decide(merge())
    assert d.decision == 'accept'
    assert [(e['operation'], e['aggregate_id']) for e in d.approved_effects] == [('merge', 3)]
    assert d.approved_effects[0]['value']['keeper_id'] == 2
    assert 'supersedes_memory_id' not in d.approved_effects[0]['value']
    assert d.proof['origin'] == 'deterministic_rule'
    assert d.proof['confidence'] == 1.0


@pytest.mark.parametrize('change', [{'content_hash': 'e' * 64}, {'content_text': 'similar fact'},
    {'kind': 'procedural'}, {'provenance': 'distilled'}, {'evidence_refs': ['7']},
    {'submission_meta': {'tags': ['different']}}, {'title': 'different'}, {'tags': ['different']},
    {'valid_from': '2025-01-01T00:00:00+00:00'},
    {'required_support': [{'evidence_id': '7', 'version_id': 9}]}])
def test_equality_requires_hash_and_all_key_metadata(change):
    p = merge()
    entries = {1: row(1), 2: row(2), 3: row(3, **change)}
    p['duplicate_refs'] = [ref(entries[3])]
    c, ctx = setup(p, entries=entries, support={'7': support_fact()})
    rejected(decide(p, c, ctx), 'EQUIVALENCE_NOT_PROVEN')


def test_uncertain_semantic_contradiction_rejects_even_at_confidence_one():
    p = proposal(action='invalidate_contradiction', target_ref=ref(row(2)), correcting_ref=ref(row(3)),
                 contradiction_basis='certainly contradicts', confidence=1.)
    rejected(decide(p), 'CONTRADICTION_NOT_PROVEN')


@pytest.mark.parametrize('field,value', [('content_hash', 'b' * 64), ('position', 'different'),
                                        ('version_id', 10), ('source_id', 11)])
def test_correction_requires_original_attribution_to_match_current_fact(field, value):
    correcting = row(3, supersedes_memory_id=2, authority={'source': 'validated_evidence'},
                     provenance='hard', confidence=None, evidence_refs=['7'],
                     provenance_meta={'validated': True, 'attributions': [{'evidence_id': '7', **support_fact()}]})
    p = proposal(action='invalidate_contradiction', target_ref=ref(row(2)), correcting_ref=ref(correcting),
                 contradiction_basis='authoritative correction')
    current, context = setup(p, entries={1: row(1), 2: row(2), 3: correcting}, support={'7': support_fact()})
    assert decide(p, current, context).decision == 'accept'
    altered = {**correcting, 'provenance_meta': {'validated': True, 'attributions': [
        {'evidence_id': '7', **support_fact(), field: value}]}}
    current = replace(current, entries={**current.entries, 3: altered})
    rejected(decide(p, current, context), 'ATTRIBUTION_FAILED')


def test_merge_consumes_only_closed_or_proven_equivalent_sources():
    from hashlib import sha256

    unrelated = row(1, content_text='unrelated', content_hash=sha256(b'unrelated').hexdigest())
    p = merge()
    p['source_refs'] = [ref(unrelated), ref(row(3))]
    current, context = setup(p, entries={1: unrelated, 2: row(2), 3: row(3)})
    decision = decide(p, current, context)
    assert decision.decision == 'accept'
    assert [outcome['source_version']['memory_id'] for outcome in decision.source_outcomes] == [3]


def test_support_invalidation_does_not_consume_unrelated_episode():
    target = row(2, kind='semantic', required_support=[{'evidence_id': '7', 'version_id': 9}])
    p = proposal(action='invalidate_contradiction', target_ref=ref(target), correcting_ref=None,
                 contradiction_basis='withdrawal')
    current, context = setup(p, entries={1: row(1), 2: target}, support={'7': support_fact(status='withdrawn')})
    decision = decide(p, current, context)
    assert decision.decision == 'accept'
    assert decision.source_outcomes == ()


def test_authoritative_single_pointer_correction_accepts():
    correcting = row(3, supersedes_memory_id=2, authority={'source': 'validated_evidence'},
                     provenance='hard', confidence=None, evidence_refs=['7'],
                     provenance_meta={'validated': True, 'attributions': [{'evidence_id': '7', **support_fact()}]})
    p = proposal(action='invalidate_contradiction', target_ref=ref(row(2)), correcting_ref=ref(correcting),
                 contradiction_basis='does not authenticate anything')
    c, ctx = setup(p, entries={1: row(1), 2: row(2), 3: correcting}, support={'7': support_fact()})
    d = decide(p, c, ctx)
    assert d.decision == 'accept'
    assert d.approved_effects[0]['value']['replacement_id'] == 3
    assert d.proof['rule_id'] == 'authoritative_correction'
    bad = replace(c, entries={**c.entries, 3: {**correcting, 'authority': {'source': 'inference'}}})
    rejected(decide(p, bad, ctx), 'CONTRADICTION_NOT_PROVEN')


def test_required_support_withdrawal_accepts_and_stale_or_historical_claim_does_not():
    target = row(2, required_support=[{'evidence_id': '7', 'version_id': 9}])
    p = proposal(action='invalidate_contradiction', target_ref=ref(target), correcting_ref=None,
                 contradiction_basis='withdrawal')
    c, ctx = setup(p, entries={1: row(1), 2: target}, support={'7': support_fact(status='withdrawn')})
    d = decide(p, c, ctx)
    assert d.decision == 'accept'
    assert d.proof['rule_id'] == 'support_withdrawal'
    rejected(decide(p, c, replace(ctx, support_facts={'7': support_fact()})), 'CONTRADICTION_NOT_PROVEN')
    rejected(decide(p, c, replace(ctx, support_facts={'7': support_fact(status='withdrawn', version_id=10)})),
             'CONTRADICTION_NOT_PROVEN')
    historical = replace(c, entries={1: row(1, status='retired'), 2: {**target, 'required_support': []}})
    # A historical episode disappearing is not support withdrawal; use a different live episode source.
    p['source_refs'] = [ref(row(3))]
    historical, ctx = setup(p, entries={**historical.entries, 3: row(3)}, support={'7': support_fact(status='withdrawn')})
    rejected(decide(p, historical, ctx), 'CONTRADICTION_NOT_PROVEN')


def test_rule_generation_is_deterministic_and_every_effect_passes_adjudication():
    p = merge()
    c, ctx = setup(p)
    first = deterministic_proposals(c, context=ctx, policy=POLICY, now=NOW)
    second = deterministic_proposals(c, context=ctx, policy=POLICY, now=NOW)
    assert first == second
    assert first
    decisions = [decide(item, c, ctx) for item in first]
    assert any(d.decision == 'accept' for d in decisions)
    assert all(d.proof['origin'] == 'deterministic_rule' for d in decisions)


@pytest.mark.parametrize('provenance', ['soft', 'hard'])
@pytest.mark.parametrize('stage,next_stage', [('active', 'compressed'), ('compressed', 'archived'),
                                            ('archived', 'tombstone')])
def test_natural_ttl_uses_governed_lifecycle_independent_of_consolidation(provenance, stage, next_stage):
    expired = row(1, provenance=provenance, confidence=None if provenance == 'hard' else .4,
                  expires_at=NOW.isoformat(), retention_stage=stage)
    c, _ctx = setup(entries={1: expired})
    intents = ttl_intents(c, now=NOW)
    assert len(intents) == 1
    d = adjudicate_ttl(intents[0], c, now=NOW)
    assert d.decision == 'accept'
    assert d.approved_effects[0]['value']['retention_stage'] == next_stage
    assert d.source_outcomes == ()
    assert POLICY.model_copy(update={'consolidation_enabled': False, 'consolidation': None})
    assert ttl_intents(c, now=NOW) == intents


def test_ttl_not_early_stale_or_forgeable():
    c, _ctx = setup(entries={1: row(1, expires_at=(NOW + timedelta(seconds=1)).isoformat())})
    assert ttl_intents(c, now=NOW) == ()
    expired = replace(c, entries={1: {**c.entries[1], 'expires_at': NOW.isoformat()}})
    intent = ttl_intents(expired, now=NOW)[0]
    rejected(adjudicate_ttl(intent, c, now=NOW), 'TTL_NOT_DUE')
    rejected(adjudicate_ttl({'memory_id': 1, 'proof': 'ttl'}, expired, now=NOW), 'TRUSTED_CONTEXT_REQUIRED')
    stale = replace(expired, entries={1: {**expired.entries[1], 'state_event_id': 9}})
    rejected(adjudicate_ttl(intent, stale, now=NOW), 'TARGET_VERSION_CHANGED')


def test_rule_generator_emits_authoritative_correction_not_just_duplicates():
    correcting = row(3, content_text='corrected', content_hash='c' * 64, supersedes_memory_id=2,
                     provenance='hard', confidence=None, authority={'source': 'validated_evidence'},
                     evidence_refs=['7'], provenance_meta={'validated': True,
                         'attributions': [{'evidence_id': '7', **support_fact()}]})
    c, ctx = setup(entries={1: row(1), 2: row(2, kind='semantic'), 3: correcting}, support={'7': support_fact()})
    proposals = deterministic_proposals(c, context=ctx, policy=POLICY, now=NOW)
    corrections = [p for p in proposals if p['action'] == 'invalidate_contradiction']
    assert len(corrections) == 1
    assert decide(corrections[0], c, ctx).decision == 'accept'


def test_withdrawal_maintenance_needs_no_live_episode_or_enabled_model_policy():
    from rag_mcp.orchestration.consolidation_pipeline import _SUPPORT_HOOK_SEAL
    from rag_mcp.services.consolidation_adjudicator import AdjudicationContext
    target = row(2, kind='semantic', required_support=[{'evidence_id': '7', 'version_id': 9}])
    p = proposal(action='invalidate_contradiction', source_refs=[], target_ref=ref(target),
                 correcting_ref=None, contradiction_basis='support withdrawal', confidence=1.)
    c, ctx = setup(p, entries={1: row(1, status='retired'), 2: target},
                   support={'7': support_fact(status='withdrawn')})
    ctx = AdjudicationContext(execution_context='deterministic_propagation',
        historical_source_refs=({'memory_id': 1, 'source_event_id': 1, 'content_hash': row(1)['content_hash']},),
        propagation_trigger={'target_ref': ref(target), 'evidence_id': '7', 'version_id': 9},
        support_facts=ctx.support_facts, support_versions=ctx.support_versions, _seal=_SUPPORT_HOOK_SEAL)
    disabled = POLICY.model_copy(update={'consolidation_enabled': False, 'consolidation': None})
    d = decide(p, c, ctx, policy=disabled)
    assert d.decision == 'accept'
    assert d.approved_effects[0]['operation'] == 'invalidate'
    assert d.source_outcomes == ()
    for extra in [{'context': {'context_digest': 'no', 'keywords': []}}, {'action': 'extract_fact'},
                  {'source_refs': [ref(row(1))]}]:
        rejected(decide({**p, **extra}, c, ctx, policy=disabled), 'MAINTENANCE_EFFECT_FORBIDDEN')
    hard = replace(c, entries={**c.entries, 2: {**target, 'provenance': 'hard', 'confidence': None}})
    rejected(decide(p, hard, ctx, policy=disabled), 'HARD_MEMORY_PROTECTED')
    rejected(decide(p, c, replace(ctx, propagation_trigger={'target_ref': ref(row(3)),
        'evidence_id': '7', 'version_id': 9}), policy=disabled), 'CONTRADICTION_NOT_PROVEN')
