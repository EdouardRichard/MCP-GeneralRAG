"""Unit test for graph_edge wide-pattern relation_type (010, T017, VS-02).

Validates the ORM validates rules after the 0074 wide-pattern relaxation:
references is now legal, other_hard is retired, inferred is forbidden, and
out-of-pattern values are rejected (FR-008/FR-010/FR-011). Also asserts the
store chokepoint rejects reserved words even when the domain vocabulary
declares them (R5/FR-010).
"""
from __future__ import annotations

import pytest

from rag_mcp.graph.models import GraphEdge
from rag_mcp.graph.store.base import GraphScope
from rag_mcp.graph.store.postgres_graph_store import PostgresGraphStore


def _edge(relation_type: str) -> GraphEdge:
    return GraphEdge(
        edge_id=1, knowledge_scope_id=100, index_version=1,
        source_chunk_id=300, target_chunk_id=301,
        relation_type=relation_type, direction="out", is_hard=True, version=1,
        parse_evidence={"source_format": "markdown", "locator": "xref:internal", "extractor": "cross_reference"},
    )


class TestOrmWidePattern:
    def test_references_is_legal(self):
        assert _edge("references").relation_type == "references"

    def test_referenced_by_is_legal(self):
        assert _edge("referenced_by").relation_type == "referenced_by"

    def test_other_hard_rejected(self):
        with pytest.raises(ValueError):
            _edge("other_hard")

    def test_inferred_rejected(self):
        with pytest.raises(ValueError):
            _edge("inferred")

    def test_out_of_pattern_rejected(self):
        with pytest.raises(ValueError):
            _edge("Invalid-Type!")

    def test_orm_validates_does_not_enforce_vocab(self):
        # FR-009 / research R5 layering: the ORM model only enforces the wide
        # pattern + reserved-word blacklist; domain-vocabulary membership is
        # enforced at PostgresGraphStore.write_edges (the store chokepoint),
        # not here (the model has no domain context). A pattern-valid,
        # non-reserved value that is out of any domain vocabulary still
        # constructs at the ORM layer — write_edges is the vocabulary gate.
        assert _edge("arbitrary_edge").relation_type == "arbitrary_edge"


class TestStoreReservedWordChokepoint:
    @pytest.mark.asyncio
    async def test_write_edges_rejects_other_hard_even_in_vocab(self, db_session):
        store = PostgresGraphStore(db_session)
        edge = {"source_chunk_id": 1, "target_chunk_id": 2,
                "relation_type": "other_hard", "direction": "out", "version": 1}
        with pytest.raises(ValueError):
            await store.write_edges([edge], GraphScope(100, 1), ["other_hard"])

    @pytest.mark.asyncio
    async def test_write_edges_rejects_inferred_even_in_vocab(self, db_session):
        store = PostgresGraphStore(db_session)
        edge = {"source_chunk_id": 1, "target_chunk_id": 2,
                "relation_type": "inferred", "direction": "out", "version": 1}
        with pytest.raises(ValueError):
            await store.write_edges([edge], GraphScope(100, 1), ["inferred"])

    @pytest.mark.asyncio
    async def test_write_edges_rejects_out_of_vocab(self, db_session):
        store = PostgresGraphStore(db_session)
        edge = {"source_chunk_id": 1, "target_chunk_id": 2,
                "relation_type": "references", "direction": "out", "version": 1}
        with pytest.raises(ValueError):
            await store.write_edges([edge], GraphScope(100, 1), ["calls"])
