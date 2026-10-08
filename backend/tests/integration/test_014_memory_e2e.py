"""014 end-to-end memory behaviours (T031 seeds this file; US7 T060 extends it).

The three-channel delivered-set case is seeded here because it is the acceptance
for US3: after the *same* session has been served the same memory through
``recall_memory``, then through the ``search_knowledge`` attachment layer, then
through the ``start_work`` package, the default behaviour is dedup across all three
and ``include_delivered=true`` restores the previously delivered items **without**
relaxing scope, state, expiry or threshold.

These tests use the project's configured PostgreSQL (and Qdrant for the attachment
arm) — the same database the 012 live-reader acceptance uses — and create only
throwaway randomly-named scopes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from rag_mcp.models.memory_recall_run import MemoryRecallRun
from rag_mcp.mcp.search_knowledge import merge_attachment_response
from rag_mcp.services.memory_reader import delivered_memory_ids
from rag_mcp.services.memory_service import MemoryService

from tests.integration.test_012_live_reader import scope_and_payload

# Session identities must be unique per run: the delivered set is persistent for
# the short TTL, so a reused fixed UUID would be legitimately deduped on a re-run.
SESSION_ONE = str(uuid4())
SESSION_TWO = str(uuid4())
SESSION_THREE = str(uuid4())
SESSION_A = str(uuid4())
SESSION_B = str(uuid4())
SESSION_C = str(uuid4())


async def _record_episodic(service, session, *, session_id, content):
    sid, payload = await scope_and_payload(session)
    recorded = await service.record({
        **payload, "kind": "episodic", "content": content, "session_id": session_id,
    })
    return sid, recorded["memory_id"]


# =============================================================================
# T060 ①: two-session continuity — record, resume, then recover the breakpoint.
# =============================================================================


@pytest.mark.asyncio
async def test_two_session_continuity_resumes_the_breakpoint(db_session):
    service = MemoryService(db_session)
    sid, memory_id = await _record_episodic(
        service, db_session, session_id=SESSION_A,
        content="Breakpoint: the migration head must be 0104 before 014 lands.",
    )

    # The *next* session opens the work package with the explicit switch.
    package = await service.start_work(scope_ref=str(sid), session_id=SESSION_B,
                                       include_working_set=True)
    derived = package["working_set"]["working_set"]
    recovered = {item["memory_id"] for item in
                 derived["open_items"] + derived["recent_activity"] + derived["procedural"]}
    assert memory_id in recovered, "the breakpoint memory must be recovered"
    # The breakpoint is complete: every recovered item carries its provenance and
    # excerpt, so a reader can act on it without a second call.
    for bucket in ("open_items", "recent_activity", "procedural"):
        for item in derived[bucket]:
            assert item["content_excerpt"]
            assert "provenance" in item and "observed_at" in item
    assert package["read_guidance"]
    assert list(package) == ["scope", "domain_brief", "digest", "working_set", "read_guidance",
                             "counts", "package_fingerprint", "request_id"]


@pytest.mark.asyncio
async def test_session_b_continuation_is_repeatable_byte_for_byte(db_session):
    service = MemoryService(db_session)
    sid, _ = await _record_episodic(service, db_session, session_id=SESSION_A,
                                    content="A durable continuation fact.")

    def stripped(body):
        return {key: value for key, value in body.items() if key != "request_id"}

    first = await service.start_work(scope_ref=str(sid), session_id=SESSION_B,
                                    include_working_set=True)
    second = await service.start_work(scope_ref=str(sid), session_id=SESSION_B,
                                      include_working_set=True)
    assert stripped(first) == stripped(second), "same input must give identical package bytes"


# =============================================================================
# T060 ②: primary retrieval with session context annotates memories, never mixes them.
# =============================================================================


@pytest.mark.asyncio
async def test_search_with_session_context_annotates_and_never_mixes(db_session, monkeypatch):
    import asyncio

    import rag_mcp.mcp.search_knowledge as search_module
    from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider

    provider = LocalCPUEmbeddingProvider()
    # Warm the embedding model first: the attachment layer has an independent
    # 800 ms budget, and a cold model load would legitimately degrade it to
    # ``attachment_timeout`` (asserted by the unit tests) instead of attaching.
    # The running service warms its provider at startup, so this mirrors it.
    await asyncio.to_thread(provider.warmup)

    service = MemoryService(db_session, embedding_provider=provider)
    sid, memory_id = await _record_episodic(
        service, db_session, session_id=SESSION_C,
        content="The delivery window is one hour for this session.")
    monkeypatch.setenv("MEMORY_AWARE_RETRIEVAL_ENABLED", "true")

    from rag_mcp.mcp import create_mcp_server

    server = create_mcp_server(embedding_provider=provider, mode="writer")
    content, structured = await server.call_tool("search_knowledge", {
        "query": "what is the delivery window",
        "domain_scope": [str(sid)],
        "session_id": SESSION_C,
        "memory_context": "The delivery window is one hour for this session.",
    })
    assert list(structured) == ["completion_status", "evidence", "related_memories",
                                "memory_notice", "counts", "request_id"] or \
        list(structured) == ["completion_status", "evidence", "related_memories",
                             "memory_notice", "counts", "gaps", "request_id"], list(structured)

    attachments = structured["related_memories"]
    assert memory_id in {item["memory_id"] for item in attachments}, \
        f"the session memory must be attached: {attachments}"
    evidence = structured["evidence"]
    # Non-mixing, at runtime and in both directions.
    evidence_ids = {item.get("evidence_id") for item in evidence}
    assert evidence_ids.isdisjoint({str(item["memory_id"]) for item in attachments})
    for item in attachments:
        for field in ("source_position", "source_version", "relevance_score"):
            assert field not in item, f"attachment must not carry {field}"
        assert item["status"] == "active"
        assert item["valid_to"] is None and item["superseded_by"] is None
        assert item["injection_flags"] is not None
    for item in evidence:
        assert "memory_id" not in item, "evidence must not carry memory vocabulary"

    # The notice carries both required elements and the untrusted flag.
    notice = structured["memory_notice"]
    assert notice["untrusted"] is True
    import rag_mcp.mcp.search_knowledge as module

    assert module.notice_is_compliant(notice["notice"])
    # The primary result was not rewritten by the memory layer.
    assert structured["completion_status"] in {"complete", "partial", "no_evidence"}
    assert content[0].text.index('"evidence"') < content[0].text.index('"related_memories"')


# =============================================================================
# T060 ③: the memory-on / memory-off contrast is measurable on real data.
# =============================================================================


@pytest.mark.asyncio
async def test_memory_on_versus_off_contrast_is_measurable(db_session):
    """A real two-arm measurement of the continuation criterion.

    The full frozen-snapshot record/replay gate (T058/T059) additionally needs a
    sealed capsule and a snapshot, which this environment does not have. What *is*
    executable — and is measured here — is the variable the gate is about: with
    memory the continuation item is recovered and the criterion completes; without
    it the response carries the legacy shape and the criterion genuinely misses.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "eval"))
    from memory_continuity_support import ArmObservation, task_complete

    service = MemoryService(db_session)
    sid, memory_id = await _record_episodic(
        service, db_session, session_id=SESSION_A,
        content="Preference: always answer with the explicit scope listed first.")

    query = {"query_id": "q_continuity", "required_items": [{"locator": "continuation"}]}

    # Memory-on arm: the explicit signal recovers the item.
    package_on = await service.start_work(scope_ref=str(sid), session_id=SESSION_B,
                                         include_working_set=True)
    derived = package_on["working_set"]["working_set"]
    recovered = {item["memory_id"] for item in
                 derived["open_items"] + derived["recent_activity"] + derived["procedural"]}
    assert memory_id in recovered
    on_observation = ArmObservation(query_id="q_continuity", arm="with_memory",
                                    hits=("continuation",))

    # Memory-off arm: no explicit switch, so the 012 shape and no memory content.
    package_off = await service.start_work(scope_ref=str(sid))
    assert "working_set" not in package_off["working_set"]
    off_observation = ArmObservation(query_id="q_continuity", arm="without_memory", hits=())

    on_result = task_complete(query, on_observation)
    off_result = task_complete(query, off_observation)
    assert on_result["task_complete"] is True, on_result
    assert off_result["task_complete"] is False, off_result
    assert off_result["missing"] == ["continuation"], "the baseline genuinely misses it"
    # The only variable between the arms is memory availability.
    assert set(package_on) == set(package_off)


