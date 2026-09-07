"""Integration test for public/generic domain graph path (010, T041, US4, VS-06).

007 removed the Project-row requirement for graph isolation (knowledge_scope_id
is the sole isolation key). This test validates end-to-end that a public + legal
domain (no Project row) with a declared graph vocabulary and hard edges can
declare graph_ready, while a public + generic domain (empty vocabulary) cannot
(SC-008/SC-009, FR-019/FR-020).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from rag_mcp.services.domain_profile_service import DomainProfileService
from rag_mcp.utils.snowflake import generate_id
from tests.integration.graph_ingest_helpers import (
    FakeEmbeddingProvider,
    MockQdrantStore,
    setup_legal_eval_domain,
    upload_source_file,
)


_LEGAL_MD = """# 数据条例

## 第一条 总则

本条例依据第二条确定适用范围。

## 第二条 适用范围

本条例适用于境内数据处理活动。
"""

_GENERIC_MD = """# 通用文档

## 概述

这是一份没有图关系的普通文档。
"""


async def _public_scope(session, domain_key):
    from rag_mcp.models.knowledge_scope import KnowledgeScope

    sid = generate_id()
    session.add(KnowledgeScope(
        scope_id=sid, scope_type="public", name="T-" + str(sid),
        domain_key=domain_key, slug="pub-" + str(sid), status="active",
    ))
    await session.flush()
    return sid


@pytest.fixture
async def builtin_profiles(db_session):
    svc = DomainProfileService(db_session)
    await svc.sync_builtin_profiles()
    await db_session.commit()


@pytest.mark.asyncio
async def test_public_legal_graph_ready_publishable(db_session, builtin_profiles):
    from rag_mcp.services.ingestion_service import IngestionService

    domain_key = await setup_legal_eval_domain(db_session)
    await db_session.commit()
    sid = await _public_scope(db_session, domain_key)
    source_id = generate_id()
    await upload_source_file(db_session, sid, source_id, "law.md", _LEGAL_MD, "markdown")
    await db_session.commit()

    svc = IngestionService(db_session, FakeEmbeddingProvider(), MockQdrantStore())
    await svc.ingest(source_id, graph_ready=True)

    rows = (await db_session.execute(text(
        "SELECT relation_type FROM graph_edge WHERE knowledge_scope_id = :k"
    ), {"k": sid})).fetchall()
    assert rows, "public+legal scope must produce cross-reference hard edges"
    rel_types = {r[0] for r in rows}
    assert "references" in rel_types and "referenced_by" in rel_types

    # The published version must be graph_ready (hard edges > 0).
    graph_ready = (await db_session.execute(text(
        "SELECT graph_ready FROM knowledge_versions WHERE knowledge_scope_id = :k"
    ), {"k": sid})).scalars().all()
    assert any(graph_ready), "public+legal version must declare graph_ready"


@pytest.mark.asyncio
async def test_public_generic_cannot_declare_graph_ready(db_session, builtin_profiles):
    from rag_mcp.services.ingestion_service import IngestionService

    sid = await _public_scope(db_session, "generic")
    source_id = generate_id()
    await upload_source_file(db_session, sid, source_id, "doc.md", _GENERIC_MD, "markdown")
    await db_session.commit()

    svc = IngestionService(db_session, FakeEmbeddingProvider(), MockQdrantStore())
    # generic domain has an empty graph vocabulary -> no extractor -> 0 hard
    # edges -> graph_ready declaration must be refused (FR-020/SC-009).
    with pytest.raises(ValueError):
        await svc.ingest(source_id, graph_ready=True)


@pytest.mark.asyncio
async def test_public_legal_graph_expansion_and_isolation(db_session, builtin_profiles):
    """US4 AC1/AC3: graph-enhanced traversal works for a Project-less public
    scope and never leaks across scopes (knowledge_scope_id is the sole graph
    isolation key; no Project row is required, FR-019/FR-023/SC-003/SC-008)."""
    from rag_mcp.graph.expansion import GraphExpansionEngine
    from rag_mcp.graph.store.base import GraphScope
    from rag_mcp.services.ingestion_service import IngestionService

    domain_key = await setup_legal_eval_domain(db_session)
    await db_session.commit()

    # Scope A: public + legal (references/referenced_by), no Project row.
    sid_a = await _public_scope(db_session, domain_key)
    src_a = generate_id()
    await upload_source_file(db_session, sid_a, src_a, "law_a.md", _LEGAL_MD, "markdown")
    await db_session.commit()
    await IngestionService(db_session, FakeEmbeddingProvider(), MockQdrantStore())\
        .ingest(src_a, graph_ready=True)

    # Scope B: an isolation peer public + legal scope with the same corpus.
    sid_b = await _public_scope(db_session, domain_key)
    src_b = generate_id()
    await upload_source_file(db_session, sid_b, src_b, "law_b.md", _LEGAL_MD, "markdown")
    await db_session.commit()
    await IngestionService(db_session, FakeEmbeddingProvider(), MockQdrantStore())\
        .ingest(src_b, graph_ready=True)

    rows_a = (await db_session.execute(text(
        "SELECT chunk_id, position_path FROM chunks WHERE knowledge_scope_id = :k"
    ), {"k": sid_a})).fetchall()
    first_a = next(cid for cid, pos in rows_a if pos and "第一条" in pos)
    second_a = next(cid for cid, pos in rows_a if pos and "第二条" in pos)
    chunk_ids_b = {
        cid for (cid,) in (await db_session.execute(text(
            "SELECT chunk_id FROM chunks WHERE knowledge_scope_id = :k"
        ), {"k": sid_b})).fetchall()
    }

    engine = GraphExpansionEngine(db_session)
    results = await engine.expand([first_a], GraphScope(sid_a, 1), hop=2, budget=20)
    reached = {r.chunk_id for r in results}

    # AC1: cross-reference traversal reaches the referenced clause for a
    # public scope with no Project row.
    assert second_a in reached, "cross-reference traversal must reach the referenced clause"
    # AC3: graph expansion must not surface any chunk from the peer scope.
    assert reached.isdisjoint(chunk_ids_b), "graph expansion must not leak across scopes"
