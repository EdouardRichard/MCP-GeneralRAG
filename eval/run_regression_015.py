#!/usr/bin/env python3
"""015 T058/T059/T060 - 001-014 full-suite regression orchestration (FR-054/FR-059/SC-020).

What this runner is allowed to do (and what it refuses to do)
------------------------------------------------------------
* **Reuse, never rewrite.** Every 001-014 caliber is re-run through its *existing*
  runner (`run_eval.py`, `run_comparison.py`, `run_graph_comparison.py`,
  `run_agentic_comparison.py`, `run_cross_reference_comparison.py`,
  `run_domain_baseline.py`, `run_multi_domain_acceptance.py`,
  `run_regression_011.py`, `run_memory_comparison.py`, pytest) exactly as the
  011 precedent does. No existing runner or test is modified.
* **History zero-overwrite.** Every artifact this runner writes lives under
  ``eval/runs/<RUN_ID>/``; the target path must not exist before a write, and
  ``_guard_command`` refuses any runner argument that names an output outside
  the run directory. The tracked ``eval/memory_baseline_report.json`` and the
  001-014 historical reports are never touched.
* **Not executed is not passed.** A group is ``executed`` only when its round(s)
  really ran and produced the artifact the caliber names. A group whose record
  or replay round could not be produced is ``not_executed`` with a reason.
* **record + replay (T059).** Model-dependent groups run a *record* round that
  freezes the model responses and the cache fingerprint, then a *replay* round
  whose **measured** real provider transports must be 0; only the replay round is
  a pass basis. The live round is never a pass basis.
* **No metric is written without being measured.** ``replay_real_network_calls``
  comes from a socket-audit-hook census (`_netcount_015.py`, generated below),
  never from a constant; a missing measurement stays ``null``.

Usage
-----
    python eval/run_regression_015.py --list
    python eval/run_regression_015.py --group 001_dense_11
    python eval/run_regression_015.py --emit-map
    python eval/run_regression_015.py --emit-report        # T060

T060 note (cross-stream record): while T058/T059 were running, the frozen helper
``memory_baseline_support.regression_block`` emitted a non-contract ``map_path`` key
whenever ``--regression-map`` was supplied, and the report contract's ``regression``
block is ``additionalProperties: false``, so the raw CLI aborted inside
``validate_report()`` before writing. That defect was fixed upstream by commit
``2b39708`` ("015 T060 stop the runner emitting the non-contract regression map_path
key") while this stream was working; ``--emit-report`` therefore invokes the frozen
runner directly and keeps a compatibility shim only as a recorded fallback. The
shim-era artifact and its validation record are preserved under
``eval/runs/<RUN_ID>/regression/_probe/``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "eval"
BACKEND_DIR = REPO_ROOT / "backend"
PY = sys.executable

# The composition calibers read DATABASE_URL/DATABASE_URL_SYNC from the process
# environment (eval/run_memory_comparison.py does the same); load the repository
# .env before any caliber import so a CLI invocation sees the same runtime the
# other 015 runners do.  User-provided values always win.
for _env_file in (REPO_ROOT / ".env", Path.cwd() / ".env"):
    if _env_file.is_file():
        for _line in _env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _value = _line.split("=", 1)
            _key, _value = _key.strip(), _value.strip().strip('"').strip("'")
            if _key and _key not in os.environ:
                os.environ[_key] = _value

DEFAULT_RUN_ID = "015-20261009205637"
TOLERANCE = 0.01          # non-latency relative tolerance (research R14)
NETCOUNT_NAME = "_netcount_015.py"
GROUPS_MAP_NAME = "regression_group_map.json"

# Host environment defect (measured 2026-10-10): this host exports
# ``NO_PROXY='localhost,127.0.0.1,::1,[::1]'``. The bracketed entry makes httpx
# build an invalid URLPattern (``httpx.InvalidURL: Invalid port: ':1]'``) for EVERY
# client, so ``qdrant_client`` cannot even be constructed and every 001-014 caliber
# exits 1 without producing its artifact (measured: all 31 groups failed this way).
# The 015 native runners sanitize this for their own process; the orchestrator must
# do the same for every child it spawns, and record the original -> normalized pair
# in the map so the defect stays visible in evidence.
PROXY_ENV_RECORD: dict[str, Any] = {"original": {}, "normalized": {}}


def sanitize_proxy_environment() -> dict[str, Any]:
    for _name in ("NO_PROXY", "no_proxy"):
        _value = os.environ.get(_name)
        if not _value:
            continue
        _entries = [entry.strip() for entry in _value.split(",") if entry.strip()]
        _cleaned = [entry for entry in _entries if not (entry.startswith("[") and entry.endswith("]"))]
        PROXY_ENV_RECORD["original"][_name] = _value
        if _cleaned != _entries:
            os.environ[_name] = ",".join(_cleaned)
        PROXY_ENV_RECORD["normalized"][_name] = os.environ.get(_name)
    return PROXY_ENV_RECORD


sanitize_proxy_environment()

# 013's comparison runner allocates a persistent working tree per run id under
# ``--base`` (``<base>/<run-id>/<nn>/root``) and refuses to reuse an existing data
# root, so a fixed run id makes the group non-repeatable: the first attempt leaves
# ``<base>/<run-id>/00/root`` behind and every later attempt returns
# ``incomplete: data root already exists``. The token is per script invocation (the
# 013 group's record and replay steps share it, which they must, because the replay
# re-restores identities from the same tree) and gives each attempt a fresh tree.
SCRATCH_013_SUFFIX = uuid4().hex[:8]
SCRATCH_013_RUN_ID = f"015REGRESSION013{SCRATCH_013_SUFFIX}"   # 013 requires an alphanumeric token
#: The replay round must be its own invocation: 013's runner refuses to reuse a run
#: identity file, so a replay sharing the record round's run id dies at
#: "refusing to overwrite existing run identity file ..." before it can consume the
#: sealed cache. Its own token makes it re-restore fresh identities from the same
#: capsule and replay against the record round's sealed cache.
SCRATCH_013_REPLAY_RUN_ID = f"015REGRESSION013R{SCRATCH_013_SUFFIX}"
SCRATCH_013_BASE = f"C:/t015c{SCRATCH_013_SUFFIX}"
#: The restore brings up its own isolated Qdrant on ``--qdrant-port-base`` and refuses
#: to reuse a store that already answers. A fixed base therefore collides with any
#: previous attempt's still-running instance ("http://127.0.0.1:18400 already answers"),
#: so the base is per invocation too. Six isolated arms need six consecutive ports.
SCRATCH_013_PORT_BASE = 18500 + (int(SCRATCH_013_SUFFIX[:4], 16) % 3000)

#: A previous attempt of the same run can leave behind a document that is only a
#: failure marker (status ``incomplete`` plus a ``reason`` and no measured content).
#: That is not a historical artifact, so it is preserved under a ``superseded-`` name
#: and the step may retry; a real report is still protected by the zero-overwrite guard.
_PLACEHOLDER_KEYS = {"schema_version", "report_type", "run_id", "generated_at", "status", "reason", "mode"}


def _is_failure_placeholder(path: Path) -> bool:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(document, dict) or document.get("status") != "incomplete":
        return False
    return bool(set(document) <= _PLACEHOLDER_KEYS and document.get("reason"))

_NETCOUNT_SOURCE = '''"""Measured real-network-call counter for one 015 regression round (T059).

PRIMARY INSTRUMENT - provider HTTP requests at the httpx transport layer.
Every model-provider call this process makes must pass through an httpx transport,
so wrapping ``HTTPTransport.handle_request`` / ``AsyncHTTPTransport.handle_async_request``
counts them exactly, independently of any local HTTP proxy or TUN device.
``provider_calls`` is that count, restricted to the configured provider host(s)
(``NETCOUNT_PROVIDER_HOSTS``, default ``api.deepseek.com``).

SECONDARY, ADVISORY - socket audit census. It is recorded for transparency only:
on this host the ``socket.connect`` audit event does not observe most connects
(measured with eval/runs/015-20261009205637/_debug/netcount_probe_015.py, which
opened real PostgreSQL, Qdrant and provider connections and was seen as a single
connect), so the census is never used as the provider-call count.
"""
import json
import os
import runpy
import sys

MARKER = "015-T059-netcount-v2"
_CENSUS = {}
_REQUESTS = {}
_HOSTS = tuple(part.strip().lower()
               for part in (os.environ.get("NETCOUNT_PROVIDER_HOSTS") or "api.deepseek.com").split(",")
               if part.strip())


def _is_provider(host):
    host = (host or "").lower()
    return any(host == candidate or host.endswith("." + candidate) for candidate in _HOSTS)


def _count(request):
    host = getattr(getattr(request, "url", None), "host", "") or ""
    _REQUESTS[host] = _REQUESTS.get(host, 0) + 1


_instrument_error = None
try:
    import httpx

    _async_handle = httpx.AsyncHTTPTransport.handle_async_request
    _sync_handle = httpx.HTTPTransport.handle_request

    async def _patched_async(self, request):
        _count(request)
        return await _async_handle(self, request)

    def _patched_sync(self, request):
        _count(request)
        return _sync_handle(self, request)

    httpx.AsyncHTTPTransport.handle_async_request = _patched_async
    httpx.HTTPTransport.handle_request = _patched_sync
except Exception as _error:  # noqa: BLE001 - a failed instrument is recorded, never hidden
    _instrument_error = "%s: %s" % (type(_error).__name__, _error)


def _hook(event, args):
    if event != "socket.connect":
        return
    try:
        address = args[1]
    except Exception:  # noqa: BLE001 - a malformed audit payload is not a call
        return
    if isinstance(address, (tuple, list)) and len(address) >= 2:
        host, port = address[0], address[1]
    else:
        host, port = str(address), None
    key = "%s:%s" % (host, port)
    _CENSUS[key] = _CENSUS.get(key, 0) + 1


sys.addaudithook(_hook)
_target = sys.argv[1]
sys.argv = sys.argv[1:]
_code = 0
try:
    runpy.run_path(_target, run_name="__main__")
except SystemExit as exc:
    _code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
finally:
    _provider = sum(count for host, count in _REQUESTS.items() if _is_provider(host))
    _payload = {
        "instrument": MARKER,
        "counting_rule": (
            "primary: provider_calls == httpx transport handle_request/handle_async_request calls whose "
            "request URL host is one of the configured provider hosts; secondary: a socket audit census "
            "that is advisory only because this host's socket.connect audit event does not observe every "
            "connect"
        ),
        "provider_calls": _provider,
        "provider_hosts": list(_HOSTS),
        "requests_by_host": _REQUESTS,
        "instrument_error": _instrument_error,
        "socket_census": _CENSUS,
        "socket_census_advisory": True,
    }
    _out = os.environ.get("NETCOUNT_OUT")
    if _out:
        with open(_out, "w", encoding="utf-8", newline="\\n") as _handle:
            json.dump(_payload, _handle, ensure_ascii=False, indent=2, sort_keys=True)
            _handle.write("\\n")
raise SystemExit(_code)
'''


_HARD_METRICS_RUNNER = '''"""015 regression group 014_hard_metrics: run the 014 measurement kernel in-place.

Why a wrapper is needed
-----------------------
``eval/hard_metrics_014.py`` has no CLI and reads ``RUN_ID``/``RUN_DIR`` at import
time.  Its ``main()`` (L433-435) unconditionally rewrites the *tracked*
``eval/hard-metrics-014.json``, which violates the 015 history-zero-overwrite rule
and is forbidden for this task.

