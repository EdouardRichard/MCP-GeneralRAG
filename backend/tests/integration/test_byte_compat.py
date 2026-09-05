"""Byte-compat test: legacy project_scope candidate shape (007, T028).

FR-009/SC-001: project_scope-only ambiguity keeps the 1.0 candidate shape
(project_id/name/alias/repo_path) and legacy AMBIGUOUS_PROJECT_REF code.
"""
from __future__ import annotations

import pytest

from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.project import Project
from rag_mcp.services.retrieval_service import RetrievalService
from rag_mcp.utils.snowflake import generate_id


@pytest.mark.asyncio
async def test_project_only_ambiguous_candidates_legacy_shape(db_session):
    token = str(generate_id())
    for i in range(2):
        sid = generate_id()
        db_session.add(KnowledgeScope(scope_id=sid, scope_type="project", name=f"Proj {i}",
            domain_key="se-project", slug="s-" + str(sid), status="active"))
        db_session.add(Project(project_id=generate_id(), name=f"Proj {i}", knowledge_scope_id=sid,
            alias=None, repo_path=f"/{token}/repo{i}"))
    await db_session.commit()
    svc = RetrievalService(db_session, None, None, None)
    _, err = await svc.resolve_knowledge_scopes([token], [])
    assert err is not None
    assert err["code"] == "AMBIGUOUS_PROJECT_REF"
    for c in err["candidates"]:
        assert "project_id" in c and "name" in c and "alias" in c and "repo_path" in c
        assert "scope_type" not in c and "domain_key" not in c and "slug" not in c
