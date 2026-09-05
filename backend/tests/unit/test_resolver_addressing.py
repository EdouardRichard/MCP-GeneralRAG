"""Unit test for slug and type:name addressing (007, T013)."""
from __future__ import annotations

import pytest

from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.services.retrieval_service import RetrievalService
from rag_mcp.utils.snowflake import generate_id


async def _make_scope(session, scope_type: str, name: str, slug: str) -> int:
    sid = generate_id()
    session.add(KnowledgeScope(
        scope_id=sid, scope_type=scope_type, name=name,
        domain_key="se-project", slug=slug, status="active",
    ))
    return sid


def _svc(session):
    return RetrievalService(session=session, qdrant_store=None, embedding_provider=None, reranker=None)


@pytest.mark.asyncio
async def test_slug_addressing(db_session):
    slug = "slug-" + str(generate_id())
    sid = await _make_scope(db_session, "public", "Slug Domain", slug)
    await db_session.commit()
    ids, err = await _svc(db_session).resolve_knowledge_scopes([], [slug])
    assert err is None and ids == [sid]


@pytest.mark.asyncio
async def test_slug_not_found_skips(db_session):
    slug = "slug-" + str(generate_id())
    await _make_scope(db_session, "public", "Slug Domain 2", slug)
    await db_session.commit()
    _, err = await _svc(db_session).resolve_knowledge_scopes([], ["slug-404-" + str(generate_id())])
    assert err is not None and err["code"] == "MISSING_KNOWLEDGE_SCOPE"


@pytest.mark.asyncio
async def test_type_name_unique_hit(db_session):
    name = "UniqueLaw-" + str(generate_id())
    sid = await _make_scope(db_session, "public", name, "slug-" + str(generate_id()))
    await db_session.commit()
    ids, err = await _svc(db_session).resolve_knowledge_scopes([], ["public:" + name])
    assert err is None and ids == [sid]


@pytest.mark.asyncio
async def test_type_name_ambiguous(db_session):
    name = "RegLib-" + str(generate_id())
    await _make_scope(db_session, "public", name, "slug-" + str(generate_id()))
    await _make_scope(db_session, "public", name, "slug-" + str(generate_id()))
    await db_session.commit()
    _, err = await _svc(db_session).resolve_knowledge_scopes([], ["public:" + name])
    assert err is not None and err["code"] == "AMBIGUOUS_DOMAIN_REF"
    assert len(err["candidates"]) == 2
    for c in err["candidates"]:
        assert "scope_type" in c and c["scope_type"] == "public"
        assert "domain_key" in c and "slug" in c


@pytest.mark.asyncio
async def test_type_name_invalid_type(db_session):
    name = "Legal-" + str(generate_id())
    await _make_scope(db_session, "public", name, "slug-" + str(generate_id()))
    await db_session.commit()
    _, err = await _svc(db_session).resolve_knowledge_scopes([], ["bogus:" + name])
    assert err is not None and err["code"] == "MISSING_KNOWLEDGE_SCOPE"
