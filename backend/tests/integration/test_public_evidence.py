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


# ---------------------------------------------------------------------------
# 007 T051 (FR-016/SC-007/SC-005 blind spot): the FULL same-scope chain —
# search_knowledge returns evidence addressed by a numeric public scope ID,
# then get_evidence expands that evidence with locatable source metadata.
# The 1.0 defect broke exactly this chain on the evidence side.
# ---------------------------------------------------------------------------

class _FakeEmbedding:
    async def embed_query(self, q):
        return [0.1] * 8

    async def embed_texts(self, texts):
        return [[0.1] * 8 for _ in texts]

    def get_dimension(self):
        return 8


class _MockQdrant:
    def __init__(self, hits):
        self._hits = hits

    def collection_exists(self, name):
        return True

    def query_hybrid(self, collection, dense_vector, sparse_vector,
                     scope_ids, version_id, limit):
        return list(self._hits), list(self._hits)

    def search_dense_named(self, collection, vector, scope_ids=None,
                           version_id=None, limit=5):
        return list(self._hits)

    def search_sparse(self, collection, sparse_vector, scope_ids=None,
                      version_id=None, limit=5):
        return list(self._hits)

    def search(self, collection, vector, scope_ids, limit):
        return list(self._hits)


@pytest.mark.asyncio
async def test_public_search_to_evidence_chain(db_session):
    """SC-007: search -> get_evidence same-scope chain succeeds for a public
    domain (numeric public scope ID addressing; no Project row involved)."""
    from contextlib import asynccontextmanager

    from rag_mcp.mcp.search_knowledge import search_knowledge_core

    sid = await _mk_scope(db_session)
    src_id, vid, cid = await _mk_source_version_chunk(db_session, sid)
    await db_session.commit()

    hit = {
        "id": cid,
        "score": 0.9,
        "payload": {
            "chunk_id": str(cid),
            "version_id": str(vid),
            "knowledge_scope_id": str(sid),
            "source_id": str(src_id),
            "position_path": "sec/1",
            "index_version": "bge-m3-v1",
        },
    }

    @asynccontextmanager
    async def sf():
        yield db_session

    # 1. search_knowledge addressed by the numeric PUBLIC scope ID
    resp = await search_knowledge_core(
        query="public evidence body", project_scope=[str(sid)], top_k=5,
        task_context=None, session_factory=sf, qdrant_store=_MockQdrant([hit]),
        embedding_provider=_FakeEmbedding(),
    )
    assert resp["completion_status"] != "failed", resp
    assert resp["evidence"], "chain test requires at least one evidence item"
    ev = resp["evidence"][0]
    assert ev["knowledge_scope_id"] == str(sid)
    assert ev["knowledge_scope_type"] == "public"

    # 2. get_evidence expands the SAME evidence under the SAME scope
    result = await EvidenceService(db_session).get_evidence(
        evidence_id=str(ev["evidence_id"]), project_scopes=[str(sid)])
    assert result["status"] == "available"
    assert result["knowledge_scope_type"] == "public"
    assert result["full_content"] == "public evidence body"

    # 3. SC-005 locatability: source version and position resolvable to origin
    assert result["source_version"] == 1
    assert result["source_position"] == "sec/1"
    assert result["evidence_id"] == str(ev["evidence_id"])
