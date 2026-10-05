import pytest


def test_rollback_is_management_only_single_scope_and_preserves_access():
    from rag_mcp.services.rollback_service import RollbackService

    service = RollbackService()
    with pytest.raises(PermissionError):
        service.rollback([], scope_id=1, actor="mcp", event_point=1)
    events = [{"event_id": 1, "knowledge_scope_id": 1, "event_type": "assert", "occurred_at": "2026-10-01T00:00:00+00:00"},
              {"event_id": 2, "knowledge_scope_id": 1, "event_type": "access", "occurred_at": "2026-10-02T00:00:00+00:00"}]
    result = service.rollback(events, scope_id=1, actor="management", event_point=1)
    assert result["scope_id"] == 1
    assert result["preserve_access"] is True


@pytest.mark.parametrize("events,scope,point", [([], 1, 1),
    ([{"event_id": 1, "knowledge_scope_id": 2}], 1, 1),
    ([{"event_id": 1, "knowledge_scope_id": 1}], True, 1),
    ([{"event_id": 1, "knowledge_scope_id": 1}], 1, 999),
])
def test_rollback_plan_rejects_missing_foreign_or_invalid_points(events, scope, point):
    from rag_mcp.services.rollback_service import RollbackService
    with pytest.raises((ValueError, PermissionError), match="MEMORY_ROLLBACK_FORBIDDEN"):
        RollbackService().rollback(events, scope_id=scope, actor="management", event_point=point)


def test_rollback_time_point_resolves_the_log_and_lists_preserved_access():
    from rag_mcp.services.rollback_service import RollbackService
    events = [{"event_id": 1, "knowledge_scope_id": 7, "event_type": "assert", "occurred_at": "2026-10-01T00:00:00+00:00"},
              {"event_id": 2, "knowledge_scope_id": 7, "event_type": "access", "occurred_at": "2026-10-03T00:00:00+00:00"}]
    result = RollbackService().rollback(events, scope_id=7, actor="management", time_point="2026-10-02T00:00:00+00:00")
    assert result["event_point"] == 1
    assert result["preserved_access_event_ids"] == [2]

