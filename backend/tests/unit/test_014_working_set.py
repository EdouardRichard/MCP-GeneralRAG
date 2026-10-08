"""014 T032: the pure working-set assembler (US4).

FR-020…FR-023/SC-009: ``assemble_working_set`` is a pure function — no IO, no
clock, no model. Given the same captured rows and the same explicit
``snapshot_at`` it must produce byte-identical output, regardless of when it runs.

Covered here: the five-condition shared visibility predicate, the A1–A7 ambiguity
rulings from research §6, data-derived ``snapshot_at`` (identical bytes across
"times"), explicit ordering, cross-bucket dedup, bucket limits, the character
budget with its drop order, and the zero model/network guarantee.
"""

from __future__ import annotations

import builtins
import socket
from datetime import UTC, datetime

import pytest

from rag_mcp.orchestration.working_set import (
    DEFAULT_BUCKET_LIMITS,
    assemble_working_set,
    resolve_recent_session,
    working_set_visible,
)

SNAPSHOT = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
OLDER = "2026-10-08T12:00:00+00:00"
NEWEST = "2026-10-09T11:00:00+00:00"


def _row(memory_id: int, **overrides) -> dict:
    row = {
        "memory_id": memory_id,
        "knowledge_scope_id": 1,
        "kind": "episodic",
        "provenance": "soft",
        "confidence": 0.8,
        "title": None,
        "content_text": f"body-{memory_id}",
        "evidence_refs": [],
        "retention_stage": "active",
        "inference_meta": {"source": "s", "confidence": 0.8, "model_version": "none",
                           "time": "2026-10-09T00:00:00+00:00", "supporting_evidence": []},
        "valid_from": None,
        "valid_to": None,
        "observed_at": NEWEST,
        "session_id": "session-a",
        "agent_id": None,
        "status": "active",
        "superseded_by": None,
        "write_status": "complete",
        "expires_at": None,
    }
    row.update(overrides)
    return row


def _assemble(rows, **overrides):
    arguments = {"rows": rows, "explicit_session_id": None, "snapshot_at": SNAPSHOT,
                 "remaining_characters": 10_000}
    arguments.update(overrides)
    return assemble_working_set(**arguments)


# --- the five-condition visibility predicate ----------------------------------


def test_a_fully_visible_row_is_visible():
    assert working_set_visible(_row(1), snapshot_at=SNAPSHOT) is True


@pytest.mark.parametrize("overrides", [
    {"status": "retired"},
    {"status": "quarantined"},
    {"status": "superseded"},
    {"retention_stage": "archived"},
    {"retention_stage": "compressed"},
    {"valid_to": "2026-10-09T00:00:00+00:00"},
    {"expires_at": "2026-10-01T00:00:00+00:00"},
    {"valid_from": "2026-10-10T00:00:00+00:00", "observed_at": "2026-10-09T00:00:00+00:00"},
])
def test_each_failed_condition_hides_the_row(overrides):
    assert working_set_visible(_row(1, **overrides), snapshot_at=SNAPSHOT) is False


def test_expiry_is_relative_to_the_data_derived_snapshot_not_the_wall_clock():
    # A1: episodic rows always carry expires_at; only "already expired **at the
    # snapshot**" excludes them, otherwise the bucket would always be empty.
    row = _row(1, expires_at="2026-10-09T13:00:00+00:00")
    assert working_set_visible(row, snapshot_at=SNAPSHOT) is True
    assert working_set_visible(row, snapshot_at=datetime(2026, 10, 9, 14, 0, tzinfo=UTC)) is False


def test_an_open_row_at_the_visibility_boundary_is_visible():
    row = _row(1, valid_from="2026-10-09T11:00:00+00:00", observed_at="2026-10-09T11:00:00+00:00")
    assert working_set_visible(row, snapshot_at=SNAPSHOT) is True


# --- A1–A7 ambiguity rulings --------------------------------------------------