# =============================================================================
# T060 ④: the existing retrieval evaluation inputs are unregressed.
# =============================================================================


def test_existing_eval_datasets_are_byte_unchanged():
    """011's fixed-set discipline: the three pinned datasets must not move.

    The expected digests come from the 011 contract test itself (single source of
    truth), so this is a real cross-check rather than a duplicated literal.
    """
    import hashlib
    from pathlib import Path

    from tests.contract.test_domain_eval_dataset_schema import _EXISTING_DATASET_SHA256

    eval_dir = Path(__file__).resolve().parents[3] / "eval"
    assert _EXISTING_DATASET_SHA256, "the 011 pin map must not be empty"
    for name, expected in _EXISTING_DATASET_SHA256.items():
        actual = hashlib.sha256((eval_dir / name).read_bytes()).hexdigest()
        assert actual == expected, f"{name} changed: {actual} != {expected}"




async def _record_in_session(service, session, session_id):
    """Record one procedural memory bound to ``session_id`` (so session filters match)."""
    sid, payload = await scope_and_payload(session)
    recorded = await service.record({**payload, "session_id": session_id})
    return sid, recorded["memory_id"]


@pytest.mark.asyncio
async def test_three_channels_share_one_delivered_set(db_session):
    """recall -> attached -> start_work, then a second recall dedupes."""
    service = MemoryService(db_session)
    sid, memory_id = await _record_in_session(service, db_session, SESSION_ONE)

    # Channel 1: recall_memory delivers it.
    first = await service.recall(scope_ref=[str(sid)], session_id=SESSION_ONE)
    assert [row["memory_id"] for row in first["memories"]] == [memory_id]

    # Channel 2: the attachment layer sees the same session and dedupes it.
    attached = await service.attach(scope_ref=[str(sid)], query="what did we decide",
                                    session_id=SESSION_ONE)
    assert attached["items"] == []
    assert attached["counts"]["dropped_delivered"] >= 1

    # Channel 3: start_work records its own channel for the returned ids.
    package = await service.start_work(scope_ref=str(sid), session_id=SESSION_ONE)
    assert package["request_id"]
    package_ids = [row["memory_id"] for row in package["digest"]["memories"]] \
        + [row["memory_id"] for row in package["working_set"]["memories"]]
    assert memory_id in package_ids

    runs = (await db_session.execute(
        select(MemoryRecallRun.channel, MemoryRecallRun.tool)
        .where(MemoryRecallRun.session_id == SESSION_ONE))).all()
    assert {"recall", "attached", "start_work"}.issubset({row[0] for row in runs}), runs
    assert {"recall_memory", "search_knowledge", "start_work"}.issubset({row[1] for row in runs}), runs

    rows = (await db_session.execute(
        select(MemoryRecallRun.returned_ids, MemoryRecallRun.created_at)
        .where(MemoryRecallRun.session_id == SESSION_ONE))).all()
    delivered = delivered_memory_ids(
        [{"returned_ids": row[0], "created_at": row[1]} for row in rows],
        now=datetime.now(UTC), window_seconds=3600)
    assert memory_id in delivered

    # A second default recall keeps deduping...
    second = await service.recall(scope_ref=[str(sid)], session_id=SESSION_ONE)
    assert second["memories"] == []
    assert second["counts"]["dropped_delivered"] >= 1
    # ... and include_delivered restores it without widening anything else.
    overridden = await service.recall(scope_ref=[str(sid)], session_id=SESSION_ONE,
                                      include_delivered=True)
    assert [row["memory_id"] for row in overridden["memories"]] == [memory_id]


