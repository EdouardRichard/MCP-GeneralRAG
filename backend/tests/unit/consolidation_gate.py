"""Shared 013.2 report / gate-registry fixtures for the T055 and T090 tests.

These fixtures prove loader and validator mechanics only. They are explicitly
NOT real three-gate acceptance evidence: no frozen dataset, cache trace or
provider identity backs them, and T103 must install a genuine report.

The per-query metrics are recomputed from a frozen physical-rank trace instead
of being asserted by the fixture, because the shared validator (T090) refuses a
self-reported metric. The traces and units here are synthetic labels: they
carry no evaluation meaning and cannot be mistaken for the frozen dataset.
"""
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from rag_mcp.services.consolidation_gate import TRACE_VERSION, binary_metrics

HASH = 'a' * 64
STAMP = '2026-10-06T06:00:00+00:00'
NOW = datetime(2026, 10, 7, tzinfo=UTC)
BINDING_FIELDS = ('data_hash', 'policy_hash', 'vocabulary_hash', 'prompt_hash', 'schema_hash',
                  'implementation_hash', 'recall_config_hash')
UNITS = ('unit-a', 'unit-b')
TRACES = {
    'baseline': [None, 'unit-a', None, 'unit-b', None],
    'consolidated_direct': [None, 'unit-a', None, 'unit-b', None],
    'consolidated_candidate_expansion': ['unit-a', 'unit-b', None, None, None],
}


def binding(scope_id='1', **overrides):
    value = {'scope_id': scope_id, 'model_version': 'test-model',
             **{key: HASH for key in BINDING_FIELDS}}
    value.update(overrides)
    return value


def metrics(mrr=.5, ndcg=.5):
    return {'mrr': mrr, 'ndcg': ndcg, 'hit_rate': 1., 'recall_at_k': 1., 'precision_at_k': 1.,
            'latency_p50_ms': None, 'latency_p95_ms': None, 'cost_usd': None}


def variant_metrics(variant, k=5):
    values = binary_metrics(TRACES[variant], UNITS, k)
    return {**values, 'latency_p50_ms': None, 'latency_p95_ms': None, 'cost_usd': None}


