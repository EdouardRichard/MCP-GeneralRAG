"""Live PostgreSQL rejection paths are prerequisites for the write pipeline."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.utils.snowflake import generate_id


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
async def test_database_rejects_event_mutation(db_session, verb):
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    scope = await db_session.scalar(select(KnowledgeScope.scope_id).limit(1))
    assert scope is not None, "development corpus must exist"
    identifier = generate_id()
    db_session.add(MemoryEvent(
        event_id=identifier, event_type="assert", aggregate_id=identifier,
        knowledge_scope_id=scope, payload={"content_text": "immutable"},
        authority={}, scope_meta={}, mutability={}, provenance_meta={}, recoverability={},
        actor="acceptance", request_id=str(identifier), occurred_at=datetime.now(timezone.utc),
    ))
    await db_session.flush()
    statement = ("UPDATE memory_events SET payload='{}'::jsonb WHERE event_id=:id"
                 if verb == "UPDATE" else "DELETE FROM memory_events WHERE event_id=:id")
    async with db_session.begin_nested():
        with pytest.raises(DBAPIError, match="append.only|immutable"):
            await db_session.execute(text(statement), {"id": identifier})


@pytest.mark.asyncio
async def test_live_schema_contains_required_projection_columns(db_session):
    rows = (await db_session.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='memory_entries'"
    ))).scalars().all()
    required = {"content_hash", "confidence", "supersedes_memory_id", "superseded_by",
                "observed_at", "invalidated_at", "session_id", "agent_id", "task_context",
                "injection_flags", "expires_at", "promote_candidate_at", "valid_from", "valid_to"}
    assert required <= set(rows), f"missing live columns: {required - set(rows)}"


@pytest.mark.asyncio
async def test_caller_published_flag_is_not_evidence(db_session):
    from rag_mcp.services import memory_validators
    validator_type = getattr(memory_validators, "MemoryProvenanceValidator", None)
    assert validator_type is not None, "no live evidence revalidation exists"
    validator = validator_type(db_session)
    with pytest.raises(ValueError, match="MEMORY_EVIDENCE_ANCHOR_REQUIRED"):
        await validator.validate({"scope_id": 1, "kind": "semantic", "content": "forged",
            "provenance": "hard", "evidence_refs": [{"published": True, "scope_id": 1,
            "source_id": "fake", "version": "1", "position": 1}]})


@pytest.mark.asyncio
async def test_real_published_chunk_is_reverified_item_by_item(db_session):
    from rag_mcp.models.chunk import Chunk
    from rag_mcp.models.knowledge_version import KnowledgeVersion
    from rag_mcp.services import memory_validators
    validator_type = getattr(memory_validators, "MemoryProvenanceValidator", None)
    assert validator_type is not None, "no live evidence revalidation exists"
    chunk = await db_session.scalar(select(Chunk).join(KnowledgeVersion)
                                    .where(KnowledgeVersion.status == "published").limit(1))
    assert chunk is not None, "real published development evidence is required"
    payload = {"scope_id": chunk.knowledge_scope_id, "kind": "semantic",
               "content": chunk.content_text[:300], "provenance": "hard",
               "evidence_refs": [str(chunk.chunk_id)]}
    validated = await validator_type(db_session).validate(payload)
    attribution = validated["attributions"][0]
    assert attribution["source_id"] == chunk.source_id
    assert attribution["version_id"] == chunk.version_id
    assert attribution["position"] == chunk.position_path
    assert attribution["content_hash"]
    payload["scope_id"] = chunk.knowledge_scope_id + 1
    with pytest.raises(ValueError, match="MEMORY_EVIDENCE_SCOPE_MISMATCH"):
        await validator_type(db_session).validate(payload)
    payload["scope_id"] = chunk.knowledge_scope_id
    async with db_session.begin_nested():
        version = await db_session.get(KnowledgeVersion, chunk.version_id)
        version.status = "superseded"
        await db_session.flush()
        with pytest.raises(ValueError, match="MEMORY_EVIDENCE_ANCHOR_REQUIRED"):
            await validator_type(db_session).validate(payload)
