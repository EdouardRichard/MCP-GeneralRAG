import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[3]


def report_module():
    spec = importlib.util.spec_from_file_location("memory_final_report", ROOT / "eval/run_memory_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inputs(tmp_path):
    suite = tmp_path / "suite.xml"
    suite.write_text('<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
                     '<testcase classname="tests.integration.test_012_memory_e2e" name="test_e2e_hard_anchor_roundtrip"/>'
                     '</testsuite></testsuites>', encoding="utf-8")
    trace = tmp_path / "trace.json"
    trace.write_text(json.dumps({"tests": []}), encoding="utf-8")
    host = tmp_path / "host.json"
    host.write_text(json.dumps({"name": "DSH", "workspace": "temp", "status": "not_verified", "evidence": []}), encoding="utf-8")
    return suite, trace, host


def test_partial_suite_and_missing_measurements_cannot_claim_acceptance(tmp_path):
    module = report_module()
    suite, trace, host = inputs(tmp_path)
    report = module.build_report(suite=suite, trace=trace, host=host, regression=[], diagnostics=None)
    assert report["status"] == "incomplete"
    assert report["suite"]["passed"] == 1
    assert len({row["id"] for row in report["success_criteria"]}) == 17
    assert all(row["status"] == "not_verified" for row in report["success_criteria"])


def test_failed_suite_never_becomes_passed(tmp_path):
    module = report_module()
    suite, trace, host = inputs(tmp_path)
    suite.write_text('<testsuites><testsuite tests="1" failures="1" errors="0" skipped="0">'
                     '<testcase classname="tests.integration.test_012_memory_e2e" name="test_e2e_hard_anchor_roundtrip">'
                     '<failure message="anchor mismatch"/></testcase></testsuite></testsuites>', encoding="utf-8")
    report = module.build_report(suite=suite, trace=trace, host=host, regression=[], diagnostics=None)
    assert report["status"] == "failed"
    assert report["suite"]["failed"] == 1


def test_report_rejects_host_claim_without_actual_calls(tmp_path):
    module = report_module()
    suite, trace, host = inputs(tmp_path)
    host.write_text(json.dumps({"name": "DSH", "workspace": "temp", "status": "passed", "evidence": ["HTTP 200"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="host.*calls"):
        module.build_report(suite=suite, trace=trace, host=host, regression=[], diagnostics=None)


def test_invocation_evidence_keeps_request_ids_paths_and_stable_fingerprints():
    spec = importlib.util.spec_from_file_location("memory_pytest_evidence", ROOT / "eval/memory_pytest_evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = {"request_id": "actual-request", "package_fingerprint": "package-sha",
              "completion_status": "partial", "counts": {"characters": 220}, "failed_paths": ["dense"]}
    measurement = module.observe_result("start_work", {"scope_ref": "7"}, result, elapsed=.25)
    assert measurement["scope_ids"] == [7]
    assert measurement["request_ids"] == ["actual-request"]
    assert measurement["failed_paths"] == ["dense"]
    assert measurement["fingerprints"] == {"package": "package-sha"}
    assert measurement["paths"]["elapsed_seconds"] == .25
    assert measurement["paths"]["counts"] == {"characters": 220}


def test_invocation_evidence_reads_failure_paths_from_public_envelopes():
    spec = importlib.util.spec_from_file_location("memory_pytest_evidence", ROOT / "eval/memory_pytest_evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recall = module.observe_result("recall", {"scope_ref": ["7"]}, {
        "completion_status": "partial", "memory_notice": {"failed_paths": ["dense_unavailable"]}}, elapsed=.1)
    package = module.observe_result("start_work", {"scope_ref": "7"}, {
        "counts": {"failed_paths": ["files"]}}, elapsed=.1)
    assert recall["failed_paths"] == ["dense_unavailable"]
    assert package["failed_paths"] == ["files"]


def test_legacy_regression_criterion_uses_completed_suites_without_memory_traces(tmp_path):
    module = report_module()
    suite, trace, host = inputs(tmp_path)
    modules = module.CRITERIA["SC-012"]
    suite.write_text('<testsuites><testsuite>' + ''.join(
        f'<testcase classname="tests.integration.{name}" name="test_real_compatibility"/>'
        for name in modules) + '</testsuite></testsuites>', encoding="utf-8")
    regression = tmp_path / "legacy.json"
    regression.write_text(json.dumps({"all_passed": True}), encoding="utf-8")
    report = module.build_report(suite=suite, trace=trace, host=host,
                                 regression=[regression], diagnostics=None)
    criterion = next(row for row in report["success_criteria"] if row["id"] == "SC-012")
    assert criterion["status"] == "passed"
    regression.write_text(json.dumps({"all_passed": False}), encoding="utf-8")
    report = module.build_report(suite=suite, trace=trace, host=host,
                                 regression=[regression], diagnostics=None)
    assert next(row for row in report["success_criteria"] if row["id"] == "SC-012")["status"] != "passed"


def test_write_observation_measures_metadata_without_retaining_user_values():
    spec = importlib.util.spec_from_file_location("memory_pytest_evidence", ROOT / "eval/memory_pytest_evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parameters = {"scope_id": 7, "provenance": "soft", "content": "private content",
                  "inference_meta": {"source": "private source", "confidence": .8, "model_version": "local",
                                     "time": "2026-10-05T00:00:00Z", "supporting_evidence": []}}
    result = {"request_id": "real-id", "status": "active",
              "provenance_validation": {"provenance": "soft", "validated": True, "attributions": []}}
    observation = module.observe_result("record", parameters, result, elapsed=.1)
    assert observation["paths"]["write_checks"] == {"provenance": True, "soft_metadata": True}
    assert "private source" not in json.dumps(observation)
    assert "private content" not in json.dumps(observation)


def test_acceptance_write_rates_require_observations_and_count_each_failure():
    module = report_module()
    measurements = [
        {"scenario": "record", "scope_ids": [7], "request_ids": ["a"], "status": "active",
         "failed_paths": [], "fingerprints": {}, "paths": {"write_checks": {"provenance": True, "hard_attribution": True}}},
        {"scenario": "record", "scope_ids": [7], "request_ids": ["b"], "status": "active",
         "failed_paths": [], "fingerprints": {}, "paths": {"write_checks": {"provenance": True, "hard_attribution": False}}},
    ]
    rates = module.write_rates(measurements)
    assert rates["paths"]["hard_attribution"] == {"passed": 1, "total": 2, "rate": .5}
    assert rates["paths"]["soft_metadata"] == {"passed": 0, "total": 0, "rate": None}
    assert rates["status"] == "failed"
    assert rates["request_ids"] == ["a", "b"]

