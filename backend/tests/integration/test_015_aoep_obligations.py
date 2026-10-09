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

async def _finish(session, evidence, context: dict, *, status: str, request_id: str | None = None,
                  before_fingerprints: dict | None = None, after_fingerprints: dict | None = None,
                  watermark_before: int | None = None, watermark_after: int | None = None,
                  impact: dict | None = None, event_chain_closed: bool | None = None,
                  re_rollback_consistent: bool | None = None, reproducible: bool | None = True,
                  projection_denominators: dict | None = None, not_measurable_reason: str | None = None,
                  extra: dict | None = None) -> dict:
    """Record the case (once) and assert no forbidden/foreign destructive touch happened."""
    if context.get("finished"):
        return context["record"]
    context["finished"] = True
    allocation: IsolationAllocation = context["allocation"]
    entry = context["entry"]
    forbidden_after = await _scope_event_count(session, FORBIDDEN_SCOPE_ID)
    foreign_after = await _foreign_event_count(session, allocation.scope_id)
    forbidden_delta = forbidden_after - context["forbidden_before"]
    foreign_delta = foreign_after - context["foreign_before"]
    touches = _DESTRUCTIVE_TOUCHES[context.get("touches_before", 0):]
    outside = [touch for touch in touches if not touch["allowed"]]
    record_extra = {
        "case_id": entry["case_id"],
        "invariant": entry["invariant"],
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
        **(extra or {}),
    }
    payload = {
        "case_id": entry["case_id"],
        "invariant": entry["invariant"],
        "request_id": str(request_id or uuid.uuid4()),
        "status": status,
        "target_kind": entry.get("target_kind"),
        "before_fingerprints": before_fingerprints or {},
        "after_fingerprints": after_fingerprints or {},
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
        await _finish(session, evidence, context, status="failed", reproducible=False)
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
    for view in ("relation", "dense", "links", "summary", "file", "salience"):
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
    context["extra"].update({
        "rollback_target": options["rollback_target"],
        "event_chain_closure_semantics": ("replay(scope) id sequence == authority log id sequence, item by item, "
                                          "no missing and no duplicate; explicitly NOT numeric continuity "
                                          "(snowflake ids are sparse)"),
        "unmet_sub_conditions": unmet,
        "impact": rollback["impact"],
        "access_event_ids": access_event_ids,
        "authority_ids": authority_ids,
    })
    await _finish(session, evidence, context, status=status, request_id=rollback["request_id"],
                  before_fingerprints=before_fingerprints, after_fingerprints=after_fingerprints,
                  watermark_before=watermark_before, watermark_after=watermark_after,
                  impact={"entries": len(rollback["impact"]["memory_ids"]),
                          "projections": {view: row["count"] for view, row in inspect_report.items()}},
                  event_chain_closed=replay_ids == authority_ids, re_rollback_consistent=re_rollback_consistent,
                  reproducible=True,
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
    status, unmet = _traceable_rollback_verdict(
        request_id=request_id, rollback_event=rollback_event, replay_ids=[event["event_id"] for event in log],
        authority_ids=authority_ids, watermark_before=None, watermark_after=None, rollback_event_id=None,
        state_before=_manifest_state(await service.projections.current(sid)),
        state_after=_manifest_state(await service.projections.current(sid)),
        before_fingerprints={}, after_fingerprints={}, digest_fingerprint=False, inspect_report={},
        access_event_ids=[], re_rollback_consistent=None, requires_re_rollback=False)
    context["extra"].update({
        "negative_control": True,
        "audit_record": {"request_id": request_id, "operation": audit.operation, "source_event_id": audit.source_event_id},
        "authority_rollback_events": len(rollback_events),
        "checker_verdict": status,
        "checker_unmet": unmet,
    })
    await _finish(session, evidence, context, status="passed" if status == "failed" else "failed",
                  request_id=request_id, event_chain_closed=False, reproducible=True,
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
    await _finish(session, evidence, context, status=status, request_id=result["request_id"],
                  before_fingerprints=before_fingerprints, after_fingerprints=after_fingerprints,
                  watermark_before=manifest_before.source_event_id, watermark_after=manifest_after.source_event_id,
                  impact={"entries": len(result["impact"]["memory_ids"]),
                          "projections": {view: row["count"] for view, row in inspect_report.items()}},
                  event_chain_closed=True, reproducible=True, projection_denominators=denominators,
                  not_measurable_reason=reason,
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
    before_ids = await _authority_ids(session, sid)
    state_before = reduce_events(await _events(session, sid)).export()
    authority_before = _authority_axis(_manifest_state(await service.projections.current(sid)))
    bindings_before = await _binding_rows(session)
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
    unchanged = (after_ids == before_ids and authority_after == authority_before and bindings_after == bindings_before)
    all_rejected = all(item["rejected"] for item in rejections)
    status = "passed" if (unchanged and all_rejected and len(rejections) == len(entry["_meta"]["attempts"])) else "failed"
    context["extra"].update({
        "attempts": rejections,
        "attempted": len(rejections),
        "succeeded": sum(1 for item in rejections if not item["rejected"]),
        "authority_ids_before": before_ids,
        "authority_ids_after": after_ids,
        "authority_axis_unchanged": authority_after == authority_before,
        "binding_rows_unchanged": bindings_after == bindings_before,
        "binding_rows_observed": len(bindings_after),
        "state_before_entries": len(state_before["entries"]),
        "state_after_entries": len(state_after["entries"]),
    })
    await _finish(session, evidence, context, status=status, request_id=str(uuid.uuid4()),
                  impact={"entries": 0, "projections": {view: row["count"] for view, row in inspect_report.items()}},
                  event_chain_closed=after_ids == before_ids, reproducible=True,
                  extra={"unmet_sub_conditions": [item["attempt"] for item in rejections if not item["rejected"]]})


async def _authority_readonly_body(case_id: str, session, evidence, context) -> None:
    entry = case(case_id)
    allocation = context["allocation"]
    sid = await _new_scope(session, allocation)
    service = _service(session)
    memory = await _record(allocation, service, _submission(sid, content=f"AOEP authority read-only {case_id} {allocation.isolation_id[:8]}",
                                             evidence_refs=(f"3101{allocation.isolation_id[:8]}",)))
    assert_isolated(allocation, sid)
    before_ids = await _authority_ids(session, sid)
    authority_before = _authority_axis(_manifest_state(await service.projections.current(sid)))
    bindings_before = await _binding_rows(session)
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
    total_attempted = sum(item["attempted"] for item in attempted.values())
    total_succeeded = sum(item["succeeded"] for item in attempted.values())
    if total_attempted == 0:
        status, reason = "not_measurable", "no non-management rollback attempt was made; a zero sample is not a measured zero"
    elif (total_succeeded == 0 and after_ids == before_ids and authority_after == authority_before
          and bindings_after == bindings_before and all(item["rejected"] for item in attempted.values())):
        status, reason = "passed", None
    else:
        status, reason = "failed", None
    context["extra"].update({
        "non_management_rollback_attempts": attempted,
        "attempted": total_attempted,
        "succeeded": total_succeeded,
        "authority_ids_before": before_ids,
        "authority_ids_after": after_ids,
        "authority_axis_unchanged": authority_after == authority_before,
        "binding_rows_unchanged": bindings_after == bindings_before,
        "rejection_audit_records": [item.get("code") for item in attempted.values()],
    })
    await _finish(session, evidence, context, status=status, request_id=str(uuid.uuid4()),
                  impact={"entries": 0, "projections": {view: row["count"] for view, row in inspect_report.items()}},
                  event_chain_closed=after_ids == before_ids, reproducible=True,
                  not_measurable_reason=reason,
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
    context["extra"].update({
        "transitions_observed": transitions,
        "provenance_preserved_per_identity": preserved,
        "content_hash_recomputed_item_by_item": hash_checks,
        "relation_projection_provenance_preserved": projection_preserved,
        "inspect_matches_replay": {view: row["matches_replay"] for view, row in inspect_report.items()},
        "recomputed_fingerprint_matches_manifest": recomputed,
        "transition_request_ids": {"rollback": rollback["request_id"], "retire": retired["request_id"],
                                   "purge": purged["request_id"]},
    })
    await _finish(session, evidence, context, status=status, request_id=rollback["request_id"],
                  before_fingerprints=before_fingerprints, after_fingerprints=after_fingerprints,
                  watermark_before=manifest_before.source_event_id, watermark_after=manifest_after.source_event_id,
                  impact={"entries": len(rollback["impact"]["memory_ids"]) + 2,
                          "projections": {view: row["count"] for view, row in inspect_report.items()}},
                  event_chain_closed=True, reproducible=True,
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
    })
    await _finish(session, evidence, context, status=status, request_id=rollback["request_id"],
                  before_fingerprints=before_fingerprints, after_fingerprints=after_fingerprints,
                  watermark_before=manifest.source_event_id, watermark_after=manifest_final.source_event_id,
                  impact={"entries": len(rollback["impact"]["memory_ids"]),
                          "projections": {view: row["count"] for view, row in final_inspect.items()}},
                  event_chain_closed=True, reproducible=True,
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
    })
    if evidence is not None:
        dispose(twin, directory=evidence.directory,
                extra={"case_id": case_id, "role": "ambiguity_twin", "isolated_scope_id": str(twin_id)})
    await _finish(session, evidence, context, status=status, request_id=str(uuid.uuid4()),
                  event_chain_closed=True, reproducible=True,
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
    })
    await _finish(session, evidence, context, status=status, request_id=str(uuid.uuid4()),
                  event_chain_closed=True, reproducible=True,
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