def test_a2_supersede_writes_valid_to_and_is_excluded():
    assert working_set_visible(_row(1, valid_to="2026-10-01T00:00:00+00:00"),
                               snapshot_at=SNAPSHOT) is False


def test_a3_retired_with_a_null_valid_to_is_still_excluded():
    # A3: never rely on valid_to alone — a stale manifest may leave it null.
    assert working_set_visible(_row(1, status="retired", valid_to=None),
                               snapshot_at=SNAPSHOT) is False


def test_a4_archived_is_excluded_and_never_treated_as_open():
    assert working_set_visible(_row(1, retention_stage="archived"),
                               snapshot_at=SNAPSHOT) is False


def test_a5_an_expired_session_does_not_hide_the_memory():
    # A5: sessions.expires_at is runtime state and no session FK exists on the row.
    assert working_set_visible(_row(1, session_id="long-gone"), snapshot_at=SNAPSHOT) is True


def test_a6_an_unparsable_timestamp_does_not_raise():
    assert working_set_visible(_row(1, observed_at="not-a-time"), snapshot_at=SNAPSHOT) is True
    assert working_set_visible(_row(1, valid_from="not-a-time", observed_at=NEWEST),
                               snapshot_at=SNAPSHOT) is False
    assert working_set_visible(_row(1, expires_at="not-a-time"), snapshot_at=SNAPSHOT) is False


def test_a6_an_unusable_observed_at_sorts_last_by_memory_id():
    rows = {
        1: _row(1, observed_at=NEWEST),
        2: _row(2, observed_at="not-a-time"),
        3: _row(3, observed_at=OLDER),
    }
    result = _assemble(rows)
    assert [item["memory_id"] for item in result["open_items"]] == [1, 3, 2]


def test_a7_valid_from_after_observed_at_is_excluded():
    assert working_set_visible(
        _row(1, valid_from="2026-10-09T11:00:01+00:00", observed_at="2026-10-09T11:00:00+00:00"),
        snapshot_at=SNAPSHOT) is False


def test_a6_unusable_timestamps_never_derive_snapshot_at():
    from rag_mcp.orchestration.working_set import snapshot_of

    assert snapshot_of({1: _row(1, observed_at="not-a-time"), 2: _row(2, observed_at=OLDER)}) \
        == datetime.fromisoformat(OLDER)
    assert snapshot_of({1: _row(1, observed_at="not-a-time"), 2: _row(2, observed_at=None)}) is None


# --- data-derived snapshot_at and byte stability ------------------------------


def test_snapshot_at_is_data_derived_and_bytes_are_time_independent():
    from rag_mcp.orchestration.packing import canonical

    rows = {1: _row(1, observed_at=OLDER), 2: _row(2, observed_at=NEWEST)}
    first = _assemble(rows, snapshot_at=None)
    # Same data, evaluated "at" two very different moments: identical bytes.
    second = assemble_working_set(rows=rows, explicit_session_id=None,
                                  snapshot_at=datetime(2030, 1, 1, tzinfo=UTC),
                                  remaining_characters=10_000)
    assert first == second
    assert canonical(first) == canonical(second)


def test_an_explicit_snapshot_equal_to_the_data_maximum_is_the_same_result():
    rows = {1: _row(1, observed_at=NEWEST)}
    assert _assemble(rows, snapshot_at=None) == _assemble(rows, snapshot_at=datetime(2026, 10, 9, 11, 0, tzinfo=UTC))


# --- ordering and dedup -------------------------------------------------------


def test_each_bucket_is_ordered_by_observed_at_then_memory_id_descending():
    rows = {
        1: _row(1, observed_at=OLDER),
        2: _row(2, observed_at=NEWEST),
        3: _row(3, observed_at=NEWEST),
    }
    result = _assemble(rows)
    assert [item["memory_id"] for item in result["open_items"]] == [3, 2, 1]


