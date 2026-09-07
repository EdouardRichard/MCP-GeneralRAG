"""011 domain eval-dataset schema contract tests (T010, VS-03).

Validates the two fixed domain evaluation datasets
(generic_domain_eval_dataset.json / legal_domain_eval_dataset.json) against
contracts/domain-eval-dataset.schema.json, asserts the coverage structure
(FR-005/FR-006), and verifies the existing 001-006/010 datasets are
byte-identical (SC-001 zero-destruction discipline).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTRACTS = _REPO_ROOT / "specs" / "011-generic-domain-evaluation" / "contracts"
_EVAL_DIR = _REPO_ROOT / "eval"

# SC-001: existing datasets must stay byte-identical (recorded at 011 planning).
_EXISTING_DATASET_SHA256 = {
    "eval_dataset.json":
        "f43841737f246791a16728c784ec209c05f92f352fcd707ae96af52c22c1ebf1",
    "agentic_eval_dataset.json":
        "4e2b33bed8639680fb4b2c2c5d7ca413ee171ccafd12ef620eff20d14462afe6",
    "cross_reference_eval_dataset.json":
        "7d26e6a3a9c09aaa6f94f40e7f93fb197662565f86dabfcc10d97f0954c7bff5",
}


def _load_dataset(name: str) -> list:
    with open(_EVAL_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def dataset_schema() -> dict:
    with open(_CONTRACTS / "domain-eval-dataset.schema.json", "r", encoding="utf-8") as f:
        return json.load(f)


class TestDatasetSchemaValidity:
    def test_schema_is_valid_json_schema(self, dataset_schema):
        jsonschema.Draft202012Validator.check_schema(dataset_schema)

    def test_generic_dataset_validates(self, dataset_schema):
        dataset = _load_dataset("generic_domain_eval_dataset.json")
        jsonschema.validate(dataset, dataset_schema)

    def test_legal_dataset_validates(self, dataset_schema):
        dataset = _load_dataset("legal_domain_eval_dataset.json")
        jsonschema.validate(dataset, dataset_schema)


class TestGenericDomainCoverage:
    def test_min_ten_queries(self):
        assert len(_load_dataset("generic_domain_eval_dataset.json")) >= 10

    def test_four_formats_each_at_least_two(self):
        dataset = _load_dataset("generic_domain_eval_dataset.json")
        by_format: dict[str, int] = {}
        for e in dataset:
            by_format[e["format"]] = by_format.get(e["format"], 0) + 1
        for fmt in ("markdown", "txt", "html", "csv"):
            assert by_format.get(fmt, 0) >= 2, f"format {fmt} under-covered"

    def test_at_least_two_chinese(self):
        dataset = _load_dataset("generic_domain_eval_dataset.json")
        assert sum(1 for e in dataset if e["language"] == "zh") >= 2

    def test_natural_and_structural_per_format(self):
        """Each of the four formats has >=1 natural-language and >=1 structural
        locating query (FR-006). The query type is recorded in review_notes
        (structural entries are tagged "结构定位查询"; natural entries are
        tagged "自然语言查询")."""
        dataset = _load_dataset("generic_domain_eval_dataset.json")
        by_format: dict[str, list] = {}
        for e in dataset:
            by_format.setdefault(e["format"], []).append(e)
        for fmt, entries in by_format.items():
            structural = [
                e for e in entries
                if "结构定位" in e["_meta"]["review_notes"]
            ]
            natural = [
                e for e in entries
                if "自然语言" in e["_meta"]["review_notes"]
            ]
            assert structural, f"{fmt} has no structural-locating query"
            assert natural, f"{fmt} has no natural-language query"

    def test_every_entry_has_review_record(self):
        dataset = _load_dataset("generic_domain_eval_dataset.json")
        for e in dataset:
            assert e["_meta"]["review_status"] == "reviewed"
            assert e["_meta"].get("review_notes")
            assert e["_meta"].get("grounded_source")


class TestLegalDomainCoverage:
    def test_min_ten_queries(self):
        assert len(_load_dataset("legal_domain_eval_dataset.json")) >= 10

    def test_clause_structure_subset_at_least_four(self):
        dataset = _load_dataset("legal_domain_eval_dataset.json")
        clause = [e for e in dataset if not e.get("is_structural_benefit")]
        assert len(clause) >= 4
        # Clause queries are carried by Word/PDF corpora (FR-006).
        assert all(e["format"] in ("word", "pdf") for e in clause)

    def test_cross_reference_benefit_subset_at_least_six(self):
        dataset = _load_dataset("legal_domain_eval_dataset.json")
        benefit = [e for e in dataset if e.get("is_structural_benefit")]
        assert len(benefit) >= 6
        # Benefit queries are carried by markdown cross-reference corpus.
        assert all(e["format"] == "markdown" for e in benefit)
        # >=1 Chinese clause-citation query (all benefit queries are zh here).
        assert any(e["language"] == "zh" for e in benefit)

    def test_at_least_two_chinese(self):
        dataset = _load_dataset("legal_domain_eval_dataset.json")
        assert sum(1 for e in dataset if e["language"] == "zh") >= 2

    def test_every_entry_has_review_record(self):
        dataset = _load_dataset("legal_domain_eval_dataset.json")
        for e in dataset:
            assert e["_meta"]["review_status"] == "reviewed"
            assert e["_meta"].get("review_notes")
            assert e["_meta"].get("grounded_source")


class TestExistingDatasetsUntouched:
    def test_existing_datasets_byte_identical(self):
        """SC-001: the 011 datasets are independent files; the existing
        eval_dataset.json / agentic_eval_dataset.json /
        cross_reference_eval_dataset.json stay byte-for-byte unchanged."""
        for name, expected_sha in _EXISTING_DATASET_SHA256.items():
            data = (_EVAL_DIR / name).read_bytes()
            actual_sha = hashlib.sha256(data).hexdigest()
            assert actual_sha == expected_sha, (
                f"{name} changed — 011 must not modify existing datasets"
            )
