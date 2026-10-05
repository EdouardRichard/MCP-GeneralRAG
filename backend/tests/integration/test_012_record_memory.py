import pytest


@pytest.mark.asyncio
async def test_record_memory_hard_anchor_closed_loop(db_session):
    from rag_mcp.services.memory_service import MemoryService
    from rag_mcp.models.memory_projection import MemoryEntry
    from rag_mcp.models.memory_event import MemoryEvent
    from tests.integration.test_012_persisted_write_loop import published_payload
    service = MemoryService(db_session)
    payload = await published_payload(db_session)
    result = await service.record(payload)
    assert result["status"] == "active"
    assert result["provenance_validation"]["validated"] is True
    assert result["provenance_validation"]["attributions"][0]["evidence_id"] == payload["evidence_refs"][0]
    event = await db_session.get(MemoryEvent, result["memory_id"])
    row = await db_session.get(MemoryEntry, result["memory_id"])
    assert event is not None and row is not None
    assert event.payload["content_text"] == row.content_text == payload["content"]
    assert all(item["matches_replay"] for item in (await service.inspect_projections(payload["scope_id"])).values())

