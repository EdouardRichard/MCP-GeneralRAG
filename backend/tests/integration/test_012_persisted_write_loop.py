"""The real write/read loop and fault visibility, with no substituted storage."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from rag_mcp.models.chunk import Chunk
from rag_mcp.models.knowledge_version import KnowledgeVersion
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.services.memory_service import MemoryService


async def published_payload(session):
    chunk = await session.scalar(select(Chunk).join(KnowledgeVersion)
                                 .where(KnowledgeVersion.status == "published").limit(1))
    assert chunk is not None
    return {"scope_id": chunk.knowledge_scope_id, "kind": "semantic",
            "content": f"Acceptance note {uuid4()}: {chunk.content_text[:150]}",
            "provenance": "hard", "evidence_refs": [str(chunk.chunk_id)]}


@pytest.mark.asyncio
async def test_record_persists_event_and_relation_and_validates_real_anchor(db_session):
    payload = await published_payload(db_session)
    result = await MemoryService(db_session).record(payload)
    row = await db_session.get(MemoryEntry, result["memory_id"])
    assert row is not None, "record returned success without a persisted relation projection"
    assert row.content_text == payload["content"]
    assert row.evidence_refs == payload["evidence_refs"]
    assert row.knowledge_scope_id == payload["scope_id"]
    assert isinstance(result["provenance_validation"], dict)
    assert result["provenance_validation"]["attributions"][0]["evidence_id"] == payload["evidence_refs"][0]
    assert isinstance(result["injection_flags"], dict)
    assert result["request_id"]
    assert row.write_status == "complete"


@pytest.mark.asyncio
async def test_missing_anchor_cannot_append_an_event(db_session):
    payload = await published_payload(db_session)
    payload["evidence_refs"] = ["9223372036854775806"]
    before = await db_session.scalar(select(func.count()).select_from(MemoryEvent))
    with pytest.raises(ValueError, match="MEMORY_EVIDENCE_ANCHOR_REQUIRED"):
        await MemoryService(db_session).record(payload)
    after = await db_session.scalar(select(func.count()).select_from(MemoryEvent))
    assert after == before


@pytest.mark.asyncio
async def test_all_six_real_projections_match_replay(db_session):
    service = MemoryService(db_session)
    inspect = getattr(service, "inspect_projections", None)
    assert callable(inspect), "no integrity verification for real projection stores"
    payload = await published_payload(db_session)
    await service.record(payload)
    report = await inspect(payload["scope_id"])
    assert set(report) == {"relation", "dense", "links", "summary", "file", "salience"}
    for name, result in report.items():
        assert result["count"] > 0, f"{name} was not actually materialized"
        assert result["matches_replay"], f"{name} diverges from authority"
        assert result["fingerprint"]
