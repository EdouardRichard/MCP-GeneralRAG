"""014 attachment-layer tests (T008 error registry, extended by T013/T022).

This file is the 014 home for the attachment layer: the error-code freeze
(T008), the signal/threshold/budget/degradation matrix (T013) and the notice
contract (T022).
"""

from __future__ import annotations

import pytest

from rag_mcp.errors import (
    ATTACHMENT_DEGRADATION_REASONS,
    ERROR_CODES,
    LEGACY_ERROR_CODES,
    MEMORY_ERROR_CODES,
    attachment_degradation_reason,
)

# Frozen registry as measured at the 014 baseline. 014 is add-only: a removal or
# a rename here is a client-visible break, so it must never be "fixed" by editing
# this literal.
FROZEN_LEGACY_ERROR_CODES = frozenset({
    "SYSTEM_ERROR", "MISSING_PROJECT_SCOPE", "AMBIGUOUS_PROJECT_REF",
    "INVALID_PROJECT_REF", "INDEX_UNAVAILABLE", "MISSING_KNOWLEDGE_SCOPE",
    "AMBIGUOUS_DOMAIN_REF", "INVALID_INPUT", "INVALID_EVIDENCE_ID",
})
FROZEN_MEMORY_ERROR_CODES = frozenset({
    "MISSING_KNOWLEDGE_SCOPE", "AMBIGUOUS_DOMAIN_REF",
    "MEMORY_EVIDENCE_ANCHOR_REQUIRED", "MEMORY_EVIDENCE_SCOPE_MISMATCH",
    "MEMORY_INFERENCE_META_INCOMPLETE", "MEMORY_PROVENANCE_INVALID",
    "MEMORY_KIND_INVALID", "MEMORY_SUPERSEDE_TARGET_INVALID",
    "MEMORY_QUOTA_EXCEEDED", "MEMORY_WRITE_UNAVAILABLE",
    "MEMORY_IDS_QUERY_CONFLICT", "MEMORY_ROLLBACK_FORBIDDEN",
    "MEMORY_TIMEOUT", "MEMORY_CONTENT_CONFLICT", "SYSTEM_ERROR",
})


def test_legacy_error_codes_unchanged():
    assert LEGACY_ERROR_CODES == FROZEN_LEGACY_ERROR_CODES


def test_memory_error_codes_unchanged():
    assert MEMORY_ERROR_CODES == FROZEN_MEMORY_ERROR_CODES


def test_combined_error_code_set_unchanged():
    assert ERROR_CODES == FROZEN_LEGACY_ERROR_CODES | FROZEN_MEMORY_ERROR_CODES
    # 014 adds no error code: degradation is reported as a reason, not a new code.
    assert ERROR_CODES == LEGACY_ERROR_CODES | MEMORY_ERROR_CODES


def test_degradation_reasons_are_a_separate_vocabulary():
    assert ATTACHMENT_DEGRADATION_REASONS, "the degradation vocabulary must not be empty"
    # A reason is never an error code and vice versa: the two vocabularies must
    # not be conflated in the response.
    assert not (ATTACHMENT_DEGRADATION_REASONS & ERROR_CODES)
    assert all(reason.islower() for reason in ATTACHMENT_DEGRADATION_REASONS)
    assert all(reason.replace("_", "").isalnum() for reason in ATTACHMENT_DEGRADATION_REASONS)


@pytest.mark.parametrize(
    "exception,reason",
    [
        (TimeoutError(), "attachment_timeout"),
        (ConnectionError("qdrant down"), "memory_unavailable"),
        (ValueError("MEMORY_PROVENANCE_INVALID: x"), "memory_unavailable"),
    ],
)
def test_degradation_reason_mapping_is_stable(exception, reason):
    assert attachment_degradation_reason(exception) == reason
    assert reason in ATTACHMENT_DEGRADATION_REASONS


# =============================================================================
# T013: signal gating, dual thresholds, budget boundaries, independent
# degradation, detection-first ordering and concurrency.
# =============================================================================

from datetime import UTC, datetime  # noqa: E402

import asyncio  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from uuid import UUID  # noqa: E402

