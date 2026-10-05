import pytest
from sqlalchemy import select, func, text
from sqlalchemy.exc import DBAPIError

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.services.memory_validators import MemoryProvenanceValidator
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
async def test_distilled_revalidates_ready_active_source_chain(db_session):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    source = await service.record(payload)
    proposal = {**payload, "content": "Derived scoped procedure", "provenance": "distilled",
                "inference_meta": {**payload["inference_meta"], "supporting_evidence": [f"memory:{source['memory_id']}"]}}
    derived = await service.record(proposal)
    leaf = {**proposal, "content": "Second derived scoped procedure",
            "inference_meta": {**proposal["inference_meta"], "supporting_evidence": [f"memory:{derived['memory_id']}"]}}
    report = await MemoryProvenanceValidator(db_session).validate(leaf)
    assert report["attributions"][0].get("source_chain"), "distilled stopped at one hop without re-verifying its sources"
    await service.record({**payload, "content": "Corrected source procedure", "supersedes_memory_id": source["memory_id"]})
    before = await db_session.scalar(select(func.count()).select_from(MemoryEvent))
    with pytest.raises(ValueError, match="MEMORY_PROVENANCE_INVALID"):
        await service.record(leaf)
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent)) == before


@pytest.mark.asyncio
async def test_source_event_cannot_authorize_changed_projection_metadata(db_session):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    source = await service.record(payload)
    with pytest.raises(DBAPIError, match="immutable|source|facts"):
        async with db_session.begin_nested():
            await db_session.execute(text("SELECT set_config('rag_memory.reducer_event', :event, true)"), {"event": str(source["memory_id"])})
            await db_session.execute(text("UPDATE memory_entries SET confidence=0.99, title='forged' WHERE memory_id=:mid"), {"mid": source["memory_id"]})
