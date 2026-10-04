def test_management_api_permission_boundary():
    from rag_mcp.api.memory import management_action

    assert management_action("browse", actor="management")["authorized"] is True
    assert management_action("rollback", actor="mcp")["authorized"] is False
