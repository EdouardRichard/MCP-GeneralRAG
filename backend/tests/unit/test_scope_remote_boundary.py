import pytest

from rag_mcp.services.scope_binding_service import ScopeBindingError, ScopeBindingService


@pytest.mark.parametrize("reference", ["https://Example.com/Team/repo.git/", "git@example.com:Team/repo.git", "ssh://git@example.com/Team/repo.git"])
def test_remote_protocol_forms_resolve_the_same_explicit_binding(reference):
    service = ScopeBindingService([{"binding_kind": "git_remote", "binding_value": "https://example.com/Team/repo",
                                    "knowledge_scope_id": 7, "priority": 0, "status": "active"}])
    assert service.resolve("path:" + reference).scope_id == 7


def test_directory_binding_is_a_scoped_fallback_not_a_default(tmp_path):
    (tmp_path / "repo").mkdir()
    service = ScopeBindingService([{"binding_kind": "dir_name", "binding_value": "repo",
                                    "knowledge_scope_id": 7, "priority": 0}])
    assert service.resolve("path:" + str(tmp_path / "repo")).scope_id == 7
    with pytest.raises(ScopeBindingError, match="MISSING_KNOWLEDGE_SCOPE"):
        service.resolve("path:" + str(tmp_path / "other"))


def test_management_cannot_mutate_binding_projection_without_a_grant_event():
    service = ScopeBindingService([])
    with pytest.raises(PermissionError, match="grant"):
        service.add_binding({"knowledge_scope_id": 7}, actor="management")


def test_persisted_canonical_remote_is_idempotently_resolved():
    canonical = ScopeBindingService.normalize_remote("ssh://git@example.org:2222/team/repo.git")
    assert ScopeBindingService.normalize_remote(canonical) == canonical
    service = ScopeBindingService([{"binding_kind": "git_remote", "binding_value": canonical, "knowledge_scope_id": 7}])
    assert service.resolve("path:ssh://git@example.org:2222/team/repo.git").scope_id == 7
