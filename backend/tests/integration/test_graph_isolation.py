"""Integration test: graph isolation + no Project dependency (007, T016).

FR-018/SC-007: public graph_ready scopes get graph retrieval (no Project row
required) and cross-domain graph edge leakage = 0.
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
from sqlalchemy import text

from rag_mcp.services.retrieval_service import RetrievalService


@pytest.mark.asyncio
async def test_graph_scope_version_no_project_required(db_session):
    sid = await _mk_scope(db_session, "public")
    _, _, _ = await _mk_source_version_chunk(db_session, sid, graph_ready=True)
    await db_session.commit()
    svc = RetrievalService(db_session, None, None, None)
    version = await svc._graph_scope_version(sid)
    assert version == 1


@pytest.mark.asyncio
async def test_cross_domain_graph_edges_no_leak(db_session):
    from rag_mcp.graph.store.postgres_graph_store import PostgresGraphStore
    from rag_mcp.graph.store.base import GraphScope
    from rag_mcp.utils.snowflake import generate_id
    from rag_mcp.models.chunk import Chunk

    a = await _mk_scope(db_session, "public")
    b = await _mk_scope(db_session, "public")
    _, _, ca = await _mk_source_version_chunk(db_session, a, graph_ready=True)
    _, _, cb = await _mk_source_version_chunk(db_session, b, graph_ready=True)
    await db_session.flush()
    # edge from a -> b (cross-scope chunk) must NOT leak into scope a expansion
    eid = generate_id()
    await db_session.execute(text(
        "INSERT INTO graph_edge (edge_id, knowledge_scope_id, index_version, source_chunk_id, "
        "target_chunk_id, relation_type, direction, is_hard, version, parse_evidence) "
        "VALUES (:eid, :ksid, 1, :src, :tgt, 'calls', 'out', true, 1, '{}'::jsonb)"
    ), {"eid": eid, "ksid": a, "src": ca, "tgt": cb})
    await db_session.commit()

    store = PostgresGraphStore(db_session)
    candidates = await store.expand([ca], GraphScope(knowledge_scope_id=a, index_version=1), hop=1, budget=10)
    # The only edge targets chunk cb (belonging to scope b); but expansion filters by
    # knowledge_scope_id = a, so no candidates from scope b leak out.
    leaked = [c for c in candidates if c.knowledge_scope_id != a]
    assert len(leaked) == 0
