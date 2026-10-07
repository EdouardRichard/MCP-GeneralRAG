"""T090: shared 013.2 comparison-report semantics and metric recomputation.

These tests exercise the pure backend validator that the eval comparison
runner and the production gate loader share. They are report-semantics tests:
no database, no provider and no frozen evaluation material is involved, and
they are explicitly not three-gate acceptance evidence (T102/T103 own that).

The physical-rank rules under test come from evaluation-contract.md
"Relevance and metrics": binary gains, preserved physical rank, duplicate
alias gain zero after the first occurrence, macro average at the frozen K=5,
a missing rank contributes zero, and a zero baseline is not computable.
"""
import json
import math
from hashlib import sha256

import pytest

from rag_mcp.services.consolidation_gate import (
    TRACE_VERSION,
    binary_metrics,
    load_gate_proof,
    macro_average,
    validate_report,
)
from tests.unit.consolidation_gate import (
    NOW,
    TRACES,
    UNITS,
    binding,
    build_report,
    install_registry,
    variant_metrics,
)

IDEAL_TWO_UNITS = 1.0 / math.log2(2) + 1.0 / math.log2(3)


class TestBinaryMetrics:
    """Pure binary-gain retrieval metrics at preserved physical rank."""

    def test_mrr_and_ndcg_use_the_true_physical_rank(self):
        observed = binary_metrics([None, 'unit-a', None, 'unit-b', None],
                                  ['unit-a', 'unit-b'], 5)
        assert observed['mrr'] == pytest.approx(0.5)
        assert observed['hit_rate'] == 1.0
        assert observed['recall_at_k'] == 1.0
        assert observed['precision_at_k'] == pytest.approx(0.4)
        expected = (1.0 / math.log2(3) + 1.0 / math.log2(5)) / IDEAL_TWO_UNITS
        assert observed['ndcg'] == pytest.approx(expected)

    def test_duplicate_alias_gains_zero_after_the_first_occurrence(self):
        observed = binary_metrics(['unit-a', None, 'unit-a', None, None],
                                  ['unit-a', 'unit-b'], 5)
        # The second occurrence must not add gain: recall counts one distinct
        # unit out of two and nDCG keeps only the rank-1 discount.
        assert observed['recall_at_k'] == pytest.approx(0.5)
        assert observed['precision_at_k'] == pytest.approx(0.2)
        assert observed['ndcg'] == pytest.approx(1.0 / IDEAL_TWO_UNITS)

    def test_missing_rank_and_gainless_retrieval_are_zero(self):
        assert binary_metrics([None] * 5, ['unit-a'], 5) == {
            'mrr': 0.0, 'ndcg': 0.0, 'hit_rate': 0.0, 'recall_at_k': 0.0, 'precision_at_k': 0.0}
        # A relevant unit beyond the frozen K contributes nothing.
        assert binary_metrics([None] * 5 + ['unit-a'], ['unit-a'], 5) == {
            'mrr': 0.0, 'ndcg': 0.0, 'hit_rate': 0.0, 'recall_at_k': 0.0, 'precision_at_k': 0.0}
        # Physical rank longer than K still only scores the first K positions.
        assert binary_metrics(['unit-a', None, None, None, None, 'unit-a'], ['unit-a'], 5) == {
            'mrr': 1.0, 'ndcg': 1.0, 'hit_rate': 1.0, 'recall_at_k': 1.0, 'precision_at_k': 0.2}

    def test_ideal_dcg_is_capped_by_k_and_by_relevant_units(self):
        everything = binary_metrics(['unit-a', 'unit-b', 'unit-c'],
                                    ['unit-a', 'unit-b', 'unit-c'], 5)
        assert everything['ndcg'] == pytest.approx(1.0)
        assert everything['recall_at_k'] == pytest.approx(1.0)
        assert everything['precision_at_k'] == pytest.approx(0.6)

    def test_aliases_outside_the_frozen_units_gain_nothing(self):
        assert binary_metrics(['other'], ['unit-a'], 5)['hit_rate'] == 0.0

    def test_macro_average_carries_a_missing_rank_as_zero(self):
        observed = macro_average([
            binary_metrics(['unit-a', None, None, None, None], ['unit-a'], 5),
            binary_metrics([None] * 5, ['unit-a'], 5),
        ])
        assert observed['mrr'] == pytest.approx(0.5)
        assert observed['ndcg'] == pytest.approx(0.5)
        assert observed['hit_rate'] == pytest.approx(0.5)
        assert observed['recall_at_k'] == pytest.approx(0.5)
        assert observed['precision_at_k'] == pytest.approx(0.1)


