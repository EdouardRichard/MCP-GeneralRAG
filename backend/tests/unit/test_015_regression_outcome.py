"""015 Phase 10 T078 (convergence) — the regression group outcome caliber.

The report's regression gate can only fail on a group whose outcome says so, so the
outcome derivation itself is load-bearing. These tests pin its rules:

* a JUnit artifact decides by failures/errors;
* otherwise the group's own published conclusion is compared with its declared
  historical artifact (same conclusion ⇒ no regression; a historically negative
  conclusion that stays negative is NOT a regression);
* latency is environment-sensitive and MUST NOT take part in the comparison;
* an artifact without a conclusion (but with its own exit code) is decided by that
  exit code only when no historical artifact is declared;
* nothing decidable ⇒ ``not_measured``, never a pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
for _candidate in (str(REPO_ROOT), str(REPO_ROOT / "eval"), str(REPO_ROOT / "backend")):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import memory_baseline_support as support  # noqa: E402


def _write(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_junit_decides_by_failures(tmp_path):
    passing = tmp_path / "pass.junit.xml"
    passing.write_text('<testsuite tests="3" failures="0" errors="0"></testsuite>', encoding="utf-8")
    failing = tmp_path / "fail.junit.xml"
    failing.write_text('<testsuite tests="3" failures="1" errors="0"></testsuite>', encoding="utf-8")
    assert support.artifact_outcome(passing, None) == ("passed", "junit tests=3 failures=0 errors=0")
    outcome, reason = support.artifact_outcome(failing, None)
    assert outcome == "failed" and "failures=1" in reason


def test_an_unchanged_published_conclusion_is_no_regression(tmp_path):
    historical = _write(tmp_path / "historical.json", {"enters_default_path": False, "mrr": 0.5})
    current = _write(tmp_path / "current.json", {"enters_default_path": False, "mrr": 0.5})
    assert support.artifact_outcome(current, historical)[0] == "passed"
    # A historically negative conclusion that stays negative is NOT a regression.
    negative = _write(tmp_path / "negative.json", {"three_gate_pass": False})
    same = _write(tmp_path / "same.json", {"three_gate_pass": False})
    assert support.artifact_outcome(same, negative)[0] == "passed"


def test_a_changed_conclusion_fails_even_with_a_zero_exit_code(tmp_path):
    historical = _write(tmp_path / "historical.json", {"all_passed": True, "exit_code": 0})
    current = _write(tmp_path / "current.json", {"all_passed": False, "exit_code": 0})
    outcome, reason = support.artifact_outcome(current, historical)
    assert outcome == "failed" and "all_passed" in reason


def test_latency_never_takes_part_in_the_comparison(tmp_path):
    historical = _write(tmp_path / "historical.json", {"dense_metrics": {
        "recall_at_k": 1.0, "latency_ms": {"p50": 10.0, "p95": 20.0}}})
    current = _write(tmp_path / "current.json", {"dense_metrics": {
        "recall_at_k": 1.0, "latency_ms": {"p50": 900.0, "p95": 1900.0}}})
    outcome, reason = support.artifact_outcome(current, historical)
    assert outcome == "passed", reason


def test_a_real_metric_drift_fails(tmp_path):
    historical = _write(tmp_path / "historical.json", {"dense_metrics": {"mrr": 0.9}})
    current = _write(tmp_path / "current.json", {"dense_metrics": {"mrr": 0.5}})
    assert support.artifact_outcome(current, historical)[0] == "failed"


def test_an_outcome_record_without_history_uses_its_own_exit_code(tmp_path):
    ok = _write(tmp_path / "ok.json", {"group": "x", "exit_code": 0})
    bad = _write(tmp_path / "bad.json", {"group": "x", "exit_code": 2})
    assert support.artifact_outcome(ok, None)[0] == "passed"
    assert support.artifact_outcome(bad, None)[0] == "failed"


def test_a_missing_historical_artifact_is_not_measured(tmp_path):
    current = _write(tmp_path / "current.json", {"dense_metrics": {"mrr": 0.9}})
    outcome, reason = support.artifact_outcome(current, tmp_path / "absent.json")
    assert outcome == "not_measured" and "does not exist" in reason


def test_no_decidable_signal_is_not_measured(tmp_path):
    current = _write(tmp_path / "current.json", {"report_type": "something", "notes": ["x"]})
    assert support.artifact_outcome(current, None)[0] == "not_measured"


def test_regression_groups_from_map_fails_a_drifted_group_without_disposition(tmp_path):
    artifact = _write(tmp_path / "group.json", {"status": "passed"})
    mapping = _write(tmp_path / "map.json", {"groups": [
        {"group": "g1", "runner": "r", "mode": "single_round", "artifact": str(artifact),
         "executed": True, "outcome": "passed", "historical": None, "non_latency_reproducible": False},
        {"group": "g2", "runner": "r", "mode": "single_round", "artifact": str(artifact),
         "executed": True, "outcome": "passed", "historical": None, "non_latency_reproducible": False,
         "outcome_reason": "disposition: accepted corpus drift measured 2026-09-07"},
    ]})
    groups, pending = support.regression_groups_from_map(mapping)
    assert pending == []
    by_group = {group["group"]: group for group in groups}
    assert by_group["g1"]["outcome"] == "failed"
    assert "drifted beyond the 1 % tolerance" in by_group["g1"]["outcome_reason"]
    assert by_group["g2"]["outcome"] == "passed", "a recorded disposition must be honoured"


def test_regression_gate_fails_on_a_not_executed_group(tmp_path):
    block = support.regression_block(groups=[], map_path=tmp_path / "map.json",
                                     not_executed=["013_consolidation_comparison"])
    gate = support.regression_gate(block)
    assert gate["passed"] is False and "013_consolidation_comparison" in gate["detail"]


def test_regression_gate_passes_only_when_every_group_passed():
    block = support.regression_block(groups=[
        {"group": "g1", "runner": "r", "mode": "single_round", "artifact": "a", "outcome": "passed"},
    ], map_path=None)
    assert support.regression_gate(block)["passed"] is True
    block["groups"].append({"group": "g2", "runner": "r", "mode": "single_round", "artifact": "b",
                            "outcome": "not_measured"})
    assert support.regression_gate(block)["passed"] is False
