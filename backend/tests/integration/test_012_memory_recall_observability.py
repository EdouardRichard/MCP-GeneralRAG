def test_recall_observability_excerpt_counts_and_partial_state():
    from rag_mcp.services.memory_service import format_memory_recall

    result = format_memory_recall([{"memory_id": 1, "content_text": "x" * 400}], failed_paths=["vector"])
    assert len(result["memories"][0]["content_excerpt"]) <= 300
    assert result["degraded"] is True
    assert result["failed_paths"] == ["vector"]
