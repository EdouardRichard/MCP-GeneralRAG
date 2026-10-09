"""015 T025 (AOEP block only) — assemble the report's AOEP obligation block.

Scope of this file **right now**: the AOEP obligation block that the 015 report
contract requires (``$defs/aoepBlock`` + ``$defs/invariantScore`` in
``specs/015-memory-evaluation-governance/contracts/memory-benchmark-common.schema.json``).
The report/hard-metric assembly parts of T027 land in this same module later and
must not be restructured around what is added here.

Input: the per-case results the **runner** produced — ``aoep-cases.json`` as
written by ``backend/tests/integration/memory_eval_evidence.py`` (T009) when
``MEMORY_EVAL_EVIDENCE_DIR`` is configured. Values are never hand-transcribed:
every count below is derived from that file, so an unexecuted case is simply
absent (and cannot be counted as a pass); a case whose status is ``failed`` makes
the report status ``failed`` and blocks finalization, exposed as a returned flag
and as ``AoepFinalizationBlocked`` rather than printed.

Zero-denominator discipline (FR-024/SC-011): when no case result exists at all the
score is ``rate = null`` / ``value = "not_measurable"`` with a non-empty
``reason`` — never ``0`` and never ``1``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for _candidate in (str(REPO_ROOT), str(REPO_ROOT / "backend")):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from tests.memory_eval_datasets import AOEP_INVARIANTS  # noqa: E402  (shared 015 truth)

AOEP_CASES_NAME = "aoep-cases.json"
MIN_CASES_PER_INVARIANT = 2
ZERO_DENOMINATOR_REASON = "a zero denominator is not a measured zero"
CASE_STATUSES = ("passed", "failed", "not_measurable")


class AoepFinalizationBlocked(RuntimeError):
    """Raised by :func:`assert_aoep_finalizable` when the AOEP block blocks finalization."""


@dataclass(frozen=True)
class AoepFinalizationVerdict:
    """Whether the AOEP obligation results permit a ``passed`` report."""

    report_status: str
    effective_status: str
    blocked: bool
    all_passed: bool
    failed_cases: tuple[str, ...]
    not_measurable_cases: tuple[str, ...]
    under_covered_invariants: tuple[str, ...]
    reasons: tuple[str, ...]


def load_aoep_cases(cases_path: str | Path) -> dict[str, Any]:
    """Load the runner-produced ``aoep-cases.json`` envelope (no interpretation)."""
    document = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("cases"), list):
        raise ValueError(f"{cases_path} is not a runner-produced AOEP case document")
    return document


def _cases(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    cases = list(document.get("cases") or [])
    for entry in cases:
        if not isinstance(entry, dict):
            raise ValueError("AOEP case entries must be objects")
        if entry.get("invariant") not in AOEP_INVARIANTS:
            raise ValueError(f"unknown AOEP invariant {entry.get('invariant')!r}")
        if entry.get("status") not in CASE_STATUSES:
            raise ValueError(f"unknown AOEP case status {entry.get('status')!r}")
    return cases


def by_invariant(cases: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """``{invariant: {passed, total, failed, not_measurable}}`` for exactly the five keys."""
    counts = {name: {"passed": 0, "total": 0, "failed": 0, "not_measurable": 0} for name in AOEP_INVARIANTS}
    for entry in cases:
        bucket = counts[entry["invariant"]]
        bucket["total"] += 1
        bucket[str(entry["status"])] += 1
    return counts


def build_aoep_block(cases_path: str | Path) -> dict[str, Any]:
    """Build the report ``aoep`` block from the runner's per-case results.

    Returns ``{"by_invariant": {...}, "score": rateBlock, "all_passed": bool}`` with
    exactly the five invariant keys (no embedded ``cases[]``: per-case detail belongs
    to ``per_case.aoep[]``, whose entries carry their own ``invariant``).
    """
    return by_invariant_block(_cases(load_aoep_cases(cases_path)))


def by_invariant_block(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``aoep`` block for an already-loaded case list (the single assembly rule)."""
    counts = by_invariant(cases)
    passed = sum(bucket["passed"] for bucket in counts.values())
    total = sum(bucket["total"] for bucket in counts.values())
    if total == 0:
        score: dict[str, Any] = {
            "passed": 0,
            "total": 0,
            "rate": None,
            "value": "not_measurable",
            "reason": f"{ZERO_DENOMINATOR_REASON} (no AOEP case result was produced)",
        }
    else:
        rate = passed / total
        score = {"passed": passed, "total": total, "rate": rate, "value": rate}
    all_passed = all(bucket["passed"] >= MIN_CASES_PER_INVARIANT and bucket["failed"] == 0
                     and bucket["not_measurable"] == 0 for bucket in counts.values())
    return {"by_invariant": counts, "score": score, "all_passed": all_passed}


