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
