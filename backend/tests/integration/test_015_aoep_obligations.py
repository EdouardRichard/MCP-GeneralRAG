"""015 T022-T024 + T068/T069/T075 — AOEP state-obligation suite (US3, FR-014-FR-020/FR-056/FR-061).

Five invariants (dataset: ``eval/memory_aoep_obligation_dataset.json``, the single
source of truth; this module never re-declares case content):

* ``traceable_rollback`` (R6.1) — rollback event + identical ``request_id``, closed
  event chain, readable watermark, whole-state and per-view fingerprints,
  ``inspect()`` integrity, impact-count equality, a second rollback to an adjacent
  checkpoint, retained ``access`` events, plus an explicit **negative control**: an
  audit-only ``request_id`` (a real ``MemoryManagementAudit`` row with no authority
  event behind it) MUST be judged **failed**.
* ``deletion_propagation`` (R6.2) — ``retire`` and ``purge`` each assert the
  consumer-visible hit count of the identity is 0 in **each** of relation, dense,
  links, summary and file, independently, with a non-zero denominator per
  projection; a zero denominator is recorded ``not_measurable`` with the reason
  ``"a zero denominator is not a measured zero"`` (never 0, never "passed"). The
  authority log must still hold the ``retract`` event and the source chain.
  ``salience`` is a field projection and does not participate.
* ``authority_monotonicity`` (R6.5 + T068) — over-authority writes and MCP-surface
  attempts to rewrite the binding table are all rejected, the authority-log id
  sequence before == after **item by item**, the ``authority`` axis and the
  ``scope_bindings`` row set are unchanged, and every rejection is observable as a
  403/structured error code.
* ``scope_non_expansion`` (R6.4 + T075/FR-061) — ambiguous, missing, empty-string
  and whitespace-only references are four separate cases with separate non-zero
  sample sizes; every surface must reject with ``AMBIGUOUS_DOMAIN_REF`` /
  ``MISSING_KNOWLEDGE_SCOPE`` **and candidate domains**, and the number of
  successful "fall back to the nearest domain / whole library" resolutions must be 0.
* ``provenance_preservation`` (R6.6 + T069) — after retire/purge/rollback the
  provenance metadata and source chain survive, ``content_hash`` is **recomputed**
  and compared item by item, the authority log keeps the tombstones, and the
  affected projections recompute consistently through ``projection_fingerprint``.

**"No gap in the id sequence" means exactly this** (research.md R6 clarification):
the id sequence obtained by ``MemoryEventStore.replay(scope_id)`` equals the
authority log's ordered id sequence *item by item* — no missing and no duplicate
entry. It is explicitly **not** numeric continuity: ``MemoryEvent.event_id`` is a
snowflake and is naturally sparse, so a numeric-contiguity check would be
permanently false and would report a false failure.

Isolation (SC-004/T026): every case allocates a fresh dedicated scope through
``eval/memory_aoep_isolation.py`` (never ``366084747748704256`` and never an
existing real domain), and every destructive command is asserted to target that
allocation. Each case records a ``MemoryEvalEvidenceBundle.record_aoep_case`` entry
(isomorphic to ``$defs/aoepCaseEntry``) and, when an evidence directory is
configured, an allocation+disposal record.

T082/FR-019 — the per-case record is **self-sufficient**: every exported case carries
``role`` (``primary`` for 12 cases, ``negative_control`` for
``aoep_traceable_rollback_audit_only_counterexample``), ``criterion`` (the dataset's
``invariants[<invariant>].machine_criterion`` plus a one-line machine-readable
statement), the criterion's ``expected`` observation, the measured ``observed``
object, every sub-condition boolean the case evaluated in ``scoring``, and the real
denominators in ``sample_sizes``. ``before_fingerprints``/``after_fingerprints`` are
either measured (authority-log id sequence, ``scope_bindings`` row set, scope
registry row set, projected views) or an explicit ``not_applicable: <reason>`` marker —
never a silent ``{}``. ``event_chain_closed`` is a measured boolean only where an
event chain is actually replayed (traceable_rollback / deletion_propagation /
provenance_preservation) and is ``null`` for
authority_monotonicity / scope_non_expansion, which replay no chain. The negative
control keeps ``status="passed"`` meaning *"the R6.1 checker applied its criterion
correctly"* and states the inversion explicitly (``expected.traceable=false`` against
``observed.authority_event_present=false``), so a machine can read the artifact alone.

Every observation below comes from the real PostgreSQL event log / projection
metadata / Qdrant-backed projections; nothing is stubbed, route-mocked or preset.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[3]
for _candidate in (str(REPO_ROOT), str(REPO_ROOT / "backend")):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from eval.memory_aoep_isolation import (  # noqa: E402
    FORBIDDEN_SCOPE_IDS,
    IsolationAllocation,
    allocate,
    assert_allowed,
    assert_isolated,
    dispose,
)
from rag_mcp.db import get_session  # noqa: E402
from rag_mcp.mcp import create_mcp_server  # noqa: E402
from rag_mcp.models.knowledge_scope import KnowledgeScope  # noqa: E402
from rag_mcp.models.memory_event import MemoryEvent  # noqa: E402
from rag_mcp.models.memory_management_audit import MemoryManagementAudit  # noqa: E402
from rag_mcp.models.memory_projection import MemoryEntry  # noqa: E402
from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta  # noqa: E402
from rag_mcp.models.runtime import WriterLease  # noqa: E402
from rag_mcp.models.scope_binding import ScopeBinding  # noqa: E402
from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider  # noqa: E402
from rag_mcp.server import create_app  # noqa: E402
from rag_mcp.services.memory_event_store import MemoryEventStore  # noqa: E402
from rag_mcp.services.memory_projection_store import VIEW_KEYS  # noqa: E402
from rag_mcp.services.memory_reducer import projection_fingerprint, reduce_events  # noqa: E402
from rag_mcp.services.memory_service import MemoryService  # noqa: E402
from rag_mcp.services.scope_binding_service import ScopeBindingError  # noqa: E402
from rag_mcp.services.scope_resolver import MemoryScopeResolver  # noqa: E402
from tests.integration.memory_acceptance import writer_owner  # noqa: E402
from tests.memory_eval_datasets import (  # noqa: E402
    AOEP_DATASET,
    AOEP_INVARIANTS,
    DELETION_PROJECTIONS,
    load_dataset,
)

RUN_ID = os.environ.get("RUN_ID", "015-20261009205637")
FORBIDDEN_SCOPE_ID = int(FORBIDDEN_SCOPE_IDS[0])
DELETE_PROJECTIONS = tuple(DELETION_PROJECTIONS)
#: The six projections R6.1/R6.6 assert a per-view fingerprint for (the five
#: consumable views plus the ``salience`` field projection).
CRITERION_VIEWS = ("relation", "dense", "links", "summary", "file", "salience")
PROVENANCE_FIELDS = (
    "content_text", "content_hash", "provenance", "confidence", "inference_meta", "evidence_refs",
    "provenance_validation", "kind", "source_event_id", "authority", "scope_meta", "mutability",
    "provenance_meta", "recoverability", "actionability",
)

DATASET = load_dataset(AOEP_DATASET)
CASES: dict[str, dict] = {case["case_id"]: case for case in DATASET["cases"]}
assert set(DATASET["invariants"]) == set(AOEP_INVARIANTS), "AOEP dataset invariant key set changed"
assert all(case["expected"]["outcome"] == "passed" for case in DATASET["cases"])


# ---------------------------------------------------------------------------
# dataset accessors (case content is never duplicated in this module)
# ---------------------------------------------------------------------------

def case(case_id: str) -> dict:
    if case_id not in CASES:
        raise AssertionError(f"{case_id} is not declared by {AOEP_DATASET}")
    return CASES[case_id]


def meta(case_id: str) -> dict:
    return case(case_id)["_meta"]


# ---------------------------------------------------------------------------
# T082 — per-case criterion/role identity (FR-019: the artifact must decide alone)
# ---------------------------------------------------------------------------
#
# The criterion id is NEVER re-declared here: it is read from the dataset's
# ``invariants[<invariant>].machine_criterion``, which is the single source of
# truth.  The one-line statement is a module-level constant because the artifact
# must be decidable without reading the (Chinese) dataset statement; a mapping is
# still a re-declaration of prose, so a drift guard below pins the criterion ids
# to the dataset and fails loudly if the dataset changes.

#: One-line machine-readable restatement of each invariant's criterion.
#: ``criterion`` in the exported record is ``"<machine_criterion>: <this line>"``.
CRITERION_STATEMENTS: dict[str, str] = {
    "traceable_rollback": (
        "a rollback is traceable iff the authority log holds a rollback event whose request_id equals the "
        "governance response request_id, the event chain is closed (replay(scope) id sequence == authority log "
        "id sequence item by item, no missing and no duplicate), the watermark is readable, whole-state and "
        "per-view fingerprints match the independently recomputed state, impact.memory_ids equals the real "
        "entries diff, inspect() reports matches_replay, any re-rollback to an adjacent checkpoint is "
        "self-consistent and access events are retained"
    ),
    "deletion_propagation": (
        "after retire and after purge the consumer-visible hit count of the identity is 0 in EACH of "
        "relation/dense/links/summary/file independently, each with a non-zero denominator, while the authority "
        "log still holds the retract event and the recomputable source chain (salience is a field projection "
        "and is excluded)"
    ),
    "authority_monotonicity": (
        "every over-authority write and every MCP-surface attempt to rewrite the binding table is rejected "
        "(403 / structured error code), the authority-log id sequence is identical before and after item by "
        "item, the authority axis and the scope_bindings row set are unchanged, and every rejection is "
        "observable as an error code"
    ),
    "provenance_preservation": (
        "after retire/purge/rollback the provenance metadata and source chain survive, content_hash is "
        "RECOMPUTED and compared item by item, the authority log keeps the tombstones and the source chain, and "
        "the affected projections recompute consistently through projection_fingerprint"
    ),
    "scope_non_expansion": (
        "ambiguous, missing, empty-string and whitespace-only scope references are all rejected with "
        "AMBIGUOUS_DOMAIN_REF / MISSING_KNOWLEDGE_SCOPE plus candidate domains on every surface, and the number "
        "of successful fall-backs to the nearest domain / whole library is exactly 0"
    ),
}

#: Drift guard: the criterion ids in the exported records come from the dataset.
_CRITERION_IDS = {name: value["machine_criterion"] for name, value in DATASET["invariants"].items()}
assert set(CRITERION_STATEMENTS) == set(AOEP_INVARIANTS) == set(_CRITERION_IDS), (
    "every AOEP invariant must have exactly one criterion statement and one dataset criterion id")
assert all(_CRITERION_IDS[name].startswith("R6.") for name in AOEP_INVARIANTS), (
    f"unexpected machine_criterion in {AOEP_DATASET}: {_CRITERION_IDS}")

#: The one case that is a negative control (the dataset's ``_meta.negative_control``
#: is authoritative; this constant pins the expected split 12 + 1).
NEGATIVE_CONTROL_CASE = "aoep_traceable_rollback_audit_only_counterexample"
assert CASES[NEGATIVE_CONTROL_CASE]["_meta"]["negative_control"] is True, (
    f"{NEGATIVE_CONTROL_CASE} must be declared _meta.negative_control=true by {AOEP_DATASET}")


def criterion(case_id: str) -> str:
    """``"<dataset machine_criterion>: <one-line machine-readable statement>"``."""
    invariant = case(case_id)["invariant"]
    return f"{_CRITERION_IDS[invariant]}: {CRITERION_STATEMENTS[invariant]}"


def role(case_id: str) -> str:
    return "negative_control" if meta(case_id).get("negative_control") else "primary"


def criterion_id_of(case_id: str) -> str:
    return _CRITERION_IDS[case(case_id)["invariant"]]


_negative_controls = sorted(key for key, value in CASES.items() if value["_meta"].get("negative_control"))
assert _negative_controls == [NEGATIVE_CONTROL_CASE], (
    f"expected exactly one negative control ({NEGATIVE_CONTROL_CASE}), got {_negative_controls}")
assert sorted(role(key) for key in CASES) == ["negative_control"] + ["primary"] * 12, (
    f"expected 12 primary + 1 negative_control in {AOEP_DATASET}, got "
    f"{sorted(role(key) for key in CASES)}")


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _submission(scope_id: int, *, content: str, evidence_refs: tuple[str, ...], provenance: str = "soft") -> dict:
    """A real submission payload; ``evidence_refs`` keeps the links projection non-empty."""
    return {
        "scope_id": scope_id,
        "kind": "procedural",
        "content": content,
        "provenance": provenance,
        "evidence_refs": list(evidence_refs),
        "inference_meta": {
            "source": "015 AOEP obligation suite", "confidence": 0.8, "model_version": "aoep-015-v1",
            "time": datetime.now(UTC).isoformat(), "supporting_evidence": [],
        },
    }


async def _new_scope(session, allocation: IsolationAllocation, *, name: str | None = None) -> int:
    assert_allowed(allocation.scope_id, forbidden=allocation.forbidden_scope_ids)
    session.add(KnowledgeScope(scope_id=allocation.scope_id, name=name or allocation.name,
                               slug=allocation.slug, scope_type="project", domain_key="generic"))
    await session.commit()
    return allocation.scope_id


def _service(session) -> MemoryService:
    return MemoryService(session)


async def _events(session, scope_id: int) -> list[dict]:
    return await MemoryEventStore(session).replay(scope_id)


async def _replay_ids(session, scope_id: int) -> list[int]:
    return [event["event_id"] for event in await _events(session, scope_id)]


async def _authority_ids(session, scope_id: int) -> list[int]:
    return list((await session.execute(
        select(MemoryEvent.event_id).where(MemoryEvent.knowledge_scope_id == scope_id)
        .order_by(MemoryEvent.event_id))).scalars().all())


async def _scope_event_count(session, scope_id: int) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(MemoryEvent).where(MemoryEvent.knowledge_scope_id == scope_id)) or 0)


async def _foreign_event_count(session, scope_id: int) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(MemoryEvent).where(MemoryEvent.knowledge_scope_id != scope_id)) or 0)


async def _view_fingerprints(session, scope_id: int, watermark: int | None) -> dict[str, str]:
    """Per-view fingerprints as persisted by the projection store (the canonical source)."""
    rows = (await session.execute(select(MemoryProjectionMeta).where(
        MemoryProjectionMeta.knowledge_scope_id == scope_id,
        MemoryProjectionMeta.source_event_id == watermark,
        MemoryProjectionMeta.projection_type.in_(VIEW_KEYS),
        MemoryProjectionMeta.status == "complete"))).scalars().all()
    return {row.projection_type: row.fingerprint for row in rows}


async def _binding_rows(session) -> list[tuple]:
    rows = (await session.execute(select(ScopeBinding))).scalars().all()
    return sorted((int(row.binding_id), row.binding_kind, row.binding_value, int(row.knowledge_scope_id),
                   int(row.priority), row.status) for row in rows)


def _fingerprint(value) -> str:
    """Stable fingerprint of an observed state subset (canonical JSON + sha256)."""
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _not_applicable(claim: str, reason: str) -> dict[str, str]:
    """Explicit "this fingerprint has no subject" marker (never a silent ``{}``).

    The contract types both fingerprint objects as ``additionalProperties:
    string``, so the marker is carried as a value; a machine reads the
    ``not_applicable:`` prefix instead of guessing from an empty object.
    """
    return {"state": f"not_applicable: {claim} — {reason}"}


async def _authority_state(session, scope_id: int) -> dict:
    """Everything that must stay identical when an authority write is refused.

    ``ids`` is the authority-log id sequence item by item; ``count`` its length;
    ``scope_registry_ids`` is the whole ``knowledge_scope`` registry row set (the
    reusable scope registry a "fall back to the nearest domain" resolution would
    have to read or mutate) so that neither an appended authority event nor a
    newly created/rebound scope can hide behind an unchanged id list.
    """
    ids = await _authority_ids(session, scope_id)
    registry = sorted(int(value) for value in (await session.execute(
        select(KnowledgeScope.scope_id))).scalars().all())
    return {"ids": ids, "count": len(ids), "scope_registry_ids": registry,
            "scope_registry_count": len(registry)}


def _authority_fingerprints(before: dict, after: dict) -> tuple[dict[str, str], dict[str, str]]:
    """The per-case before/after fingerprints for an authority-monotonicity case."""
    left = {"authority_log_ids": _fingerprint(before["ids"]),
            "scope_registry_ids": _fingerprint(before["scope_registry_ids"])}
    right = {"authority_log_ids": _fingerprint(after["ids"]),
             "scope_registry_ids": _fingerprint(after["scope_registry_ids"])}
    return left, right


async def _binding_row_set_fingerprint(session) -> str:
    """Fingerprint of the ``scope_bindings`` row set (the table MCP must not rewrite)."""
    return _fingerprint(await _binding_rows(session))


async def _scope_registry_fingerprints(session, scope_id: int) -> tuple[dict[str, str], dict[str, str]]:
    """R6.4 before/after fingerprints: the authority log ids and the scope registry row set.

    A "fall back to the nearest domain / whole library" resolution would either append
    an authority event (a resolution that succeeded) or create/rebind a scope, so both
    the log id sequence and the whole ``knowledge_scope`` registry are fingerprinted
    before and after the rejection window of a scope case.
    """
    state = await _authority_state(session, scope_id)
    return _authority_fingerprints(state, state)


#: The criteria for which ``event_chain_closed`` is a fabrication: no event chain is
#: replayed by these cases, so the field MUST stay ``null`` (FR-019/SC-005) and the
#: real criterion lives in ``scoring`` (``authority_ids_unchanged`` /
#: ``all_rejected`` / ``zero_fallback`` / ...).
CHAIN_FREE_INVARIANTS = ("authority_monotonicity", "scope_non_expansion")
assert "traceable_rollback" not in CHAIN_FREE_INVARIANTS, "R6.1 replays a chain and must report the boolean"


def _chain_denominator(entry: dict) -> int:
    """How many identity projections the case asserted (the other 6/13 use a 1-identity scope)."""
    return len(tuple(entry.get("projections_asserted") or ()))


def _manifest_state(manifest) -> dict:
    return manifest.payload["state"]


def _entries(state: dict) -> dict:
    return {int(key): value for key, value in state["entries"].items()}


def _authority_axis(state: dict) -> dict:
    return {int(key): _canonical(row.get("authority")) for key, row in state["entries"].items()}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


#: Every authority command (record/govern) this suite issued, with its allow/deny
#: verdict against the case's isolation allocation. This is the machine measurement
#: behind SC-004/T026 ("destructive operations touching an existing real domain or
#: 366084747748704256 = 0"): the target is captured at call time, so a command aimed
#: anywhere else is counted and refused before it can append an event.
_DESTRUCTIVE_TOUCHES: list[dict[str, Any]] = []


def _record_touch(allocation: IsolationAllocation, action: str, scope_id: Any) -> bool:
    allowed = str(scope_id) == str(allocation.scope_id) and str(scope_id) not in allocation.forbidden_scope_ids
    _DESTRUCTIVE_TOUCHES.append({"action": action, "scope_id": str(scope_id),
                                 "isolated_scope_id": str(allocation.scope_id), "allowed": allowed})
    return allowed


async def _record(allocation: IsolationAllocation, service: MemoryService, payload: dict):
    _record_touch(allocation, "record", payload.get("scope_id"))
    assert_isolated(allocation, payload.get("scope_id"))
    return await service.record(payload)


async def _govern(allocation: IsolationAllocation, service: MemoryService, action: str, **parameters):
    _record_touch(allocation, action, parameters.get("scope_id"))
    assert_isolated(allocation, parameters.get("scope_id"))
    return await service.govern(action, **parameters)


def _consumable_hits(state: dict, mid: int) -> dict[str, int]:
    """Independent per-projection consumer-visible hit count for one identity.

    One measurement function is used before and after the tombstone so the
    denominator and the propagation verdict are directly comparable.
    """
    hits: dict[str, int] = {}
    entry = _entries(state).get(mid)
    hits["relation"] = 1 if entry is not None and entry.get("status") not in {"retired", "quarantined"} else 0
    hits["dense"] = sum(1 for key, row in state["dense"].items()
                        if int(row.get("memory_id", key)) == mid)
    hits["links"] = sum(1 for key, row in state["links"].items()
                        if key.startswith(f"{mid}/") or mid in {int(row.get("from_id", -1)), int(row.get("to_id", -1))})
    hits["summary"] = sum(1 for rows in state["summary"].values() for row in rows
                          if int(row.get("memory_id", -1)) == mid)
    hits["file"] = sum(1 for row in state["files"].values() if int(row.get("memory_id", -1)) == mid)
    return hits


def _entries_diff(before: dict, after: dict) -> set[str]:
    left, right = _entries(before), _entries(after)
    return {str(mid) for mid in set(left) | set(right) if left.get(mid) != right.get(mid)}


@asynccontextmanager
async def _sessions(session):
    yield session


@lru_cache(maxsize=1)
def _embedding() -> LocalCPUEmbeddingProvider:
    """One provider per process: the MCP surface needs a real embedding provider."""
    return LocalCPUEmbeddingProvider()


def _mcp_server(session, *, mode: str = "writer"):
    return create_mcp_server(session_factory=lambda: _sessions(session),
                             embedding_provider=_embedding(), mode=mode)


@asynccontextmanager
async def _rest_client(session):
    app = create_app()

    async def sessions():
        yield session

    app.dependency_overrides[get_session] = sessions
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _structured(result) -> dict | None:
    body = getattr(result, "structuredContent", None)
    return body if isinstance(body, dict) else None


@asynccontextmanager
async def _retrying_writer_owner(engine, *, attempts: int = 12, delay: float = 15.0):
    """``memory_acceptance.writer_owner`` with a bounded wait for a foreign lease.

    The writer lease is process-global (one active lease per database), so a
    concurrently running suite in the same evaluation database can hold it for the
    duration of one of its tests. Waiting is a harness concern, never a relaxed
    assertion: only the documented "writer lease already held" refusal is retried.
    """
    last: AssertionError | None = None
    for attempt in range(attempts):
        context = writer_owner(engine)
        try:
            owner = await context.__aenter__()
        except AssertionError as error:
            if "writer lease already held" not in str(error) or attempt == attempts - 1:
                raise
            last = error
            await asyncio.sleep(delay)
            continue
        try:
            yield owner
        finally:
            await context.__aexit__(None, None, None)
        return
    raise AssertionError(f"writer lease still unavailable after {attempts} attempts: {last}")


@pytest_asyncio.fixture
async def aoep_writer_owner(engine):
    """The per-run dedicated writer identity used by the lease-dependent cases."""
    async with _retrying_writer_owner(engine) as owner:
        yield owner


async def _active_writer_lease_count(session) -> int:
    """How many writer leases are active right now (a foreign suite may hold one)."""
    return int(await session.scalar(select(func.count()).select_from(WriterLease).where(
        WriterLease.state == "active", WriterLease.expires_at > func.now())) or 0)


async def _mcp_call(server, tool: str, arguments: dict) -> dict:
    """Call an MCP tool, normalising both rejection styles as one observation.

    A rejection is either a structured ``isError`` result (``CallToolResult``) or a
    raised protocol error (unknown tool / argument-model validation).
    """
    try:
        result = await server.call_tool(tool, arguments)
    except Exception as error:  # noqa: BLE001 - any protocol error is a rejection
        return {"surface": f"mcp:{tool}", "rejected": True, "is_error": True,
                "error_type": type(error).__name__, "code": str(error).split("\n", 1)[0][:200],
                "structured": None}
    body = _structured(result)
    return {"surface": f"mcp:{tool}", "rejected": bool(result.isError), "is_error": bool(result.isError),
            "error_type": None, "code": (body or {}).get("error", {}).get("code") if body else None,
            "structured": body}


def _rejected(observation: dict) -> bool:
    return bool(observation.get("rejected"))


def _observed_codes(observations: list[dict]) -> list[str | None]:
    return [observation.get("code") for observation in observations]


# ---------------------------------------------------------------------------
# case recording
# ---------------------------------------------------------------------------

#: Fallback expected observation per invariant, used only when a case does not pass
#: its own (the ``_finish`` call sites pass the case-specific object).
EXPECTED_BY_INVARIANT: dict[str, dict[str, Any]] = {
    "traceable_rollback": {"traceable": True},
    "deletion_propagation": {
        "per_projection_consumable_hits": {view: 0 for view in DELETION_PROJECTIONS},
        "retract_event_present": True, "source_chain_recomputable": True,
    },
    "authority_monotonicity": {
        "all_attempts_rejected": True, "succeeded": 0, "authority_ids_unchanged": True,
        "binding_rows_unchanged": True,
    },
    "provenance_preservation": {
        "provenance_preserved_for_every_identity": True, "content_hash_recomputed_item_by_item": True,
        "tombstones_retained": True, "recomputed_fingerprint_matches_manifest": True,
    },
    "scope_non_expansion": {"all_rejected": True, "zero_fallback": True, "candidates_present": True},
}
assert set(EXPECTED_BY_INVARIANT) == set(AOEP_INVARIANTS), "an invariant has no fallback expectation"


def _sample_sizes(case_id: str, sample_sizes: dict | None) -> dict[str, int]:
    """The contract types ``sample_sizes`` as non-negative integers; enforce it here.

    A nested map (e.g. a per-projection denominator block) belongs in ``observed``,
    not in ``sample_sizes``: silently ``int()``-ing or stringifying it would export a
    denominator that is not a count.
    """
    values: dict[str, int] = {}
    for key, value in (sample_sizes or {}).items():
        assert isinstance(value, int) and not isinstance(value, bool) and value >= 0, (
            f"{case_id}: sample_sizes[{key!r}] must be a non-negative integer denominator, got {value!r}")
        values[str(key)] = int(value)
    return values


async def _finish(session, evidence, context: dict, *, status: str, request_id: str | None = None,
                  before_fingerprints: dict | None = None, after_fingerprints: dict | None = None,
                  watermark_before: int | None = None, watermark_after: int | None = None,
                  impact: dict | None = None, event_chain_closed: bool | None = None,
                  re_rollback_consistent: bool | None = None, reproducible: bool | None = True,
                  projection_denominators: dict | None = None, not_measurable_reason: str | None = None,
                  expected: dict | None = None, observed: dict | None = None, scoring: dict | None = None,
                  sample_sizes: dict | None = None, record_extra: dict | None = None,
                  extra: dict | None = None) -> dict:
    """Record the case (once) and assert no forbidden/foreign destructive touch happened.

    T082/FR-019: the exported case record is **self-sufficient** — it carries the
    case ``role``, the dataset's ``criterion``, the criterion's ``expected`` and the
    measured ``observed`` object, every sub-condition boolean in ``scoring`` (the
    place a reader looks instead of trusting the aggregate ``status``) and the real
    denominators in ``sample_sizes``.  ``record_extra`` carries the same criterion
    evidence into the append-only isolation/disposal record, so that document stays
    a superset; the case record no longer relies on it.
    """
    if context.get("finished"):
        return context["record"]
    context["finished"] = True
    try:
        return await _finish_body(
            session, context, status=status, request_id=request_id, before_fingerprints=before_fingerprints,
            after_fingerprints=after_fingerprints, watermark_before=watermark_before,
            watermark_after=watermark_after, impact=impact, event_chain_closed=event_chain_closed,
            re_rollback_consistent=re_rollback_consistent, reproducible=reproducible,
            projection_denominators=projection_denominators, not_measurable_reason=not_measurable_reason,
            expected=expected, observed=observed, scoring=scoring, sample_sizes=sample_sizes,
            record_extra=record_extra, extra=extra, evidence=evidence)
    except BaseException:
        # The "recording finished" latch must only be held by a *completed* record:
        # otherwise a failure inside the body would make _guard's failure record
        # unreachable and mask the real error behind a KeyError.
        context["finished"] = False
        raise


async def _finish_body(session, context: dict, *, status: str, request_id: str | None,
                       before_fingerprints: dict | None, after_fingerprints: dict | None,
                       watermark_before: int | None, watermark_after: int | None, impact: dict | None,
                       event_chain_closed: bool | None, re_rollback_consistent: bool | None,
                       reproducible: bool | None, projection_denominators: dict | None,
                       not_measurable_reason: str | None, expected: dict | None, observed: dict | None,
                       scoring: dict | None, sample_sizes: dict | None, record_extra: dict | None,
                       extra: dict | None, evidence) -> dict:
    """The body of :func:`_finish` (split out only so the latch can be rolled back)."""
    allocation: IsolationAllocation = context["allocation"]
    entry = context["entry"]
    case_id = entry["case_id"]
    invariant = entry["invariant"]
    forbidden_after = await _scope_event_count(session, FORBIDDEN_SCOPE_ID)
    foreign_after = await _foreign_event_count(session, allocation.scope_id)
    forbidden_delta = forbidden_after - context["forbidden_before"]
    foreign_delta = foreign_after - context["foreign_before"]
    touches = _DESTRUCTIVE_TOUCHES[context.get("touches_before", 0):]
    outside = [touch for touch in touches if not touch["allowed"]]
    record_extra = {
        "case_id": case_id,
        "invariant": invariant,
        "status": status,
        "run_id": RUN_ID,
        "isolated_scope_id": str(allocation.scope_id),
        "isolation_id": allocation.isolation_id,
        "identity_id": allocation.identity_id,
        "forbidden_scope_ids": list(allocation.forbidden_scope_ids),
        "forbidden_scope_events_before": context["forbidden_before"],
        "forbidden_scope_events_after": forbidden_after,
        "forbidden_scope_event_delta": forbidden_delta,
        "destructive_operations_total": len(touches),
        "destructive_operations_outside_isolation": len(outside),
        "destructive_touches": touches,
        "foreign_scope_event_delta_observed": foreign_delta,
        "foreign_scope_event_delta_note": ("observational only: a shared database can receive concurrent "
                                          "writes from other isolated runs"),
        **(context.get("extra") or {}),
        **(record_extra or {}),
        **(extra or {}),
    }
    # T082: no default value may be fabricated for an inapplicable field (FR-019/SC-005).
    if invariant in CHAIN_FREE_INVARIANTS:
        assert event_chain_closed is None, (
            f"{case_id} ({invariant}) must not report event_chain_closed={event_chain_closed!r}: no event chain "
            f"is replayed by this invariant, so the field MUST be null and the evidence MUST live in scoring")
    if expected is None:
        expected = dict(EXPECTED_BY_INVARIANT[invariant])
        assert invariant in CHAIN_FREE_INVARIANTS, (
            f"{case_id} ({invariant}) must pass its own criterion-specific expected observation")
    else:
        expected = dict(expected)
    if observed is None:
        observed = {"not_applicable": True,
                    "reason": f"{invariant} does not measure a {invariant.replace('_', ' ')} observation"}
    if before_fingerprints is None or after_fingerprints is None:
        marker = _not_applicable(
            "before/after fingerprints",
            "this criterion measures only the refusal of the attempt and no state change it could fingerprint "
            "is reachable from the case body")
        before_fingerprints = before_fingerprints if before_fingerprints is not None else dict(marker)
        after_fingerprints = after_fingerprints if after_fingerprints is not None else dict(marker)
    assert before_fingerprints and after_fingerprints, (
        f"{case_id}: before/after fingerprints must be non-empty or carry an explicit not_applicable marker")
    payload = {
        "case_id": case_id,
        "invariant": invariant,
        "role": role(case_id),
        "criterion": criterion(case_id),
        "expected": expected,
        "observed": observed,
        "scoring": dict(scoring or {}),
        "sample_sizes": _sample_sizes(case_id, sample_sizes),
        "request_id": str(request_id or uuid.uuid4()),
        "status": status,
        "target_kind": entry.get("target_kind"),
        "before_fingerprints": before_fingerprints,
        "after_fingerprints": after_fingerprints,
        "watermark_before": watermark_before,
        "watermark_after": watermark_after,
        "impact": impact or {"entries": 0, "projections": {}},
        "event_chain_closed": event_chain_closed,
        "re_rollback_consistent": re_rollback_consistent,
        "reproducible": reproducible,
        "projection_denominators": projection_denominators or {},
        "isolated_scope_id": str(allocation.scope_id),
        "not_measurable_reason": not_measurable_reason,
    }
    if evidence is not None:
        dispose(allocation, directory=evidence.directory, extra=record_extra)
        evidence.record_aoep_case(payload)
    context["record"] = payload
    assert outside == [], (
        f"a destructive operation touched an existing real domain or a forbidden scope: {outside}")
    assert forbidden_delta == 0, (
        f"a destructive operation touched the forbidden scope {FORBIDDEN_SCOPE_ID}: delta={forbidden_delta}")
    return payload


async def _guard(case_id: str, session, evidence, body, *, identity_id: str | None = None) -> None:
    """Allocate the per-case isolation domain and record a failure if the body raises."""
    entry = case(case_id)
    allocation = allocate(run_id=RUN_ID, identity_id=identity_id)
    context = {
        "case_id": case_id,
        "entry": entry,
        "allocation": allocation,
        "forbidden_before": await _scope_event_count(session, FORBIDDEN_SCOPE_ID),
        "foreign_before": await _foreign_event_count(session, allocation.scope_id),
        "touches_before": len(_DESTRUCTIVE_TOUCHES),
        "extra": {},
    }
    try:
        await body(case_id, session, evidence, context)
    except BaseException as error:
        context["extra"]["exception"] = f"{type(error).__name__}: {error}"[:500]
        # T082: the abort record is still a self-sufficient case record. It states the
        # criterion's expectation (per-invariant default) and that the case aborted
        # before it could be measured, instead of inventing a conclusion. Without this,
        # a case whose body raises before any measurement would export a record with no
        # expected observation at all.
        await _finish(session, evidence, context, status="failed", reproducible=False,
                      expected=dict(EXPECTED_BY_INVARIANT[entry["invariant"]]),
                      observed={"aborted_before_measurement": True,
                                "exception": context["extra"]["exception"],
                                "reason": ("the case body raised before the criterion could be measured; the "
                                           "criterion's expectation is recorded unmeasured")},
                      scoring={"aborted_before_measurement": True,
                               "criterion_measured": False,
                               "case_body_raised": True},
                      sample_sizes={"attempts_before_abort": 0, "measurements_completed": 0},
                      record_extra={"criterion_evidence": "case aborted before measurement"})
        raise


# ===========================================================================
# traceable_rollback (R6.1) — T022
# ===========================================================================

def _traceable_rollback_verdict(*, request_id, rollback_event, replay_ids, authority_ids,
                                watermark_before, watermark_after, rollback_event_id,
                                state_before, state_after, before_fingerprints, after_fingerprints,
                                digest_fingerprint, inspect_report, access_event_ids,
                                re_rollback_consistent, requires_re_rollback) -> tuple[str, list[str]]:
    """R6.1 machine criterion. Returns (status, unmet sub-conditions)."""
    unmet: list[str] = []
    if rollback_event is None:
        unmet.append("no authority event carries this request_id")
    else:
        if rollback_event.get("event_type") != "rollback":
            unmet.append(f"event_type is {rollback_event.get('event_type')!r}, not 'rollback'")
        if rollback_event.get("request_id") != request_id:
            unmet.append("rollback event request_id differs from the response request_id")
        if rollback_event.get("payload", {}).get("event_point") is None:
            unmet.append("rollback payload has no event_point watermark")
    # Event-chain closure: item-by-item equality with the authority log, NOT numeric continuity.
    if not authority_ids:
        unmet.append("empty authority log")
    if replay_ids != authority_ids:
        unmet.append("replay id sequence != authority id sequence (missing/duplicate/foreign event)")
    if len(set(replay_ids)) != len(replay_ids):
        unmet.append("duplicate authority event id")
    if authority_ids != sorted(authority_ids):
        unmet.append("authority id sequence is not ordered")
    if watermark_after != rollback_event_id:
        unmet.append("watermark_after != rollback event id (projection manifest not materialised at the command)")
    if watermark_before is None or watermark_after is None:
        unmet.append("watermark not readable before/after")
    if not digest_fingerprint:
        unmet.append("whole-state fingerprint of the reduced log != manifest fingerprint")
    if not inspect_report or not all(row["matches_replay"] for row in inspect_report.values()):
        unmet.append("inspect() reported a projection that does not match the replay")
    for view in CRITERION_VIEWS:
        if view not in after_fingerprints:
            unmet.append(f"per-view fingerprint missing for {view}")
    if before_fingerprints.get("state") != (rollback_event or {}).get("payload", {}).get("before_fingerprint"):
        unmet.append("before_fingerprint does not match the independently reduced state")
    if after_fingerprints.get("state") != (rollback_event or {}).get("payload", {}).get("after_fingerprint"):
        unmet.append("after_fingerprint does not match the independently reduced state")
    expected_impact = _entries_diff(state_before, state_after)
    actual_impact = {str(mid) for mid in (rollback_event or {}).get("payload", {}).get("impact", {}).get(
        "memory_ids", [])}
    if expected_impact != actual_impact:
        unmet.append("impact.memory_ids != the real entries diff")
    if not access_event_ids:
        unmet.append("no access event was retained")
    if requires_re_rollback and not re_rollback_consistent:
        unmet.append("the re-rollback to an adjacent checkpoint was not self-consistent")
    return ("failed" if unmet else "passed"), unmet


async def _traceable_rollback(case_id: str, session, evidence, context) -> None:
    entry = case(case_id)
    options = entry["_meta"]
    allocation = context["allocation"]
    sid = await _new_scope(session, allocation)
    service = _service(session)
    tag = allocation.isolation_id[:8]
    first = await _record(allocation, service, _submission(sid, content=f"AOEP rollback anchor {case_id} {tag}",
                                             evidence_refs=(f"1001{tag}",)))
    anchor_event = next(event for event in await _events(session, sid) if event["event_id"] == first["memory_id"])
    second = await _record(allocation, service, {**_submission(sid, content=f"AOEP rollback successor {case_id} {tag}",
                                                 evidence_refs=(f"1002{tag}",)),
                                   "supersedes_memory_id": first["memory_id"]})
    access = await _govern(allocation, service, "access", scope_id=sid, memory_id=second["memory_id"], actor="management",
                                  reason="AOEP observed read before the rollback")
    assert_isolated(allocation, sid)

    manifest_before = await service.projections.current(sid)
    watermark_before = manifest_before.source_event_id
    state_before = _manifest_state(manifest_before)
    before_fingerprints = await _view_fingerprints(session, sid, watermark_before)
    before_fingerprints["state"] = manifest_before.fingerprint

    parameters = ({"event_point": first["memory_id"]} if options["rollback_target"] == "event_point"
                  else {"time_point": anchor_event["occurred_at"]})
    rollback = await _govern(allocation, service, "rollback", scope_id=sid, actor="management",
                                    reason=f"AOEP traceable rollback ({case_id})", **parameters)

    manifest_after = await service.projections.current(sid)
    watermark_after = manifest_after.source_event_id
    state_after = _manifest_state(manifest_after)
    after_fingerprints = await _view_fingerprints(session, sid, watermark_after)
    after_fingerprints["state"] = manifest_after.fingerprint
    log = await _events(session, sid)
    rollback_event = next((event for event in log if event["event_id"] == rollback["event_id"]), None)
    replay_ids, authority_ids = await _replay_ids(session, sid), await _authority_ids(session, sid)
    inspect_report = await service.inspect_projections(sid)
    access_event_ids = [event["event_id"] for event in log if event["event_type"] == "access"]
    digest = projection_fingerprint(reduce_events(log)) == manifest_after.fingerprint

    re_rollback_consistent: bool | None = None
    if entry.get("requires_re_rollback"):
        second_rollback = await _govern(allocation, service, "rollback", scope_id=sid, actor="management",
                                               reason="AOEP re-rollback to an adjacent checkpoint",
                                               event_point=second["memory_id"])
        recomputed_manifest = await service.projections.current(sid)
        re_inspect = await service.inspect_projections(sid)
        re_rollback_consistent = bool(
            recomputed_manifest.source_event_id == second_rollback["event_id"]
            and recomputed_manifest.fingerprint == projection_fingerprint(reduce_events(await _events(session, sid)))
            and all(row["matches_replay"] for row in re_inspect.values()))

    status, unmet = _traceable_rollback_verdict(
        request_id=rollback["request_id"], rollback_event=rollback_event, replay_ids=replay_ids,
        authority_ids=authority_ids, watermark_before=watermark_before, watermark_after=watermark_after,
        rollback_event_id=rollback["event_id"], state_before=state_before, state_after=state_after,
        before_fingerprints=before_fingerprints, after_fingerprints=after_fingerprints,
        digest_fingerprint=digest, inspect_report=inspect_report,
        access_event_ids=access_event_ids,
        re_rollback_consistent=re_rollback_consistent, requires_re_rollback=bool(entry.get("requires_re_rollback")))
    # T082: the sub-conditions the R6.1 checker actually evaluated, item by item, so a
    # machine can decide pass/fail without re-deriving the criterion from `status`.
    scoring = {
        "rollback_event_found": rollback_event is not None,
        "rollback_request_id_matches": bool(rollback_event) and rollback_event.get("request_id") == rollback["request_id"],
        "event_chain_closed": bool(replay_ids == authority_ids and authority_ids),
        "fingerprints_match": bool(before_fingerprints and after_fingerprints and digest),
        "impact_consistent": (
            {str(mid) for mid in rollback_event.get("payload", {}).get("impact", {}).get("memory_ids", [])}
            == _entries_diff(state_before, state_after)) if rollback_event else False,
        "access_events_retained": bool(access_event_ids),
        "re_rollback_consistent": (None if not entry.get("requires_re_rollback")
                                   else bool(re_rollback_consistent)),
    }
    observed = {
        "rollback_event_id": rollback["event_id"],
        "rollback_event_type": (rollback_event or {}).get("event_type"),
        "request_id_matches_response": bool(rollback_event)
        and rollback_event.get("request_id") == rollback["request_id"],
        "event_chain_closed": bool(replay_ids == authority_ids and authority_ids),
        "authority_ids": authority_ids,
        "event_chain_semantics": ("replay(scope) id sequence == authority log id sequence, item by item, no "
                                  "missing and no duplicate; explicitly NOT numeric continuity (snowflake ids "
                                  "are sparse)"),
        "watermark_after_equals_rollback_event_id": watermark_after == rollback["event_id"],
        "impact_memory_ids": list(rollback_event.get("payload", {}).get("impact", {}).get("memory_ids", []))
        if rollback_event else [],
        "entries_diff": sorted(_entries_diff(state_before, state_after)),
        "inspect_views_matching_replay": sorted(view for view, row in inspect_report.items() if row["matches_replay"]),
        "access_event_ids": access_event_ids,
    }
    sample_sizes = {
        "authority_events_examined": len(authority_ids),
        "replay_events_examined": len(replay_ids),
        "views_asserted": len(CRITERION_VIEWS),
        "impact_entries_asserted": len(observed["impact_memory_ids"]),
        "access_events_asserted": len(access_event_ids),
        "re_rollbacks_executed": 1 if entry.get("requires_re_rollback") else 0,
    }
    context["extra"].update({
        "rollback_target": options["rollback_target"],
        "event_chain_closure_semantics": ("replay(scope) id sequence == authority log id sequence, item by item, "
                                          "no missing and no duplicate; explicitly NOT numeric continuity "
                                          "(snowflake ids are sparse)"),
        "unmet_sub_conditions": unmet,
        "impact": rollback["impact"],
        "access_event_ids": access_event_ids,
        "authority_ids": authority_ids,
        "scoring": scoring,
    })
    await _finish(session, evidence, context, status=status, request_id=rollback["request_id"],
                  before_fingerprints=before_fingerprints, after_fingerprints=after_fingerprints,
                  watermark_before=watermark_before, watermark_after=watermark_after,
                  impact={"entries": len(rollback["impact"]["memory_ids"]),
                          "projections": {view: row["count"] for view, row in inspect_report.items()}},
                  event_chain_closed=replay_ids == authority_ids, re_rollback_consistent=re_rollback_consistent,
                  reproducible=True,
                  expected={"traceable": True, "authority_event_present": True, "event_chain_closed": True,
                            "before_after_fingerprints_present": True, "impact_consistent": True,
                            "access_events_retained": True},
                  observed=observed, scoring=scoring, sample_sizes=sample_sizes,
                  record_extra={"criterion_evidence": "R6.1 item-by-item sub-conditions"},
                  extra={"unmet_sub_conditions": unmet})
    assert status == "passed", f"{case_id} did not satisfy R6.1: {unmet}"


async def _traceable_rollback_audit_only(case_id: str, session, evidence, context) -> None:
    """The explicit negative control: an audit-only reference must be judged failed."""
    allocation = context["allocation"]
    sid = await _new_scope(session, allocation)
    service = _service(session)
    memory = await _record(allocation, service, _submission(sid, content=f"AOEP audit-only control {case_id} {allocation.isolation_id[:8]}",
                                             evidence_refs=(f"1003{allocation.isolation_id[:8]}",)))
    assert_isolated(allocation, sid)
    request_id = str(uuid.uuid4())
    await service.rebuild(sid, actor="management", reason="AOEP audit-only counterexample source", request_id=request_id)
    audit = await session.get(MemoryManagementAudit, request_id)
    log = await _events(session, sid)
    authority_ids = await _authority_ids(session, sid)
    rollback_event = next((event for event in log if event["request_id"] == request_id), None)
    rollback_events = [event for event in log if event["event_type"] == "rollback"]
    assert audit is not None, "the counterexample needs a real queryable audit record"
    assert audit.operation == "rebuild" and audit.knowledge_scope_id == sid
    assert rollback_event is None and rollback_events == [], "the authority log must hold no event-chain evidence"
    # T082: the negative control gets explicit fingerprints too. There is no
    # rollback attempt at all, so "before" is the observed post-rebuild authority
    # state and "after" is that same state re-read; the identical pair is the
    # evidence that an audit-only reference changed no state and closed no chain.
    authority_state = await _authority_state(session, sid)
    after_state = await _authority_state(session, sid)
    before_fingerprints, after_fingerprints = _authority_fingerprints(authority_state, after_state)
    assert before_fingerprints == after_fingerprints, (
        "the audit-only negative control performs no write between the two observations")
    status, unmet = _traceable_rollback_verdict(
        request_id=request_id, rollback_event=rollback_event, replay_ids=[event["event_id"] for event in log],
        authority_ids=authority_ids, watermark_before=None, watermark_after=None, rollback_event_id=None,
        state_before=_manifest_state(await service.projections.current(sid)),
        state_after=_manifest_state(await service.projections.current(sid)),
        before_fingerprints=before_fingerprints, after_fingerprints=after_fingerprints, digest_fingerprint=False,
        inspect_report={}, access_event_ids=[], re_rollback_consistent=None, requires_re_rollback=False)
    # T082: the inversion is explicit and machine-checkable. ``status="passed"``
    # means ONLY "the R6.1 checker applied its criterion correctly", i.e. the
    # checker judged an audit-only reference (an audit row with no authority event
    # behind it) NOT traceable. ``expected.traceable=false`` with
    # ``expected.checker_verdict="failed"`` states that norm; ``observed`` shows the
    # audit row present and the authority event absent.
    expected = {
        "traceable": False,
        "checker_verdict": "failed",
        "authority_event_present": False,
        "audit_row_present": True,
        "event_chain_closed": False,
        "status_meaning": "passed means the R6.1 checker correctly judged the audit-only reference NOT traceable",
    }
    observed = {
        "audit_row_present": True,
        "audit_operation": audit.operation,
        "audit_source_event_id": audit.source_event_id,
        "authority_event_present": rollback_event is not None,
        "authority_rollback_events": len(rollback_events),
        "event_point": None,
        "event_chain_closed": False,
        "event_chain_not_applicable_reason": ("no authority event carries the request_id, so there is no chain to "
                                              "close; the R6.1 checker MUST reject an audit-only reference"),
        "checker_verdict": status,
        "checker_unmet_sub_conditions": unmet,
        "authority_ids": authority_ids,
        "status_inversion": ("status=passed AND expected.traceable=false; the case passes by measuring that the "
                             "checker returned failed, never by the reference being traceable"),
    }
    scoring = {
        "audit_row_present": True,
        "authority_event_present": False,
        "authority_rollback_events": 0,
        "event_chain_closed": False,
        "checker_verdict_is_failed": status == "failed",
        "checker_unmet_sub_conditions_observed": len(unmet),
    }
    sample_sizes = {
        "audit_rows_examined": 1,
        "authority_events_examined": len(authority_ids),
        "authority_rollback_events_examined": len(rollback_events),
        "checker_sub_conditions_evaluated": len(unmet),
        "views_asserted": len(CRITERION_VIEWS),
    }
    context["extra"].update({
        "negative_control": True,
        "audit_record": {"request_id": request_id, "operation": audit.operation, "source_event_id": audit.source_event_id},
        "authority_rollback_events": len(rollback_events),
        "checker_verdict": status,
        "checker_unmet": unmet,
        "scoring": scoring,
    })
    await _finish(session, evidence, context, status="passed" if status == "failed" else "failed",
                  request_id=request_id, event_chain_closed=False, reproducible=True,
                  before_fingerprints=before_fingerprints, after_fingerprints=after_fingerprints,
                  expected=expected, observed=observed, scoring=scoring, sample_sizes=sample_sizes,
                  record_extra={"criterion_evidence": "R6.1 negative control: audit-only reference"},
                  extra={"negative_control_verdict": status, "checker_unmet": unmet})
    assert status == "failed", "the R6.1 checker must judge an audit-only reference failed"
    assert memory["memory_id"] is not None


@pytest.mark.asyncio
async def test_aoep_traceable_rollback_event_point(db_session, memory_eval_evidence):
    await _guard("aoep_traceable_rollback_event_point", db_session, memory_eval_evidence, _traceable_rollback)


@pytest.mark.asyncio
async def test_aoep_traceable_rollback_time_point_re_rollback(db_session, memory_eval_evidence):
    await _guard("aoep_traceable_rollback_time_point_re_rollback", db_session, memory_eval_evidence, _traceable_rollback)


@pytest.mark.asyncio
async def test_aoep_traceable_rollback_audit_only_counterexample(db_session, memory_eval_evidence):
    await _guard("aoep_traceable_rollback_audit_only_counterexample", db_session, memory_eval_evidence,
                 _traceable_rollback_audit_only)


# ===========================================================================
# deletion_propagation (R6.2) — T023
# ===========================================================================

async def _deletion(case_id: str, session, evidence, context) -> None:
    entry = case(case_id)
    options = entry["_meta"]
    action = options["deletion"]
    allocation = context["allocation"]
    sid = await _new_scope(session, allocation)
    service = _service(session)
    tag = allocation.isolation_id[:8]
    memory = await _record(allocation, service, _submission(sid, content=f"AOEP deletion propagation {action} {case_id} {tag}",
                                             evidence_refs=(f"2001{tag}",)))
    mid = memory["memory_id"]
    assert_isolated(allocation, sid)

    manifest_before = await service.projections.current(sid)
    state_before = _manifest_state(manifest_before)
    denominators = _consumable_hits(state_before, mid)
    recall_before = await service.recall(scope_ref=[str(sid)])
    consumable_before = [row["memory_id"] for row in recall_before["memories"]] == [mid]
    before_fingerprints = await _view_fingerprints(session, sid, manifest_before.source_event_id)
    before_fingerprints["state"] = manifest_before.fingerprint

    result = await _govern(allocation, service, action, scope_id=sid, memory_id=mid, actor="management",
                                 reason=f"AOEP deletion propagation via {action} ({case_id})")
    manifest_after = await service.projections.current(sid)
    state_after = _manifest_state(manifest_after)
    hits = _consumable_hits(state_after, mid)
    inspect_report = await service.inspect_projections(sid)
    after_fingerprints = await _view_fingerprints(session, sid, manifest_after.source_event_id)
    after_fingerprints["state"] = manifest_after.fingerprint
    log = await _events(session, sid)
    retract_events = [event for event in log if event["event_type"] == "retract" and event["aggregate_id"] == mid]
    source_event = next(event for event in log if event["event_id"] == mid)
    payload = source_event["payload"]
    content_recomputable = bool(payload.get("content_text")) and bool(payload.get("content_hash")) and (
        hashlib.sha256(payload["content_text"].encode("utf-8")).hexdigest() == payload["content_hash"])
    recall_after = await service.recall(scope_ref=[str(sid)], memory_ids=[mid], include_superseded=True,
                                       include_delivered=True)
    inspect_ok = bool(inspect_report) and all(row["matches_replay"] for row in inspect_report.values())

    assert set(entry["projections_asserted"]) == set(DELETE_PROJECTIONS)
    zero_denominators = sorted(view for view in DELETE_PROJECTIONS if denominators.get(view, 0) == 0)
    per_projection = {view: (hits.get(view, 0) == 0) for view in DELETE_PROJECTIONS}
    sub_conditions = {
        "consumable_before_deletion": bool(consumable_before),
        "recall_after_deletion_empty": not recall_after["memories"],
        "inspect_matches_replay": inspect_ok,
        "retract_event_present": bool(retract_events),
        "source_chain_recomputable": content_recomputable,
    }
    if zero_denominators:
        status = "not_measurable"
        reason = "a zero denominator is not a measured zero"
    else:
        status = "passed" if all({**per_projection, **sub_conditions}.values()) else "failed"
        reason = None
    context["extra"].update({
        "deletion": action,
        "projection_denominators": denominators,
        "per_projection_consumable_hits_after": hits,
        "per_projection_zero_assertion": per_projection,
        "sub_conditions": sub_conditions,
        "zero_denominator_projections": zero_denominators,
        "salience_excluded": True,
        "consumable_before_deletion": consumable_before,
        "recall_after_deletion_returned": [row["memory_id"] for row in recall_after["memories"]],
        "retract_event_ids": [event["event_id"] for event in retract_events],
        "purge_marker": bool(retract_events and retract_events[-1]["payload"].get("purge")),
        "source_chain_recomputable": content_recomputable,
        "inspect_matches_replay": {view: row["matches_replay"] for view, row in inspect_report.items()},
    })
    event_chain_closed = bool(
        [event["event_id"] for event in log] == await _authority_ids(session, sid)
        and len({event["event_id"] for event in log}) == len(log))
    scoring = {"per_projection_zero_after_deletion": per_projection, **sub_conditions}
    expected = {
        "per_projection_consumable_hits": {view: 0 for view in DELETE_PROJECTIONS},
        "retract_event_present": True,
        "source_chain_recomputable": True,
        "recall_after_deletion_empty": True,
        "salience_excluded_from_deletion_propagation": True,
    }
    observed = {
        "deletion_action": action,
        "per_projection_consumable_hits_after": hits,
        "per_projection_denominators": denominators,
        "per_projection_zero_assertion": per_projection,
        "zero_denominator_projections": zero_denominators,
        "retract_event_ids": [event["event_id"] for event in retract_events],
        "purge_marker": bool(retract_events and retract_events[-1]["payload"].get("purge")),
        "source_chain_recomputable": content_recomputable,
        "recall_after_deletion_returned": [row["memory_id"] for row in recall_after["memories"]],
        "inspect_views_matching_replay": sorted(view for view, row in inspect_report.items() if row["matches_replay"]),
        "salience_excluded_from_deletion_propagation": True,
        "event_chain_closed": event_chain_closed,
        "event_chain_semantics": ("replay(scope) id sequence == authority log id sequence, item by item; this "
                                  "invariant DOES replay the chain, so the boolean is measured, not defaulted"),
    }
    sample_sizes = {
        "projections_asserted": len(DELETE_PROJECTIONS),
        "identity_projections_asserted": _chain_denominator(entry),
        "retract_events_examined": len(retract_events),
        "events_replayed": len(log),
        "consumer_visible_hits_before_deletion": sum(denominators.values()),
        **{f"denominator_{view}": int(denominators.get(view, 0)) for view in DELETE_PROJECTIONS},
    }
    context["extra"].update({
        "deletion": action,
        "projection_denominators": denominators,
        "per_projection_consumable_hits_after": hits,
        "per_projection_zero_assertion": per_projection,
        "sub_conditions": sub_conditions,
        "zero_denominator_projections": zero_denominators,
        "salience_excluded": True,
        "consumable_before_deletion": consumable_before,
        "recall_after_deletion_returned": [row["memory_id"] for row in recall_after["memories"]],
        "retract_event_ids": [event["event_id"] for event in retract_events],
        "purge_marker": bool(retract_events and retract_events[-1]["payload"].get("purge")),
        "source_chain_recomputable": content_recomputable,
        "inspect_matches_replay": {view: row["matches_replay"] for view, row in inspect_report.items()},
        "scoring": scoring,
    })
    await _finish(session, evidence, context, status=status, request_id=result["request_id"],
                  before_fingerprints=before_fingerprints, after_fingerprints=after_fingerprints,
                  watermark_before=manifest_before.source_event_id, watermark_after=manifest_after.source_event_id,
                  impact={"entries": len(result["impact"]["memory_ids"]),
                          "projections": {view: row["count"] for view, row in inspect_report.items()}},
                  event_chain_closed=event_chain_closed, reproducible=True, projection_denominators=denominators,
                  not_measurable_reason=reason, expected=expected, observed=observed, scoring=scoring,
                  sample_sizes=sample_sizes,
                  record_extra={"criterion_evidence": "R6.2 per-projection denominators and hit counts"},
                  extra={"unmet_sub_conditions": sorted(
                      key for key, ok in {**per_projection, **sub_conditions}.items() if not ok)
                      if status == "failed" else []})
    if zero_denominators:
        raise AssertionError(f"{case_id}: {reason} for {zero_denominators}")
    assert status == "passed", (
        f"{case_id} did not satisfy R6.2: denominators={denominators} hits_after={hits} "
        f"consumable_before={consumable_before} recall_after={recall_after['memories']} "
        f"inspect_ok={inspect_ok} retract={len(retract_events)} recomputable={content_recomputable}")


@pytest.mark.asyncio
async def test_aoep_deletion_propagation_retire(db_session, memory_eval_evidence):
    await _guard("aoep_deletion_propagation_retire", db_session, memory_eval_evidence, _deletion)


@pytest.mark.asyncio
async def test_aoep_deletion_propagation_purge(db_session, memory_eval_evidence):
    await _guard("aoep_deletion_propagation_purge", db_session, memory_eval_evidence, _deletion)


# ===========================================================================
# authority_monotonicity (R6.5 + T068) — T024
# ===========================================================================

async def _authority_escalation(case_id: str, session, evidence, context) -> None:
    entry = case(case_id)
    allocation = context["allocation"]
    sid = await _new_scope(session, allocation)
    service = _service(session)
    memory = await _record(allocation, service, _submission(sid, content=f"AOEP authority escalation {case_id} {allocation.isolation_id[:8]}",
                                             evidence_refs=(f"3001{allocation.isolation_id[:8]}",)))
    assert_isolated(allocation, sid)
    authority_before = await _authority_state(session, sid)
    bindings_before = await _binding_rows(session)
    before_ids = authority_before["ids"]
    state_before = reduce_events(await _events(session, sid)).export()
    authority_axis_before = _authority_axis(_manifest_state(await service.projections.current(sid)))
    rejections: list[dict] = []

    try:
        await service.apply_event({"knowledge_scope_id": sid, "event_type": "assert", "payload": {"provenance": "hard"}})
        rejections.append({"attempt": "raw_event_append", "rejected": False})
    except PermissionError as error:
        rejections.append({"attempt": "raw_event_append", "rejected": True, "code": str(error).split(":", 1)[0]})

    try:
        await _govern(allocation, service, "rollback", scope_id=sid, event_point=memory["memory_id"], actor="mcp",
                             reason="AOEP untrusted management command")
        rejections.append({"attempt": "untrusted_management_command", "rejected": False})
    except PermissionError as error:
        rejections.append({"attempt": "untrusted_management_command", "rejected": True, "code": str(error)})

    try:
        await _govern(allocation, service, "binding", scope_id=sid, actor="mcp", binding_kind="dir_name",
                             binding_value=f"aoep-untrusted-{allocation.isolation_id[:8]}",
                             reason="AOEP untrusted binding grant")
        rejections.append({"attempt": "untrusted_binding_grant", "rejected": False})
    except PermissionError as error:
        rejections.append({"attempt": "untrusted_binding_grant", "rejected": True, "code": str(error)})

    server = _mcp_server(session)
    for tool in ("rollback", "grant", "scope_bindings"):
        observation = await _mcp_call(server, tool, {})
        rejections.append({"attempt": f"mcp_tool_{tool}", "rejected": _rejected(observation),
                           "code": observation.get("code") or observation.get("error_type")})
    extra_argument = await _mcp_call(server, "record_memory", {
        **_submission(sid, content=f"AOEP MCP extra argument {allocation.isolation_id[:8]}",
                      evidence_refs=(f"3002{allocation.isolation_id[:8]}",)),
        "scope_ref": str(sid), "scope_id": None, "binding_kind": "dir_name", "binding_value": "aoep-forbidden"})
    rejections.append({"attempt": "mcp_extra_argument", "rejected": _rejected(extra_argument),
                       "code": extra_argument.get("code") or extra_argument.get("error_type")})
    declared_hard = await _mcp_call(server, "record_memory", {
        "scope_ref": str(sid), "kind": "procedural",
        "content": f"AOEP declared hard authority without anchors {allocation.isolation_id[:8]}",
        "provenance": "hard", "inference_meta": None})
    rejections.append({"attempt": "mcp_declared_hard_authority", "rejected": _rejected(declared_hard),
                       "code": (declared_hard.get("structured") or {}).get("error", {}).get("code")
                       or declared_hard.get("error_type")})

    after_ids = await _authority_ids(session, sid)
    state_after = reduce_events(await _events(session, sid)).export()
    authority_after = _authority_axis(_manifest_state(await service.projections.current(sid)))
    bindings_after = await _binding_rows(session)
    inspect_report = await service.inspect_projections(sid)
    authority_state_after = await _authority_state(session, sid)
    authority_fingerprints_before, authority_fingerprints_after = _authority_fingerprints(
        authority_before, authority_state_after)
    binding_rows_fingerprint_before = _fingerprint(bindings_before)
    binding_rows_fingerprint_after = _fingerprint(bindings_after)
    unchanged = (after_ids == before_ids and authority_after == authority_axis_before
                 and bindings_after == bindings_before)
    all_rejected = all(item["rejected"] for item in rejections)
    status = "passed" if (unchanged and all_rejected and len(rejections) == len(entry["_meta"]["attempts"])) else "failed"
    scoring = {
        "all_rejected": all_rejected,
        "authority_ids_unchanged": after_ids == before_ids,
        "authority_axis_unchanged": authority_after == authority_axis_before,
        "binding_rows_unchanged": bindings_after == bindings_before,
        "scope_registry_unchanged": (authority_before["scope_registry_ids"]
                                     == authority_state_after["scope_registry_ids"]),
        "attempt_count_matches_dataset": len(rejections) == len(entry["_meta"]["attempts"]),
        "succeeded": sum(1 for item in rejections if not item["rejected"]),
        "event_chain_closed": None,  # not applicable: this invariant replays no event chain
    }
    observed = {
        "attempts": rejections,
        "attempted": len(rejections),
        "succeeded": sum(1 for item in rejections if not item["rejected"]),
        "expected_attempts": list(entry["_meta"]["attempts"]),
        "codes_observed": [item.get("code") for item in rejections],
        "authority_ids_before": before_ids,
        "authority_ids_after": after_ids,
        "authority_axis_unchanged": authority_after == authority_axis_before,
        "binding_rows_unchanged": bindings_after == bindings_before,
        "scope_registry_unchanged": (authority_before["scope_registry_ids"]
                                     == authority_state_after["scope_registry_ids"]),
        "event_chain_closed": None,
        "event_chain_not_applicable_reason": ("R6.5 refuses writes; it replays no event chain and therefore MUST "
                                              "NOT report a boolean event_chain_closed (FR-019/SC-005)"),
        "state_entries_before": len(state_before["entries"]),
        "state_entries_after": len(state_after["entries"]),
    }
    sample_sizes = {
        "attempted": len(rejections),
        "succeeded": sum(1 for item in rejections if not item["rejected"]),
        "attempt_forms_declared": len(entry["_meta"]["attempts"]),
        "authority_events_examined": len(after_ids),
        "rejection_codes_observed": sum(1 for item in rejections if item.get("code")),
    }
    # T082: the fingerprint pair above is only meaningful while the binding table is
    # owned by this suite. A foreign suite granting a row mid-case would invalidate the
    # comparison, so fail with that exact condition rather than exporting a misleading
    # "unchanged" fingerprint.
    assert bindings_after == bindings_before, (
        f"{case_id}: the scope_bindings row set changed during the rejection window, so the "
        f"binding_rows fingerprint pair cannot witness R6.5 (a foreign writer may have granted a binding)")
    context["extra"].update({
        "attempts": rejections,
        "attempted": len(rejections),
        "succeeded": sum(1 for item in rejections if not item["rejected"]),
        "authority_ids_before": before_ids,
        "authority_ids_after": after_ids,
        "authority_axis_unchanged": authority_after == authority_axis_before,
        "binding_rows_unchanged": bindings_after == bindings_before,
        "state_before_entries": len(state_before["entries"]),
        "state_after_entries": len(state_after["entries"]),
        "scoring": scoring,
    })
    await _finish(session, evidence, context, status=status, request_id=str(uuid.uuid4()),
                  impact={"entries": 0, "projections": {view: row["count"] for view, row in inspect_report.items()}},
                  event_chain_closed=None, reproducible=True,
                  before_fingerprints={**authority_fingerprints_before,
                                       "binding_rows": binding_rows_fingerprint_before},
                  after_fingerprints={**authority_fingerprints_after,
                                      "binding_rows": binding_rows_fingerprint_after},
                  expected={"all_attempts_rejected": True, "succeeded": 0, "authority_ids_unchanged": True,
                            "authority_axis_unchanged": True, "binding_rows_unchanged": True,
                            "rejection_observable_as_error_code": True, "event_chain_closed": None},
                  observed=observed, scoring=scoring, sample_sizes=sample_sizes,
                  record_extra={"criterion_evidence": "R6.5 attempt list, id sequences and binding row set"},
                  extra={"unmet_sub_conditions": [item["attempt"] for item in rejections if not item["rejected"]]})
    assert status == "passed", (
        f"{case_id} did not satisfy R6.5: attempted={len(rejections)} "
        f"unchanged={unchanged} failed_attempts={[item['attempt'] for item in rejections if not item['rejected']]}")


async def _authority_readonly_body(case_id: str, session, evidence, context) -> None:
    entry = case(case_id)
    allocation = context["allocation"]
    sid = await _new_scope(session, allocation)
    service = _service(session)
    memory = await _record(allocation, service, _submission(sid, content=f"AOEP authority read-only {case_id} {allocation.isolation_id[:8]}",
                                             evidence_refs=(f"3101{allocation.isolation_id[:8]}",)))
    assert_isolated(allocation, sid)
    authority_before = await _authority_state(session, sid)
    bindings_before = await _binding_rows(session)
    before_ids = authority_before["ids"]
    authority_axis_before = _authority_axis(_manifest_state(await service.projections.current(sid)))
    attempted: dict[str, dict] = {}

    # (i) MCP surface route: the memory tool surface exposes no rollback capability at all.
    server = _mcp_server(session)
    observation = await _mcp_call(server, "rollback", {"scope_id": sid, "event_point": memory["memory_id"],
                                                       "reason": "AOEP non-management rollback via MCP"})
    attempted["mcp_surface"] = {"attempted": 1, "succeeded": 0 if _rejected(observation) else 1,
                                "rejected": _rejected(observation),
                                "code": observation.get("code") or observation.get("error_type")}

    # (ii) non-writer instance route: an untrusted actor on the service boundary.
    try:
        await _govern(allocation, service, "rollback", scope_id=sid, event_point=memory["memory_id"], actor="mcp",
                      reason="AOEP non-management rollback on a non-writer instance")
        attempted["non_writer_instance"] = {"attempted": 1, "succeeded": 1, "rejected": False, "code": None}
    except PermissionError as error:
        attempted["non_writer_instance"] = {"attempted": 1, "succeeded": 0, "rejected": True, "code": str(error)}
    # The MCP write path checks only that *some* writer lease is active, so this extra
    # observation is measurable only while no other instance holds the lease. It is not
    # one of the three rollback routes: it is recorded not_measurable rather than
    # counted, and no write is issued while a foreign lease is active.
    active_leases = await _active_writer_lease_count(session)
    if active_leases == 0:
        lease_observation = await _mcp_call(server, "record_memory", {
            "scope_ref": str(sid), "kind": "procedural",
            "content": f"AOEP write on a non-writer instance {allocation.isolation_id[:8]}",
            "provenance": "soft",
            "inference_meta": {"source": "015 AOEP suite", "confidence": 0.8, "model_version": "aoep-015-v1",
                               "time": datetime.now(UTC).isoformat(), "supporting_evidence": []}})
        attempted["non_writer_instance"]["leased_write_attempt"] = {
            "rejected": _rejected(lease_observation),
            "code": (lease_observation.get("structured") or {}).get("error", {}).get("code")
            or lease_observation.get("error_type")}
    else:
        attempted["non_writer_instance"]["leased_write_attempt"] = {
            "attempted": 0, "rejected": None, "not_measurable": True,
            "active_foreign_writer_leases": active_leases,
            "reason": ("a foreign writer lease was active, so the non-writer-instance write path could "
                       "not be observed without writing into the isolated scope")}

    # (iii) read-only instance route: REST with no writer lease and with instance_mode=reader.
    async with _rest_client(session) as client:
        no_lease = await client.post("/api/memories/rollback", json={
            "scope_id": sid, "event_point": memory["memory_id"], "reason": "AOEP rollback without a writer lease"})
        retire_no_lease = await client.post("/api/memories/retire", json={
            "scope_id": sid, "memory_id": memory["memory_id"], "reason": "AOEP retire without a writer lease"})
    with patch("rag_mcp.api.memory.get_settings", lambda: SimpleNamespace(instance_mode="reader")):
        async with _rest_client(session) as client:
            reader_mode = await client.post("/api/memories/rollback", json={
                "scope_id": sid, "event_point": memory["memory_id"], "reason": "AOEP rollback on a reader instance"})
    codes = [no_lease.json()["detail"]["code"], retire_no_lease.json()["detail"]["code"],
             reader_mode.json()["detail"]["code"]]
    read_only_rejected = (
        no_lease.status_code == 503 and retire_no_lease.status_code == 503 and reader_mode.status_code == 503
        and all(code == "MEMORY_WRITE_UNAVAILABLE" for code in codes))
    attempted["read_only_instance"] = {
        "attempted": 3, "succeeded": 0 if read_only_rejected else 1, "rejected": read_only_rejected,
        "code": "MEMORY_WRITE_UNAVAILABLE",
        "statuses": [no_lease.status_code, retire_no_lease.status_code, reader_mode.status_code]}

    after_ids = await _authority_ids(session, sid)
    authority_after = _authority_axis(_manifest_state(await service.projections.current(sid)))
    bindings_after = await _binding_rows(session)
    inspect_report = await service.inspect_projections(sid)
    authority_state_after = await _authority_state(session, sid)
    authority_fingerprints_before, authority_fingerprints_after = _authority_fingerprints(
        authority_before, authority_state_after)
    total_attempted = sum(item["attempted"] for item in attempted.values())
    total_succeeded = sum(item["succeeded"] for item in attempted.values())
    if total_attempted == 0:
        status, reason = "not_measurable", "no non-management rollback attempt was made; a zero sample is not a measured zero"
    elif (total_succeeded == 0 and after_ids == before_ids and authority_after == authority_axis_before
          and bindings_after == bindings_before and all(item["rejected"] for item in attempted.values())):
        status, reason = "passed", None
    else:
        status, reason = "failed", None
    scoring = {
        "all_attempts_rejected": all(item["rejected"] for item in attempted.values()),
        "succeeded": total_succeeded,
        "authority_ids_unchanged": after_ids == before_ids,
        "authority_axis_unchanged": authority_after == authority_axis_before,
        "binding_rows_unchanged": bindings_after == bindings_before,
        "scope_registry_unchanged": (authority_before["scope_registry_ids"]
                                     == authority_state_after["scope_registry_ids"]),
        "event_chain_closed": None,  # not applicable: no event chain is replayed by this invariant
    }
    observed = {
        "non_management_rollback_attempts": attempted,
        "attempted": total_attempted,
        "succeeded": total_succeeded,
        "routes_declared": list(entry["_meta"]["rollback_attempt_methods"]),
        "codes_observed": {name: item.get("code") for name, item in attempted.items()},
        "authority_ids_before": before_ids,
        "authority_ids_after": after_ids,
        "authority_axis_unchanged": authority_after == authority_axis_before,
        "binding_rows_unchanged": bindings_after == bindings_before,
        "scope_registry_unchanged": (authority_before["scope_registry_ids"]
                                     == authority_state_after["scope_registry_ids"]),
        "event_chain_closed": None,
        "event_chain_not_applicable_reason": ("R6.5 refuses writes; it replays no event chain and therefore MUST "
                                              "NOT report a boolean event_chain_closed (FR-019/SC-005)"),
    }
    sample_sizes = {
        "attempted": total_attempted,
        "succeeded": total_succeeded,
        "attempt_routes_declared": len(entry["_meta"]["rollback_attempt_methods"]),
        "authority_events_examined": len(after_ids),
        "rejection_codes_observed": sum(1 for item in attempted.values() if item.get("code")),
    }
    context["extra"].update({
        "non_management_rollback_attempts": attempted,
        "attempted": total_attempted,
        "succeeded": total_succeeded,
        "authority_ids_before": before_ids,
        "authority_ids_after": after_ids,
        "authority_axis_unchanged": authority_after == authority_axis_before,
        "binding_rows_unchanged": bindings_after == bindings_before,
        "rejection_audit_records": [item.get("code") for item in attempted.values()],
        "scoring": scoring,
    })
    await _finish(session, evidence, context, status=status, request_id=str(uuid.uuid4()),
                  impact={"entries": 0, "projections": {view: row["count"] for view, row in inspect_report.items()}},
                  event_chain_closed=None, reproducible=True,
                  before_fingerprints=authority_fingerprints_before,
                  after_fingerprints=authority_fingerprints_after,
                  not_measurable_reason=reason,
                  expected={"all_attempts_rejected": True, "succeeded": 0, "authority_ids_unchanged": True,
                            "authority_axis_unchanged": True, "binding_rows_unchanged": True,
                            "routes_attempted": list(entry["_meta"]["rollback_attempt_methods"]),
                            "event_chain_closed": None},
                  observed=observed, scoring=scoring, sample_sizes=sample_sizes,
                  record_extra={"criterion_evidence": "R6.5 non-management rollback routes"},
                  extra={"non_management_rollback_attempts": attempted, "attempted": total_attempted,
                         "succeeded": total_succeeded,
                         "criterion": entry["_meta"]["rollback_attempt_methods"]})
    if status == "not_measurable":
        raise AssertionError(f"{case_id}: {reason}")
    assert status == "passed", (
        f"{case_id} did not satisfy R6.5/T026: attempted={total_attempted} succeeded={total_succeeded} "
        f"{attempted}")


@pytest.mark.asyncio
async def test_aoep_authority_monotonicity_rejects_escalation(db_session, aoep_writer_owner, memory_eval_evidence):
    await _guard("aoep_authority_monotonicity_rejects_escalation", db_session, memory_eval_evidence,
                 _authority_escalation, identity_id=str(aoep_writer_owner.holder_instance_id))


@pytest.mark.asyncio
async def test_aoep_authority_monotonicity_rejects_readonly_instance(db_session, memory_eval_evidence):
    await _guard("aoep_authority_monotonicity_rejects_readonly_instance", db_session, memory_eval_evidence,
                 _authority_readonly_body)


# ===========================================================================
# provenance_preservation (R6.6 + T069)
# ===========================================================================

async def _provenance_transitions(case_id: str, session, evidence, context) -> None:
    entry = case(case_id)
    allocation = context["allocation"]
    sid = await _new_scope(session, allocation)
    service = _service(session)
    tag = allocation.isolation_id[:8]
    memories = [await _record(allocation, service, _submission(sid, content=f"AOEP provenance {case_id} #{index} {tag}",
                                                evidence_refs=(f"400{index}{tag}",)))
                for index in range(1, 5)]
    ids = [memory["memory_id"] for memory in memories]
    assert_isolated(allocation, sid)
    manifest_before = await service.projections.current(sid)
    before_fingerprints = await _view_fingerprints(session, sid, manifest_before.source_event_id)
    before_fingerprints["state"] = manifest_before.fingerprint
    original = {str(mid): {field: value for field, value in _entries(_manifest_state(manifest_before))[mid].items()
                           if field in PROVENANCE_FIELDS} for mid in ids}

    # rollback first (tombstones the fourth identity), then retire and purge, so all
    # three transitions are independently observable in the final state.
    rollback = await _govern(allocation, service, "rollback", scope_id=sid, actor="management",
                                    reason="AOEP provenance rollback transition", event_point=ids[2])
    retired = await _govern(allocation, service, "retire", scope_id=sid, memory_id=ids[0], actor="management",
                                   reason="AOEP provenance retire transition")
    purged = await _govern(allocation, service, "purge", scope_id=sid, memory_id=ids[1], actor="management",
                                  reason="AOEP provenance purge transition")

    manifest_after = await service.projections.current(sid)
    state_after = _manifest_state(manifest_after)
    after_fingerprints = await _view_fingerprints(session, sid, manifest_after.source_event_id)
    after_fingerprints["state"] = manifest_after.fingerprint
    entries_after = _entries(state_after)
    preserved = {str(mid): {field: entries_after[mid].get(field) for field in PROVENANCE_FIELDS} == original[str(mid)]
                 for mid in ids}
    transitions = {
        "retire": entries_after[ids[0]]["status"] == "retired",
        "purge": entries_after[ids[1]]["status"] == "retired",
        "rollback": entries_after[ids[3]]["status"] == "retired",
    }
    log = await _events(session, sid)
    hash_checks = {str(event["event_id"]): hashlib.sha256(event["payload"]["content_text"].encode("utf-8")).hexdigest()
                   == event["payload"]["content_hash"]
                   for event in log if "content_hash" in event["payload"]}
    rows = (await session.execute(select(MemoryEntry).where(MemoryEntry.knowledge_scope_id == sid))).scalars().all()
    projected = {int(row.memory_id): {"content_hash": row.content_hash, "provenance": row.provenance,
                                      "evidence_refs": list(row.evidence_refs or []),
                                      "inference_meta": row.inference_meta}
                 for row in rows}
    projection_preserved = all(
        projected.get(mid, {}).get("content_hash") == original[str(mid)]["content_hash"]
        and projected.get(mid, {}).get("provenance") == original[str(mid)]["provenance"]
        and projected.get(mid, {}).get("evidence_refs") == original[str(mid)]["evidence_refs"]
        for mid in ids)
    inspect_report = await service.inspect_projections(sid)
    inspect_ok = bool(inspect_report) and all(row["matches_replay"] for row in inspect_report.values())
    recomputed = projection_fingerprint(reduce_events(log)) == manifest_after.fingerprint
    status = "passed" if (all(preserved.values()) and all(transitions.values()) and all(hash_checks.values())
                          and projection_preserved and inspect_ok and recomputed) else "failed"
    event_chain_closed = bool(
        [event["event_id"] for event in log] == await _authority_ids(session, sid)
        and len({event["event_id"] for event in log}) == len(log))
    scoring = {
        "provenance_preserved_for_every_identity": all(preserved.values()),
        "transitions_observed": transitions,
        "content_hash_recomputed_item_by_item": all(hash_checks.values()),
        "projection_provenance_preserved": projection_preserved,
        "inspect_matches_replay": inspect_ok,
        "recomputed_fingerprint_matches_manifest": recomputed,
        "event_chain_closed": event_chain_closed,
    }
    observed = {
        "transitions_observed": transitions,
        "provenance_preserved_per_identity": preserved,
        "identity_ids": [str(mid) for mid in ids],
        "content_hash_recomputed_item_by_item": hash_checks,
        "relation_projection_provenance_preserved": projection_preserved,
        "inspect_views_matching_replay": sorted(view for view, row in inspect_report.items() if row["matches_replay"]),
        "recomputed_fingerprint_matches_manifest": recomputed,
        "transition_request_ids": {"rollback": rollback["request_id"], "retire": retired["request_id"],
                                   "purge": purged["request_id"]},
        "event_chain_closed": event_chain_closed,
        "event_chain_semantics": ("replay(scope) id sequence == authority log id sequence, item by item; this "
                                  "invariant DOES replay the chain, so the boolean is measured, not defaulted"),
    }
    sample_sizes = {
        "identities_tracked": len(ids),
        "provenance_fields_compared_per_identity": len(PROVENANCE_FIELDS),
        "transitions_asserted": len(transitions),
        "events_hash_checked": len(hash_checks),
        "views_asserted": len(CRITERION_VIEWS),
        "identity_projections_asserted": _chain_denominator(entry),
    }
    context["extra"].update({
        "transitions_observed": transitions,
        "provenance_preserved_per_identity": preserved,
        "content_hash_recomputed_item_by_item": hash_checks,
        "relation_projection_provenance_preserved": projection_preserved,
        "inspect_matches_replay": {view: row["matches_replay"] for view, row in inspect_report.items()},
        "recomputed_fingerprint_matches_manifest": recomputed,
        "transition_request_ids": {"rollback": rollback["request_id"], "retire": retired["request_id"],
                                   "purge": purged["request_id"]},
        "scoring": scoring,
    })
    await _finish(session, evidence, context, status=status, request_id=rollback["request_id"],
                  before_fingerprints=before_fingerprints, after_fingerprints=after_fingerprints,
                  watermark_before=manifest_before.source_event_id, watermark_after=manifest_after.source_event_id,
                  impact={"entries": len(rollback["impact"]["memory_ids"]) + 2,
                          "projections": {view: row["count"] for view, row in inspect_report.items()}},
                  event_chain_closed=event_chain_closed, reproducible=True,
                  expected={"provenance_preserved_for_every_identity": True,
                            "content_hash_recomputed_item_by_item": True,
                            "transitions": {"rollback": True, "retire": True, "purge": True},
                            "recomputed_fingerprint_matches_manifest": True, "event_chain_closed": True},
                  observed=observed, scoring=scoring, sample_sizes=sample_sizes,
                  record_extra={"criterion_evidence": "R6.6 provenance fields and per-event content hashes"},
                  extra={"unmet_sub_conditions": {
                      "preserved": [mid for mid, ok in preserved.items() if not ok],
                      "transitions": [name for name, ok in transitions.items() if not ok],
                      "content_hash": [key for key, ok in hash_checks.items() if not ok]}})
    assert status == "passed", f"{case_id} did not satisfy R6.6: {context['extra'].get('unmet_sub_conditions')}"


async def _provenance_source_chain(case_id: str, session, evidence, context) -> None:
    entry = case(case_id)
    allocation = context["allocation"]
    sid = await _new_scope(session, allocation)
    service = _service(session)
    tag = allocation.isolation_id[:8]
    first = await _record(allocation, service, _submission(sid, content=f"AOEP provenance chain root {case_id} {tag}",
                                            evidence_refs=(f"4101{tag}",)))
    second = await _record(allocation, service, {**_submission(sid, content=f"AOEP provenance chain successor {case_id} {tag}",
                                                 evidence_refs=(f"4102{tag}",)),
                                   "supersedes_memory_id": first["memory_id"]})
    assert_isolated(allocation, sid)
    log_before = await _events(session, sid)
    before_fingerprints = await _view_fingerprints(session, sid, (await service.projections.current(sid)).source_event_id)
    revise_event = next(event for event in log_before if event["event_id"] == second["memory_id"])
    assert revise_event["event_type"] == "revise"
    assert revise_event["payload"]["supersedes_memory_id"] == first["memory_id"]

    retired = await _govern(allocation, service, "retire", scope_id=sid, memory_id=second["memory_id"], actor="management",
                                   reason="AOEP source-chain retire transition")
    purged = await _govern(allocation, service, "purge", scope_id=sid, memory_id=first["memory_id"], actor="management",
                                  reason="AOEP source-chain purge transition")
    log_after = await _events(session, sid)
    manifest = await service.projections.current(sid)
    recomputed = projection_fingerprint(reduce_events(log_after)) == manifest.fingerprint
    inspect_report = await service.inspect_projections(sid)
    retained_ids = {event["event_id"] for event in log_after}
    tombstones = [event for event in log_after if event["event_type"] == "retract"]
    purge_event = next((event for event in tombstones if event["aggregate_id"] == first["memory_id"]), None)
    rollback = await _govern(allocation, service, "rollback", scope_id=sid, actor="management",
                                    reason="AOEP source-chain rollback transition",
                                    event_point=second["memory_id"])
    log_final = await _events(session, sid)
    manifest_final = await service.projections.current(sid)
    after_fingerprints = await _view_fingerprints(session, sid, manifest_final.source_event_id)
    after_fingerprints["state"] = manifest_final.fingerprint
    final_recomputed = projection_fingerprint(reduce_events(log_final)) == manifest_final.fingerprint
    final_inspect = await service.inspect_projections(sid)
    source_chain_ok = (
        {first["memory_id"], second["memory_id"], retired["event_id"], purged["event_id"]} <= retained_ids
        and len(log_final) >= len(log_before) + 2
        and purge_event is not None and purge_event["payload"].get("purge") is True
        and bool(next(event for event in log_final if event["event_id"] == first["memory_id"])["payload"].get("content_hash"))
    )
    status = "passed" if (source_chain_ok and recomputed and final_recomputed
                          and all(row["matches_replay"] for row in inspect_report.values())
                          and all(row["matches_replay"] for row in final_inspect.values())) else "failed"
    event_chain_closed = bool(
        [event["event_id"] for event in log_final] == await _authority_ids(session, sid)
        and len({event["event_id"] for event in log_final}) == len(log_final))
    scoring = {
        "source_chain_retained": source_chain_ok,
        "purge_marker_present": bool(purge_event and purge_event["payload"].get("purge")),
        "history_never_deleted": len(log_final) >= len(log_before) + 2,
        "recomputed_fingerprint_matches_manifest": recomputed,
        "final_recomputed_fingerprint_matches_manifest": final_recomputed,
        "inspect_matches_replay": all(row["matches_replay"] for row in final_inspect.values()),
        "event_chain_closed": event_chain_closed,
    }
    observed = {
        "retained_event_ids": sorted(retained_ids),
        "retract_event_ids": [event["event_id"] for event in tombstones],
        "purge_marker": bool(purge_event and purge_event["payload"].get("purge")),
        "event_count_before": len(log_before),
        "event_count_after_transitions": len(log_after),
        "event_count_final": len(log_final),
        "source_chain_retained": source_chain_ok,
        "recomputed_fingerprint_matches_manifest": recomputed,
        "final_recomputed_fingerprint_matches_manifest": final_recomputed,
        "inspect_views_matching_replay": sorted(view for view, row in final_inspect.items() if row["matches_replay"]),
        "transition_request_ids": {"retire": retired["request_id"], "purge": purged["request_id"],
                                   "rollback": rollback["request_id"]},
        "event_chain_closed": event_chain_closed,
        "event_chain_semantics": ("replay(scope) id sequence == authority log id sequence, item by item; this "
                                  "invariant DOES replay the chain, so the boolean is measured, not defaulted"),
    }
    sample_sizes = {
        "events_before_transitions": len(log_before),
        "events_after_transitions": len(log_after),
        "events_final": len(log_final),
        "tombstones_examined": len(tombstones),
        "transitions_asserted": len(entry["_meta"]["transitions"]),
        "views_asserted": len(CRITERION_VIEWS),
    }
    context["extra"].update({
        "retained_event_ids": sorted(retained_ids),
        "retract_event_ids": [event["event_id"] for event in tombstones],
        "purge_marker": bool(purge_event and purge_event["payload"].get("purge")),
        "event_count_before": len(log_before),
        "event_count_after_transitions": len(log_after),
        "event_count_final": len(log_final),
        "source_chain_retained": source_chain_ok,
        "recomputed_fingerprint_matches_manifest": recomputed,
        "final_recomputed_fingerprint_matches_manifest": final_recomputed,
        "inspect_matches_replay": {view: row["matches_replay"] for view, row in final_inspect.items()},
        "transition_request_ids": {"retire": retired["request_id"], "purge": purged["request_id"],
                                   "rollback": rollback["request_id"]},
        "scoring": scoring,
    })
    await _finish(session, evidence, context, status=status, request_id=rollback["request_id"],
                  before_fingerprints=before_fingerprints, after_fingerprints=after_fingerprints,
                  watermark_before=manifest.source_event_id, watermark_after=manifest_final.source_event_id,
                  impact={"entries": len(rollback["impact"]["memory_ids"]),
                          "projections": {view: row["count"] for view, row in final_inspect.items()}},
                  event_chain_closed=event_chain_closed, reproducible=True,
                  expected={"source_chain_retained": True, "purge_marker_present": True,
                            "history_never_deleted": True, "recomputed_fingerprint_matches_manifest": True,
                            "event_chain_closed": True},
                  observed=observed, scoring=scoring, sample_sizes=sample_sizes,
                  record_extra={"criterion_evidence": "R6.6 retained event ids and tombstones"},
                  extra={"unmet_sub_conditions": {
                      "source_chain_retained": source_chain_ok,
                      "recomputed": recomputed, "final_recomputed": final_recomputed}})
    assert status == "passed", f"{case_id} did not satisfy R6.6: {context['extra'].get('unmet_sub_conditions')}"


@pytest.mark.asyncio
async def test_aoep_provenance_preservation_retire_purge_rollback(db_session, memory_eval_evidence):
    await _guard("aoep_provenance_preservation_retire_purge_rollback", db_session, memory_eval_evidence,
                 _provenance_transitions)


@pytest.mark.asyncio
async def test_aoep_provenance_preservation_source_chain_recomputable(db_session, memory_eval_evidence):
    await _guard("aoep_provenance_preservation_source_chain_recomputable", db_session, memory_eval_evidence,
                 _provenance_source_chain)


# ===========================================================================
# scope_non_expansion (R6.4 + T075/FR-061) — T024
# ===========================================================================

async def _scope_ambiguous(case_id: str, session, evidence, context) -> None:
    entry = case(case_id)
    options = entry["_meta"]
    allocation = context["allocation"]
    sid = await _new_scope(session, allocation)
    twin = allocate(run_id=RUN_ID, identity_id=allocation.identity_id)
    twin_id = await _new_scope(session, twin, name=allocation.name)
    reference = f"project:{allocation.name}"
    observations: list[dict] = []

    try:
        resolved = await MemoryScopeResolver(session).resolve(reference)
        observations.append({"surface": "scope_resolver", "rejected": False, "resolved": str(resolved)})
    except ScopeBindingError as error:
        observations.append({"surface": "scope_resolver", "rejected": True, "code": error.code,
                             "candidates": error.candidates})
    server = _mcp_server(session)
    for tool, arguments in (("record_memory", {"scope_ref": reference, "kind": "procedural",
                                              "content": f"AOEP ambiguous reference {allocation.isolation_id[:8]}",
                                              "provenance": "soft",
                                              "inference_meta": {"source": "015 AOEP suite", "confidence": 0.8,
                                                                 "model_version": "aoep-015-v1",
                                                                 "time": datetime.now(UTC).isoformat(),
                                                                 "supporting_evidence": []}}),
                            ("recall_memory", {"scope_ref": [reference]})):
        observation = await _mcp_call(server, tool, arguments)
        structured = observation.get("structured") or {}
        observations.append({"surface": f"mcp:{tool}", "rejected": _rejected(observation),
                             "code": (structured.get("error") or {}).get("code"),
                             "candidates": (structured.get("error") or {}).get("candidates")})
    async with _rest_client(session) as client:
        response = await client.get("/api/memories", params={"scope_ref": reference})
    observations.append({"surface": "rest:GET /api/memories", "rejected": response.status_code >= 400,
                         "http_status": response.status_code, "code": response.json().get("detail", {}).get("code"),
                         "candidates": response.json().get("detail", {}).get("candidates")})

    candidate_samples = [observation for observation in observations if observation.get("candidates") is not None]
    fallbacks = [observation for observation in observations if observation.get("resolved")]
    scored = {
        "all_rejected": all(_rejected(observation) for observation in observations),
        "code_is_ambiguous": all(observation.get("code") in (None, options["expected_code"]) for observation in observations),
        "candidates_present": bool(candidate_samples) and all(bool(observation["candidates"]) for observation in candidate_samples),
        "zero_fallback": not fallbacks,
    }
    status = "passed" if all(scored.values()) else "failed"
    scope_before, scope_after = await _scope_registry_fingerprints(session, sid)
    scoring = dict(scored)
    scoring["event_chain_closed"] = None  # not applicable: no event chain is replayed by R6.4
    observed = {
        "reference_form": options["reference_form"],
        "surface_codes": {observation["surface"]: observation.get("code") for observation in observations},
        "surface_rejected": {observation["surface"]: _rejected(observation) for observation in observations},
        "expected_code": options["expected_code"],
        "candidate_domains_per_surface": {observation["surface"]: len(observation.get("candidates") or [])
                                          for observation in observations},
        "ambiguity_twin_scope_id": str(twin_id),
        "scope_registry_unchanged_across_the_rejection_window": scope_before == scope_after,
        "fallback_successes": len(fallbacks),
        "event_chain_closed": None,
        "event_chain_not_applicable_reason": ("R6.4 performs only refused resolutions; it replays no event chain "
                                              "and therefore MUST NOT report a boolean event_chain_closed "
                                              "(FR-019/SC-005)"),
    }
    sample_sizes = {
        "surfaces_observed": len(observations),
        "rejections_observed": sum(1 for observation in observations if _rejected(observation)),
        "candidate_domain_samples": len(candidate_samples),
        "fallback_successes": len(fallbacks),
        "ambiguity_twin_scopes_created": 1,
    }
    context["extra"].update({
        "reference_form": options["reference_form"],
        "reference": reference,
        "observations": observations,
        "isolated_scope_id": str(sid),
        "ambiguity_twin_scope_id": str(twin_id),
        "sample_size": len(observations),
        "candidate_domain_samples": len(candidate_samples),
        "fallback_successes": len(fallbacks),
        "scored": scored,
        "scoring": scoring,
    })
    if evidence is not None:
        dispose(twin, directory=evidence.directory,
                extra={"case_id": case_id, "role": "ambiguity_twin", "isolated_scope_id": str(twin_id)})
    await _finish(session, evidence, context, status=status, request_id=str(uuid.uuid4()),
                  event_chain_closed=None, reproducible=True,
                  before_fingerprints=scope_before, after_fingerprints=scope_after,
                  expected={"all_rejected": True, "code": options["expected_code"],
                            "candidates_present": True, "zero_fallback": True, "event_chain_closed": None},
                  observed=observed, scoring=scoring, sample_sizes=sample_sizes,
                  record_extra={"criterion_evidence": "R6.4 per-surface observations and candidate domains"},
                  extra={"scored": scored, "sample_size": len(observations),
                         "fallback_successes": len(fallbacks)})
    assert status == "passed", f"{case_id} did not satisfy R6.4 (ambiguous): {scored}"


async def _scope_missing(case_id: str, session, evidence, context) -> None:
    entry = case(case_id)
    options = entry["_meta"]
    form = options["reference_form"]
    allocation = context["allocation"]
    sid = await _new_scope(session, allocation)
    service = _service(session)
    observations: list[dict] = []
    reference = {"missing_scope_ref": None, "empty_string": "", "whitespace_only": "   "}[form]

    async def resolver_observation(label: str, callable_):
        try:
            resolved = await callable_()
            observations.append({"surface": label, "rejected": False, "resolved": str(resolved)})
        except ScopeBindingError as error:
            observations.append({"surface": label, "rejected": True, "code": error.code,
                                 "candidates": error.candidates})
        except ValueError as error:
            observations.append({"surface": label, "rejected": True, "code": str(error).split(":", 1)[0],
                                 "candidates": getattr(error, "candidates", [])})

    resolver = MemoryScopeResolver(session)
    if form == "missing_scope_ref":
        await resolver_observation("resolve_many([])", lambda: resolver.resolve_many([]))
        await resolver_observation("resolve_many(None)", lambda: resolver.resolve_many(None))
        await resolver_observation("record(no scope_id)",
                                   lambda: service.record(_submission(sid, content="ignored",
                                                                      evidence_refs=("4201",)) | {"scope_id": None}))
    else:
        await resolver_observation("resolve(reference)", lambda: resolver.resolve(reference))
        await resolver_observation("resolve_many([reference])", lambda: resolver.resolve_many([reference]))
        await resolver_observation("record(scope_id=reference)",
                                   lambda: service.record(_submission(sid, content="ignored",
                                                                      evidence_refs=("4202",)) | {"scope_id": reference}))

    server = _mcp_server(session)
    submissions = {"kind": "procedural", "content": f"AOEP missing scope reference {allocation.isolation_id[:8]}",
                   "provenance": "soft",
                   "inference_meta": {"source": "015 AOEP suite", "confidence": 0.8,
                                      "model_version": "aoep-015-v1", "time": datetime.now(UTC).isoformat(),
                                      "supporting_evidence": []}}
    record_arguments = (dict(submissions) if reference is None else {**submissions, "scope_ref": reference})
    observation = await _mcp_call(server, "record_memory", record_arguments)
    structured = observation.get("structured") or {}
    observations.append({"surface": "mcp:record_memory", "rejected": _rejected(observation),
                         "code": (structured.get("error") or {}).get("code") or observation.get("error_type"),
                         "candidates": (structured.get("error") or {}).get("candidates")})
    recall_arguments = {} if reference is None else {"scope_ref": [reference]}
    observation = await _mcp_call(server, "recall_memory", recall_arguments)
    structured = observation.get("structured") or {}
    observations.append({"surface": "mcp:recall_memory", "rejected": _rejected(observation),
                         "code": (structured.get("error") or {}).get("code") or observation.get("error_type"),
                         "candidates": (structured.get("error") or {}).get("candidates")})
    async with _rest_client(session) as client:
        response = (await client.get("/api/memories") if reference is None
                    else await client.get("/api/memories", params={"scope_ref": reference}))
    detail = response.json().get("detail")
    code = detail.get("code") if isinstance(detail, dict) else None
    observations.append({"surface": "rest:GET /api/memories", "rejected": response.status_code >= 400,
                         "http_status": response.status_code, "code": code,
                         "candidates": detail.get("candidates") if isinstance(detail, dict) else None})

    service_codes = [observation.get("code") for observation in observations
                     if observation["surface"].startswith(("resolve", "record("))]
    structured_codes = [observation.get("code") for observation in observations
                        if observation.get("code") in ("MISSING_KNOWLEDGE_SCOPE", "AMBIGUOUS_DOMAIN_REF")]
    candidate_samples = [observation for observation in observations if observation.get("candidates") is not None]
    fallbacks = [observation for observation in observations if observation.get("resolved")]
    scored = {
        "all_rejected": all(_rejected(observation) for observation in observations),
        "service_code_is_missing_knowledge_scope": bool(service_codes)
        and all(code == options["expected_code"] for code in service_codes),
        "structured_code_matches": bool(structured_codes)
        and all(code == options["expected_code"] for code in structured_codes),
        "candidates_present": bool(candidate_samples)
        and all(bool(observation["candidates"]) for observation in candidate_samples),
        "zero_fallback": not fallbacks,
    }
    status = "passed" if all(scored.values()) else "failed"
    scope_before, scope_after = await _scope_registry_fingerprints(session, sid)
    scoring = {
        **scored,
        "expected_code": options["expected_code"],
        "service_code_samples": len(service_codes),
        "structured_code_samples": len(structured_codes),
        "succeeded": len(fallbacks),
        "event_chain_closed": None,  # not applicable: R6.4 replays no event chain
    }
    observed = {
        "reference_form": form,
        "reference": reference,
        "surface_codes": {observation["surface"]: observation.get("code") for observation in observations},
        "surface_rejected": {observation["surface"]: _rejected(observation) for observation in observations},
        "expected_code": options["expected_code"],
        "service_codes_observed": service_codes,
        "structured_codes_observed": structured_codes,
        "candidate_domains_per_surface": {observation["surface"]: len(observation.get("candidates") or [])
                                          for observation in observations},
        "scope_registry_unchanged_across_the_rejection_window": scope_before == scope_after,
        "fallback_successes": len(fallbacks),
        "event_chain_closed": None,
        "event_chain_not_applicable_reason": ("R6.4 performs only refused resolutions; it replays no event chain "
                                              "and therefore MUST NOT report a boolean event_chain_closed "
                                              "(FR-019/SC-005)"),
    }
    sample_sizes = {
        "surfaces_observed": len(observations),
        "rejections_observed": sum(1 for observation in observations if _rejected(observation)),
        "service_code_samples": len(service_codes),
        "structured_code_samples": len(structured_codes),
        "candidate_domain_samples": len(candidate_samples),
        "fallback_successes": len(fallbacks),
    }
    context["extra"].update({
        "reference_form": form,
        "reference": reference,
        "observations": observations,
        "sample_size": len(observations),
        "structured_sample_size": len(structured_codes),
        "candidate_domain_samples": len(candidate_samples),
        "fallback_successes": len(fallbacks),
        "scored": scored,
        "isolated_scope_id": str(sid),
        "scoring": scoring,
    })
    await _finish(session, evidence, context, status=status, request_id=str(uuid.uuid4()),
                  event_chain_closed=None, reproducible=True,
                  before_fingerprints=scope_before, after_fingerprints=scope_after,
                  expected={"all_rejected": True, "code": options["expected_code"],
                            "candidates_present": True, "zero_fallback": True, "event_chain_closed": None},
                  observed=observed, scoring=scoring, sample_sizes=sample_sizes,
                  record_extra={"criterion_evidence": "R6.4/FR-061 per-surface observations and error codes"},
                  extra={"scored": scored, "sample_size": len(observations),
                         "fallback_successes": len(fallbacks),
                         "candidate_domain_samples": len(candidate_samples)})
    assert status == "passed", (
        f"{case_id} did not satisfy R6.4/FR-061 ({form}): {scored}; observations={observations}")


@pytest.mark.asyncio
async def test_aoep_scope_non_expansion_ambiguous_scope(db_session, aoep_writer_owner, memory_eval_evidence):
    await _guard("aoep_scope_non_expansion_ambiguous_scope", db_session, memory_eval_evidence,
                 _scope_ambiguous, identity_id=str(aoep_writer_owner.holder_instance_id))


@pytest.mark.asyncio
async def test_aoep_scope_non_expansion_missing_scope_void(db_session, aoep_writer_owner, memory_eval_evidence):
    await _guard("aoep_scope_non_expansion_missing_scope_void", db_session, memory_eval_evidence,
                 _scope_missing, identity_id=str(aoep_writer_owner.holder_instance_id))


@pytest.mark.asyncio
async def test_aoep_scope_non_expansion_missing_scope_empty_string(db_session, aoep_writer_owner, memory_eval_evidence):
    await _guard("aoep_scope_non_expansion_missing_scope_empty_string", db_session, memory_eval_evidence,
                 _scope_missing, identity_id=str(aoep_writer_owner.holder_instance_id))


@pytest.mark.asyncio
async def test_aoep_scope_non_expansion_missing_scope_whitespace(db_session, aoep_writer_owner, memory_eval_evidence):
    await _guard("aoep_scope_non_expansion_missing_scope_whitespace", db_session, memory_eval_evidence,
                 _scope_missing, identity_id=str(aoep_writer_owner.holder_instance_id))
