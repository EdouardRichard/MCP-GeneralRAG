#!/usr/bin/env python3
"""Cross-reference benefit comparison runner (010, T039, VS-10/SC-002).

Builds a legal-domain scope, ingests eval/corpora/legal/*.md, declares
graph_ready, then runs the hybrid baseline (graph off) vs the graph-enhanced
path (cross-reference expansion on) over the benefit subset
(eval/cross_reference_eval_dataset.json), reusing the 004 comparison
infrastructure (GraphComparisonRunner / run_single_eval / search_graph_enhanced).

The SC-002 gate (MRR & nDCG mean relative improvement >= 3% + Recall non-
decreasing) decides enters_default_path; a failure is reported (research R11
declarative remedy keeps the feature deliverable).
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

from sqlalchemy import select as sa_select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from rag_mcp.config import get_settings
from rag_mcp.indexing.qdrant_client import QdrantStore
from rag_mcp.indexing.sparse_encoder import BM25SparseEncoder
from rag_mcp.models.chunk import Chunk
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.knowledge_version import KnowledgeVersion
from rag_mcp.utils.snowflake import generate_id
from run_eval import (  # noqa: E402
    _EvalEmbeddingProvider,
    compute_metrics,
    run_single_eval,
)
from run_graph_comparison import (  # noqa: E402
    search_graph_enhanced,
    _derive_index_version,
)

logger = logging.getLogger(__name__)


async def _ensure_legal_scope(session_factory) -> int:
    """Create (or reuse) a legal-domain public scope for the eval corpus."""
    settings = get_settings()
    scope_id = generate_id()
    async with session_factory() as session:
        await session.execute(sa_text(
            "INSERT INTO knowledge_scopes (scope_id, scope_type, name, slug, "
            "status, domain_key) VALUES (:sid, 'public', :name, :slug, "
            "'active', 'legal')"
        ), {"sid": scope_id, "name": "legal-eval", "slug": "legal-eval-" + str(scope_id)})
        await session.commit()
    return scope_id


async def _ingest_corpus(session_factory, scope_id: int) -> None:
    """Ingest every eval/corpora/legal/*.md into the legal scope (graph_ready)."""
    from rag_mcp.services.ingestion_service import IngestionService

    settings = get_settings()
    embedding = _EvalEmbeddingProvider(settings.embedding_model)
    qdrant = QdrantStore(url=settings.qdrant_url)
    data_root = Path(settings.data_root)
    if not data_root.exists():
        data_root = _REPO_ROOT / "backend" / data_root

    corpus_dir = _REPO_ROOT / "eval" / "corpora" / "legal"
    files = sorted(corpus_dir.glob("*.md"))
    if not files:
        raise RuntimeError(f"no legal corpus found in {corpus_dir}")

    async with session_factory() as session:
        svc = IngestionService(session, embedding, qdrant)
        for path in files:
            source_id = generate_id()
            raw = path.read_bytes()
            save_dir = data_root / str(scope_id) / str(source_id)
            save_dir.mkdir(parents=True, exist_ok=True)
            (save_dir / path.name).write_bytes(raw)
            await session.execute(sa_text(
                "INSERT INTO knowledge_sources (source_id, knowledge_scope_id, "
                "filename, content_hash, format, size_bytes, status) "
                "VALUES (:sid, :ksid, :fn, :ch, 'markdown', :sz, 'uploaded')"
            ), {"sid": source_id, "ksid": scope_id, "fn": path.name,
                "ch": "hash-" + str(source_id), "sz": len(raw)})
            await session.commit()
            # Ingest WITHOUT graph_ready: a reference-only file may produce no
            # cross-reference edges; graph_ready is declared afterwards on the
            # versions that actually have hard edges.
            await svc.ingest(source_id, graph_ready=False)
        await session.commit()

    # Declare graph_ready on published versions that have hard edges (>0).
    async with session_factory() as session:
        await session.execute(sa_text(
            "UPDATE knowledge_versions SET graph_ready = true, "
            "capabilities = capabilities || '{\"graph_ready\": true}'::jsonb "
            "WHERE knowledge_scope_id = :ksid AND status = 'published' "
            "AND EXISTS (SELECT 1 FROM graph_edge e "
            "WHERE e.knowledge_scope_id = knowledge_versions.knowledge_scope_id "
            "AND e.index_version = knowledge_versions.version_number)"
        ), {"ksid": scope_id})
        await session.commit()


async def _redeclare_graph(session_factory, scope_id: int) -> int:
    """Re-extract all cross-reference edges at the latest published version.

    The per-source ingestion writes edges at each source's own version_number;
    the graph retrieval reads a single version, so re-extract every source's
    cross-reference edges against the latest version (deterministic rebuild,
    research R10.3 / R12.3).
    """
    from rag_mcp.graph.extractors.base import GraphExtractorRegistry
    from rag_mcp.graph.store.base import GraphScope
    from rag_mcp.graph.store.postgres_graph_store import PostgresGraphStore
    from rag_mcp.models.knowledge_source import KnowledgeSource
    from rag_mcp.models.knowledge_version import KnowledgeVersion
    from rag_mcp.services.ingestion_service import _basename, _extract_heading_from_path

    async with session_factory() as session:
        version = (await session.execute(
            sa_select(KnowledgeVersion).where(
                KnowledgeVersion.knowledge_scope_id == scope_id,
                KnowledgeVersion.status == "published",
            ).order_by(KnowledgeVersion.version_number.desc())
        )).scalars().first()
        if version is None:
            return 0
        version_number = version.version_number
        scope = GraphScope(scope_id, version_number)

        sources = (await session.execute(
            sa_select(KnowledgeSource).where(
                KnowledgeSource.knowledge_scope_id == scope_id,
                KnowledgeSource.status == "published",
                KnowledgeSource.format == "markdown",
            )
        )).scalars().all()

        # Build the scope chunk index (all published markdown chunks).
        chunks = []
        for src in sources:
            rows = (await session.execute(
                sa_select(Chunk).where(Chunk.source_id == src.source_id)
            )).scalars().all()
            for c in rows:
                chunks.append({
                    "chunk_id": c.chunk_id,
                    "heading": _extract_heading_from_path(c.position_path or ""),
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "filename": _basename(src.filename),
                })

        store = PostgresGraphStore(session)
        await store.delete_graph_relations(scope)

        registry = GraphExtractorRegistry.instance()
        total = 0
        for src in sources:
            raw_path = Path(get_settings().data_root) / str(scope_id) / str(src.source_id) / src.filename
            if not raw_path.exists():
                raw_path = _REPO_ROOT / "backend" / Path(get_settings().data_root) / str(scope_id) / str(src.source_id) / src.filename
            if not raw_path.exists():
                continue
            raw_text = raw_path.read_bytes().decode("utf-8", errors="replace")
            # mark the current source's chunks as is_current for anchor resolution
            current_basename = _basename(src.filename)
            scope_chunks = [dict(c, is_current=(c["filename"] == current_basename)) for c in chunks]
            for extractor in registry.discover("markdown", {"references": ["out"], "referenced_by": ["in"]}):
                edges = extractor.extract(raw_text, scope_chunks, scope)
                for edge in edges:
                    edge["version"] = version_number
                total += await store.write_edges(
                    edges, scope,
                    allowed_relation_types=["references", "referenced_by"],
                )
        await session.commit()
        return total


async def _resolve_expected(dataset, session_factory, scope_id: int) -> None:
    """Resolve each entry's expected_evidence_ids from expected_heading."""
    async with session_factory() as session:
        rows = (await session.execute(
            sa_select(Chunk.chunk_id, Chunk.position_path).where(
                Chunk.knowledge_scope_id == scope_id
            )
        )).all()
        for entry in dataset:
            heading = entry.get("expected_heading") or ""
            match = next((str(cid) for cid, pos in rows
                          if heading and heading in (pos or "")), None)
            if match is None:
                # fall back to the chunk whose position_path ends with heading
                match = next((str(cid) for cid, pos in rows
                              if (pos or "").rstrip("# ").endswith(heading.rstrip("# "))), None)
            entry["expected_evidence_ids"] = [match] if match else []
            entry["project_scope"] = [str(scope_id)]
            entry.pop("expected_heading", None)


def _relative_improvement(base: float, graph: float) -> float:
    if base == 0:
        return 0.0
    return (graph - base) / base * 100.0


async def run_cross_reference_comparison(dataset_path: str, output_path: str) -> int:
    settings = get_settings()
    ds_path = Path(dataset_path)
    with open(ds_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    embedding_provider = _EvalEmbeddingProvider(settings.embedding_model)
    qdrant_store = QdrantStore(url=settings.qdrant_url)
    index_version = _derive_index_version(settings.embedding_model)
    hybrid_collection = f"chunks_hybrid_{index_version}"

    engine = create_async_engine(settings.database_url)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    scope_id = await _ensure_legal_scope(session_factory)
    await _ingest_corpus(session_factory, scope_id)
    await _redeclare_graph(session_factory, scope_id)
    await _resolve_expected(dataset, session_factory, scope_id)

    # Sparse encoder over the legal scope's published chunks.
    async with session_factory() as session:
        texts = (await session.execute(
            sa_select(Chunk.content_text).where(
                Chunk.knowledge_scope_id == scope_id
            ).order_by(Chunk.chunk_id)
        )).scalars().all()
    sparse_encoder = BM25SparseEncoder()
    sparse_encoder.fit(list(texts))

    # Graph retrieval reads the latest published version (post redeclaration).
    async with session_factory() as session:
        latest_version = (await session.execute(
            sa_select(KnowledgeVersion.version_number).where(
                KnowledgeVersion.knowledge_scope_id == scope_id,
                KnowledgeVersion.status == "published",
            ).order_by(KnowledgeVersion.version_number.desc())
        )).scalars().first() or 1
    graph_triples = {scope_id: {"version_number": latest_version}}

    baseline_per_query, baseline_metrics = await run_single_eval(
        dataset, qdrant_store, embedding_provider, hybrid_collection, 5,
        mode="hybrid", sparse_encoder=sparse_encoder,
    )

    graph_per_query = []
    async with session_factory() as session:
        for i, entry in enumerate(dataset):
            result = await search_graph_enhanced(
                query=entry["query"],
                project_scope_ids=[scope_id],
                qdrant_store=qdrant_store,
                embedding_provider=embedding_provider,
                collection_name=hybrid_collection,
                session=session,
                graph_triples=graph_triples,
                top_k=5,
                sparse_encoder=sparse_encoder,
            )
            graph_per_query.append({
                "query_index": i,
                "query": entry["query"],
                "expected_evidence_ids": entry["expected_evidence_ids"],
                "retrieved_evidence_ids": result["evidence_ids"],
                "scores": result["scores"],
                "latency_ms": result["latency_ms"],
                "status": result["status"],
            })

    baseline = compute_metrics(baseline_per_query, 5)
    graph = compute_metrics(graph_per_query, 5)

    mrr_improvement = _relative_improvement(baseline["mrr"]["mean"], graph["mrr"]["mean"])
    ndcg_improvement = _relative_improvement(baseline["ndcg_at_k"]["mean"], graph["ndcg_at_k"]["mean"])
    recall_non_decreasing = graph["recall_at_k"]["mean"] >= baseline["recall_at_k"]["mean"]

    enters_default_path = (
        mrr_improvement >= 3.0 and ndcg_improvement >= 3.0 and recall_non_decreasing
    )

    report = {
        "report_type": "cross_reference_comparison",
        "scope_id": scope_id,
        "num_queries": len(dataset),
        "baseline_metrics": {
            "recall_at_k": baseline["recall_at_k"],
            "mrr": baseline["mrr"],
            "ndcg_at_k": baseline["ndcg_at_k"],
        },
        "graph_metrics": {
            "recall_at_k": graph["recall_at_k"],
            "mrr": graph["mrr"],
            "ndcg_at_k": graph["ndcg_at_k"],
        },
        "mrr_improvement_pct": round(mrr_improvement, 4),
        "ndcg_improvement_pct": round(ndcg_improvement, 4),
        "recall_non_decreasing": recall_non_decreasing,
        "enters_default_path": enters_default_path,
        "per_query": graph_per_query,
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info("cross_reference comparison written to %s", out)
    logger.info("MRR %.4f -> %.4f (%.2f%%), nDCG %.4f -> %.4f (%.2f%%), recall_non_decreasing=%s",
                baseline["mrr"]["mean"], graph["mrr"]["mean"], mrr_improvement,
                baseline["ndcg_at_k"]["mean"], graph["ndcg_at_k"]["mean"], ndcg_improvement,
                recall_non_decreasing)
    logger.info("enters_default_path=%s", enters_default_path)

    await engine.dispose()
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Cross-reference benefit comparison (010).")
    p.add_argument("--dataset", "-d", default="eval/cross_reference_eval_dataset.json")
    p.add_argument("--output", "-o", default="eval/cross_reference_comparison_report.json")
    return p.parse_args(argv)


async def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    return await run_cross_reference_comparison(args.dataset, args.output)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