from rag_mcp.mcp.search_knowledge import attachment_triggered  # noqa: E402
from rag_mcp.services.memory_service import (  # noqa: E402
    ATTACH_CHARACTERS_HARD_LIMIT,
    ATTACH_EXCERPT_HARD_LIMIT,
    ATTACH_ITEMS_HARD_LIMIT,
    MemoryService,
    attachment_budget,
    attachment_candidates,
    attachment_hard_anchor_ok,
    attachment_min_score,
    attachment_visible,
    detect_context_flags,
)

NOW = datetime(2026, 10, 9, tzinfo=UTC)
MATCH = {"dense_similarity": 0.7, "recency_rank": 1, "kind_rank": 1, "salience": None, "fused_score": 0.01}


def _row(**overrides) -> dict:
    row = {
        "memory_id": 1, "knowledge_scope_id": 1, "kind": "episodic", "provenance": "soft",
        "confidence": 0.8, "title": None, "content_text": "memory body",
        "evidence_refs": [], "retention_stage": "active",
        "inference_meta": {"source": "s", "confidence": 0.8, "model_version": "none",
                           "time": "2026-10-09T00:00:00+00:00", "supporting_evidence": []},
        "valid_from": None, "valid_to": None, "observed_at": "2026-10-09T00:00:00+00:00",
        "session_id": None, "agent_id": None, "status": "active", "superseded_by": None,
        "write_status": "complete", "expires_at": None, "injection_flags": {},
    }
    row.update(overrides)
    return row


# --- signal gating ------------------------------------------------------------


@pytest.mark.parametrize(
    "enabled,session_id,memory_context,expected",
    [
        (False, None, None, False),
        (False, "s", None, False),
        (False, None, "ctx", False),
        (True, None, None, False),
        (True, "s", None, True),
        (True, None, "ctx", True),
        (True, "s", "ctx", True),
    ],
)
def test_signal_gating_matrix(enabled, session_id, memory_context, expected):
    assert attachment_triggered(session_id=session_id, memory_context=memory_context, enabled=enabled) is expected


def test_gate_never_coerces_a_falsy_but_present_signal():
    # An empty string is still an explicit value at the gate; the *parameter*
    # layer rejects it first (see test_014_search_bytes_frozen.py), so the gate
    # must not silently turn it into "not triggered".
    assert attachment_triggered(session_id=None, memory_context="", enabled=True) is True


# --- dual threshold track -----------------------------------------------------


def test_threshold_dual_track_uses_policy_defaults():
    assert attachment_min_score({}, has_context=True) == 0.0
    assert attachment_min_score({}, has_context=False) == 0.5


def test_threshold_dual_track_honours_the_domain_policy():
    policy = {"attach_min_score": 0.2, "attach_conservative_min_score": 0.6}
    assert attachment_min_score(policy, has_context=True) == 0.2
    assert attachment_min_score(policy, has_context=False) == 0.6


def test_threshold_rejects_a_conservative_value_below_the_permissive_one():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        attachment_min_score({"attach_min_score": 0.5, "attach_conservative_min_score": 0.4},
                             has_context=False)


# --- visibility / state re-verification ---------------------------------------


@pytest.mark.parametrize("status", ["quarantined", "superseded", "retired"])
def test_non_active_status_is_not_visible(status):
    assert attachment_visible(_row(status=status), now=NOW) is False


@pytest.mark.parametrize("stage", ["compressed", "archived"])
def test_non_active_retention_stage_is_not_visible(stage):
    assert attachment_visible(_row(retention_stage=stage), now=NOW) is False


def test_closed_and_expired_and_unfinished_rows_are_not_visible():
    assert attachment_visible(_row(valid_to="2026-10-01T00:00:00+00:00"), now=NOW) is False
    assert attachment_visible(_row(expires_at="2026-10-01T00:00:00+00:00"), now=NOW) is False
    assert attachment_visible(_row(write_status="pending"), now=NOW) is False


def test_a_future_expiry_is_visible_and_open_ended_rows_are_visible():
    assert attachment_visible(_row(expires_at="2026-11-01T00:00:00+00:00"), now=NOW) is True
    assert attachment_visible(_row(expires_at=None), now=NOW) is True


