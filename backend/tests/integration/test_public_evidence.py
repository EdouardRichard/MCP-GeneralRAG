"""Integration test: public evidence expansion (007, T014).

FR-016/SC-007: get_evidence resolves a numeric public scope ID directly (no
Project row), so search -> get_evidence same-scope chain works for public domains.
"""
async def _mk_scope(session, scope_type="public"):
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    from rag_mcp.utils.snowflake import generate_id
    sid = generate_id()
    session.add(KnowledgeScope(scope_id=sid, scope_type=scope_type, name="T-" + str(sid),
        domain_key="se-project", slug="s-" + str(sid), status="active"))
    return sid

async def _mk_source_version_chunk(session, sid, graph_ready=False):
    from rag_mcp.models.knowledge_source import KnowledgeSource
    from rag_mcp.models.knowledge_version import KnowledgeVersion
    from rag_mcp.models.chunk import Chunk
    from rag_mcp.utils.snowflake import generate_id
    src_id = generate_id()
    session.add(KnowledgeSource(source_id=src_id, knowledge_scope_id=sid, filename="x.md",
        content_hash="h" + str(src_id), format="markdown", size_bytes=1, status="published"))
    vid = generate_id()
    session.add(KnowledgeVersion(version_id=vid, knowledge_scope_id=sid, version_number=1,
        capabilities={"dense_ready": True, "lexical_ready": True, "graph_ready": graph_ready},
        status="published", graph_ready=graph_ready))
    cid = generate_id()
    session.add(Chunk(chunk_id=cid, source_id=src_id, version_id=vid, knowledge_scope_id=sid,
        content_text="public evidence body", position_path="sec/1", chunk_type="section",
        start_line=1, end_line=1, token_count=10, embedding_model="bge-m3",
        index_version="bge-m3-v1", parent_chunk_id=None))
    return src_id, vid, cid

import pytest

from rag_mcp.services.evidence_service import EvidenceService


@pytest.mark.asyncio
async def test_resolve_public_scope_id_directly(db_session):
    sid = await _mk_scope(db_session)
    await db_session.commit()
    svc = EvidenceService(db_session)
    ids = await svc._resolve_scope_ids([str(sid)])
    assert ids == [sid]


@pytest.mark.asyncio
async def test_get_evidence_public_scope_available(db_session):
    sid = await _mk_scope(db_session)
    _, _, cid = await _mk_source_version_chunk(db_session, sid)
    await db_session.commit()
    svc = EvidenceService(db_session)
    result = await svc.get_evidence(evidence_id=str(cid), project_scopes=[str(sid)])
    assert result["status"] == "available"
    assert result["knowledge_scope_type"] == "public"
