from __future__ import annotations

from datetime import datetime, timezone

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_projection_store import MemoryProjectionStore
from rag_mcp.services.memory_reducer import reduce_events
from rag_mcp.services.memory_validators import validate_memory, sanitize_memory


def recall_memories(rows, *, mode, scope_ids, memory_id=None, limit=40):
    if not scope_ids:
        raise ValueError("MISSING_KNOWLEDGE_SCOPE")
    selected = [row for row in rows if row.get("knowledge_scope_id") in scope_ids]
    if mode == "by_id":
        selected = [row for row in selected if row.get("memory_id") == memory_id]
    return selected[:max(40, limit)]


def format_memory_recall(rows, *, failed_paths=None):
    failed_paths = failed_paths or []
    memories = []
    for row in rows:
        item = dict(row)
        text = item.get("content_text", "")
        item["content_excerpt"] = text[:300]
        memories.append(item)
    return {"memories": memories, "degraded": bool(failed_paths), "failed_paths": failed_paths, "counts": {"returned": len(memories)}}


class MemoryService:
    def __init__(self, session, projection_store=None):
        self.session = session
        self.events = []
        self.projections = projection_store or MemoryProjectionStore()

    async def apply_event(self, event_data):
        event = MemoryEvent(
            event_id=event_data["event_id"], event_type=event_data["event_type"],
            aggregate_id=event_data["aggregate_id"], knowledge_scope_id=event_data["knowledge_scope_id"],
            payload=event_data.get("payload", {}), authority=event_data.get("authority", {}),
            scope_meta=event_data.get("scope_meta", {}), mutability=event_data.get("mutability", {}),
            provenance_meta=event_data.get("provenance_meta", {}), recoverability=event_data.get("recoverability", {}),
            actor=event_data.get("actor", "system"), request_id=event_data.get("request_id", "test"),
            occurred_at=event_data.get("occurred_at", datetime.now(timezone.utc)),
        )
        await MemoryEventStore(self.session).append(event)
        self.events.append(event_data)
        state = reduce_events(self.events)
        self.projections.upsert_from_reducer(event.memory_id if hasattr(event, "memory_id") else event.aggregate_id, state)
        return {"status": "complete", "event_id": event.event_id}

    async def record(self, payload):
        validate_memory(payload)
        sanitized = sanitize_memory(payload["content"])
        event_payload = {"content_text": sanitized.content, "kind": payload["kind"], "provenance": payload["provenance"], "evidence_refs": payload.get("evidence_refs", []), "injection_flags": sanitized.injection_flags}
        result = await self.apply_event({"event_id": len(self.events) + 1, "event_type": "assert", "aggregate_id": len(self.events) + 1, "knowledge_scope_id": payload["scope_id"], "payload": event_payload})
        return {"memory_id": result["event_id"], "status": sanitized.status, "provenance_validation": "valid", "injection_flags": sanitized.injection_flags}
