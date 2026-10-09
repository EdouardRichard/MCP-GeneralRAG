"""T020 — per-run AOEP isolation domain and identity (015 US3, FR-019/SC-004).

The AOEP obligation cases perform destructive operations (rollback, retirement,
purge).  They therefore MUST NOT run inside an existing real domain or inside the
domain the frozen 013/014 evaluation subsets depend on
(``366084747748704256``, slug ``c013-eval-meeting-notes``; research.md Q8/R3).

This module is the single place that

* allocates a **fresh dedicated isolation domain** per run — a numeric snowflake
  ``KnowledgeScope.scope_id`` produced by ``rag_mcp.utils.snowflake.generate_id``
  (with a stdlib-only snowflake fallback so the module stays usable without the
  backend installed), plus
* allocates a **fresh dedicated isolation identity** per run (a uuid4 marker; the
  test harness pairs it with a real writer lease),
* refuses every configured forbidden scope id, and
* records the allocation and its disposal under
  ``disposal == "record_and_dispose"`` (the records are append-only: an existing
  isolation record is never rewritten, and a second run appends its own).

The module is deliberately dependency-light: only the standard library plus the
shared ``FORBIDDEN_SCOPE_IDS`` / ``canonical`` / ``sha256_text`` primitives from
``backend/tests/memory_eval_datasets.py`` (reused, never duplicated).  Everything
that needs PostgreSQL/rag_mcp is imported lazily inside the function that uses it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for _candidate in (str(REPO_ROOT), str(REPO_ROOT / "backend")):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from tests.memory_eval_datasets import (  # noqa: E402  (shared 015 primitives)
    FORBIDDEN_SCOPE_IDS,
    canonical,
    sha256_text,
)

#: The 013/014 frozen evaluation subsets share this scope; it is always forbidden.
REQUIRED_FORBIDDEN_SCOPE_ID = "366084747748704256"
if REQUIRED_FORBIDDEN_SCOPE_ID not in FORBIDDEN_SCOPE_IDS:  # pragma: no cover - guard
    raise RuntimeError(
        f"shared 015 FORBIDDEN_SCOPE_IDS must contain {REQUIRED_FORBIDDEN_SCOPE_ID}"
    )

MODE = "per_run_dedicated"
IDENTITY = "per_run_dedicated"
DISPOSAL = "record_and_dispose"
DISPOSAL_RECORD_NAME = "aoep_isolation_disposal.json"
ALLOCATION_RECORD_NAME = "aoep_isolation_allocation.json"
ISOLATION_RECORD_VERSION = "015.aoep.isolation.1"

_SEQUENCE = 0


class IsolationDenied(PermissionError):
    """A destructive operation was aimed outside the per-run isolation domain."""

    def __init__(self, code: str, scope_id: Any):
        super().__init__(f"{code}:{scope_id}")
        self.code = code
        self.scope_id = scope_id


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _generate_scope_id() -> int:
    """Numeric snowflake scope id.

    Prefers the production ``generate_id``; falls back to the same snowflake
    layout (41-bit millisecond clock, 22-bit sequence) when the backend package is
    not importable, so the module stays importable from a bare interpreter.
    """
    try:
        from rag_mcp.utils.snowflake import generate_id  # noqa: PLC0415 - lazy

        return int(generate_id())
    except Exception:  # noqa: BLE001 - fallback keeps this module dependency-light
        global _SEQUENCE
        _SEQUENCE = (_SEQUENCE + 1) & 0x3FFFFF
        return (int(time.time() * 1000) << 22) | _SEQUENCE


@dataclass(frozen=True)
class IsolationAllocation:
    """One per-run dedicated isolation domain plus its dedicated identity."""

    scope_id: int
    isolation_id: str
    identity_id: str
    slug: str
    name: str
    run_id: str | None = None
    mode: str = MODE
    identity: str = IDENTITY
    disposal: str = DISPOSAL
    record_isolation_id: bool = True
    forbidden_scope_ids: tuple[str, ...] = tuple(FORBIDDEN_SCOPE_IDS)
    allocated_at: str = ""
    scope_type: str = "project"
    domain_key: str = "generic"

    @property
    def isolated_scope_id(self) -> str:
        return str(self.scope_id)

    def document(self) -> dict[str, Any]:
        """JSON-safe allocation record (allocation only, no disposal)."""
        return {
            "isolation_record_version": ISOLATION_RECORD_VERSION,
            "mode": self.mode,
            "identity": self.identity,
            "identity_id": self.identity_id,
            "isolation_id": self.isolation_id,
            "record_isolation_id": bool(self.record_isolation_id),
            "scope_id": str(self.scope_id),
            "slug": self.slug,
            "name": self.name,
            "scope_type": self.scope_type,
            "domain_key": self.domain_key,
            "run_id": self.run_id,
            "allocated_at": self.allocated_at,
            "disposal": self.disposal,
            "forbidden_scope_ids": list(self.forbidden_scope_ids),
            "forbidden_scope_id_touched": False,
        }


def forbidden_scope_ids(*, extra: Any = None) -> tuple[str, ...]:
    """The configured forbidden set (shared default plus caller additions)."""
    values = [str(item) for item in FORBIDDEN_SCOPE_IDS]
    if extra:
        for item in extra:
            text = str(item)
            if text not in values:
                values.append(text)
    return tuple(values)


def assert_allowed(scope_id: Any, *, forbidden: Any = None) -> int:
    """Return the scope id only when it is a positive id outside the forbidden set."""
    if isinstance(scope_id, bool) or not isinstance(scope_id, int) or scope_id <= 0:
        raise IsolationDenied("ISOLATION_SCOPE_INVALID", scope_id)
    if str(scope_id) in forbidden_scope_ids(extra=forbidden):
        raise IsolationDenied("ISOLATION_FORBIDDEN_SCOPE", scope_id)
    return scope_id


def assert_isolated(allocation: IsolationAllocation, scope_id: Any) -> int:
    """A destructive target must be exactly this run's allocation (and allowed)."""
    resolved = assert_allowed(scope_id, forbidden=allocation.forbidden_scope_ids)
    if resolved != allocation.scope_id:
        raise IsolationDenied("ISOLATION_SCOPE_NOT_ALLOCATED", scope_id)
    return resolved


