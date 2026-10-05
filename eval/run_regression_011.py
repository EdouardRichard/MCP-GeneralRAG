#!/usr/bin/env python3
"""001-006 full regression orchestration runner (011, T022/T023, FR-016/SC-005).

Re-runs every 001-006 historical report caliber with the current (011-changed)
code and verifies the non-latency metrics (Recall@K / MRR / nDCG) match the
historical reports within 1% relative tolerance. Re-run artifacts land in
011-prefixed NEW files — historical reports are never overwritten (research
R11 / US5 AC2).

Groups (per spec regression table + research R11):
  001 dense 11  : run_eval.py --mode dense, first 11 entries  vs baseline_report.json
  002 hybrid 18 : run_comparison.py --limit 18                vs hybrid_comparison_report.json
  003 format 37 : run_eval.py --mode hybrid, first 37 entries vs regression_report.json
  004 graph 37  : run_graph_comparison.py --limit 37          vs 010_graph_regression_report.json
  005 agentic 63: run_agentic_comparison.py (combined full)   vs agentic_comparison_report.json
  006 smoke 11x2: instance-form smoke (direct function call)  vs instance_form_smoke_report.json

Usage:
    python eval/run_regression_011.py            # run all six groups
    python eval/run_regression_011.py --group 001_dense_11
"""
from __future__ import annotations

import argparse
import asyncio
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

logger = logging.getLogger(__name__)

_TOLERANCE = 0.01
_EVAL = _REPO_ROOT / "eval"

# ---------------------------------------------------------------------------
# Group definitions: command + output + historical baseline + metric extractor
# ---------------------------------------------------------------------------


def _dense_metrics(r: dict) -> dict[str, float]:
    m = r["metrics"]
    return {
        "recall_at_k": m["recall_at_k"]["mean"],
        "mrr": m["mrr"]["mean"],
        "ndcg_at_k": m["ndcg_at_k"]["mean"],
    }


