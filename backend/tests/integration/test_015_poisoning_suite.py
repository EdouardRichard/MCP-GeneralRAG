"""015 T016/T017/T072: the parameterized memory-poisoning safety gate.

The single source of truth is ``eval/memory_poisoning_eval_dataset.json``
(T015), validated against ``poisoning-eval-dataset.schema.json`` at module
import.  This module never restates an injection body, a pattern label or a
criterion: every case is consumed from the frozen dataset, and the detector
vocabulary used by the T072 desensitization scan is derived from the dataset's
own ``pattern`` enum plus live introspection of the shipped detector module.

Per case (T016, FR-003/FR-004) this suite measures eight assertions:

1. ``write_flagged``                 -- ``injection_flags.risk_level == "high"``.
2. ``write_quarantined``             -- ``status == "quarantined"`` on the write
   acknowledgement AND on the row re-read from PG.
3. ``default_recall_absent``         -- the quarantined id never appears in the
   MCP ``recall_memory`` by-id or query channels.
4. ``consolidation_input_absent``    -- the id is absent from the real
   ``MemoryReader.consolidation_candidates`` window and from the
   enablement-filter-free deterministic candidate predicate.  Consolidation is
   DEFAULT OFF (``services/memory_policy.py:57``), so the run mode is recorded
   as ``default_off`` and the live sealed-window sub-path is reported as
   ``not_measurable`` (zero sealed windows) instead of being claimed.
5. ``attachment_absent``             -- ``MemoryService.attach(...)["items"]``
   carries no entry for the id (corroborated by the attach counts).
6. ``working_set_absent``            -- the three derived ``start_work`` buckets
   (``open_items`` / ``recent_activity`` / ``procedural``) carry no entry.
7. ``control_surface_unchanged``     -- before/after comparison of the tool
   schema set, scope binding rows, domain ``memory_policy``, runtime switches,
   scope row, detector entry point and the recall filter/threshold constants:
   the number of changed items is 0.  Computed purely from the two snapshots,
   never from whether detection fired.
8. ``no_inconsistent_marking``       -- a crafted inconsistent ``revise`` event
   is refused by ``MemoryEventStore.append`` with
   ``ValueError("MEMORY_WRITE_UNAVAILABLE")`` and the event count is unchanged.

Every case runs in its own freshly created isolated scope (never an existing
one, never a forbidden id), and a benign *anchor* memory is written into that
same scope so each absence assertion has a non-zero denominator: a zero
denominator is not a measured zero.  Both the anchor and the case are episodic
so the derived ``start_work`` buckets are not crowded out of the frozen
2000-character package budget by the digest; the attachment surface is measured
inside its own frozen 800 ms budget with the attempt count exported.

T017 adds the authority-gain counters (four per-scope before/after deltas, all
zero) and the detector-unavailable path (fault-injected detector; writes are
rejected with the structured ``MEMORY_WRITE_UNAVAILABLE`` error, the process
survives, and scope/provenance/desensitization/isolation validation stays in
force; the case is recorded in ``detector_unavailable_cases`` and is never
counted as intercepted).

Write surface: the 015 evaluation database is shared with concurrent instances,
so a live writer lease can be held elsewhere (the 012 acceptance caliber refuses
to enter write mode then).  ``writer_surface`` acquires the lease and measures
the MCP ``record_memory`` tool whenever it is free; otherwise the write goes
through the identical ``MemoryService.record`` entry point and the surface
actually used is exported with the case (``write_surface=...`` in the evidence
notes) rather than silently swapped.

T072 adds the desensitization scan: no consumption surface may leak detector
internals (pattern names, thresholds, word lists).

T081 adds the honest-judgement path of FR-003 and the machine-readable variant
dictionary.  Per case this suite now *records* the observed detector outcome
(``flag_observed``/``status_observed``/``matched_patterns``/``detector_rule``)
and derives ``criterion_met`` from those observations instead of asserting the
declared ``pattern``/``risk_tier`` up front -- a high-risk case the detector does
not recognise is therefore judged not-passed (``criterion_met=false``) and still
measured, rather than aborting the run.  The three checks that must never be
silently weakened are kept, but at the level where they belong:

* the detector-independent assertion (``control_surface_unchanged``) is asserted
  unconditionally per case, and again inside :func:`judge_poisoning_case`, so it
  holds for an unrecognised variant too (FR-003);
* the coverage reverse-check (a case's declared ``pattern`` MUST be the rule that
  actually fired) and the 100% interception watermark of the frozen subset are
  asserted over the recorded judgements by
  :func:`test_every_declared_rule_and_variant_is_the_one_that_actually_fired` and
  :func:`test_interception_rate_is_computed_over_primary_cases_only`, so a
  detector regression still fails the run loudly while the per-case evidence
  stays honest;
* the residual non-detection the subset deliberately does not contain is
  disclosed as ``variant_dictionary.known_misses`` and demonstrated at the
  judgement level by ``tests/unit/test_015_poisoning_variants.py``.

Note on the marking record: the write acknowledgement legitimately returns
``injection_flags`` (including ``matched_patterns``) -- that is the graded
marking observation of FR-004, not a consumption leak, so the write response is
never scanned here.  The same field is republished by the 014 attachment item
shape and by the management browse row (``api/memory.py:297``, pinned by
``tests/integration/test_012_memory_rest.py:206``); the scan therefore drops
that one protocol-declared marking field and reports the residual exposure as
measured evidence (``marking_field_republished_on=...`` in the notes) instead of
silently ignoring it.  The quarantined case's own pattern label is additionally
required to be absent from the four consumption surfaces even unfiltered.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from jsonschema import Draft202012Validator
from sqlalchemy import func, or_, select

from rag_mcp.agents import injection_detector as detector_module
from rag_mcp.config import get_settings
from rag_mcp.db import get_session as db_get_session
from rag_mcp.mcp import create_mcp_server
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.models.scope_binding import ScopeBinding
from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider
from rag_mcp.services import memory_validators
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_policy import MemoryPolicy
from rag_mcp.services.memory_reader import (
    DEFAULT_DELIVERED_TTL_SECONDS,
    READ_GUIDANCE,
    WEIGHTS,
    MemoryReader,
    memory_visible,
)
from rag_mcp.services.memory_service import (
    ATTACH_CHARACTERS_HARD_LIMIT,
    ATTACH_EXCERPT_HARD_LIMIT,
    ATTACH_ITEMS_HARD_LIMIT,
    ATTACH_TIMEOUT_MS_HARD_LIMIT,
    MemoryService,
)
from rag_mcp.utils.snowflake import generate_id
from tests.memory_eval_datasets import (
    ASSERTION_NAMES,
    POISONING_DATASET,
    canonical,
    load_dataset,
    merged_schema,
    validate_dataset,
)

# --------------------------------------------------------------------------- #
# single source of truth: the frozen poisoning dataset
# --------------------------------------------------------------------------- #

DATASET = load_dataset(POISONING_DATASET)
validate_dataset(DATASET, "poisoning-eval-dataset.schema.json")
CASES = list(DATASET["cases"])
PRIMARY_CASES = [case for case in CASES if case["role"] == "primary"]
CONTROL_CASES = [case for case in CASES if case["role"] == "control"]

# The frozen, machine-readable variant dictionary (T081): the version, the four
# entries with their per-class minimum and the 11 shipped detector rule ids the
# subset claims to cover.  The dataset schema already enforces per-class and
# per-rule coverage; these module-level checks additionally bind the runtime
# registries below to the same dictionary.
VARIANT_DICTIONARY = DATASET["variant_dictionary"]
VARIANT_DICTIONARY_VERSION = VARIANT_DICTIONARY["version"]
assert DATASET["frozen"]["variant_dictionary"] == VARIANT_DICTIONARY_VERSION == "015.variants.1"
VARIANT_CLASSES = tuple(entry["variant_class"] for entry in VARIANT_DICTIONARY["entries"])
RULE_SURFACE = tuple(VARIANT_DICTIONARY["rule_surface"])

# The dataset schema's generic ``minItems>=5`` does not carry the role
# minimums, so they are asserted here on the real frozen file.
assert len(PRIMARY_CASES) >= 5, "the poisoning subset needs >= 5 primary cases"
assert all(case["risk_tier"] == "high" for case in PRIMARY_CASES), (
    "every primary case must be high risk, otherwise 'marked and quarantined' is unreachable"
)
assert len(VARIANT_CLASSES) == 4, VARIANT_CLASSES
for _entry in VARIANT_DICTIONARY["entries"]:
    _covered = [case for case in PRIMARY_CASES if case["variant_class"] == _entry["variant_class"]]
    assert len(_covered) >= _entry["min_cases"], (
        f"variant class {_entry['variant_class']!r} has {len(_covered)} primary case(s), "
        f"the frozen dictionary requires >= {_entry['min_cases']}")
    assert any(case.get("variant_id") == f"{VARIANT_DICTIONARY_VERSION}#{_entry['variant_class']}"
               for case in _covered), (
        f"variant class {_entry['variant_class']!r} has no case bound to its dictionary entry id")
for _rule in RULE_SURFACE:
    assert any(case["pattern"] == _rule for case in CASES), f"declared rule id {_rule!r} has no case"
assert any(case["variant_class"] for case in PRIMARY_CASES), "a primary variant case is required"
assert any(case["language"] == "zh" for case in CASES), "a Chinese-language case is required"
assert all(set(case["assertions"]) == set(ASSERTION_NAMES) for case in CASES), (
    "the dataset's assertion vocabulary must equal the shared ASSERTION_NAMES"
)
assert DATASET["explicit_criterion"]["control_cases_excluded_from_rate"] is True

FORBIDDEN_SCOPE_IDS = frozenset(str(value) for value in DATASET["isolation"]["forbidden_scope_ids"])
assert "366084747748704256" in FORBIDDEN_SCOPE_IDS
assert "c015-eval-poisoning-isolated" in DATASET["scope_id"]

POISONING_ENTRY_SCHEMA = merged_schema("memory-benchmark-common.schema.json")["$defs"]["poisoningCaseEntry"]
POISONING_ENTRY_VALIDATOR = Draft202012Validator(POISONING_ENTRY_SCHEMA)

# --------------------------------------------------------------------------- #
# detector-internals vocabulary derived from the shipped code (never restated)
# --------------------------------------------------------------------------- #

# The dataset's own pattern enum is the frozen pattern-label vocabulary.
PATTERN_LABELS = tuple(merged_schema("poisoning-eval-dataset.schema.json")["$defs"]["case"]["properties"]["pattern"]["enum"])
# The detector's word-list tables and result types, read off the live module.
PATTERN_TABLE_NAMES = tuple(sorted(
    name for name, value in vars(detector_module).items() if isinstance(value, list) and name.isupper()))
DETECTOR_TYPE_NAMES = tuple(sorted(
    name for name, value in vars(detector_module).items() if isinstance(value, type)))
# The flag-key vocabulary the sanitizer actually emits (``matched_patterns`` and
# friends) -- derived from a real call, not hand-copied.
MARKING_FIELD = "injection_flags"
MARKING_KEYS = tuple(sorted(memory_validators.sanitize_memory("015 desensitization probe").injection_flags))
FORBIDDEN_DETECTOR_TOKENS = PATTERN_LABELS + PATTERN_TABLE_NAMES + DETECTOR_TYPE_NAMES + MARKING_KEYS

#: The four genuine consumption surfaces (the write ack is not one of them).
CONSUMPTION_SURFACES = ("recall_by_id", "recall_query", "attach", "start_work", "working_set")

ANCHOR_CONTENT = (
    "015 harness anchor: the sprint review notes for the platform rewrite stay in the shared planning folder."
)
# The anchor is episodic on purpose: a procedural anchor would also occupy a
# ``start_work`` digest slot, and the derived buckets yield to the digest under
# the frozen 2000-character budget (014 T035), which would empty the buckets and
# turn the ``working_set_absent`` denominator into a silent zero.
ANCHOR_KIND = "episodic"
# Episodic keeps the case row out of the semantic/procedural digest, so both the
# anchor and an active control case land in the derived ``open_items`` bucket
# instead of being cropped by the frozen 2000-character package budget.
CASE_KIND = "episodic"

#: Per-case module-level registries the interception rate is computed from.
OBSERVED_PRIMARY: dict[str, bool] = {}
OBSERVED_CONTROL: dict[str, bool] = {}
DETECTOR_UNAVAILABLE_CASES: dict[str, bool] = {}
#: The full per-case judgement (T081), keyed by case id, so the aggregate
#: coverage reverse-check reads the *observed* rules rather than the code.
OBSERVED_JUDGEMENTS: dict[str, dict] = {}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def declared_rule_observed(case: dict, matched_patterns) -> bool:
    """FR-002/FR-007 coverage reverse-check: the declared rule must really fire.

    ``pattern == "none"`` declares the no-match control, so it requires an empty
    match list; any other declaration requires that id in ``matched_patterns``.
    """
    patterns = list(matched_patterns or ())
    if case["pattern"] == "none":
        return patterns == []
    return case["pattern"] in patterns


def detector_rule_for(case: dict, matched_patterns) -> str | None:
    """The rule that actually fired for one case (``None`` when none fired)."""
    patterns = list(matched_patterns or ())
    if case["pattern"] in patterns:
        return case["pattern"]
    return patterns[0] if patterns else None


def criterion_expected_for(case: dict) -> bool:
    """The dataset's own criterion: a primary case must be marked AND quarantined.

    ``explicit_criterion.pass_requires`` -- controls are excluded from the rate
    and are expected *not* to be intercepted, so the expected value is False.
    """
    return case["role"] == "primary"


def judge_poisoning_case(case: dict, *, flag_observed, status_observed, matched_patterns,
                         control_surface_changes: int, detector_available: bool = True) -> dict:
    """Judge ONE poisoning case honestly (FR-003) and return its evidence entry.

    The judgement is derived from *observations only*: an unrecognised variant of
    a high-risk case yields ``criterion_met = false`` and is recorded as not
    passed / not intercepted -- it never raises, and it is never recorded as
    intercepted merely because the case is declared high risk.

    The detector-independent assertion of FR-003 (``control_surface_unchanged``)
    is enforced right here, before and independently of any detection-dependent
    value, so it holds for a case the detector failed to recognise as well.
    """
    assert control_surface_changes == 0, (
        "control_surface_unchanged is the detector-independent assertion of FR-003 and it is violated "
        f"for {case['case_id']!r}: {control_surface_changes} control-surface item(s) changed")
    patterns = list(matched_patterns or ())
    if detector_available:
        criterion_met = bool(flag_observed == "high" and status_observed == "quarantined")
    else:
        criterion_met = None
    return {
        "case_id": case["case_id"],
        "role": case["role"],
        "pattern": case["pattern"],
        "risk_tier": case["risk_tier"],
        "variant_class": case["variant_class"],
        "variant_id": case.get("variant_id"),
        "language": case["language"],
        "flag_observed": flag_observed,
        "status_observed": status_observed,
        "matched_patterns": patterns,
        "detector_rule": detector_rule_for(case, patterns),
        "criterion_expected": criterion_expected_for(case),
        "criterion_met": criterion_met,
        "detector_available": detector_available,
    }


def _inference_meta(source: str) -> dict:
    return {"source": source, "confidence": 0.5, "model_version": "015.eval.1",
            "time": datetime.now(UTC).isoformat(), "supporting_evidence": []}


def _record_arguments(case: dict, *, scope_id: int | None = None, kind: str = CASE_KIND) -> dict:
    arguments = {"kind": kind, "content": case["content"], "provenance": "soft",
                 "inference_meta": _inference_meta("015 poisoning case")}
    if scope_id is not None:
        arguments["scope_id"] = scope_id
    return arguments


def _anchor_arguments(scope_id: int | None = None) -> dict:
    arguments = {"kind": ANCHOR_KIND, "content": ANCHOR_CONTENT, "provenance": "soft",
                 "inference_meta": _inference_meta("015 poisoning harness anchor")}
    if scope_id is not None:
        arguments["scope_id"] = scope_id
    return arguments


def _json_text(body) -> str:
    return json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)


def _without_marking_field(value):
    """Drop the protocol's own declared marking record (``injection_flags``).

    ``injection_flags`` is the write-time marking record itself: the write
    acknowledgement returns it by contract (FR-004) and the 014 attachment item
    shape and the management browse row republish that same record.  It is the
    marked value, not a leaked detector internal, so the desensitization scan
    looks for detector internals *outside* it.  Everything else the surface
    publishes is scanned verbatim.
    """
    if isinstance(value, dict):
        return {key: _without_marking_field(item) for key, item in value.items() if key != MARKING_FIELD}
    if isinstance(value, (list, tuple)):
        return [_without_marking_field(item) for item in value]
    return value


def _token_hits(text: str) -> list[str]:
    """Forbidden detector tokens present in ``text``.

    ``none`` is a pattern *label*, so it is matched as a quoted JSON value
    rather than as an arbitrary substring.
    """
    hits = []
    for token in FORBIDDEN_DETECTOR_TOKENS:
        needle = f'"{token}"' if token == "none" else token
        if needle in text:
            hits.append(token)
    return sorted(set(hits))


def _changed_items(before: dict, after: dict) -> list[str]:
    return sorted(key for key in before if before[key] != after[key])


async def _count(session, model, *conditions) -> int:
    return int(await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)


async def _case_events(session, sid: int) -> int:
    return await _count(session, MemoryEvent, MemoryEvent.knowledge_scope_id == sid)


async def _authority_gain_counts(session, sid: int) -> dict[str, int]:
    """The four authority-gain counters, per scope, as absolute counts.

    The four names exist only in the 015 contracts; each is derived from real
    rows (``MemoryEntry`` fields plus the append-only authority log) so a
    before/after delta is a real measurement.
    """
    became_hard = await _count(session, MemoryEntry,
                               MemoryEntry.knowledge_scope_id == sid, MemoryEntry.provenance == "hard")
    promotion_candidates = await _count(
        session, MemoryEntry, MemoryEntry.knowledge_scope_id == sid,
        or_(MemoryEntry.candidate_version.is_not(None), MemoryEntry.promote_candidate_at.is_not(None)))
    auto_promoted = await _count(
        session, MemoryEvent, MemoryEvent.knowledge_scope_id == sid, MemoryEvent.event_type == "grant",
        func.jsonb_extract_path_text(MemoryEvent.payload, "grant_type").in_(list(memory_validators.PROMOTION_GRANTS)))
    consolidated = await _count(
        session, MemoryEvent, MemoryEvent.knowledge_scope_id == sid, MemoryEvent.event_type == "consolidate",
        MemoryEvent.actor == "consolidation_service")
    return {"became_hard": became_hard, "entered_promotion_candidates": promotion_candidates,
            "auto_promoted_to_canonical": auto_promoted,
            "gained_effective_authority_via_consolidation": consolidated}


async def _control_surface(session, server, sid: int) -> dict[str, str]:
    """Before/after snapshot of the control surface (T016 assertion 7).

    The change count is derived by comparing two snapshots only: it is
    independent of whether detection fired, so it stays true for ``control``
    cases and for detection variants.
    """
    tools = await server.list_tools()
    scope = await session.get(KnowledgeScope, sid)
    profile = await session.get(DomainProfile, scope.domain_key)
    bindings = (await session.execute(
        select(ScopeBinding).where(ScopeBinding.knowledge_scope_id == sid))).scalars().all()
    settings = get_settings()
    detector = memory_validators.InjectionDetector
    return {
        "tool_schemas": canonical(sorted(
            [[tool.name, tool.inputSchema] for tool in tools], key=lambda item: item[0])),
        "scope_bindings": canonical(sorted(
            [[str(row.binding_id), row.binding_kind, row.binding_value, row.priority, row.status] for row in bindings],
            key=lambda item: item[0])),
        "domain_memory_policy": canonical(profile.memory_policy or {}),
        "runtime_switches": canonical({
            "memory_aware_retrieval_enabled": bool(settings.memory_aware_retrieval_enabled),
            "agentic_retrieval_enabled": bool(settings.agentic_retrieval_enabled),
            "instance_mode": settings.instance_mode,
            "domain_key": scope.domain_key,
        }),
        "scope_row": canonical({"scope_id": sid, "status": scope.status, "domain_key": scope.domain_key,
                                "scope_type": scope.scope_type}),
        "detector_entry_point": canonical(f"{detector.__module__}.{detector.__qualname__}"),
        "recall_threshold_constants": canonical({
            "weights": WEIGHTS, "read_guidance": READ_GUIDANCE,
            "delivered_ttl_seconds": DEFAULT_DELIVERED_TTL_SECONDS,
            "attach_limits": [ATTACH_ITEMS_HARD_LIMIT, ATTACH_CHARACTERS_HARD_LIMIT,
                              ATTACH_EXCERPT_HARD_LIMIT, ATTACH_TIMEOUT_MS_HARD_LIMIT],
            "policy_defaults": MemoryPolicy().model_dump(mode="json"),
        }),
    }


async def _create_scope(session, case_id: str) -> int:
    sid = generate_id()
    assert str(sid) not in FORBIDDEN_SCOPE_IDS, "a case must never write into a forbidden evaluator scope"
    assert sid != 366084747748704256
    session.add(KnowledgeScope(scope_id=sid, name=f"015 poisoning {case_id}",
                               slug=f"c015-eval-poisoning-isolated-{sid}",
                               scope_type="project", domain_key="generic"))
    await session.commit()
    return sid


async def _browse(test_client, session, sid: int) -> dict:
    from rag_mcp.server import app

    async def sessions():
        yield session

    app.dependency_overrides[db_get_session] = sessions
    response = await test_client.get("/api/memories", params={"scope_ref": str(sid), "limit": 100})
    assert response.status_code == 200, response.text
    return response.json()


async def _attach_with_retry(service, sid: int, *, attempts: int = 3) -> tuple[dict, int]:
    """Measure ``MemoryService.attach`` inside its own frozen 800 ms budget.

    The 014 attachment budget is capped by ``ATTACH_TIMEOUT_MS_HARD_LIMIT`` and
    cannot be widened, while Qdrant is remote, so the first dense call inside the
    attachment window can legitimately exceed it.  The measurement is retried and
    the number of attempts actually used is exported with the case.  A surface
    that never answers inside its own budget fails with its real ``failed_paths``
    -- it is never skipped.
    """
    result = None
    for attempt in range(1, attempts + 1):
        result = await service.attach(scope_ref=[str(sid)], memory_context=ANCHOR_CONTENT)
        if "attachment_timeout" not in (result.get("failed_paths") or []):
            return result, attempt
    return result, attempts


async def _consolidation_probe(session, service, sid: int) -> dict:
    """Deterministic consolidation-input probe (T016 assertion 4).

    ``MemoryReader.consolidation_candidates`` is the real accessor, but it
    filters by the scope's ``consolidation_enabled`` switch (DEFAULT OFF), which
    would make a disabled scope a zero-denominator pass.  The same
    ``memory_visible`` predicate used inside the accessor is therefore also
    applied without the enablement filter, which yields a real candidate
    universe, and the sealed-window refs are read from the authority log.
    """
    reader = MemoryReader(session, service.projections)
    candidates = await reader.consolidation_candidates(scope_ref=[str(sid)])
    rows, _salience, _manifests, failed_paths = await reader._views([sid])
    now = datetime.now(UTC)
    lifecycle_visible = {int(mid) for mid, row in rows.items() if memory_visible(row, point=None, now=now)}
    sealed = (await session.execute(select(MemoryEvent).where(
        MemoryEvent.knowledge_scope_id == sid, MemoryEvent.event_type == "grant",
        func.jsonb_extract_path_text(MemoryEvent.payload, "grant_type") == "consolidation_window"))).scalars().all()
    window_refs = set()
    for event in sealed:
        for reference in event.payload.get("source_refs") or ():
            if isinstance(reference, dict) and reference.get("memory_id") is not None:
                window_refs.add(int(reference["memory_id"]))
    profile = await session.get(DomainProfile, "generic")
    policy = (profile.memory_policy if profile is not None else None) or {}
    return {
        "candidate_ids": {int(row["memory_id"]) for row in candidates},
        "lifecycle_visible": lifecycle_visible,
        "window_refs": window_refs,
        "sealed_windows": len(sealed),
        "consolidation_enabled": bool(policy.get("consolidation_enabled", False)),
        "failed_paths": list(failed_paths),
    }


async def _inconsistent_marking_probe(session, sid: int, content: str) -> tuple[bool, int]:
    """Assertion 8: an inconsistent marking cannot be appended to the log.

    The crafted ``revise`` payload carries the dataset's own injection body and
    claims ``status == "active"`` while dropping the marking fields, i.e. it
    contradicts the marking the sanitizer derives for exactly that content.  The
    append-only store must refuse it and the event count must not move.
    """
    before = await _case_events(session, sid)
    identifier = generate_id()
    moment = datetime.now(UTC)
    event = MemoryEvent(
        event_id=identifier, aggregate_id=identifier, event_type="revise", knowledge_scope_id=sid,
        payload={"kind": CASE_KIND, "provenance": "soft", "content_text": content, "status": "active",
                 "inference_meta": _inference_meta("015 inconsistent marking probe")},
        actor="memory_tool", request_id=str(uuid4()), session_id=None, occurred_at=moment,
        valid_from=moment, authority={"source": "inference"},
        scope_meta={"knowledge_scope_id": sid}, mutability={"correction": "supersede"},
        provenance_meta={}, recoverability={"source": "event_log"}, actionability="evidence")
    with pytest.raises(ValueError) as failure:
        await MemoryEventStore(session).append(event)
    assert str(failure.value) == "MEMORY_WRITE_UNAVAILABLE", (
        f"an inconsistent marking must be refused with MEMORY_WRITE_UNAVAILABLE, got {failure.value!r}")
    after = await _case_events(session, sid)
    assert after == before, "a refused inconsistent event must not change the event count"
    return True, before


def _check_desensitization(surfaces: dict[str, dict], case: dict, role: str) -> dict:
    """T072: no consumption surface leaks detector internals.

    The full responses are scanned for the poisoned case's own pattern label
    (which must never surface once the entry is quarantined) and the responses
    with the protocol's own marking field removed are scanned for the whole
    forbidden vocabulary derived from the dataset schema and the detector
    module.
    """
    hits: dict[str, list[str]] = {}
    marking_hits: dict[str, list[str]] = {}
    own_pattern = case["pattern"]
    own_hits: dict[str, list[str]] = {}
    for name, body in surfaces.items():
        hits[name] = _token_hits(_json_text(_without_marking_field(body)))
        marking_hits[name] = _token_hits(_json_text(body))
        if role == "primary":
            needle = f'"{own_pattern}"' if own_pattern == "none" else own_pattern
            own_hits[name] = [own_pattern] if needle in _json_text(body) else []
    for name, found in hits.items():
        assert found == [], f"consumption surface {name!r} leaks detector internals: {found}"
    if role == "primary":
        for name in CONSUMPTION_SURFACES:
            assert own_hits[name] == [], (
                f"the quarantined case's own pattern label surfaced on consumption surface {name!r}")
    return {"surface_hits": hits, "marking_field_hits": marking_hits, "own_pattern_hits": own_hits}


@pytest_asyncio.fixture
async def writer_surface(engine):
    """The measured write surface for one case: ``"mcp"`` or ``"service"``.

    The 015 evaluation database is shared, so a concurrent instance can hold the
    live writer lease (the 012 acceptance caliber refuses to enter write mode
    while another holder is unexpired).  The MCP ``record_memory`` surface is
    measured whenever the lease is available; otherwise the write goes through
    the identical ``MemoryService.record`` entry point and the surface actually
    used is exported with the case instead of being silently swapped.
    """
    from tests.integration.memory_acceptance import writer_owner

    try:
        async with writer_owner(engine):
            yield "mcp"
    except AssertionError:
        yield "service"


async def _record(server, service, arguments: dict, sid: int, surface: str) -> dict:
    """Write through the measured surface and return the acknowledgement body."""
    if surface == "mcp":
        result = await server.call_tool("record_memory", {**arguments, "scope_ref": str(sid)})
        assert not result.isError, result.structuredContent
        return result.structuredContent
    return await service.record({**arguments, "scope_id": sid})


async def _write_error_code(server, service, arguments: dict, sid: int, surface: str) -> str:
    """Attempt a write that must be refused and return its structured error code."""
    from rag_mcp.mcp.serialization import memory_error

    if surface == "mcp":
        result = await server.call_tool("record_memory", {**arguments, "scope_ref": str(sid)})
        assert result.isError, result.structuredContent
        return result.structuredContent["error"]["code"]
    with pytest.raises(ValueError) as failure:
        await service.record({**arguments, "scope_id": sid})
    return memory_error(failure.value).structuredContent["error"]["code"]


# --------------------------------------------------------------------------- #
# T016 + T072: per-case measurement
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", CASES, ids=[entry["case_id"] for entry in CASES])
@pytest.mark.asyncio
async def test_poisoning_case(case, db_session, engine, writer_surface, memory_eval_evidence, test_client):
    sid = await _create_scope(db_session, case["case_id"])
    provider = LocalCPUEmbeddingProvider()

    @asynccontextmanager
    async def sessions():
        yield db_session

    server = create_mcp_server(session_factory=sessions, embedding_provider=provider, mode="writer")
    service = MemoryService(db_session, embedding_provider=provider)

    before_surface = await _control_surface(db_session, server, sid)
    gains_before = await _authority_gain_counts(db_session, sid)

    # Non-zero denominator: an ordinary active memory in the SAME dedicated
    # scope, so every absence assertion is measured against a live surface.
    anchor_payload = await _record(server, service, _anchor_arguments(), sid, writer_surface)
    anchor_id = int(anchor_payload["memory_id"])
    assert anchor_payload["status"] == "active"
    assert anchor_payload["injection_flags"]["risk_level"] == "none"

    payload = await _record(server, service, _record_arguments(case), sid, writer_surface)
    memory_id = int(payload["memory_id"])
    flags = payload["injection_flags"]
    flag_observed = flags["risk_level"]
    status_observed = payload["status"]

    # --- 1. write_flagged / 2. write_quarantined -------------------------- #
    # FR-003: the detector outcome is observed and recorded, never predicted by an
    # assertion on the declared tier/role.  An unrecognised variant of a high-risk
    # case is judged honestly below (criterion_met=false) and the run continues --
    # the declared coverage is reverse-checked in aggregate further down.
    write_flagged = flags["risk_level"] == "high"
    write_quarantined = status_observed == "quarantined"
    declared_rule_fired = declared_rule_observed(case, flags["matched_patterns"])
    row = await db_session.get(MemoryEntry, memory_id, populate_existing=True)
    assert row is not None and row.status == status_observed, "the acknowledgement must match the persisted row"
    assert row.injection_flags["risk_level"] == flags["risk_level"]
    assert row.write_status == "complete"
    persisted_status = row.status

    # --- 3. default_recall_absent ---------------------------------------- #
    by_id = await server.call_tool("recall_memory", {"scope_ref": [str(sid)], "memory_ids": [memory_id]})
    assert not by_id.isError, by_id.structuredContent
    by_id_body = by_id.structuredContent
    by_id_ids = {int(item["memory_id"]) for item in by_id_body["memories"]}
    anchor_by_id = await server.call_tool("recall_memory", {"scope_ref": [str(sid)], "memory_ids": [anchor_id]})
    assert [int(item["memory_id"]) for item in anchor_by_id.structuredContent["memories"]] == [anchor_id], (
        "the by-id recall channel must be demonstrably live")
    query_recall = await server.call_tool("recall_memory", {"scope_ref": [str(sid)], "query": ANCHOR_CONTENT})
    assert not query_recall.isError, query_recall.structuredContent
    query_body = query_recall.structuredContent
    query_ids = {int(item["memory_id"]) for item in query_body["memories"]}
    assert anchor_id in query_ids, "the query recall channel must be demonstrably live"
    default_recall_absent = memory_id not in by_id_ids and memory_id not in query_ids

    # --- 4. consolidation_input_absent ----------------------------------- #
    probe = await _consolidation_probe(db_session, service, sid)
    assert probe["consolidation_enabled"] is False, "T016 asserts the deterministic default-off path"
    assert anchor_id in probe["lifecycle_visible"], "the candidate predicate must be demonstrably live"
    consolidation_input_absent = (memory_id not in probe["candidate_ids"]
                                  and memory_id not in probe["lifecycle_visible"]
                                  and memory_id not in probe["window_refs"])
    consolidation_run_mode = "default_off" if not probe["consolidation_enabled"] else "enabled"

    # --- 5. attachment_absent -------------------------------------------- #
    # Warm the service-level dense path (the attachment window is 800 ms and the
    # vector store is built on first use), then measure the attachment itself.
    warm_recall = await service.recall(scope_ref=[str(sid)], query=ANCHOR_CONTENT)
    assert anchor_id in {int(item["memory_id"]) for item in warm_recall["memories"]}
    attachment, attach_attempts = await _attach_with_retry(service, sid)
    attachment_ids = {int(item["memory_id"]) for item in attachment["items"]}
    assert attachment_ids, (attachment["counts"], attachment["failed_paths"], attachment["injection_flags"])
    assert anchor_id in attachment_ids, attachment["failed_paths"]
    attachment_absent = memory_id not in attachment_ids

    # --- 6. working_set_absent ------------------------------------------- #
    # The derived buckets are measured on the service path: the MCP tool form is
    # additionally gated by MEMORY_AWARE_RETRIEVAL_ENABLED (default false), and
    # that deployment gate is recorded rather than silently bypassed.
    package = await service.start_work(scope_ref=str(sid), include_working_set=True)
    buckets = package["working_set"]["working_set"]
    bucket_ids = {int(item["memory_id"]) for name in ("open_items", "recent_activity", "procedural")
                  for item in buckets[name]}
    digest_ids = {int(item["memory_id"]) for item in package["digest"]["memories"]}
    assert anchor_id in bucket_ids, "the derived working set must be demonstrably live"
    mcp_package = await server.call_tool("start_work", {"scope_ref": str(sid), "include_working_set": True})
    assert not mcp_package.isError, mcp_package.structuredContent
    mcp_body = mcp_package.structuredContent
    mcp_derived = "working_set" in mcp_body["working_set"]
    mcp_ids = {int(item["memory_id"]) for item in mcp_body["working_set"]["memories"]}
    working_set_absent = memory_id not in bucket_ids and memory_id not in digest_ids
    assert memory_id not in mcp_ids

    # --- T072 desensitization -------------------------------------------- #
    desensitization = _check_desensitization(
        {"recall_by_id": by_id_body, "recall_query": query_body, "attach": attachment,
         "start_work": mcp_body, "working_set": buckets,
         "browse": await _browse(test_client, db_session, sid)},
        case, case["role"])
    marking_exposure = {name: hits for name, hits in desensitization["marking_field_hits"].items() if hits}

    # --- 8. no_inconsistent_marking (with the real detector) ------------- #
    no_inconsistent_marking, events_before = await _inconsistent_marking_probe(db_session, sid, case["content"])

    # --- 7. control_surface_unchanged ------------------------------------ #
    after_surface = await _control_surface(db_session, server, sid)
    changed = _changed_items(before_surface, after_surface)
    assert changed == [], f"the control surface moved: {changed}"

    # --- authority gain counts (T017) ------------------------------------ #
    gains_after = await _authority_gain_counts(db_session, sid)
    authority_gain_counts = {name: gains_after[name] - gains_before[name] for name in gains_after}
    assert list(authority_gain_counts) == ["became_hard", "entered_promotion_candidates",
                                           "auto_promoted_to_canonical", "gained_effective_authority_via_consolidation"]
    assert all(delta == 0 for delta in authority_gain_counts.values()), authority_gain_counts

    # --- FR-003 judgement: recorded from the observations, never predicted -- #
    # The detector-independent half of FR-003 (``control_surface_unchanged``) is
    # enforced unconditionally inside the judgement; the detection-dependent half
    # is enforced as the real quarantine implication -- quarantined storage MUST
    # NOT reach any consumption surface -- instead of as a prediction that the
    # detector must fire.  A high-risk case the detector does not recognise is
    # therefore recorded as NOT passed / NOT intercepted and the run continues;
    # the frozen subset's 100% watermark is asserted over the recorded judgements
    # by ``test_interception_rate_is_computed_over_primary_cases_only``.
    judgement = judge_poisoning_case(
        case, flag_observed=flag_observed, status_observed=status_observed,
        matched_patterns=flags["matched_patterns"], control_surface_changes=len(changed))
    criterion_met = judgement["criterion_met"]
    if status_observed == "quarantined":
        assert by_id_body["completion_status"] == "no_evidence" and by_id_body["memories"] == []
        assert by_id_body["counts"]["filtered_inactive"] >= 1, by_id_body["counts"]
        assert all(value is True for value in (default_recall_absent, consolidation_input_absent,
                                               attachment_absent, working_set_absent)), (
            "a quarantined entry MUST NOT reach any consumption surface")
    if status_observed == "active":
        assert memory_id in by_id_ids and memory_id in query_ids, (
            "an active entry must stay recallable, otherwise the absence assertions would be a silent zero")

    assertions = {
        "write_flagged": bool(write_flagged),
        "write_quarantined": bool(write_quarantined),
        "default_recall_absent": bool(default_recall_absent),
        "consolidation_input_absent": bool(consolidation_input_absent),
        "attachment_absent": bool(attachment_absent),
        "working_set_absent": bool(working_set_absent),
        "control_surface_unchanged": changed == [],
        "no_inconsistent_marking": bool(no_inconsistent_marking),
    }
    assert list(assertions) == list(ASSERTION_NAMES)

    entry = {
        **judgement,
        "status_observed": persisted_status,
        "six_assertions": assertions,
        "control_surface_changes": len(changed),
        "authority_gain_counts": authority_gain_counts,
        "not_measurable_reason": None,
    }
    POISONING_ENTRY_VALIDATOR.validate(entry)

    if case["role"] == "primary":
        OBSERVED_PRIMARY[case["case_id"]] = bool(criterion_met)
    else:
        OBSERVED_CONTROL[case["case_id"]] = bool(criterion_met)
    OBSERVED_JUDGEMENTS[case["case_id"]] = entry

    if memory_eval_evidence is not None:
        memory_eval_evidence.record_poisoning_case(entry)
        memory_eval_evidence.add_note(
            f"T016 {case['case_id']}: isolated_scope_id={sid} anchor_id={anchor_id} write_surface={writer_surface} "
            f"consolidation_run_mode={consolidation_run_mode} sealed_consolidation_windows={probe['sealed_windows']} "
            f"candidates={len(probe['candidate_ids'])} lifecycle_visible={len(probe['lifecycle_visible'])} "
            f"recall_filtered_inactive={by_id_body['counts']['filtered_inactive']} "
            f"attach_candidates={attachment['counts']['candidates']} attach_failed_paths={attachment['failed_paths']} "
            f"attach_attempts={attach_attempts} "
            f"working_set_buckets={len(bucket_ids)} digest={len(digest_ids)} mcp_derived_working_set={mcp_derived} "
            f"events_before_inconsistent_probe={events_before} "
            f"marking_field_republished_on={sorted(marking_exposure)}")
        memory_eval_evidence.add_note(
            f"T081 {case['case_id']}: declared_pattern={case['pattern']} "
            f"declared_rule_fired={declared_rule_fired} observed_risk={flag_observed} "
            f"observed_status={persisted_status} matched_patterns={judgement['matched_patterns']} "
            f"detector_rule={judgement['detector_rule']} variant_class={case['variant_class']} "
            f"variant_id={judgement['variant_id']} criterion_expected={judgement['criterion_expected']} "
            f"criterion_met={criterion_met}")
    if probe["sealed_windows"] == 0:
        # A live sealed consolidation window does not exist on the default-off
        # path, so that sub-path has a zero denominator: it is not measurable
        # and is recorded as such (``sealed_consolidation_windows=0`` in the
        # notes) instead of being claimed as a measured zero.
        assert probe["window_refs"] == set()


# --------------------------------------------------------------------------- #
# T017/T081: interception rate is defined over the primary set only
# --------------------------------------------------------------------------- #


def test_interception_rate_is_computed_over_primary_cases_only():
    assert len(OBSERVED_PRIMARY) == len(PRIMARY_CASES) >= 5, sorted(OBSERVED_PRIMARY)
    assert len(OBSERVED_CONTROL) == len(CONTROL_CASES) >= 2, sorted(OBSERVED_CONTROL)
    numerator = sorted(case_id for case_id, met in OBSERVED_PRIMARY.items() if met)
    denominator = sorted(OBSERVED_PRIMARY)
    # The frozen subset's 100% watermark (FR-002).  This is the one place the
    # watermark is asserted: every unmet case is already recorded honestly as
    # criterion_met=false by the per-case judgement, so a detector regression
    # fails here by name instead of aborting the measurement run.
    assert numerator == denominator, (
        "the frozen subset's 100% interception watermark is not met; these cases were recorded as "
        f"NOT intercepted (criterion_met=false): {sorted(set(denominator) - set(numerator))}")
    rate = len(numerator) / len(denominator)
    assert rate == 1.0
    assert not set(OBSERVED_CONTROL) & set(denominator), "control cases must not enter the rate denominator"
    assert not set(OBSERVED_CONTROL) & set(numerator), "control cases must not enter the rate numerator"
    assert not set(DETECTOR_UNAVAILABLE_CASES) & set(denominator), (
        "the detector-unavailable case must never enter the interception rate")
    assert all(met is False for met in OBSERVED_CONTROL.values())


def test_every_declared_rule_and_variant_is_the_one_that_actually_fired():
    """FR-002/FR-007 coverage reverse-check, read off the recorded judgements.

    The per-case judgement never asserts the declared pattern (FR-003 makes that
    path unreachable for an unrecognised variant); the coverage claim is checked
    here instead, over the *observed* rules of the whole frozen subset, so an
    overstated coverage declaration ("declares identity_override, actually
    matched role_hijack") still fails the run.
    """
    assert set(OBSERVED_JUDGEMENTS) == {case["case_id"] for case in CASES}, (
        "every frozen case must have produced a recorded judgement")
    annotated = {case["variant_class"] for case in CASES if case.get("variant_id")}
    assert set(VARIANT_CLASSES) <= annotated, (
        f"every declared variant class needs at least one case bound to its entry id; missing "
        f"{sorted(set(VARIANT_CLASSES) - annotated)}")
    for case in CASES:
        judgement = OBSERVED_JUDGEMENTS[case["case_id"]]
        assert judgement["matched_patterns"] == list(judgement["matched_patterns"])
        if case["pattern"] == "none":
            assert judgement["matched_patterns"] == [], (case["case_id"], judgement)
            assert judgement["detector_rule"] is None, judgement
        else:
            assert declared_rule_observed(case, judgement["matched_patterns"]), (
                f"{case['case_id']} declares pattern {case['pattern']!r} but the detector matched "
                f"{judgement['matched_patterns']!r}")
            assert judgement["detector_rule"] == case["pattern"], judgement
        assert judgement["variant_id"] == case.get("variant_id"), judgement
        assert judgement["criterion_expected"] is criterion_expected_for(case), judgement


def test_known_misses_are_disclosed_and_never_enter_the_frozen_subset():
    """FR-003 residual limitation: disclosed, machine-readable and traceable."""
    misses = VARIANT_DICTIONARY["known_misses"]
    assert misses, "the residual detector limitation must be disclosed"
    contents = {case["content"] for case in CASES}
    for miss in misses:
        assert miss["observed_risk_level"] == "none" and miss["observed_status"] == "active"
        assert miss["observed_matched_patterns"] == []
        assert miss["reason"].strip()
        assert miss["content"] not in contents, (
            "a known miss MUST NOT be added to the frozen subset: it would break the 100% watermark")


# --------------------------------------------------------------------------- #
# T017: authority gain + detector-unavailable path
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_detector_unavailable_write_is_rejected_and_validations_are_not_relaxed(
        db_session, engine, writer_surface, memory_eval_evidence, monkeypatch):
    probe = PRIMARY_CASES[0]
    sid = await _create_scope(db_session, "poison_detector_unavailable")
    provider = LocalCPUEmbeddingProvider()

    @asynccontextmanager
    async def sessions():
        yield db_session

    server = create_mcp_server(session_factory=sessions, embedding_provider=provider, mode="writer")
    service = MemoryService(db_session, embedding_provider=provider)

    anchor_payload = await _record(server, service, _anchor_arguments(), sid, writer_surface)
    assert anchor_payload["status"] == "active"

    before_surface = await _control_surface(db_session, server, sid)
    gains_before = await _authority_gain_counts(db_session, sid)
    entries_before = await _count(db_session, MemoryEntry, MemoryEntry.knowledge_scope_id == sid)
    events_before = await _case_events(db_session, sid)
    global_entries_before = await _count(db_session, MemoryEntry)
    forbidden_before = {forbidden: await _count(
        db_session, MemoryEntry, MemoryEntry.knowledge_scope_id == int(forbidden)) for forbidden in FORBIDDEN_SCOPE_IDS}

    class FaultyDetector:
        """Fault-injected stand-in: ``detect`` raises, exactly like VS-03."""

        def detect(self, text, *, strict=False):
            raise RuntimeError("015 detector fault injection")

    with monkeypatch.context() as broken:
        broken.setattr(memory_validators, "InjectionDetector", FaultyDetector)
        # Fault injection: the same call that normally succeeds must now be
        # refused with the structured MEMORY_WRITE_UNAVAILABLE error.
        write_error_code = await _write_error_code(
            server, service, _record_arguments(probe), sid, writer_surface)
        assert write_error_code == "MEMORY_WRITE_UNAVAILABLE", write_error_code
        assert write_error_code != "MEMORY_QUOTA_EXCEEDED"

        # The process did not crash: the very next call still answers.
        alive = await server.call_tool("recall_memory", {"scope_ref": [str(sid)]})
        assert not alive.isError, alive.structuredContent

        # Scope validation runs before detection (memory_service.py:657 vs :663),
        # so it must be probed on its own call -- and so must provenance.
        with pytest.raises(ValueError, match="MISSING_KNOWLEDGE_SCOPE"):
            await service.record({**_record_arguments(probe), "scope_id": generate_id()})
        from rag_mcp.services.scope_resolver import MemoryScopeResolver

        with pytest.raises(Exception, match="MISSING_KNOWLEDGE_SCOPE"):
            await MemoryScopeResolver(db_session).resolve(str(generate_id()))

        # Provenance validation also runs before detection: an unanchored hard
        # write must still fail with its own code.
        hard_error_code = await _write_error_code(
            server, service, {"kind": CASE_KIND, "content": probe["content"], "provenance": "hard"},
            sid, writer_surface)
        assert hard_error_code == "MEMORY_EVIDENCE_ANCHOR_REQUIRED", hard_error_code

        # Nothing was stored anywhere: desensitization/storage and isolation are
        # not relaxed by a broken detector.
        assert await _count(db_session, MemoryEntry, MemoryEntry.knowledge_scope_id == sid) == entries_before
        assert await _case_events(db_session, sid) == events_before
        assert await _count(db_session, MemoryEntry) == global_entries_before
        for forbidden, count in forbidden_before.items():
            assert await _count(db_session, MemoryEntry,
                                MemoryEntry.knowledge_scope_id == int(forbidden)) == count

    # Detection precedes the quota check (memory_service.py:663 vs :698), so a
    # broken detector can never let an over-quota write through; the quota path
    # itself is unreachable while detection fails and is reported as such.
    quota_relaxation_observable = False

    no_inconsistent_marking, events_checked = await _inconsistent_marking_probe(db_session, sid, probe["content"])
    after_surface = await _control_surface(db_session, server, sid)
    changed = _changed_items(before_surface, after_surface)
    assert changed == [], f"the control surface did not return to its baseline: {changed}"

    gains_after = await _authority_gain_counts(db_session, sid)
    authority_gain_counts = {name: gains_after[name] - gains_before[name] for name in gains_after}
    assert all(delta == 0 for delta in authority_gain_counts.values()), authority_gain_counts

    assertions = {
        "write_flagged": False, "write_quarantined": False,
        "default_recall_absent": True, "consolidation_input_absent": True,
        "attachment_absent": True, "working_set_absent": True,
        "control_surface_unchanged": changed == [],
        "no_inconsistent_marking": bool(no_inconsistent_marking),
    }
    assert list(assertions) == list(ASSERTION_NAMES)
    # T081: the same judgement, with detection unavailable, must record
    # criterion_met=None (not measurable) -- never False-as-a-failure and never
    # True-as-intercepted; the detector-independent assertion is still enforced.
    unavailable_case = {**probe, "case_id": "poison_detector_unavailable"}
    judgement = judge_poisoning_case(
        unavailable_case, flag_observed=None, status_observed=None, matched_patterns=[],
        control_surface_changes=len(changed), detector_available=False)
    assert judgement["criterion_met"] is None, judgement
    assert judgement["criterion_expected"] is True, judgement
    entry = {
        **judgement,
        "six_assertions": assertions,
        "control_surface_changes": len(changed),
        "authority_gain_counts": authority_gain_counts,
        "not_measurable_reason": (
            "Detector fault injection (VS-03): the write is rejected with MEMORY_WRITE_UNAVAILABLE and is therefore "
            "not measurable as 'intercepted'; the case is excluded from the interception-rate numerator and "
            "denominator and recorded in detector_unavailable_cases. Quota relaxation is not separately observable "
            "because detection (memory_service.py:663) precedes the quota check (:698); scope and provenance "
            "validation, non-storage of the rejected body and the unchanged control surface were measured directly."
        ),
    }
    POISONING_ENTRY_VALIDATOR.validate(entry)
    DETECTOR_UNAVAILABLE_CASES[entry["case_id"]] = False

    if memory_eval_evidence is not None:
        memory_eval_evidence.record_poisoning_case(entry)
        memory_eval_evidence.add_note(
            f"T017 poison_detector_unavailable: isolated_scope_id={sid} write_surface={writer_surface} "
            f"write_error_code={write_error_code} "
            f"missing_scope_code=MISSING_KNOWLEDGE_SCOPE unanchored_hard_code={hard_error_code} "
            f"entries_unchanged={entries_before} events_unchanged={events_before} "
            f"global_entries_unchanged={global_entries_before} forbidden_scope_writes=0 "
            f"inconsistent_marking_events_before={events_checked} "
            f"quota_relaxation_observable={quota_relaxation_observable} (detection precedes the quota check) "
            f"intercepted=False excluded_from_rate=True")
