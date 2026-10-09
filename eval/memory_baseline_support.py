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


    return 1 if verdict.blocked else 0


# ===========================================================================
# 015 T027 — report assembly helpers (the report/hard-metric stream)
# ===========================================================================
#
# Everything below is *additive* to the AOEP block above: the T025 functions and
# constants are never renamed or restructured. This half of the module is the
# single assembly rule for the report, so the runner (T028) and the contract
# test (T029) both validate the same artifact the report actually ships.
#
# Disciplines encoded here, not documented elsewhere:
#
# * ``$defs`` merge validation (contracts/README.md §1): load the report schema,
#   load ``memory-benchmark-common.schema.json``, ``$defs.update``, rewrite the
#   relative ``$ref`` strings, validate with Draft 2020-12. No new registry.
# * two zero-denominator encodings: ratio blocks (``total == 0``) become
#   ``rate = null`` / ``value = "not_measurable"`` + a non-empty ``reason``;
#   path/axis blocks (``examined == 0``) become ``state``/``value`` =
#   ``"not_measurable"`` (+ ``rate = null`` where the block has a rate) + reason.
# * a skip is never a pass: ``all_passed`` is derived from the sub-blocks, never
#   written independently, and safety-class calibers keep zero tolerance.

import hashlib
import os
import platform
import socket
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

#: Feature-frozen identity (T002/T036): the run id of this feature's run dir.
RUN_ID = os.environ.get("RUN_ID") or "015-20261009205637"
RUN_ID_PREFIX = "015"
RUN_ID_PATTERN = r"^015-\d{14}$"

REPORT_SCHEMA_NAME = "memory-baseline-report.schema.json"
COMMON_SCHEMA_NAME = "memory-benchmark-common.schema.json"
REPORT_TYPE = "015_memory_baseline"
REPORT_SCHEMA_VERSION = "015.1"
TRACKED_REPORT_NAME = "memory_baseline_report.json"
RATE_TOLERANCE = 0.01
#: 013's relative-gain threshold; the benefit watermark is *record only* here.
BENEFIT_THRESHOLD = 0.03

#: The six MCP tools T031 measures, in the contract's frozen order.
TOOLS_CHECKED = (
    "search_knowledge",
    "get_evidence",
    "list_knowledge_domains",
    "recall_memory",
    "start_work",
    "record_memory",
)

#: The four cross-domain paths (Constitution hard constraint 1 / FR-028).
LEAK_PATHS = ("event_log", "relation", "vector", "file")
#: FR-057 projections: the five consumable views plus the field projection.
PROJECTION_VIEWS = ("relation", "dense", "links", "summary", "file", "salience")
#: FR-058 governance axes, in the reducer's own order.
METADATA_AXES = ("authority", "scope", "mutability", "provenance", "recoverability", "actionability")
#: Map axis name -> the governance column the reducer/DB actually stores.
AXIS_COLUMNS = {
    "authority": "authority",
    "scope": "scope_meta",
    "mutability": "mutability",
    "provenance": "provenance_meta",
    "recoverability": "recoverability",
    "actionability": "actionability",
}
#: FR-032 quarantine-exclusion surfaces, each with its own denominator.
QUARANTINE_SURFACES = ("default_recall", "consolidation_window", "attachment", "working_set", "control_surface")

GOAL_STATEMENTS = {
    1: "MCP 记忆工具可用且旧三工具零破坏",
    2: "硬记忆锚定率 100% + 软/distilled provenance 完备率 100%",
    3: "跨域记忆串库 = 0",
    4: "巩固受益 ≥3%",
    5: "跨会话续接达标",
    6: "记忆投毒 E2E 全过",
    7: "既有评测全集无回归",
}


class BaselineBlocked(RuntimeError):
    """Raised when the 015 contract itself blocks producing a report."""


# --------------------------------------------------------------------------- #
# schema loading / merged-$defs validation (contracts/README.md §1)
# --------------------------------------------------------------------------- #


def contracts_dir() -> Path:
    return REPO_ROOT / "specs" / "015-memory-evaluation-governance" / "contracts"


def load_contract_schema(name: str) -> dict[str, Any]:
    return json.loads((contracts_dir() / name).read_text(encoding="utf-8"))


def merged_report_schema(name: str = REPORT_SCHEMA_NAME) -> dict[str, Any]:
    """Report schema with the shared ``$defs`` inlined, per contracts/README.md §1.

    No registry is introduced: the common file's ``$defs`` are merged into the
    report schema and its relative ``$ref`` prefix is rewritten to ``#/$defs/``.
    """
    schema = load_contract_schema(name)
    if name == COMMON_SCHEMA_NAME:
        return schema
    common = load_contract_schema(COMMON_SCHEMA_NAME)
    merged = dict(schema)
    defs = dict(schema.get("$defs", {}))
    defs.update(common.get("$defs", {}))
    merged["$defs"] = defs
    text = json.dumps(merged, ensure_ascii=False)
    text = text.replace(f"./{COMMON_SCHEMA_NAME}#/$defs/", "#/$defs/")
    return json.loads(text)


def report_validator(name: str = REPORT_SCHEMA_NAME):
    from jsonschema import Draft202012Validator

    return Draft202012Validator(merged_report_schema(name))


def validate_report(report: Mapping[str, Any]) -> None:
    """Raise ``jsonschema.ValidationError`` when the report is not schema-legal."""
    report_validator().validate(dict(report))


# --------------------------------------------------------------------------- #
# the two zero-denominator encodings
# --------------------------------------------------------------------------- #


def rate_block(passed: int, total: int, reason: str | None = None) -> dict[str, Any]:
    """Ratio encoding: ``total == 0`` is not-measurable, never ``0`` and never ``1``.

    ``passed`` is always the integer pass count (014 caliber), never a boolean.
    """
    if total == 0:
        return {"passed": 0, "total": 0, "rate": None, "value": "not_measurable",
                "reason": reason or ZERO_DENOMINATOR_REASON}
    return {"passed": int(passed), "total": int(total), "rate": passed / total, "value": passed / total}


def leak_path(examined: int, leaks: int, reason: str | None = None, **extra: Any) -> dict[str, Any]:
    """``leakPath`` encoding: ``examined == 0`` is not-measurable, never a pass."""
    block = {"examined": int(examined), "leaks": int(leaks)}
    if examined == 0:
        block.update({"value": None, "state": "not_measurable",
                      "reason": reason or ZERO_DENOMINATOR_REASON})
    else:
        block.update({"value": int(leaks), "state": "measured"})
    block.update(extra)
    return block


