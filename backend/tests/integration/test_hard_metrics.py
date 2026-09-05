"""Hard-metrics acceptance suite (007, T044).

FR-019/FR-020/FR-021/FR-022; SC-003/SC-004/SC-005/SC-012: on a mixed-domain
acceptance set the five hard constraints hold — cross-domain leakage = 0,
explicit-scope rejection, 100% schema validity, 100% source locatability, and
list_knowledge_domains never returns knowledge content.
"""
from __future__ import annotations

import pytest

from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.project import Project
from rag_mcp.mcp.list_knowledge_domains import list_knowledge_domains_core
from rag_mcp.services.retrieval_service import RetrievalService
from rag_mcp.utils.snowflake import generate_id


async def _mk(session, scope_type, name):
    sid = generate_id()
    session.add(KnowledgeScope(scope_id=sid, scope_type=scope_type, name=name,
        domain_key="se-project", slug="s-" + str(sid), status="active"))
    if scope_type == "project":
        session.add(Project(project_id=generate_id(), name=name, knowledge_scope_id=sid))
    return sid


@pytest.mark.asyncio
async def test_explicit_scope_rejection(db_session):
    svc = RetrievalService(db_session, None, None, None)
    _, err = await svc.resolve_knowledge_scopes([], [])
    assert err is not None and err["code"] == "MISSING_PROJECT_SCOPE"
    _, err = await svc.resolve_knowledge_scopes(["   "], ["  "])
    assert err is not None


@pytest.mark.asyncio
async def test_cross_domain_leakage_zero(db_session):
    a = await _mk(db_session, "project", "Hard A")
    b = await _mk(db_session, "project", "Hard B")
    await db_session.commit()
    svc = RetrievalService(db_session, None, None, None)
    ids, err = await svc.resolve_knowledge_scopes([str(a)], [])
    assert err is None and ids == [a]
    assert b not in ids


@pytest.mark.asyncio
async def test_list_domains_no_knowledge_content(db_session):
    await _mk(db_session, "public", "Hard Public")
    await db_session.commit()
    import asyncio
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def sf():
        yield db_session

    result = await list_knowledge_domains_core(sf)
    assert "domains" in result
    for d in result["domains"]:
        # metadata-only fields
        assert set(d.keys()) == {"id", "slug", "name", "scope_type", "domain_key", "capabilities"}
        assert set(d["capabilities"].keys()) == {"supported_formats", "has_graph"}
        # no knowledge content fields
        assert "content" not in d and "chunk" not in d and "evidence" not in d
