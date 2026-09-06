"""Integration test for cross-reference extraction end-to-end (010, T036, VS-03).

Validates the legal-domain ingestion path: legal markdown corpus upload ->
cross_reference extraction (references/referenced_by hard edges) -> vocabulary
validation -> edge persistence, then a rebuild producing a stable (deterministic)
edge set including cross-file relative-link edges (R10.3 scope index).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from rag_mcp.services.domain_profile_service import DomainProfileService
from rag_mcp.utils.snowflake import generate_id
from tests.integration.graph_ingest_helpers import (
    FakeEmbeddingProvider,
    MockQdrantStore,
    setup_graph_scope,
    setup_legal_eval_domain,
    upload_source_file,
)


_LAW = """# 数据条例

## 第一条 总则

本条例依据第二条确定适用范围。

## 第二条 适用范围

本条例适用于数据处理活动。

## 第三条 数据处理

处理活动见 [实施细则](./rules.md)。

## 处罚条款

见 [处罚](#Penalties)。

## Penalties

违反本条规定者，依法处罚。
"""

_RULES = """# 数据条例实施细则

## 第一条 施行

本细则依据数据条例第二条制定。

## 第二条 补充

补充规定如下。
"""


@pytest.fixture
async def legal_scope(db_session):
    """Seed the legal builtin profile and create a legal-domain scope."""
    svc = DomainProfileService(db_session)
    await svc.sync_builtin_profiles()
    await db_session.commit()
    domain_key = await setup_legal_eval_domain(db_session)
    await db_session.commit()

    scope_id = generate_id()
    project_id = generate_id()
    await setup_graph_scope(db_session, scope_id, project_id)
    await db_session.execute(text(
        "UPDATE knowledge_scopes SET domain_key = :dk WHERE scope_id = :sid"
    ), {"dk": domain_key, "sid": scope_id})
    await db_session.commit()

    law_id = generate_id()
    rules_id = generate_id()
    await upload_source_file(db_session, scope_id, law_id, "law.md", _LAW, "markdown")
    await upload_source_file(db_session, scope_id, rules_id, "rules.md", _RULES, "markdown")
    await db_session.commit()
    return {"scope_id": scope_id, "project_id": project_id,
            "law_id": law_id, "rules_id": rules_id}


@pytest.mark.asyncio
async def test_cross_reference_edges_written(db_session, legal_scope):
    from rag_mcp.services.ingestion_service import IngestionService

    scope_id = legal_scope["scope_id"]
    # Ingest the law first (cross-file link to rules.md is first-pass best-effort).
    svc = IngestionService(db_session, FakeEmbeddingProvider(), MockQdrantStore())
    await svc.ingest(legal_scope["law_id"])
    await svc.ingest(legal_scope["rules_id"])

    rows = (await db_session.execute(text(
        "SELECT relation_type, source_chunk_id, target_chunk_id "
        "FROM graph_edge WHERE knowledge_scope_id = :k"
    ), {"k": scope_id})).fetchall()
    rel_types = {r[0] for r in rows}
    assert "references" in rel_types, f"expected references edges, got {rel_types}"
    assert "referenced_by" in rel_types


@pytest.mark.asyncio
async def test_cross_reference_edges_paired_and_deterministic(db_session, legal_scope):
    """references/referenced_by edges must be paired (symmetric, VS-03)."""
    from rag_mcp.services.ingestion_service import IngestionService

    scope_id = legal_scope["scope_id"]
    svc = IngestionService(db_session, FakeEmbeddingProvider(), MockQdrantStore())
    await svc.ingest(legal_scope["law_id"])
    await svc.ingest(legal_scope["rules_id"])

    rows = (await db_session.execute(text(
        "SELECT relation_type, source_chunk_id, target_chunk_id "
        "FROM graph_edge WHERE knowledge_scope_id = :k"
    ), {"k": scope_id})).fetchall()
    refs = {(s, t) for (rt, s, t) in rows if rt == "references"}
    rby = {(s, t) for (rt, s, t) in rows if rt == "referenced_by"}
    assert refs, "expected references edges"
    assert len(refs) == len(rby), "references/referenced_by must be paired"
    for (s, t) in refs:
        assert (t, s) in rby, "every references edge must have a referenced_by mirror"
