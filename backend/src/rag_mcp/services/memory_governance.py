"""Trusted management commands append events before any derived write."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text

from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.scope_binding import ScopeBinding
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_projection_store import ProjectionFailure
from rag_mcp.services.memory_reducer import reduce_events, projection_fingerprint
from rag_mcp.services.memory_validators import sanitize_submission
from rag_mcp.services.scope_binding_service import ScopeBindingService
from rag_mcp.utils.snowflake import generate_id


class MemoryGovernance:
    def __init__(self, service):
        self.service, self.session = service, service.session

    async def execute(self, action, *, scope_id, actor, reason, memory_id=None, event_point=None,
                      time_point=None, binding_id=None, binding_kind=None, binding_value=None,
                      priority=0, status="active"):
        if actor != "management" or not isinstance(scope_id, int) or isinstance(scope_id, bool) or action not in {"access", "retire", "purge", "rollback", "binding"}:
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("MEMORY_PROVENANCE_INVALID: reason required")
        scope = await self.session.get(KnowledgeScope, scope_id)
        if scope is None or scope.status != "active":
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:scope)"), {"scope": scope_id})
        history = await MemoryEventStore(self.session).replay(scope_id)
        state = reduce_events(history)
        current = await self.service.projections.current(scope_id)
        if history and (current is None or current.source_event_id != history[-1]["event_id"]):
            raise ValueError("MEMORY_WRITE_UNAVAILABLE")
        event_id, request_id = generate_id(), str(uuid4())
        payload = {"reason": reason}
        target = state["entries"].get(memory_id)
        if action in {"access", "retire", "purge"}:
            if target is None or target["knowledge_scope_id"] != scope_id:
                raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
            if action == "access" and target["status"] != "active":
                raise ValueError("MEMORY_WRITE_UNAVAILABLE")
            event_type = "access" if action == "access" else "retract"
            aggregate_id = memory_id
            if action == "purge":
                payload["purge"] = True
        elif action == "rollback":
            if (event_point is None) == (time_point is None):
                raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
            if time_point is not None:
                from rag_mcp.services.memory_reader import timestamp
                candidates = [event for event in history if timestamp(event["occurred_at"]) <= timestamp(time_point)]
                event_point = candidates[-1]["event_id"] if candidates else None
            if not isinstance(event_point, int) or isinstance(event_point, bool) or not any(event["event_id"] == event_point for event in history):
                raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
            event_type, aggregate_id = "rollback", event_id
            payload["event_point"] = event_point
        else:
            if binding_kind not in {"workdir_prefix", "git_remote", "dir_name"} or status not in {"active", "disabled"}:
                raise ValueError("MEMORY_PROVENANCE_INVALID: binding")
            if not isinstance(priority, int) or isinstance(priority, bool):
                raise ValueError("MEMORY_PROVENANCE_INVALID: priority")
            if not isinstance(binding_value, str) or not binding_value.strip():
                raise ValueError("MISSING_KNOWLEDGE_SCOPE")
            normalizer = ScopeBindingService([])
            if binding_kind == "workdir_prefix":
                binding_value = normalizer._normalize_path(binding_value)
            elif binding_kind == "git_remote":
                binding_value = normalizer._normalize_remote(binding_value)
            elif any(character in binding_value for character in "/\\"):
                raise ValueError("MEMORY_PROVENANCE_INVALID: dir_name")
            existing = await self.session.scalar(select(ScopeBinding).where(
                ScopeBinding.binding_kind == binding_kind, ScopeBinding.binding_value == binding_value))
            if existing and existing.knowledge_scope_id != scope_id:
                raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
            if binding_id and (not existing or existing.binding_id != binding_id):
                raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
            binding_id = existing.binding_id if existing else event_id
            payload.update(binding_id=binding_id, binding_kind=binding_kind, binding_value=binding_value, priority=priority, status=status)
            event_type, aggregate_id = "grant", binding_id
        payload, _ = sanitize_submission(payload)
        now = datetime.now(timezone.utc)
        event = MemoryEvent(event_id=event_id, aggregate_id=aggregate_id, knowledge_scope_id=scope_id,
            event_type=event_type, payload=payload, actor="management", request_id=request_id, occurred_at=now,
            authority={"source": "management"}, scope_meta={"knowledge_scope_id": scope_id},
            mutability={"correction": "append_event"}, provenance_meta={"source": "management"},
            recoverability={"source": "event_log"}, actionability="audit")
        candidate = {column.name: getattr(event, column.name) for column in MemoryEvent.__table__.columns if column.name != "created_at"}
        after = reduce_events([*history, candidate])
        impact = {"memory_ids": sorted(mid for mid in set(state["entries"]) | set(after["entries"])
                                        if state["entries"].get(mid) != after["entries"].get(mid)),
                  "scope_ids": [scope_id]}
        result = {"scope_id": scope_id, "event_id": event_id, "request_id": request_id, "impact": impact,
                  "before_fingerprint": projection_fingerprint(state), "after_fingerprint": projection_fingerprint(after)}
        event.payload = {**payload, **{key: result[key] for key in ("impact", "before_fingerprint", "after_fingerprint")}}
        fields = {column.name: getattr(event, column.name) for column in MemoryEvent.__table__.columns if column.name != "created_at"}
        self.service._ensure_vector_store()
        try:
            async with self.session.begin_nested():
                await MemoryEventStore(self.session).append(event)
                after = reduce_events(await MemoryEventStore(self.session).replay(scope_id))
                await self.service.projections.materialize(after, scope_id, event_id)
                integrity = await self.service.projections.inspect(after, scope_id)
                if not all(item["matches_replay"] for item in integrity.values()):
                    raise ProjectionFailure("integrity")
            await self.session.commit()
        except ProjectionFailure as failure:
            if failure.path == "relation":
                await self.session.rollback()
                raise
            await MemoryEventStore(self.session).append(MemoryEvent(**fields))
            after = reduce_events(await MemoryEventStore(self.session).replay(scope_id))
            await self.service.projections.retain_failure(after, scope_id, event_id, failure.path)
            await self.session.commit()
            raise ValueError("MEMORY_WRITE_UNAVAILABLE") from None
        except Exception:
            await self.session.rollback()
            raise
        return result