This wrapper therefore sets ``RUN_ID``/``RUN_DIR`` to a fresh directory under the
015 run **before** importing the module and calls ``measure()`` (L376) directly.
``main()`` is never imported-as-main and never called, so the tracked artifact is
untouched; the assembled document is byte-shaped exactly like the module's own
document but is written only to this run's new artifact path.
"""
import asyncio
import importlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
EVAL_DIR = REPO_ROOT / "eval"
RUN_ID = os.environ["HARD_METRICS_RUN_ID"]
RUN_DIR = Path(os.environ["HARD_METRICS_RUN_DIR"])
OUT = Path(os.environ["HARD_METRICS_OUT"])

# The module reads these at import time (L34-35); set them first.
os.environ["RUN_ID"] = RUN_ID
os.environ["RUN_DIR"] = str(RUN_DIR)
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(EVAL_DIR))
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "backend" / "tests"))

module = importlib.import_module("hard_metrics_014")
assert Path(module.__file__).resolve() == (EVAL_DIR / "hard_metrics_014.py"), module.__file__
assert Path(module.RUN_DIR).resolve() == RUN_DIR.resolve(), module.RUN_DIR

metrics = asyncio.run(module.measure())

from rag_mcp.services.memory_projection_store import VIEW_KEYS  # noqa: E402

metrics["view_keys_unchanged"] = {
    "value": sorted(VIEW_KEYS), "total": len(VIEW_KEYS),
    "caliber": "MemoryProjectionStore VIEW_KEYS must stay exactly six",
    "unchanged": len(VIEW_KEYS) == 6,
}
payload = {
    "schema_version": "014.1",
    "report_type": "hard-metrics",
    "run_id": RUN_ID,
    "generated_at": datetime.now(UTC).isoformat(),
    "metrics": metrics,
    "notes": [
        "each metric names the exact caliber and denominator it used",
        "unmeasurable metrics are reported as not_measurable with the reason, never as 0 or 100%",
    ],
}
# The wrapper composes the same document shape as hard_metrics_014.main() but only
# ever writes this run's new artifact path.
if OUT.exists():
    raise SystemExit("refusing to overwrite " + str(OUT))
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8", newline="\\n")

for name, value in metrics.items():
    summary = {key: item for key, item in value.items()
               if key in {"value", "leaks", "occurrences", "reason", "total",
                          "attachment_items_carrying_evidence_locating_fields", "unchanged"}}
    print(name + ": " + json.dumps(summary, ensure_ascii=False))
print("written: " + str(OUT))
'''


# --------------------------------------------------------------------------- #
# metric extractors (the same calibers run_regression_011.py uses)
# --------------------------------------------------------------------------- #


def _dense_metrics(report: dict) -> dict[str, float]:
    metrics = report["metrics"]
    return {"recall_at_k": metrics["recall_at_k"]["mean"], "mrr": metrics["mrr"]["mean"],
            "ndcg_at_k": metrics["ndcg_at_k"]["mean"]}


def _comparison_metrics(report: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for arm, key in (("baseline", "baseline_metrics"), ("hybrid", "hybrid_metrics")):
        metrics = report[key]
        for metric in ("recall_at_k", "mrr", "ndcg_at_k"):
            out[f"{arm}.{metric}"] = metrics[metric]["mean"]
    return out


def _graph_metrics(report: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for arm, key in (("baseline", "baseline_metrics"), ("graph", "graph_metrics")):
        metrics = report[key]
        for metric in ("recall_at_k", "mrr", "ndcg_at_k"):
            out[f"{arm}.{metric}"] = metrics[metric]["mean"]
    return out


def _agentic_metrics(report: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for arm, key in (("baseline", "baseline_metrics"), ("agentic", "agentic_metrics")):
        metrics = report[key]
        for metric in ("recall_at_k", "mrr", "ndcg_at_k"):
            out[f"{arm}.{metric}"] = metrics[metric]["mean"]
    return out


def _smoke_metrics(report: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for form in ("writer", "reader"):
        means = report["instance_forms"][form]["means"]
        for metric in ("recall_at_k", "mrr", "ndcg_at_k"):
            out[f"{form}.{metric}"] = means[metric]
    return out


EXTRACTORS = {"dense": _dense_metrics, "comparison": _comparison_metrics,
              "graph": _graph_metrics, "agentic": _agentic_metrics, "smoke": _smoke_metrics}


# --------------------------------------------------------------------------- #
# group registry (T058): every group names its runner, command, test module and
# artifact. `command` uses {python}/{run}/{datasets}/{regression} placeholders.
# --------------------------------------------------------------------------- #

NO_DEDICATED_MODULE = ("n/a (runner-based caliber; no dedicated pytest module exists for this caliber)")


def _dataset(datasets: Path, count: int) -> Path:
    return datasets / f"eval_dataset_{count}.json"


GROUP_SPECS: list[dict] = [
    {
        "group": "001_dense_11",
        "runner": "eval/run_eval.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": "eval/baseline_report.json",
        "artifact": "regression/001_dense_11_report.json",
        "extract": "dense",
        "caliber": "001 dense baseline: eval_dataset.json entries 0-10 (11), --mode dense",
        "command": ["{python}", "-X", "utf8", "eval/run_eval.py", "--dataset", "{datasets}/eval_dataset_11.json",
                    "--mode", "dense", "--output", "{artifact}", "--no-reproducibility-check"],
    },
    {
        "group": "002_hybrid_18",
        "runner": "eval/run_comparison.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": "eval/hybrid_comparison_report.json",
        "artifact": "regression/002_hybrid_18_report.json",
        "extract": "comparison",
        "caliber": "002 hybrid baseline: eval_dataset.json --limit 18 (dense vs hybrid)",
        "command": ["{python}", "-X", "utf8", "eval/run_comparison.py", "--dataset", "eval/eval_dataset.json",
                    "--output", "{artifact}", "--limit", "18",
                    "--format-report", "{regression}/002_hybrid_18_format_report.json"],
    },
    {
        "group": "003_format_37",
        "runner": "eval/run_eval.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": "eval/regression_report.json",
        "artifact": "regression/003_format_37_report.json",
        "extract": "dense",
        "caliber": "003 format expansion: eval_dataset.json entries 0-36 (37), --mode hybrid",
        "command": ["{python}", "-X", "utf8", "eval/run_eval.py", "--dataset", "{datasets}/eval_dataset_37.json",
                    "--mode", "hybrid", "--output", "{artifact}", "--no-reproducibility-check"],
    },
    {
        "group": "004_graph_37",
        "runner": "eval/run_graph_comparison.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": "eval/010_graph_regression_report.json",
        "artifact": "regression/004_graph_37_report.json",
        "extract": "graph",
        "caliber": "004 graph enhancement: eval_dataset.json --limit 37 (010 regression caliber, 1% non-latency)",
        "command": ["{python}", "-X", "utf8", "eval/run_graph_comparison.py", "--dataset", "eval/eval_dataset.json",
                    "--output", "{artifact}", "--limit", "37", "--skip-reproducibility"],
    },
    {
        "group": "005_agentic_63",
        "runner": "eval/run_agentic_comparison.py",
        "mode": "record_then_replay",
        "model_dependent": True,
        "test_module": "backend/tests/unit/test_query_planner_schema.py (005/009 structural equivalence precedent)",
        "historical": "eval/agentic_comparison_report.json",
        "artifact": "regression/005_agentic_replay.json",
        "extract": "agentic",
        "cache_dir": "regression/005-llm-cache",
        "caliber": "005 agentic orchestration: combined eval_dataset.json + agentic_eval_dataset.json (63), "
                   "judged on the replay round only (real provider transports must be 0)",
        "rounds": [
            {"round": "record", "artifact": "regression/005_agentic_record.json", "instrumented": True,
             "command": ["{python}", "-X", "utf8", "eval/run_agentic_comparison.py",
                         "--dataset", "eval/eval_dataset.json",
                         "--agentic-dataset", "eval/agentic_eval_dataset.json",
                         "--llm-cache-dir", "{cachedir}",
                         "--output", "{artifact}", "--skip-repeatability"]},
            {"round": "replay", "artifact": "regression/005_agentic_replay.json", "instrumented": True,
             "command": ["{python}", "-X", "utf8", "eval/run_agentic_comparison.py",
                         "--dataset", "eval/eval_dataset.json",
                         "--agentic-dataset", "eval/agentic_eval_dataset.json",
                         "--llm-cache-dir", "{cachedir}", "--keep-llm-cache",
                         "--output", "{artifact}", "--skip-repeatability"]},
        ],
    },
    {
        "group": "006_smoke_11x2",
        "runner": "rag_mcp.eval.instance_form_smoke.run_form_smoke (direct call; run_instance_form_smoke.py fixes its own path)",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/integration/test_006_instance_forms.py",
        "historical": "eval/instance_form_smoke_report.json",
        "artifact": "regression/006_instance_form_smoke_report.json",
        "extract": "smoke",
        "direct": "smoke",
        "caliber": "006 instance-form smoke: writer + reader, the first 11 baseline queries each",
    },
    {
        "group": "007_hybrid_18",
        "runner": "eval/run_comparison.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/unit/test_query_planner_schema.py (007 domain-profile caliber precedent)",
        "historical": "eval/007_hybrid_report.json",
        "artifact": "regression/007_hybrid_18_report.json",
        "extract": "comparison",
        "caliber": "007 domain generalization, hybrid caliber: eval_dataset.json --limit 18",
        "command": ["{python}", "-X", "utf8", "eval/run_comparison.py", "--dataset", "eval/eval_dataset.json",
                    "--output", "{artifact}", "--limit", "18",
                    "--format-report", "{regression}/007_hybrid_18_format_report.json"],
    },
    {
        "group": "007_graph_37",
        "runner": "eval/run_graph_comparison.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/unit/test_query_planner_schema.py (007 domain-profile caliber precedent)",
        "historical": "eval/007_graph_report.json",
        "artifact": "regression/007_graph_37_report.json",
        "extract": "graph",
        "caliber": "007 domain generalization, graph caliber: eval_dataset.json --limit 37",
        "command": ["{python}", "-X", "utf8", "eval/run_graph_comparison.py", "--dataset", "eval/eval_dataset.json",
                    "--output", "{artifact}", "--limit", "37", "--skip-reproducibility"],
    },
    {
        "group": "008_regression",
        "runner": "eval/run_eval.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": "eval/008_regression_report.json",
        "artifact": "regression/008_regression_report.json",
        "extract": "dense",
        "caliber": "008 ingestion-channel regression: recovered from the produced artifact itself, not from the "
                   "task text. eval/008_regression_report.json (commit 616ba94, 008 T060/T062) is a "
                   "dense_retrieval_baseline document whose config records dataset_path eval/eval_dataset.json, "
                   "num_queries 56, retrieval_mode hybrid, top_k 5, and which carries a `gate` block - a block "
                   "run_eval.py emits only under --regression-gate. eval/eval_dataset.json is byte-unchanged "
                   "since that commit, so the caliber is exactly `run_eval.py --dataset eval/eval_dataset.json "
                   "--mode hybrid --regression-gate --no-reproducibility-check`",
        "command": ["{python}", "-X", "utf8", "eval/run_eval.py", "--dataset", "eval/eval_dataset.json",
                    "--mode", "hybrid", "--regression-gate", "--no-reproducibility-check",
                    "--output", "{artifact}"],
    },
    {
        "group": "009_graph_37",
        "runner": "eval/run_graph_comparison.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/unit/test_query_planner_schema.py (009 domain-neutral caliber precedent)",
        "historical": "eval/graph_enhanced_comparison_report.json",
        "artifact": "regression/009_graph_37_report.json",
        "extract": "graph",
        "caliber": "009 domain-neutral rerun of the 004 deterministic set: eval_dataset.json full (56 entries, "
                   "graph caliber) against the 004 historical report",
        "command": ["{python}", "-X", "utf8", "eval/run_graph_comparison.py", "--dataset", "eval/eval_dataset.json",
                    "--output", "{artifact}", "--limit", "37", "--skip-reproducibility"],
    },
    {
        "group": "009_agentic_63",
        "runner": "eval/run_agentic_comparison.py",
        "mode": "record_then_replay",
        "model_dependent": True,
        "test_module": "backend/tests/unit/test_query_planner_schema.py (009 structural equivalence precedent)",
        "historical": "eval/agentic_comparison_report.json",
        "artifact": "regression/009_agentic_replay.json",
        "extract": "agentic",
        "cache_dir": "regression/005-llm-cache",
        "reuse_record": {
            "artifact": "regression/005_agentic_record.json",
            "why": "009's agentic caliber is the same runner/dataset/caliber as 005_agentic_63, and 009's own "
                   "verification re-ran 004+005 without persisting a 009-prefixed artifact. The record round "
                   "therefore already exists in this run id: re-running it would repeat ~151 live billable "
                   "provider calls for the same frozen cache, so the replay round consumes that frozen cache "
                   "instead. The record's own provider-call count stays null (the v1 census could not observe "
                   "provider transports on this host); the measured pass basis is the replay round's counter.",
        },
        "caliber": "009 rerun of the 005 agentic caliber (63 combined entries), judged on the replay round only "
                   "(real provider transports must be 0), consuming the 005 record round's frozen cache",
        "rounds": [
            {"round": "record", "artifact": "regression/005_agentic_record.json", "instrumented": True,
             "command": ["{python}", "-X", "utf8", "eval/run_agentic_comparison.py",
                         "--dataset", "eval/eval_dataset.json",
                         "--agentic-dataset", "eval/agentic_eval_dataset.json",
                         "--llm-cache-dir", "{cachedir}",
                         "--output", "{artifact}", "--skip-repeatability"]},
            {"round": "replay", "artifact": "regression/009_agentic_replay.json", "instrumented": True,
             "command": ["{python}", "-X", "utf8", "eval/run_agentic_comparison.py",
                         "--dataset", "eval/eval_dataset.json",
                         "--agentic-dataset", "eval/agentic_eval_dataset.json",
                         "--llm-cache-dir", "{cachedir}", "--keep-llm-cache",
                         "--output", "{artifact}", "--skip-repeatability"]},
        ],
    },
    {
        "group": "010_graph_regression",
        "runner": "eval/run_graph_comparison.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": "eval/010_graph_regression_report.json",
        "artifact": "regression/010_graph_regression_report.json",
        "extract": "graph",
        "caliber": "010 graph-relation-registry regression: eval_dataset.json --limit 37 rerun of the same caliber "
                   "004 compares against; own artifact so the two groups are measured separately",
        "command": ["{python}", "-X", "utf8", "eval/run_graph_comparison.py", "--dataset", "eval/eval_dataset.json",
                    "--output", "{artifact}", "--limit", "37", "--skip-reproducibility"],
    },
    {
        "group": "010_cross_reference",
        "runner": "eval/run_cross_reference_comparison.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": "eval/cross_reference_comparison_report.json",
        "artifact": "regression/010_cross_reference_report.json",
        "extract": None,
        "caliber": "010 cross-reference benefit comparison on the legal-domain benefit subset",
        "command": ["{python}", "-X", "utf8", "eval/run_cross_reference_comparison.py",
                    "--dataset", "eval/cross_reference_eval_dataset.json", "--output", "{artifact}"],
    },
    {
        "group": "011_ingest_domain_corpora",
        "runner": "eval/ingest_domain_corpora.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": None,
        "artifact": "regression/011_ingest_domain_corpora.outcome.json",
        "extract": None,
        "no_artifact_expected": True,
        "caliber": "011 domain-corpus idempotent ingestion (personal/generic/legal, one scope per file)",
        "command": ["{python}", "-X", "utf8", "eval/ingest_domain_corpora.py"],
    },
    {
        "group": "011_legal_benefit",
        "runner": "eval/run_legal_benefit.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": "eval/legal_benefit_result.json",
        "artifact": "regression/011_legal_benefit_result.json",
        "extract": None,
        "caliber": "011 cross-reference benefit re-verification (Q1=A dual-branch gate; a new artifact path keeps "
                   "the historical eval/legal_benefit_result.json untouched)",
        "command": ["{python}", "-X", "utf8", "eval/run_legal_benefit.py", "--output", "{artifact}"],
    },
    {
        "group": "011_domain_baseline_generic",
        "runner": "eval/run_domain_baseline.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": "eval/generic_domain_baseline_report.json",
        "artifact": "regression/011_generic_domain_baseline_report.json",
        "extract": "dense",
        "caliber": "011 personal/generic domain baseline (non-binding anchor, dense/hybrid 13 queries)",
        "command": ["{python}", "-X", "utf8", "eval/run_domain_baseline.py",
                    "--dataset", "eval/generic_domain_eval_dataset.json",
                    "--output", "{artifact}", "--domain-key", "personal"],
    },
    {
        "group": "011_domain_baseline_legal",
        "runner": "eval/run_domain_baseline.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": "eval/legal_domain_baseline_report.json",
        "artifact": "regression/011_legal_domain_baseline_report.json",
        "extract": "dense",
        "caliber": "011 legal domain baseline (non-binding anchor, 11 queries)",
        "command": ["{python}", "-X", "utf8", "eval/run_domain_baseline.py",
                    "--dataset", "eval/legal_domain_eval_dataset.json",
                    "--output", "{artifact}", "--domain-key", "legal",
                    "--benefit-report", "eval/legal_benefit_result.json"],
    },
    {
        "group": "011_multi_domain_acceptance",
        "runner": "eval/run_multi_domain_acceptance.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": "eval/multi_domain_acceptance_report.json",
        "artifact": "regression/011_multi_domain_acceptance_report.json",
        "extract": None,
        "caliber": "011 multi-domain end-to-end acceptance (scenarios + the three hard metrics, per-item measurement)",
        "command": ["{python}", "-X", "utf8", "eval/run_multi_domain_acceptance.py", "--output", "{artifact}"],
    },
    {
        "group": "011_regression_011",
        "runner": "eval/run_regression_011.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": NO_DEDICATED_MODULE,
        "historical": "eval/011_regression_summary.json",
        "artifact": "regression/011_regression/012_regression_summary.json",
        "extract": None,
        "caliber": "011's own six-group rerun, narrowed to the deterministic groups (001/002/003/004/006) because the "
                   "011 group set also contains the model-dependent 005 agentic caliber, which T059 requires to be "
                   "judged by a record+replay round - the live 005 result must not be the pass basis",
        "prepare_empty_dir": "regression/011_regression",
        "command": ["{python}", "-X", "utf8", "eval/run_regression_011.py",
                    "--output-dir", "{regression}/011_regression",
                    "--group", "001_dense_11", "--group", "002_hybrid_18", "--group", "003_format_37",
                    "--group", "004_graph_37", "--group", "006_smoke_11x2"],
    },
    {
        "group": "012_acceptance",
        "runner": "eval/run_memory_acceptance.py",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/integration/test_012_memory_e2e.py",
        "historical": "eval/runs/012-20261005-final-regression-h/final-memory-report-verified.json",
        "artifact": "regression/012_acceptance_report.json",
        "extract": None,
        "caliber": "012 final acceptance report: the 012-era suite junit, memory trace, host evidence and read "
                   "diagnostics are read as real inputs and the runner re-validates the assembled report against the "
                   "012 acceptance-report schema; the exit code is the acceptance verdict. SC-012 additionally "
                   "requires the in-run regression evidence (the runner marks SC-012 not_verified when no "
                   "--regression report is supplied: measured 2026-10-10, omitting it kept the report at "
                   "status=incomplete with all other 16 criteria passed)",
        "inputs_are_read_only": [
            "eval/runs/012-20261005-final-regression-h/backend-pytest.xml",
            "eval/runs/012-20261005-final-regression-h/memory-trace.json",
            "eval/runs/012-20261005-final-regression-h/host-evidence.json",
            "eval/runs/012-20261005-final-regression-h/read-diagnostics.json"
        ],
        "command": ["{python}", "-X", "utf8", "eval/run_memory_acceptance.py",
                    "--suite", "eval/runs/012-20261005-final-regression-h/backend-pytest.xml",
                    "--trace", "eval/runs/012-20261005-final-regression-h/memory-trace.json",
                    "--host", "eval/runs/012-20261005-final-regression-h/host-evidence.json",
                    "--diagnostics", "eval/runs/012-20261005-final-regression-h/read-diagnostics.json",
                    "--output", "{artifact}",
                    "--regression", "{regression}/011_regression/012_regression_summary.json",
                    "--regression", "{regression}/004_graph_37_report.json",
                    "--regression", "{regression}/010_graph_regression_report.json",
                    "--suite-command",
                    "python -m pytest -vv --tb=short --durations=30 "
                    "--junitxml=eval/runs/012-20261005-final-regression-h/backend-pytest.xml"],
    },
    {
        "group": "012_e2e",
        "runner": "python -m pytest (cwd backend)",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/integration/test_012_memory_e2e.py",
        "historical": None,
        "artifact": "regression/pytest/012_e2e.junit.xml",
        "extract": None,
        "pytest": True,
        "pytest_target": "tests/integration/test_012_memory_e2e.py",
        "caliber": "012 memory E2E suite as run by the 014 regression-evidence listing",
        "command": ["{python}", "-m", "pytest", "tests/integration/test_012_memory_e2e.py", "-q", "--no-header",
                    "-p", "no:cacheprovider", "--junitxml", "{artifact}"],
    },
    {
        "group": "012_old_client_compat",
        "runner": "python -m pytest (cwd backend)",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/contract/test_012_old_tool_compat.py",
        "historical": None,
        "artifact": "regression/pytest/012_old_client_compat.junit.xml",
        "extract": None,
        "pytest": True,
        "pytest_target": "tests/contract/test_012_old_tool_compat.py",
        "caliber": "012 old-client byte compatibility contract suite",
        "command": ["{python}", "-m", "pytest", "tests/contract/test_012_old_tool_compat.py", "-q", "--no-header",
                    "-p", "no:cacheprovider", "--junitxml", "{artifact}"],
    },
    {
        "group": "012_reader_boundaries",
        "runner": "python -m pytest (cwd backend)",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/integration/test_012_reader_boundaries.py",
        "historical": None,
        "artifact": "regression/pytest/012_reader_boundaries.junit.xml",
        "extract": None,
        "pytest": True,
        "pytest_target": "tests/integration/test_012_reader_boundaries.py",
        "caliber": "012 reader boundary suite",
        "command": ["{python}", "-m", "pytest", "tests/integration/test_012_reader_boundaries.py", "-q",
                    "--no-header", "-p", "no:cacheprovider", "--junitxml", "{artifact}"],
    },
    {
        "group": "013_e2e",
        "runner": "python -m pytest (cwd backend)",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/integration/test_013_consolidation_e2e.py",
        "historical": None,
        "artifact": "regression/pytest/013_e2e.junit.xml",
        "extract": None,
        "pytest": True,
        "pytest_target": "tests/integration/test_013_consolidation_e2e.py",
        "requires_isolated_database": True,
        "caliber": "013 consolidation E2E suite (014 regression-evidence listing) run against the isolated 013 "
                   "database: this suite creates 013 scopes, and consolidation_fixtures.create_scope refuses to write "
                   "into the shared acceptance database by product design",
        "command": ["{python}", "-m", "pytest", "tests/integration/test_013_consolidation_e2e.py", "-q",
                    "--no-header", "-p", "no:cacheprovider", "--junitxml", "{artifact}"],
    },
    {
        "group": "014_e2e",
        "runner": "python -m pytest (cwd backend)",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/integration/test_014_memory_e2e.py",
        "historical": None,
        "artifact": "regression/pytest/014_e2e.junit.xml",
        "extract": None,
        "pytest": True,
        "pytest_target": "tests/integration/test_014_memory_e2e.py",
        "caliber": "014 memory-aware retrieval E2E suite (014 regression-evidence listing)",
        "command": ["{python}", "-m", "pytest", "tests/integration/test_014_memory_e2e.py", "-q", "--no-header",
                    "-p", "no:cacheprovider", "--junitxml", "{artifact}"],
    },
    {
        "group": "014_contract",
        "runner": "python -m pytest (cwd backend)",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/contract (whole directory, as listed by run_014_regression_evidence.SUITES)",
        "historical": None,
        "artifact": "regression/pytest/014_contract.junit.xml",
        "extract": None,
        "pytest": True,
        "pytest_target": "tests/contract",
        "requires_isolated_database": True,
        "caliber": "014 regression-evidence contract listing: the whole backend/tests/contract directory, run against "
                   "the isolated 013 database so the 013 consolidation-scope contract suites execute instead of "
                   "failing at fixture setup (measured 2026-10-10: on the shared database the same four 013 modules "
                   "fail with '013 writes require the explicitly isolated database')",
        "command": ["{python}", "-m", "pytest", "tests/contract", "-q", "--no-header",
                    "-p", "no:cacheprovider", "--junitxml", "{artifact}"],
    },
    {
        "group": "014_consumption_projection",
        "runner": "python -m pytest (cwd backend)",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/integration/test_014_consumption_projection.py",
        "historical": None,
        "artifact": "regression/pytest/014_consumption_projection.junit.xml",
        "extract": None,
        "pytest": True,
        "pytest_target": "tests/integration/test_014_consumption_projection.py",
        "caliber": "014 consumption-projection suite (014 regression-evidence listing)",
        "command": ["{python}", "-m", "pytest", "tests/integration/test_014_consumption_projection.py", "-q",
                    "--no-header", "-p", "no:cacheprovider", "--junitxml", "{artifact}"],
    },
    {
        "group": "014_no_bypass",
        "runner": "python -m pytest (cwd backend)",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "backend/tests/integration/test_014_no_bypass.py",
        "historical": None,
        "artifact": "regression/pytest/014_no_bypass.junit.xml",
        "extract": None,
        "pytest": True,
        "pytest_target": "tests/integration/test_014_no_bypass.py",
        "caliber": "014 no-bypass suite (014 regression-evidence listing)",
        "command": ["{python}", "-m", "pytest", "tests/integration/test_014_no_bypass.py", "-q",
                    "--no-header", "-p", "no:cacheprovider", "--junitxml", "{artifact}"],
    },
    {
        "group": "013_consolidation_comparison",
        "runner": "eval/run_consolidation_comparison.py",
        "mode": "record_then_replay",
        "model_dependent": True,
        "test_module": "backend/tests/unit/test_consolidation_comparison_runner.py",
        "historical": "eval/memory-gate-report-014.json",
        "artifact": "regression/013-consolidation/013_consolidation_replay.json",
        "snapshot": "regression/013-consolidation/authority-snapshot.json",
        "snapshot_builder": ("eval/run_regression_015.py --build-013-snapshot: re-exports the sealed authority of "
                             "C:/t102/capsule (capsule_version 013.restore.1, capsule_database "
                             "memory_consolidation_013_capsule_t102a) with consolidation_restore_support."
                             "authority_snapshot, reads the frozen scope's real domain_profiles.memory_policy, and "
                             "refuses to emit anything unless the recomputed digest equals the frozen dataset "
                             "snapshot_hash and the cutoff matches"),
        "caliber": "013 consolidation record -> replay on the frozen six-query dataset: the record round runs on "
                   "six independently restored copies of the sealed unconsolidated authority and seals the strict "
                   "cache manifest; the replay round re-restores the replay identities from the same capsule and "
                   "consumes exactly that sealed cache, so its real provider transports must be 0",
        "subprocess_steps": [
            {"round": "record", "artifact": "regression/013-consolidation/013_consolidation_record.json",
             "instrumented": False,
             # 013's comparison runner declares exit 2 as its own real "incomplete"
             # outcome (its published conclusion IS incomplete: default_enable_eligible
             # false, no claimable benefit). A non-zero exit is therefore an executed
             # outcome here, not a failure to execute; the replay round remains the
             # only pass basis and still has to measure zero real network calls.
             "allow_nonzero_exit": True,
             # A real record round already on disk is reused rather than re-frozen, so
             # the replay consumes exactly that sealed cache (see resume_existing_artifact
             # in _execute_subprocess_steps). Never overwrites it.
             "resume_existing_artifact": True,
             # The session environment carries NO_PROXY='localhost,127.0.0.1,::1,[::1]',
             # whose bracketed entry makes httpx build an invalid URLPattern
             # (``InvalidURL: Invalid port: ':1]'``) for EVERY sync client, so the
             # capsule restore could not construct its local Qdrant client at all
             # (measured: all three of http://[::1]:P, http://127.0.0.1:P and
             # http://localhost:P failed as-is and all three succeed with this value).
             # Overridden for these steps only; nothing global is changed.
             "env": {"NO_PROXY": "localhost,127.0.0.1,::1", "no_proxy": "localhost,127.0.0.1,::1"},
             "log": "013_consolidation_comparison.record.log",
             "command": ["{python}", "-X", "utf8", "eval/run_consolidation_comparison.py",
                         "--dataset", "eval/consolidation_eval_dataset.json",
                         "--snapshot", "{snapshot}",
                         "--mode", "record",
                         "--cache-manifest", "{regression}/013-consolidation/strict-cache-manifest.json",
                         "--gate-variant", "consolidated_candidate_expansion",
                         "--output", "{artifact}",
                         "--run-id", SCRATCH_013_RUN_ID,
                         "--base", SCRATCH_013_BASE,
                         "--capsule-dir", "C:/t102/capsule", "--restore",
                         "--qdrant-port-base", str(SCRATCH_013_PORT_BASE),
                         "--evidence-dir", "{regression}/013-consolidation/evidence"]},
            {"round": "replay", "artifact": "regression/013-consolidation/013_consolidation_replay.json",
             "instrumented": True, "pass_basis": True,
             # 013's own published conclusion IS `status=failed` /
             # `default_enable_eligible=false` (no claimable benefit), so the replay
             # runner's exit code carries that verdict, not an execution failure. The
             # pass basis stays "this replay round measured zero real provider
             # transports"; the group's outcome is then derived as "the published
             # conclusion is unchanged against the declared historical".
             "allow_nonzero_exit": True,
             # A completed real replay measurement already on disk is adopted as the
             # pass basis when its own recorded counter is 0 (never overwritten);
             # anything else refuses adoption and the group is not executed.
             "resume_existing_artifact": True,
             "env": {"NO_PROXY": "localhost,127.0.0.1,::1", "no_proxy": "localhost,127.0.0.1,::1"},
             "log": "013_consolidation_comparison.replay.log",
             "command": ["{python}", "-X", "utf8", "eval/run_consolidation_comparison.py",
                         "--dataset", "eval/consolidation_eval_dataset.json",
                         "--snapshot", "{snapshot}",
                         "--mode", "replay",
                         "--cache-manifest", "{regression}/013-consolidation/strict-cache-manifest.json",
                         "--gate-variant", "consolidated_candidate_expansion",
                         "--output", "{artifact}",
                         "--run-id", SCRATCH_013_REPLAY_RUN_ID,
                         "--base", SCRATCH_013_BASE,
                         "--capsule-dir", "C:/t102/capsule", "--restore",
                         "--qdrant-port-base", str(SCRATCH_013_PORT_BASE),
                         "--evidence-dir", "{regression}/013-consolidation/evidence"]},
        ],
    },
    {
        "group": "014_continuity_gate",
        "runner": "eval/run_memory_comparison.py + eval/archive_memory_gate_report.py",
        "mode": "record_then_replay",
        "model_dependent": True,
        "test_module": "backend/tests/integration/test_014_memory_e2e.py",
        "historical": "eval/memory-gate-report-014.json",
        "artifact": "eval/runs/015-20261009205637/continuity-replay/memory-replay.json",
        "extract": None,
        "reuse_measured_evidence": True,
        "caliber": "014 memory-aware retrieval gate: record round freezes the model responses and the cache fingerprint, "
                   "then the replay round (measured real provider transports = 0) is the only pass basis",
        "reuse": {
            "produced_by": "phase 5 of this same run id (eval/runs/015-20261009205637/continuity-replay/)",
            "record_artifact": None,
            "replay_artifact": "eval/runs/015-20261009205637/continuity-replay/memory-replay.json",
            "summary_artifact": "eval/runs/015-20261009205637/continuity-replay/run-summary-replay.json",
            "measured_fields": ["cache.manifest_hash", "cache.record_real_network_calls",
                                "cache.replay_real_network_calls", "gates.replay_zero_network"],
            "why_reused": "the parent task explicitly allows reusing this record+replay evidence; the measured counters "
                          "are read from the artifact, never typed in, and a fresh record round would repeat 32 live "
                          "provider transports against a shared development PostgreSQL",
        },
    },
    {
        "group": "014_hard_metrics",
        "runner": "eval/hard_metrics_014.py (module-level measure(), called through the generated wrapper)",
        "mode": "single_round",
        "model_dependent": False,
        "test_module": "n/a (the module has no CLI and no test entry point)",
        "historical": "eval/hard-metrics-014.json",
        "artifact": "regression/014-hard-metrics/hard-metrics.json",
        "direct": "hard_metrics",
        "wrapper_name": "_hard_metrics_014_runner.py",
        "verdict_from": ["view_keys_unchanged", "unchanged"],
        "caliber": "014 hard-metrics measurement kernel: measure() over the live 014 scopes, written to this "
                   "run's own directory; the module's main() is never called because it rewrites the tracked "
                   "eval/hard-metrics-014.json",
    },
]

GROUPS_BY_ID = {spec["group"]: spec for spec in GROUP_SPECS}


# --------------------------------------------------------------------------- #
# paths and small helpers
# --------------------------------------------------------------------------- #


class Run:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.dir = EVAL_DIR / "runs" / run_id
        self.regression = self.dir / "regression"
        self.datasets = self.regression / "datasets"
        self.logs = self.regression / "logs"
        self.status = self.regression / "_status"
        self.evidence_dir = self.dir / "evidence"
        self.netcount = self.regression / NETCOUNT_NAME

    def ensure(self) -> None:
        for path in (self.dir, self.regression, self.datasets, self.logs, self.status, self.evidence_dir):
            path.mkdir(parents=True, exist_ok=True)
        if not self.netcount.exists() or "015-T059-netcount-v2" not in self.netcount.read_text(
                encoding="utf-8", errors="replace"):
            # generated instrument of this run (never a historical artifact): refresh it
            # in place when it is missing or pre-dates the current counting rule.
            self.netcount.write_text(_NETCOUNT_SOURCE, encoding="utf-8", newline="\n")

    def artifact(self, relative: str) -> Path:
        return (REPO_ROOT / relative) if relative.startswith("eval/") else (self.dir / relative)

    def relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return path.as_posix()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _render(command: list[str], run: Run, artifact_rel: str | None, cache_dir: str | None) -> list[str]:
    mapping = {
        "python": PY,
        "run": str(run.dir),
        "regression": str(run.regression),
        "datasets": str(run.datasets),
        "artifact": str(run.artifact(artifact_rel)) if artifact_rel else "",
        "cachedir": str(run.artifact(cache_dir)) if cache_dir else "",
        "snapshot": str(run.artifact(_ACTIVE_SPEC.get("snapshot"))) if (_ACTIVE_SPEC or {}).get("snapshot") else "",
    }
    rendered: list[str] = []
    for token in command:
        for key, value in mapping.items():
            token = token.replace("{" + key + "}", value)
        rendered.append(token)
    return rendered


def _guard_command(command: list[str], run: Run) -> list[str]:
    """Refuse any runner argument that would write outside the run directory."""
    output_flags = {"--output", "--format-report", "--cache-manifest", "--run-out",
                    "--output-dir", "--junitxml", "--evidence-dir"}
    guarded = list(command)
    for index, token in enumerate(guarded):
        if token in output_flags and index + 1 < len(guarded):
            value = guarded[index + 1]
            if not value.startswith(("http://", "https://")):
                resolved = Path(value)
                resolved = resolved if resolved.is_absolute() else (REPO_ROOT / resolved)
                resolved = resolved.resolve()
                try:
                    resolved.relative_to(run.dir.resolve())
                except ValueError as error:
                    raise SystemExit(
                        f"history zero-overwrite refusal: {token} {value} escapes the run directory "
                        f"{run.dir} (would touch a historical artifact / the tracked report)") from error
    return guarded


def _write_new_json(path: Path, payload: dict) -> None:
    """Zero-overwrite: never replace an existing file with different bytes."""
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if path.exists():
        if path.read_bytes() == text.encode("utf-8"):
            return
        raise SystemExit(f"refusing to overwrite {path}: it already exists with different bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_run_owned(run: "Run", path: Path, payload: dict) -> None:
    """Refresh a derived index/record that belongs to *this* run.

    Used for the regression group map (regenerated as groups complete) and for the
    T060 block-validation record. It refuses any target outside the run directory
    and any existing file that is not a record of this same run id, so a
    historical artifact can never be clobbered through it. Every per-group
    caliber artifact still goes through the strict ``_write_new_json``.
    """
    try:
        path.resolve().relative_to(run.dir.resolve())
    except ValueError as error:
        raise SystemExit(f"refusing to write {path}: it is outside the run directory {run.dir}") from error
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError as error:
            raise SystemExit(f"refusing to overwrite unreadable {path}") from error
        if existing.get("run_id") != payload.get("run_id"):
            raise SystemExit(f"refusing to overwrite {path}: it is not a record of run {payload.get('run_id')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
                    encoding="utf-8", newline="\n")


#: Name of the isolated database the 013-writing calibers run against. Set from
#: ``--isolated-database`` in ``main``; a spec only declares the requirement.
ISOLATED_DATABASE = "memory_consolidation_013_015regr_pytest"


def _isolated_environment(database: str | None = None) -> dict[str, str]:
    """Extra child environment for calibers that write 013 consolidation state.

    Those tests refuse to run against the shared acceptance database by their own
    product guard (``consolidation_fixtures.create_scope`` asserts
    ``CONSOLIDATION_ISOLATED_DATABASE == DATABASE_URL.database``). The isolated
    database is a native template copy of the sealed 013 capsule, refreshed before
    the run, so the caliber executes for real instead of failing at fixture setup.
    """
    from sqlalchemy.engine import make_url

    database = database or ISOLATED_DATABASE
    base = os.environ["DATABASE_URL"]
    sync_base = os.environ.get("DATABASE_URL_SYNC") or base.replace("+asyncpg", "+psycopg2")
    return {
        "DATABASE_URL": make_url(base).set(database=database).render_as_string(hide_password=False),
        "DATABASE_URL_SYNC": make_url(sync_base).set(database=database).render_as_string(hide_password=False),
        "CONSOLIDATION_ISOLATED_DATABASE": database,
    }


def provision_isolated_database(name: str, template: str | None) -> dict:
    """Refresh the isolated 013 database from the sealed capsule template."""
    sys.path.insert(0, str(EVAL_DIR))
    from consolidation_restore_support import (create_database, database_exists, drop_database,
                                               require_isolated_database, terminate_connections)

    require_isolated_database(name)
    existed = database_exists(name)
    if existed:
        dropped = terminate_connections(name)
        drop_database(name)
    else:
        dropped = 0
    create_database(name, template=template)
    return {"database": name, "template": template, "existed_before": existed,
            "terminated_connections": dropped, "refreshed_at": _now()}


def _run_process(command: list[str], log_path: Path, timeout: int, cwd: Path,
                 env_extra: dict[str, str] | None = None) -> dict:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    if env_extra:
        environment.update(env_extra)
    started = time.time()
    with open(log_path, "w", encoding="utf-8", newline="\n") as log:
        try:
            completed = subprocess.run(command, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                                       env=environment, timeout=timeout, check=False)
            code: int | None = completed.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            code, timed_out = None, True
    return {"command": command, "exit_code": code, "timed_out": timed_out,
            "duration_seconds": round(time.time() - started, 3),
            "log": str(log_path), "started_at": datetime.fromtimestamp(started, UTC).isoformat()}


def _tail(path: Path, lines: int = 25) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


# --------------------------------------------------------------------------- #
# prepare helpers
# --------------------------------------------------------------------------- #


def _prepare_datasets(run: Run) -> dict[str, str]:
    source = _load_json(EVAL_DIR / "eval_dataset.json")
    for count in (11, 37):
        target = _dataset(run.datasets, count)
        payload = json.dumps(source[:count], ensure_ascii=False, indent=2) + "\n"
        if target.exists() and target.read_bytes() != payload.encode("utf-8"):
            raise SystemExit(f"refusing to overwrite {target} with different bytes")
        target.write_text(payload, encoding="utf-8", newline="\n")
    return {"dataset_11": str(_dataset(run.datasets, 11)), "dataset_37": str(_dataset(run.datasets, 37))}


def _cache_manifest(cache_dir: Path) -> dict:
    """Fingerprint of the frozen model-response cache written by the record round."""
    if not cache_dir.exists():
        return {"manifest_hash": None, "file_count": 0, "bytes": 0, "files": [],
                "reason": f"the record round wrote no cache directory at {cache_dir}"}
    entries = []
    for path in sorted(p for p in cache_dir.rglob("*") if p.is_file()):
        entries.append({"path": path.relative_to(cache_dir).as_posix(), "sha256": _sha256_file(path),
                        "bytes": path.stat().st_size})
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {"manifest_hash": _sha256_bytes(payload), "file_count": len(entries),
            "bytes": sum(entry["bytes"] for entry in entries),
            "files": [entry["path"] for entry in entries], "cache_dir": str(cache_dir)}


def _compare_to_historical(spec: dict, artifact: Path) -> dict | None:
    """Non-latency 1% relative tolerance against the historical caliber report."""
    extractor = EXTRACTORS.get(spec.get("extract") or "")
    historical_rel = spec.get("historical")
    if extractor is None or not historical_rel or not artifact.exists():
        return None
    historical = REPO_ROOT / historical_rel
    if not historical.exists():
        return {"non_latency_reproducible": None,
                "reason": f"historical reference {historical_rel} is not present"}
    try:
        new_metrics = extractor(_load_json(artifact))
        old_metrics = extractor(_load_json(historical))
    except Exception as error:  # noqa: BLE001 - an unreadable caliber is not a measurement
        return {"non_latency_reproducible": None,
                "reason": f"caliber metrics could not be extracted: {type(error).__name__}: {error}"}
    checks = []
    reproducible = bool(old_metrics) and set(new_metrics) == set(old_metrics)
    for name in sorted(set(new_metrics) & set(old_metrics)):
        old, new = old_metrics[name], new_metrics[name]
        if old == 0 and new == 0:
            delta, within = 0.0, True
        elif old == 0 or new == 0:
            delta, within = abs(old - new), abs(old - new) <= TOLERANCE
        else:
            delta = abs(old - new) / max(abs(old), abs(new))
            within = delta <= TOLERANCE
        reproducible = reproducible and within
        checks.append({"metric": name, "historical": round(old, 6), "rerun": round(new, 6),
                       "relative_delta": round(delta, 6), "tolerance": TOLERANCE, "passed": within})
    return {"non_latency_reproducible": reproducible, "tolerance": TOLERANCE,
            "historical_report": historical_rel, "checks": checks,
            "caliber": "non-latency metrics only, 1% relative tolerance (latency.env_sensitive is excluded)"}


def _hard_metrics_comparison(artifact: Path, historical_rel: str = "eval/hard-metrics-014.json") -> dict | None:
    """1% non-latency comparison of the 014 hard-metrics document.

    The hard-metrics caliber is not a flat metric block: every entry is a
    measurement object with its own ``value``/``rate`` and its own denominator, so
    the comparison walks each ``metrics.<name>`` pair and compares the measured
    numeric slot.  Entries whose value is textual (``not_measurable``) are
    recorded verbatim and never turned into a number.  Denominators that are real
    live scope/database compositions (the 014 ``scope_selection`` block) are
    recorded as evidence but excluded from the reproducibility verdict, exactly as
    the 015 rule excludes latency: they are inputs, not caliber metrics.
    """
    historical = REPO_ROOT / historical_rel
    if not artifact.exists() or not historical.exists():
        return None
    try:
        new_doc = _load_json(artifact)
        old_doc = _load_json(historical)
    except Exception as error:  # noqa: BLE001 - an unreadable caliber is not a measurement
        return {"non_latency_reproducible": None,
                "reason": f"hard-metrics document could not be read: {type(error).__name__}: {error}"}
    excluded = {"scope_selection"}
    checks: list[dict] = []
    reproducible = True
    seen = 0
    for name in sorted(set(new_doc.get("metrics") or {}) | set(old_doc.get("metrics") or {})):
        old_entry = (old_doc.get("metrics") or {}).get(name)
        new_entry = (new_doc.get("metrics") or {}).get(name)
        if name in excluded:
            checks.append({"metric": name, "historical": old_entry, "rerun": new_entry,
                           "excluded_reason": "live scope/database composition: an input of the caliber, "
                                              "not a caliber metric",
                           "relative_delta": None, "tolerance": TOLERANCE, "passed": None})
            continue
        seen += 1
        old_value = _hard_metric_value(old_entry)
        new_value = _hard_metric_value(new_entry)
        if isinstance(old_value, bool) or isinstance(new_value, bool) or \
                not isinstance(old_value, (int, float)) or not isinstance(new_value, (int, float)):
            identical = old_value == new_value
            reproducible = reproducible and identical
            checks.append({"metric": name, "historical": old_value, "rerun": new_value,
                           "relative_delta": None, "tolerance": TOLERANCE, "passed": identical,
                           "value_kind": "non-numeric: compared for equality only"})
            continue
        if old_value == 0 and new_value == 0:
            delta, within = 0.0, True
        elif old_value == 0 or new_value == 0:
            delta = abs(old_value - new_value)
            within = delta <= TOLERANCE
        else:
            delta = abs(old_value - new_value) / max(abs(old_value), abs(new_value))
            within = delta <= TOLERANCE
        reproducible = reproducible and within
        checks.append({"metric": name, "historical": round(old_value, 6), "rerun": round(new_value, 6),
                       "relative_delta": round(delta, 6), "tolerance": TOLERANCE, "passed": within})
    return {"non_latency_reproducible": bool(reproducible and seen) if seen else None,
            "tolerance": TOLERANCE, "historical_report": historical_rel, "checks": checks,
            "excluded_from_verdict": sorted(excluded),
            "caliber": "hard-metrics measurement entries: numeric value/rate slots only, 1% relative "
                       "tolerance; the live scope_selection denominators are recorded, not verdicts"}


def _hard_metric_value(entry):
    """The measured slot of one hard-metrics entry (``value`` then ``rate``)."""
    if not isinstance(entry, dict):
        return entry
    for key in ("value", "rate", "leaks", "occurrences", "unchanged"):
        if key in entry:
            return entry[key]
    return None


# --------------------------------------------------------------------------- #
# group execution
# --------------------------------------------------------------------------- #


def _not_executed(spec: dict, reason: str, rounds: list[dict] | None = None) -> dict:
    return {"group": spec["group"], "runner": spec["runner"], "mode": spec["mode"],
            "model_dependent": bool(spec.get("model_dependent")), "test_module": spec["test_module"],
            "caliber": spec.get("caliber"), "command": _command_text(spec, rounds),
            "rounds": rounds or [], "executed": False, "artifact": None,
            "historical": spec.get("historical"), "not_executed_reason": reason,
            "cache_manifest_hash": None, "replay_real_network_calls": None,
            "non_latency_reproducible": None, "checked_at": _now()}


def _command_text(spec: dict, rounds: list[dict] | None = None) -> str:
    if rounds:
        parts = []
        for item in rounds:
            command = item.get("command")
            if isinstance(command, (list, tuple)):
                command = " ".join(str(token) for token in command)
            parts.append(f"{item.get('round', 'single')}: {command}")
        return " | ".join(parts)
    return " ".join(_render(spec.get("command") or [], _ACTIVE_RUN, spec.get("artifact"),
                            spec.get("cache_dir")))


_ACTIVE_RUN: Run | None = None
_ACTIVE_SPEC: dict | None = None


def run_smoke_group(run: Run, artifact_rel: str, timeout: int) -> dict:
    """Group 006: instance-form smoke by direct function call (the legacy runner
    hard-codes its own output path, so a direct call keeps history intact)."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from rag_mcp.config import get_settings
    from rag_mcp.eval.instance_form_smoke import load_baseline_queries, run_form_smoke
    from rag_mcp.indexing.qdrant_client import QdrantStore
    from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider

    artifact = run.artifact(artifact_rel)
    if artifact.exists():
        raise SystemExit(f"refusing to overwrite {artifact}: it already exists")

    async def _main() -> dict:
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        reports = {}
        try:
            for mode in ("writer", "reader"):
                reports[mode] = await run_form_smoke(
                    mode, session_factory=session_factory, qdrant_store=QdrantStore(),
                    embedding_provider=LocalCPUEmbeddingProvider(),
                    queries=load_baseline_queries(), top_k=5, tolerance=TOLERANCE)
        finally:
            await engine.dispose()
        return {"report_type": "instance_form_smoke", "generated_at": _now(), "instance_forms": reports}

    started = time.time()
    combined = asyncio.run(_main())
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"duration_seconds": round(time.time() - started, 3)}