def test_an_unparsable_timestamp_is_treated_as_not_a_candidate():
    # A6: a malformed/naive timestamp must exclude the row, never raise.
    assert attachment_visible(_row(observed_at="not-a-time"), now=NOW) is False
    assert attachment_visible(_row(observed_at="2026-10-09T00:00:00"), now=NOW) is False


# --- hard provenance anchor ---------------------------------------------------


def test_hard_items_need_an_attribution_anchor():
    assert attachment_hard_anchor_ok(_row(provenance="hard", evidence_refs=["e-1"])) is True
    assert attachment_hard_anchor_ok(_row(provenance="hard", evidence_refs=[])) is False
    assert attachment_hard_anchor_ok(_row(provenance="soft", evidence_refs=[])) is True
    assert attachment_hard_anchor_ok(_row(provenance="distilled", evidence_refs=[])) is True


# --- threshold + budget boundaries -------------------------------------------


def _candidates(count: int, *, score: float = 0.9):
    rows = {index: _row(memory_id=index, content_text=f"body-{index}") for index in range(1, count + 1)}
    matches = {index: {**MATCH, "dense_similarity": score} for index in range(1, count + 1)}
    return rows, matches


def test_top_k_is_capped_by_the_policy_and_the_frozen_hard_limit():
    rows, matches = _candidates(10)
    result = attachment_candidates(rows, matches=matches, policy={}, has_context=True,
                                   session_id=None, now=NOW)
    assert len(result["items"]) == 3, "policy default attach_top_k is 3"

    result5 = attachment_candidates(rows, matches=matches, policy={"attach_top_k": 5}, has_context=True,
                                    session_id=None, now=NOW)
    assert len(result5["items"]) == 5

    # even a policy asking for more cannot exceed the frozen protocol limit
    assert attachment_budget({"attach_top_k": 5})["top_k"] == ATTACH_ITEMS_HARD_LIMIT


def test_below_threshold_candidates_are_dropped_and_counted():
    low_rows = {index: _row(memory_id=index) for index in range(1, 4)}
    low_matches = {index: {**MATCH, "dense_similarity": 0.1} for index in range(1, 4)}
    result = attachment_candidates(low_rows, matches=low_matches, policy={}, has_context=False,
                                   session_id="s", now=NOW)
    assert result["items"] == []
    assert "below_min_score" in result["failed_paths"]
    assert result["counts"]["returned"] == 0


def test_with_context_uses_the_permissive_threshold():
    rows = {1: _row(memory_id=1)}
    matches = {1: {**MATCH, "dense_similarity": 0.3}}
    assert attachment_candidates(rows, matches=matches, policy={}, has_context=True,
                                 session_id=None, now=NOW)["items"], "0.3 >= attach_min_score 0.0"
    assert attachment_candidates(rows, matches=matches, policy={}, has_context=False,
                                 session_id="s", now=NOW)["items"] == [], "0.3 < 0.5 conservative"


def test_character_budget_is_respected_by_cropping_tail_items():
    rows = {index: _row(memory_id=index, content_text="x" * 190) for index in range(1, 6)}
    matches = {index: {**MATCH, "dense_similarity": 0.9} for index in range(1, 6)}
    result = attachment_candidates(rows, matches=matches, policy={"attach_top_k": 5}, has_context=True,
                                   session_id=None, now=NOW)
    assert result["counts"]["characters"] <= ATTACH_CHARACTERS_HARD_LIMIT
    assert result["counts"]["truncated_by_budget"] >= 1
    assert len(result["items"]) < 5


def test_excerpt_is_capped_at_200_and_marks_truncation():
    rows = {1: _row(memory_id=1, content_text="y" * 500)}
    matches = {1: {**MATCH, "dense_similarity": 0.9}}
    item = attachment_candidates(rows, matches=matches, policy={}, has_context=True, session_id=None,
                                 now=NOW)["items"][0]
    assert len(item["content_excerpt"]) == ATTACH_EXCERPT_HARD_LIMIT
    assert item["truncated"] is True
    assert item["content_length"] == 500