def allocate(
    *,
    run_id: str | None = None,
    forbidden: Any = None,
    scope_id: int | None = None,
    slug_prefix: str = "aoep",
    name_prefix: str = "AOEP isolation",
    identity_id: str | None = None,
    isolation_id: str | None = None,
    now: str | None = None,
) -> IsolationAllocation:
    """Allocate the per-run dedicated isolation domain and identity.

    ``scope_id`` is only for tests that pin the value; the default path always
    mints a new snowflake so two runs never share a domain.
    """
    forbidden_ids = forbidden_scope_ids(extra=forbidden)
    if scope_id is None:
        scope_id = _generate_scope_id()
    assert_allowed(scope_id, forbidden=forbidden_ids)
    marker = isolation_id or uuid.uuid4().hex
    allocation = IsolationAllocation(
        scope_id=int(scope_id),
        isolation_id=str(marker),
        identity_id=str(identity_id or uuid.uuid4()),
        slug=f"{slug_prefix}-{marker[:16]}",
        name=f"{name_prefix} {marker[:16]}",
        run_id=run_id,
        forbidden_scope_ids=forbidden_ids,
        allocated_at=now or _now(),
    )
    return allocation


def record_path(directory: str | Path, name: str = DISPOSAL_RECORD_NAME) -> Path:
    """Where the allocation/disposal record lives (evidence directory)."""
    return Path(directory) / name


def _load_records(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "isolation_record_version": ISOLATION_RECORD_VERSION,
            "disposal": DISPOSAL,
            "allocations": [],
        }
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        document.get("isolation_record_version") != ISOLATION_RECORD_VERSION
        or not isinstance(document.get("allocations"), list)
    ):
        raise RuntimeError(f"unreadable AOEP isolation record: {path}")
    return document


