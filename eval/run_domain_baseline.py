#!/usr/bin/env python3
"""Domain baseline runner (011, T012, FR-008/FR-009, research R1).

Thin entry that reuses the 001/002 evaluation kernels (run_single_eval /
compute_metrics / check_reproducibility / measure_hard_constraints) to produce
the two non-binding domain-baseline anchor reports (dense + hybrid arms, same
session). Differences from the legacy runners (R1):

1. dataset addressing: domain_scope entries (slug / numeric scope id) resolve
   to numeric scope sets;
2. expected anchor: expected_heading structural anchors (not runtime chunk IDs);
3. report: the 011 domain-baseline report shape (no enters_default_path).

The dense arm runs dense-only search over the hybrid collection's named
"dense" vector (search_dense_named) because the 011 corpora are ingested into
the hybrid collection only. The hybrid arm reuses run_single_eval(mode=hybrid).

History artifact discipline (US3 AC5): the report is never overwritten — the
runner refuses to write over an existing report file.

Usage:
    python eval/run_domain_baseline.py --dataset eval/generic_domain_eval_dataset.json \
        --output eval/generic_domain_baseline_report.json --domain-key personal
    python eval/run_domain_baseline.py --dataset eval/legal_domain_eval_dataset.json \
        --output eval/legal_domain_baseline_report.json --domain-key legal
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from rag_mcp.models.knowledge_scope import KnowledgeScope  # noqa: E402
from rag_mcp.services.ingestion_service import _derive_index_version  # noqa: E402
from run_eval import (  # noqa: E402
    _EvalEmbeddingProvider,
    check_reproducibility,
    compute_metrics,
    run_single_eval,
)
from run_graph_comparison import measure_hard_constraints  # noqa: E402

logger = logging.getLogger(__name__)

_TOP_K = 5
_TOLERANCE = 0.01


# ---------------------------------------------------------------------------
# Dataset addressing + expected-anchor resolution (R1/R2)
# ---------------------------------------------------------------------------

async def resolve_domain_scopes(dataset: list[dict], session_factory) -> None:
    """Resolve domain_scope slugs (or numeric scope IDs) to scope-id sets.

    Sets entry["domain_scope_ids"] (ints) and entry["project_scope"] (strings,
    the legacy field the 001/002 kernels read). Fails loud on any unresolvable
    slug so an anchor cannot silently dangle (Constitution I).
    """
    slugs: set[str] = set()
    numeric: set[int] = set()
    for entry in dataset:
        for s in entry.get("domain_scope", []):
            if str(s).isdigit():
                numeric.add(int(s))
            else:
                slugs.add(str(s))

    slug_to_id: dict[str, int] = {}
    if slugs:
        async with session_factory() as session:
            rows = (await session.execute(
                sa_select(KnowledgeScope.scope_id, KnowledgeScope.slug).where(
                    KnowledgeScope.slug.in_(list(slugs))
                )
            )).all()
        slug_to_id = {r.slug: int(r.scope_id) for r in rows}
        missing = slugs - set(slug_to_id)
        if missing:
            raise RuntimeError(
                f"unresolvable domain_scope slugs: {sorted(missing)}"
            )

    for entry in dataset:
        ids = []
        for s in entry.get("domain_scope", []):
            ids.append(int(s) if str(s).isdigit() else slug_to_id[str(s)])
        entry["domain_scope_ids"] = ids
        entry["project_scope"] = [str(i) for i in ids]


async def resolve_expected_heading(dataset: list[dict], session_factory) -> None:
    """Resolve each entry's expected_heading into expected_evidence_ids.

    Structural anchors are matched as a substring of the chunk position_path
    (title-path tail / locator prefix), mirroring the 010 cross-reference
    runner's heading resolution (R1). Anchors never depend on runtime chunk
    IDs (R2 / SC-010).
    """
    scope_ids = sorted({i for e in dataset for i in e.get("domain_scope_ids", [])})
    if not scope_ids:
        return
    async with session_factory() as session:
        rows = (await session.execute(
            sa_select(Chunk.chunk_id, Chunk.position_path, Chunk.knowledge_scope_id)
            .where(Chunk.knowledge_scope_id.in_(scope_ids))
        )).all()
    by_scope: dict[int, list[tuple[int, str]]] = {}
    for cid, pos, sid in rows:
        by_scope.setdefault(int(sid), []).append((int(cid), pos or ""))

    for entry in dataset:
        heading = entry.get("expected_heading") or ""
        candidates: list[tuple[int, str]] = []
        for sid in entry.get("domain_scope_ids", []):
            candidates.extend(by_scope.get(sid, []))
        match = next((cid for cid, pos in candidates if heading and heading in pos), None)
        if match is None:
            match = next(
                (cid for cid, pos in candidates
                 if (pos or "").rstrip("# ").endswith(heading.rstrip("# "))),
                None,
            )
        entry["expected_evidence_ids"] = [str(match)] if match is not None else []


# ---------------------------------------------------------------------------
# Dense-only arm over the hybrid collection's named "dense" vector (R1)
# ---------------------------------------------------------------------------

async def run_dense_named_eval(
    dataset: list[dict],
    qdrant_store: QdrantStore,
    embedding_provider: Any,
    collection: str,
    top_k: int,
) -> tuple[list[dict], dict]:
    per_query: list[dict] = []
    for i, entry in enumerate(dataset):
        qv = await embedding_provider.embed_query(entry["query"])
        start = time.perf_counter()
        hits = qdrant_store.search_dense_named(
            collection, qv, scope_ids=entry["domain_scope_ids"], limit=top_k,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        per_query.append({
            "query_index": i,
            "query": entry["query"],
            "project_scope": entry["project_scope"],
            "expected_evidence_ids": entry.get("expected_evidence_ids", []),
            "retrieved_evidence_ids": [str(h["id"]) for h in hits],
            "scores": [h["score"] for h in hits],
            "latency_ms": elapsed_ms,
            "status": "ok",
            "candidate_details": [],
            "evidence_items": [],
        })
        if (i + 1) % 10 == 0 or i == len(dataset) - 1:
            logger.info("  dense-named processed %d/%d", i + 1, len(dataset))
    return per_query, compute_metrics(per_query, top_k)


def _metric_block(m: dict) -> dict:
    return {"mean": round(m["mean"], 6), "min": round(m["min"], 6),
            "max": round(m["max"], 6)}


def _latency_block(m: dict) -> dict:
    return {"p50": round(m["p50"], 6), "p95": round(m["p95"], 6),
            "mean": round(m.get("mean", 0.0), 6)}


def _rank(per_query_entry: dict) -> tuple[int | None, float | None]:
    expected = set(per_query_entry.get("expected_evidence_ids") or [])
    for r, rid in enumerate(per_query_entry.get("retrieved_evidence_ids", []), start=1):
        if rid in expected:
            return r, per_query_entry["scores"][r - 1]
    return None, None


def build_per_query_comparison(
    dataset: list[dict], dense_pq: list[dict], hybrid_pq: list[dict]
) -> list[dict]:
    out: list[dict] = []
    for i, entry in enumerate(dataset):
        d_rank, d_score = _rank(dense_pq[i])
        h_rank, _ = _rank(hybrid_pq[i])
        # candidate-level scores for the matched hybrid candidate
        cand = next(
            (c for c in hybrid_pq[i].get("candidate_details", [])
             if c.get("chunk_id") in set(entry.get("expected_evidence_ids") or [])),
            None,
        )
        rank_improved = bool(h_rank is not None and (d_rank is None or h_rank < d_rank))
        out.append({
            "query_index": i,
            "query": entry["query"],
            "domain_scope": entry["domain_scope"],
            "expected_heading": entry.get("expected_heading", ""),
            "format": entry.get("format"),
            "dense_rank": d_rank,
            "hybrid_rank": h_rank,
            "dense_score": round(d_score, 6) if d_score is not None else None,
            "hybrid_dense_score": round(cand["dense_score"], 6) if cand and cand.get("dense_score") is not None else None,
            "hybrid_sparse_score": round(cand["sparse_score"], 6) if cand and cand.get("sparse_score") is not None else None,
            "hybrid_fused_score": round(cand["fused_score"], 6) if cand and cand.get("fused_score") is not None else None,
            "hybrid_rerank_score": round(cand["rerank_score"], 6) if cand and cand.get("rerank_score") is not None else None,
            "rank_improved": rank_improved,
        })
    return out


def _validate_report_against_schema(report: dict, report_type: str) -> None:
    """Validate the produced report against its 011 contract schema (FR-009)."""
    import jsonschema

    contracts = _REPO_ROOT / "specs" / "011-generic-domain-evaluation" / "contracts"
    with open(contracts / "domain-baseline-common.schema.json", "r", encoding="utf-8") as f:
        common = json.load(f)
    schema_name = (
        "legal-domain-baseline-report.schema.json"
        if report_type == "legal_domain_baseline"
        else "generic-domain-baseline-report.schema.json"
    )
    with open(contracts / schema_name, "r", encoding="utf-8") as f:
        schema = json.load(f)
    schema.setdefault("$defs", {})
    schema["$defs"].update(common.get("$defs", {}))
    schema = json.loads(
        json.dumps(schema).replace(
            "./domain-baseline-common.schema.json#/$defs/", "#/$defs/"
        )
    )
    jsonschema.validate(report, schema)


def _combined_reproducibility(a: dict, b: dict, prefix: str) -> dict:
    """Prefix check metric names and return {reproducible, checks}."""
    prefixed = []
    for c in a["checks"]:
        cc = dict(c)
        cc["metric"] = prefix + "." + cc["metric"]
        prefixed.append(cc)
    return {"reproducible": a["reproducible"], "checks": prefixed}


async def run_domain_baseline(
    dataset_path: str,
    output_path: str,
    domain_key: str,
    benefit_block: dict | None = None,
) -> int:
    settings = get_settings()
    ds_path = Path(dataset_path)
    out_path = Path(output_path)

    # History artifact discipline: never overwrite a produced baseline report.
    if out_path.exists():
        logger.error(
            "refusing to overwrite existing report %s (历史产物勿覆盖纪律)",
            out_path,
        )
        return 1

    with open(ds_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    if not dataset:
        logger.error("empty dataset %s", dataset_path)
        return 1

    embedding = _EvalEmbeddingProvider(settings.embedding_model)
    qdrant = QdrantStore(url=settings.qdrant_url)
    index_version = _derive_index_version(settings.embedding_model)
    hybrid_collection = f"chunks_hybrid_{index_version}"

    engine = create_async_engine(settings.database_url)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        await resolve_domain_scopes(dataset, session_factory)
        await resolve_expected_heading(dataset, session_factory)
        unresolved = [e for e in dataset if not e.get("expected_evidence_ids")]
        if unresolved:
            logger.warning(
                "%d/%d entries have no resolvable expected_heading anchor",
                len(unresolved), len(dataset),
            )

        # Sparse encoder fitted on published chunk texts (hybrid arm).
        async with session_factory() as session:
            texts = (await session.execute(
                sa_select(Chunk.content_text)
                .where(Chunk.knowledge_scope_id.in_(
                    sorted({i for e in dataset for i in e["domain_scope_ids"]})
                ))
                .order_by(Chunk.chunk_id)
            )).scalars().all()
        sparse_encoder = BM25SparseEncoder()
        sparse_encoder.fit(list(texts))

        # Reranker for the hybrid arm (mirror run_eval's degrade-to-fusion).
        reranker = None
        try:
            from rag_mcp.providers.local_cpu_reranker import LocalCPUReranker
            reranker = LocalCPUReranker()
            reranker.warmup()
            logger.info("reranker loaded: %s", settings.hybrid_retrieval.reranker_model)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reranker unavailable, hybrid runs fusion-only: %s", exc)

        # --- Run 1: dense (named) + hybrid, same session ---
        dense_pq, dense_metrics = await run_dense_named_eval(
            dataset, qdrant, embedding, hybrid_collection, _TOP_K,
        )
        hybrid_pq, hybrid_metrics = await run_single_eval(
            dataset, qdrant, embedding, hybrid_collection, _TOP_K,
            mode="hybrid", sparse_encoder=sparse_encoder, reranker=reranker,
            rerank_budget=settings.hybrid_retrieval.rerank_budget,
        )

        # --- Run 2 (reproducibility, non-latency 1% tolerance) ---
        _, dense_metrics_2 = await run_dense_named_eval(
            dataset, qdrant, embedding, hybrid_collection, _TOP_K,
        )
        _, hybrid_metrics_2 = await run_single_eval(
            dataset, qdrant, embedding, hybrid_collection, _TOP_K,
            mode="hybrid", sparse_encoder=sparse_encoder, reranker=reranker,
            rerank_budget=settings.hybrid_retrieval.rerank_budget,
        )

        d_repro = check_reproducibility(dense_metrics, dense_metrics_2, _TOLERANCE)
        h_repro = check_reproducibility(hybrid_metrics, hybrid_metrics_2, _TOLERANCE)
        d_repro_c = _combined_reproducibility(d_repro, dense_metrics_2, "dense")
        h_repro_c = _combined_reproducibility(h_repro, hybrid_metrics_2, "hybrid")
        reproducibility = {
            "non_latency_reproducible": d_repro["reproducible"] and h_repro["reproducible"],
            "tolerance": _TOLERANCE,
            "checks": d_repro_c["checks"] + h_repro_c["checks"],
        }

        # Cross-domain leakage: evidence must stay within the query's scope set.
        leakage = 0
        for i, entry in enumerate(dataset):
            allowed = set(entry["domain_scope_ids"])
            for ev in hybrid_pq[i].get("evidence_items", []):
                sid = ev.get("knowledge_scope_id")
                if sid is not None and int(sid) not in allowed:
                    leakage += 1

        hard = await measure_hard_constraints(
            dataset, hybrid_pq, leakage, session_factory,
        )
        hard_constraints = {
            "cross_domain_leakage_events": leakage,
            "schema_validity_rate": hard["schema_validity_rate"],
            "source_locatability_rate": hard["source_locatability_rate"],
            "all_passed": (
                leakage == 0
                and hard["schema_validity_rate"] >= 1.0
                and hard["source_locatability_rate"] >= 1.0
            ),
        }

        report_type = (
            "legal_domain_baseline" if domain_key == "legal"
            else "generic_domain_baseline"
        )
        report: dict[str, Any] = {
            "report_type": report_type,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": {
                "domain_key": domain_key,
                "embedding_model": settings.embedding_model,
                "reranker_model": settings.hybrid_retrieval.reranker_model,
                "dataset_path": str(ds_path),
                "num_queries": len(dataset),
                "retrieval_modes": ["dense", "hybrid"],
            },
            "dense_metrics": {
                "recall_at_k": _metric_block(dense_metrics["recall_at_k"]),
                "mrr": _metric_block(dense_metrics["mrr"]),
                "ndcg_at_k": _metric_block(dense_metrics["ndcg_at_k"]),
                "latency_ms": _latency_block(dense_metrics["latency_ms"]),
            },
            "hybrid_metrics": {
                "recall_at_k": _metric_block(hybrid_metrics["recall_at_k"]),
                "mrr": _metric_block(hybrid_metrics["mrr"]),
                "ndcg_at_k": _metric_block(hybrid_metrics["ndcg_at_k"]),
                "latency_ms": _latency_block(hybrid_metrics["latency_ms"]),
            },
            "deltas": {
                "mrr_mean_delta": round(
                    hybrid_metrics["mrr"]["mean"] - dense_metrics["mrr"]["mean"], 6),
                "ndcg_mean_delta": round(
                    hybrid_metrics["ndcg_at_k"]["mean"] - dense_metrics["ndcg_at_k"]["mean"], 6),
                "recall_mean_delta": round(
                    hybrid_metrics["recall_at_k"]["mean"] - dense_metrics["recall_at_k"]["mean"], 6),
                "latency_p50_delta_ms": round(
                    hybrid_metrics["latency_ms"]["p50"] - dense_metrics["latency_ms"]["p50"], 6),
                "latency_p95_delta_ms": round(
                    hybrid_metrics["latency_ms"]["p95"] - dense_metrics["latency_ms"]["p95"], 6),
            },
            "hard_constraints": hard_constraints,
            "per_query_comparison": build_per_query_comparison(
                dataset, dense_pq, hybrid_pq,
            ),
            "reproducibility": reproducibility,
        }
        if domain_key == "legal":
            report["cross_reference_benefit"] = benefit_block or {}
            if not benefit_block:
                logger.warning(
                    "legal baseline produced without cross_reference_benefit "
                    "block — run run_legal_benefit.py first (FR-011)"
                )

        # Contract schema validation before the report is written (FR-009).
        _validate_report_against_schema(report, report_type)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info("domain baseline written to %s", out_path)
        logger.info(
            "dense MRR=%.4f hybrid MRR=%.4f | leakage=%d schema=%.2f locatability=%.2f | reproducible=%s",
            dense_metrics["mrr"]["mean"], hybrid_metrics["mrr"]["mean"],
            leakage, hard_constraints["schema_validity_rate"],
            hard_constraints["source_locatability_rate"],
            reproducibility["non_latency_reproducible"],
        )
        return 0
    finally:
        await engine.dispose()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="011 domain baseline runner (dense+hybrid).")
    p.add_argument("--dataset", "-d", required=True)
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--domain-key", "-k", required=True, choices=["personal", "generic", "legal"])
    p.add_argument("--benefit-report", help="legal benefit block JSON (from run_legal_benefit.py)")
    return p.parse_args(argv)


async def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    benefit = None
    if args.benefit_report:
        with open(args.benefit_report, "r", encoding="utf-8") as f:
            benefit = json.load(f)
    return await run_domain_baseline(
        args.dataset, args.output, args.domain_key, benefit_block=benefit,
    )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
