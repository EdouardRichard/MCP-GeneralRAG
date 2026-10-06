"""T055: read-only gate proof loading, binding and report validation.

Fixtures prove loader mechanics only; they are not real three-gate evidence.
"""
import json
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from rag_mcp.services.consolidation_gate import (
    canonical_json,
    data_material_hash,
    load_gate_proof,
    ordinary_source_events,
    validate_gate_binding,
    validate_report,
)

HASH = 'a' * 64
STAMP = '2026-10-06T06:00:00+00:00'
NOW = datetime(2026, 10, 7, tzinfo=UTC)


def binding(scope_id='1', **overrides):
    value = {'scope_id': scope_id, 'model_version': 'test-model',
             **{key: HASH for key in ('data_hash', 'policy_hash', 'vocabulary_hash', 'prompt_hash',
                                      'schema_hash', 'implementation_hash', 'recall_config_hash')}}
    value.update(overrides)
    return value


def metrics(mrr=.5, ndcg=.5):
    return {'mrr': mrr, 'ndcg': ndcg, 'hit_rate': 1., 'recall_at_k': 1., 'precision_at_k': 1.,
            'latency_p50_ms': None, 'latency_p95_ms': None, 'cost_usd': None}


def build_report(bound, *, variant='consolidated_candidate_expansion', passed=True):
    usage = {'source': 'replay_zero',
             'provider_usage': {key: 0 for key in ('embedding_calls', 'rerank_calls', 'llm_calls',
                                                   'llm_prompt_chars', 'llm_completion_chars')},
             'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0, 'latency_ms': None}
    baseline, direct, expansion = metrics(), metrics(), metrics(mrr=.53, ndcg=.53)
    queries = []
    for index, category in enumerate(('extraction', 'extraction', 'correction', 'correction', 'merge', 'merge')):
        queries.append({'query_id': f'q{index}', 'primary_category': category,
            'extraction_kind': ('semantic' if index == 0 else 'procedural') if category == 'extraction' else None,
            'scope_id': bound['scope_id'], 'expected_source_event_ids': ['1'], 'relevance_units': ['unit'],
            'baseline': baseline, 'consolidated_direct': direct, 'consolidated_candidate_expansion': expansion,
            'result_trace': {'event': '1'}, 'failed_paths': []})
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


def install_registry(directory, bound, report_body, *, expires=None):
    directory = Path(directory)
    raw = json.dumps(report_body).encode()
    entry = {'gate_binding': bound, 'report_path': 'reports/report.json',
             'report_sha256': sha256(raw).hexdigest(),
             'expires_at': (expires or (NOW + timedelta(days=1))).isoformat()}
    (directory / 'reports').mkdir(parents=True, exist_ok=True)
    (directory / 'reports/report.json').write_bytes(raw)
    registry = directory / 'registry.json'
    registry.write_text(json.dumps({'schema_version': '013.gate.1', 'entries': [entry]}))
    return registry


class TestPureValidation:
    def test_binding_shape(self):
        assert validate_gate_binding(binding())['scope_id'] == '1'
        for patch in ({'scope_id': '0'}, {'scope_id': 1}, {'data_hash': 'short'},
                      {'model_version': ''}, {'extra': 1}):
            with pytest.raises(ValueError):
                validate_gate_binding({**binding(), **patch})
        with pytest.raises(ValueError):
            validate_gate_binding({key: value for key, value in binding().items() if key != 'data_hash'})

    def test_report_semantics_positive_and_matrix(self):
        report = build_report(binding())
        assert validate_report(report)['status'] == 'passed'
        # Duplicate query ids, mixed scopes, fabricated aggregates, missing gate
        # checks and direct-only coverage all fail semantic validation.
        cases = []
        duplicate = build_report(binding())
        duplicate['queries'][1]['query_id'] = 'q0'
        cases.append(duplicate)
        mixed = build_report(binding())
        mixed['queries'][0]['scope_id'] = '2'
        cases.append(mixed)
        fabricated = build_report(binding())
        fabricated['aggregates']['consolidated_candidate_expansion'] = metrics(mrr=.9, ndcg=.9)
        cases.append(fabricated)
        missing_check = build_report(binding())
        del missing_check['gates']['safety']['checks']['scope_isolation']
        cases.append(missing_check)
        few_queries = build_report(binding())
        few_queries['queries'] = few_queries['queries'][:5]
        cases.append(few_queries)
        tampered_gain = build_report(binding())
        tampered_gain['relative_gains']['mrr'] = .5
        cases.append(tampered_gain)
        hard_failure = build_report(binding())
        hard_failure['hard_metrics']['soft_overturns_hard'] = 1
        cases.append(hard_failure)
        for broken in cases:
            with pytest.raises(ValueError):
                validate_report(broken)

    def test_canonical_json_and_data_material_hash(self):
        assert canonical_json({'b': 1, 'a': 'é'}) == b'{"a":"\\u00e9","b":1}'
        with pytest.raises(ValueError):
            canonical_json({'x': float('nan')})
        events = [{'event_id': 5, 'event_type': 'assert', 'occurred_at': STAMP, 'aggregate_id': 5,
                   'payload': {'kind': 'episodic'}}]
        evidence = [{'chunk_id': '9', 'content_hash': HASH}]
        first = data_material_hash(1, events, evidence)
        assert first == data_material_hash(1, events, evidence)
        assert data_material_hash(1, [*events, {'event_id': 6, 'event_type': 'retract', 'occurred_at': STAMP,
                                                'aggregate_id': 5, 'payload': {}}], evidence) != first

    def test_013_internal_effects_never_enter_data_material(self):
        ordinary = {'event_id': 5, 'event_type': 'assert', 'occurred_at': STAMP, 'aggregate_id': 5, 'payload': {}}
        internal = [
            {'event_id': 6, 'event_type': 'consolidate', 'occurred_at': STAMP, 'aggregate_id': 6,
             'payload': {'payload_version': 2}},
            {'event_id': 7, 'event_type': 'grant', 'occurred_at': STAMP, 'aggregate_id': 7,
             'payload': {'grant_type': 'consolidation_window'}},
            {'event_id': 8, 'event_type': 'grant', 'occurred_at': STAMP, 'aggregate_id': 8,
             'payload': {'grant_type': 'consolidation_propagation'}},
        ]
        assert ordinary_source_events([ordinary, *internal]) == ordinary_source_events([ordinary])
        policy_grant = {'event_id': 9, 'event_type': 'grant', 'occurred_at': STAMP, 'aggregate_id': 9,
                        'payload': {'policy_after': {}}}
        v1 = {'event_id': 10, 'event_type': 'consolidate', 'occurred_at': STAMP, 'aggregate_id': 10, 'payload': {}}
        assert [e['event_id'] for e in ordinary_source_events([ordinary, policy_grant, v1, *internal])] == ['5', '9', '10']

    def test_gate_module_stays_read_only_and_eval_free(self):
        source = Path(__file__).parents[2] / 'src/rag_mcp/services/consolidation_gate.py'
        text = source.read_text(encoding='utf-8')
        assert 'eval' not in [line.split()[1].split('.')[0] for line in text.splitlines()
                              if line.startswith(('import ', 'from ')) and len(line.split()) > 1]
        # Read-only: no writer, session-mutation, upload or eval capability, and
        # no cached authorization keyed by anything but validated report bytes.
        for forbidden in ('session.add', 'session.delete', 'session.commit', 'session.flush',
                          'apply_event', 'MemoryService', 'ingestion_service', '.execute(text("INSERT',
                          '.execute(text("UPDATE', '.execute(text("DELETE'):
            assert forbidden not in text
        assert 'Authorization' not in text and 'authorized_cache' not in text


class TestLoadGateProof:
    @pytest.mark.asyncio
    async def test_not_configured_and_data_root_containment(self, tmp_path, monkeypatch):
        monkeypatch.delenv('CONSOLIDATION_GATE_REGISTRY_PATH', raising=False)
        proof = await load_gate_proof('1', binding(), NOW)
        assert not proof.available and proof.reason_code == 'GATE_NOT_CONFIGURED'
        inside = Path(os.environ['DATA_ROOT']).resolve() / 'registry.json'
        inside.parent.mkdir(parents=True, exist_ok=True)
        inside.write_text('{}')
        proof = await load_gate_proof('1', binding(), NOW, registry_path=str(inside))
        assert not proof.available and proof.reason_code == 'GATE_INVALID'

    @pytest.mark.asyncio
    async def test_missing_invalid_and_budget_limited_registry(self, tmp_path):
        proof = await load_gate_proof('1', binding(), NOW, registry_path=str(tmp_path / 'absent.json'))
        assert proof.reason_code == 'GATE_MISSING'
        broken = tmp_path / 'registry.json'
        broken.write_text('{"schema_version": "013.gate.1", "entries": [], "entries": []}')
        assert (await load_gate_proof('1', binding(), NOW, registry_path=str(broken))).reason_code == 'GATE_INVALID'
        broken.write_text(json.dumps({'schema_version': '013.gate.2', 'entries': []}))
        assert (await load_gate_proof('1', binding(), NOW, registry_path=str(broken))).reason_code == 'GATE_INVALID'
        broken.write_text(json.dumps({'schema_version': '013.gate.1', 'entries': []}))
        assert (await load_gate_proof('1', binding(), NOW, registry_path=str(broken))).reason_code == 'GATE_MISSING'
        assert (await load_gate_proof('1', binding(), NOW, registry_path=str(broken),
                                      remaining_budget_ms=0)).reason_code == 'GATE_IO_BUDGET_EXCEEDED'
        oversized = tmp_path / 'big.json'
        oversized.write_bytes(b'{"schema_version":"013.gate.1","entries":[],"pad":"' + b'x' * 300_000 + b'"}')
        assert (await load_gate_proof('1', binding(), NOW,
                                      registry_path=str(oversized))).reason_code == 'GATE_INVALID'

    @pytest.mark.asyncio
    async def test_full_positive_then_revocation_and_tampering(self, tmp_path):
        bound = binding()
        registry = install_registry(tmp_path, bound, build_report(bound))
        proof = await load_gate_proof('1', bound, NOW, registry_path=str(registry))
        assert proof.available, proof.reason_code
        assert proof.scope_id == '1' and proof.gate_variant == 'consolidated_candidate_expansion'
        assert proof.report_sha256 == sha256((tmp_path / 'reports/report.json').read_bytes()).hexdigest()
        assert proof.binding == bound and proof.expires_at is not None
        # No cached authorization survives entry removal.
        registry.write_text(json.dumps({'schema_version': '013.gate.1', 'entries': []}))
        assert (await load_gate_proof('1', bound, NOW,
                                      registry_path=str(registry))).reason_code == 'GATE_MISSING'
        # Same-mtime tampering is detected by exact bytes.
        registry = install_registry(tmp_path, bound, build_report(bound))
        report_path = tmp_path / 'reports/report.json'
        original = report_path.read_bytes()
        tampered = build_report(bound)
        tampered['relative_gains']['mrr'] = .5
        raw = json.dumps(tampered).encode()
        report_path.write_bytes(raw)
        stat = os.stat(report_path)
        os.utime(report_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert report_path.read_bytes() != original
        assert (await load_gate_proof('1', bound, NOW,
                                      registry_path=str(registry))).reason_code == 'GATE_HASH_MISMATCH'

    @pytest.mark.asyncio
    async def test_negative_matrix(self, tmp_path):
        bound = binding()
        # expired entry
        registry = install_registry(tmp_path / 'expired', bound, build_report(bound),
                                    expires=NOW - timedelta(seconds=1))
        assert (await load_gate_proof('1', bound, NOW,
                                      registry_path=str(registry))).reason_code == 'GATE_EXPIRED'
        # expiry must be later than report generation
        registry = install_registry(tmp_path / 'early', bound, build_report(bound),
                                    expires=datetime(2026, 10, 6, 6, tzinfo=UTC))
        assert (await load_gate_proof('1', bound, NOW,
                                      registry_path=str(registry))).reason_code == 'GATE_EXPIRED'
        # wrong scope entry
        registry = install_registry(tmp_path / 'scope', binding(scope_id='2'),
                                    build_report(binding(scope_id='2')))
        assert (await load_gate_proof('1', binding(scope_id='2'), NOW,
                                      registry_path=str(registry))).reason_code == 'GATE_MISSING'
        # stale binding vs current
        registry = install_registry(tmp_path / 'stale', bound, build_report(bound))
        assert (await load_gate_proof('1', binding(data_hash='b' * 64), NOW,
                                      registry_path=str(registry))).reason_code == 'GATE_BINDING_STALE'
        # entry/report binding divergence
        registry = install_registry(tmp_path / 'diverge', binding(data_hash='c' * 64), build_report(bound))
        assert (await load_gate_proof('1', bound, NOW,
                                      registry_path=str(registry))).reason_code == 'GATE_BINDING_STALE'
        # direct-only reports never authorize expansion
        registry = install_registry(tmp_path / 'direct', bound,
                                    build_report(bound, variant='consolidated_direct'))
        assert (await load_gate_proof('1', bound, NOW,
                                      registry_path=str(registry))).reason_code == 'GATE_VARIANT_NOT_AUTHORIZED'
        # failed reports never authorize
        registry = install_registry(tmp_path / 'failed', bound, build_report(bound, passed=False))
        assert (await load_gate_proof('1', bound, NOW,
                                      registry_path=str(registry))).reason_code == 'GATE_VARIANT_NOT_AUTHORIZED'
        # report file removed after registry install
        registry = install_registry(tmp_path / 'removed', bound, build_report(bound))
        (tmp_path / 'removed/reports/report.json').unlink()
        assert (await load_gate_proof('1', bound, NOW,
                                      registry_path=str(registry))).reason_code == 'GATE_MISSING'

    @pytest.mark.asyncio
    async def test_report_path_escape_rejected(self, tmp_path):
        bound = binding()
        raw = json.dumps(build_report(bound)).encode()
        entry = {'gate_binding': bound, 'report_path': '../escape.json',
                 'report_sha256': sha256(raw).hexdigest(),
                 'expires_at': (NOW + timedelta(days=1)).isoformat()}
        registry = tmp_path / 'registry.json'
        registry.write_text(json.dumps({'schema_version': '013.gate.1', 'entries': [entry]}))
        assert (await load_gate_proof('1', bound, NOW,
                                      registry_path=str(registry))).reason_code == 'GATE_INVALID'
