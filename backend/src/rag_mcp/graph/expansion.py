"""Graph expansion engine (T011).

Orchestrates graph expansion over the PostgresGraphStore with config-driven
defaults (hop, budget, direction), total-budget truncation, structure weight
decay (hard 1.0->0.5->0.25, soft 0.3, research sec 2), bidirectional default
(calls+called_by, fk_references+fk_referenced_by), and edge_path retention
(FR-008).

This engine is the layer between the store (T010) and the RRF fusion (T013):
it returns ranked GraphCandidate objects ready for the 3rd-retriever input.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from rag_mcp.config import get_settings
from rag_mcp.graph.store.base import GraphCandidate, GraphScope
from rag_mcp.graph.store.postgres_graph_store import PostgresGraphStore

logger = logging.getLogger(__name__)


class GraphExpansionEngine:
    """Config-driven graph expansion engine wrapping PostgresGraphStore.

    Applies guardrails from GraphConfig (hop_default, candidate_budget,
    direction_default) and returns ranked candidates for RRF 3rd input.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._store = PostgresGraphStore(session)
        self._settings = get_settings()
        self._cfg = self._settings.graph

    async def expand(
        self,
        start_chunk_ids: list[int],
        scope: GraphScope,
        hop: int | None = None,
        budget: int | None = None,
        direction: str | None = None,
        relation_types: list[str] | None = None,
    ) -> list[GraphCandidate]:
        """Expand from start chunks with config defaults.

        Args:
            start_chunk_ids: Seed chunks for expansion.
            scope: Isolation triple.
            hop: Max hops (default from config = 2).
            budget: Total candidate budget (default from config = 10).
            direction: 'bidirectional' (default), 'out', or 'in'.
            relation_types: Filter; None = all hard relations.

        Returns:
            Ranked GraphCandidate list with edge_path and graph_rank,
            truncated to budget, sorted by structure_weight descending.
        """
        hop = hop if hop is not None else self._cfg.hop_default
        budget = budget if budget is not None else self._cfg.candidate_budget
        direction = direction if direction is not None else self._cfg.direction_default

        # 010 (R6.1): no hard-coded default relation set — relation_types=None
        # means "no filter" (the write-side vocabulary validation already
        # guarantees every relation_type in the scope is domain-legal). This is
        # per-edge equivalent in the se-project scope (SC-001).

        candidates = await self._store.expand(
            start_chunk_ids=start_chunk_ids,
            scope=scope,
            hop=hop,
            budget=budget,
            direction=direction,
            relation_types=relation_types,
        )

        logger.info(
            "Expansion engine: start=%d chunks, hop=%d, budget=%d, dir=%s, "
            "candidates=%d",
            len(start_chunk_ids), hop, budget, direction, len(candidates),
        )
        return candidates
