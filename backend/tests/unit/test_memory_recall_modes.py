from rag_mcp.services.memory_reader import public_entry


def test_public_memory_excerpt_keeps_attribution_and_truncation_metadata():
    row = {"memory_id": 1, "knowledge_scope_id": 7, "status": "active", "content_text": "x" * 400,
           "evidence_refs": ["123"], "provenance": "hard", "valid_from": "2026-10-05T00:00:00Z"}
    result = public_entry(row)
    assert result["content_excerpt"] == "x" * 300
    assert result["content_length"] == 400 and result["truncated"]
    assert result["evidence_refs"] == ["123"] and result["provenance"] == "hard"
    assert result["knowledge_scope_id"] == 7 and result["valid_from"] == row["valid_from"]


def test_valid_time_matrix_is_half_open_and_never_relaxes_lifecycle():
    from datetime import datetime, timezone
    import rag_mcp.services.memory_reader as reader
    visible = getattr(reader, "memory_visible", None)
    assert callable(visible), "one deterministic valid-time gate must serve read paths"
    stamp = lambda day: datetime(2026, 10, day, tzinfo=timezone.utc)
    for status in ("active", "superseded", "retired", "quarantined"):
        for flag in (False, True):
            for open_end in (False, True):
                row = {"status": status, "valid_from": stamp(2).isoformat(),
                       "valid_to": None if open_end else stamp(4).isoformat(),
                       "observed_at": stamp(8).isoformat(), "expires_at": None}
                before = dict(row)
                for day in (1, 2, 3, 4, 5):
                    expected = status in ({"active", "superseded"} if flag else {"active"}) and day >= 2 and (open_end or day < 4)
                    assert visible(row, point=stamp(day), now=stamp(10), include_superseded=flag) == expected
                    assert row == before, "as_of must not rewrite observed or valid metadata"
    active = {"status": "active", "valid_from": stamp(3).isoformat(), "valid_to": None, "expires_at": None}
    assert not visible(active, point=None, now=stamp(2), include_superseded=False)
    active["expires_at"] = stamp(4).isoformat()
    assert not visible(active, point=stamp(4), now=stamp(10), include_superseded=False)

