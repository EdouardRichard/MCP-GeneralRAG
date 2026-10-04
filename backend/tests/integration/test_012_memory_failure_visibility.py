import pytest


@pytest.mark.asyncio
async def test_failed_projection_is_not_complete_or_recallable():
    from rag_mcp.services.memory_projection_store import MemoryProjectionStore

    store = MemoryProjectionStore()
    state = store.mark_failed(42, "vector")
    assert state["status"] == "failed"
    assert store.recallable(42) is False
