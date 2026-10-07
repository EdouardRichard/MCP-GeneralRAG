"""T095/T096/T098: dataset validation and frozen three-arm metric adapter.

Pure tests: they prove the structural dataset contract, the frozen metric
definitions (physical rank, duplicate-alias zero gain, zero-baseline
not-computable), the explicit three-arm reporting and the fail-closed report
validation. No provider, store or dataset material is required.
"""
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / 'eval') not in sys.path:
    sys.path.insert(0, str(ROOT / 'eval'))

from consolidation_eval_support import (
    COVERAGE_SLOTS,
    DatasetInvalid,
    arm_report,
    cross_check_012_metric_functions,
    load_dataset,
    query_metrics,
    relative_gains,
    trace_for,
    validate_comparison_report,
    validate_dataset,
)

from tests.unit.consolidation_gate import binding, build_report

SCOPE = '913000000000000001'


def unit(alias, *, group=None, source='1', content=None, validity='current'):
    return {'alias': alias, 'expected_content': content or f'frozen content {alias}',
            'equivalence_group': group or f'group-{alias}', 'source_event_ids': [source],
            'validity': validity}


def dataset():
    categories = {'extract_fact_01': ('extraction', 'semantic'),
                  'distill_procedure_01': ('extraction', 'procedural'),
                  'correct_01': ('correction', None), 'correct_02': ('correction', None),
                  'merge_01': ('merge', None), 'merge_02': ('merge', None)}
    queries = []
    for slot in COVERAGE_SLOTS:
        category, kind = categories[slot]
        units = [unit(f'{slot}-a'), unit(f'{slot}-b', group='shared')]
        queries.append({'query_id': slot, 'coverage_slot': slot, 'primary_category': category,
                        'extraction_kind': kind, 'question': f'What is frozen for {slot}?',
                        'scope_id': SCOPE, 'expected_content': [f'expected {slot}'],
                        'expected_source_event_ids': ['1'],
                        'locators': [{'kind': 'event', 'event_id': '1'},
                                     {'kind': 'chunk', 'chunk_id': '11', 'position_path': 'section/1'}],
                        'relevance_units': units})
    return {'dataset_version': '013.1', 'k': 5, 'gate_variant': 'consolidated_candidate_expansion',
            'scope_id': SCOPE, 'snapshot_hash': 'a' * 64, 'authority_cutoff': 42,
            'frozen_clock': '2026-10-07T00:00:00+00:00',
            'frozen': {field: f'{field}-v1' for field in
                       ('model', 'prompt', 'schema', 'policy', 'vocabulary', 'recall', 'budget',
                        'implementation', 'snapshot', 'clock')},
            'domain_profile': {'domain_key': 'generic', 'declared_topic_adaptations': ['meeting-notes']},
            'queries': queries}


def test_valid_frozen_dataset_is_accepted_and_round_trips(tmp_path):
    document = dataset()
    path = tmp_path / 'dataset.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    loaded = load_dataset(path)
    assert validate_dataset(loaded) is loaded
    assert [q['coverage_slot'] for q in loaded['queries']] == list(COVERAGE_SLOTS)


@pytest.mark.parametrize('mutation', [
    'missing_slot', 'duplicate_id', 'one_category', 'single_extraction_kind', 'empty_content',
    'no_locator', 'unlocatable_lineage', 'stale_expected_event', 'mixed_equivalence',
    'duplicate_alias', 'wrong_scope', 'bad_snapshot_hash', 'missing_frozen_field', 'wrong_k',
])
def test_dataset_contract_violations_are_rejected(mutation):
    document = dataset()
    queries = document['queries']
    if mutation == 'missing_slot':
        queries.pop()
    elif mutation == 'duplicate_id':
        queries[1]['query_id'] = queries[0]['query_id']
    elif mutation == 'one_category':
        queries[3]['primary_category'] = 'merge'
    elif mutation == 'single_extraction_kind':
        queries[1]['extraction_kind'] = 'semantic'
    elif mutation == 'empty_content':
        queries[0]['expected_content'] = []
    elif mutation == 'no_locator':
        queries[0]['locators'] = []
    elif mutation == 'unlocatable_lineage':
        queries[0]['relevance_units'][0]['source_event_ids'] = ['999999']
    elif mutation == 'stale_expected_event':
        queries[0]['expected_source_event_ids'] = ['8']
    elif mutation == 'mixed_equivalence':
        queries[0]['relevance_units'][1]['equivalence_group'] = 'group-extract_fact_01-a'
    elif mutation == 'duplicate_alias':
        queries[0]['relevance_units'][1]['alias'] = queries[0]['relevance_units'][0]['alias']
    elif mutation == 'wrong_scope':
        queries[0]['scope_id'] = '1'
    elif mutation == 'bad_snapshot_hash':
        document['snapshot_hash'] = 'xyz'
    elif mutation == 'missing_frozen_field':
        document['frozen'].pop('budget')
    else:
        document['k'] = 10
    with pytest.raises(DatasetInvalid):
        validate_dataset(document)


def test_frozen_metrics_follow_physical_rank_and_duplicate_alias_zero_gain():
    ranked = ['u1', None, 'u1', 'u2', 'u3']
    units = ['u1', 'u2', 'u3']
    metrics = query_metrics(ranked, units)
    assert metrics['mrr'] == 1.0
    # the second u1 gains 0 because its alias already appeared at rank 1
    dcg = 1 + 1 / math.log2(5) + 1 / math.log2(6)
    idcg = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert metrics['ndcg'] == pytest.approx(dcg / idcg, abs=1e-12)
    assert metrics['recall_at_k'] == 1.0
    assert metrics['precision_at_k'] == pytest.approx(3 / 5)
    assert metrics['hit_rate'] == 1.0
    assert query_metrics([None] * 5, units)['mrr'] == 0.0