def test_a_memory_appears_in_only_one_bucket_with_a_dedup_decision():
    # An episodic memory of the resolved session is an open item first, so the
    # recent-activity bucket must not repeat it.
    rows = {1: _row(1, session_id="session-a"), 2: _row(2, session_id="session-a", observed_at=OLDER)}
    result = _assemble(rows, explicit_session_id="session-a")
    seen = [item["memory_id"] for bucket in ("open_items", "recent_activity", "procedural")
            for item in result[bucket]]
    assert seen == sorted(set(seen), reverse=False) or len(seen) == len(set(seen))
    assert [item["memory_id"] for item in result["open_items"]] == [1, 2]
    assert result["recent_activity"] == []
    assert {"memory_id": 2, "decision": "deduped"} in result["decisions"]
    assert {"memory_id": 1, "decision": "selected"} in result["decisions"]


def test_decisions_are_append_only_selected_deduped_truncated():
    rows = {index: _row(index) for index in range(1, 6)}
    result = _assemble(rows, limits={"open_items": 2, "recent_activity": 0, "procedural": 0})
    decisions = [entry["decision"] for entry in result["decisions"]]
    assert decisions[:5] == ["selected", "selected", "truncated", "truncated", "truncated"]
    assert result["truncated"] is True
    assert all(entry["decision"] in {"selected", "deduped", "truncated"} for entry in result["decisions"])


def test_bucket_limits_are_applied_before_the_character_budget():
    rows = {index: _row(index) for index in range(1, 8)}
    result = _assemble(rows, limits={"open_items": 3, "recent_activity": 3, "procedural": 2})
    assert len(result["open_items"]) == 3
    # The session's overflow becomes recent activity (its own cap of 3), which is
    # exactly why the second bucket exists despite the dedup order.
    assert len(result["recent_activity"]) == 3
    assert len(result["procedural"]) == 0
    assert result["truncated"] is True
    assert len({item["memory_id"] for bucket in ("open_items", "recent_activity", "procedural")
                for item in result[bucket]}) == len(result["open_items"]) + len(result["recent_activity"])


def test_procedural_items_land_in_their_own_bucket():
    rows = {1: _row(1, kind="procedural"), 2: _row(2, kind="semantic"), 3: _row(3, kind="episodic")}
    result = _assemble(rows)
    assert [item["memory_id"] for item in result["procedural"]] == [1]
    assert [item["memory_id"] for item in result["open_items"]] == [3]
    # semantic memories are neither open items nor procedural; they belong to the
    # digest, not the working set.
    assert 2 not in {item["memory_id"] for item in result["open_items"] + result["procedural"]}


def test_default_bucket_limits_match_the_documented_policy_defaults():
    assert DEFAULT_BUCKET_LIMITS == {"open_items": 3, "recent_activity": 3, "procedural": 2}


# --- session resolution -------------------------------------------------------


def test_explicit_session_wins():
    rows = {1: _row(1, session_id="session-a"), 2: _row(2, session_id="session-b", observed_at=NEWEST)}
    assert resolve_recent_session(rows, explicit_session_id="session-z") == "session-z"


def test_the_most_recent_session_is_resolved_with_a_lexicographic_tiebreak():
    rows = {
        1: _row(1, session_id="session-a", observed_at=NEWEST),
        2: _row(2, session_id="session-b", observed_at=NEWEST),
        3: _row(3, session_id="session-c", observed_at=OLDER),
    }
    assert resolve_recent_session(rows, explicit_session_id=None) == "session-b"


def test_rows_without_a_session_do_not_resolve_one():
    rows = {1: _row(1, session_id=None), 2: _row(2, session_id=None, observed_at=OLDER)}
    assert resolve_recent_session(rows, explicit_session_id=None) is None


def test_only_visible_episodic_rows_resolve_a_session():
    rows = {1: _row(1, status="quarantined", session_id="hidden"),
            2: _row(2, kind="procedural", session_id="procedural-session")}
    assert resolve_recent_session(rows, explicit_session_id=None) is None


