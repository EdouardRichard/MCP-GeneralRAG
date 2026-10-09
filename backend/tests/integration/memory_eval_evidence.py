"""015 memory-evaluation evidence export (T009).

Isomorphic with ``tests/integration/consolidation_evidence.py`` (013): a
session-scoped bundle collects real per-case observations while the suite runs and
writes them once at session finish. It only writes when
``MEMORY_EVAL_EVIDENCE_DIR`` is configured, and it refuses to overwrite bytes that
differ from what it would write (the 015 zero-overwrite discipline).

Two documents are produced:

* ``aoep-cases.json``   -- per-case AOEP obligation results (``aoepCaseEntry``)
* ``poisoning-cases.json`` -- per-case poisoning-suite results (``poisoningCaseEntry``)

Both are consumed by ``eval/run_memory_baseline.py`` (T025/T028) via
``--aoep-results`` / ``--poisoning-results``. The bundle never invents a case: a
case only appears if a test recorded a real observation for it, so an unexecuted
case is reported as absent rather than as a pass.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

AOEP_CASES_NAME = "aoep-cases.json"
POISONING_CASES_NAME = "poisoning-cases.json"
EVIDENCE_VERSION = "015.evidence.1"

AOEP_REQUIRED = ("case_id", "invariant", "request_id", "status", "isolated_scope_id")
AOEP_INVARIANTS = (
    "traceable_rollback",
    "deletion_propagation",
    "authority_monotonicity",
    "provenance_preservation",
    "scope_non_expansion",
)
POISONING_REQUIRED = (
    "case_id",
    "role",
    "pattern",
    "risk_tier",
    "language",
    "six_assertions",
    "control_surface_changes",
    "authority_gain_counts",
)


def _jsonable(value):
    """Convert nested structures to JSON-safe primitives (mirrors 013's helper)."""
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class MemoryEvalEvidenceBundle:
    """Session-scoped collector for real 015 per-case observations."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.started_at = datetime.now(UTC).isoformat()
        self.aoep_cases: dict[str, dict] = {}
        self.poisoning_cases: dict[str, dict] = {}
        self.notes: list[str] = []
        self.finalized = False

    # -- recording ---------------------------------------------------------

    def record_aoep_case(self, entry):
        payload = _jsonable(entry)
        missing = [key for key in AOEP_REQUIRED if key not in payload]
        if missing:
            raise ValueError(f"aoep case entry missing required keys {missing}: {payload.get('case_id')!r}")
        if payload["invariant"] not in AOEP_INVARIANTS:
            raise ValueError(f"unknown AOEP invariant {payload['invariant']!r}")
        case_id = str(payload["case_id"])
        self.aoep_cases[case_id] = payload
        return payload

    def record_poisoning_case(self, entry):
        payload = _jsonable(entry)
        missing = [key for key in POISONING_REQUIRED if key not in payload]
        if missing:
            raise ValueError(f"poisoning case entry missing required keys {missing}: {payload.get('case_id')!r}")
        case_id = str(payload["case_id"])
        self.poisoning_cases[case_id] = payload
        return payload

    def add_note(self, note):
        text = str(note)
        if text not in self.notes:
            self.notes.append(text)
        return text

    # -- derived views -----------------------------------------------------

    def by_invariant(self):
        counts = {name: {"passed": 0, "total": 0, "failed": 0, "not_measurable": 0} for name in AOEP_INVARIANTS}
        for entry in self.aoep_cases.values():
            bucket = counts[entry["invariant"]]
            bucket["total"] += 1
            status = entry["status"]
            if status == "passed":
                bucket["passed"] += 1
            elif status == "failed":
                bucket["failed"] += 1
            else:
                bucket["not_measurable"] += 1
        return counts

    # -- documents ---------------------------------------------------------

    def _aoep_document(self, exitstatus):
        cases = [self.aoep_cases[key] for key in sorted(self.aoep_cases)]
        return {
            "evidence_version": EVIDENCE_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "started_at": self.started_at,
            "exitstatus": int(exitstatus),
            "case_count": len(cases),
            "observed_case_ids": [entry["case_id"] for entry in cases],
            "by_invariant": self.by_invariant(),
            "cases": cases,
            "notes": list(self.notes),
        }

    def _poisoning_document(self, exitstatus):
        cases = [self.poisoning_cases[key] for key in sorted(self.poisoning_cases)]
        primary = [entry for entry in cases if entry.get("role") == "primary"]
        return {
            "evidence_version": EVIDENCE_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "started_at": self.started_at,
            "exitstatus": int(exitstatus),
            "case_count": len(cases),
            "primary_count": len(primary),
            "control_cases": [entry["case_id"] for entry in cases if entry.get("role") == "control"],
            "detector_unavailable_cases": [
                entry["case_id"] for entry in cases if entry.get("detector_available") is False
            ],
            "observed_case_ids": [entry["case_id"] for entry in cases],
            "cases": cases,
            "notes": list(self.notes),
        }

    @staticmethod
    def _write(path: Path, document, *, case_count: int = 0):
        """Zero-overwrite export, isomorphic in spirit with the 013 bundle.

        * identical bytes -> idempotent success
        * absent -> write
        * different bytes -> refuse (RuntimeError), UNLESS the new document holds
          no cases at all (never clobber collected evidence with an empty dump
          produced by an unrelated run), or the operator explicitly opted into
          replacing the transient session dump with
          ``MEMORY_EVAL_EVIDENCE_REPLACE=1`` for the one authoritative run.
        """
        raw = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() == raw:
                return sha256(raw).hexdigest()
            replace = os.environ.get("MEMORY_EVAL_EVIDENCE_REPLACE") == "1"
            if case_count == 0 and not replace:
                return None
            if replace:
                path.unlink()
            else:
                raise RuntimeError(f"015 memory-eval evidence exists with different content: {path}")
        with path.open("xb") as stream:
            stream.write(raw)
        return sha256(raw).hexdigest()

    def write_aoep_cases(self, exitstatus):
        document = self._aoep_document(exitstatus)
        return self._write(self.directory / AOEP_CASES_NAME, document, case_count=document["case_count"])

    def write_poisoning_cases(self, exitstatus):
        document = self._poisoning_document(exitstatus)
        return self._write(self.directory / POISONING_CASES_NAME, document, case_count=document["case_count"])

    def finalize(self, exitstatus):
        if self.finalized:
            return
        self.finalized = True
        self.write_aoep_cases(exitstatus)
        self.write_poisoning_cases(exitstatus)


def evidence_dir():
    value = os.environ.get("MEMORY_EVAL_EVIDENCE_DIR")
    return value or None