def count_block(examined: int, occurrences: int, reason: str | None = None, **extra: Any) -> dict[str, Any]:
    """``countBlock`` encoding: ``examined == 0`` is not-measurable."""
    block = {"examined": int(examined), "occurrences": int(occurrences)}
    if examined == 0:
        block.update({"state": "not_measurable", "reason": reason or ZERO_DENOMINATOR_REASON})
    else:
        block.update({"state": "measured"})
    block.update(extra)
    return block


def rate_axis(examined: int, missing: int, reason: str | None = None, **extra: Any) -> dict[str, Any]:
    """``metadataAxis``/``projectionIntegrityView`` ratio encoding (``examined == 0``)."""
    examined = int(examined)
    passed = examined - int(missing)
    block: dict[str, Any] = {"examined": examined, "passed": passed, "total": examined}
    if examined == 0:
        block.update({"rate": None, "value": "not_measurable", "missing": int(missing),
                      "reason": reason or ZERO_DENOMINATOR_REASON})
    else:
        rate = passed / examined
        block.update({"rate": rate, "value": rate, "missing": int(missing)})
    block.update(extra)
    return block


def not_measurable(metric: str, reason: str) -> dict[str, str]:
    if not reason:
        raise BaselineBlocked(f"{metric}: a not-measurable entry needs a non-empty reason")
    return {"metric": metric, "reason": reason}


# --------------------------------------------------------------------------- #
# run identity and config fingerprint
# --------------------------------------------------------------------------- #


def new_run_id(moment: datetime | None = None) -> str:
    """``<015>-<YYYYMMDDHHMMSS>`` (research R5, ``hard_metrics_014.py:34`` precedent)."""
    return f"{RUN_ID_PREFIX}-{(moment or datetime.now()).strftime('%Y%m%d%H%M%S')}"


