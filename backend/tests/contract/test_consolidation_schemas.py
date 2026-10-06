import json
from datetime import datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).parents[3] / 'specs/013-memory-consolidation-loop/contracts'
HASH = 'a' * 64
STAMP = '2026-10-06T06:00:00+00:00'
RUN = '00000000-0000-4000-8000-000000000001'
REF = {'memory_id': 1, 'source_event_id': 1, 'state_event_id': 1, 'content_hash': HASH}
BINDING = {'scope_id': '1', 'model_version': 'test-model', **{k: HASH for k in
           ('data_hash', 'policy_hash', 'vocabulary_hash', 'prompt_hash', 'schema_hash', 'implementation_hash', 'recall_config_hash')}}


def validator(name):
    schemas = [json.loads(p.read_text(encoding='utf-8')) for p in ROOT.glob('*.schema.json')]
    registry = Registry().with_resources((s['$id'], Resource.from_contents(s)) for s in schemas)
    schema = json.loads((ROOT / name).read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    formats = FormatChecker()

    @formats.checks('date-time', raises=ValueError)
    def timestamp(value):
        return not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is not None

    return Draft202012Validator(schema, registry=registry, format_checker=formats)


def proposal(action):
    common = {'proposal_id': 'p0', 'action': action, 'source_refs': [REF], 'confidence': .8,
              'justification': 'Source-backed proposal', 'evidence_refs': []}
    if action in ('extract_fact', 'distill_procedure'):
        common.update(kind='semantic' if action == 'extract_fact' else 'procedural', content='Approved body')
    elif action == 'merge_duplicate':
        common.update(survivor_ref=REF, duplicate_refs=[{**REF, 'memory_id': 2}], equivalence_basis='Exact equality')
    else:
        common.update(target_ref=REF, correcting_ref=None, contradiction_basis='Revoked support')
    return common


@pytest.mark.parametrize('action', ['extract_fact', 'distill_procedure', 'merge_duplicate', 'invalidate_contradiction'])
def test_four_actions_and_unknown_permission_rejection(action):
    check = validator('distiller-output.schema.json')
    body = {'proposals': [proposal(action)]}
    check.validate(body)
    body['proposals'][0]['writer_permission'] = True
    assert not check.is_valid(body)


@pytest.mark.parametrize('confidence', [float('nan'), float('inf'), -float('inf')])
def test_contract_boundary_rejects_nonfinite_confidence(confidence):
    from rag_mcp.orchestration.consolidation_pipeline import validate_contract
    with pytest.raises(ValueError):
        validate_contract({'proposals': [{**proposal('extract_fact'), 'confidence': confidence}]},
                          validator('distiller-output.schema.json'))


def event_v2():
    return {'payload_version': 2, 'operation': 'derive', 'action': 'extract_fact', 'proposal_key': HASH,
            'group_key': HASH, 'group_id': RUN, 'effect_index': 0, 'effect_count': 1, 'created_by_run': RUN,
            'execution_context': 'distiller_window', 'window_id': 2, 'propagation': None,
            'source_refs': [REF], 'target_refs': [REF], 'source_outcomes': [], 'source_lineage': [REF],
            'required_support': [], 'confidence': .8, 'confidence_origin': 'llm_self', 'evidence_refs': [],
            'versions': {'model': 'test', 'prompt': 'test', 'schema': '013.1', 'rule': '1', 'policy': HASH, 'vocabulary': HASH},
            'captured_policy': {}, 'captured_vocabulary': [],
            'adjudication': {'decision_id': 'd0', 'decision': 'accept', 'rule_version': '1', 'reason_codes': ['ACCEPTED'],
                             'min_confidence': .8, 'proofs': [], 'evidence_attributions': []},
            'approved_effect': {'memory_id': 1, 'links': []}}


def test_v2_local_reference_resolution_and_v1_flat_replay():
    from rag_mcp.services.memory_reducer import reduce_events
    check = validator('consolidate-event.schema.json')
    body = event_v2()
    check.validate(body)
    body['source_lineage'] = []
    assert not check.is_valid(body)
    body = event_v2()
    body['provenance'] = 'hard'
    assert not check.is_valid(body)
    state = reduce_events([{'event_id': 1, 'aggregate_id': 1, 'knowledge_scope_id': 1, 'event_type': 'consolidate',
                            'occurred_at': STAMP, 'payload': {'kind': 'semantic', 'provenance': 'distilled', 'content_text': 'Legacy'}}])
    assert state['entries'][1]['content_text'] == 'Legacy'


def report(passed=False):
    usage = {'source': 'replay_zero', 'provider_usage': {k: 0 for k in
             ('embedding_calls', 'rerank_calls', 'llm_calls', 'llm_prompt_chars', 'llm_completion_chars')},
             'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0, 'latency_ms': None}
    metrics = {'mrr': .5, 'ndcg': .5, 'hit_rate': 1, 'recall_at_k': 1, 'precision_at_k': 1,
               'latency_p50_ms': None, 'latency_p95_ms': None, 'cost_usd': None}
    body = {'schema_version': '013.2', 'report_type': '013_memory_consolidation_comparison', 'generated_at': STAMP,
            'commit': 'a' * 40, 'status': 'passed' if passed else 'incomplete', 'gate_binding': BINDING if passed else None,
            'environment': {'host': 'isolated', 'python': '3.12', 'database': 'isolated', 'qdrant': 'isolated',
                            'frozen_clock': STAMP, 'model_version': 'test-model', 'projection_fingerprints': {'entries': HASH},
                            **{k: HASH for k in ('snapshot_hash', 'dataset_hash', 'policy_hash', 'vocabulary_hash', 'prompt_hash', 'schema_hash')}},
            'request_ids': ['request'], 'run_ids': [RUN], 'gate_variant': 'consolidated_direct', 'k': 5, 'queries': [],
            'aggregates': {k: metrics if passed else None for k in ('baseline', 'consolidated_direct', 'consolidated_candidate_expansion')},
            'relative_gains': {'mrr': .03 if passed else None, 'ndcg': .03 if passed else None, 'baseline_zero': False},
            'cache': {'path': 'evidence/cache.json', 'manifest_hash': HASH, 'content_hash': HASH, 'expected_keys': 6,
                      'recorded_success': 6, 'recorded_failure': 0, 'replayed_success': 6, 'replayed_failure': 0,
                      'missing': 0, 'corrupt': 0, 'version_mismatch': 0, 'record_real_network_calls': 6,
                      'replay_real_network_calls': 0, 'response_match_rate': 1, 'evidence_complete': passed,
                      'record_usage': {**usage, 'source': 'actual'}, 'replay_usage': usage},
            'reproducibility': {'status': 'passed' if passed else 'incomplete', 'non_latency_relative_tolerance': .01,
                                'max_non_latency_relative_drift': 0, 'zero_baseline_exact_match': True, 'safety_exact_match': True},
            'hard_metrics': {**{k: 0 for k in ('cross_scope_leaks', 'quarantined_inputs', 'soft_overturns_hard',
                             'automatic_promotions', 'invalid_outputs_applied', 'stale_holder_commits',
                             'incomplete_outputs_consumed', 'rebuild_llm_calls')},
                             **{k: 1 for k in ('source_chain_complete_rate', 'schema_validity_rate', 'projection_integrity_rate')}},
            'gates': {k: {'status': 'passed' if passed else 'incomplete', 'checks': {'verified': passed}, 'evidence': ['evidence/test.txt']}
                      for k in ('quality', 'safety', 'regression')}, 'default_enable_eligible': passed,
            'default_configuration': {'consolidation_enabled': False, 'link_expansion_enabled': False,
                                      'policy_published': False, 'reason': 'Evaluation only'},
            'evidence_paths': ['evidence/test.txt'], 'failed_paths': []}
    if passed:
        for index, category in enumerate(('extraction', 'extraction', 'correction', 'correction', 'merge', 'merge')):
            body['queries'].append({'query_id': str(index), 'primary_category': category,
                'extraction_kind': ('semantic' if index == 0 else 'procedural') if category == 'extraction' else None,
                'scope_id': '1', 'expected_source_event_ids': ['1'], 'relevance_units': ['unit'],
                'baseline': metrics, 'consolidated_direct': metrics, 'consolidated_candidate_expansion': metrics,
                'result_trace': {'event': '1'}, 'failed_paths': []})
    return body


def test_complete_and_incomplete_reports_have_explicit_gate_binding():
    check = validator('benefit-report.schema.json')
    check.validate(report())
    check.validate(report(True))
    for patch in ({'gate_binding': None}, {'queries': []}, {'hard_metrics': None}):
        assert not check.is_valid({**report(True), **patch})
    broken = report(True)
    broken['gate_binding'] = {**BINDING, 'permission': 'writer'}
    assert not check.is_valid(broken)


def test_gate_registry_path_hash_expiry_and_local_report_reference():
    check = validator('gate-registry.schema.json')
    entry = {'gate_binding': BINDING, 'report_path': 'evidence/report.json', 'report_sha256': HASH, 'expires_at': STAMP}
    check.validate({'schema_version': '013.gate.1', 'entries': [entry]})
    for patch in ({'report_path': '../report.json'}, {'report_path': 'C:/report.json'},
                  {'report_sha256': 'short'}, {'expires_at': 'not-a-date'}, {'grant': 'writer'}):
        assert not check.is_valid({'schema_version': '013.gate.1', 'entries': [{**entry, **patch}]})
