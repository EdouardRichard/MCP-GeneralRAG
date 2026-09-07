"""011 domain-baseline report schema contract tests (T011, VS-04).

Validates the two domain-baseline report contract schemas
(generic-domain-baseline-report.schema.json / legal-domain-baseline-report.schema.json)
plus the shared domain-baseline-common.schema.json definitions. Asserts the
schema shape (dense/hybrid metric blocks, P50/P95 latency, per-query entries
with domain_scope + expected_heading, hard-constraint block, reproducibility)
and the non-binding-anchor semantics (no enters_default_path field, FR-010).
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTRACTS = _REPO_ROOT / "specs" / "011-generic-domain-evaluation" / "contracts"


def _load(name: str) -> dict:
    with open(_CONTRACTS / name, "r", encoding="utf-8") as f:
        return json.load(f)


def _inline_common(schema: dict, common: dict) -> dict:
    """Inline the shared $defs so $ref resolves against local #/$defs."""
    merged = json.loads(json.dumps(schema))
    merged.setdefault("$defs", {})
    merged["$defs"].update(common.get("$defs", {}))
    s = json.dumps(merged)
    s = s.replace("./domain-baseline-common.schema.json#/$defs/", "#/$defs/")
    return json.loads(s)


@pytest.fixture(scope="module")
def common_schema() -> dict:
    return _load("domain-baseline-common.schema.json")


@pytest.fixture(scope="module")
def generic_schema(common_schema) -> dict:
    return _inline_common(_load("generic-domain-baseline-report.schema.json"), common_schema)


@pytest.fixture(scope="module")
def legal_schema(common_schema) -> dict:
    return _inline_common(_load("legal-domain-baseline-report.schema.json"), common_schema)


def _metric_block() -> dict:
    return {"mean": 0.9, "min": 0.5, "max": 1.0}


def _latency_block() -> dict:
    return {"p50": 100.0, "p95": 200.0, "mean": 120.0}


def _query_entry(i: int) -> dict:
    return {
        "query_index": i,
        "query": f"query {i}",
        "domain_scope": ["personal-eval-rag-notes"],
        "expected_heading": "嵌入模型选型笔记",
        "format": "markdown",
        "dense_rank": 1,
        "hybrid_rank": 1,
        "dense_score": 0.9,
        "hybrid_dense_score": 0.9,
        "hybrid_sparse_score": 0.8,
        "hybrid_fused_score": 0.85,
        "hybrid_rerank_score": 0.95,
        "rank_improved": False,
    }


def _base_report(report_type: str) -> dict:
    return {
        "report_type": report_type,
        "generated_at": "2026-09-07T12:00:00Z",
        "config": {
            "domain_key": "personal",
            "embedding_model": "BAAI/bge-m3",
            "reranker_model": "BAAI/bge-reranker-v2-m3",
            "dataset_path": "eval/generic_domain_eval_dataset.json",
            "num_queries": 13,
            "retrieval_modes": ["dense", "hybrid"],
        },
        "dense_metrics": {
            "recall_at_k": _metric_block(),
            "mrr": _metric_block(),
            "ndcg_at_k": _metric_block(),
            "latency_ms": _latency_block(),
        },
        "hybrid_metrics": {
            "recall_at_k": _metric_block(),
            "mrr": _metric_block(),
            "ndcg_at_k": _metric_block(),
            "latency_ms": _latency_block(),
        },
        "deltas": {
            "mrr_mean_delta": 0.0,
            "ndcg_mean_delta": 0.0,
            "recall_mean_delta": 0.0,
            "latency_p50_delta_ms": 0.0,
            "latency_p95_delta_ms": 0.0,
        },
        "hard_constraints": {
            "cross_domain_leakage_events": 0,
            "schema_validity_rate": 1.0,
            "source_locatability_rate": 1.0,
            "all_passed": True,
        },
        "per_query_comparison": [_query_entry(0)],
        "reproducibility": {
            "non_latency_reproducible": True,
            "tolerance": 0.01,
            "checks": [],
        },
    }


class TestSchemaValidity:
    def test_common_schema_valid(self, common_schema):
        jsonschema.Draft202012Validator.check_schema(common_schema)

    def test_generic_schema_valid(self, generic_schema):
        jsonschema.Draft202012Validator.check_schema(generic_schema)

    def test_legal_schema_valid(self, legal_schema):
        jsonschema.Draft202012Validator.check_schema(legal_schema)


class TestGenericReportShape:
    def test_valid_generic_report(self, generic_schema):
        jsonschema.validate(_base_report("generic_domain_baseline"), generic_schema)

    def test_generic_rejects_enters_default_path(self, generic_schema):
        """FR-010: the domain baseline is a non-binding anchor — no
        enters_default_path field is allowed."""
        report = _base_report("generic_domain_baseline")
        report["enters_default_path"] = False
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(report, generic_schema)

    def test_generic_rejects_wrong_report_type(self, generic_schema):
        report = _base_report("legal_domain_baseline")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(report, generic_schema)


class TestLegalReportShape:
    def test_valid_legal_report(self, legal_schema):
        report = _base_report("legal_domain_baseline")
        report["cross_reference_benefit"] = {
            "baseline_metrics": {
                "recall_at_k": _metric_block(),
                "mrr": _metric_block(),
                "ndcg_at_k": _metric_block(),
            },
            "graph_metrics": {
                "recall_at_k": _metric_block(),
                "mrr": _metric_block(),
                "ndcg_at_k": _metric_block(),
            },
            "mrr_improvement_pct": 5.0,
            "ndcg_improvement_pct": 4.0,
            "recall_non_decreasing": True,
            "three_gate_pass": True,
            "vocabulary_disposition": "enabled",
        }
        jsonschema.validate(report, legal_schema)

    def test_legal_requires_benefit_block(self, legal_schema):
        """Legal report schema REQUIRES cross_reference_benefit (FR-011)."""
        report = _base_report("legal_domain_baseline")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(report, legal_schema)

    def test_legal_benefit_disposition_enum(self, legal_schema):
        report = _base_report("legal_domain_baseline")
        report["cross_reference_benefit"] = {
            "baseline_metrics": {
                "recall_at_k": _metric_block(), "mrr": _metric_block(),
                "ndcg_at_k": _metric_block(),
            },
            "graph_metrics": {
                "recall_at_k": _metric_block(), "mrr": _metric_block(),
                "ndcg_at_k": _metric_block(),
            },
            "mrr_improvement_pct": 1.0,
            "ndcg_improvement_pct": 1.0,
            "recall_non_decreasing": True,
            "three_gate_pass": False,
            "vocabulary_disposition": "kept_empty_r11",
        }
        jsonschema.validate(report, legal_schema)

        report["cross_reference_benefit"]["vocabulary_disposition"] = "bogus"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(report, legal_schema)


class TestDomainQueryEntry:
    def test_entry_uses_domain_scope_and_heading(self, generic_schema):
        """The per-query entry addresses domain_scope + expected_heading
        (not the legacy project_scope + expected_evidence_ids)."""
        entry_def = generic_schema["$defs"]["domainQueryEntry"]
        props = entry_def["properties"]
        assert "domain_scope" in props
        assert "expected_heading" in props
        assert "project_scope" not in props
        assert "expected_evidence_ids" not in props

    def test_entry_requires_domain_scope_and_heading(self, generic_schema):
        required = set(generic_schema["$defs"]["domainQueryEntry"]["required"])
        assert {"domain_scope", "expected_heading", "query_index", "query"} <= required