def test_trace_identity_and_012_function_agreement():
    trace = trace_for({'baseline': [None] * 5,
                       'consolidated_direct': ['u1', 'u2'],
                       'consolidated_candidate_expansion': ['u2', 'u1', None, None, None]})
    assert trace['trace_version'] == '013.trace.1' and trace['k'] == 5
    assert trace['variants']['consolidated_direct'] == ['u1', 'u2', None, None, None]
    metrics = cross_check_012_metric_functions(['u2', 'u1', None, None, None], ['u1', 'u2'])
    assert metrics['mrr'] == 1.0 and metrics['ndcg'] == pytest.approx(1.0)
    with pytest.raises(DatasetInvalid, match='distinct aliases'):
        cross_check_012_metric_functions(['u1', 'u1', None, None, None], ['u1', 'u2'])


def test_zero_baseline_is_not_computable_and_three_arms_stay_visible():
    queries = dataset()['queries']
    traces, latency = {}, {}
    for query in queries:
        aliases = [unit['alias'] for unit in query['relevance_units']]
        traces[query['query_id']] = {
            'baseline': [None] * 5,
            'consolidated_direct': [None, aliases[0], None, None, None],
            'consolidated_candidate_expansion': [aliases[1], aliases[0], None, None, None]}
        latency[(query['query_id'], 'baseline')] = 12.5
        latency[(query['query_id'], 'consolidated_candidate_expansion')] = 13.5
    report = arm_report(queries, traces, latency=latency)
    assert len(report['per_query']) == 6
    assert set(report['aggregates']) == {'baseline', 'consolidated_direct',
                                         'consolidated_candidate_expansion'}
    assert report['relative_gains'] == {'baseline_zero': True, 'mrr': None, 'ndcg': None}
    assert report['aggregates']['consolidated_direct']['mrr'] == .5
    assert report['aggregates']['consolidated_candidate_expansion']['mrr'] == 1.0
    assert report['per_query'][0]['consolidated_candidate_expansion']['latency_p50_ms'] == 13.5
    assert report['per_query'][0]['baseline']['cost_usd'] is None
    assert report['direct_fallback_queries'] == []
    first = queries[0]
    aliases = [item['alias'] for item in first['relevance_units']]
    fallback = arm_report(queries[:1], {first['query_id']: {
        'baseline': [None] * 5,
        'consolidated_direct': [aliases[0], None, None, None, None],
        'consolidated_candidate_expansion': [aliases[0], None, None, None, None]}})
    assert fallback['direct_fallback_queries'] == [first['query_id']]
    assert fallback['aggregates']['consolidated_candidate_expansion']['mrr'] == 1.0
    direct = relative_gains({'mrr': .5, 'ndcg': .5}, {'mrr': .55, 'ndcg': .6})
    assert direct == {'baseline_zero': False, 'mrr': pytest.approx(.1),
                      'ndcg': pytest.approx(.2)}


def _evidence(hard_counts=None, exitstatus=0):
    scenarios = ('batch_distillation', 'deterministic_merge', 'deterministic_correction',
                 'soft_overturn_refusal', 'model_schema_fault', 'benefit_gate_control',
                 'manual_candidate_promotion')
    counts = {name: 0 for name in ('cross_scope_leaks', 'soft_overturns_hard', 'automatic_promotions',
                                   'invalid_outputs_applied', 'stale_holder_commits',
                                   'incomplete_outputs_consumed', 'rebuild_llm_calls')}
    counts.update({'source_chain_complete_rate': 1.0, 'projection_integrity_rate': 1.0})
    counts.update(hard_counts or {})
    return {'exitstatus': exitstatus,
            'tests': [{'nodeid': 'tests/integration/x.py::t',
                       'records': [{'scenario': name} for name in scenarios]}],
            'hard_counts': counts}


def test_passed_report_requires_real_e2e_and_old_suite_evidence():
    report = build_report(binding(SCOPE))
    with pytest.raises(DatasetInvalid, match='real 013 E2E evidence'):
        validate_comparison_report(report)
    with pytest.raises(DatasetInvalid, match='old-suite evidence'):
        validate_comparison_report(report, e2e_evidence=_evidence())
    decision = validate_comparison_report(report, e2e_evidence=_evidence(),
                                          old_suite_evidence=['012 acceptance report'])
    assert decision['status'] == 'passed' and decision['default_enable_eligible'] is True
    with pytest.raises(DatasetInvalid, match='observed cross_scope_leaks'):
        validate_comparison_report(report, e2e_evidence=_evidence({'cross_scope_leaks': 1}),
                                   old_suite_evidence=['012 acceptance report'])
    with pytest.raises(DatasetInvalid, match='no observation'):
        validate_comparison_report(report, e2e_evidence=_evidence({'automatic_promotions': None}),
                                   old_suite_evidence=['012 acceptance report'])
    with pytest.raises(DatasetInvalid, match='did not succeed'):
        validate_comparison_report(report, e2e_evidence=_evidence(exitstatus=1),
                                   old_suite_evidence=['012 acceptance report'])
    other = build_report(binding('1'))
    with pytest.raises(DatasetInvalid, match='current trusted binding'):
        validate_comparison_report(report, expected_binding=other['gate_binding'],
                                   e2e_evidence=_evidence(), old_suite_evidence=['012 acceptance report'])
    incomplete = build_report(binding(SCOPE))
    incomplete['cache']['replayed_success'] = 5
    with pytest.raises(DatasetInvalid, match='coverage is not 100%'):
        validate_comparison_report(incomplete, e2e_evidence=_evidence(),
                                   old_suite_evidence=['012 acceptance report'])