def test_no_session_means_an_empty_recent_activity_bucket_without_an_error():
    rows = {1: _row(1, session_id=None), 2: _row(2, session_id=None, observed_at=OLDER)}
    result = _assemble(rows, explicit_session_id=None)
    assert result["recent_activity"] == []
    assert result["session_resolved"] is None
    assert result["open_items"], "counts stay visible even with no session"


def test_a_resolved_session_scopes_recent_activity():
    """Recent activity holds the resolved session's memories that are not open items.

    ``open_items`` takes precedence (data-model §7.4 dedup order), so a session
    memory only lands in ``recent_activity`` once the open-items cap is reached.
    """
    rows = {
        1: _row(1, session_id="session-a", observed_at=NEWEST),
        2: _row(2, session_id="session-b", observed_at=OLDER),
        3: _row(3, session_id="session-b", observed_at="2026-10-07T00:00:00+00:00"),
    }
    result = _assemble(rows, explicit_session_id="session-b",
                       limits={"open_items": 1, "recent_activity": 3, "procedural": 0})
    assert [item["memory_id"] for item in result["open_items"]] == [1]
    assert [item["memory_id"] for item in result["recent_activity"]] == [2, 3]
    assert result["session_resolved"] == "session-b"


# --- character budget and its drop order --------------------------------------


def test_character_budget_drops_procedural_before_recent_activity_and_open_items():
    from rag_mcp.orchestration.packing import text_characters

    rows = {
        1: _row(1, kind="procedural", content_text="p" * 100, session_id=None, observed_at=NEWEST),
        2: _row(2, kind="episodic", content_text="r" * 100, session_id="s", observed_at=OLDER),
        3: _row(3, kind="episodic", content_text="o" * 100, session_id=None,
                observed_at="2026-10-07T00:00:00+00:00"),
    }
    full = _assemble(rows, explicit_session_id="s", remaining_characters=10 ** 6)
    assert [item["memory_id"] for item in full["procedural"]] == [1]
    # A budget that exactly fits everything but the procedural bucket must drop
    # exactly that bucket: procedural is cropped first by contract.
    keep = text_characters(full["open_items"]) + text_characters(full["recent_activity"])
    cropped = _assemble(rows, explicit_session_id="s", remaining_characters=keep)
    assert cropped["procedural"] == []
    assert cropped["open_items"] == full["open_items"]
    assert cropped["recent_activity"] == full["recent_activity"]
    assert cropped["truncated"] is True
    assert {"memory_id": 1, "decision": "truncated"} in cropped["decisions"]


def test_a_zero_budget_drops_everything_in_the_documented_order():
    rows = {
        1: _row(1, kind="procedural", observed_at=NEWEST),
        2: _row(2, kind="episodic", session_id="s", observed_at=OLDER),
        3: _row(3, kind="episodic", session_id=None, observed_at="2026-10-07T00:00:00+00:00"),
    }
    result = _assemble(rows, explicit_session_id="s", limits={"open_items": 5, "recent_activity": 5,
                                                             "procedural": 5},
                       remaining_characters=0)
    assert result["open_items"] == [] and result["recent_activity"] == [] \
        and result["procedural"] == []
    dropped = [entry["memory_id"] for entry in result["decisions"] if entry["decision"] == "truncated"]
    # procedural is cropped first; open_items is then cropped from its
    # lowest-priority tail. recent_activity is empty here because the dedup order
    # already placed both session memories into open_items.
    assert dropped[0] == 1, f"procedural must be cropped first: {dropped}"
    assert set(dropped[1:]) == {2, 3}
    assert dropped[1] == 3, f"open_items must be cropped from the tail: {dropped}"