class TestPassedReportSemantics:
    def test_shared_fixture_report_is_valid(self):
        report = build_report(binding())
        assert validate_report(report)['status'] == 'passed'
        for variant, ranked in TRACES.items():
            assert report['aggregates'][variant]['mrr'] == pytest.approx(
                variant_metrics(variant)['mrr'])
            assert report['queries'][0]['result_trace']['variants'][variant] == ranked
        assert report['queries'][0]['relevance_units'] == list(UNITS)
        assert report['queries'][0]['result_trace']['trace_version'] == TRACE_VERSION

    def test_passed_report_requires_a_complete_gate_binding(self):
        broken = build_report(binding())
        broken['gate_binding'] = None
        with pytest.raises(ValueError):
            validate_report(broken)
        incomplete = build_report(binding())
        del incomplete['gate_binding']['implementation_hash']
        with pytest.raises(ValueError):
            validate_report(incomplete)
        bad_scope = build_report(binding())
        bad_scope['gate_binding']['scope_id'] = '0'
        with pytest.raises(ValueError):
            validate_report(bad_scope)

    def test_passed_report_environment_must_agree_with_the_binding(self):
        for key in ('policy_hash', 'vocabulary_hash', 'prompt_hash', 'schema_hash'):
            broken = build_report(binding())
            broken['environment'][key] = 'b' * 64
            with pytest.raises(ValueError):
                validate_report(broken)
        model = build_report(binding())
        model['environment']['model_version'] = 'other-model'
        with pytest.raises(ValueError):
            validate_report(model)

    def test_passed_report_rejects_cross_scope_queries(self):
        broken = build_report(binding())
        broken['queries'][3]['scope_id'] = '2'
        with pytest.raises(ValueError):
            validate_report(broken)

    def test_passed_report_rejects_fabricated_per_query_metrics(self):
        broken = build_report(binding())
        broken['queries'][2]['consolidated_candidate_expansion'] = {
            **broken['queries'][2]['consolidated_candidate_expansion'], 'mrr': 0.9}
        with pytest.raises(ValueError):
            validate_report(broken)

    def test_passed_report_rejects_a_duplicate_alias_double_count(self):
        broken = build_report(binding())
        for query in broken['queries']:
            query['result_trace']['variants']['consolidated_candidate_expansion'] = [
                'unit-a', None, 'unit-a', None, 'unit-b']
            # Claim the full ideal nDCG that only a double-counted gain could reach.
            query['consolidated_candidate_expansion'] = {
                **query['consolidated_candidate_expansion'], 'ndcg': 1.0}
        with pytest.raises(ValueError):
            validate_report(broken)

    def test_passed_report_rejects_unknown_or_malformed_trace_aliases(self):
        unknown = build_report(binding())
        unknown['queries'][0]['result_trace']['variants']['baseline'][0] = 'not-a-frozen-unit'
        with pytest.raises(ValueError):
            validate_report(unknown)
        empty_label = build_report(binding())
        empty_label['queries'][0]['relevance_units'] = ['   ']
        with pytest.raises(ValueError):
            validate_report(empty_label)
        stale_trace = build_report(binding())
        stale_trace['queries'][0]['result_trace']['trace_version'] = '013.trace.0'
        with pytest.raises(ValueError):
            validate_report(stale_trace)
        short_trace = build_report(binding())
        short_trace['queries'][0]['result_trace']['variants']['baseline'] = [None, None]
        with pytest.raises(ValueError):
            validate_report(short_trace)

    def test_passed_report_requires_both_relative_gains_at_three_percent(self):
        mrr_only = build_report(binding())
        mrr_only['relative_gains']['ndcg'] = 0.02
        with pytest.raises(ValueError):
            validate_report(mrr_only)
        ndcg_only = build_report(binding())
        ndcg_only['relative_gains']['mrr'] = 0.02
        with pytest.raises(ValueError):
            validate_report(ndcg_only)

    def test_passed_report_rejects_hidden_direct_path_regression(self):
        for metric in ('hit_rate', 'recall_at_k', 'precision_at_k'):
            broken = build_report(binding())
            for query in broken['queries']:
                query['consolidated_direct'] = {**query['consolidated_direct'], metric: 0.0}
            broken['aggregates']['consolidated_direct'] = {
                **broken['aggregates']['consolidated_direct'], metric: 0.0}
            with pytest.raises(ValueError):
                validate_report(broken)

    def test_passed_report_requires_all_three_gates_and_their_checks(self):
        for gate in ('quality', 'safety', 'regression'):
            broken = build_report(binding())
            broken['gates'][gate]['status'] = 'incomplete'
            with pytest.raises(ValueError):
                validate_report(broken)