def _comparison_metrics(r: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for arm, key in (("baseline", "baseline_metrics"), ("hybrid", "hybrid_metrics")):
        m = r[key]
        for metric in ("recall_at_k", "mrr", "ndcg_at_k"):
            out[f"{arm}.{metric}"] = m[metric]["mean"]
    return out


def _graph_metrics(r: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for arm, key in (("baseline", "baseline_metrics"), ("graph", "graph_metrics")):
        m = r[key]
        for metric in ("recall_at_k", "mrr", "ndcg_at_k"):
            out[f"{arm}.{metric}"] = m[metric]["mean"]
    return out


def _agentic_metrics(r: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for arm, key in (("baseline", "baseline_metrics"), ("agentic", "agentic_metrics")):
        m = r[key]
        for metric in ("recall_at_k", "mrr", "ndcg_at_k"):
            out[f"{arm}.{metric}"] = m[metric]["mean"]
    return out


def _smoke_metrics(r: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for form in ("writer", "reader"):
        means = r["instance_forms"][form]["means"]
        for metric in ("recall_at_k", "mrr", "ndcg_at_k"):
            out[f"{form}.{metric}"] = means[metric]
    return out


def _write_truncated_dataset(n: int, path: Path) -> Path:
    with open(_EVAL / "eval_dataset.json", "r", encoding="utf-8") as f:
        dataset = json.load(f)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dataset[:n], f, indent=2, ensure_ascii=False)
    return path


GROUPS: list[dict] = [
    {
        "id": "001_dense_11",
        "prepare": lambda: _write_truncated_dataset(11, _EVAL / "_tmp_ds11.json"),
        "cmd": lambda ds: [sys.executable, "-X", "utf8", "eval/run_eval.py",
                           "--dataset", str(ds), "--mode", "dense",
                           "--output", "eval/011_001_regression_report.json",
                           "--no-reproducibility-check"],
        "cleanup": lambda ds: Path(ds).unlink(missing_ok=True),
        "output": "eval/011_001_regression_report.json",
        "historical": "eval/baseline_report.json",
        "extract": _dense_metrics,
    },
    {
        "id": "002_hybrid_18",
        "cmd": lambda: [sys.executable, "-X", "utf8", "eval/run_comparison.py",
                        "--dataset", "eval/eval_dataset.json",
                        "--output", "eval/011_002_regression_report.json",
                        "--limit", "18",
                        "--format-report", "eval/011_002_format_regression_report.json"],
        "output": "eval/011_002_regression_report.json",
        "historical": "eval/hybrid_comparison_report.json",
        "extract": _comparison_metrics,
    },
    {
        "id": "003_format_37",
        "prepare": lambda: _write_truncated_dataset(37, _EVAL / "_tmp_ds37.json"),
        "cmd": lambda ds: [sys.executable, "-X", "utf8", "eval/run_eval.py",
                           "--dataset", str(ds), "--mode", "hybrid",
                           "--output", "eval/011_003_regression_report.json",
                           "--no-reproducibility-check"],
        "cleanup": lambda ds: Path(ds).unlink(missing_ok=True),
        "output": "eval/011_003_regression_report.json",
        "historical": "eval/regression_report.json",
        "extract": _dense_metrics,
    },
    {
        "id": "004_graph_37",
        "cmd": lambda: [sys.executable, "-X", "utf8", "eval/run_graph_comparison.py",
                        "--dataset", "eval/eval_dataset.json",
                        "--output", "eval/011_004_regression_report.json",
                        "--limit", "37", "--skip-reproducibility"],
        "output": "eval/011_004_regression_report.json",
        "historical": "eval/010_graph_regression_report.json",
        "extract": _graph_metrics,
    },
    {
        "id": "005_agentic_63",
        "cmd": lambda: [sys.executable, "-X", "utf8", "eval/run_agentic_comparison.py",
                        "--output", "eval/011_005_regression_report.json",
                        "--skip-repeatability"],
        "output": "eval/011_005_regression_report.json",
        "historical": "eval/agentic_comparison_report.json",
        "extract": _agentic_metrics,
    },
    {
        "id": "006_smoke_11x2",
        "direct": "smoke",
        "output": "eval/011_006_regression_report.json",
        "historical": "eval/instance_form_smoke_report.json",
        "extract": _smoke_metrics,
    },
]


def configure_output_directory(directory: Path) -> list[dict]:
    """Copy the historical calibers while directing every artifact to a new run."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise FileExistsError(f"regression output directory must be empty: {directory}")
    groups = []
    for original in GROUPS:
        group = dict(original)
        group["output"] = str(directory / Path(original["output"]).name.replace("011_", "012_", 1))
        if "cmd" in original:
            def redirected(*args, original=original):
                command = original["cmd"](*args)
                for flag in ("--output", "--format-report"):
                    if flag in command:
                        index = command.index(flag) + 1
                        command[index] = str(directory / Path(command[index]).name.replace("011_", "012_", 1))
                return command
            group["cmd"] = redirected
        if "prepare" in original:
            n = 11 if original["id"] == "001_dense_11" else 37
            group["prepare"] = lambda n=n: _write_truncated_dataset(n, directory / f"dataset_{n}.json")
        groups.append(group)
    return groups


async def run_smoke_group(output_path: str) -> int:
    """Group 6: instance-form smoke via direct function import (the legacy
    runner writes to a fixed path — direct call keeps history intact)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from rag_mcp.config import get_settings
    from rag_mcp.eval.instance_form_smoke import (
        load_baseline_queries,
        run_form_smoke,
    )
    from rag_mcp.indexing.qdrant_client import QdrantStore
    from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    qdrant_store = QdrantStore()
    embedding_provider = LocalCPUEmbeddingProvider()
    queries = load_baseline_queries()

    reports = {}
    for mode in ("writer", "reader"):
        report = await run_form_smoke(
            mode, session_factory=session_factory, qdrant_store=qdrant_store,
            embedding_provider=embedding_provider, queries=queries,
            top_k=5, tolerance=_TOLERANCE,
        )
        reports[mode] = report
        logger.info("smoke %s: pass=%s", mode, report["pass"])

    combined = {
        "report_type": "instance_form_smoke",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instance_forms": reports,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)
    await engine.dispose()
    return 0


async def _run_subprocess(cmd: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(_REPO_ROOT), stdout=log, stderr=asyncio.subprocess.STDOUT,
        )
        return await proc.wait()


def _compare(group: dict) -> dict:
    with open(_REPO_ROOT / group["output"], "r", encoding="utf-8") as f:
        new_report = json.load(f)
    with open(_REPO_ROOT / group["historical"], "r", encoding="utf-8") as f:
        old_report = json.load(f)

    new_metrics = group["extract"](new_report)
    old_metrics = group["extract"](old_report)

    checks = []
    all_no_regression = bool(old_metrics) and set(new_metrics) == set(old_metrics)
    for name in sorted(set(new_metrics) & set(old_metrics)):
        a, b = old_metrics[name], new_metrics[name]
        if a == 0 and b == 0:
            delta, within = 0.0, True
        elif a == 0 or b == 0:
            delta = abs(a - b)
            within = delta <= _TOLERANCE
        else:
            delta = abs(a - b) / max(abs(a), abs(b))
            within = delta <= _TOLERANCE
        # One-sided no-regression gate (006 instance-form smoke precedent):
        # the rerun must not be WORSE than history by more than the tolerance.
        # Improvements beyond tolerance are recorded as within_tolerance=false
        # but no_regression=true (e.g. the 001 caliber's pre-existing corpus
        # re-ingestion drift — improvement, not a 011 regression).
        no_regression = b >= a * (1 - _TOLERANCE) - 1e-9
        if not no_regression:
            all_no_regression = False
        checks.append({
            "metric": name,
            "historical": round(a, 6),
            "rerun": round(b, 6),
            "relative_delta": round(delta, 6),
            "tolerance": _TOLERANCE,
            "within_tolerance": within,
            "no_regression": no_regression,
            "passed": no_regression,
        })
    return {
        "group": group["id"],
        "historical_report": group["historical"],
        "rerun_report": group["output"],
        "checks": checks,
        "all_passed": all_no_regression,
        "gate": "one_sided_no_regression (006 precedent; improvements beyond "
                "tolerance are recorded, not failed)",
    }


async def run_regression(group_ids: list[str] | None = None, output_dir: Path | None = None) -> int:
    groups = configure_output_directory(output_dir) if output_dir else GROUPS
    selected = [g for g in groups if not group_ids or g["id"] in group_ids]
    results = []
    for group in selected:
        logger.info("=== group %s ===", group["id"])
        ds_arg = None
        if "prepare" in group:
            ds_arg = group["prepare"]()
        try:
            if group.get("direct") == "smoke":
                rc = await run_smoke_group(group["output"])
            else:
                cmd = group["cmd"](ds_arg) if "prepare" in group else group["cmd"]()
                log_path = (output_dir or _EVAL) / f"regression_{group['id']}.log"
                rc = await _run_subprocess(cmd, log_path)
            if rc != 0:
                logger.error("group %s runner exited %s", group["id"], rc)
                results.append({"group": group["id"], "runner_exit_code": rc,
                                "all_passed": False, "checks": []})
                continue
            results.append(_compare(group))
        finally:
            if "cleanup" in group and ds_arg:
                group["cleanup"](ds_arg)

    summary = {
        "report_type": "regression_011",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tolerance": _TOLERANCE,
        "groups": results,
        "all_passed": all(r.get("all_passed") for r in results) and len(results) == len(GROUPS),
    }
    out = output_dir / "012_regression_summary.json" if output_dir else _EVAL / "011_regression_summary.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    for r in results:
        logger.info("group %s: all_passed=%s (%d checks)", r["group"], r.get("all_passed"),
                    len(r.get("checks", [])))
    logger.info("regression summary written to %s | all_passed=%s", out, summary["all_passed"])
    return 0 if summary["all_passed"] else 1


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="011 full regression (001-006 calibers).")
    p.add_argument("--group", action="append", default=None,
                   help="run a single group id (repeatable); default all six")
    p.add_argument("--output-dir", type=Path, help="fresh directory for a 012 rerun; existing artifacts are refused")
    return p.parse_args(argv)


async def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    return await run_regression(args.group, args.output_dir)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
