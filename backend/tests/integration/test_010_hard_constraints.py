"""Hard-constraint acceptance test for cross-reference edges (010, T043).

SC-004/SC-005/SC-012: every cross-reference hard edge carries a complete
parse_evidence (source_format/extractor/locator), references/referenced_by are
paired (no missing mirror), and the MCP graph annotation schema accepts a
references hard edge (the SC-004 precondition).
"""
from __future__ import annotations

import jsonschema
import pytest
from sqlalchemy import text

from rag_mcp.services.domain_profile_service import DomainProfileService
from rag_mcp.utils.snowflake import generate_id
from tests.contract._graph_schema_helper import load_schema
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


@pytest.fixture
async def legal_scope(db_session):
    svc = DomainProfileService(db_session)
    await svc.sync_builtin_profiles()
    await db_session.commit()

    from rag_mcp.models.knowledge_scope import KnowledgeScope

    domain_key = await setup_legal_eval_domain(db_session)
    sid = generate_id()
    db_session.add(KnowledgeScope(
        scope_id=sid, scope_type="public", name="T-" + str(sid),
        domain_key=domain_key, slug="hard-" + str(sid), status="active",
    ))
    await db_session.flush()
    source_id = generate_id()
    await upload_source_file(db_session, sid, source_id, "law.md", _LEGAL_MD, "markdown")
    await db_session.commit()

    from rag_mcp.services.ingestion_service import IngestionService

    svc = IngestionService(db_session, FakeEmbeddingProvider(), MockQdrantStore())
    await svc.ingest(source_id, graph_ready=True)
    return sid


@pytest.mark.asyncio
async def test_cross_reference_edges_parse_evidence_complete(db_session, legal_scope):
    rows = (await db_session.execute(text(
        "SELECT parse_evidence FROM graph_edge WHERE knowledge_scope_id = :k"
    ), {"k": legal_scope})).fetchall()
    assert rows, "expected cross-reference edges"
    for (pe,) in rows:
        assert pe.get("source_format") == "markdown"
        assert pe.get("extractor") == "cross_reference"
        assert pe.get("locator", "").startswith("xref:")


@pytest.mark.asyncio
async def test_cross_reference_edges_paired(db_session, legal_scope):
    rows = (await db_session.execute(text(
        "SELECT relation_type, source_chunk_id, target_chunk_id "
        "FROM graph_edge WHERE knowledge_scope_id = :k"
    ), {"k": legal_scope})).fetchall()
    refs = {(s, t) for (rt, s, t) in rows if rt == "references"}
    rby = {(s, t) for (rt, s, t) in rows if rt == "referenced_by"}
    assert refs, "expected references edges"
    assert len(refs) == len(rby), "paired references/referenced_by required"
    for (s, t) in refs:
        assert (t, s) in rby, "missing referenced_by mirror"


def test_graph_annotation_schema_accepts_references():
    schema = load_schema("mcp-search-output.graph-annotation.schema.json")
    resp = {
        "completion_status": "complete",
        "evidence": [
            {
                "evidence_id": "1",
                "content_excerpt": "excerpt",
                "source_version": 1,
                "source_position": "## 第一条 总则",
                "knowledge_scope_id": "100",
                "knowledge_scope_type": "public",
                "relevance_score": 0.5,
                "relation": {
                    "type": "hard",
                    "relation_type": "references",
                    "is_hard": True,
                    "edge_id": "1",
                    "parse_evidence": {
                        "source_format": "markdown",
                        "locator": "xref:clause:ref=第二条:marker=依据:line=5",
                        "extractor": "cross_reference",
                    },
                },
            }
        ],
        "request_id": "req-1",
    }
    jsonschema.validate(resp, schema)


def test_graph_annotation_schema_rejects_other_hard():
    schema = load_schema("mcp-search-output.graph-annotation.schema.json")
    rel = {
        "type": "hard",
        "relation_type": "other_hard",
        "is_hard": True,
        "edge_id": "1",
        "parse_evidence": {
            "source_format": "java", "locator": "x", "extractor": "e",
        },
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(rel, schema)
