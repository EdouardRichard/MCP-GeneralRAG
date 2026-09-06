"""Integration test: get_evidence domain_scope addressing (007, T052).

FR-007 (get_evidence half)/US2-AC1 + Edge Cases: get_evidence resolves
domain_scope entries (numeric id / slug / type:name) and rejects evidence
that does not belong to any requested domain (scope_mismatch, per 1.0
scope-validation semantics). The search-side domain_scope error path is covered
by test_error_dual_track.py; this file closes the evidence-side gap.
"""
from __future__ import annotations

import pytest

from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.knowledge_source import KnowledgeSource
from rag_mcp.models.knowledge_version import KnowledgeVersion
from rag_mcp.models.chunk import Chunk
from rag_mcp.services.evidence_service import EvidenceService
from rag_mcp.utils.snowflake import generate_id


async def _mk_scope(session, scope_type="public", name=None, slug=None):
    sid = generate_id()
    session.add(KnowledgeScope(
        scope_id=sid, scope_type=scope_type,
        name=name or ("T-" + str(sid)), domain_key="se-project",
        slug=slug or ("s-" + str(sid)), status="active"))
    return sid


async def _mk_chunk(session, sid, content="evidence body"):
    src_id = generate_id()
    session.add(KnowledgeSource(source_id=src_id, knowledge_scope_id=sid,
        filename="x.md", content_hash="h" + str(src_id), format="markdown",
        size_bytes=1, status="published"))
    vid = generate_id()
    session.add(KnowledgeVersion(version_id=vid, knowledge_scope_id=sid,
        version_number=1,
        capabilities={"dense_ready": True, "lexical_ready": True},
        status="published", graph_ready=False))
    cid = generate_id()
    session.add(Chunk(chunk_id=cid, source_id=src_id, version_id=vid,
        knowledge_scope_id=sid, content_text=content, position_path="sec/1",
        chunk_type="section", start_line=1, end_line=1, token_count=10,
        embedding_model="bge-m3", index_version="bge-m3-v1",
        parent_chunk_id=None))
    return cid


@pytest.mark.asyncio
async def test_get_evidence_numeric_domain_scope(db_session):
    sid = await _mk_scope(db_session)
    cid = await _mk_chunk(db_session, sid)
    await db_session.commit()
    result = await EvidenceService(db_session).get_evidence(
        evidence_id=str(cid), project_scopes=[], domain_scopes=[str(sid)])
    assert result["status"] == "available"
    assert result["knowledge_scope_id"] == str(sid)
    assert result["knowledge_scope_type"] == "public"


@pytest.mark.asyncio
async def test_get_evidence_slug_domain_scope(db_session):
    sid = await _mk_scope(db_session, slug="regs-lib")
    cid = await _mk_chunk(db_session, sid)
    await db_session.commit()
    result = await EvidenceService(db_session).get_evidence(
        evidence_id=str(cid), project_scopes=[], domain_scopes=["regs-lib"])
    assert result["status"] == "available"
    assert result["knowledge_scope_id"] == str(sid)


@pytest.mark.asyncio
async def test_get_evidence_type_name_domain_scope(db_session):
    sid = await _mk_scope(db_session, name="法规库")
    cid = await _mk_chunk(db_session, sid)
    await db_session.commit()
    result = await EvidenceService(db_session).get_evidence(
        evidence_id=str(cid), project_scopes=[], domain_scopes=["public:法规库"])
    assert result["status"] == "available"
    assert result["knowledge_scope_id"] == str(sid)


@pytest.mark.asyncio
async def test_get_evidence_rejects_foreign_domain(db_session):
    """Edge case: evidence not belonging to any requested domain is rejected."""
    sid_a = await _mk_scope(db_session)
    cid_a = await _mk_chunk(db_session, sid_a)
    sid_b = await _mk_scope(db_session, slug="other-lib")
    await db_session.commit()
    result = await EvidenceService(db_session).get_evidence(
        evidence_id=str(cid_a), project_scopes=[], domain_scopes=["other-lib"])
    assert result["status"] == "scope_mismatch"
    assert result["error"]["code"] == "SCOPE_MISMATCH"


@pytest.mark.asyncio
async def test_get_evidence_union_project_and_domain(db_session):
    """project_scope and domain_scope resolve as a union; either owning scope passes."""
    sid_a = await _mk_scope(db_session, name="域A", slug="domain-a")
    cid_a = await _mk_chunk(db_session, sid_a)
    sid_b = await _mk_scope(db_session, name="域B", slug="domain-b")
    await db_session.commit()
    # request both scopes: union [a, b]; evidence a passes via domain-scope a
    result = await EvidenceService(db_session).get_evidence(
        evidence_id=str(cid_a), project_scopes=[str(sid_b)], domain_scopes=["domain-a"])
    assert result["status"] == "available"