def _execute_hard_metrics(spec: dict, run: Run, timeout: int) -> dict:
    """Group 014_hard_metrics: call the 014 measurement kernel through the wrapper.

    ``eval/hard_metrics_014.main()`` is never called: its L433-435 rewrites the
    tracked ``eval/hard-metrics-014.json``.  The wrapper configures RUN_ID/RUN_DIR
    to this run's own directory before importing the module and calls ``measure()``
    directly, so the tracked artifact is untouched (verified by git afterwards).
    """
    artifact = run.artifact(spec["artifact"])
    if artifact.exists():
        return _not_executed(spec, f"history zero-overwrite: {run.relative(artifact)} already exists")
    wrapper = run.regression / spec["wrapper_name"]
    wrapper.write_text(_HARD_METRICS_RUNNER, encoding="utf-8", newline="\n")
    log = run.logs / f"{spec['group']}.log"
    census = run.regression / f"{spec['group']}.netcount.json"
    info = _run_process([PY, "-X", "utf8", str(wrapper)], log, timeout, REPO_ROOT,
                        {"HARD_METRICS_RUN_ID": f"{run.run_id}-014-hard-metrics",
                         "HARD_METRICS_RUN_DIR": str(artifact.parent),
                         "HARD_METRICS_OUT": str(artifact),
                         "NETCOUNT_OUT": str(census)})
    if info["timed_out"]:
        return _not_executed(spec, f"the measurement kernel exceeded the {timeout}s budget", [info])
    if not artifact.exists():
        return _not_executed(spec, f"the measurement kernel exited {info['exit_code']} and wrote no document "
                                   f"(log: {run.relative(log)})", [info])
    measured = _load_json(census) if census.exists() else {}
    verdict = spec.get("verdict_from")
    outcome_verdict = None
    if verdict:
        document = _load_json(artifact)
        entry = (document.get("metrics") or {}).get(verdict[0]) or {}
        outcome_verdict = entry.get(verdict[1])
    outcome = {"group": spec["group"], "runner": spec["runner"], "mode": spec["mode"],
               "model_dependent": False, "test_module": spec["test_module"], "caliber": spec["caliber"],
               "command": " ".join([PY, "-X", "utf8", run.relative(wrapper)]),
               "rounds": [{"round": "single", **info, "artifact": run.relative(artifact),
                           "instrumented": True, "netcount": run.relative(census),
                           "measured_real_network_calls": measured.get("provider_calls")}],
               "executed": True, "artifact": run.relative(artifact), "historical": spec.get("historical"),
               "outcome": ("passed" if outcome_verdict in (1.0, 1, True) else "failed")
               if outcome_verdict is not None else ("passed" if info["exit_code"] == 0 else "failed"),
               "exit_code": info["exit_code"],
               "verdict_metric": verdict, "verdict_value": outcome_verdict,
               "measured_real_network_calls": measured.get("provider_calls"),
               "main_not_called": True,
               "tracked_artifact_untouched": "eval/hard-metrics-014.json",
               "execution_rule": "the 014 measurement kernel (measure()) ran to completion and produced its "
                                 "document under this run's directory; the module's main() was never called "
                                 "because it rewrites the tracked eval/hard-metrics-014.json",
               "not_executed_reason": None, "cache_manifest_hash": None,
               "replay_real_network_calls": None, "checked_at": _now()}
    comparison = _hard_metrics_comparison(artifact, spec.get("historical") or "eval/hard-metrics-014.json")
    outcome["non_latency_reproducible"] = (comparison or {}).get("non_latency_reproducible")
    outcome["comparison"] = comparison
    return outcome


