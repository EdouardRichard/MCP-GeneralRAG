import pytest


def test_scope_binding_resolves_path_with_longest_prefix_and_priority(tmp_path):
    from rag_mcp.services.scope_binding_service import ScopeBindingService

    root = tmp_path / "repo"
    child = root / "src"
    child.mkdir(parents=True)
    service = ScopeBindingService([
        {"binding_kind": "workdir_prefix", "binding_value": str(root), "knowledge_scope_id": 1, "priority": 0},
        {"binding_kind": "workdir_prefix", "binding_value": str(child), "knowledge_scope_id": 2, "priority": 0},
    ])
    assert service.resolve(f"path:{child / 'x.py'}").scope_id == 2


def test_scope_binding_rejects_relative_and_returns_candidates_for_ambiguity():
    from rag_mcp.services.scope_binding_service import ScopeBindingError, ScopeBindingService

    with pytest.raises(ScopeBindingError, match="MISSING_KNOWLEDGE_SCOPE"):
        ScopeBindingService([]).resolve("path:relative/file.py")
    service = ScopeBindingService([
        {"binding_kind": "workdir_prefix", "binding_value": "C:/repo", "knowledge_scope_id": 1, "priority": 1},
        {"binding_kind": "workdir_prefix", "binding_value": "C:/repo", "knowledge_scope_id": 2, "priority": 1},
    ])
    with pytest.raises(ScopeBindingError, match="AMBIGUOUS_DOMAIN_REF") as exc:
        service.resolve("path:C:/repo/a.py")
    assert exc.value.candidates == [1, 2]