def test_excluded_states_never_appear_in_the_output():
    rows = {
        1: _row(memory_id=1, status="quarantined"),
        2: _row(memory_id=2, retention_stage="archived"),
        3: _row(memory_id=3, valid_to="2026-10-01T00:00:00+00:00"),
        4: _row(memory_id=4, expires_at="2026-10-01T00:00:00+00:00"),
        5: _row(memory_id=5, write_status="pending"),
        6: _row(memory_id=6),
    }
    matches = {index: {**MATCH, "dense_similarity": 0.9} for index in range(1, 7)}
    result = attachment_candidates(rows, matches=matches, policy={}, has_context=True, session_id=None, now=NOW)
    assert [item["memory_id"] for item in result["items"]] == [6]
    assert result["counts"]["filtered_inactive"] == 5


def test_hard_item_without_an_anchor_is_excluded():
    rows = {1: _row(memory_id=1, provenance="hard", confidence=None, evidence_refs=[]) ,
            2: _row(memory_id=2, provenance="hard", confidence=None, evidence_refs=["e-1"])}
    matches = {index: {**MATCH, "dense_similarity": 0.9} for index in range(1, 3)}
    result = attachment_candidates(rows, matches=matches, policy={}, has_context=True, session_id=None, now=NOW)
    assert [item["memory_id"] for item in result["items"]] == [2]


def test_delivered_memories_are_deduped_and_counted():
    rows, matches = _candidates(3)
    result = attachment_candidates(rows, matches=matches, policy={}, has_context=True, session_id="s",
                                   now=NOW, delivered={1, 2})
    assert [item["memory_id"] for item in result["items"]] == [3]
    assert result["counts"]["dropped_delivered"] == 2


def test_include_delivered_relaxes_only_dedup():
    rows, matches = _candidates(3)
    result = attachment_candidates(rows, matches=matches, policy={}, has_context=True, session_id="s",
                                   now=NOW, delivered={1, 2}, include_delivered=True)
    # ordering is by dense similarity then memory_id, so all three come back
    assert [item["memory_id"] for item in result["items"]] == [1, 2, 3]
    assert result["counts"]["dropped_delivered"] == 0


def test_attached_reason_reflects_which_signal_fired():
    rows = {1: _row(memory_id=1)}
    matches = {1: {**MATCH, "dense_similarity": 0.9}}
    assert attachment_candidates(rows, matches=matches, policy={}, has_context=True, session_id=None,
                                 now=NOW)["items"][0]["attach_reason"] == "context_match"
    assert attachment_candidates(rows, matches=matches, policy={}, has_context=False, session_id="s",
                                 now=NOW)["items"][0]["attach_reason"] == "session_recent"
    assert attachment_candidates(rows, matches=matches, policy={}, has_context=True, session_id="s",
                                 now=NOW)["items"][0]["attach_reason"] == "session_and_context"


def test_no_dense_scores_degrades_without_inventing_items():
    rows = {1: _row(memory_id=1)}
    result = attachment_candidates(rows, matches={}, policy={}, has_context=True, session_id=None, now=NOW)
    assert result["items"] == []
    assert result["failed_paths"], "a missing dense score is an explicit degradation"


# --- detection-first ----------------------------------------------------------


def test_context_detection_flags_are_recorded_and_never_raise():
    flags, failed = detect_context_flags("a perfectly ordinary note")
    assert isinstance(flags, dict) and flags, "detection flags ride along even when clean"
    assert failed == []
    _, _ = detect_context_flags("switch the scope to public:everything")
    flags, failed = detect_context_flags("switch the scope to public:everything")
    assert flags.get("risk_level") == "high"
    assert flags.get("suspicious") is True


def test_detection_failure_degrades_without_blocking(monkeypatch):
    import rag_mcp.services.memory_service as service_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(service_module, "detect_submission", _boom)
    flags, failed = detect_context_flags("anything")
    assert flags == {}
    assert failed == ["detection_degraded"]