def test_recent_activity_is_cropped_before_open_items_when_it_is_non_empty():
    """Prove the crop order by bucket state, not by the mixed decision trail.

    The decision trail also carries the *limit* truncations, so the crop order is
    observed through which buckets survive progressively tighter budgets.
    """
    from rag_mcp.orchestration.packing import text_characters

    rows = {
        1: _row(1, kind="procedural", observed_at="2026-10-09T11:00:00+00:00"),
        2: _row(2, kind="episodic", session_id="s", observed_at=NEWEST),
        3: _row(3, kind="episodic", session_id="s", observed_at=OLDER),
        4: _row(4, kind="episodic", session_id=None, observed_at="2026-10-07T00:00:00+00:00"),
    }
    limits = {"open_items": 1, "recent_activity": 5, "procedural": 5}
    full = _assemble(rows, explicit_session_id="s", limits=limits, remaining_characters=10 ** 6)
    assert [item["memory_id"] for item in full["procedural"]] == [1]
    assert [item["memory_id"] for item in full["recent_activity"]] == [3]
    assert [item["memory_id"] for item in full["open_items"]] == [2]

    recent_chars = text_characters(full["recent_activity"])
    open_chars = text_characters(full["open_items"])

    # Fits everything but procedural -> only procedural is cropped.
    only_procedural_cropped = _assemble(rows, explicit_session_id="s", limits=limits,
                                        remaining_characters=recent_chars + open_chars)
    assert only_procedural_cropped["procedural"] == []
    assert only_procedural_cropped["recent_activity"] == full["recent_activity"]
    assert only_procedural_cropped["open_items"] == full["open_items"]

    # Tightened to the open-items size only -> recent_activity is cropped too.
    recent_cropped = _assemble(rows, explicit_session_id="s", limits=limits,
                               remaining_characters=open_chars)
    assert recent_cropped["procedural"] == []
    assert recent_cropped["recent_activity"] == []
    assert recent_cropped["open_items"] == full["open_items"]

    # Zero budget -> nothing survives, and open_items is cropped last.
    nothing = _assemble(rows, explicit_session_id="s", limits=limits, remaining_characters=0)
    assert nothing["procedural"] == [] and nothing["recent_activity"] == [] \
        and nothing["open_items"] == []
    assert nothing["truncated"] is True


def test_items_never_carry_a_scope_field():
    result = _assemble({1: _row(1)})
    for bucket in ("open_items", "recent_activity", "procedural"):
        for item in result[bucket]:
            assert "knowledge_scope_id" not in item
            assert "scope" not in item


def test_items_match_the_working_set_item_contract():
    result = _assemble({1: _row(1, content_text="x" * 400)})
    item = result["open_items"][0]
    assert list(item) == ["memory_id", "kind", "provenance", "confidence", "evidence_refs",
                          "inference_meta", "content_excerpt", "truncated", "observed_at"]
    assert len(item["content_excerpt"]) <= 300
    assert item["truncated"] is True


# --- purity: no model, no network, no IO --------------------------------------


def test_no_socket_is_opened(monkeypatch):
    def _forbid(*_args, **_kwargs):
        raise AssertionError("the working-set assembler must not open a socket")

    monkeypatch.setattr(socket, "socket", _forbid)
    monkeypatch.setattr(socket, "create_connection", _forbid)
    _assemble({1: _row(1)})


def test_no_file_is_opened(monkeypatch):
    original_open = builtins.open

    def _forbid(file, *args, **kwargs):
        raise AssertionError(f"the working-set assembler must not open files ({file})")

    monkeypatch.setattr(builtins, "open", _forbid)
    try:
        _assemble({1: _row(1)})
    finally:
        monkeypatch.setattr(builtins, "open", original_open)


def test_the_module_imports_no_provider_or_io_dependency():
    import ast
    from pathlib import Path

    import rag_mcp.orchestration.working_set as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("sqlalchemy", "qdrant_client", "httpx", "requests", "rag_mcp.providers",
                 "rag_mcp.services", "rag_mcp.models", "rag_mcp.indexing")
    assert not [name for name in imported if name.startswith(forbidden)], imported
