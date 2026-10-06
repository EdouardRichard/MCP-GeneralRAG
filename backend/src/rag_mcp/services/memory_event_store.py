from copy import deepcopy

from sqlalchemy import select, text

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.services.memory_validators import MemoryProvenanceValidator, sanitize_submission


class MemoryEventStore:
    """Append-only event repository. Deliberately exposes no mutation methods."""

    def __init__(self, session):
        self.session = session

    async def _validate(self, event):
        if event.event_type == 'consolidate' and event.payload.get('payload_version') == 2:
            from rag_mcp.services.memory_validators import validate_consolidation_payload
            validate_consolidation_payload({column.name: getattr(event, column.name)
                                            for column in MemoryEvent.__table__.columns})
            return
        if event.event_type in {"assert", "revise", "consolidate"}:
            payload = event.payload
            validation = await MemoryProvenanceValidator(self.session).validate({
                **payload, "scope_id": event.knowledge_scope_id, "content": payload.get("content_text")
            })
            clean, sanitized = sanitize_submission({**payload, "content": payload["content_text"]})
            del clean["content"]
            if clean != payload or sanitized.status != payload.get("status") or sanitized.injection_flags != payload.get("injection_flags"):
                raise ValueError("MEMORY_WRITE_UNAVAILABLE")
            event.payload = {**payload, "provenance_validation": validation}
        elif event.event_type in {"grant", "rollback"} and event.actor != "management":
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")

    async def append(self, event, *, flush=True):
        await self._validate(event)
        await self.session.execute(text("SET LOCAL ROLE rag_memory_reducer"))
        self.session.add(event)
        if flush:
            await self.session.flush()
        return event

    async def append_many(self, events):
        events = list(events)
        async with self.session.begin_nested():
            for event in events:
                await self._validate(event)
            if events:
                await self.session.execute(text("SET LOCAL ROLE rag_memory_reducer"))
                self.session.add_all(events)
            await self.session.flush()

    async def replay_online(self, scope_id):
        from rag_mcp.models.memory_history import MemoryArchivedEvent
        archived = set((await self.session.execute(select(MemoryArchivedEvent.event_id).join(MemoryEvent)
            .where(MemoryEvent.knowledge_scope_id == scope_id))).scalars().all())
        return [event for event in await self.replay(scope_id) if event["event_id"] not in archived]

    async def replay(self, scope_id, *, through_event_id=None):
        if not isinstance(scope_id, int) or isinstance(scope_id, bool) or scope_id <= 0:
            raise ValueError("MISSING_KNOWLEDGE_SCOPE")
        statement = select(MemoryEvent).where(MemoryEvent.knowledge_scope_id == scope_id).order_by(MemoryEvent.event_id)
        if through_event_id is not None:
            statement = statement.where(MemoryEvent.event_id <= through_event_id)
        rows = (await self.session.execute(statement.execution_options(populate_existing=True))).scalars().all()
        return deepcopy([{column.name: (getattr(row, column.name).isoformat()
                if hasattr(getattr(row, column.name), "isoformat") else getattr(row, column.name))
                 for column in MemoryEvent.__table__.columns} for row in rows])