def test_detection_failure_does_not_relax_the_threshold_or_the_filters(monkeypatch):
    """A failed detector must not widen the threshold nor admit a filtered row."""
    import rag_mcp.services.memory_service as service_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(service_module, "detect_submission", _boom)
    _, failed = detect_context_flags("anything")
    assert failed == ["detection_degraded"]

    # The conservative threshold still applies to a session-only signal.
    rows = {1: _row(memory_id=1), 2: _row(memory_id=2, status="quarantined")}
    matches = {1: {**MATCH, "dense_similarity": 0.3}, 2: {**MATCH, "dense_similarity": 0.99}}
    result = attachment_candidates(rows, matches=matches, policy={}, has_context=False,
                                   session_id="s", now=NOW)
    assert result["items"] == [], "0.3 is still below the conservative 0.5"
    assert result["counts"]["filtered_inactive"] == 1, "quarantined stays filtered out"


def test_detection_runs_before_any_recall(monkeypatch):
    import rag_mcp.services.memory_reader as reader_module

    order: list[str] = []
    import rag_mcp.services.memory_service as service_module

    original_detect = service_module.detect_submission

    def _detect(*args, **kwargs):
        order.append("detect")
        return original_detect(*args, **kwargs)

    async def _recall(self, **_kwargs):
        order.append("recall")
        return {"completion_status": "no_evidence", "memories": [], "counts": {"returned": 0},
                "request_id": "r", "gaps": []}

    monkeypatch.setattr(service_module, "detect_submission", _detect)
    monkeypatch.setattr(reader_module.MemoryReader, "recall", _recall)
    service = MemoryService(_FakeSession(), embedding_provider=None, qdrant_store=None)
    service.projections.qdrant = None
    asyncio.run(_attach(service, memory_context="ctx", session_id=None))
    assert order and order[0] == "detect", f"detection must be first, got {order}"


# --- independent degradation / timeout ---------------------------------------


class _FakeSession:
    async def execute(self, *_args, **_kwargs):
        return None

    async def get(self, *_args, **_kwargs):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None


async def _attach(service, **kwargs):
    kwargs.setdefault("policy", {})
    return await service.attach(scope_ref="1", query="q", **kwargs)


def test_attachment_timeout_degrades_independently(monkeypatch):
    import rag_mcp.services.memory_reader as reader_module

    async def _slow(self, **_kwargs):
        await asyncio.sleep(5)
        raise AssertionError("the timeout must fire first")

    monkeypatch.setattr(reader_module.MemoryReader, "recall", _slow)
    service = MemoryService(_FakeSession(), embedding_provider=None, qdrant_store=None)
    service.projections.qdrant = None
    result = asyncio.run(_attach(service, memory_context="ctx", session_id=None,
                                 policy={"attach_timeout_ms": 50}))
    assert result["items"] == []
    assert "attachment_timeout" in result["failed_paths"]


def test_attachment_failure_degrades_independently(monkeypatch):
    import rag_mcp.services.memory_reader as reader_module

    async def _broken(self, **_kwargs):
        raise ConnectionError("qdrant down")

    monkeypatch.setattr(reader_module.MemoryReader, "recall", _broken)
    service = MemoryService(_FakeSession(), embedding_provider=None, qdrant_store=None)
    service.projections.qdrant = None
    result = asyncio.run(_attach(service, memory_context="ctx", session_id=None))
    assert result["items"] == []
    assert "memory_unavailable" in result["failed_paths"]


