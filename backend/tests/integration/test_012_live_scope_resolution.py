import importlib.util

import pytest
from sqlalchemy import select

from rag_mcp.models.knowledge_scope import KnowledgeScope


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
