def test_status_is_post_filtered_and_not_sent_to_vector_query():
    from rag_mcp.indexing.qdrant_client import memory_filter_payload

    payload = memory_filter_payload(scope_ids=[1], kind="episodic", status="retired")
    assert "status" not in payload
    assert payload["scope_ids"] == [1]

