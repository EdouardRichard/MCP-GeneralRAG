"""Unit test: agentic evidence scope_type uses real scope type (007, T015).

FR-017: retrieval_pipeline enrichment carries the real knowledge_scope_type
(public != "project"); project domains are unchanged.
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

from rag_mcp.orchestration.retrieval_pipeline import AgenticRetrievalPipeline


@pytest.mark.asyncio
async def test_public_scope_type_enrichment(db_session):
    sid = await _mk_scope(db_session, "public")
    _, vid, cid = await _mk_source_version_chunk(db_session, sid)
    await db_session.commit()
    pipeline = AgenticRetrievalPipeline(session_factory=None, qdrant_store=None, embedding_provider=None)
    candidate = {"chunk_id": str(cid), "payload": {"chunk_id": str(cid), "version_id": str(vid),
        "knowledge_scope_id": str(sid), "source_id": "1", "position_path": "sec/1"}}
    enriched = await pipeline._enrich_candidates(db_session, [candidate], [sid])
    assert enriched[0]["knowledge_scope_type"] == "public"


@pytest.mark.asyncio
async def test_project_scope_type_enrichment(db_session):
    sid = await _mk_scope(db_session, "project")
    _, vid, cid = await _mk_source_version_chunk(db_session, sid)
    await db_session.commit()
    pipeline = AgenticRetrievalPipeline(session_factory=None, qdrant_store=None, embedding_provider=None)
    candidate = {"chunk_id": str(cid), "payload": {"chunk_id": str(cid), "version_id": str(vid),
        "knowledge_scope_id": str(sid), "source_id": "1", "position_path": "sec/1"}}
    enriched = await pipeline._enrich_candidates(db_session, [candidate], [sid])
    assert enriched[0]["knowledge_scope_type"] == "project"
