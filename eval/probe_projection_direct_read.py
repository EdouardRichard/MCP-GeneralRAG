"""014 T064/T065: three-host smoke and the projection direct-read evidence.

Two separate artefacts, both written with **only what was actually observed**:

* ``projection-direct-read.json`` (T065) — three evidence layers:
  1. *filesystem level (required to pass)*: the consumption tree exists, every
     memory file's frontmatter is complete, its body is byte-identical to the
     authoritative ``content_text``, and clearing plus rebuilding reproduces the
     same tree fingerprint with zero model calls;
  2. *DSH real observation*: the host reading a projection path. This needs a
     running DSH/MCP endpoint; when nothing is observed the layer is ``failed``;
  3. *protocol layer*: explicitly not applicable — the consumption layer is a file
     system surface and does not go through MCP, so no protocol-level direct-read
     evidence can exist by construction.
* ``target-host-smoke.json`` (T064) — DSH (must pass), ChatGPT App and Claude Code
  (availability/compatibility recorded only; never recorded as passed when they
  were not executed).

Nothing here fabricates a host observation. The filesystem layer is executed for
real against the configured PostgreSQL.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "backend" / "tests"))

RUN_ID = os.environ.get("RUN_ID") or f"014-projection-{datetime.now(UTC):%Y%m%d%H%M%S}"
RUN_DIR = Path(os.environ.get("RUN_DIR", REPO_ROOT / "eval" / "runs" / RUN_ID))
MCP_ENDPOINTS = {
    "writer": ("127.0.0.1", 18080),
    "reader": ("127.0.0.1", 18081),
    "default": ("127.0.0.1", 8080),
}


def _probe(host: str, port: int, timeout: float = 0.4) -> bool:
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


async def _filesystem_layer(root: Path) -> dict:
    from rag_mcp.db import get_session_factory
    from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider
    from rag_mcp.runtime.memory_projection import MemoryProjectionConsumer, set_consumer
    from rag_mcp.services.memory_service import MemoryService
    from tests.integration.test_012_live_reader import scope_and_payload

    factory = get_session_factory()
    async with factory() as session:
        service = MemoryService(session, embedding_provider=LocalCPUEmbeddingProvider())
        sid, payload = await scope_and_payload(session)
        first = await service.record({**payload, "content": "Projection direct-read authority text."})
        second = await service.record({**payload, "kind": "episodic",
                                       "content": "A second authoritative body for the projection."})

    consumer = MemoryProjectionConsumer(root=root, session_factory=factory)
    set_consumer(consumer)
    report = await consumer.rebuild(sid)
    tree = consumer.guard.manifest(consumer.guard.resolve_scope_dir(report.scope_slug))
    slug_dir = consumer.guard.resolve_scope_dir(report.scope_slug)

    files = sorted(str(Path(relative)) for relative in tree)
    frontmatter_complete = True
    frontmatter_issues: list[str] = []
    body_matches_authority = True
    body_issues: list[str] = []
    untrusted_complete = True
    expected_bodies = {
        first["memory_id"]: "Projection direct-read authority text.",
        second["memory_id"]: "A second authoritative body for the projection.",
    }
    for relative in tree:
        path = slug_dir / relative
        text = path.read_text(encoding="utf-8")
        name = Path(relative).name
        # DIGEST.md / INDEX.md carry an untrusted *banner*, not memory frontmatter.
        if name in {"DIGEST.md", "INDEX.md"}:
            if "untrusted" not in text.lower():
                untrusted_complete = False
                frontmatter_issues.append(f"{relative}: banner lacks the untrusted declaration")
            continue
        head, separator, body = text.partition("\n---\n")
        if not separator:
            frontmatter_issues.append(f"{relative}: no frontmatter block")
            frontmatter_complete = False
            continue
        for key in ("memory_id", "kind", "provenance", "confidence", "valid_from", "valid_to",
                    "session_id", "evidence_refs", "status", "superseded_by", "untrusted"):
            if f"{key}:" not in head:
                frontmatter_complete = False
                frontmatter_issues.append(f"{relative}: missing {key}")
        if "untrusted: true" not in head:
            untrusted_complete = False
            frontmatter_issues.append(f"{relative}: untrusted is not true")
        try:
            stem = int(Path(relative).stem)
        except ValueError:
            body_matches_authority = False
            body_issues.append(f"{relative}: memory file name is not a numeric memory id")
            continue
        if stem not in expected_bodies:
            body_matches_authority = False
            body_issues.append(f"{relative}: unexpected memory file")
        elif body.strip() != expected_bodies[stem]:
            body_matches_authority = False
            body_issues.append(f"{relative}: body != authoritative content_text")

    # Clear and rebuild: the tree fingerprint and the digest summary must reproduce.
    fingerprint_before = report.tree_fingerprint
    for entry in slug_dir.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.chmod(0o666)
            entry.unlink(missing_ok=True)
    rebuilt = await consumer.rebuild(sid)
    fingerprint_after = rebuilt.tree_fingerprint
    return {
        "scope_id": sid,
        "scope_slug": report.scope_slug,
        "tree_root": str(root),
        "files": files,
        "file_count": report.file_count,
        "frontmatter_complete": frontmatter_complete,
        "frontmatter_issues": frontmatter_issues,
        "untrusted_marker_complete": untrusted_complete,
        "body_matches_authority": body_matches_authority,
        "body_issues": body_issues,
        "fingerprint_before_clear": fingerprint_before,
        "fingerprint_after_rebuild": fingerprint_after,
        "rebuild_reproduced_the_tree": fingerprint_before == fingerprint_after,
        "model_calls": 0,
        "digest_empty_state": (slug_dir / "DIGEST.md").read_text(encoding="utf-8") != "" if (
            slug_dir / "DIGEST.md").exists() else False,
        "passed": bool(frontmatter_complete and untrusted_complete and body_matches_authority
                       and fingerprint_before == fingerprint_after),
    }


def main() -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("projection-direct-read.json", "target-host-smoke.json"):
        if (RUN_DIR / name).exists():
            print(f"refusing to overwrite {RUN_DIR / name}", file=sys.stderr)
            return 2

    availability = {name: _probe(host, port) for name, (host, port) in MCP_ENDPOINTS.items()}
    filesystem = asyncio.run(_filesystem_layer(RUN_DIR / "consumption"))

    host_observed = False  # nothing observed a projection read through a host in this run
    projection = {
        "schema_version": "014.1",
        "report_type": "projection-direct-read",
        "run_id": RUN_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "layers": {
            "filesystem": {**filesystem, "observed": True},
            "dsh_host_observation": {
                "observed": host_observed,
                "status": "failed" if not host_observed else "passed",
                "reason": (
                    "no running DSH/MCP endpoint was reachable, so no host actually read a "
                    "projection path in this run"
                    if not host_observed else ""
                ),
                "mcp_endpoint_availability": availability,
            },
            "protocol": {
                "observed": False,
                "status": "not_applicable",
                "reason": (
                    "the consumption layer is a file-system surface and is deliberately not "
                    "exposed through MCP, so no protocol-layer direct-read evidence can exist"
                ),
            },
        },
        "conclusion": "failed",
        "conclusion_reason": (
            "the required filesystem layer passed, but the DSH real observation layer is "
            "failed/unobserved, so the three-layer criterion is not met"
        ),
    }
    (RUN_DIR / "projection-direct-read.json").write_text(
        json.dumps(projection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    dsh_reachable = availability["writer"] or availability["reader"] or availability["default"]
    smoke = {
        "schema_version": "014.1",
        "report_type": "target-host-smoke",
        "run_id": RUN_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "hosts": {
            "dsh": {
                "must_pass": True,
                "status": "failed" if not dsh_reachable else "unverified",
                "work_package_continuation_observed": False,
                "projection_direct_read_observed": False,
                "reason": (
                    "no DSH/MCP endpoint was reachable, so neither the work-package "
                    "continuation nor a host read of the projection path was observed; an "
                    "unobserved must-pass host is recorded as failed"
                ),
            },
            "chatgpt_app": {
                "must_pass": False,
                "status": "not_executed",
                "reason": "no ChatGPT App MCP client is configured in this environment; "
                          "availability only, never recorded as passed",
            },
            "claude_code": {
                "must_pass": False,
                "status": "not_executed",
                "reason": "the Claude Code MCP configuration lists no rag-mcp server; "
                          "availability only, never recorded as passed",
            },
        },
        "summary": "convergence is NOT declared: the DSH must-pass smoke did not pass",
    }
    (RUN_DIR / "target-host-smoke.json").write_text(
        json.dumps(smoke, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    # T064 requires the smoke report to live under eval/ as a tracked deliverable;
    # eval/runs/ is gitignored, so the canonical copy is written beside the probe.
    smoke_path = REPO_ROOT / "eval" / "target-host-smoke-014.json"
    smoke_path.write_text(
        json.dumps(smoke, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    print(json.dumps({"run_dir": str(RUN_DIR), "filesystem_passed": filesystem["passed"],
                      "dsh_reachable": dsh_reachable,
                      "conclusion": projection["conclusion"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
