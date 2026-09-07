"""Unit test for the evidence knowledge_scope_type fallback (010, T058).

FR-019 / Constitution XI: evidence must never default its
knowledge_scope_type to 'project'. When the knowledge_scopes row is
unavailable the fallback is the empty string — the same domain-neutral
fallback already used by entry._serialize_mcp_response,
state_machine._supplement_parent_context and retrieval_pipeline.enrich
(T056). This test pins the retrieval_service._build_evidence_items path.
"""
from __future__ import annotations

import pytest

from rag_mcp.services.retrieval_service import RetrievalService
from rag_mcp.utils.snowflake import generate_id


def _hit(scope_id: int) -> dict:
    """A minimal Qdrant-style search hit payload for one chunk."""
    return {
        "id": 1,
        "score": 0.9,
        "payload": {
            "chunk_id": "1",
            "version_id": "1",
            "knowledge_scope_id": str(scope_id),
            "source_id": "1",
            "position_path": "sec/1",
        },
    }


@pytest.fixture
async def builtin_profiles(db_session):
    """Ensure builtin domain profiles exist (KnowledgeScope.domain_key FK)."""
    from rag_mcp.services.domain_profile_service import DomainProfileService

    svc = DomainProfileService(db_session)
    await svc.sync_builtin_profiles()
    await db_session.commit()


@pytest.mark.asyncio
async def test_missing_scope_row_falls_back_to_empty_not_project(db_session):
    """A payload whose knowledge_scope_id has no knowledge_scopes row must
    yield knowledge_scope_type='' — never 'project' (T058, Constitution XI)."""
    svc = RetrievalService(db_session, None, None)
    missing_sid = generate_id()  # no knowledge_scopes row exists for this id
    items = await svc._build_evidence_items([_hit(missing_sid)])
    assert len(items) == 1
    assert items[0]["knowledge_scope_type"] == ""


@pytest.mark.asyncio
async def test_existing_scope_row_uses_real_type(db_session, builtin_profiles):
    """The real scope_type is used whenever the knowledge_scopes row exists
    (public stays 'public'); the empty fallback only covers a missing row."""
    from rag_mcp.models.knowledge_scope import KnowledgeScope

    sid = generate_id()
    db_session.add(KnowledgeScope(
        scope_id=sid, scope_type="public", name="T-fallback",
        domain_key="se-project", slug="t-fallback-" + str(sid), status="active",
    ))
    await db_session.flush()

    svc = RetrievalService(db_session, None, None)
    items = await svc._build_evidence_items([_hit(sid)])
    assert len(items) == 1
    assert items[0]["knowledge_scope_type"] == "public"
