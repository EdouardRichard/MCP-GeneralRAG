from rag_mcp.services.memory_reader import public_entry


def test_public_memory_excerpt_keeps_attribution_and_truncation_metadata():
    row = {"memory_id": 1, "knowledge_scope_id": 7, "status": "active", "content_text": "x" * 400,
           "evidence_refs": ["123"], "provenance": "hard", "valid_from": "2026-10-05T00:00:00Z"}
    result = public_entry(row)
    assert result["content_excerpt"] == "x" * 300
    assert result["content_length"] == 400 and result["truncated"]
    assert result["evidence_refs"] == ["123"] and result["provenance"] == "hard"
    assert result["knowledge_scope_id"] == 7 and result["valid_from"] == row["valid_from"]

