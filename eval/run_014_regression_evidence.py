"""T103: record real regression evidence for the 014 gate.

Runs the existing suites the 014 contract names (012 E2E, old-client byte
compatibility, 012 reader boundaries, 013 E2E, 014 E2E and 014 contract) and
writes their measured pytest summaries plus the pre-existing 011/012 regression
artefacts into ``eval/regression-evidence-014.json``.  A suite that cannot run in
this environment is recorded as such, never as a pass.
"""

import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
OUT = ROOT / "eval" / "regression-evidence-014.json"

SUITES = [
    ("012_e2e", "tests/integration/test_012_memory_e2e.py"),
    ("012_old_client_compat", "tests/contract/test_012_old_tool_compat.py"),
    ("012_reader_boundaries", "tests/integration/test_012_reader_boundaries.py"),
    ("013_e2e", "tests/integration/test_013_consolidation_e2e.py"),
    ("014_e2e", "tests/integration/test_014_memory_e2e.py"),
    ("014_contract", "tests/contract"),
    ("014_consumption_projection", "tests/integration/test_014_consumption_projection.py"),
    ("014_no_bypass", "tests/integration/test_014_no_bypass.py"),
]
COUNT = re.compile(r"(\d+) (passed|failed|skipped|error|errors)")
TARGET = {"passed": "tests/contract", "014_contract": "tests/contract"}

EXISTING_ARTIFACTS = (
    "eval/011_regression_summary.json",
    "eval/regression_report.json",
    "eval/hard-metrics-014.json",
)


def _counts(summary: str) -> dict:
    counts = {}
    for number, label in COUNT.findall(summary):
        key = "error" if label == "errors" else label
        counts[key] = int(number)
    return counts


def main() -> int:
    results = []
    for name, target in SUITES:
        command = [sys.executable, "-m", "pytest", target, "-q", "--no-header",
                   "-p", "no:cacheprovider"]
        completed = subprocess.run(command, cwd=BACKEND, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", check=False)
        output = (completed.stdout or "") + (completed.stderr or "")
        lines = [line for line in output.splitlines() if COUNT.search(line) and ("passed" in line or "failed" in line)]
        summary = lines[-1].strip() if lines else "no pytest summary line observed"
        results.append({
            "name": name,
            "target": target,
            "exit_code": completed.returncode,
            "summary": summary,
            "counts": _counts(summary),
            "no_regression": completed.returncode == 0,
        })
        print(f"{name}: rc={completed.returncode} :: {summary}")

    artefacts = {}
    for relative in EXISTING_ARTIFACTS:
        path = ROOT / relative
        if path.is_file():
            artefacts[relative] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                   "bytes": path.stat().st_size}

    payload = {
        "schema_version": "014.1",
        "report_type": "014_regression_evidence",
        "generated_at": datetime.now(UTC).isoformat(),
        "command": "python eval/run_014_regression_evidence.py (pytest suites listed below)",
        "suites": results,
        "existing_artefacts": artefacts,
        "note": ("013 E2E needs CONSOLIDATION_ISOLATED_DATABASE and is recorded honestly as "
                 "not executed when that environment is absent; every other suite is measured here."),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
