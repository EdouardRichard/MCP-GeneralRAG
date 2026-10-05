"""Assemble 012 acceptance from completed suites and actual invocation evidence."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
from memory_acceptance_reports import write_report


CRITERIA = {
    "SC-001": ("test_012_memory_e2e", "test_012_aoep_obligations"),
    "SC-002": ("test_012_hard_metrics", "test_012_memory_isolation"),
    "SC-003": ("test_012_hard_metrics", "test_012_distilled_chain", "test_012_provenance_no_bypass"),
    "SC-004": ("test_012_hard_metrics", "test_012_memory_e2e"),
    "SC-005": ("test_012_live_reader", "test_012_reader_boundaries"),
    "SC-006": ("test_012_live_reader", "test_012_memory_recall_observability"),
    "SC-007": ("test_012_memory_failure_visibility", "test_012_persisted_write_loop", "test_012_memory_e2e"),
    "SC-008": ("test_012_memory_projection_equivalence", "test_012_projection_corruption", "test_012_hard_metrics"),
    "SC-009": ("test_012_live_mcp_tools", "test_012_binding_escalation", "test_012_memory_e2e"),
    "SC-010": ("test_012_live_history", "test_012_live_maintenance", "test_salience_service"),
    "SC-011": ("test_memory_policy_defaults", "test_memory_quota_ttl", "test_012_memory_e2e"),
    "SC-012": ("test_012_actual_tool_surface", "test_012_old_tool_compat", "test_012_regression_suite", "test_011_multidomain_acceptance"),
    "SC-013": ("test_012_live_history", "test_012_snapshot_truncation"),
    "SC-014": ("test_012_live_reader", "test_012_reader_boundaries"),
    "SC-015": ("test_salience_service", "test_012_live_reader"),
    "SC-016": ("test_012_aoep_obligations", "test_012_live_governance"),
    "SC-017": ("test_012_memory_e2e", "test_012_write_metadata_boundary"),
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_report(*, suite, trace, host, regression, diagnostics):
    cases = list(ET.parse(suite).getroot().iter("testcase"))
    outcomes = {}
    for case in cases:
        name = case.get("classname", "") + "::" + case.get("name", "")
        outcomes[name] = "failed" if case.find("failure") is not None or case.find("error") is not None else "skipped" if case.find("skipped") is not None else "passed"
    host_data = read_json(host)
    if host_data.get("status") == "passed":
        calls = host_data.get("calls", [])
        required = {"writer:list_tools", "reader:list_tools", "record_memory", "recall_memory", "start_work", "reader:record_memory_rejected"}
        if not required.issubset({call.get("operation") for call in calls}) or any(not call.get("passed") for call in calls):
            raise ValueError("host acceptance requires actual successful calls and reader rejection")
    traces = read_json(trace)["tests"]
    diagnostic_data = read_json(diagnostics) if diagnostics else {}
    criteria = []
    for identifier, modules in CRITERIA.items():
        selected = {name: outcome for name, outcome in outcomes.items() if any(module + "::" in name for module in modules)}
        present = all(any(module + "::" in name for name in selected) for module in modules)
        traced = [test for test in traces if any(module + ".py::" in test["nodeid"] for module in modules) and test.get("measurements")]
        state = "failed" if "failed" in selected.values() else "passed" if present and all(value == "passed" for value in selected.values()) and traced else "not_verified"
        evidence = [str(suite) + "#" + name for name in selected] + [str(trace) + "#" + test["nodeid"] for test in traced]
        if identifier in {"SC-001", "SC-009"} and host_data.get("status") != "passed":
            state = "not_verified" if state != "failed" else state
        if identifier == "SC-012":
            if not regression or not all(read_json(path).get("all_passed", read_json(path).get("hard_constraints", {}).get("all_passed", False)) for path in regression):
                state = "not_verified" if state != "failed" else state
            evidence.extend(map(str, regression))
        if identifier in {"SC-005", "SC-006", "SC-015"}:
            if diagnostic_data.get("status") != "passed":
                state = "not_verified" if state != "failed" else state
            if diagnostics:
                evidence.append(str(diagnostics))
        criteria.append({"id": identifier, "status": state, "evidence": evidence or [str(suite) + "#required evidence absent"]})
    failed = sum(value == "failed" for value in outcomes.values())
    measurements = [measurement for test in traces for measurement in test.get("measurements", [])]
    status = "failed" if failed or any(row["status"] == "failed" for row in criteria) or host_data.get("status") == "failed" else "passed" if all(row["status"] == "passed" for row in criteria) else "incomplete"
    report = {
        "report_type": "012_memory_acceptance", "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "status": status, "suite": {"command": "python -m pytest -vv --tb=short --durations=30",
            "passed": sum(value == "passed" for value in outcomes.values()), "failed": failed,
            "skipped": sum(value == "skipped" for value in outcomes.values()), "evidence": str(suite)},
        "host": {key: host_data[key] for key in ("name", "workspace", "status", "evidence")},
        "success_criteria": criteria, "measurements": measurements, "regression_reports": list(map(str, regression)),
    }
    Draft202012Validator(read_json(ROOT / "specs/012-memory-foundation-write-read-loop/contracts/acceptance-report.schema.json")).validate(report)
    return report


def main():
    parser = argparse.ArgumentParser()
    for name in ("suite", "trace", "host", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--regression", nargs="+", type=Path, default=[])
    parser.add_argument("--diagnostics", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; historical evidence must not be overwritten")
    report = build_report(suite=args.suite, trace=args.trace, host=args.host,
                          regression=args.regression, diagnostics=args.diagnostics)
    write_report(args.output, report)
    print(json.dumps({"status": report["status"], "suite": report["suite"], "criteria": {row["id"]: row["status"] for row in report["success_criteria"]}}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
