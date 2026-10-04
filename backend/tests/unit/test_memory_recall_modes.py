def test_memory_recall_modes_and_limit_floor():
    from rag_mcp.services.memory_service import recall_memories

    rows = [{"memory_id": 1, "knowledge_scope_id": 7, "status": "active", "valid_from": 0, "valid_to": None}]
    assert recall_memories(rows, mode="by_id", memory_id=1, scope_ids=[7])[0]["memory_id"] == 1
    assert len(recall_memories(rows, mode="timeline", scope_ids=[7], limit=1)) == 1
    assert recall_memories(rows, mode="filtered", scope_ids=[8]) == []