def _execute_subprocess_steps(spec: dict, run: Run, timeout: int) -> dict:
    """Run a caliber that needs two invocations (013 record + replay) strictly serially.

    Only the steps the spec marks ``instrumented`` are wrapped in the v2 httpx
    transport counter; a live model round is deliberately NOT instrumented as a
    pass basis (its counter is recorded as evidence, and the group's measured
    replay count is the only zero that decides execution).  Steps run one after
    the other, never concurrently, because the shared PostgreSQL writer lease can
    block indefinitely.
    """
    rounds: list[dict] = []
    measured_replay: int | None = None
    replay_artifact: Path | None = None
    for index, step in enumerate(spec["subprocess_steps"]):
        artifact_rel = step.get("artifact")
        artifact = run.artifact(artifact_rel) if artifact_rel else None
        if artifact is not None and artifact.exists():
            if _is_failure_placeholder(artifact):
                number = len(list(artifact.parent.glob(f"{artifact.stem}.superseded-*{artifact.suffix}"))) + 1
                artifact.rename(artifact.with_name(f"{artifact.stem}.superseded-{number}{artifact.suffix}"))
            elif step.get("resume_existing_artifact"):
                # Explicit opt-in only. For a record+replay caliber, a REAL record
                # round already on disk must not be re-frozen: the replay has to
                # consume exactly that sealed cache. The step is recorded as reused
                # and the next step still has to pass its own measurement.
                #
                # The reused artifact's OWN status decides the code: a non-"passed"
                # status is carried as a non-zero exit so a failing caliber is never
                # laundered into outcome=passed just because no process was spawned here.
                artifact_status = None
                try:
                    artifact_status = json.loads(artifact.read_text(encoding="utf-8")).get("status")
                except (OSError, ValueError):
                    artifact_status = None
                rounds.append({"round": step.get("round"), "reused": True,
                               "exit_code": 0 if artifact_status == "passed" else 2,
                               "artifact_status": artifact_status,
                               "timed_out": False, "artifact": run.relative(artifact),
                               "log": None, "instrumented": bool(step.get("instrumented")),
                               "note": "an existing real record artifact was reused; it was NOT overwritten and "
                                       "its own status, not a spawned process, carries the verdict"})
                if step.get("pass_basis") and step.get("instrumented"):
                    # An existing REAL replay measurement can be adopted as the pass
                    # basis, but only when its own recorded counter is a measured zero.
                    # The caliber's own report carries the counter, so nothing is
                    # inferred: a non-zero or absent value refuses adoption.
                    try:
                        adopted = json.loads(artifact.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        adopted = {}
                    recorded_calls = ((adopted.get("cache") or {}).get("replay_real_network_calls")
                                      if isinstance(adopted, Mapping) else None)
                    if recorded_calls != 0:
                        return _not_executed(
                            spec, f"the existing replay artifact records "
                                  f"replay_real_network_calls={recorded_calls!r}; it cannot serve as the "
                                  f"zero-transport pass basis", rounds)
                    measured_replay = 0
                    replay_artifact = artifact
                    rounds[-1]["pass_basis_adopted"] = (
                        "the artifact's own measured replay_real_network_calls is 0; the replay was not re-run")
                continue
            else:
                return _not_executed(spec, f"history zero-overwrite: {run.relative(artifact)} already exists", rounds)
        if step.get("prepare_empty_dir"):
            target = run.artifact(step["prepare_empty_dir"])
            if target.exists() and any(target.iterdir()):
                return _not_executed(spec, f"{run.relative(target)} is not empty", rounds)
            target.mkdir(parents=True, exist_ok=True)
        command = _guard_command(_render(step["command"], run, artifact_rel, spec.get("cache_dir")), run)
        log = run.logs / (step.get("log") or f"{spec['group']}.{step['round']}.log")
        environment = dict(step.get("env") or {})
        census = None
        if step.get("instrumented"):
            census = run.regression / f"{spec['group']}.{step['round']}.netcount.json"
            environment["NETCOUNT_OUT"] = str(census)
            command = _instrument(command, run, census)
        info = _run_process(command, log, timeout, REPO_ROOT, environment or None)
        info.update({"round": step["round"], "instrumented": bool(step.get("instrumented")),
                     "log": run.relative(log)})
        if artifact is not None:
            info["artifact"] = run.relative(artifact)
        if census is not None:
            info["netcount"] = run.relative(census)
            measured = _load_json(census) if census.exists() else {}
            info["measured_real_network_calls"] = measured.get("provider_calls")
        rounds.append(info)
        if info["timed_out"]:
            return _not_executed(spec, f"the {step['round']} step exceeded the {timeout}s budget", rounds)
        if step.get("expect_artifact", True) and artifact is not None and not artifact.exists():
            return _not_executed(spec, f"the {step['round']} step exited {info['exit_code']} and produced no "
                                       f"artifact (log: {run.relative(log)})", rounds)
        if not step.get("allow_nonzero_exit", False) and info["exit_code"] != 0:
            return _not_executed(spec, f"the {step['round']} step exited {info['exit_code']} "
                                       f"(log: {run.relative(log)})", rounds)
        if step.get("pass_basis"):
            if not census or not census.exists():
                return _not_executed(spec, f"the {step['round']} step produced no network census", rounds)
            value = (_load_json(census) or {}).get("provider_calls")
            if value is None:
                return _not_executed(spec, f"the {step['round']} step recorded no provider-call measurement",
                                     rounds)
            measured_replay = int(value)
            replay_artifact = artifact
            if measured_replay != 0:
                return _not_executed(spec, f"the replay step made {measured_replay} real provider transport(s); "
                                           f"the replay round is the only pass basis and it is not zero", rounds)
    if measured_replay is None or replay_artifact is None:
        return _not_executed(spec, "no instrumented pass-basis round was produced", rounds)
    outcome = {"group": spec["group"], "runner": spec["runner"], "mode": spec["mode"],
               "model_dependent": bool(spec.get("model_dependent")), "test_module": spec["test_module"],
               "caliber": spec.get("caliber"), "command": _command_text(spec, rounds), "rounds": rounds,
               "executed": True, "artifact": run.relative(replay_artifact),
               "historical": spec.get("historical"), "not_executed_reason": None,
               "cache_manifest_hash": None, "replay_real_network_calls": measured_replay,
               "replay_zero_network": measured_replay == 0,
               "measured_by": "v2 httpx-transport provider counter (regression/_netcount_015.py)",
               "checked_at": _now()}
    manifest_rel = spec.get("cache_manifest")
    if manifest_rel:
        manifest_path = run.artifact(manifest_rel)
        if manifest_path.exists():
            outcome["cache_manifest_hash"] = _sha256_file(manifest_path)
            outcome["cache_manifest"] = run.relative(manifest_path)
    try:
        replay_report = _load_json(replay_artifact) if replay_artifact.exists() else {}
    except Exception as error:  # noqa: BLE001 - an unreadable report is not a measurement
        replay_report = {"unreadable": f"{type(error).__name__}: {error}"}
    spec_snapshot = spec.get("snapshot")
    if spec_snapshot:
        snapshot_path = run.artifact(spec_snapshot)
        if snapshot_path.exists():
            outcome["snapshot"] = run.relative(snapshot_path)
            outcome["snapshot_sha256"] = _sha256_file(snapshot_path)
    for key, path in (("record_report", (spec["subprocess_steps"][0] or {}).get("artifact")),
                      ("replay_report", (spec.get("subprocess_steps") or [{}, {}])[1].get("artifact"))):
        if path:
            resolved = run.artifact(path)
            outcome[key] = run.relative(resolved)
            try:
                outcome[f"{key}_sha256"] = _sha256_file(resolved) if resolved.exists() else None
            except OSError:
                outcome[f"{key}_sha256"] = None
    if isinstance(replay_report, dict) and replay_report:
        outcome["report_status"] = replay_report.get("status")
        outcome["runner_measured_replay_transport_calls"] = (replay_report.get("replayed") or {}).get(
            "transport_calls")
        outcome["runner_measured_record_transport_calls"] = (replay_report.get("recorded") or {}).get(
            "transport_calls")
    return outcome


def _execute_reused(spec: dict, run: Run) -> dict:
    """014 continuity gate: the record+replay evidence of this run id is reused,
    with the measured counters read out of the artifact (never typed in)."""
    artifact = run.artifact(spec["artifact"])
    if not artifact.exists():
        return _not_executed(spec, f"the reuse target {run.relative(artifact)} does not exist")
    report = _load_json(artifact)
    cache = report.get("cache") or {}
    gates = report.get("gates") or {}
    replay_calls = cache.get("replay_real_network_calls")
    record_calls = cache.get("record_real_network_calls")
    manifest_hash = cache.get("manifest_hash")
    if replay_calls is None or manifest_hash is None:
        return _not_executed(spec, f"{run.relative(artifact)} carries no measured replay counters")
    outcome = {
        "group": spec["group"], "runner": spec["runner"], "mode": spec["mode"],
        "model_dependent": True, "test_module": spec["test_module"], "caliber": spec["caliber"],
        "command": f"record round + replay round of this run id (see {run.relative(artifact)})",
        "rounds": [
            {"round": "record", "artifact": run.relative(artifact),
             "measured_real_network_calls": record_calls, "source": "cache.record_real_network_calls"},
            {"round": "replay", "artifact": run.relative(artifact),
             "measured_real_network_calls": replay_calls, "source": "cache.replay_real_network_calls"},
        ],
        "executed": True, "evidence_reused": True, "reused_from": run.relative(artifact),
        "reuse_reason": (spec.get("reuse") or {}).get("why_reused"),
        "artifact": run.relative(artifact), "historical": spec.get("historical"),
        "not_executed_reason": None,
        "cache_manifest_hash": manifest_hash, "replay_real_network_calls": int(replay_calls),
        "record_real_network_calls": None if record_calls is None else int(record_calls),
        "replay_zero_network": gates.get("replay_zero_network"),
        "non_latency_reproducible": (report.get("reproducibility") or {}).get("non_latency_reproducible"),
        "checked_at": _now(),
    }
    return outcome


def execute_group(spec: dict, run: Run, timeout: int, dry_run: bool = False) -> dict:
    global _ACTIVE_RUN, _ACTIVE_SPEC
    _ACTIVE_RUN = run
    _ACTIVE_SPEC = spec
    if dry_run:
        return {**_not_executed(spec, "dry run: not executed"), "command": _command_text(spec, spec.get("rounds"))}
    if spec.get("not_executed_reason"):
        return _not_executed(spec, spec["not_executed_reason"])
    if spec.get("reuse_measured_evidence"):
        outcome = _execute_reused(spec, run)

        return outcome

    # ---- sub-process steps (calibers that need more than one invocation) -- #
    if spec.get("subprocess_steps"):
        return _execute_subprocess_steps(spec, run, timeout)

    # ---- single round -------------------------------------------------- #
    if spec["mode"] == "single_round":
        if spec.get("direct") == "hard_metrics":
            return _execute_hard_metrics(spec, run, timeout)
        if spec.get("direct") == "smoke":
            artifact = run.artifact(spec["artifact"])
            if artifact.exists():
                return _not_executed(spec, f"history zero-overwrite: {run.relative(artifact)} already exists")
            log = run.logs / f"{spec['group']}.log"
            try:
                info = run_smoke_group(run, spec["artifact"], timeout)
            except SystemExit:
                raise
            except Exception as error:  # noqa: BLE001 - a refusal is not a pass
                return _not_executed(spec, f"direct call failed: {type(error).__name__}: {error}")
            log.write_text(f"direct call into rag_mcp.eval.instance_form_smoke.run_form_smoke "
                           f"({info['duration_seconds']}s)\n", encoding="utf-8", newline="\n")
            outcome = {"group": spec["group"], "runner": spec["runner"], "mode": spec["mode"],
                       "model_dependent": False, "test_module": spec["test_module"],
                       "caliber": spec["caliber"], "command": "direct call: run_form_smoke(writer) + "
                       "run_form_smoke(reader)", "rounds": [
                           {"round": "single", "artifact": run.relative(artifact),
                            "exit_code": 0, "duration_seconds": info["duration_seconds"],
                            "log": run.relative(log)}],
                       "executed": True, "artifact": run.relative(artifact),
                       "historical": spec.get("historical"), "not_executed_reason": None,
                       "cache_manifest_hash": None, "replay_real_network_calls": None,
                       "checked_at": _now()}
            comparison = _compare_to_historical(spec, artifact)
            outcome["non_latency_reproducible"] = (comparison or {}).get("non_latency_reproducible")
            outcome["comparison"] = comparison
            return outcome

        artifact = run.artifact(spec["artifact"])
        if artifact.exists():
            return _not_executed(spec, f"history zero-overwrite: {run.relative(artifact)} already exists")
        if spec.get("prepare_empty_dir"):
            target = run.artifact(spec["prepare_empty_dir"])
            if target.exists() and any(target.iterdir()):
                return _not_executed(spec, f"the 011 orchestrator requires an empty output directory; "
                                           f"{run.relative(target)} is not empty")
            target.mkdir(parents=True, exist_ok=True)
        command = _guard_command(_render(spec["command"], run, spec.get("artifact"), None), run)
        log = run.logs / f"{spec['group']}.log"
        isolated = spec.get("requires_isolated_database")
        env_extra = _isolated_environment() if isolated else None
        info = _run_process(command, log, timeout, BACKEND_DIR if spec.get("pytest") else REPO_ROOT,
                            env_extra)
        if env_extra:
            info["isolated_database"] = env_extra["CONSOLIDATION_ISOLATED_DATABASE"]
        if info["timed_out"]:
            return _not_executed(spec, f"the runner exceeded the {timeout}s budget", [info])
        if spec.get("no_artifact_expected"):
            if info["exit_code"] != 0:
                return _not_executed(spec, f"the runner exited {info['exit_code']} (log: {run.relative(log)})", [info])
            outcome_artifact = run.artifact(spec["artifact"])
            _write_new_json(outcome_artifact, {
                "group": spec["group"], "runner": spec["runner"], "caliber": spec["caliber"],
                "exit_code": info["exit_code"], "command": " ".join(command),
                "log": run.relative(log), "log_tail": _tail(log, 40),
                "expected_in_place_output": spec.get("expected_in_place"),
                "in_place_output_sha256": (_sha256_file(REPO_ROOT / spec["expected_in_place"])
                                           if spec.get("expected_in_place")
                                           and (REPO_ROOT / spec["expected_in_place"]).exists() else None),
                "note": "this caliber has no new report artifact (its runner re-verifies in place); the outcome "
                        "file records the measured exit code and log tail",
                "checked_at": _now()})
            return {"group": spec["group"], "runner": spec["runner"], "mode": spec["mode"],
                    "model_dependent": False, "test_module": spec["test_module"], "caliber": spec["caliber"],
                    "command": " ".join(command),
                    "rounds": [{"round": "single", "artifact": run.relative(outcome_artifact), **info}],
                    "executed": True, "artifact": run.relative(outcome_artifact),
                    "historical": spec.get("historical"), "not_executed_reason": None,
                    "cache_manifest_hash": None, "replay_real_network_calls": None,
                    "non_latency_reproducible": None, "checked_at": _now()}
        if spec.get("pytest"):
            summary = _pytest_summary(log)
            if summary is None:
                return _not_executed(spec, f"no pytest summary line was observed (exit {info['exit_code']}); "
                                           f"the suite did not run to completion", [info])
            return {"group": spec["group"], "runner": spec["runner"], "mode": spec["mode"],
                    "model_dependent": False, "test_module": spec["test_module"], "caliber": spec["caliber"],
                    "command": " ".join(command), "rounds": [{"round": "single", **info}],
                    "executed": True, "artifact": run.relative(artifact) if artifact.exists() else None,
                    "artifact_present": artifact.exists(),
                    "pytest_summary": summary, "outcome": "passed" if info["exit_code"] == 0 else "failed",
                    "historical": spec.get("historical"), "not_executed_reason": None,
                    "cache_manifest_hash": None, "replay_real_network_calls": None,
                    "non_latency_reproducible": None, "checked_at": _now()}
        if not artifact.exists():
            return _not_executed(spec, f"the runner exited {info['exit_code']} and produced no artifact "
                                       f"(log: {run.relative(log)})", [info])
        outcome = {"group": spec["group"], "runner": spec["runner"], "mode": spec["mode"],
                   "model_dependent": False, "test_module": spec["test_module"], "caliber": spec["caliber"],
                   "command": " ".join(command), "rounds": [{"round": "single", **info}],
                   "executed": True, "artifact": run.relative(artifact), "historical": spec.get("historical"),
                   "outcome": "passed" if info["exit_code"] == 0 else "failed",
                   "exit_code": info["exit_code"],
                   "execution_rule": "the round ran to completion and produced the caliber artifact; a non-zero "
                                     "exit code is a verdict on the caliber (recorded as outcome=failed), not a "
                                     "failure to execute",
                   "not_executed_reason": None, "cache_manifest_hash": None,
                   "replay_real_network_calls": None, "checked_at": _now()}
        comparison = _compare_to_historical(spec, artifact)
        outcome["non_latency_reproducible"] = (comparison or {}).get("non_latency_reproducible")
        outcome["comparison"] = comparison
        return outcome

    # ---- record then replay ------------------------------------------- #
    cache_dir = run.artifact(spec["cache_dir"])
    rounds: list[dict] = []
    record = spec["rounds"][0]
    replay = spec["rounds"][1]
    record_artifact = run.artifact(record["artifact"])
    replay_artifact = run.artifact(replay["artifact"])
    # `reuse_record` names a record round of THIS run id whose frozen cache the
    # replay round consumes.  The record is never re-run and never re-billed: the
    # measured manifest of that frozen cache is re-computed from its real bytes,
    # and the record artifact is registered as reused (with its source named).
    reuse_record = spec.get("reuse_record")
    if reuse_record:
        source = run.artifact(reuse_record["artifact"])
        if not source.exists():
            return _not_executed(spec, f"the reused record artifact {run.relative(source)} does not exist")
        record_artifact = source
        source_round = next((item for item in _load_json(source).get("rounds") or []
                             if item.get("round") == "record"), {})
        record_info = {"round": "record", "artifact": run.relative(source), "reused": True,
                       "reused_from": run.relative(source),
                       "reuse_reason": reuse_record.get("why"),
                       "measured_real_network_calls": reuse_record.get("record_real_network_calls"),
                       "log": source_round.get("log"), "exit_code": source_round.get("exit_code"),
                       "netcount": source_round.get("netcount")}
        rounds.append(record_info)
        if not cache_dir.exists():
            return _not_executed(spec, f"the reused record pairs with a missing cache {run.relative(cache_dir)}",
                                 rounds)
        manifest = _cache_manifest(cache_dir)
        if not manifest["file_count"]:
            return _not_executed(spec, "the reused record round froze no model responses (empty cache manifest)",
                                 rounds)
    else:
        for target in (record_artifact, replay_artifact):
            if target.exists():
                return _not_executed(spec, f"history zero-overwrite: {run.relative(target)} already exists")
        if cache_dir.exists():
            return _not_executed(spec, f"history zero-overwrite: the record cache {run.relative(cache_dir)} "
                                       f"already exists")

        record_log = run.logs / f"{spec['group']}.record.log"
        record_command = _guard_command(_render(record["command"], run, record["artifact"], spec["cache_dir"]), run)
        record_count = run.regression / f"{spec['group']}.record.netcount.json"
        record_info = _run_process(_instrument(record_command, run, record_count), record_log, timeout, REPO_ROOT,
                                   {"NETCOUNT_OUT": str(record_count)})
        record_info.update({"round": "record", "artifact": run.relative(record_artifact),
                            "instrumented": True, "netcount": run.relative(record_count)})
        rounds.append(record_info)
        if record_info["timed_out"]:
            return _not_executed(spec, f"the record round exceeded the {timeout}s budget", rounds)
        if record_info["exit_code"] != 0 or not record_artifact.exists():
            return _not_executed(spec, f"the record round exited {record_info['exit_code']} and "
                                       f"{'produced' if record_artifact.exists() else 'did not produce'} its "
                                       f"artifact (log: {run.relative(record_log)})", rounds)
        manifest = _cache_manifest(cache_dir)
        if not manifest["file_count"]:
            return _not_executed(spec, "the record round froze no model responses (empty cache manifest), so no "
                                       "replay round can be judged", rounds)

    replay_log = run.logs / f"{spec['group']}.replay.log"
    replay_command = _guard_command(_render(replay["command"], run, replay["artifact"], spec["cache_dir"]), run)
    replay_count = run.regression / f"{spec['group']}.replay.netcount.json"
    replay_info = _run_process(_instrument(replay_command, run, replay_count), replay_log, timeout, REPO_ROOT,
                               {"NETCOUNT_OUT": str(replay_count)})
    replay_info.update({"round": "replay", "artifact": run.relative(replay_artifact),
                        "instrumented": True, "netcount": run.relative(replay_count)})
    rounds.append(replay_info)
    measured = _load_json(replay_count) if replay_count.exists() else {}
    replay_calls = measured.get("provider_calls")
    replay_info["measured_real_network_calls"] = replay_calls
    if replay_info["timed_out"]:
        return _not_executed(spec, f"the replay round exceeded the {timeout}s budget", rounds)
    if replay_calls is None:
        return _not_executed(spec, "the replay round produced no network census (the socket audit hook did not run)",
                             rounds)
    if replay_info["exit_code"] != 0 or not replay_artifact.exists():
        return _not_executed(spec, f"the replay round exited {replay_info['exit_code']} and "
                                   f"{'produced' if replay_artifact.exists() else 'did not produce'} its artifact "
                                   f"(log: {run.relative(replay_log)})", rounds)
    if replay_calls != 0:
        return _not_executed(spec, f"the replay round made {replay_calls} real provider transport(s); a replay round "
                                   f"is the only pass basis and it is not zero, so the group is not executed as a "
                                   f"pass (record round result is never a pass basis)", rounds)

    outcome = {"group": spec["group"], "runner": spec["runner"], "mode": spec["mode"],
               "model_dependent": True, "test_module": spec["test_module"], "caliber": spec["caliber"],
               "command": _command_text(spec, rounds), "rounds": rounds, "executed": True,
               "artifact": run.relative(replay_artifact), "historical": spec.get("historical"),
               "not_executed_reason": None, "cache_manifest_hash": manifest["manifest_hash"],
               "cache_manifest": {"manifest_hash": manifest["manifest_hash"], "file_count": manifest["file_count"],
                                  "bytes": manifest["bytes"], "cache_dir": run.relative(cache_dir),
                                  "files": manifest["files"]},
               "record_real_network_calls": (reuse_record.get("record_real_network_calls")
                                             if reuse_record else
                                             (int((_load_json(record_count) or {}).get("provider_calls") or 0)
                                              if record_count.exists() else None)),
               "replay_real_network_calls": int(replay_calls),
               "replay_zero_network": int(replay_calls) == 0,
               "checked_at": _now()}
    if reuse_record:
        outcome["record_reused"] = True
        outcome["record_reused_from"] = run.relative(run.artifact(reuse_record["artifact"]))
        outcome["record_reuse_reason"] = reuse_record.get("why")
    comparison = _compare_to_historical(spec, replay_artifact)
    outcome["non_latency_reproducible"] = (comparison or {}).get("non_latency_reproducible")
    outcome["comparison"] = comparison
    return outcome


def readjudicate(spec: dict, run: Run) -> dict:
    """Re-classify one already-recorded round under the current execution rule.

    Nothing is re-run and no measurement is changed: the recorded round's exit
    code, log and artifact stay exactly as they were measured. Only the
    executed/not_executed classification is recomputed, and the previous reason is
    preserved verbatim in ``readjudicated_from``.
    """
    path = run.status / f"{spec['group']}.json"
    if not path.exists():
        raise SystemExit(f"no recorded status for {spec['group']}: nothing to re-adjudicate")
    old = _load_json(path)
    if old.get("executed"):
        raise SystemExit(f"{spec['group']} is already recorded as executed; refusing to re-adjudicate")
    rounds = old.get("rounds") or []
    if not rounds or rounds[0].get("timed_out"):
        raise SystemExit(f"{spec['group']} has no completed round to re-adjudicate")
    artifact_rel = rounds[0].get("artifact") or spec.get("artifact")
    artifact = run.artifact(artifact_rel) if artifact_rel else None
    if artifact is None or not artifact.exists():
        raise SystemExit(f"{spec['group']}: the recorded round names no existing artifact")
    outcome = dict(old)
    outcome.update({
        "executed": True, "artifact": run.relative(artifact), "not_executed_reason": None,
        "outcome": "passed" if rounds[0].get("exit_code") == 0 else "failed",
        "exit_code": rounds[0].get("exit_code"),
        "readjudicated": True,
        "readjudicated_from": old.get("not_executed_reason"),
        "readjudication_rule": "the round ran to completion and produced the caliber artifact; a non-zero exit "
                               "code is a verdict on the caliber (recorded as outcome=failed), not a failure to "
                               "execute",
        "checked_at": _now(),
    })
    comparison = _compare_to_historical(spec, artifact)
    outcome["non_latency_reproducible"] = (comparison or {}).get("non_latency_reproducible")
    outcome["comparison"] = comparison
    return outcome


def remeasure_replay(spec: dict, run: Run, replay_artifact_rel: str, timeout: int) -> dict:
    """Re-run ONLY the replay round of an already-recorded record_then_replay group.

    Used when the replay evidence has to be produced again with a corrected
    instrument: the frozen record round (its artifact and its cache fingerprint)
    is reused exactly as measured, nothing is re-billed to the provider, and the
    superseded replay artifact is named in the record rather than deleted.
    """
    if spec["mode"] != "record_then_replay":
        raise SystemExit(f"{spec['group']} is not a record_then_replay group")
    path = run.status / f"{spec['group']}.json"
    if not path.exists():
        raise SystemExit(f"no recorded status for {spec['group']}: run the record round first")
    previous = _load_json(path)
    replay_artifact = run.artifact(replay_artifact_rel)
    if replay_artifact.exists():
        raise SystemExit(f"history zero-overwrite: {run.relative(replay_artifact)} already exists")
    record = next((item for item in previous.get("rounds") or [] if item.get("round") == "record"), None)
    record_artifact_rel = (record or {}).get("artifact") or spec["rounds"][0]["artifact"]
    record_artifact = run.artifact(record_artifact_rel)
    if not record_artifact.exists():
        raise SystemExit(f"the frozen record artifact {run.relative(record_artifact)} is absent")
    cache_dir = run.artifact(spec["cache_dir"])
    manifest = _cache_manifest(cache_dir)
    if not manifest["file_count"]:
        raise SystemExit(f"the frozen cache {run.relative(cache_dir)} is empty; nothing to replay")

    replay_spec = spec["rounds"][1]
    replay_log = run.logs / f"{spec['group']}.replay.v2.log"
    command = _guard_command(_render(replay_spec["command"], run, replay_artifact_rel, spec["cache_dir"]), run)
    census = run.regression / f"{spec['group']}.replay.v2.netcount.json"
    info = _run_process(_instrument(command, run, census), replay_log, timeout, REPO_ROOT,
                        {"NETCOUNT_OUT": str(census)})
    info.update({"round": "replay", "artifact": run.relative(replay_artifact), "instrumented": True,
                 "netcount": run.relative(census)})
    measured = _load_json(census) if census.exists() else {}
    provider_calls = measured.get("provider_calls")
    rounds = [item for item in (previous.get("rounds") or []) if item.get("round") != "replay"]
    rounds.append(info)
    if info["timed_out"]:
        return _not_executed(spec, f"the re-measured replay round exceeded the {timeout}s budget", rounds)
    if provider_calls is None:
        return _not_executed(spec, "the re-measured replay round produced no provider-call measurement", rounds)
    if info["exit_code"] != 0 or not replay_artifact.exists():
        return _not_executed(spec, f"the re-measured replay round exited {info['exit_code']} and "
                                   f"{'produced' if replay_artifact.exists() else 'did not produce'} its artifact "
                                   f"(log: {run.relative(replay_log)})", rounds)
    if provider_calls != 0:
        return _not_executed(spec, f"the re-measured replay round made {provider_calls} real provider request(s); "
                                   f"a replay round is the only pass basis and it is not zero", rounds)
    outcome = dict(previous)
    outcome.update({
        "group": spec["group"], "runner": spec["runner"], "mode": spec["mode"], "model_dependent": True,
        "test_module": spec["test_module"], "caliber": spec["caliber"], "rounds": rounds, "executed": True,
        "artifact": run.relative(replay_artifact), "historical": spec.get("historical"),
        "not_executed_reason": None, "cache_manifest_hash": manifest["manifest_hash"],
        "cache_manifest": {"manifest_hash": manifest["manifest_hash"], "file_count": manifest["file_count"],
                           "bytes": manifest["bytes"], "cache_dir": run.relative(cache_dir),
                           "files": manifest["files"]},
        "record_real_network_calls": None,
        "record_provider_calls_note": "the record round ran under the v1 socket-audit census, which cannot observe "
                                      "provider transports on this host; re-measuring it would repeat live billable "
                                      "provider calls, so it is recorded as not measured (null) rather than as 0",
        "record_frozen_cache_entries": manifest["file_count"],
        "replay_real_network_calls": int(provider_calls), "replay_zero_network": True,
        "replay_remeasured": True,
        "superseded_replay_artifact": previous.get("artifact"),
        "superseded_replay_reason": "the first replay round was measured with the v1 socket-audit census, which "
                                    "this host cannot observe (it saw 1200+ connects to a local proxy and 0 provider "
                                    "connects in both rounds); the replay was re-measured with the v2 httpx transport "
                                    "counter, reusing the frozen record round and cache unchanged",
        "checked_at": _now(),
    })
    comparison = _compare_to_historical(spec, replay_artifact)
    outcome["non_latency_reproducible"] = (comparison or {}).get("non_latency_reproducible")
    outcome["comparison"] = comparison
    return outcome


def _instrument(command: list[str], run: Run, netcount_out: Path) -> list[str]:
    """Wrap the target runner so the audit hook is installed before it starts."""
    rest = list(command)
    if rest and rest[0] in (PY, "python", "python3"):
        rest = rest[1:]
    if len(rest) >= 2 and rest[0] == "-X" and rest[1] == "utf8":
        rest = rest[2:]
    return [PY, "-X", "utf8", str(run.netcount), *rest]


_PYTEST_SUMMARY = __import__("re").compile(r"(\d+) (passed|failed|skipped|error|errors)")


def _pytest_summary(log: Path) -> str | None:
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if _PYTEST_SUMMARY.search(line) and ("passed" in line or "failed" in line or "error" in line):
            return line.strip()
    return None


# --------------------------------------------------------------------------- #
# status + map assembly (T058)
# --------------------------------------------------------------------------- #


def record_status(run: Run, outcome: dict, refresh: bool = False, previous: dict | None = None) -> Path:
    path = run.status / f"{outcome['group']}.json"
    if previous is not None and not previous.get("executed"):
        outcome = dict(outcome)
        outcome["superseded_not_executed_status"] = {
            "reason": previous.get("not_executed_reason"),
            "checked_at": previous.get("checked_at"),
        }
    text = json.dumps(outcome, ensure_ascii=False, indent=2) + "\n"
    retry = previous is not None and not previous.get("executed")
    if path.exists() and path.read_bytes() != text.encode("utf-8"):
        if not (refresh or retry):
            raise SystemExit(f"refusing to overwrite the measured status of {outcome['group']} "
                             f"({path} already exists with different bytes)")
        existing = _load_json(path)
        if existing.get("executed") and not refresh:
            raise SystemExit(f"refusing to overwrite the executed status of {outcome['group']}")
        if existing.get("group") != outcome["group"]:
            raise SystemExit(f"refusing to refresh {path}: it records a different group")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


#: Documented, evidence-cited dispositions for beyond-tolerance non-latency
#: comparisons. The 011 stream measured these exact drifts on 2026-09-06/07 and
#: recorded the cause and the disposition in
#: ``eval/runs/015-20261009205637/evidence/fr054_sync.json``
#: (``tolerance_reconciliation.items``). A disposition is applied ONLY when the
#: group's own comparison reproduces the documented (historical, rerun) values for
#: every drifted metric; otherwise the group stays failed. This makes the
#: disposition machine-checked instead of a blanket excuse.
DRIFT_DISPOSITIONS: dict[str, dict[str, Any]] = {
    "001_dense_11": {
        "metrics": {"mrr": (0.909091, 0.954545), "ndcg_at_k": (0.932896, 0.966448)},
        "kind": "pre_existing_corpus_drift",
        "disposition": ("pre-existing corpus drift (pre-dates 015): eval/011_001_regression_report.json already "
                        "measured mrr 0.954545 and ndcg 0.966448 on 2026-09-07 against the same 001-era historical; "
                        "the drift comes from the 008/011 corpus re-ingestion and the rerun equals the 011 caliber"),
        "evidence": ["eval/runs/015-20261009205637/evidence/fr054_sync.json",
                     "eval/011_001_regression_report.json"],
    },
    "002_hybrid_18": {
        "metrics": {"baseline.mrr": (0.6852, 0.9722), "baseline.ndcg_at_k": (0.7672, 0.9795)},
        "kind": "pre_existing_corpus_drift",
        "disposition": ("pre-existing corpus drift (pre-dates 015): the 'baseline' arm is a fresh dense pass over the "
                        "re-ingested corpus and eval/011_002_regression_report.json already measured 0.9722 / 0.9795 on "
                        "2026-09-07 against the same 002 historical; the hybrid arm is unchanged (delta 0.0)"),
        "evidence": ["eval/runs/015-20261009205637/evidence/fr054_sync.json",
                     "eval/011_002_regression_report.json"],
    },
    "007_hybrid_18": {
        "metrics": {"baseline.mrr": (0.6852, 0.9722), "baseline.ndcg_at_k": (0.7672, 0.9795)},
        "kind": "pre_existing_corpus_drift",
        "disposition": ("same caliber and same measured values as 002_hybrid_18 (007's hybrid caliber is the 002 "
                        "--limit 18 caliber); pre-existing corpus drift recorded in eval/011_002_regression_report.json"),
        "evidence": ["eval/runs/015-20261009205637/evidence/fr054_sync.json",
                     "eval/011_002_regression_report.json"],
    },
    "009_graph_37": {
        "metrics": {"graph.mrr": (0.8821, 0.8964), "graph.recall_at_k": (0.9643, 0.9459)},
        "kind": "inherited_between_historicals",
        "disposition": ("inherited between the 004 and 010 historicals (pre-dates 015): eval/010_graph_regression_report.json "
                        "(2026-09-06) already records graph.mrr 0.8964 and graph.recall_at_k 0.9459 against the 004 "
                        "historical 0.8821 / 0.9643; the rerun reproduces the 010 caliber exactly (delta 0.0 on all six "
                        "metrics). graph.mrr improves; graph.recall_at_k is the one declining check and it is inherited, "
                        "not introduced here"),
        "evidence": ["eval/runs/015-20261009205637/evidence/fr054_sync.json",
                     "eval/010_graph_regression_report.json",
                     "eval/graph_enhanced_comparison_report.json"],
    },
}


def _disposition_for(entry: dict) -> str | None:
    """Return the documented disposition iff the drift matches it exactly.

    The comparison is read from the entry itself (the caliber's own ``checks``);
    every drifted check must be one of the documented metrics with exactly the
    documented (historical, rerun) pair, and no undocumented drift may be present.
    """
    group = str(entry.get("group"))
    documented = DRIFT_DISPOSITIONS.get(group)
    if documented is None:
        return None
    comparison = entry.get("comparison") or {}
    checks = comparison.get("checks") if isinstance(comparison, Mapping) else None
    if not isinstance(checks, list):
        return None
    drifted = [check for check in checks if isinstance(check, Mapping) and check.get("passed") is False]
    if not drifted:
        return None
    for check in drifted:
        metric = str(check.get("metric"))
        expected = documented["metrics"].get(metric)
        if expected is None:
            return None
        historical, rerun = expected
        if (abs(float(check.get("historical") or 0) - historical) > 1e-6
                or abs(float(check.get("rerun") or 0) - rerun) > 1e-6):
            return None
    return documented["disposition"] + " | evidence: " + ", ".join(documented["evidence"])


def _derive_outcome(entry: dict) -> str:
    """Phase 10 T078: derive a group outcome from its own recorded evidence.

    ``passed`` only when the group's artifact demonstrates a pass (a JUnit artifact
    with zero failures/errors, a non-latency comparison inside the 1 % tolerance, or
    an unchanged published conclusion against the group's declared historical
    artifact); ``failed`` when it demonstrates the opposite; otherwise
    ``not_measured`` — an undecidable group is never a pass.
    """
    artifact = entry.get("artifact")
    if artifact:
        path = Path(artifact)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if path.suffix.lower() == ".xml" and path.exists():
            try:
                root = ElementTree.parse(path).getroot()
            except ElementTree.ParseError:
                return "not_measured"
            suites = [root] if root.tag == "testsuite" else list(root)
            tests = failures = errors = 0
            for suite in suites:
                if suite.tag != "testsuite":
                    continue
                tests += int(suite.get("tests") or 0)
                failures += int(suite.get("failures") or 0)
                errors += int(suite.get("errors") or 0)
            if tests == 0:
                return "not_measured"
            return "failed" if (failures or errors) else "passed"
    reproducible = entry.get("non_latency_reproducible")
    if reproducible is True:
        return "passed"
    if reproducible is False:
        return "failed"
    try:
        from memory_baseline_support import artifact_outcome
    except Exception:  # noqa: BLE001 - the historical comparison is best-effort
        return "not_measured"
    comparison = artifact_outcome(artifact, entry.get("historical"))
    if comparison is not None:
        entry["outcome_reason"] = comparison[1]
        return comparison[0]
    return "not_measured"


def assemble_map(run: Run) -> dict:
    statuses = {path.stem: _load_json(path) for path in sorted(run.status.glob("*.json"))} \
        if run.status.exists() else {}
    entries = []
    for spec in GROUP_SPECS:
        outcome = statuses.get(spec["group"])
        if outcome is None:
            outcome = _not_executed(spec, spec.get("not_executed_reason")
                                    or "not executed in this run (no measured status was recorded)")
        entry = {
            "group": spec["group"], "runner": spec["runner"], "command": outcome.get("command"),
            "test_module": spec["test_module"], "artifact": outcome.get("artifact"),
            "mode": spec["mode"], "executed": bool(outcome.get("executed")),
            "model_dependent": bool(spec.get("model_dependent")),
            "historical": spec.get("historical"), "caliber": spec.get("caliber"),
            "cache_manifest_hash": outcome.get("cache_manifest_hash"),
            "replay_real_network_calls": outcome.get("replay_real_network_calls"),
            "record_real_network_calls": outcome.get("record_real_network_calls"),
            "non_latency_reproducible": outcome.get("non_latency_reproducible"),
            "rounds": outcome.get("rounds") or [],
            "not_executed_reason": outcome.get("not_executed_reason"),
        }
        for optional in ("comparison", "cache_manifest", "evidence_reused", "reused_from", "reuse_reason",
                         "pytest_summary", "outcome", "artifact_present"):
            if optional in outcome:
                entry[optional] = outcome[optional]
        # Phase 10 T078: every executed group must carry a machine-readable outcome,
        # because the report's regression gate can only fail on a group whose outcome
        # says so. A group that cannot be decided is `not_measured`, never a pass.
        if entry["executed"] and not entry.get("outcome"):
            entry["outcome"] = _derive_outcome(entry)
            entry.setdefault("outcome_reason", (
                "derived by the Phase 10 T078 rule from the group's own artifact / comparison result; the caliber "
                "itself did not record a pass/fail verdict"))
        # A beyond-tolerance non-latency comparison is a regression UNLESS a
        # documented disposition is recorded for exactly this drift (verified
        # metric-by-metric against the 011 stream's own measurement).
        if entry.get("non_latency_reproducible") is False:
            disposition = _disposition_for(entry)
            if disposition:
                entry["outcome"] = "passed"
                entry["outcome_reason"] = disposition
            elif not entry.get("outcome_reason"):
                entry["outcome"] = "failed"
                entry["outcome_reason"] = ("the non-latency comparison drifted beyond the 1 % tolerance and the map "
                                           "records no disposition for exactly this drift")
        entries.append(entry)
    payload = {
        "schema_version": "015.1",
        "report_type": "015_regression_group_map",
        "run_id": run.run_id,
        "generated_at": _now(),
        "tolerance": TOLERANCE,
        "execution_rule": (
            "executed == the group's round(s) really ran: a single round requires exit 0 plus the caliber artifact; "
            "a pytest group requires an observed pytest summary line; a record_then_replay group requires a "
            "non-empty recorded cache manifest, a replay artifact, and a MEASURED replay provider-call count of 0. "
            "An unexecuted group is named in not_executed and is never recorded as passed."
        ),
        "history_zero_overwrite": (
            "every artifact path in this map lives under eval/runs/<RUN_ID>/; the orchestrator refuses a target path "
            "that already exists and refuses any runner argument that writes outside the run directory"
        ),
        "model_dependent_groups": [spec["group"] for spec in GROUP_SPECS if spec.get("model_dependent")],
        "environment_defects_recorded": {
            "NO_PROXY": {
                "defect": ("this host exports a bracketed IPv6 entry in NO_PROXY; httpx then raises "
                           "InvalidURL: Invalid port ':1]' for every client, so qdrant_client cannot be "
                           "constructed and every 001-014 caliber exits without an artifact"),
                "original": PROXY_ENV_RECORD["original"],
                "normalized": PROXY_ENV_RECORD["normalized"],
                "handling": ("the orchestrator normalizes NO_PROXY/no_proxy for its own process and therefore for "
                             "every child it spawns; nothing global is changed"),
            }
        },
        "shared_writer_lease_discipline": (
            "groups run strictly sequentially in this process: concurrent memory suites deadlock on the global "
            "writer_lease row (measured 481 s idle-in-transaction), so no two calibers may run at once"
        ),
        "groups": entries,
    }
    _write_run_owned(run, run.regression / GROUPS_MAP_NAME, payload)
    return payload


# --------------------------------------------------------------------------- #
# T060: the report's regression block
# --------------------------------------------------------------------------- #


def _regression_argv(run: Run, output: Path, map_path: Path) -> list[str]:
    continuity = run.dir / "continuity-replay" / "memory-replay.json"
    argv = [
        "--output", str(output),
        "--poisoning", str(EVAL_DIR / "memory_poisoning_eval_dataset.json"),
        "--aoep", str(EVAL_DIR / "memory_aoep_obligation_dataset.json"),
        "--aoep-results", str(run.dir / "evidence" / "aoep-cases.json"),
        "--poisoning-results", str(run.dir / "evidence" / "poisoning-cases.json"),
        "--runs-dir", str(run.dir),
        "--regression-map", str(map_path),
        "--measurements", str(run.dir / "hard-metrics-measurements.json"),
    ]
    if continuity.exists():
        argv += ["--continuity-report", str(continuity), "--continuity-criterion-met", "--continuity-completed", "16"]
    return argv


def probe_raw_cli(run: Run, map_path: Path) -> dict:
    """Ask the frozen CLI itself to produce the report, and keep the result.

    The probe writes to a scratch path inside the run directory: it is the direct,
    un-intervened invocation T060 asks for. Its exit code and the contract verdict
    of the report it wrote are recorded verbatim.
    """
    scratch = run.regression / "_probe" / "raw_cli_report.current.json"
    scratch.parent.mkdir(parents=True, exist_ok=True)
    argv = _regression_argv(run, scratch, map_path)
    if scratch.exists():
        scratch = scratch.with_name("raw_cli_report.current.%d.json" % int(time.time()))
        argv = _regression_argv(run, scratch, map_path)
    captured = subprocess.run([PY, "-X", "utf8", "eval/run_memory_baseline.py", *argv], cwd=str(REPO_ROOT),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    record = {"kind": "direct_cli_probe",
              "command": "python eval/run_memory_baseline.py " + " ".join(argv),
              "exit_code": captured.returncode,
              "wrote_artifact": scratch.exists(),
              "artifact": run.relative(scratch) if scratch.exists() else None,
              "stderr_tail": "\n".join(captured.stderr.splitlines()[-25:]),
              "checked_at": _now()}
    if scratch.exists():
        try:
            import memory_baseline_support as support
            support.validate_report(_load_json(scratch))
            record["contract_valid"] = True
        except Exception as error:  # noqa: BLE001 - a contract failure is recorded, not hidden
            record["contract_valid"] = False
            record["validation_error"] = f"{type(error).__name__}: {error}"
    return record


def emit_report(run: Run, output: Path, timeout: int) -> int:
    import memory_baseline_support as support
    import run_memory_baseline as baseline

    map_path = run.regression / GROUPS_MAP_NAME
    if not map_path.exists():
        print(f"--emit-map must run first: {map_path} is absent", file=sys.stderr)
        return 2

    probe = probe_raw_cli(run, map_path)

    # The frozen runner is invoked directly: its own zero-overwrite rule decides
    # (identical bytes -> idempotent success, different bytes -> refusal).
    started = time.time()
    code = baseline.main(_regression_argv(run, output, map_path))

    validation: dict = {"run_id": run.run_id, "report_type": "015_regression_block_validation",
                        "output": str(output), "runner_exit_code": code,
                        "duration_seconds": round(time.time() - started, 3),
                        "direct_cli_probe": probe,
                        "historical_defect": {
                            "observed_while_t058_t059_ran": (
                                "memory_baseline_support.regression_block emitted a non-contract `map_path` key "
                                "whenever --regression-map was passed; the report contract's regression block is "
                                "additionalProperties:false, so validate_report() aborted and the raw CLI exited 1 "
                                "without writing a report"),
                            "fixed_by": "commit 2b39708 '015 T060 stop the runner emitting the non-contract "
                                        "regression map_path key'",
                            "shim_era_artifact": "eval/runs/015-20261009205637/regression/_probe/"
                                                 "memory_baseline_report.regression.shim-era.json",
                            "shim_era_validation": "eval/runs/015-20261009205637/regression/_probe/"
                                                   "regression_block_validation.shim-era.json",
                            "equivalence_evidence": "the shim-era deliverable and the direct CLI output of the same "
                                                    "caliber are byte-identical (sha256 "
                                                    "caefd65102413b14150fe5f18ae7ab48981fe5454bb6232a34d14de0dd95d496), "
                                                    "so the shim changed nothing",
                        }}
    if output.exists():
        document = _load_json(output)
        checks: list[str] = []
        try:
            support.validate_report(document)
            valid, error = True, None
        except Exception as exc:  # noqa: BLE001 - a contract failure is recorded, not hidden
            valid, error = False, f"{type(exc).__name__}: {exc}"
        block = document.get("regression") or {}
        allowed = {"group", "runner", "mode", "cache_manifest_hash", "replay_real_network_calls",
                   "non_latency_reproducible", "artifact"}
        for item in block.get("groups") or []:
            extra = set(item) - allowed
            if extra:
                checks.append(f"{item.get('group')}: non-contract keys {sorted(extra)}")
        validation.update({
            "valid": valid, "validation_error": error,
            "report_sha256": _sha256_file(output),
            "regression": block,
            "group_items_allowed_keys": sorted(allowed),
            "non_contract_key_checks": checks,
            "not_executed": block.get("not_executed"),
            "all_groups_executed": block.get("all_groups_executed"),
            "map_path_present_in_block": "map_path" in block,
            "command_test_module_in_block": sorted({"command", "test_module"} & set().union(
                *(set(item) for item in (block.get("groups") or [{}])))),
            "invocation": "eval/run_memory_baseline.py invoked directly (unmodified), with --runs-dir and "
                          "--regression-map; no in-process patch was applied",
        })
    else:
        validation.update({"valid": False, "validation_error": "no report was written"})
    _write_run_owned(run, run.evidence_dir / "regression_block_validation.json", validation)
    return 0 if validation.get("valid") else 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


_SNAPSHOT_RUNNER = '''"""015 regression group 013_consolidation_comparison: emit the authority snapshot.

The 013 contract CLI requires ``--snapshot <authority-snapshot.json>`` whose
``authority.authority_digest`` equals the frozen dataset's ``snapshot_hash``.  No
such file is tracked in the repository, but the sealed capsule of that exact
frozen scope still exists on this host, so the snapshot is *rebuilt from the
sealed material* rather than invented:

* ``scope_id`` / ``authority_digest`` / ``authority_cutoff`` come from the
  capsule's own sealed authority record;
* the authority object itself is re-exported from the capsule's live isolated
  database (``memory_consolidation_013_capsule_t102a``) with
  ``consolidation_restore_support.authority_snapshot`` -- the same function the
  sealer used -- so the digest is *recomputed*, not copied;
* ``policy`` is read from the frozen scope's real ``domain_profiles.memory_policy``
  row in that database (the published target policy the sealer wrote);
* ``frozen_clock`` / ``frozen`` come from the frozen dataset, which IS the sealed
  record of the caliber.

Every cross-check is hard: a mismatch aborts instead of emitting a snapshot.
"""
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "eval"))
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from consolidation_eval_support import load_dataset  # noqa: E402
from consolidation_restore_support import authority_snapshot  # noqa: E402

CAPSULE_DIR = Path(os.environ["SNAPSHOT_CAPSULE_DIR"])
DATASET = Path(os.environ["SNAPSHOT_DATASET"])
OUT = Path(os.environ["SNAPSHOT_OUT"])

capsule = json.loads((CAPSULE_DIR / "capsule.json").read_text(encoding="utf-8"))
dataset = load_dataset(DATASET)

if capsule.get("capsule_version") != "013.restore.1":
    raise SystemExit("refusing: capsule_version is not the 013 restore capsule")
scopes = [int(scope) for scope in capsule["scopes"]]
if str(scopes[0]) != str(dataset["scope_id"]):
    raise SystemExit("refusing: the capsule scope does not match the frozen dataset scope")
if capsule["authority"]["authority_digest"] != dataset["snapshot_hash"]:
    raise SystemExit("refusing: the sealed authority digest does not match the frozen snapshot_hash")
if int(capsule["authority_cutoff"]) != int(dataset["authority_cutoff"]):
    raise SystemExit("refusing: the sealed authority cutoff does not match the frozen dataset")

authority = authority_snapshot(capsule["capsule_database"], scopes=scopes)
if authority["authority_digest"] != dataset["snapshot_hash"]:
    raise SystemExit("refusing: the re-exported authority digest does not match the frozen snapshot_hash")
if int(authority["authority_cutoff"]) != int(dataset["authority_cutoff"]):
    raise SystemExit("refusing: the re-exported authority cutoff does not match the frozen dataset")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

url = make_url(os.environ["DATABASE_URL_SYNC"]).set(database=capsule["capsule_database"])
engine = create_engine(url.render_as_string(hide_password=False))
try:
    with engine.connect() as connection:
        domain_key = connection.scalar(
            text("select domain_key from knowledge_scopes where scope_id = :scope"), {"scope": scopes[0]})
        policy = connection.scalar(
            text("select memory_policy from domain_profiles where domain_key = :key"), {"key": domain_key})
        published = connection.scalar(
            text("select count(*) from memory_events where knowledge_scope_id = :scope "
                 "and event_type = :kind"), {"scope": scopes[0], "kind": "grant"})
finally:
    engine.dispose()
if not isinstance(policy, dict):
    raise SystemExit("refusing: the frozen scope carries no dict memory_policy")

snapshot = {
    "scope_id": str(scopes[0]),
    "authority": authority,
    "policy": policy,
    "frozen_clock": dataset["frozen_clock"],
    "frozen": dataset["frozen"],
    "snapshot_provenance": {
        "capsule_dir": str(CAPSULE_DIR),
        "capsule_version": capsule["capsule_version"],
        "capsule_database": capsule["capsule_database"],
        "capsule_sealed_at": capsule.get("sealed_at"),
        "capsule_token": capsule.get("capsule_token"),
        "domain_key": domain_key,
        "policy_source": "domain_profiles.memory_policy of the frozen scope in the capsule database",
        "policy_published_events": int(published or 0),
        "policy_event_kind": "grant",
        "verification": ("authority_digest re-exported from the capsule database equals the capsule's sealed "
                         "digest and the frozen dataset snapshot_hash"),
    },
}
if OUT.exists():
    raise SystemExit("refusing to overwrite " + str(OUT))
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(snapshot, indent=2, sort_keys=True, default=str) + "\\n", encoding="utf-8", newline="\\n")
print(json.dumps({"status": "snapshot", "output": str(OUT), "scope_id": snapshot["scope_id"],
                  "authority_digest": authority["authority_digest"],
                  "authority_cutoff": authority["authority_cutoff"],
                  "policy_keys": sorted(policy), "domain_key": domain_key,
                  "policy_published_events": int(published or 0)}, indent=2))
'''


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="015 T058/T059/T060 full-suite regression orchestration")
    parser.add_argument("--run-id", default=os.environ.get("RUN_ID") or DEFAULT_RUN_ID)
    parser.add_argument("--group", action="append", default=None, help="group id (repeatable); default: all")
    parser.add_argument("--timeout", type=int, default=3600, help="per-round wall-clock budget in seconds")
    parser.add_argument("--list", action="store_true", help="list the registered groups and exit")
    parser.add_argument("--dry-run", action="store_true", help="print the planned commands without running")
    parser.add_argument("--emit-map", action="store_true", help="assemble regression_group_map.json from the status files")
    parser.add_argument("--readjudicate", action="append", default=None,
                        help="re-classify an already-recorded round under the current execution rule (never re-runs, "
                             "never changes a measurement); repeatable")
    parser.add_argument("--remeasure-replay", default=None,
                        help="re-run ONLY the replay round of a record_then_replay group with the current "
                             "instrument, reusing the frozen record round and cache")
    parser.add_argument("--replay-artifact", default=None,
                        help="artifact path for --remeasure-replay (relative to the run dir; must not exist)")
    parser.add_argument("--emit-report", action="store_true", help="T060: emit the report's regression block")
    parser.add_argument("--output", type=Path, help="T060 report output path (must not exist)")
    parser.add_argument("--build-013-snapshot", action="store_true",
                        help="013: rebuild the authority snapshot from the sealed capsule and the frozen dataset")
    parser.add_argument("--snapshot-out", type=Path,
                        help="output path for --build-013-snapshot (must not exist)")
    parser.add_argument("--capsule-dir", type=Path, default=Path("C:/t102/capsule"),
                        help="sealed 013 capsule used by --build-013-snapshot (read-only)")
    parser.add_argument("--snapshot-dataset", type=Path, default=EVAL_DIR / "consolidation_eval_dataset.json",
                        help="frozen 013 dataset the snapshot must match")
    parser.add_argument("--isolated-database", default=os.environ.get("CONSOLIDATION_ISOLATED_DATABASE")
                        or "memory_consolidation_013_015regr_pytest",
                        help="isolated database used by calibers that write 013 consolidation state")
    parser.add_argument("--isolated-template", default="memory_consolidation_013_capsule_t102a",
                        help="sealed capsule database the isolated database is copied from (read-only template)")
    parser.add_argument("--keep-isolated-database", action="store_true",
                        help="reuse the existing isolated database instead of refreshing it from the template")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run = Run(args.run_id)
    run.ensure()
    _prepare_datasets(run)
    global _ACTIVE_RUN
    _ACTIVE_RUN = run

    if args.list:
        for spec in GROUP_SPECS:
            print(f"{spec['group']:34s} {spec['mode']:18s} model={str(bool(spec.get('model_dependent'))):5s} "
                  f"{spec['runner']}")
        return 0
    if args.dry_run:
        for spec in GROUP_SPECS:
            outcome = execute_group(spec, run, args.timeout, dry_run=True)
            print(f"{spec['group']}: {outcome['command']}")
        return 0
    if args.remeasure_replay:
        group_id = args.remeasure_replay
        spec = GROUPS_BY_ID.get(group_id)
        if spec is None:
            print(f"unknown group: {group_id}", file=sys.stderr)
            return 2
        default_replay = spec["rounds"][1]["artifact"].replace(".json", ".v2.json")
        outcome = remeasure_replay(spec, run, args.replay_artifact or default_replay, args.timeout)
        record_status(run, outcome, refresh=True)
        print(f"{group_id}: executed={outcome['executed']} artifact={outcome.get('artifact')} "
              f"replay_real_network_calls={outcome.get('replay_real_network_calls')}")
        payload = assemble_map(run)
        executed = sum(1 for entry in payload["groups"] if entry["executed"])
        print(f"map: {run.regression / GROUPS_MAP_NAME} ({executed}/{len(payload['groups'])} executed)")
        return 0 if outcome["executed"] else 1
    if args.readjudicate:
        for group_id in args.readjudicate:
            spec = GROUPS_BY_ID.get(group_id)
            if spec is None:
                print(f"unknown group: {group_id}", file=sys.stderr)
                return 2
            outcome = readjudicate(spec, run)
            record_status(run, outcome, refresh=True)
            print(f"{group_id}: executed={outcome['executed']} outcome={outcome.get('outcome')} "
                  f"artifact={outcome.get('artifact')}")
        payload = assemble_map(run)
        executed = sum(1 for entry in payload["groups"] if entry["executed"])
        print(f"map: {run.regression / GROUPS_MAP_NAME} ({executed}/{len(payload['groups'])} executed)")
        return 0
    if args.emit_map:
        payload = assemble_map(run)
        executed = sum(1 for entry in payload["groups"] if entry["executed"])
        print(f"written: {run.regression / GROUPS_MAP_NAME} "
              f"({executed}/{len(payload['groups'])} groups executed)")
        return 0
    if args.emit_report:
        output = args.output or (run.dir / "memory_baseline_report.regression.json")
        return emit_report(run, Path(output), args.timeout)

    if args.build_013_snapshot:
        output = args.snapshot_out or (run.regression / "013-consolidation" / "authority-snapshot.json")
        output = Path(output)
        if not output.is_absolute():
            output = REPO_ROOT / output
        try:
            output.resolve().relative_to(run.dir.resolve())
        except ValueError as error:
            print(f"refusing: {output} is outside the run directory {run.dir}", file=sys.stderr)
            return 2
        if output.exists():
            print(f"refusing to overwrite {output}", file=sys.stderr)
            return 2
        wrapper = run.regression / "_build_013_snapshot.py"
        wrapper.write_text(_SNAPSHOT_RUNNER, encoding="utf-8", newline="\n")
        environment = dict(os.environ)
        if not environment.get("DATABASE_URL_SYNC"):
            print("refusing: DATABASE_URL_SYNC is not configured (the capsule database cannot be read)",
                  file=sys.stderr)
            return 2
        environment.update({"SNAPSHOT_CAPSULE_DIR": str(Path(args.capsule_dir)),
                            "SNAPSHOT_DATASET": str(Path(args.snapshot_dataset)),
                            "SNAPSHOT_OUT": str(output)})
        log = run.logs / "013_consolidation_comparison.snapshot.log"
        completed = subprocess.run([PY, "-X", "utf8", str(wrapper)], cwd=str(REPO_ROOT), env=environment,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        log.write_text((completed.stdout or "") + (completed.stderr or ""), encoding="utf-8", newline="\n")
        print(completed.stdout.strip() or completed.stderr.strip(), flush=True)
        return 0 if (completed.returncode == 0 and output.exists()) else 1

    selected = [spec for spec in GROUP_SPECS if not args.group or spec["group"] in args.group]
    if not selected:
        print(f"no group matched {args.group}", file=sys.stderr)
        return 2
    global ISOLATED_DATABASE
    ISOLATED_DATABASE = args.isolated_database
    if any(spec.get("requires_isolated_database") for spec in selected):
        if args.keep_isolated_database:
            print(f"=== isolated database {args.isolated_database}: reused as-is ===", flush=True)
        else:
            try:
                provisioned = provision_isolated_database(args.isolated_database, args.isolated_template)
            except Exception as error:  # noqa: BLE001 - a provisioning failure must not be a pass
                print(f"refused: the isolated database could not be provisioned: "
                      f"{type(error).__name__}: {error}", file=sys.stderr)
                return 2
            run.evidence_dir.mkdir(parents=True, exist_ok=True)
            (run.evidence_dir / "isolated_database.json").write_text(
                json.dumps({"report_type": "015_isolated_database_provisioning", "run_id": run.run_id,
                            "reason": "013_e2e and 014_contract write 013 consolidation state and refuse the shared "
                                      "acceptance database by product design",
                            **provisioned}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8", newline="\n")
            print(f"=== isolated database {provisioned['database']} refreshed from {provisioned['template']} ===",
                  flush=True)
    failures = 0
    for spec in selected:
        status_path = run.status / f"{spec['group']}.json"
        previous = _load_json(status_path) if status_path.exists() else None
        if previous is not None and previous.get("executed"):
            print(f"=== {spec['group']}: already executed in this run; keeping the measured record ===",
                  flush=True)
            continue
        print(f"=== {spec['group']} ({spec['mode']}) ===", flush=True)
        try:
            outcome = execute_group(spec, run, args.timeout)
        except SystemExit as error:
            print(f"refused: {error}", file=sys.stderr)
            return 2
        record_status(run, outcome, previous=previous)
        flag = "executed" if outcome["executed"] else "not_executed"
        print(f"    {flag}: {outcome.get('artifact') or outcome.get('not_executed_reason')}", flush=True)
        failures += 0 if outcome["executed"] else 1
    payload = assemble_map(run)
    executed = sum(1 for entry in payload["groups"] if entry["executed"])
    print(f"map: {run.regression / GROUPS_MAP_NAME} ({executed}/{len(payload['groups'])} executed)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
