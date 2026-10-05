import json

import pytest
from sqlalchemy import select

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.services.memory_projection_store import MemoryProjectionStore
from rag_mcp.services.memory_reducer import reduce_events

from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
async def test_all_untrusted_metadata_is_redacted_before_log_and_views(db_session):
    sid, payload = await scope_and_payload(db_session)
    payload.update(title="password=titlecredential", tags=["token=tagcredential"],
                   agent_id="api_key=agentcredential", task_context={"client_secret": "contextcredential", "nested": {"token": "nestedcredential"}})
    payload["inference_meta"]["source"] = "source password=sourcecredential"
    service = MemoryService(db_session)
    result = await service.record(payload)
    event = await db_session.scalar(select(MemoryEvent).where(MemoryEvent.aggregate_id == result["memory_id"]))
    entry = await db_session.get(MemoryEntry, result["memory_id"])
    manifest = await service.projections.current(sid)
    for value in (event.payload, entry.submission_meta, manifest.payload):
        stored = json.dumps(value)
        for secret in ("titlecredential", "tagcredential", "agentcredential", "contextcredential", "nestedcredential", "sourcecredential"):
            assert secret not in stored, "metadata credential crossed the sole write boundary"
        assert "password" in stored and "client_secret" in stored


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["relation", "dense", "links", "summary", "files", "salience"])
async def test_each_adapter_rejects_scope_relabel_before_io(db_session, tmp_path, path):
    event = {"event_id": 1, "aggregate_id": 1, "knowledge_scope_id": 81, "event_type": "assert",
             "occurred_at": "2026-10-05T01:00:00+00:00", "payload": {"content_text": "scoped fact", "kind": "semantic"}}
    state = reduce_events([event])
    store = MemoryProjectionStore(db_session, projection_root=tmp_path)
    with pytest.raises(ValueError, match="MEMORY_EVIDENCE_SCOPE_MISMATCH"):
        await getattr(store, f"_materialize_{path}")(state, 82, 1)
    assert not list(tmp_path.rglob("*.md"))
