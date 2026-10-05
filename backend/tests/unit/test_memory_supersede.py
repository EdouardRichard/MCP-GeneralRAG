import pytest


def test_supersede_requires_same_scope_active_target():
    from rag_mcp.services.memory_validators import validate_supersede

    with pytest.raises(ValueError, match="MEMORY_SUPERSEDE_TARGET_INVALID"):
        validate_supersede({"scope_id": 1, "target": {"scope_id": 2, "status": "active"}})