def build_report(bound, *, variant='consolidated_candidate_expansion', passed=True):
    usage = {'source': 'replay_zero',
             'provider_usage': {key: 0 for key in ('embedding_calls', 'rerank_calls', 'llm_calls',
                                                   'llm_prompt_chars', 'llm_completion_chars')},
             'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0, 'latency_ms': None}
    baseline, direct = variant_metrics('baseline'), variant_metrics('consolidated_direct')
    expansion = variant_metrics('consolidated_candidate_expansion')
    queries = []
    for index, category in enumerate(('extraction', 'extraction', 'correction', 'correction', 'merge', 'merge')):
        queries.append({'query_id': f'q{index}', 'primary_category': category,
            'extraction_kind': ('semantic' if index == 0 else 'procedural') if category == 'extraction' else None,
            'scope_id': bound['scope_id'], 'expected_source_event_ids': ['1'],
            'relevance_units': list(UNITS),
            'baseline': dict(baseline), 'consolidated_direct': dict(direct),
            'consolidated_candidate_expansion': dict(expansion),
            'result_trace': {'trace_version': TRACE_VERSION, 'k': 5,
                             'variants': {name: list(ranked) for name, ranked in TRACES.items()}},
            'failed_paths': []})
    gains = {'baseline_zero': False,
             'mrr': (expansion['mrr'] - baseline['mrr']) / baseline['mrr'],
             'ndcg': (expansion['ndcg'] - baseline['ndcg']) / baseline['ndcg']}
    return {'schema_version': '013.2', 'report_type': '013_memory_consolidation_comparison',
            'generated_at': STAMP, 'commit': 'a' * 40, 'status': 'passed' if passed else 'failed',
            'gate_binding': bound if passed else None,
            'environment': {'host': 'isolated', 'python': '3.12', 'database': 'isolated', 'qdrant': 'isolated',
                            'frozen_clock': STAMP, 'model_version': bound['model_version'],
                            'projection_fingerprints': {'entries': HASH},
                            **{key: bound[key] for key in ('policy_hash', 'vocabulary_hash', 'prompt_hash',
                                                           'schema_hash')},
                            'snapshot_hash': HASH, 'dataset_hash': HASH},
            'request_ids': ['request'], 'run_ids': ['00000000-0000-4000-8000-000000000001'],
            'gate_variant': variant, 'k': 5, 'queries': queries,
            'aggregates': {'baseline': baseline, 'consolidated_direct': direct,
                           'consolidated_candidate_expansion': expansion},
            'relative_gains': gains,
            'cache': {'path': 'evidence/cache.json', 'manifest_hash': HASH, 'content_hash': HASH,
                      'expected_keys': 6, 'recorded_success': 6, 'recorded_failure': 0,
                      'replayed_success': 6, 'replayed_failure': 0, 'missing': 0, 'corrupt': 0,
                      'version_mismatch': 0, 'record_real_network_calls': 6, 'replay_real_network_calls': 0,
                      'response_match_rate': 1, 'evidence_complete': True,
                      'record_usage': {**usage, 'source': 'actual'}, 'replay_usage': usage},
            'reproducibility': {'status': 'passed', 'non_latency_relative_tolerance': .01,
                                'max_non_latency_relative_drift': 0, 'zero_baseline_exact_match': True,
                                'safety_exact_match': True},
            'hard_metrics': {**{key: 0 for key in ('cross_scope_leaks', 'quarantined_inputs', 'soft_overturns_hard',
                                                   'automatic_promotions', 'invalid_outputs_applied',
                                                   'stale_holder_commits', 'incomplete_outputs_consumed',
                                                   'rebuild_llm_calls')},
                             **{key: 1 for key in ('source_chain_complete_rate', 'schema_validity_rate',
                                                   'projection_integrity_rate')}},
            'gates': {'quality': {'status': 'passed', 'checks': {'six_query_coverage': True,
                      'aggregate_recomputed': True, 'relative_gain_thresholds': True}, 'evidence': ['e']},
                      'safety': {'status': 'passed', 'checks': {'hard_metrics_zero': True, 'scope_isolation': True},
                                 'evidence': ['e']},
                      'regression': {'status': 'passed', 'checks': {'reproducibility_passed': True,
                      'replay_zero_network': True, 'legacy_contract_unchanged': True}, 'evidence': ['e']}},
            'default_enable_eligible': passed,
            'default_configuration': {'consolidation_enabled': False, 'link_expansion_enabled': False,
                                      'policy_published': False, 'reason': 'Evaluation only'},
            'evidence_paths': ['evidence/test.txt'], 'failed_paths': []}


def default_expiry():
    """A proof installed right now carries an expiry relative to the wall clock.

    It must not be a fixed calendar stamp: production paths such as
    ``MemoryService.recall`` evaluate the gate at the real time, so tying the
    default to the frozen ``NOW`` silently turned every default registry into an
    expired one the day after it was written (observed on 2026-10-08, when
    ``NOW + 1 day`` was already in the past). The frozen ``NOW`` remains the
    evaluation clock for the pure gate tests that pass it explicitly.
    """
    return datetime.now(UTC) + timedelta(days=1)


def install_registry(directory, bound, report_body, *, expires=None):
    """Deployer-style atomic install of one registry entry plus its report bytes."""
    directory = Path(directory)
    raw = json.dumps(report_body).encode()
    entry = {'gate_binding': bound, 'report_path': 'reports/report.json',
             'report_sha256': sha256(raw).hexdigest(),
             'expires_at': (expires or default_expiry()).isoformat()}
    (directory / 'reports').mkdir(parents=True, exist_ok=True)
    (directory / 'reports/report.json').write_bytes(raw)
    registry = directory / 'registry.json'
    registry.write_text(json.dumps({'schema_version': '013.gate.1', 'entries': [entry]}))
    return registry
