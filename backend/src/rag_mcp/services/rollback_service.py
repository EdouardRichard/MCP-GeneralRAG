class RollbackService:
    def rollback(self, events, *, scope_id, actor, event_point=None, time_point=None):
        if actor != "management" or not isinstance(scope_id, int) or isinstance(scope_id, bool) or scope_id <= 0:
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
        history = sorted(events, key=lambda event: event["event_id"])
        if not history or any(event["knowledge_scope_id"] != scope_id for event in history):
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
        if (event_point is None) == (time_point is None):
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
        if time_point is not None:
            from rag_mcp.services.memory_reader import timestamp
            try:
                candidates = [event for event in history if timestamp(event["occurred_at"]) <= timestamp(time_point)]
                event_point = candidates[-1]["event_id"] if candidates else None
            except (ValueError, TypeError):
                raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN") from None
        if not isinstance(event_point, int) or isinstance(event_point, bool) or not any(event["event_id"] == event_point for event in history):
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
        return {"scope_id": scope_id, "event_point": event_point, "preserve_access": True, "event_type": "rollback",
                "preserved_access_event_ids": [event["event_id"] for event in history if event.get("event_type") == "access"]}
