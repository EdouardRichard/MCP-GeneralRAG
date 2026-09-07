#!/usr/bin/env python3
"""Cross-reference benefit re-verification runner (011, T015, FR-011/SC-007).

Re-runs the 010 Q1=A benefit gate on the 011 enriched legal corpus: same-session
hybrid baseline arm (graph off) vs graph-enhanced arm (hybrid + cross-reference
expansion) over the benefit subset (legal_domain_eval_dataset.json entries with
is_structural_benefit=true). The gate is MRR & nDCG mean relative improvement
>= 3% + Recall non-decreasing + hard constraints all pass (010 FR-030).

Graph edges are extracted through the registry explicit trigger (the
cross_reference extractor), independent of the legal profile's graph
vocabulary — the disposition only flips the profile (T016), it does not change
the extractor (research R9). Zero measurable edges records "无可测量受益"
(Constitution III), handled as the not-passing branch.

Output: eval/legal_benefit_result.json — the vocabulary_disposition record and
the full cross_reference_benefit block, embedded into the legal domain baseline
report by run_domain_baseline.py --benefit-report.

Usage:
    python eval/run_legal_benefit.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_SRC = _REPO_ROOT / "backend" / "src"
for p in (_BACKEND_SRC, str(_REPO_ROOT / "eval"), str(_REPO_ROOT / "backend")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from sqlalchemy import select as sa_select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rag_mcp.config import get_settings  # noqa: E402
from rag_mcp.indexing.qdrant_client import QdrantStore  # noqa: E402
from rag_mcp.indexing.sparse_encoder import BM25SparseEncoder  # noqa: E402
from rag_mcp.models.chunk import Chunk  # noqa: E402
from rag_mcp.models.knowledge_version import KnowledgeVersion  # noqa: E402
from rag_mcp.services.ingestion_service import _derive_index_version  # noqa: E402
from run_cross_reference_comparison import _redeclare_graph  # noqa: E402
from run_domain_baseline import (  # noqa: E402
    resolve_domain_scopes,
    resolve_expected_heading,
)
from run_eval import (  # noqa: E402
    _EvalEmbeddingProvider,
    check_reproducibility,
    compute_metrics,
    run_single_eval,
)
from run_graph_comparison import (  # noqa: E402
    measure_hard_constraints,
    run_graph_eval,
)

logger = logging.getLogger(__name__)

_TOP_K = 5
_TOLERANCE = 0.01
_BENEFIT_DATASET = _REPO_ROOT / "eval" / "legal_domain_eval_dataset.json"
_OUTPUT = _REPO_ROOT / "eval" / "legal_benefit_result.json"


def _relative_improvement(base: float, enhanced: float) -> float:
    if base == 0:
        return 0.0
    return (enhanced - base) / base * 100.0


async def compute_cross_reference_benefit(
    dataset: list[dict],
    session_factory,
    qdrant_store: QdrantStore,
    embedding_provider,
    sparse_encoder: BM25SparseEncoder,
    hybrid_collection: str,
) -> dict:
    """Run the hybrid-vs-graph benefit comparison and return the benefit block.

    The block's vocabulary_disposition is the Q1=A disposition record (FR-011):
    enabled / kept_empty_r11 / no_measurable_benefit.
    """
    # Benefit subset = is_structural_benefit entries.
    subset = [e for e in dataset if e.get("is_structural_benefit")]
    if not subset:
        return {
            "baseline_metrics": {"recall_at_k": {"mean": 0, "min": 0, "max": 0},
                                 "mrr": {"mean": 0, "min": 0, "max": 0},
                                 "ndcg_at_k": {"mean": 0, "min": 0, "max": 0}},
            "graph_metrics": {"recall_at_k": {"mean": 0, "min": 0, "max": 0},
                              "mrr": {"mean": 0, "min": 0, "max": 0},
                              "ndcg_at_k": {"mean": 0, "min": 0, "max": 0}},
            "mrr_improvement_pct": 0.0,
            "ndcg_improvement_pct": 0.0,
            "recall_non_decreasing": True,
            "three_gate_pass": False,
            "vocabulary_disposition": "no_measurable_benefit",
        }

    # Re-declare cross-reference edges for every markdown scope in the subset
    # (registry explicit trigger — independent of the legal profile vocabulary).
    markdown_scope_ids = sorted({i for e in subset for i in e.get("domain_scope_ids", [])})
    total_edges = 0
    for scope_id in markdown_scope_ids:
        total_edges += await _redeclare_graph(session_factory, scope_id)
    logger.info("re-declared %d cross-reference edges across %d scope(s)",
                total_edges, len(markdown_scope_ids))

    # graph_triples: scope -> latest published version (post redeclaration).
    graph_triples: dict[int, dict] = {}
    async with session_factory() as session:
        for scope_id in markdown_scope_ids:
            v = (await session.execute(
                sa_select(KnowledgeVersion.version_number).where(
                    KnowledgeVersion.knowledge_scope_id == scope_id,
                    KnowledgeVersion.status == "published",
                ).order_by(KnowledgeVersion.version_number.desc())
            )).scalars().first()
            graph_triples[scope_id] = {"version_number": int(v or 1)}

    baseline_pq, baseline_metrics = await run_single_eval(
        subset, qdrant_store, embedding_provider, hybrid_collection, _TOP_K,
        mode="hybrid", sparse_encoder=sparse_encoder,
    )
    graph_pq, graph_metrics, leakage = await run_graph_eval(
        subset, qdrant_store, embedding_provider, hybrid_collection,
        session_factory, graph_triples, _TOP_K, sparse_encoder,
    )

    # Hard-constraint gate (cross-domain leakage=0 / schema=100% / locatable=100%).
    hard = await measure_hard_constraints(subset, graph_pq, leakage, session_factory)
    hard_all_passed = (
        leakage == 0
        and hard["schema_validity_rate"] >= 1.0
        and hard["source_locatability_rate"] >= 1.0
    )

    b = compute_metrics(baseline_pq, _TOP_K)
    g = compute_metrics(graph_pq, _TOP_K)
    mrr_imp = _relative_improvement(b["mrr"]["mean"], g["mrr"]["mean"])
    ndcg_imp = _relative_improvement(b["ndcg_at_k"]["mean"], g["ndcg_at_k"]["mean"])
    recall_non_decreasing = g["recall_at_k"]["mean"] >= b["recall_at_k"]["mean"]

    three_gate_pass = (
        mrr_imp >= 3.0 and ndcg_imp >= 3.0 and recall_non_decreasing and hard_all_passed
    )

    if total_edges == 0:
        disposition = "no_measurable_benefit"  # Constitution III: no fabricated benefit
    elif three_gate_pass:
        disposition = "enabled"
    else:
        disposition = "kept_empty_r11"

    def _block(m):
        return {"mean": round(m["mean"], 6), "min": round(m["min"], 6),
                "max": round(m["max"], 6)}

    return {
        "baseline_metrics": {
            "recall_at_k": _block(b["recall_at_k"]),
            "mrr": _block(b["mrr"]),
            "ndcg_at_k": _block(b["ndcg_at_k"]),
        },
        "graph_metrics": {
            "recall_at_k": _block(g["recall_at_k"]),
            "mrr": _block(g["mrr"]),
            "ndcg_at_k": _block(g["ndcg_at_k"]),
        },
        "mrr_improvement_pct": round(mrr_imp, 4),
        "ndcg_improvement_pct": round(ndcg_imp, 4),
        "recall_non_decreasing": recall_non_decreasing,
        "three_gate_pass": three_gate_pass,
        "vocabulary_disposition": disposition,
    }


async def run_legal_benefit(output_path: str = str(_OUTPUT)) -> int:
    settings = get_settings()
    with open(_BENEFIT_DATASET, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    embedding = _EvalEmbeddingProvider(settings.embedding_model)
    qdrant = QdrantStore(url=settings.qdrant_url)
    index_version = _derive_index_version(settings.embedding_model)
    hybrid_collection = f"chunks_hybrid_{index_version}"

    engine = create_async_engine(settings.database_url)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        await resolve_domain_scopes(dataset, session_factory)
        await resolve_expected_heading(dataset, session_factory)

        async with session_factory() as session:
            scope_ids = sorted({i for e in dataset if e.get("is_structural_benefit")
                                for i in e["domain_scope_ids"]})
            texts = (await session.execute(
                sa_select(Chunk.content_text)
                .where(Chunk.knowledge_scope_id.in_(scope_ids))
                .order_by(Chunk.chunk_id)
            )).scalars().all()
        sparse_encoder = BM25SparseEncoder()
        sparse_encoder.fit(list(texts))

        block = await compute_cross_reference_benefit(
            dataset, session_factory, qdrant, embedding, sparse_encoder,
            hybrid_collection,
        )

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(block, f, indent=2, ensure_ascii=False)

        logger.info("benefit block written to %s", out)
        logger.info(
            "MRR %+.2f%% nDCG %+.2f%% recall_non_decreasing=%s three_gate_pass=%s -> %s",
            block["mrr_improvement_pct"], block["ndcg_improvement_pct"],
            block["recall_non_decreasing"], block["three_gate_pass"],
            block["vocabulary_disposition"],
        )
        print(json.dumps(block, indent=2, ensure_ascii=False))
        return 0
    finally:
        await engine.dispose()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="011 legal cross-reference benefit gate.")
    p.add_argument("--output", "-o", default=str(_OUTPUT))
    return p.parse_args(argv)


async def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return await run_legal_benefit(args.output)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
