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


@pytest.mark.parametrize("remote", ["https://EXAMPLE.org/team/repo.git/", "ssh://git@example.org/team/repo.git",
    "git@example.org:team/repo.git", "https://example.org:443/team/repo", "ssh://example.org:22/team/repo"])
def test_git_remote_equivalent_spellings_resolve_one_explicit_binding(remote):
    from rag_mcp.services.scope_binding_service import ScopeBindingService
    service = ScopeBindingService([{"binding_kind": "git_remote", "binding_value": "example.org/team/repo",
                                   "knowledge_scope_id": 7, "priority": 0}])
    assert service.resolve("path:" + remote).scope_id == 7


@pytest.mark.parametrize("remote", ["ssh://[", "https://example.org:invalid/team/repo",
    "https://example.org:65536/team/repo", "https://example.org/team/../repo",
    "https://example.org/team/repo?token=x", "https://example.org/team/repo#branch"])
def test_malformed_remote_returns_scope_error_without_fallback(remote):
    from rag_mcp.services.scope_binding_service import ScopeBindingError, ScopeBindingService
    with pytest.raises(ScopeBindingError, match="MISSING_KNOWLEDGE_SCOPE"):
        ScopeBindingService([]).resolve("path:" + remote)


def test_path_boundary_disabled_binding_priority_and_case(tmp_path):
    import os
    from rag_mcp.services.scope_binding_service import ScopeBindingError, ScopeBindingService
    root = tmp_path / "repo"
    root.mkdir()
    service = ScopeBindingService([
        {"binding_kind": "workdir_prefix", "binding_value": str(root), "knowledge_scope_id": 1, "priority": 1},
        {"binding_kind": "workdir_prefix", "binding_value": str(root), "knowledge_scope_id": 2, "priority": 2},
        {"binding_kind": "workdir_prefix", "binding_value": str(root), "knowledge_scope_id": 3, "priority": 3, "status": "disabled"},
    ])
    assert service.resolve("path:" + str(root / "sub" / ".." / "file")).scope_id == 2
    if os.name == "nt":
        assert service.resolve("path:" + str(root).upper()).scope_id == 2
    with pytest.raises(ScopeBindingError, match="MISSING_KNOWLEDGE_SCOPE"):
        service.resolve("path:" + str(tmp_path / "repo-other"))


def test_real_filesystem_alias_resolves_to_target_scope(tmp_path):
    import os
    import subprocess
    from rag_mcp.services.scope_binding_service import ScopeBindingService
    target, alias = tmp_path / "target", tmp_path / "alias"
    target.mkdir()
    if os.name == "nt":
        subprocess.run(["powershell", "-NoProfile", "-Command", "New-Item", "-ItemType", "Junction",
                        "-Path", str(alias), "-Target", str(target)], check=True, capture_output=True)
    else:
        alias.symlink_to(target, target_is_directory=True)
    service = ScopeBindingService([{"binding_kind": "workdir_prefix", "binding_value": str(target),
                                   "knowledge_scope_id": 9, "priority": 0}])
    assert service.resolve("path:" + str(alias / "file")).scope_id == 9