def aoep_blocks_finalization(report_status: str, aoep_block: Mapping[str, Any],
                             cases: Sequence[Mapping[str, Any]] = ()) -> AoepFinalizationVerdict:
    """Decide whether the AOEP obligation results block a ``passed`` report.

    A single ``failed`` case forces ``report_status = "failed"`` and blocks
    finalization; a ``not_measurable`` case or an under-covered invariant keeps the
    report out of ``passed`` (``incomplete``) but is never reported as ``0``/passed.
    """
    failed_cases = tuple(sorted(str(entry.get("case_id")) for entry in cases if entry.get("status") == "failed"))
    not_measurable = tuple(sorted(
        f"{entry.get('case_id')} ({entry.get('not_measurable_reason') or 'no reason recorded'})"
        for entry in cases if entry.get("status") == "not_measurable"))
    counts = aoep_block.get("by_invariant") or {}
    under_covered = tuple(sorted(
        f"{name} ({counts.get(name, {}).get('passed', 0)}/{MIN_CASES_PER_INVARIANT} passed)"
        for name in AOEP_INVARIANTS if counts.get(name, {}).get("passed", 0) < MIN_CASES_PER_INVARIANT))
    all_passed = bool(aoep_block.get("all_passed"))
    reasons: list[str] = []
    if failed_cases:
        reasons.append(f"AOEP cases failed and must block finalization: {list(failed_cases)}")
    if not_measurable:
        reasons.append(f"AOEP cases are not measurable: {list(not_measurable)}")
    if under_covered:
        reasons.append(f"AOEP invariants below the {MIN_CASES_PER_INVARIANT}-case minimum: {list(under_covered)}")
    if not all_passed and not reasons:
        reasons.append("aoep.all_passed is false")
    blocked = bool(failed_cases) or not all_passed
    if failed_cases or report_status == "failed":
        effective = "failed"
    elif blocked:
        effective = "incomplete"
    else:
        effective = report_status
    return AoepFinalizationVerdict(
        report_status=report_status, effective_status=effective, blocked=blocked, all_passed=all_passed,
        failed_cases=failed_cases, not_measurable_cases=not_measurable,
        under_covered_invariants=under_covered, reasons=tuple(reasons))


def assert_aoep_finalizable(report_status: str, aoep_block: Mapping[str, Any],
                            cases: Sequence[Mapping[str, Any]] = ()) -> AoepFinalizationVerdict:
    """Same decision as :func:`aoep_blocks_finalization`, raising when blocked."""
    verdict = aoep_blocks_finalization(report_status, aoep_block, cases)
    if verdict.blocked:
        raise AoepFinalizationBlocked(
            f"AOEP obligations block finalization (effective status {verdict.effective_status}): "
            + "; ".join(verdict.reasons))
    return verdict


def aoep_verdict_from_path(cases_path: str | Path, *, report_status: str = "incomplete") -> AoepFinalizationVerdict:
    """Convenience: build the block from a file and decide the finalization verdict."""
    cases = _cases(load_aoep_cases(cases_path))
    return aoep_blocks_finalization(report_status, by_invariant_block(cases), cases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble and inspect the 015 AOEP obligation block.")
    parser.add_argument("cases", nargs="?", default=None, help="path to the runner-produced aoep-cases.json")
    parser.add_argument("--report-status", default="incomplete")
    arguments = parser.parse_args(argv)
    if not arguments.cases:
        parser.error("a path to aoep-cases.json is required")
    block = build_aoep_block(arguments.cases)
    verdict = aoep_verdict_from_path(arguments.cases, report_status=arguments.report_status)
    print(json.dumps({"aoep": block, "verdict": verdict.__dict__}, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if verdict.blocked else 0


if __name__ == "__main__":  # pragma: no cover - debug entry point
    raise SystemExit(main())
