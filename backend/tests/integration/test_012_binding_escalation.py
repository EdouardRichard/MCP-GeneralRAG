import pytest


def test_non_management_binding_write_is_rejected():
    from rag_mcp.services.scope_binding_service import ScopeBindingService

    service = ScopeBindingService([])
    with pytest.raises(PermissionError):
        service.add_binding({"binding_kind": "workdir_prefix", "binding_value": "C:/x", "knowledge_scope_id": 1}, actor="mcp")

