import pytest


@pytest.mark.asyncio
async def test_memory_transaction_appends_event_and_projection_together():
    from rag_mcp.services.memory_service import MemoryService

    class Session:
        def __init__(self): self.added = []
        def add(self, item): self.added.append(item)
        async def flush(self): pass

    session = Session()
    service = MemoryService(session)
    result = await service.apply_event({"event_id": 1, "event_type": "assert", "aggregate_id": 2, "knowledge_scope_id": 7, "payload": {"content_text": "x"}})
    assert result["status"] == "complete"
    assert len(session.added) == 1

