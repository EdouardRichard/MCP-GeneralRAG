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

import pytest
from sqlalchemy import select

from rag_mcp.models.memory_recall_run import MemoryRecallRun
from rag_mcp.mcp.search_knowledge import merge_attachment_response
from rag_mcp.services.memory_reader import delivered_memory_ids
from rag_mcp.services.memory_service import MemoryService

from tests.integration.test_012_live_reader import scope_and_payload

SESSION_ONE = "00000000-0000-4000-8000-0000000000bb"
SESSION_TWO = "00000000-0000-4000-8000-0000000000cc"
SESSION_THREE = "00000000-0000-4000-8000-0000000000dd"


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
