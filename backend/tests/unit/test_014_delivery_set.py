"""014 T027: the session-level delivered memory set (US3).

FR-016鈥R-019/SC-008: one session-level delivered set is shared by all three
channels (``recall`` / ``attached`` / ``start_work``); ``include_delivered=true``
relaxes **only** dedup; a short TTL expires old deliveries; multiple scopes take
the shortest window; and a dedup-to-empty result is an actionable empty state that
never rewrites the primary retrieval status.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from rag_mcp.mcp.search_knowledge import (
    DEDUPED_EMPTY_GAP,
    memory_notice,
    merge_attachment_response,
    notice_is_compliant,
)
from rag_mcp.services.memory_reader import (
    DEFAULT_DELIVERED_TTL_SECONDS,
    MemoryReader,
    delivered_cutoff,
    delivered_memory_ids,
    delivered_window_seconds,
)
from rag_mcp.services.memory_service import attachment_candidates
from rag_mcp.services.scope_resolver import MemoryScopeResolver

NOW = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
SESSION = "00000000-0000-4000-8000-0000000000aa"
MATCH = {"dense_similarity": 0.9, "recency_rank": 1, "kind_rank": 1, "salience": None,
         "fused_score": 0.02}


def _run(*, channel: str, tool: str, ids: list[int], age_seconds: float = 0.0) -> dict:
    return {
        "channel": channel,
        "tool": tool,
        "returned_ids": list(ids),
        "created_at": NOW - timedelta(seconds=age_seconds),
    }


def _row(memory_id: int, **overrides) -> dict:
    row = {
        "memory_id": memory_id, "knowledge_scope_id": 1, "kind": "episodic", "provenance": "soft",
        "confidence": 0.8, "title": None, "content_text": "memory body",
        "evidence_refs": [], "retention_stage": "active",
        "inference_meta": {"source": "s", "confidence": 0.8, "model_version": "none",
                           "time": "2026-10-09T00:00:00+00:00", "supporting_evidence": []},
        "valid_from": None, "valid_to": None, "observed_at": "2026-10-09T00:00:00+00:00",
        "session_id": "s-1", "agent_id": None, "status": "active", "superseded_by": None,
        "write_status": "complete", "expires_at": None, "injection_flags": {},
    }
    row.update(overrides)
    return row


# --- one set, three channels ---------------------------------------------------


def test_the_three_channels_share_one_delivered_set():
    runs = [
        _run(channel="recall", tool="recall_memory", ids=[11, 12]),
        _run(channel="attached", tool="search_knowledge", ids=[13]),
        _run(channel="start_work", tool="start_work", ids=[14, 11]),
    ]
    delivered = delivered_memory_ids(runs, now=NOW, window_seconds=DEFAULT_DELIVERED_TTL_SECONDS)
    assert delivered == {11, 12, 13, 14}
    assert all(isinstance(mid, int) for mid in delivered)


def test_the_delivered_query_is_channel_agnostic():
    """A run contributed by any channel counts; the filter must not name channels."""
    only_attached = [_run(channel="attached", tool="search_knowledge", ids=[21])]
    only_start_work = [_run(channel="start_work", tool="start_work", ids=[21])]
    assert delivered_memory_ids(only_attached, now=NOW,
                                window_seconds=3600) == {21}
    assert delivered_memory_ids(only_start_work, now=NOW,
                                window_seconds=3600) == {21}


def test_delivered_ids_are_a_deduplicated_union():
    runs = [_run(channel="recall", tool="recall_memory", ids=[1, 1, 2]),
            _run(channel="attached", tool="search_knowledge", ids=[2, 3])]
    assert delivered_memory_ids(runs, now=NOW, window_seconds=3600) == {1, 2, 3}


# --- short TTL -----------------------------------------------------------------


@pytest.mark.parametrize("age_seconds,inside", [(10, True), (3599, True), (3601, False), (86400, False)])
def test_short_ttl_window_decides_participation(age_seconds, inside):
    runs = [_run(channel="recall", tool="recall_memory", ids=[7], age_seconds=age_seconds)]
    delivered = delivered_memory_ids(runs, now=NOW, window_seconds=3600)
    assert (7 in delivered) is inside


def test_runs_without_a_usable_timestamp_do_not_participate():
    runs = [_run(channel="recall", tool="recall_memory", ids=[7]),
            {"returned_ids": [8], "created_at": "not-a-time"},
            {"returned_ids": [9], "created_at": None}]
    assert delivered_memory_ids(runs, now=NOW, window_seconds=3600) == {7}


def test_cutoff_is_derived_from_the_window_not_the_audit_retention():
    assert delivered_cutoff(NOW, 3600) == NOW - timedelta(seconds=3600)
    # 012 used the 7-day expires_at window; 014 replaces it with the short TTL.
    assert DEFAULT_DELIVERED_TTL_SECONDS == 3600


# --- multi-scope shortest window ----------------------------------------------


def test_multi_scope_requests_take_the_shortest_window():
    policies = [{"delivered_ttl_seconds": 3600}, {"delivered_ttl_seconds": 60}, {"delivered_ttl_seconds": 600}]
    assert delivered_window_seconds(policies) == 60


def test_shortest_window_is_conservative_for_an_empty_scope_list():
    assert delivered_window_seconds([]) == DEFAULT_DELIVERED_TTL_SECONDS


def test_shortest_window_uses_policy_defaults_for_absent_keys():
    assert delivered_window_seconds([{}, {"delivered_ttl_seconds": 60}]) == 60
    assert delivered_window_seconds([{}]) == DEFAULT_DELIVERED_TTL_SECONDS


def test_an_invalid_policy_window_is_rejected_not_defaulted():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        delivered_window_seconds([{"delivered_ttl_seconds": 5}])


# --- include_delivered relaxes only dedup -------------------------------------


def test_include_delivered_restores_only_previously_delivered_items():
    rows = {index: _row(index) for index in (1, 2, 3)}
    matches = {index: dict(MATCH) for index in (1, 2, 3)}
    default = attachment_candidates(rows, matches=matches, policy={}, has_context=True,
                                    session_id="s-1", now=NOW, delivered={1, 2})
    assert [item["memory_id"] for item in default["items"]] == [3]
    assert default["counts"]["dropped_delivered"] == 2

    overridden = attachment_candidates(rows, matches=matches, policy={}, has_context=True,
                                       session_id="s-1", now=NOW, delivered={1, 2},
                                       include_delivered=True)
    assert [item["memory_id"] for item in overridden["items"]] == [1, 2, 3]
    assert overridden["counts"]["dropped_delivered"] == 0


def test_include_delivered_does_not_relax_status_scope_expiry_or_threshold():
    rows = {
        1: _row(1),                                             # previously delivered
        2: _row(2, status="quarantined"),                       # state filtered
        3: _row(3, expires_at="2026-10-01T00:00:00+00:00"),     # expired
        4: _row(4),                                             # below the conservative threshold
    }
    matches = {1: dict(MATCH), 2: dict(MATCH), 3: dict(MATCH),
               4: {**MATCH, "dense_similarity": 0.2}}
    result = attachment_candidates(rows, matches=matches, policy={}, has_context=False,
                                   session_id="s-1", now=NOW, delivered={1},
                                   include_delivered=True)
    assert [item["memory_id"] for item in result["items"]] == [1]
    assert result["counts"]["filtered_inactive"] == 2
    # Exact semantics: the pool had two visible candidates, one of which was
    # below the conservative threshold and was simply not selected — the
    # explicit include_delivered override means nothing was degraded.
    assert result["failed_paths"] == []
    assert result["counts"]["candidates"] == 2
    assert result["counts"]["dropped_delivered"] == 0


def test_include_delivered_is_a_single_request_override():
    """The override must not leak: a second default call still dedupes."""
    rows = {1: _row(1)}
    matches = {1: dict(MATCH)}
    attachment_candidates(rows, matches=matches, policy={}, has_context=True, session_id="s-1",
                          now=NOW, delivered={1}, include_delivered=True)
    default = attachment_candidates(rows, matches=matches, policy={}, has_context=True,
                                    session_id="s-1", now=NOW, delivered={1})
    assert default["items"] == []


# --- dedup-to-empty empty state ----------------------------------------------


def test_dedup_to_empty_is_an_actionable_empty_state():
    primary = {"completion_status": "complete", "evidence": [{"evidence_id": "e-1"}], "request_id": "r"}
    merged = merge_attachment_response(primary, {
        "items": [],
        "counts": {"returned": 0, "candidates": 3, "truncated_by_budget": 0,
                   "dropped_delivered": 3, "filtered_inactive": 0, "characters": 0},
        "failed_paths": [],
    })
    assert merged["related_memories"] == []
    # memory_notice carries the explanation as well as the two mandatory elements
    assert notice_is_compliant(merged["memory_notice"]["notice"])
    assert "already delivered" in merged["memory_notice"]["notice"]
    # gaps carries an actionable suggested_action
    assert merged["gaps"] == [DEDUPED_EMPTY_GAP]
    assert merged["gaps"][0]["suggested_action"]


def test_dedup_to_empty_never_rewrites_the_primary_result():
    evidence = [{"evidence_id": "e-1"}, {"evidence_id": "e-2"}]
    primary = {"completion_status": "partial", "evidence": evidence, "request_id": "r",
               "gaps": [{"description": "original gap"}]}
    merged = merge_attachment_response(primary, {
        "items": [], "counts": {"dropped_delivered": 2}, "failed_paths": [],
    })
    assert merged["completion_status"] == "partial", "must not become no_evidence"
    assert merged["evidence"] is evidence
    assert merged["request_id"] == "r"
    # the memory-layer gap is appended, the primary gap is preserved
    assert merged["gaps"][0] == {"description": "original gap"}
    assert merged["gaps"][-1] == DEDUPED_EMPTY_GAP


def test_an_empty_result_without_dedup_does_not_claim_already_delivered():
    primary = {"completion_status": "complete", "evidence": [], "request_id": "r"}
    merged = merge_attachment_response(primary, {
        "items": [], "counts": {"dropped_delivered": 0}, "failed_paths": ["below_min_score"],
    })
    assert "gaps" not in merged or DEDUPED_EMPTY_GAP not in merged["gaps"]
    assert "already delivered" not in merged["memory_notice"]["notice"]


def test_notice_with_deduped_empty_still_carries_both_required_elements():
    notice = memory_notice([], deduped_empty=True)
    assert notice_is_compliant(notice["notice"])
    assert notice["untrusted"] is True
    assert "already delivered" in notice["notice"]


# --- start_work writes the delivered channel ---------------------------------


@pytest.mark.asyncio
async def test_start_work_records_the_returned_ids_under_its_own_channel(monkeypatch):
    audits: list = []

    class Session:
        async def get(self, model, key):
            from rag_mcp.models.domain_profile import DomainProfile
            from rag_mcp.models.knowledge_scope import KnowledgeScope

            if model is KnowledgeScope:
                return SimpleNamespace(slug="scope", domain_key="generic")
            if model is DomainProfile:
                return SimpleNamespace(description="", memory_policy={})
            raise AssertionError(model)

        async def commit(self):
            return None

        def add(self, row):
            audits.append(row)

    async def resolve(self, reference):
        return 7

    row = _row(41, kind="semantic", content_text="a semantic fact")

    async def views(self, *args, **kwargs):
        return {41: row}, {}, [], []

    monkeypatch.setattr(MemoryScopeResolver, "resolve", resolve)
    monkeypatch.setattr(MemoryReader, "_views", views)

    result = await MemoryReader(Session(), None).start_work(scope_ref="7", session_id=SESSION)

    assert audits, "start_work must record a delivered-channel audit row"
    audit = audits[-1]
    assert audit.tool == "start_work"
    assert audit.channel == "start_work"
    assert audit.session_id == SESSION
    assert 41 in list(audit.returned_ids)
    # the package body itself is unchanged by the audit write
    assert list(result)[:4] == ["scope", "domain_brief", "digest", "working_set"]


@pytest.mark.asyncio
async def test_recall_records_the_recall_channel(monkeypatch):
    audits: list = []

    class Session:
        def __init__(self):
            self.rows = []

        async def execute(self, *args, **kwargs):
            return SimpleNamespace(all=lambda: [], scalars=lambda: SimpleNamespace(all=lambda: []))

        async def commit(self):
            return None

        async def rollback(self):
            return None

        def add(self, row):
            audits.append(row)

    async def resolve_many(self, reference):
        return [7]

    async def views(self, *args, **kwargs):
        return {}, {}, [], []

    monkeypatch.setattr(MemoryScopeResolver, "resolve_many", resolve_many)
    monkeypatch.setattr(MemoryReader, "_views", views)

    await MemoryReader(Session(), None).recall(scope_ref=["7"])

    assert audits and audits[-1].tool == "recall_memory" and audits[-1].channel == "recall"


def test_recall_defaults_keep_the_historical_audit_values():
    import inspect

    signature = inspect.signature(MemoryReader.recall)
    assert signature.parameters["tool"].default == "recall_memory"
    assert signature.parameters["channel"].default == "recall"


# --- T091: accurate degradation reasons and counts -----------------------------


def test_dedup_to_empty_is_not_claimed_when_another_reason_exists():
    """T091: dedup is only the *explanation* when nothing else degraded."""
    primary = {"completion_status": "complete", "evidence": [], "request_id": "r"}
    merged = merge_attachment_response(primary, {
        "items": [], "counts": {"dropped_delivered": 3}, "failed_paths": ["below_min_score"],
    })
    assert DEDUPED_EMPTY_GAP not in merged.get("gaps", [])
    assert "already delivered" not in merged["memory_notice"]["notice"]


def test_state_filtered_and_unscored_candidates_are_reported_accurately():
    """T091/FR-014: reasons match the real cause and the candidate pool is counted."""
    filtered = attachment_candidates(
        {1: _row(1, status="quarantined")}, matches={1: dict(MATCH)}, policy={},
        has_context=True, session_id=None, now=NOW)
    assert filtered["failed_paths"] == ["state_filtered"]
    assert filtered["counts"]["filtered_inactive"] == 1

    unscored = attachment_candidates(
        {1: _row(1)}, matches={}, policy={}, has_context=True, session_id=None, now=NOW)
    assert unscored["failed_paths"] == ["memory_unavailable"]
    assert unscored["counts"]["candidates"] == 1, "a visible but unscored row is still a candidate"


def test_a_whole_pool_cropped_by_the_budget_reports_budget_exhausted():
    """T091: a budget-caused empty result is never silent."""
    result = attachment_candidates(
        {1: _row(1, content_text="x" * 500)}, matches={1: dict(MATCH)},
        policy={"attach_excerpt_chars": 200, "attach_max_chars": 200},
        has_context=True, session_id=None, now=NOW)
    assert result["items"] == []
    assert result["failed_paths"] == ["budget_exhausted"]
    assert result["counts"]["truncated_by_budget"] >= 1
