import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[3]


def reports_module():
    spec = importlib.util.spec_from_file_location("memory_acceptance_reports", ROOT / "eval/memory_acceptance_reports.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_writer_never_overwrites_existing_evidence(tmp_path):
    reports = reports_module()
    target = tmp_path / "evidence.json"
    target.write_text("historical evidence", encoding="utf-8")
    with pytest.raises(FileExistsError):
        reports.write_report(target, {"new": True})
    assert target.read_text(encoding="utf-8") == "historical evidence"


def test_non_latency_regression_comparison_rejects_changed_quality():
    reports = reports_module()
    before = {"dense_metrics": {"mrr": {"mean": .8}, "latency_ms": {"p95": 50}}}
    after = {"dense_metrics": {"mrr": {"mean": .7}, "latency_ms": {"p95": 30}}}
    assert not reports.compare_quality(before, after)["passed"]
    after["dense_metrics"]["mrr"]["mean"] = .8
    assert reports.compare_quality(before, after)["passed"]


@pytest.mark.parametrize("historical,fresh", [
    ("generic_domain_baseline_report.json", "012_generic_domain_report.json"),
    ("legal_domain_baseline_report.json", "012_legal_domain_report.json"),
])
def test_actual_domain_reports_preserve_non_latency_quality(historical, fresh):
    import json
    reports = reports_module()
    baseline = json.loads((ROOT / "eval" / historical).read_text(encoding="utf-8"))
    current = json.loads((ROOT / "eval/runs/012-20261005-final-regression-a" / fresh).read_text(encoding="utf-8"))
    assert current["hard_constraints"]["all_passed"]
    comparison = reports.compare_quality(baseline, current)
    assert comparison["passed"], comparison
