"""Unit test for query-side vocabulary compatibility (010, T024, VS-08).

Validates the research R6 clearing of three SE hard-codings:
  * expansion drops the hard-coded default relation set (None = no filter)
  * relation_types filtering is pattern-sanitized before entering SQL
  * map_graph_params falls back to the request-domain vocabulary (not None)
  * the inverse map aggregates every registered reciprocal pair (incl.
    references/referenced_by once cross_reference is registered)
"""
from __future__ import annotations

import pytest

from rag_mcp.graph.extractors.base import GraphExtractor, GraphExtractorRegistry
from rag_mcp.graph.store.base import GraphScope
from rag_mcp.graph.store.postgres_graph_store import PostgresGraphStore


class _RefExtractor(GraphExtractor):
    format = "markdown"
    relation_pairs = {"references": "referenced_by"}
    chunk_scope = "scope"

    def extract(self, source, chunks, scope):
        return []


class TestExpansionDefault:
    def test_no_bidirectional_default_constant(self):
        import rag_mcp.graph.expansion as expansion

        assert not hasattr(expansion, "_BIDIRECTIONAL_PAIRS"), (
            "expansion.py must not hard-code a default bidirectional pair set "
            "(010, R6.1: relation_types=None means no filter)"
        )


class TestRelationTypePatternSanitize:
    @pytest.mark.asyncio
    async def test_store_expand_rejects_invalid_pattern(self, db_session):
        store = PostgresGraphStore(db_session)
        with pytest.raises(ValueError):
            await store.expand(
                [1], GraphScope(100, 1), relation_types=["Bad-Type!"],
            )


class TestMapGraphParamsVocabFallback:
    def test_empty_directions_fall_back_to_request_vocab(self):
        from rag_mcp.orchestration.retrieval_pipeline import map_graph_params

        use_graph, relation_types = map_graph_params(
            signals=["graph"], relation_directions=None,
            valid_directions=["references", "referenced_by"],
        )
        assert use_graph is True
        assert set(relation_types) == {"references", "referenced_by"}

    def test_all_invalid_directions_fall_back_to_request_vocab(self):
        from rag_mcp.orchestration.retrieval_pipeline import map_graph_params

        use_graph, relation_types = map_graph_params(
            signals=["graph"], relation_directions=["bogus"],
            valid_directions=["references", "referenced_by"],
        )
        assert use_graph is True
        assert set(relation_types) == {"references", "referenced_by"}

    def test_se_project_vocab_matches_004_default(self):
        from rag_mcp.orchestration.retrieval_pipeline import map_graph_params

        se = ["calls", "called_by", "fk_references", "fk_referenced_by"]
        use_graph, relation_types = map_graph_params(
            signals=["graph"], relation_directions=None, valid_directions=se,
        )
        assert use_graph is True
        assert set(relation_types) == set(se)


class TestInverseMapAggregation:
    def test_inverse_map_includes_references_pair(self):
        reg = GraphExtractorRegistry([_RefExtractor])
        mapping = reg.inverse_relation_map()
        assert mapping["references"] == "referenced_by"
        assert mapping["referenced_by"] == "references"
