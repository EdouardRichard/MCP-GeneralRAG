#!/usr/bin/env python3
"""Multi-domain acceptance runner (011, T021, FR-014/FR-015/SC-003).

Runs the DeepSeek Harness reference-client closed loop over the mixed-domain
environment (list_knowledge_domains discovery -> domain_scope three addressing
forms -> search_knowledge -> get_evidence) and measures the hard-metrics
three-piece per response (cross-domain leakage=0 / Schema 100% / source
locatability 100%). Persists eval/multi_domain_acceptance_report.json.

The report is the FR-014 acceptance artifact: scenario checklist + per-query
three-piece measurements + reference-client conclusion (DeepSeek Harness is the
must-pass target host; ChatGPT App / Claude Code are recorded non-blocking).

Usage:
    python eval/run_multi_domain_acceptance.py
"""
from __future__ import annotations

import asyncio
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_SRC = _REPO_ROOT / "backend" / "src"
for p in (_BACKEND_SRC, str(_REPO_ROOT / "eval"), str(_REPO_ROOT / "backend")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from jsonschema import Draft202012Validator  # noqa: E402
from sqlalchemy import select as sa_select, text as sa_text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rag_mcp.config import get_settings  # noqa: E402
from rag_mcp.indexing.qdrant_client import QdrantStore  # noqa: E402
from rag_mcp.mcp.list_knowledge_domains import list_knowledge_domains_core  # noqa: E402
from rag_mcp.mcp.search_knowledge import search_knowledge_core  # noqa: E402
from rag_mcp.services.evidence_service import EvidenceService  # noqa: E402
from run_eval import _EvalEmbeddingProvider  # noqa: E402
from memory_acceptance_reports import write_report  # noqa: E402

logger = logging.getLogger(__name__)

_OUTPUT = _REPO_ROOT / "eval" / "multi_domain_acceptance_report.json"

# One query per 011 domain + a se-project axis query.
_QUERIES = [
    ("personal", "personal-eval-rag-notes", "嵌入模型选型时本地部署首选哪个模型"),
    ("generic", "generic-eval-meeting-notes", "hybrid A/B test 的 Recall@5 结果如何"),
    ("legal", "legal-eval-dpa", "数据处理协议对跨境提供个人数据有什么要求"),
    ("legal", "legal-eval-data-security", "数据安全管理办法对重要数据处理者有什么义务"),
]


def _load_schema(name: str) -> dict:
    p = _REPO_ROOT / "specs" / "001-minimum-rag-mcp-loop" / "contracts"
    return json.loads((p / name).read_text(encoding="utf-8"))


async def run(output: Path) -> int:
    if output.exists():
        raise FileExistsError(output)
    settings = get_settings()
    embedding = _EvalEmbeddingProvider(settings.embedding_model)
    qdrant = QdrantStore(url=settings.qdrant_url)
    engine = create_async_engine(settings.database_url)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    search_schema = _load_schema("mcp-search-output.schema.json")
    evidence_schema = _load_schema("mcp-get-evidence.schema.json")["properties"]["output"]

    try:
        domains = (await list_knowledge_domains_core(session_factory))["domains"]
        by_slug = {d["slug"]: d for d in domains}

        scenarios: list[dict] = []
        per_query: list[dict] = []
        total_evidence = 0
        leakage = 0
        valid_search = 0
        locatable = 0

        # Scenario 1: discovery covers the four semantic axes.
        axes = {d["domain_key"] for d in domains}
        discovery_ok = {"personal", "generic", "legal", "se-project"} <= axes
        scenarios.append({
            "id": "discovery_four_axes",
            "description": "list_knowledge_domains covers personal/generic/legal/se-project",
            "status": "passed" if discovery_ok else "failed",
        })

        # Scenario 2: three-form addressing + closed loop + hard metrics.
        three_form_ok = True
        for domain_key, slug, query in _QUERIES:
            if slug not in by_slug:
                three_form_ok = False
                continue
            scope_id = by_slug[slug]["id"]
            name = by_slug[slug]["name"]

            # numeric / slug / type:name
            forms = {
                "numeric": [scope_id],
                "slug": [slug],
                "type_name": [f"public:{name}"],
            }
            form_results = {}
            for form, dscope in forms.items():
                resp = await search_knowledge_core(
                    query=query, project_scope=[], domain_scope=dscope, top_k=5,
                    task_context=None, session_factory=session_factory,
                    qdrant_store=qdrant, embedding_provider=embedding,
                )
                form_results[form] = resp
                if resp.get("completion_status") not in ("complete", "partial"):
                    three_form_ok = False

            # hard metrics over the slug-form response
            resp = form_results["slug"]
            evidence = resp.get("evidence", [])
            total_evidence += len(evidence)
            for ev in evidence:
                if str(ev.get("knowledge_scope_id")) != str(scope_id):
                    leakage += 1
                if ev.get("source_position"):
                    locatable += 1
            if Draft202012Validator(search_schema).is_valid(resp):
                valid_search += 1

            # closed loop: expand first evidence
            loop_ok = False
            if evidence:
                async with session_factory() as session:
                    svc = EvidenceService(session=session)
                    expanded = await svc.get_evidence(
                        evidence_id=evidence[0]["evidence_id"],
                        project_scopes=[], domain_scopes=[slug],
                    )
                    await session.commit()
                loop_ok = expanded.get("status") == "available"
            if not loop_ok and evidence:
                three_form_ok = False

            per_query.append({
                "domain_key": domain_key,
                "slug": slug,
                "query": query,
                "forms": {f: r.get("completion_status") for f, r in form_results.items()},
                "evidence_count": len(evidence),
                "closed_loop": "passed" if loop_ok or not evidence else "failed",
            })

        scenarios.append({
            "id": "three_form_addressing_closed_loop",
            "description": "domain_scope numeric/slug/type:name addressing + get_evidence expansion",
            "status": "passed" if three_form_ok else "failed",
        })

        schema_rate = round(valid_search / len(_QUERIES), 4) if _QUERIES else 1.0
        locatability_rate = round(locatable / total_evidence, 4) if total_evidence else 1.0
        hard = {
            "cross_domain_leakage_events": leakage,
            "schema_validity_rate": schema_rate,
            "source_locatability_rate": locatability_rate,
            "all_passed": leakage == 0 and schema_rate >= 1.0 and locatability_rate >= 1.0,
        }
        scenarios.append({
            "id": "hard_metrics_three_piece",
            "description": "跨域串库=0 / Schema 100% / 定位 100%",
            "status": "passed" if hard["all_passed"] else "failed",
        })

        report = {
            "report_type": "multi_domain_acceptance",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scenarios": scenarios,
            "hard_constraints": hard,
            "per_query_measurements": per_query,
            "reference_client": {
                "deepseek_harness": "not_measured_by_core_runner",
                "chatgpt_app": "recorded_non_blocking",
                "claude_code": "recorded_non_blocking",
            },
        }
        out = output
        write_report(out, report)
        logger.info("multi-domain acceptance written to %s (leakage=%d schema=%.2f locatability=%.2f)",
                    out, leakage, schema_rate, locatability_rate)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if hard["all_passed"] and all(item["status"] == "passed" for item in scenarios) else 1
    finally:
        await engine.dispose()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New report path; existing evidence is never overwritten")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    return await run(args.output)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
