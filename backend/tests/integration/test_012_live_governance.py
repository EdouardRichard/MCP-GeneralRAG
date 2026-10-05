from uuid import uuid4

import pytest
from sqlalchemy import select, func

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.models.memory_salience import MemorySalience
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.services.memory_reducer import projection_fingerprint
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
async def test_management_rollback_restores_supersede_chain_and_preserves_usage(db_session):
    service = MemoryService(db_session)
    govern = getattr(service, "govern", None)
    assert callable(govern), "management commands have no real event/projection pipeline"
    sid, payload = await scope_and_payload(db_session)
    first = await service.record(payload)
    second = await service.record({**payload, "content": "Corrected procedure", "supersedes_memory_id": first["memory_id"]})
    before_use = await db_session.get(MemoryEntry, second["memory_id"])
    fact = {key: getattr(before_use, key) for key in ("content_text", "provenance", "confidence", "valid_from", "valid_to", "supersedes_memory_id")}
    usage = await govern("access", scope_id=sid, memory_id=second["memory_id"], actor="management", reason="verified read")
    await db_session.refresh(before_use)
    assert {key: getattr(before_use, key) for key in fact} == fact
    salience = await db_session.get(MemorySalience, second["memory_id"])
    assert salience.access_count == 1 and salience.reinforced_at is not None
    before = await db_session.scalar(select(func.count()).select_from(MemoryEvent))
    with pytest.raises(PermissionError, match="MEMORY_ROLLBACK_FORBIDDEN"):
        await govern("rollback", scope_id=sid, event_point=first["memory_id"], actor="mcp", reason="untrusted")
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent)) == before
    result = await govern("rollback", scope_id=sid, event_point=first["memory_id"], actor="management", reason="human correction")
    assert result["before_fingerprint"] != result["after_fingerprint"]
    assert result["impact"]["memory_ids"] == sorted([first["memory_id"], second["memory_id"]])
    event = await db_session.get(MemoryEvent, result["event_id"])
    assert event.event_type == "rollback" and event.payload["reason"] == "human correction"
    assert event.payload["before_fingerprint"] == result["before_fingerprint"]
    current = await service.recall(scope_ref=[str(sid)])
    assert [row["memory_id"] for row in current["memories"]] == [first["memory_id"]]
    await db_session.refresh(salience)
    assert salience.access_count == 1
    assert await db_session.get(MemoryEvent, usage["event_id"]) is not None
    assert all(item["matches_replay"] for item in (await service.inspect_projections(sid)).values())
    other, _ = await scope_and_payload(db_session)
    with pytest.raises(PermissionError, match="MEMORY_ROLLBACK_FORBIDDEN"):
        await govern("rollback", scope_id=other, event_point=first["memory_id"], actor="management", reason="wrong scope")


@pytest.mark.asyncio
async def test_retire_purge_and_binding_are_derived_management_events(db_session, tmp_path):
    from rag_mcp.services.scope_resolver import MemoryScopeResolver
    service = MemoryService(db_session)
    govern = getattr(service, "govern", None)
    assert callable(govern), "management commands have no real event/projection pipeline"
    sid, payload = await scope_and_payload(db_session)
    first = await service.record(payload)
    result = await govern("retire", scope_id=sid, memory_id=first["memory_id"], actor="management", reason="obsolete")
    assert (await db_session.get(MemoryEvent, result["event_id"])).event_type == "retract"
    assert (await service.recall(scope_ref=[str(sid)]))["memories"] == []
    assert all(item["matches_replay"] for item in (await service.inspect_projections(sid)).values())
    purged = await govern("purge", scope_id=sid, memory_id=first["memory_id"], actor="management", reason="explicit removal")
    assert await db_session.get(MemoryEvent, first["memory_id"]) is not None
    assert (await db_session.get(MemoryEvent, purged["event_id"])).payload["purge"] is True
    binding = await govern("binding", scope_id=sid, actor="management", reason="directory association",
                           binding_kind="workdir_prefix", binding_value=str(tmp_path))
    assert (await db_session.get(MemoryEvent, binding["event_id"])).event_type == "grant"
    assert await MemoryScopeResolver(db_session).resolve(f"path:{tmp_path}") == sid
    with pytest.raises(PermissionError):
        await govern("binding", scope_id=sid, actor="mcp", reason="model escalation", binding_kind="workdir_prefix", binding_value=str(tmp_path / "other"))
