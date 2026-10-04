class RollbackService:
    def rollback(self, events, *, scope_id, actor, event_point):
        if actor != "management":
            raise PermissionError("rollback is management-only")
        if not isinstance(scope_id, int):
            raise ValueError("ROLLBACK_SCOPE_INVALID")
        return {"scope_id": scope_id, "event_point": event_point, "preserve_access": True, "event_type": "rollback"}