class TestIncompleteBranch:
    def test_incomplete_report_keeps_empty_and_null_observations(self):
        report = build_report(binding(), passed=False)
        report['status'] = 'incomplete'
        report['run_ids'] = []
        report['queries'] = []
        report['aggregates'] = {'baseline': None, 'consolidated_direct': None,
                                'consolidated_candidate_expansion': None}
        report['relative_gains'] = {'mrr': None, 'ndcg': None, 'baseline_zero': True}
        report['hard_metrics'] = None
        report['reproducibility'] = {'status': 'incomplete', 'non_latency_relative_tolerance': 0.01,
                                     'max_non_latency_relative_drift': None,
                                     'zero_baseline_exact_match': False, 'safety_exact_match': False}
        report['cache'] = {**report['cache'], 'manifest_hash': None, 'content_hash': None,
                           'response_match_rate': None, 'evidence_complete': False}
        report['environment'] = {**report['environment'], 'frozen_clock': None,
                                 'snapshot_hash': None, 'dataset_hash': None, 'model_version': None,
                                 'policy_hash': None, 'vocabulary_hash': None, 'prompt_hash': None,
                                 'schema_hash': None}
        report['default_enable_eligible'] = False
        report['failed_paths'] = ['evidence/preflight.txt']
        assert validate_report(report)['status'] == 'incomplete'

    def test_incomplete_report_can_never_be_default_enable_eligible(self):
        report = build_report(binding(), passed=False)
        report['status'] = 'incomplete'
        report['default_enable_eligible'] = True
        with pytest.raises(ValueError):
            validate_report(report)

    def test_declared_passed_status_with_unobserved_metrics_is_rejected(self):
        report = build_report(binding())
        report['queries'][0]['baseline'] = None
        with pytest.raises(ValueError):
            validate_report(report)
        report = build_report(binding())
        report['aggregates']['baseline'] = None
        with pytest.raises(ValueError):
            validate_report(report)

    def test_zero_baseline_is_not_computable_and_not_eligible(self):
        zeroed = build_report(binding(), passed=False)
        zeroed['status'] = 'incomplete'
        for query in zeroed['queries']:
            query['baseline'] = {**query['baseline'], 'mrr': 0.0, 'ndcg': 0.0}
        zeroed['aggregates']['baseline'] = {**zeroed['aggregates']['baseline'], 'mrr': 0.0, 'ndcg': 0.0}
        zeroed['relative_gains'] = {'mrr': None, 'ndcg': None, 'baseline_zero': True}
        zeroed['default_enable_eligible'] = False
        assert validate_report(zeroed)['relative_gains']['mrr'] is None
        # A computed gain, or a "not zero" claim, is impossible on a zero baseline.
        for gains in ({'mrr': 0.5, 'ndcg': 0.5, 'baseline_zero': False},
                      {'mrr': None, 'ndcg': None, 'baseline_zero': False}):
            dishonest = build_report(binding(), passed=False)
            dishonest['status'] = 'incomplete'
            for query in dishonest['queries']:
                query['baseline'] = {**query['baseline'], 'mrr': 0.0, 'ndcg': 0.0}
            dishonest['aggregates']['baseline'] = {**dishonest['aggregates']['baseline'],
                                                   'mrr': 0.0, 'ndcg': 0.0}
            dishonest['relative_gains'] = gains
            dishonest['default_enable_eligible'] = False
            with pytest.raises(ValueError):
                validate_report(dishonest)


class TestAuthorizationBoundary:
    """The loader boundary the runner must not be able to install around."""

    @pytest.mark.asyncio
    async def test_direct_only_report_never_authorizes_expansion(self, tmp_path):
        bound = binding()
        registry = install_registry(tmp_path, bound,
                                    build_report(bound, variant='consolidated_direct'))
        proof = await load_gate_proof('1', bound, NOW, registry_path=str(registry))
        assert not proof.available and proof.reason_code == 'GATE_VARIANT_NOT_AUTHORIZED'

    @pytest.mark.asyncio
    async def test_recomputed_semantics_reject_a_hand_edited_report(self, tmp_path):
        bound = binding()
        registry = install_registry(tmp_path, bound, build_report(bound))
        report_path = tmp_path / 'reports/report.json'
        tampered = build_report(bound)
        tampered['queries'][0]['consolidated_candidate_expansion'] = {
            **tampered['queries'][0]['consolidated_candidate_expansion'], 'ndcg': 0.99}
        raw = json.dumps(tampered).encode()
        report_path.write_bytes(raw)
        # Refresh the registry hash so only semantics, not bytes, can reject it.
        entry = json.loads(registry.read_text())
        entry['entries'][0]['report_sha256'] = sha256(raw).hexdigest()
        registry.write_text(json.dumps(entry))
        proof = await load_gate_proof('1', bound, NOW, registry_path=str(registry))
        assert not proof.available and proof.reason_code == 'GATE_INVALID'

    @pytest.mark.asyncio
    async def test_stale_binding_in_registry_is_rejected(self, tmp_path):
        bound = binding()
        registry = install_registry(tmp_path, bound, build_report(bound))
        proof = await load_gate_proof('1', binding(data_hash='b' * 64), NOW,
                                      registry_path=str(registry))
        assert not proof.available and proof.reason_code == 'GATE_BINDING_STALE'
