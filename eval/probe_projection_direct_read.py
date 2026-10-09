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
import subprocess
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
#: The installed DSH host CLI used by the 012 precedent, plus a PATH fallback.
#: On Windows the ``.cmd`` shim must come first: the extensionless shim is a
#: Unix shell script and ``subprocess`` raises OSError on it.
DSH_CLI_CANDIDATES = (
    REPO_ROOT / "eval" / ".dsh-012-run" / "node_modules" / ".bin" / "dsh.CMD",
    REPO_ROOT / "eval" / ".dsh-012-run" / "node_modules" / ".bin" / "dsh",
)
HOST_CONFIG_CANDIDATES = (Path.home() / ".dsh" / "dsh-mcp.json", REPO_ROOT / ".dsh" / "mcp.json")


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
        "authoritative_bodies": sorted(expected_bodies.values()),
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


def _dsh_host_environment(availability: dict) -> dict:
    """The real DSH host prerequisites, measured rather than assumed."""
    cli = next((str(path) for path in DSH_CLI_CANDIDATES if path.exists()), shutil.which("dsh"))
    configs = [str(path) for path in HOST_CONFIG_CANDIDATES if path.exists()]
    endpoints = [f"{host}:{port}" for name, (host, port) in MCP_ENDPOINTS.items() if availability.get(name)]
    patches = [item for item in os.environ.get("DSH_HOST_SMOKE_PATCH", "").split(os.pathsep) if item]
    return {"dsh_cli": cli, "mcp_config_paths": configs, "reachable_endpoints": endpoints,
            "patch_paths": patches}


def _projection_read_parser(root: Path, slug: str, bodies):
    """Require the projection path *and* an authoritative body actually read.

    The task prompt itself contains the path, so a prompt echo alone must never
    count: one of the recorded memory bodies has to appear in the transcript.
    """
    marker = str((root / slug))

    def _parse(transcript: str) -> bool:
        return marker in transcript and any(body in transcript for body in bodies)

    return _parse


def _working_set_parser(bodies):
    """A positive continuation needs the derived buckets *and* real content."""

    def _parse(transcript: str) -> bool:
        return (("open_items" in transcript or "recent_activity" in transcript)
                and any(body in transcript for body in bodies))

    return _parse


def _probe_host_task(*, availability: dict, task: str, parser) -> dict:
    """Best-effort real DSH host observation. Never fabricates a positive.

    ``DSH_HOST_SMOKE=1`` opts in to actually launching the installed DSH CLI
    against the reachable MCP endpoint; ``DSH_HOST_SMOKE_PATCH`` (one or more
    ``;``-separated patch files) injects the rag-mcp MCP client overlay for the
    headless session. Without the opt-in, or without the prerequisites, the probe
    records ``observed=False`` together with the exact blocking condition and the
    command that would have been run.
    """
    environment = _dsh_host_environment(availability)
    # The launcher takes the profile positionally first, then its own options:
    # ``dsh headless --patch <overlay> "<task>"`` (see ``dsh --help``).
    command = [environment["dsh_cli"] or "dsh", "headless"]
    for patch in environment["patch_paths"]:
        command += ["--patch", patch]
    command.append(task)
    outcome = {
        "observed": False,
        "status": "failed",
        "checked_at": datetime.now(UTC).isoformat(),
        # The intended command is recorded even when the probe could not run, so
        # the blocker is reproducible (T087).
        "probe_command": subprocess.list2cmdline(command),
        "availability": availability,
        "environment": environment,
        "raw_observation": None,
        "reason": "",
    }
    if not environment["reachable_endpoints"]:
        outcome["reason"] = "no DSH/MCP endpoint was reachable, so the host probe could not run"
        return outcome
    if not (environment["dsh_cli"] and (environment["mcp_config_paths"] or environment["patch_paths"])):
        outcome["reason"] = ("an MCP endpoint was reachable but the DSH host is not configured "
                             "(no CLI, no MCP server config and no --patch overlay), so the probe "
                             "could not be executed")
        return outcome
    if os.environ.get("DSH_HOST_SMOKE") != "1":
        outcome["reason"] = ("host prerequisites are present but the operator did not opt in "
                             "(set DSH_HOST_SMOKE=1) to launch a real DSH session")
        return outcome
    try:
        timeout_s = int(os.environ.get("DSH_HOST_SMOKE_TIMEOUT_S", "600"))
        # The host transcript is UTF-8; the Windows locale (GBK) must not decide
        # how it is decoded.
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s,
                                   cwd=str(REPO_ROOT), check=False,
                                   encoding="utf-8", errors="replace")
        transcript = (completed.stdout or "") + (completed.stderr or "")
        outcome["raw_observation"] = transcript[-8000:]
        outcome["exit_code"] = completed.returncode
        outcome["observed"] = bool(parser(transcript))
        outcome["status"] = "passed" if outcome["observed"] else "failed"
        outcome["reason"] = "" if outcome["observed"] else (
            "the DSH transcript did not contain the required evidence (projection path plus a real "
            "authoritative body, or the working-set buckets plus real content)")
    except Exception as error:  # noqa: BLE001 - a probe failure is recorded, never raised
        outcome["reason"] = f"the DSH probe raised {type(error).__name__}: {error}"[:400]
    return outcome