def test_attach_never_raises_on_a_degraded_path(monkeypatch):
    import rag_mcp.services.memory_reader as reader_module

    async def _broken(self, **_kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(reader_module.MemoryReader, "recall", _broken)
    service = MemoryService(_FakeSession(), embedding_provider=None, qdrant_store=None)
    service.projections.qdrant = None
    result = asyncio.run(_attach(service, memory_context="ctx", session_id=None))
    assert set(result) >= {"items", "counts", "failed_paths"}
    assert result["failed_paths"]


# --- orchestration: main failed, concurrency, no leftover tasks ---------------


def _install_core_fakes(monkeypatch, *, main_result, main_delay=0.0, attach_spy=None, attach_result=None):
    import rag_mcp.mcp.search_knowledge as search_module

    class _FakeRetrievalService:
        def __init__(self, **_kwargs):
            pass

        async def search(self, **_kwargs):
            if main_delay:
                await asyncio.sleep(main_delay)
            return main_result

    class _FakeMemoryService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def attach(self, **kwargs):
            if attach_spy is not None:
                attach_spy.append(("attach_start", asyncio.get_running_loop().time(), kwargs))
            if attach_result is not None:
                return attach_result
            return {"items": [], "counts": {"returned": 0, "candidates": 0, "truncated_by_budget": 0,
                                            "dropped_delivered": 0, "filtered_inactive": 0, "characters": 0},
                    "failed_paths": ["below_min_score"]}

    monkeypatch.setattr(search_module, "RetrievalService", _FakeRetrievalService)
    monkeypatch.setattr(search_module, "MemoryService", _FakeMemoryService)


@asynccontextmanager
async def _session_factory():
    yield _FakeSession()


def _core_kwargs():
    from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider

    return {
        "query": "q", "project_scope": ["p"], "top_k": 5, "task_context": None,
        "session_factory": _session_factory, "qdrant_store": _OfflineQdrant(),
        "embedding_provider": LocalCPUEmbeddingProvider(),
    }


class _OfflineQdrant:
    _client = None


def test_main_search_failure_attaches_nothing(monkeypatch):
    """Q10 keeps the attachment concurrent, so this is about *merging*, not starting."""
    import rag_mcp.mcp.search_knowledge as search_module

    monkeypatch.setenv("MEMORY_AWARE_RETRIEVAL_ENABLED", "true")
    failed = {"completion_status": "failed", "evidence": [],
              "error": {"code": "SYSTEM_ERROR", "message": "boom"}, "request_id": "r"}
    attachment = {"items": [{"memory_id": 1}], "counts": {"returned": 1, "candidates": 1,
                                                        "truncated_by_budget": 0, "dropped_delivered": 0,
                                                        "filtered_inactive": 0, "characters": 10},
                  "failed_paths": []}
    _install_core_fakes(monkeypatch, main_result=failed, attach_result=attachment)

    async def _run():
        return await search_module.search_knowledge_core(**_core_kwargs(), memory_context="ctx")

    result = asyncio.run(_run())
    assert list(result) == ["completion_status", "evidence", "error", "request_id"]
    assert "related_memories" not in result, "a failed primary search must not attach memories"
    assert "memory_notice" not in result
    assert "counts" not in result


def test_attachment_is_skipped_when_the_switch_is_off(monkeypatch):
    import rag_mcp.mcp.search_knowledge as search_module

    monkeypatch.setenv("MEMORY_AWARE_RETRIEVAL_ENABLED", "false")
    spy: list = []
    ok = {"completion_status": "complete", "evidence": [], "request_id": "r"}
    _install_core_fakes(monkeypatch, main_result=ok, attach_spy=spy)

    async def _run():
        return await search_module.search_knowledge_core(**_core_kwargs(), memory_context="ctx")

    result = asyncio.run(_run())
    assert list(result) == ["completion_status", "evidence", "request_id"]
    assert spy == []


def test_attachment_and_main_search_start_concurrently(monkeypatch):
    """Q10: serial execution is not an acceptable implementation."""
    import rag_mcp.mcp.search_knowledge as search_module

    monkeypatch.setenv("MEMORY_AWARE_RETRIEVAL_ENABLED", "true")
    spy: list = []
    main_started = None

    class _FakeRetrievalService:
        def __init__(self, **_kwargs):
            pass

        async def search(self, **_kwargs):
            nonlocal main_started
            main_started = asyncio.get_running_loop().time()
            await asyncio.sleep(0.15)
            return {"completion_status": "complete", "evidence": [], "request_id": "r"}

    class _FakeMemoryService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def attach(self, **kwargs):
            spy.append(("attach_start", asyncio.get_running_loop().time(), kwargs))
            return {"items": [], "counts": {"returned": 0}, "failed_paths": []}

    monkeypatch.setattr(search_module, "RetrievalService", _FakeRetrievalService)
    monkeypatch.setattr(search_module, "MemoryService", _FakeMemoryService)

    async def _run():
        started = asyncio.get_running_loop().time()
        result = await search_module.search_knowledge_core(**_core_kwargs(), session_id=_UUID)
        return result, asyncio.get_running_loop().time() - started

    result, elapsed = asyncio.run(_run())
    assert spy and spy[0][0] == "attach_start"
    assert main_started is not None
    # The attachment must have started before the primary retrieval finished;
    # a serial implementation would start it only after ~0.15s.
    assert spy[0][1] - main_started < 0.10, (
        f"the attachment started {spy[0][1] - main_started:.3f}s after the main search began"
    )
    assert elapsed < 0.30, "end-to-end must stay near max(main, attachment), not their sum"
    assert "related_memories" in result


def test_no_task_is_left_pending_after_the_response(monkeypatch):
    import rag_mcp.mcp.search_knowledge as search_module

    monkeypatch.setenv("MEMORY_AWARE_RETRIEVAL_ENABLED", "true")
    ok = {"completion_status": "complete", "evidence": [], "request_id": "r"}
    _install_core_fakes(monkeypatch, main_result=ok, main_delay=0.05)

    async def _run():
        result = await search_module.search_knowledge_core(**_core_kwargs(), session_id=_UUID)
        await asyncio.sleep(0)
        pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        return result, pending

    result, pending = asyncio.run(_run())
    assert pending == [], f"leftover tasks after the response: {pending}"


from uuid import UUID  # noqa: E402

_UUID = str(UUID("00000000-0000-4000-8000-000000000001"))


def test_failed_main_search_cancels_a_running_attachment(monkeypatch):
    import rag_mcp.mcp.search_knowledge as search_module

    monkeypatch.setenv("MEMORY_AWARE_RETRIEVAL_ENABLED", "true")
    state = {"started": False, "cancelled": False}

    class _FakeRetrievalService:
        def __init__(self, **_kwargs):
            pass

        async def search(self, **_kwargs):
            # Wait until the attachment is provably running, then report failure.
            await attach_started.wait()
            return {"completion_status": "failed", "evidence": [],
                    "error": {"code": "SYSTEM_ERROR", "message": "boom"}, "request_id": "r"}

    class _FakeMemoryService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def attach(self, **_kwargs):
            state["started"] = True
            attach_started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise
            return {"items": [], "counts": {}, "failed_paths": []}

    monkeypatch.setattr(search_module, "RetrievalService", _FakeRetrievalService)
    monkeypatch.setattr(search_module, "MemoryService", _FakeMemoryService)

    attach_started = asyncio.Event()

    async def _run():
        result = await search_module.search_knowledge_core(**_core_kwargs(), memory_context="ctx")
        await asyncio.sleep(0)
        remaining = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        return result, remaining

    result, remaining = asyncio.run(_run())
    assert list(result) == ["completion_status", "evidence", "error", "request_id"]
    assert state["started"] is True, "the attachment must actually have been running"
    assert state["cancelled"] is True, "the attachment task must be cancelled and recycled"
    assert remaining == []


def test_degraded_attachment_never_changes_the_primary_result(monkeypatch):
    import rag_mcp.mcp.search_knowledge as search_module

    monkeypatch.setenv("MEMORY_AWARE_RETRIEVAL_ENABLED", "true")
    main = {"completion_status": "partial", "evidence": [{"evidence_id": "e-1"}], "request_id": "r",
            "gaps": [{"description": "insufficient evidence"}]}
    _install_core_fakes(monkeypatch, main_result=main,
                        attach_result={"items": [], "counts": {"returned": 0},
                                       "failed_paths": ["attachment_timeout"]})

    async def _run():
        return await search_module.search_knowledge_core(**_core_kwargs(), memory_context="ctx")

    result = asyncio.run(_run())
    assert result["completion_status"] == "partial"
    assert result["evidence"] == main["evidence"]
    assert result["gaps"] == main["gaps"]
    assert result["request_id"] == "r"
    assert result["related_memories"] == []
    assert "attachment_timeout" in result["memory_notice"]["failed_paths"]