def _write(path: Path, document: dict[str, Any]) -> str:
    """Write an already-merged document. Callers never rewrite an existing entry."""
    raw = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return sha256_text(raw.decode("utf-8"))


def _record_id(entry: dict[str, Any]) -> str:
    return str(entry.get("isolation_id"))


def dispose(
    allocation: IsolationAllocation,
    *,
    directory: str | Path | None = None,
    path: str | Path | None = None,
    reason: str = "per-run dedicated AOEP isolation domain disposed after the run",
    disposed_at: str | None = None,
    extra: dict[str, Any] | None = None,
    name: str = DISPOSAL_RECORD_NAME,
) -> dict[str, Any]:
    """Append the allocation + its disposal record (``record_and_dispose``).

    Append-only: an existing record for the same ``isolation_id`` is never
    rewritten, and a later run appends its own entry.  Returns the written
    document and the record hash.
    """
    if directory is None and path is None:
        raise ValueError("dispose requires directory or path")
    target = Path(path) if path is not None else record_path(directory, name)
    document = _load_records(target)
    entry = {
        "disposed_at": disposed_at or _now(),
        "disposal": DISPOSAL,
        "disposal_reason": reason,
        "disposed": True,
        "isolation": allocation.document(),
    }
    if extra:
        entry["extra"] = {str(key): value for key, value in extra.items()}
    existing = {_record_id(item.get("isolation", {})): item for item in document["allocations"]}
    previous = existing.get(allocation.isolation_id)
    if previous is not None:
        if canonical(previous) != canonical(entry):
            raise RuntimeError(
                f"refusing to rewrite the AOEP isolation record for {allocation.isolation_id}"
            )
        return {"path": str(target), "hash": sha256_text(canonical(document)), "document": document,
                "appended": False}
    document["allocations"].append(entry)
    document["disposal"] = DISPOSAL
    document["allocation_count"] = len(document["allocations"])
    document["updated_at"] = entry["disposed_at"]
    digest = _write(target, document)
    return {"path": str(target), "hash": digest, "document": document, "appended": True}


def record_allocation(
    allocation: IsolationAllocation,
    *,
    directory: str | Path | None = None,
    path: str | Path | None = None,
    recorded_at: str | None = None,
    name: str = ALLOCATION_RECORD_NAME,
) -> dict[str, Any]:
    """Persist an allocation-only record (used before the destructive work)."""
    if directory is None and path is None:
        raise ValueError("record_allocation requires directory or path")
    target = Path(path) if path is not None else record_path(directory, name)
    document = _load_records(target)
    entry = {"recorded_at": recorded_at or _now(), "disposal": DISPOSAL, "isolation": allocation.document()}
    existing = {_record_id(item.get("isolation", {})): item for item in document["allocations"]}
    previous = existing.get(allocation.isolation_id)
    if previous is not None and canonical(previous) != canonical(entry):
        raise RuntimeError(f"refusing to rewrite the AOEP allocation record for {allocation.isolation_id}")
    if previous is None:
        document["allocations"].append(entry)
        document["allocation_count"] = len(document["allocations"])
        document["updated_at"] = entry["recorded_at"]
        digest = _write(target, document)
        return {"path": str(target), "hash": digest, "document": document, "appended": True}
    return {"path": str(target), "hash": sha256_text(canonical(document)), "document": document, "appended": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Allocate or dispose one per-run AOEP isolation domain.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--dispose", action="store_true", help="write the disposal record after allocating")
    parser.add_argument("--reason", default="per-run dedicated AOEP isolation domain disposed after the run")
    arguments = parser.parse_args(argv)
    allocation = allocate(run_id=arguments.run_id)
    result: dict[str, Any] = {"allocation": allocation.document()}
    if arguments.dispose and arguments.evidence_dir:
        result["disposal"] = dispose(allocation, directory=arguments.evidence_dir, reason=arguments.reason)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
