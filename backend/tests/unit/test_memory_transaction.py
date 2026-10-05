import pytest


@pytest.mark.asyncio
async def test_raw_event_command_cannot_bypass_provenance(db_session):
    from rag_mcp.services.memory_service import MemoryService
    from rag_mcp.models.memory_event import MemoryEvent
    from sqlalchemy import select, func
    before = await db_session.scalar(select(func.count()).select_from(MemoryEvent))
    with pytest.raises(PermissionError, match="MEMORY_WRITE_UNAVAILABLE"):
        await MemoryService(db_session).apply_event({"event_id": 1, "event_type": "assert", "aggregate_id": 2, "knowledge_scope_id": 7, "payload": {"content_text": "x"}})
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent)) == before

