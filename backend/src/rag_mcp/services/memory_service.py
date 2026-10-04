from __future__ import annotations

from datetime import datetime, timezone

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_projection_store import MemoryProjectionStore
from rag_mcp.services.memory_reducer import reduce_events


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