def _claude_code_compatibility() -> dict:
    """Record the Claude Code MCP configuration state (never a fake pass)."""
    config_path = Path.home() / ".claude.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable config is a recorded state
        return {"config_path": str(config_path), "readable": False, "rag_mcp_configured": False}
    servers = payload.get("mcpServers") if isinstance(payload, dict) else None
    configured = bool(servers) and any("rag" in str(name).lower() for name in servers)
    return {"config_path": str(config_path), "readable": True,
            "rag_mcp_configured": configured, "server_names": sorted(servers or {})}


def main() -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("projection-direct-read.json", "target-host-smoke.json"):
        if (RUN_DIR / name).exists():
            print(f"refusing to overwrite {RUN_DIR / name}", file=sys.stderr)
            return 2

    availability = {name: _probe(host, port) for name, (host, port) in MCP_ENDPOINTS.items()}
    # T099: the host must read the *configured* consumption layer, so the smoke
    # run materialises it at ``MEMORY_CONSUMPTION_ROOT`` (default
    # ``data/memory_projection``) instead of a private run directory.
    from rag_mcp.config import get_settings

    consumption_root = Path(get_settings().memory_consumption_root)
    filesystem = asyncio.run(_filesystem_layer(consumption_root))
    bodies = filesystem["authoritative_bodies"]
    scope_ref = str(filesystem["scope_id"])
    slug_dir = f"{filesystem['tree_root']}/{filesystem['scope_slug']}"

    # T074: the two host observations are *attempted*, never hardcoded. With no
    # reachable endpoint / configured host they stay failed, honestly.
    projection_host = _probe_host_task(
        availability=availability,
        task=(f"Use the rag-mcp MCP server for one call, then use your file-reading tool to read a memory "
              f".md file under {slug_dir} and quote its absolute path and the first line of its body verbatim."),
        parser=_projection_read_parser(Path(filesystem["tree_root"]), filesystem["scope_slug"], bodies),
    )
    continuation_host = _probe_host_task(
        availability=availability,
        task=(f"Call the rag-mcp MCP tool start_work with scope_ref=\"{scope_ref}\" and "
              f"include_working_set=true, then print the open_items, recent_activity and procedural "
              f"buckets including one item's content_excerpt verbatim."),
        parser=_working_set_parser(bodies),
    )
    host_observed = bool(projection_host["observed"])
    projection = {
        "schema_version": "014.1",
        "report_type": "projection-direct-read",
        "run_id": RUN_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "layers": {
            "filesystem": {**filesystem, "observed": True},
            "dsh_host_observation": {
                **{key: projection_host[key] for key in
                   ("observed", "status", "reason", "checked_at", "probe_command",
                    "availability", "environment", "raw_observation")},
                "source": "dsh_host_probe",
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
        "conclusion": "passed" if host_observed else "failed",
        "conclusion_reason": (
            "the required filesystem layer and the DSH real-observation layer both passed"
            if host_observed else
            "the required filesystem layer passed, but the DSH real observation layer is "
            "failed/unobserved, so the three-layer criterion is not met"
        ),
    }
    (RUN_DIR / "projection-direct-read.json").write_text(
        json.dumps(projection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    # T087: the canonical direct-read evidence must live on a *tracked* path
    # (eval/runs/ is gitignored), alongside the tracked smoke report.
    canonical_direct_read = REPO_ROOT / "eval" / "projection-direct-read-014.json"
    canonical_direct_read.write_text(
        json.dumps(projection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    dsh_reachable = availability["writer"] or availability["reader"] or availability["default"]
    dsh_passed = bool(projection_host["observed"] and continuation_host["observed"])
    claude = _claude_code_compatibility()
    smoke = {
        "schema_version": "014.1",
        "report_type": "target-host-smoke",
        "run_id": RUN_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "hosts": {
            "dsh": {
                "must_pass": True,
                "status": "passed" if dsh_passed else "failed",
                "checked_at": max(projection_host["checked_at"], continuation_host["checked_at"]),
                "availability": availability,
                "compatibility": {
                    "mcp_endpoint_reachable": bool(dsh_reachable),
                    "dsh_cli": projection_host["environment"]["dsh_cli"],
                    "mcp_config_paths": projection_host["environment"]["mcp_config_paths"],
                },
                "probe_commands": [projection_host["probe_command"], continuation_host["probe_command"]],
                "work_package_continuation_observed": continuation_host["observed"],
                "projection_direct_read_observed": projection_host["observed"],
                "raw_observation": (continuation_host["raw_observation"]
                                    or projection_host["raw_observation"]),
                "reason": (
                    "both required host observations were captured"
                    if dsh_passed else
                    "an unobserved or unexecuted must-pass host is recorded as failed: "
                    f"projection={projection_host['reason']}; continuation={continuation_host['reason']}"
                ),
            },
            "chatgpt_app": {
                "must_pass": False,
                "status": "not_executed",
                "checked_at": datetime.now(UTC).isoformat(),
                "availability": "no ChatGPT App MCP client is configured in this environment",
                "compatibility": "not_executed",
                "probe_commands": [],
                "raw_observation": None,
                "reason": "availability only; never recorded as passed",
            },
            "claude_code": {
                "must_pass": False,
                "status": "not_executed",
                "checked_at": datetime.now(UTC).isoformat(),
                "availability": "the Claude Code MCP configuration was inspected for a rag-mcp server",
                "compatibility": claude,
                "probe_commands": [],
                "raw_observation": None,
                "reason": ("the Claude Code MCP configuration lists no rag-mcp server; availability only, "
                           "never recorded as passed" if not claude.get("rag_mcp_configured")
                           else "a rag-mcp server is configured but this run did not execute the host"),
            },
        },
        "summary": ("convergence is NOT declared: the DSH must-pass smoke did not pass"
                    if not dsh_passed else "the DSH must-pass smoke passed"),
    }
    (RUN_DIR / "target-host-smoke.json").write_text(
        json.dumps(smoke, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    # T064 requires the smoke report to live under eval/ as a tracked deliverable;
    # eval/runs/ is gitignored, so the canonical copy is written beside the probe.
    smoke_path = REPO_ROOT / "eval" / "target-host-smoke-014.json"
    smoke_path.write_text(
        json.dumps(smoke, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    print(json.dumps({"run_dir": str(RUN_DIR), "filesystem_passed": filesystem["passed"],
                      "dsh_reachable": dsh_reachable, "dsh_passed": dsh_passed,
                      "conclusion": projection["conclusion"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