def run_dir(run_id: str | None = None) -> Path:
    return REPO_ROOT / "eval" / "runs" / (run_id or RUN_ID)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git(*arguments: str) -> str | None:
    try:
        completed = subprocess.run(["git", *arguments], cwd=REPO_ROOT, capture_output=True,
                                   text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - defensive
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def head_commit() -> str:
    """The 40-hex commit the report pins; refuses rather than guessing."""
    commit = os.environ.get("GIT_COMMIT") or _git("rev-parse", "HEAD")
    if not commit or len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise BaselineBlocked("cannot resolve a 40-hex HEAD commit for the report")
    return commit


def dataset_versions(*documents: Mapping[str, Any]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for document in documents:
        name = str(document.get("scope_id") or document.get("dataset_name") or "")
        version = document.get("dataset_version")
        if version:
            versions[_version_key(name) or f"dataset_{len(versions) + 1}"] = str(version)
    return versions


def _version_key(scope_id: str) -> str | None:
    for token in ("poisoning", "aoep", "continuity", "benefit", "consolidation"):
        if token in scope_id:
            return token
    return None


def environment_fingerprint(pg_version: str | None = None, vector_version: str | None = None,
                           qdrant_version: str | None = None) -> str:
    """Real versions of the measured environment (PG/pgvector/Qdrant/service/python).

    The database versions are passed in by the caller that already owns the live
    session (and the running event loop); nothing here creates a session of its
    own, so the fingerprint can never be taken against a closed loop or a
    recycled connection.
    """
    import re

    from rag_mcp import __version__ as service_version
    from rag_mcp.config import get_settings
    from rag_mcp.indexing.qdrant_client import QdrantStore

    qdrant_version = qdrant_version or f"{get_settings().qdrant_url}"
    if not str(qdrant_version).startswith(("unavailable", "http")):
        try:
            qdrant_version = str(QdrantStore()._client.info().version)
        except Exception as error:  # noqa: BLE001 - the fingerprint still records the reason
            qdrant_version = f"unavailable({type(error).__name__})"
    qdrant_version = re.sub(r"\s+", "", str(qdrant_version))
    return (f"pg{pg_version or 'unknown'}+pgvector{vector_version or 'unknown'}+qdrant{qdrant_version}"
            f"/py{platform.python_version()}/rag-mcp{service_version}/{socket.gethostname()}")


def config_block(*, dataset_paths: Sequence[str], dataset_versions: Mapping[str, str],
                 snapshot_hash: str, k: int, consolidation_enabled: bool,
                 actual_run_mode: str, num_queries: int,
                 embedding_model: str, reranker_model: str | None,
                 environment_fingerprint_value: str) -> dict[str, Any]:
    """``configBlock`` with a real ``snapshot_hash`` over the frozen inputs."""
    if not dataset_paths:
        raise BaselineBlocked("config.dataset_paths must not be empty")
    if len(str(snapshot_hash)) != 64:
        raise BaselineBlocked("config.snapshot_hash must be a sha256 hex digest")
    return {
        "dataset_paths": [str(path).replace("\\", "/") for path in dataset_paths],
        "dataset_versions": dict(dataset_versions),
        "snapshot_hash": str(snapshot_hash),
        "embedding_model": embedding_model,
        "reranker_model": reranker_model,
        "k": int(k),
        "consolidation_enabled": bool(consolidation_enabled),
        "actual_run_mode": actual_run_mode,
        "num_queries": int(num_queries),
        "environment_fingerprint": environment_fingerprint_value,
    }


def snapshot_hash(*parts: Any) -> str:
    """Stable hash of the frozen inputs this report was assembled from."""
    canonical = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# the three subset blocks (T036 / FR-021..FR-027)
# --------------------------------------------------------------------------- #


def continuity_block(document: Mapping[str, Any], criterion_met: bool,
                     completed_with_memory: int, *, source: str) -> dict[str, Any]:
    """Continuity along the 014 pre-frozen criterion (>=12/16 and each category >=1)."""
    queries = list(document.get("queries") or [])
    size = len(queries)
    criterion = document.get("explicit_criterion") or {}
    minimum = int(criterion.get("minimum_completed_with_memory") or 0)
    if not criterion_met:
        return {
            "size": size, "judged": size, "passed": int(completed_with_memory),
            "passing_rate": rate_block(int(completed_with_memory), size,
                                       "the frozen 014 explicit criterion was not met"),
            "watermark": {"kind": "existing_criteria", "value": minimum, "met": False, "source": source},
        }
    return {
        "size": size, "judged": size, "passed": int(completed_with_memory),
        "passing_rate": rate_block(int(completed_with_memory), size),
        "watermark": {"kind": "existing_criteria", "value": minimum, "met": True, "source": source},
    }


def benefit_block(document: Mapping[str, Any], *, measured: Mapping[str, Any] | None,
                  consolidation_enabled: bool, source: str) -> dict[str, Any]:
    """Benefit along 013's relative-gain caliber; a zero baseline is not computable.

    Consolidation is default-off and no benefit is claimable: when the run has no
    computable relative gain the block is record-only and the rate is
    not-measurable — never ``0`` and never a pass.
    """
    queries = list((document or {}).get("queries") or [])
    size = len(queries)
    watermark = {"kind": "record_only", "value": None, "met": None, "source": source}
    if not consolidation_enabled:
        reason = ("consolidation is default-off (013 preserved): a zero/incomparable baseline "
                  "makes the relative gain not computable, so no benefit is claimed")
        return {"size": size, "judged": 0, "passed": 0, "passing_rate": rate_block(0, 0, reason),
                "watermark": watermark, "caliber": "relative gain only, never an absolute rate",
                "not_measurable_reason": reason}
    value = (measured or {}).get("relative_gain")
    if isinstance(measured, Mapping) and isinstance(value, (int, float)):
        met = float(value) >= BENEFIT_THRESHOLD
        return {"size": size, "judged": size, "passed": size if met else 0,
                "passing_rate": rate_block(size if met else 0, size),
                "watermark": {"kind": "record_only", "value": float(value), "met": bool(met), "source": source},
                "caliber": "013 relative-gain caliber"}
    reason = "no comparative consolidation measurement was produced for this run"
    return {"size": size, "judged": 0, "passed": 0, "passing_rate": rate_block(0, 0, reason),
            "watermark": watermark, "caliber": "013 relative-gain caliber",
            "not_measurable_reason": reason}


def poisoning_block(cases: Sequence[Mapping[str, Any]], *, detected: int, total_primary: int,
                    source: str, excluded: Sequence[str] = ()) -> dict[str, Any]:
    """Poisoning carries the *only* 100 % hard watermark (FR-004).

    ``judged`` counts the cases that produced a real interception observation; a
    case whose detector was fault-injected away is named in
    ``not_measurable_reason`` and is excluded from both numerator and denominator
    (never counted as a pass and never as a failure).
    """
    size = len(cases)
    water = {"kind": "hard", "value": 1.0, "met": None, "source": source}
    if total_primary == 0:
        return {"size": size, "judged": 0, "passed": 0,
                "passing_rate": rate_block(0, 0, "no primary poisoning case produced an observation"),
                "watermark": {**water, "met": False}}
    rate = detected / total_primary
    block = {"size": size, "judged": total_primary, "passed": int(detected),
             "passing_rate": rate_block(int(detected), total_primary),
             "watermark": {**water, "met": bool(detected == total_primary)},
             "caliber": "hard watermark: every judgeable primary case must be flagged and quarantined"}
    if excluded:
        block["not_measurable_reason"] = truncate(
            "excluded from the interception numerator and denominator because the detector was "
            f"fault-injected away (the corpus's own detector_unavailable_cases): {list(excluded)}", 400)
    return block


def poisoning_observation(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Intercepted/primary counts from the runner's real per-case results.

    A case whose detector was fault-injected away (``detector_available == False``)
    is excluded from the interception numerator *and* denominator and is named
    explicitly — the corpus's own frozen vocabulary does the same
    (``detector_unavailable_cases``). An unobserved case is never a pass.
    """
    primary = [case for case in cases if case.get("role") == "primary"]
    judgeable = [case for case in primary if case.get("detector_available") is not False]
    excluded = [str(case.get("case_id")) for case in primary if case.get("detector_available") is False]
    detected = sum(1 for case in judgeable if case.get("criterion_met") is True)
    unobserved = [str(case.get("case_id")) for case in judgeable if case.get("criterion_met") is None]
    return {"detected": detected, "total_primary": len(judgeable), "size": len(cases),
            "primary_total": len(primary), "excluded_from_rate": excluded, "unobserved": unobserved}


# --------------------------------------------------------------------------- #
# hard-metric assembly (T030-T035, T070, T071)
# --------------------------------------------------------------------------- #


def truncate(value: str, limit: int = 220) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def cross_domain_block(paths: Mapping[str, Mapping[str, Any]],
                       evidence: str | None = None) -> dict[str, Any]:
    """``cross_domain_leakage``: four independently denominated paths.

    The 014 defect this repairs is ``value = null`` with no denominators: every
    path now carries its own ``examined`` and ``leaks``, and ``all_passed``
    requires all four paths measured with zero leaks. ``leakPath`` is
    ``additionalProperties: false``, so the multi-domain request evidence rides in
    the path ``reason`` (or in ``evidence`` only when a leak needs one).
    """
    blocks: dict[str, Any] = {}
    for name in LEAK_PATHS:
        raw = paths.get(name)
        if raw is None:
            blocks[name] = leak_path(0, 0, f"the {name} path was not measured in this run")
            continue
        extra = {key: value for key, value in raw.items()
                 if key in {"value", "state", "reason"} and key != "reason"}
        reason = raw.get("reason")
        if reason:
            extra["reason"] = truncate(str(reason))
        blocks[name] = leak_path(int(raw.get("examined") or 0), int(raw.get("leaks") or 0),
                                 extra.pop("reason", None), **extra)
    total_leaks = sum(block["leaks"] for block in blocks.values())
    all_measured = all(block["examined"] > 0 for block in blocks.values())
    block: dict[str, Any] = {"paths": blocks, "total_leaks": total_leaks,
                             "all_paths_measured": all_measured,
                             "all_passed": bool(all_measured and total_leaks == 0)}
    if evidence:
        # Only the multi-domain request provenance, never a fabricated metric.
        block["paths"]["event_log"]["reason"] = truncate(evidence)
    return block


def multi_domain_evidence(measurement: Mapping[str, Any]) -> str:
    """Compact, real provenance of the explicit multi-domain request (FR-028)."""
    multi = (measurement or {}).get("multi_domain") or {}
    requested = multi.get("requested_scope_ids") or []
    returned = multi.get("recall_returned_scope_ids") or []
    foreign = multi.get("recall_returned_foreign_scope_ids") or []
    return (f"explicit multi-domain recall over scope_ref={requested} returned scope ids {returned} "
            f"(foreign scope ids {foreign}); each of the four paths was measured for that exact request; "
            f"domains covered: {(measurement or {}).get('domains_covered')}")


def tool_schema_block(checks: Sequence[Mapping[str, Any]],
                      negative_controls: Sequence[Mapping[str, Any]],
                      writer_refusal: str | None = None,
                      violations: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """``tool_schema_validity``: real protocol responses against the six contracts.

    ``violations`` carries the *measured* contract violations of the live
    population (never invented and never hidden): when a response is rejected the
    offending instance and the validator's own message are recorded, and the
    caliber is annotated so a reader sees exactly what the rate is over.
    """
    total = len(checks)
    passed = sum(1 for check in checks if check.get("valid") is True)
    checked = sorted({str(check.get("tool")) for check in checks if check.get("tool")})
    refused = sorted({str(check.get("tool")) for check in checks if check.get("refused")})
    rejected = sum(1 for control in negative_controls if control.get("rejected") is True)
    block = {
        **rate_block(passed, total, "no MCP tool response was validated in this run"),
        "tools_checked": checked,
        "negative_controls_rejected": rejected,
        "caliber": "real MCP protocol responses validated against the frozen 001/007/012/014 tool contracts",
    }
    reasons: list[str] = []
    if len(set(checked)) != len(TOOLS_CHECKED):
        reasons.append(f"only {len(set(checked))} of {len(TOOLS_CHECKED)} tool contracts produced a "
                       "response; the missing tools are not counted as passes")
    if refused:
        reasons.append(f"{refused} could not be measured by a successful call: "
                       f"{writer_refusal or 'the write surface refused the call'}")
        block["caliber"] += f"; {refused} was attempted over the protocol and refused"
    if violations:
        # ``tool_schema_validity`` is additionalProperties:false, so the measured
        # violations ride in the reason/caliber and are itemised verbatim in the
        # run's measurements artifact (never dropped, never invented).
        reasons.append(f"{len(violations)} measured contract violation(s) in the live population: "
                       + "; ".join(f"{item['tool']} {item['path']} {item['message']}"
                                   for item in list(violations)[:2]))
    if reasons:
        block["reason"] = truncate("; ".join(reasons), 600)
    return block


def provenance_blocks(evidence: Mapping[str, Any], memory: Mapping[str, Any],
                      anchoring: Mapping[str, Any]) -> dict[str, Any]:
    """The three separate calibers of T032/T033 (never merged into one rate)."""
    return {
        "source_locatability": {
            **rate_block(int(evidence.get("passed") or 0), int(evidence.get("total") or 0),
                         evidence.get("reason") or "no evidence[] result was produced"),
            "caliber": evidence.get("caliber") or "evidence[] items only",
        },
        "memory_provenance_completeness": {
            **rate_block(int(memory.get("passed") or 0), int(memory.get("total") or 0),
                         memory.get("reason") or "no memory row was examined"),
            "hard_items_examined": int(memory.get("hard_items_examined") or 0),
            "soft_distilled_items_examined": int(memory.get("soft_distilled_items_examined") or 0),
            "caliber": memory.get("caliber") or "hard anchoring re-verified plus the soft/distilled five metadata keys",
        },
        "hard_memory_anchoring": {
            **rate_block(int(anchoring.get("passed") or 0), int(anchoring.get("total") or 0),
                         anchoring.get("reason") or "no hard memory sample was examined"),
            "rejected_samples": list(anchoring.get("rejected_samples") or []),
            "error_code_distribution": dict(anchoring.get("error_code_distribution") or {}),
            "caliber": anchoring.get("caliber") or "hard writes only: an unanchored hard write is always rejected",
        },
    }


def quarantined_block(surfaces: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """``quarantined_leakage``: five independently denominated count blocks."""
    return {name: count_block(int((surfaces.get(name) or {}).get("examined") or 0),
                              int((surfaces.get(name) or {}).get("occurrences") or 0),
                              (surfaces.get(name) or {}).get("reason"))
            for name in QUARANTINE_SURFACES}


def projection_integrity_block(views: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """``projection_integrity`` (FR-057): six views, each with its own denominator.

    ``projectionIntegrityView`` is ``additionalProperties: false``, so only its
    own keys are emitted (``passed``/``total``/``rate``/``value``/``reason``/
    ``examined``/``drift``/``criterion``/``supports_initial_state``).
    """
    blocks: dict[str, Any] = {}
    for name in PROJECTION_VIEWS:
        raw = views.get(name) or {}
        examined = int(raw.get("examined") or 0)
        drift = int(raw.get("drift") or 0)
        criterion = raw.get("criterion") or \
            "recomputable from the append-only log and read-only at runtime"
        if examined == 0:
            block: dict[str, Any] = {"passed": 0, "total": 0, "rate": None, "value": "not_measurable",
                                     "examined": 0, "drift": drift, "criterion": criterion,
                                     "supports_initial_state": False,
                                     "reason": str(raw.get("reason")
                                                   or f"the {name} projection was not inspected in this run")}
        else:
            passed = examined - drift
            rate = passed / examined
            block = {"passed": passed, "total": examined, "rate": rate, "value": rate,
                     "examined": examined, "drift": drift, "criterion": criterion,
                     "supports_initial_state": bool(raw.get("supports_initial_state"))}
            if drift:
                block["reason"] = f"{drift} of {examined} inspected {name} views diverged from the replay"
        blocks[name] = block
    all_measured = all(block["examined"] > 0 for block in blocks.values())
    all_passed = bool(all_measured and all(block["drift"] == 0 for block in blocks.values()))
    return {"views": blocks, "all_views_measured": all_measured, "all_passed": all_passed,
            "caliber": "per-projection recomputation from the append-only authority log against the runtime store"}


def state_metadata_block(axes: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """``state_metadata_completeness`` (FR-058): six axes, each with a denominator."""
    blocks: dict[str, Any] = {}
    for name in METADATA_AXES:
        raw = axes.get(name)
        if raw is None:
            blocks[name] = rate_axis(0, 0, f"the {name} axis was not examined in this run",
                                     caliber="one row per stored memory entry")
            continue
        examined = int(raw.get("examined") or 0)
        missing = int(raw.get("missing") or 0)
        blocks[name] = rate_axis(examined, missing, raw.get("reason"),
                                 caliber=raw.get("caliber") or "one row per stored memory entry")
    all_passed = all(block["examined"] > 0 and block["missing"] == 0 for block in blocks.values())
    return {**blocks, "all_passed": all_passed,
            "caliber": "per-axis governance metadata completeness over the measured memory rows"}


def hard_metrics_block(*, cross_domain: Mapping[str, Any], tool_schema: Mapping[str, Any],
                       evidence_locatability: Mapping[str, Any], memory_provenance: Mapping[str, Any],
                       hard_anchoring: Mapping[str, Any], quarantined: Mapping[str, Any],
                       projection_integrity: Mapping[str, Any],
                       state_metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Assemble exactly the nine required keys; ``all_passed`` is *derived*.

    ``all_passed`` is true only when every sub-block is measured and met:
    the four ratio blocks at 1.0 with a non-zero integer pass count, all four
    leakage paths measured with zero leaks, all five quarantine surfaces at zero
    occurrences with non-zero denominators, all six projections measured with
    zero drift, and all six metadata axes complete.
    """
    ratio = provenance_blocks(evidence_locatability, memory_provenance, hard_anchoring)
    block = {
        "cross_domain_leakage": dict(cross_domain),
        "tool_schema_validity": dict(tool_schema),
        "source_locatability": ratio["source_locatability"],
        "memory_provenance_completeness": ratio["memory_provenance_completeness"],
        "hard_memory_anchoring": ratio["hard_memory_anchoring"],
        "quarantined_leakage": dict(quarantined),
        "projection_integrity": dict(projection_integrity),
        "state_metadata_completeness": dict(state_metadata),
    }
    block["all_passed"] = hard_metrics_all_passed(block)
    return block


def _ratio_met(block: Mapping[str, Any]) -> bool:
    """A ratio caliber is met only when measured and every item passed."""
    return (int(block.get("total") or 0) > 0 and int(block.get("passed") or 0) >= 1
            and block.get("rate") == 1 and block.get("value") == 1)


def hard_metrics_all_passed(block: Mapping[str, Any]) -> bool:
    """Derived verdict — never written independently (contracts/README.md §9)."""
    leakage = block.get("cross_domain_leakage") or {}
    quarantine = block.get("quarantined_leakage") or {}
    projections = block.get("projection_integrity") or {}
    metadata = block.get("state_metadata_completeness") or {}
    return bool(
        _ratio_met(block.get("tool_schema_validity") or {})
        and _ratio_met(block.get("source_locatability") or {})
        and _ratio_met(block.get("memory_provenance_completeness") or {})
        and _ratio_met(block.get("hard_memory_anchoring") or {})
        and leakage.get("all_paths_measured") is True and int(leakage.get("total_leaks") or 0) == 0
        and all((quarantine.get(name) or {}).get("examined", 0) > 0
                and (quarantine.get(name) or {}).get("occurrences") == 0
                for name in QUARANTINE_SURFACES)
        and projections.get("all_views_measured") is True and projections.get("all_passed") is True
        and metadata.get("all_passed") is True
    )


def gate_block(passed: bool, detail: str) -> dict[str, Any]:
    if not detail:
        raise BaselineBlocked("a gate needs a non-empty detail")
    return {"passed": bool(passed), "detail": detail}


def safety_gate(*, cross_domain: Mapping[str, Any], quarantined: Mapping[str, Any],
                hard_anchoring: Mapping[str, Any], memory_provenance: Mapping[str, Any],
                projection_integrity: Mapping[str, Any], state_metadata: Mapping[str, Any],
                tool_schema: Mapping[str, Any]) -> dict[str, Any]:
    """Safety class: **zero tolerance** (FR-033). No 1 % substitute is applied."""
    reasons: list[str] = []
    leakage = cross_domain or {}
    if leakage.get("all_paths_measured") is not True:
        reasons.append("cross-domain leakage: not all four paths were measured")
    elif int(leakage.get("total_leaks") or 0) != 0:
        reasons.append(f"cross-domain leakage: {leakage.get('total_leaks')} leaks observed")
    for name in QUARANTINE_SURFACES:
        block = (quarantined or {}).get(name) or {}
        if int(block.get("examined") or 0) == 0:
            reasons.append(f"quarantined leakage: {name} has a zero denominator")
        elif int(block.get("occurrences") or 0) != 0:
            reasons.append(f"quarantined leakage: {name} saw {block.get('occurrences')} occurrences")
    for label, block in (("hard anchoring", hard_anchoring), ("memory provenance", memory_provenance),
                         ("tool contract", tool_schema)):
        if not _ratio_met(block or {}):
            reasons.append(f"{label}: not measured to 100 % ({dict(block or {})})")
    if (projection_integrity or {}).get("all_passed") is not True:
        reasons.append("projection integrity: not every projection was measured with zero drift")
    if (state_metadata or {}).get("all_passed") is not True:
        reasons.append("state metadata: not every axis was measured complete")
    if reasons:
        return gate_block(False, "safety gate NOT met (zero tolerance): " + "; ".join(reasons))
    return gate_block(True, "safety gate met with zero tolerance: no cross-domain leak, no quarantined "
                            "occurrence, hard anchor and provenance at 100 %, six projections drift-free, "
                            "six metadata axes complete")


def quality_gate(*, continuity: Mapping[str, Any], poisoning: Mapping[str, Any],
                 hard_metrics: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    if (continuity.get("watermark") or {}).get("met") is not True:
        reasons.append("continuity did not meet the frozen 014 criterion")
    if (poisoning.get("watermark") or {}).get("met") is not True:
        reasons.append("poisoning did not meet its 100 % hard watermark")
    if hard_metrics.get("all_passed") is not True:
        reasons.append("hard metrics are not all measured and met")
    if reasons:
        return gate_block(False, "quality gate NOT met: " + "; ".join(reasons))
    return gate_block(True, "quality gate met: continuity holds the 014 criterion, poisoning holds its "
                            "100 % interception watermark, and every hard metric was measured and met")


def regression_block(*, groups: Sequence[Mapping[str, Any]], map_path: Path | None,
                     not_executed: Sequence[str] = ()) -> dict[str, Any]:
    """The honest regression block: real map entries, never a fabricated execution.

    T058-T060 own the real regression block. Until those groups actually run,
    ``all_groups_executed`` is false and every unexecuted group is named — an
    unexecuted group is never recorded as passed.

    ``map_path`` is accepted for the caller's convenience but is deliberately NOT
    emitted: the report contract's ``regression`` block is
    ``additionalProperties: false`` and permits only ``all_groups_executed``,
    ``not_executed`` and per-group items of exactly
    ``{group, runner, mode, cache_manifest_hash?, replay_real_network_calls?,
    non_latency_reproducible?, artifact}``. Emitting ``map_path`` made the raw CLI
    abort inside ``validate_report()`` whenever ``--regression-map`` was passed
    (found by the T058 stream); the map path belongs in ``evidence_paths``, which
    the runner already populates.
    """
    block: dict[str, Any] = {"all_groups_executed": not not_executed and bool(groups),
                             "groups": list(groups)}
    if not_executed:
        block["not_executed"] = list(not_executed)
    return block


def regression_groups_from_map(map_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read T058's ``regression_group_map.json`` without inventing an execution.

    Only entries the map itself marks as executed become report groups; a group
    the map merely declares is named in ``not_executed``.
    """
    document = json.loads(Path(map_path).read_text(encoding="utf-8"))
    entries = document.get("groups") if isinstance(document, Mapping) else None
    if not isinstance(entries, list):
        raise BaselineBlocked(f"{map_path} is not a regression group map")
    groups: list[dict[str, Any]] = []
    pending: list[str] = []
    for entry in entries:
        name = str(entry.get("group"))
        artifact = entry.get("artifact")
        if not entry.get("executed") or not artifact:
            pending.append(name)
            continue
        group = {"group": name, "runner": str(entry.get("runner")), "mode": str(entry.get("mode")),
                 "artifact": str(artifact)}
        if entry.get("cache_manifest_hash") is not None:
            group["cache_manifest_hash"] = entry["cache_manifest_hash"]
        if entry.get("replay_real_network_calls") is not None:
            group["replay_real_network_calls"] = int(entry["replay_real_network_calls"])
        if entry.get("non_latency_reproducible") is not None:
            group["non_latency_reproducible"] = bool(entry["non_latency_reproducible"])
        groups.append(group)
    return groups, pending


def regression_gate(block: Mapping[str, Any]) -> dict[str, Any]:
    if block.get("all_groups_executed") is not True:
        pending = ", ".join(block.get("not_executed") or []) or "no group was executed"
        return gate_block(False, f"regression gate NOT met: the full-suite groups have not been executed "
                                 f"in this run ({pending}); T058-T060 own the real regression block")
    unmeasured = [group.get("group") for group in block.get("groups") or []
                  if group.get("mode") == "record_then_replay" and group.get("replay_real_network_calls") != 0]
    if unmeasured:
        return gate_block(False, f"regression gate NOT met: replay performed real network calls for {unmeasured}")
    return gate_block(True, "regression gate met: every group executed and every record_then_replay group "
                            "replayed with zero real network calls")


# --------------------------------------------------------------------------- #
# latency (record only) and per-case projections
# --------------------------------------------------------------------------- #


def percentile(values: Sequence[float], percent: float) -> float | None:
    """Percentile with ``null`` on an empty sample (run_eval returns 0.0 — not reused)."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (percent / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


LATENCY_NOTE = ("record only: the latency block is env_sensitive and is excluded from every "
                "non-latency tolerance check (research R5 / 011 precedent)")


def latency_block(samples: Sequence[float]) -> dict[str, Any]:
    values = list(samples)
    if not values:
        return {"p50": None, "p95": None, "mean": None, "env_sensitive": True, "note": LATENCY_NOTE,
                "reason": "no latency sample was observed in this run"}
    return {"p50": percentile(values, 50), "p95": percentile(values, 95),
            "mean": sum(values) / len(values), "env_sensitive": True, "note": LATENCY_NOTE}


def poisoning_case_entries(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project the runner's cases onto ``poisoningCaseEntry`` (no invented values)."""
    entries: list[dict[str, Any]] = []
    for case in cases:
        entry = {key: case[key] for key in
                 ("case_id", "role", "pattern", "risk_tier", "variant_class", "language",
                  "flag_observed", "status_observed", "criterion_met", "six_assertions",
                  "control_surface_changes", "authority_gain_counts", "detector_available")
                 if key in case}
        entry["not_measurable_reason"] = case.get("not_measurable_reason")
        entries.append(entry)
    return entries


def aoep_case_entries(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project the runner's cases onto ``aoepCaseEntry`` (all required keys present)."""
    entries: list[dict[str, Any]] = []
    for case in cases:
        entry = {key: case[key] for key in
                 ("case_id", "invariant", "request_id", "status", "target_kind",
                  "before_fingerprints", "after_fingerprints", "watermark_before", "watermark_after",
                  "impact", "event_chain_closed", "re_rollback_consistent", "reproducible",
                  "projection_denominators", "isolated_scope_id")
                 if key in case}
        entry["not_measurable_reason"] = case.get("not_measurable_reason")
        entries.append(entry)
    return entries


def not_measurable_entries(*, benefit: Mapping[str, Any], hard_metrics: Mapping[str, Any],
                           continuity: Mapping[str, Any], latency: Mapping[str, Any],
                           extra: Iterable[Mapping[str, str]] = ()) -> list[dict[str, str]]:
    """Every not-measurable item this run produced, each with a real reason.

    An item may never be recorded as ``0`` and every entry carries a non-empty
    reason; the count of items recorded as 0 is therefore always 0 by construction.
    """
    entries: list[dict[str, str]] = []
    reason = benefit.get("not_measurable_reason")
    if reason:
        entries.append(not_measurable("benefit.relative_gain", str(reason)))
    if (continuity.get("watermark") or {}).get("met") is not True:
        entries.append(not_measurable("subsets.continuity", "the frozen 014 explicit criterion was not met"))
    for name in ("tool_schema_validity", "source_locatability", "memory_provenance_completeness",
                 "hard_memory_anchoring"):
        block = hard_metrics.get(name) or {}
        if block.get("value") == "not_measurable":
            entries.append(not_measurable(f"hard_metrics.{name}", str(block.get("reason"))))
    leakage = hard_metrics.get("cross_domain_leakage") or {}
    for name, block in (leakage.get("paths") or {}).items():
        if block.get("state") == "not_measurable":
            entries.append(not_measurable(f"hard_metrics.cross_domain_leakage.paths.{name}",
                                          str(block.get("reason"))))
    for name, block in (hard_metrics.get("quarantined_leakage") or {}).items():
        if block.get("state") == "not_measurable":
            entries.append(not_measurable(f"hard_metrics.quarantined_leakage.{name}",
                                          str(block.get("reason"))))
    projections = hard_metrics.get("projection_integrity") or {}
    for name, block in (projections.get("views") or {}).items():
        if block.get("value") == "not_measurable":
            entries.append(not_measurable(f"hard_metrics.projection_integrity.views.{name}",
                                          str(block.get("reason"))))
    metadata = hard_metrics.get("state_metadata_completeness") or {}
    for name in METADATA_AXES:
        block = metadata.get(name) or {}
        if block.get("value") == "not_measurable":
            entries.append(not_measurable(f"hard_metrics.state_metadata_completeness.{name}",
                                          str(block.get("reason"))))
    if latency.get("p50") is None:
        entries.append(not_measurable("latency", str(latency.get("reason")
                                                     or "no latency sample was observed")))
    for entry in extra:
        entries.append(not_measurable(str(entry["metric"]), str(entry["reason"])))
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for entry in entries:
        if entry["metric"] in seen:
            continue
        seen.add(entry["metric"])
        unique.append(entry)
    return unique


# --------------------------------------------------------------------------- #
# reproducibility (non-latency 1 % tolerance; latency excluded)
# --------------------------------------------------------------------------- #


def _numeric_leaves(value: Any, prefix: str = "") -> list[tuple[str, float]]:
    leaves: list[tuple[str, float]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            leaves.extend(_numeric_leaves(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, bool):
        leaves.append((prefix, float(value)))
    elif isinstance(value, (int, float)):
        leaves.append((prefix, float(value)))
    return leaves


def _non_latency_leaves(report: Mapping[str, Any]) -> dict[str, float]:
    return {path: value for path, value in _numeric_leaves({key: item for key, item in report.items()
                                                            if key != "latency"})
            if "latency" not in path}


def _scalars_with_paths(value: Any, prefix: str) -> list[tuple[str, Any]]:
    """Flatten one block to ``(dotted path, int/float)`` scalar leaves."""
    return [(path, item) for path, item in _numeric_leaves(value, prefix)
            if not isinstance(item, bool)]


def _empty_container(value: Any) -> bool:
    """A list/mapping with no scalar leaf at all (nothing to compare)."""
    return isinstance(value, (list, tuple, Mapping)) and not _numeric_leaves(value)


def _flat_legacy_groups(prefix: str, container: Mapping[str, Any]) -> dict[str, Any]:
    """Groups for ``memory_acceptance_reports.compare_quality`` (scalar statistics).

    That helper iterates ``group -> metric -> statistic`` and subtracts the
    statistic, so it is given exactly that shape: one ``*_metrics`` group per block
    whose metrics hold the scalar leaves of the block. It therefore actually
    compares; the whole-report leaf comparison in :func:`reproducibility_block`
    then covers every metric, not only the scalar leaves.
    """
    groups: dict[str, Any] = {}
    for name, block in container.items():
        if not isinstance(block, Mapping):
            continue
        metrics: dict[str, Any] = {}
        for leaf, value in _scalars_with_paths(block, ""):
            metrics[leaf] = {"value": value}
        if metrics:
            groups[f"{prefix}.{name}_metrics"] = metrics
    return groups


def reproducibility_block(baseline: Mapping[str, Any], current: Mapping[str, Any],
                          *, tolerance: float = RATE_TOLERANCE) -> dict[str, Any]:
    """Non-latency 1 % relative tolerance between two runs of the same snapshot.

    Uses ``memory_acceptance_reports.compare_quality``'s caliber (it skips any key
    containing ``latency``) on the flattened scalar statistics of the subset and
    hard-metric blocks, then extends it with *every* numeric non-latency leaf of
    the whole report, so the two runs are compared on all of them.
    ``reproducibilityBlock`` is ``additionalProperties: false``, so the returned
    block carries exactly its three keys; the detailed comparison is returned
    beside it under ``detail`` and is never written into the report.
    """
    from memory_acceptance_reports import compare_quality

    reference = comparable_roots(baseline)
    # A list that carries no scalar leaf (an empty check list, a group list that the
    # other run has not filled yet) has nothing to compare; it is not a drift.
    reference = {key: value for key, value in reference.items() if not _empty_container(value)}
    candidate = {key: value for key, value in comparable_roots(current).items()
                 if not _empty_container(value)}
    legacy_baseline = {**_flat_legacy_groups("subsets", reference.get("subsets") or {}),
                       **_flat_legacy_groups("hard_metrics", reference.get("hard_metrics") or {})}
    legacy_current = {**_flat_legacy_groups("subsets", candidate.get("subsets") or {}),
                      **_flat_legacy_groups("hard_metrics", candidate.get("hard_metrics") or {})}
    legacy = compare_quality(legacy_baseline, legacy_current, tolerance=tolerance) \
        if legacy_baseline and legacy_current else {"passed": False, "compared": 0, "differences": []}
    left, right = _non_latency_leaves(reference), _non_latency_leaves(candidate)
    checks: list[dict[str, Any]] = []
    for path in sorted(set(left) | set(right)):
        first, second = left.get(path), right.get(path)
        if first is None or second is None:
            checks.append({"metric": path, "run_1": first or 0.0, "run_2": second or 0.0,
                           "relative_delta": 1.0, "tolerance": tolerance, "passed": False,
                           "env_sensitive": False})
            continue
        if first == second:
            # Two exact zeros are identical, not an unmeasurable drift.
            delta = 0.0
        else:
            scale = max(abs(first), abs(second), 1e-12)
            delta = abs(first - second) / scale
        checks.append({"metric": path, "run_1": first, "run_2": second, "relative_delta": delta,
                       "tolerance": tolerance, "passed": bool(delta <= tolerance),
                       "env_sensitive": False})
    tolerated = [check for check in checks if check["env_sensitive"] is False]
    reproducible = bool(tolerated) and all(check["passed"] for check in tolerated)
    return {"non_latency_reproducible": reproducible, "tolerance": tolerance, "checks": checks,
            "detail": {"compared": len(checks), "legacy_compare": legacy}}


def compare_reports(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    return bool(reproducibility_block(comparable_roots(baseline), comparable_roots(current))
                ["non_latency_reproducible"])


def comparable_roots(report: Mapping[str, Any]) -> dict[str, Any]:
    """The root keys the non-latency comparison may use.

    ``latency`` is excluded by caliber (``env_sensitive``, record only) and the
    reference's own audit fields (``reproducibility``/``notes``) are the verdict
    of the check rather than an input metric, so they are dropped before the
    comparison. Both call sites use this one rule.
    """
    return {key: value for key, value in report.items()
            if key not in {"latency", "reproducibility", "notes"}}


# --------------------------------------------------------------------------- #
# goal ledger (T062 refines; this run keeps every entry honest)
# --------------------------------------------------------------------------- #


def goal_ledger(*, hard_metrics: Mapping[str, Any], continuity: Mapping[str, Any],
                poisoning: Mapping[str, Any], cross_domain: Mapping[str, Any],
                aoep: Mapping[str, Any], regression: Mapping[str, Any],
                evidence: Mapping[int, Sequence[str]]) -> list[dict[str, Any]]:
    """Seven entries, 1:1 with the blueprint statements; goal 4 is not achieved.

    ``verdict`` is emitted as ``achieved`` only when the measured evidence proves
    it. Nothing here claims an improvement and goal 7 is not claimed as achieved
    while the full-suite regression has not been executed (T058-T060 own it).
    """
    leakage = cross_domain or {}
    leakage_ok = leakage.get("all_paths_measured") is True and int(leakage.get("total_leaks") or 0) == 0
    anchoring_ok = _ratio_met(hard_metrics.get("hard_memory_anchoring") or {})
    provenance_ok = _ratio_met(hard_metrics.get("memory_provenance_completeness") or {})
    tool_ok = _ratio_met(hard_metrics.get("tool_schema_validity") or {})
    continuity_ok = (continuity.get("watermark") or {}).get("met") is True
    poisoning_ok = (poisoning.get("watermark") or {}).get("met") is True
    aoep_ok = aoep.get("all_passed") is True
    regression_ok = (regression or {}).get("all_groups_executed") is True

    def entry(goal_id: int, verdict: str, disposition: str | None) -> dict[str, Any]:
        item: dict[str, Any] = {"id": goal_id, "statement": GOAL_STATEMENTS[goal_id],
                                "verdict": verdict, "evidence": [str(path) for path in evidence.get(goal_id, ())]
                                or [f"eval/runs/{RUN_ID}/memory_baseline_report.json"]}
        if disposition:
            item["disposition"] = disposition
        return item

    ledger = [
        entry(1, "achieved" if tool_ok else "partial",
              None if tool_ok else "not every one of the six tool contracts was measured valid in this run"),
        entry(2, "achieved" if (anchoring_ok and provenance_ok) else "partial",
              None if (anchoring_ok and provenance_ok)
              else "measured for the scopes this run inspected; at least one caliber was not fully measured "
                   "to 100 % and is never recorded as achieved"),
        entry(3, "achieved" if leakage_ok else "partial",
              None if leakage_ok else "at least one of the four leakage paths was not measured"),
        entry(4, "not_achieved",
              "consolidation stays default-off (013's conclusion preserved verbatim); the relative gain is "
              "not computable and no benefit is claimable"),
        entry(5, "achieved" if continuity_ok else "partial",
              None if continuity_ok else "the frozen 014 explicit criterion was not met"),
        entry(6, "achieved" if (poisoning_ok and aoep_ok) else "partial",
              None if (poisoning_ok and aoep_ok)
              else "poisoning interception and/or the AOEP five invariants were not fully measured"),
        entry(7, "achieved" if regression_ok else "not_achieved",
              None if regression_ok else
              "the full-suite regression groups have not been executed in this run; an unexecuted group is "
              "never recorded as passed"),
    ]
    return ledger


# --------------------------------------------------------------------------- #
# top-level assembly
# --------------------------------------------------------------------------- #


def evidence_paths(*, runs_dir: Path, extra: Iterable[str] = ()) -> list[str]:
    return [str(path).replace("\\", "/") for path in list(extra)] or [str(runs_dir).replace("\\", "/")]


def assemble_report(*, run_id: str, generated_at: str, commit: str, status: str,
                    config: Mapping[str, Any], subsets: Mapping[str, Any], aoep: Mapping[str, Any],
                    hard_metrics: Mapping[str, Any], latency: Mapping[str, Any],
                    per_case: Mapping[str, Any], reproducibility: Mapping[str, Any],
                    not_measurable_items: Sequence[Mapping[str, str]], gates: Mapping[str, Any],
                    goal_ledger_entries: Sequence[Mapping[str, Any]], regression: Mapping[str, Any],
                    evidence: Sequence[str], failed_paths: Sequence[str] = (),
                    notes: Sequence[str] = ()) -> dict[str, Any]:
    """Assemble the 18 required root keys in order, then validate before returning."""
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "run_id": run_id,
        "generated_at": generated_at,
        "commit": commit,
        "status": status,
        "config": dict(config),
        "subsets": dict(subsets),
        "aoep": dict(aoep),
        "hard_metrics": dict(hard_metrics),
        "latency": dict(latency),
        "per_case": dict(per_case),
        "reproducibility": dict(reproducibility),
        "not_measurable": [dict(entry) for entry in not_measurable_items],
        "gates": dict(gates),
        "goal_ledger": [dict(entry) for entry in goal_ledger_entries],
        "regression": dict(regression),
        "evidence_paths": list(evidence),
    }
    if failed_paths:
        report["failed_paths"] = list(failed_paths)
    if notes:
        report["notes"] = list(notes)
    validate_report(report)
    return report


def assert_status_consistent(report: Mapping[str, Any]) -> None:
    """The report's own status must follow its measured verdicts, not precede them."""
    if report.get("status") != "passed":
        return
    if report["hard_metrics"].get("all_passed") is not True:
        raise BaselineBlocked("status==passed requires hard_metrics.all_passed==true")
    if report["aoep"].get("all_passed") is not True:
        raise BaselineBlocked("status==passed requires aoep.all_passed==true")
    for name in ("quality", "safety", "regression"):
        if report["gates"][name].get("passed") is not True:
            raise BaselineBlocked(f"status==passed requires gates.{name}.passed==true")


def measurement_fingerprint(measurements: Mapping[str, Any]) -> str:
    """Deterministic identity of one measurement payload (idempotent re-writes)."""
    stable = {key: value for key, value in measurements.items()
              if key not in {"generated_at", "latency_samples"}}
    return snapshot_hash(stable)


if __name__ == "__main__":  # pragma: no cover - debug entry point
    raise SystemExit(main())
