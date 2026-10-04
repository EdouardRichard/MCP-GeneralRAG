import pytest


@pytest.mark.asyncio
async def test_record_memory_hard_anchor_closed_loop():
    from rag_mcp.services.memory_service import MemoryService

    class Session:
        def add(self, item): pass
        async def flush(self): pass

    service = MemoryService(Session())
    result = await service.record({"scope_id": 1, "kind": "episodic", "content": "fact", "provenance": "hard", "evidence_refs": [{"scope_id": 1, "published": True, "source_id": "s", "version": "1", "position": 1}]})
    assert result["status"] == "active"
    assert result["provenance_validation"] == "valid"

