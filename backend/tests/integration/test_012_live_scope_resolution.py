import importlib.util
import json
import os
import subprocess
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import select

from rag_mcp.models.knowledge_scope import KnowledgeScope


def _create_directory_alias(target, alias):
    if os.name == "nt":
        subprocess.run(["powershell", "-NoProfile", "-Command", "New-Item", "-ItemType", "Junction",
                        "-Path", str(alias), "-Target", str(target)], check=True, capture_output=True)
    else:
        alias.symlink_to(target, target_is_directory=True)


async def _bind_scope(session, binding_kind, binding_value):
    from rag_mcp.services.memory_service import MemoryService
    from rag_mcp.utils.snowflake import generate_id

    sid = generate_id()
    session.add(KnowledgeScope(scope_id=sid, name=f"path-{uuid4()}", slug=f"path-{sid}",
                               scope_type="project", domain_key="generic"))
    await session.commit()
    await MemoryService(session).govern("binding", scope_id=sid, actor="management", reason="scope path acceptance",
                                        binding_kind=binding_kind, binding_value=binding_value)
    return sid


@pytest.mark.asyncio
async def test_real_numeric_slug_and_typed_name_resolve_the_same_scope(db_session):
    module_name = "rag_mcp.services.scope_resolver"
    assert importlib.util.find_spec(module_name) is not None, "memory tools have no scope resolver"
    from rag_mcp.services.scope_resolver import MemoryScopeResolver
    from rag_mcp.services.scope_binding_service import ScopeBindingError
    scopes = (await db_session.execute(select(KnowledgeScope).where(KnowledgeScope.status == "active"))).scalars().all()
    scope = next(row for row in scopes if sum(s.name == row.name and s.scope_type == row.scope_type for s in scopes) == 1)
    resolver = MemoryScopeResolver(db_session)
    for reference in (str(scope.scope_id), scope.slug, f"{scope.scope_type}:{scope.name}"):
        assert await resolver.resolve(reference) == scope.scope_id
    with pytest.raises(ScopeBindingError, match="MISSING_KNOWLEDGE_SCOPE"):
        await resolver.resolve("missing-memory-scope-for-012")
    with pytest.raises(ScopeBindingError, match="MISSING_KNOWLEDGE_SCOPE"):
        await resolver.resolve_many([])


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing_child", "missing_dir_name", "deleted_target", "dangling_alias"])
async def test_real_missing_filesystem_paths_return_dual_channel_scope_errors(db_session, tmp_path, case):
    from rag_mcp.mcp import create_mcp_server
    from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider
    from rag_mcp.services.scope_binding_service import ScopeBindingError
    from rag_mcp.services.scope_resolver import MemoryScopeResolver
    from rag_mcp.utils.snowflake import generate_id

    root = tmp_path / "repo"
    root.mkdir()
    requested = root / f"missing-{uuid4()}"
    kind, value = "workdir_prefix", str(root)
    if case == "missing_dir_name":
        kind, value = "dir_name", requested.name
    elif case == "deleted_target":
        requested = root
    elif case == "dangling_alias":
        requested = tmp_path / "alias"
        _create_directory_alias(root, requested)
    await _bind_scope(db_session, kind, value)
    if case in {"deleted_target", "dangling_alias"}:
        root.rmdir()

    @asynccontextmanager
    async def sessions():
        yield db_session

    server = create_mcp_server(session_factory=sessions, embedding_provider=LocalCPUEmbeddingProvider(), mode="reader")
    result = await server.call_tool("recall_memory", {"scope_ref": [f"path:{requested}"], "memory_ids": [generate_id()]})
    assert result.isError
    assert result.structuredContent["error"]["code"] == "MISSING_KNOWLEDGE_SCOPE"
    assert json.loads(result.content[0].text) == result.structuredContent
    assert result.structuredContent["request_id"]
    with pytest.raises(ScopeBindingError, match="MISSING_KNOWLEDGE_SCOPE"):
        await MemoryScopeResolver(db_session).resolve(f"path:{requested}")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["directory", "file", "alias", "remote"])
async def test_real_existing_filesystem_paths_aliases_and_remotes_resolve(db_session, tmp_path, case):
    from rag_mcp.services.scope_resolver import MemoryScopeResolver

    root = tmp_path / "repo"
    root.mkdir()
    requested = str(root)
    kind, value = "workdir_prefix", str(root)
    if case == "file":
        file_path = root / "file.py"
        file_path.touch()
        requested = str(file_path)
    elif case == "alias":
        alias = tmp_path / "alias"
        _create_directory_alias(root, alias)
        requested = str(alias)
    elif case == "remote":
        kind, value = "git_remote", f"https://example.org/scope/{uuid4()}.git"
        requested = value
    sid = await _bind_scope(db_session, kind, value)
    assert await MemoryScopeResolver(db_session).resolve(f"path:{requested}") == sid