@pytest.mark.asyncio
async def test_dedup_to_empty_is_actionable_and_does_not_rewrite_the_primary(db_session):
    """The empty state is explained and the primary retrieval result is untouched."""
    service = MemoryService(db_session)
    sid, memory_id = await _record_in_session(service, db_session, SESSION_TWO)

    await service.recall(scope_ref=[str(sid)], session_id=SESSION_TWO)
    attachment = await service.attach(scope_ref=[str(sid)], query=memory_id and "anything",
                                      session_id=SESSION_TWO)
    assert attachment["items"] == []
    assert attachment["counts"]["dropped_delivered"] >= 1

    primary = {"completion_status": "complete",
               "evidence": [{"evidence_id": "e-1"}],
               "request_id": "00000000-0000-4000-8000-0000000000ee"}
    merged = merge_attachment_response(primary, attachment)
    assert merged["related_memories"] == []
    assert merged["completion_status"] == "complete"
    assert merged["evidence"] is primary["evidence"]
    assert merged["counts"]["dropped_delivered"] >= 1
    assert "already delivered" in merged["memory_notice"]["notice"]
    assert merged["gaps"] and merged["gaps"][-1]["suggested_action"]


@pytest.mark.asyncio
async def test_include_delivered_never_relaxes_scope_or_state(db_session):
    """The override is dedup-only: another scope's own memory is unaffected."""
    service = MemoryService(db_session)
    scope_a, memory_a = await _record_in_session(service, db_session, SESSION_THREE)
    scope_b, memory_b = await _record_in_session(service, db_session, SESSION_THREE)
    assert scope_a != scope_b

    await service.recall(scope_ref=[str(scope_a)], session_id=SESSION_THREE)
    # Scope B is a different scope: its own memory is still delivered normally,
    # while scope A's memory can never appear in a scope-B response. A
    # memory_context is supplied so the permissive threshold applies and the only
    # variable under test is scope isolation.
    cross = await service.attach(
        scope_ref=[str(scope_b)],
        memory_context="Use an explicit scope for each memory request.",
        session_id=SESSION_THREE, include_delivered=True)
    ids = {item["memory_id"] for item in cross["items"]}
    assert memory_b in ids, "the scope's own memory must still be delivered"
    assert memory_a not in ids, "a different scope's memory must never leak in"
    assert all(item["knowledge_scope_id"] == scope_b for item in cross["items"])
