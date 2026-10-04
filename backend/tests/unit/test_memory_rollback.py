import pytest


def test_rollback_is_management_only_single_scope_and_preserves_access():
    from rag_mcp.services.rollback_service import RollbackService

    service = RollbackService()
    with pytest.raises(PermissionError):
        service.rollback([], scope_id=1, actor="mcp", event_point=1)
    result = service.rollback([], scope_id=1, actor="management", event_point=1)
    assert result["scope_id"] == 1
    assert result["preserve_access"] is True

