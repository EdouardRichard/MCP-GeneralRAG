"""Unit test for the unified resolver boundaries (007, T012)."""
from __future__ import annotations

import pytest

from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.project import Project
from rag_mcp.services.retrieval_service import RetrievalService
from rag_mcp.utils.snowflake import generate_id


async def _make_scope(session, scope_type: str, name: str) -> tuple[int, int | None, str]:
    sid = generate_id()
    slug = "scope-" + str(sid)
    session.add(KnowledgeScope(
        scope_id=sid, scope_type=scope_type, name=name,
        domain_key="se-project", slug=slug, status="active",
    ))
    if scope_type == "project":
        pid = generate_id()
        session.add(Project(project_id=pid, name=name, knowledge_scope_id=sid, alias=None, repo_path=None))
        return sid, pid, slug
    return sid, None, slug


def _svc(session):
    return RetrievalService(session=session, qdrant_store=None, embedding_provider=None, reranker=None)


@pytest.mark.asyncio
async def test_union_and_dedupe(db_session):
    sid, pid, _ = await _make_scope(db_session, "project", "Union Project")
    pub_sid, _, _ = await _make_scope(db_session, "public", "Union Public")
    await db_session.commit()
    svc = _svc(db_session)
    ids, err = await svc.resolve_knowledge_scopes([str(pid)], [str(sid)])
    assert err is None
    assert ids == [sid]
    ids, err = await svc.resolve_knowledge_scopes([str(pid)], [str(pub_sid)])
    assert err is None
    assert set(ids) == {sid, pub_sid}


@pytest.mark.asyncio
async def test_empty_and_whitespace_skip(db_session):
    sid, pid, _ = await _make_scope(db_session, "project", "Skip Project")
    await db_session.commit()
    svc = _svc(db_session)
    ids, err = await svc.resolve_knowledge_scopes(["  ", str(pid)], ["", "   "])
    assert err is None
    assert ids == [sid]


@pytest.mark.asyncio
async def test_missing_dual_track_codes(db_session):
    svc = _svc(db_session)
    _, err = await svc.resolve_knowledge_scopes(["  "], [" "])
    assert err is not None and err["code"] == "MISSING_PROJECT_SCOPE"
    _, err = await svc.resolve_knowledge_scopes(["no-such-alias-xyz"], [])
    assert err is not None and err["code"] == "MISSING_PROJECT_SCOPE"
    _, err = await svc.resolve_knowledge_scopes([], ["no-such-slug-xyz"])
    assert err is not None and err["code"] == "MISSING_KNOWLEDGE_SCOPE"


@pytest.mark.asyncio
async def test_mixed_ambiguous_project_with_domain(db_session):
    token = str(generate_id())
    _, pid_a, _ = await _make_scope(db_session, "project", "Mixed A")
    _, pid_b, _ = await _make_scope(db_session, "project", "Mixed B")
    await db_session.execute(
        Project.__table__.update().where(Project.project_id == pid_a).values(repo_path="/a/" + token)
    )
    await db_session.execute(
        Project.__table__.update().where(Project.project_id == pid_b).values(repo_path="/b/" + token)
    )
    await db_session.commit()
    svc = _svc(db_session)
    _, err = await svc.resolve_knowledge_scopes([token], ["some-domain-ref"])
    assert err is not None and err["code"] == "AMBIGUOUS_DOMAIN_REF"
