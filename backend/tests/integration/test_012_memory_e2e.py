import pytest


@pytest.mark.asyncio
async def test_memory_e2e_hard_anchor_quarantine_reader_and_timeline():
    from rag_mcp.services.memory_service import MemoryService, recall_memories
    from rag_mcp.mcp.memory_tools import tool_names

    class Session:
        def add(self, item): pass
        async def flush(self): pass

    service = MemoryService(Session())
    result = await service.record({"scope_id": 1, "kind": "episodic", "content": "fact", "provenance": "hard", "evidence_refs": [{"scope_id": 1, "published": True, "source_id": "s", "version": "1", "position": 1}]})
    assert result["status"] == "active"
    assert "record_memory" not in tool_names("reader")
    assert recall_memories([{"memory_id": result["memory_id"], "knowledge_scope_id": 1}], mode="timeline", scope_ids=[1])

