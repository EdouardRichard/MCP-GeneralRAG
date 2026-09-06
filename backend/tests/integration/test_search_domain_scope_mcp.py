"""MCP acceptance test for search_knowledge domain_scope success paths (007, T054).

SC-002/FR-008 + T046: the three domain_scope addressing forms (numeric
knowledge_scope_id, slug, type:name) resolve through the tool entry
(search_knowledge_core) and retrieve evidence from the addressed domain with a
schema-valid output; a mixed project_scope+domain_scope union de-duplicates and
does not amplify the result set. The resolver-level dedupe/boundary coverage
lives in test_resolver_boundaries.py; this file closes the tool-layer success
gap (previously only the entry ERROR path was covered by test_error_dual_track).
"""
from __future__ import annotations

import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from rag_mcp.mcp.search_knowledge import search_knowledge_core
from rag_mcp.models.chunk import Chunk
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.knowledge_source import KnowledgeSource
from rag_mcp.models.knowledge_version import KnowledgeVersion
from rag_mcp.utils.snowflake import generate_id

_CONTRACTS = Path(__file__).resolve().parents[3] / "specs/007-knowledge-domain-generalization/contracts"


def _merged_schema() -> dict:
    schema = copy.deepcopy(json.loads((_CONTRACTS / "mcp-search-output.schema.json").read_text(encoding="utf-8")))
    common = json.loads((_CONTRACTS / "common.schema.json").read_text(encoding="utf-8"))
    schema.setdefault("$defs", {})
    schema["$defs"].update(copy.deepcopy(common["definitions"]))
    prefixes = (common["$id"] + "#/definitions/", "common.schema.json#/definitions/")

    def _rewrite(obj):
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if k == "$ref" and isinstance(v, str):
                    for p in prefixes:
                        if v.startswith(p):
                            obj[k] = "#/$defs/" + v[len(p):]
                            break
                else:
                    _rewrite(v)
        elif isinstance(obj, list):
            for item in obj:
                _rewrite(item)

    _rewrite(schema)
    return schema


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


async def _mk_scope_chunk(session, scope_type="public", name=None, slug=None):
    sid = generate_id()
    session.add(KnowledgeScope(
        scope_id=sid, scope_type=scope_type, name=name or ("T-" + str(sid)),
        domain_key="se-project", slug=slug or ("s-" + str(sid)), status="active"))
    src_id = generate_id()
    session.add(KnowledgeSource(source_id=src_id, knowledge_scope_id=sid,
        filename="x.md", content_hash="h" + str(src_id), format="markdown",
        size_bytes=1, status="published"))
    vid = generate_id()
    session.add(KnowledgeVersion(version_id=vid, knowledge_scope_id=sid,
        version_number=1, capabilities={"dense_ready": True, "lexical_ready": True},
        status="published", graph_ready=False))
    cid = generate_id()
    session.add(Chunk(chunk_id=cid, source_id=src_id, version_id=vid,
        knowledge_scope_id=sid, content_text="domain scope evidence body",
        position_path="sec/1", chunk_type="section", start_line=1, end_line=1,
        token_count=10, embedding_model="bge-m3", index_version="bge-m3-v1",
        parent_chunk_id=None))
    return sid, vid, cid, src_id


def _hit(cid, vid, sid, src_id):
    return {"id": cid, "score": 0.9, "payload": {
        "chunk_id": str(cid), "version_id": str(vid),
        "knowledge_scope_id": str(sid), "source_id": str(src_id),
        "position_path": "sec/1", "index_version": "bge-m3-v1"}}


async def _search(db_session, project_scope, domain_scope, cid, vid, sid, src_id):
    @asynccontextmanager
    async def sf():
        yield db_session

    return await search_knowledge_core(
        query="domain scope evidence", project_scope=project_scope, top_k=5,
        task_context=None, session_factory=sf, domain_scope=domain_scope,
        qdrant_store=_MockQdrant([_hit(cid, vid, sid, src_id)]),
        embedding_provider=_FakeEmbedding())


@pytest.mark.asyncio
async def test_search_numeric_domain_scope_success(db_session):
    sid, vid, cid, src_id = await _mk_scope_chunk(db_session)
    await db_session.commit()
    resp = await _search(db_session, [], [str(sid)], cid, vid, sid, src_id)
    assert resp["completion_status"] == "complete", resp
    assert [e["knowledge_scope_id"] for e in resp["evidence"]] == [str(sid)]
    assert resp["evidence"][0]["knowledge_scope_type"] == "public"
    Draft202012Validator(_merged_schema()).validate(resp)


@pytest.mark.asyncio
async def test_search_slug_domain_scope_success(db_session):
    slug = "slug-" + str(generate_id())
    sid, vid, cid, src_id = await _mk_scope_chunk(db_session, slug=slug)
    await db_session.commit()
    resp = await _search(db_session, [], [slug], cid, vid, sid, src_id)
    assert resp["completion_status"] == "complete", resp
    assert [e["knowledge_scope_id"] for e in resp["evidence"]] == [str(sid)]
    Draft202012Validator(_merged_schema()).validate(resp)


@pytest.mark.asyncio
async def test_search_type_name_domain_scope_success(db_session):
    name = "Domain-" + str(generate_id())
    sid, vid, cid, src_id = await _mk_scope_chunk(db_session, name=name)
    await db_session.commit()
    resp = await _search(db_session, [], ["public:" + name], cid, vid, sid, src_id)
    assert resp["completion_status"] == "complete", resp
    assert [e["knowledge_scope_id"] for e in resp["evidence"]] == [str(sid)]
    Draft202012Validator(_merged_schema()).validate(resp)


@pytest.mark.asyncio
async def test_search_union_dedupe_no_amplification(db_session):
    slug = "slug-" + str(generate_id())
    sid, vid, cid, src_id = await _mk_scope_chunk(db_session, slug=slug)
    await db_session.commit()
    resp = await _search(db_session, [str(sid)], [slug], cid, vid, sid, src_id)
    assert resp["completion_status"] == "complete", resp
    # same scope referenced twice resolves once; single hit is not amplified
    assert len(resp["evidence"]) == 1
    assert resp["evidence"][0]["knowledge_scope_id"] == str(sid)
    Draft202012Validator(_merged_schema()).validate(resp)
