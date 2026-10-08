"""Deterministic regenerator for the 014 legacy byte-freeze goldens (T002).

Usage::

    cd backend
    python tests/contract/fixtures/014/_generate_golden.py          # write
    python tests/contract/fixtures/014/_generate_golden.py --check  # verify only

Only the *service* layer is stubbed (``search_knowledge_core`` and
``MemoryService.start_work``). FastMCP registration, ``_convert_to_content``,
``CallToolResult`` validation and ``model_dump_json`` all stay real, so the frozen
literals are the actual serializer output rather than a hand-written guess.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp.types import CallToolResult

from rag_mcp.mcp import create_mcp_server
from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider
from rag_mcp.services.memory_service import MemoryService

import rag_mcp.mcp.search_knowledge as search_module

FIXTURE_DIR = Path(__file__).resolve().parent
REQUEST_ID = "00000000-0000-4000-8000-000000000000"


class _OfflineQdrant:
    """Sentinel vector store.

    The goldens only exercise registration and result serialization, so the real
    ``QdrantStore`` (which performs a health-check HTTP request at construction)
    is replaced to keep the freeze deterministic and network-free.
    """

    _client = None

_EVIDENCE = [
    {
        "evidence_id": "e-1",
        "content_excerpt": "excerpt",
        "source_version": 1,
        "source_position": "doc.md#L1",
        "knowledge_scope_id": "1",
        "knowledge_scope_type": "project",
        "relevance_score": 0.9,
    }
]

# Legacy `search_knowledge` response bodies, one per completion status, in the
# runtime insertion order produced by RetrievalService (success -> request_id,
# partial -> gaps appended last, failed -> error before request_id).
LEGACY_SEARCH_BODIES: dict[str, dict] = {
    "complete": {
        "completion_status": "complete",
        "evidence": _EVIDENCE,
        "request_id": REQUEST_ID,
    },
    "partial": {
        "completion_status": "partial",
        "evidence": _EVIDENCE,
        "request_id": REQUEST_ID,
        "gaps": [{"description": "insufficient evidence", "suggested_action": "broaden the query"}],
    },
    "no_evidence": {
        "completion_status": "no_evidence",
        "evidence": [],
        "request_id": REQUEST_ID,
    },
    "failed": {
        "completion_status": "failed",
        "evidence": [],
        "error": {"code": "SYSTEM_ERROR", "message": "boom"},
        "request_id": REQUEST_ID,
    },
}

# Legacy `start_work` bodies (`CallToolResult` via `memory_result`), one per
# include_working_set value.  The false branch is byte-identical to 012; the true
# branch is the 014 shape and is added by T036/T035.
LEGACY_START_WORK_BODIES: dict[str, dict] = {
    "false": {
        "scope": {"knowledge_scope_id": 1, "slug": "demo"},
        "domain_brief": {"domain_key": "coding", "description": "brief", "policy_fingerprint": "0" * 64},
        "digest": {"memories": []},
        "working_set": {"memories": []},
        "read_guidance": "Verify anchors.",
        "counts": {"returned": 0, "characters": 1, "failed_paths": [], "truncated_by_budget": 0},
        "package_fingerprint": "1" * 64,
        "request_id": REQUEST_ID,
    },
}


def _wire(structured: dict, mirror_text: str) -> str:
    """Reproduce the low-level MCP wire literal for a converted tool result."""
    from mcp.types import TextContent

    result = CallToolResult(
        structuredContent=structured,
        content=[TextContent(type="text", text=mirror_text)],
        isError=False,
    )
    return result.model_dump_json(by_alias=True, exclude_none=True)


async def _capture_search() -> dict:
    async def _capture(body: dict) -> dict:
        async def fake_core(**_kwargs):
            return body

        search_module.search_knowledge_core = fake_core
        server = create_mcp_server(embedding_provider=LocalCPUEmbeddingProvider(), qdrant_store=_OfflineQdrant(), mode="writer")
        content, structured = await server.call_tool(
            "search_knowledge", {"query": "q", "project_scope": ["p"]}
        )
        text = content[0].text
        return {
            "body_keys": list(structured),
            "pretty_mirror": text,
            "wire": _wire(structured, text),
        }

    return {branch: await _capture(body) for branch, body in LEGACY_SEARCH_BODIES.items()}


async def _capture_start_work() -> dict:
    async def _capture(body: dict, include_working_set: bool) -> dict:
        async def fake_start_work(self, **_kwargs):  # noqa: ANN001 - signature parity
            return body

        MemoryService.start_work = fake_start_work
        server = create_mcp_server(embedding_provider=LocalCPUEmbeddingProvider(), qdrant_store=_OfflineQdrant(), mode="reader")
        tool = server._tool_manager.get_tool("start_work")
        arguments = {"scope_ref": "1"}
        if "include_working_set" in tool.fn_metadata.arg_model.model_fields:
            arguments["include_working_set"] = include_working_set
        result = await server.call_tool("start_work", arguments)
        if isinstance(result, tuple):
            content, structured = result
            result = CallToolResult(structuredContent=structured, content=list(content), isError=False)
        mirror_text = result.content[0].text
        return {
            "arguments": arguments,
            "body_keys": list(result.structuredContent),
            "working_set_keys": list(result.structuredContent["working_set"]),
            "mirror": mirror_text,
            "wire": result.model_dump_json(by_alias=True, exclude_none=True),
        }

    return {
        key: await _capture(body, key == "true")
        for key, body in LEGACY_START_WORK_BODIES.items()
    }


def _normalise_scope(data: dict) -> dict:
    """Drop the include_working_set=true capture while the false branch is the freeze.

    The 014 branch is frozen by its own task (T033): the golden file carries only
    the legacy false branch, and the true branch is asserted by the contract test
    once T035/T036 land.  Keeping a stale pre-implementation true-branch literal in
    the file would make T036 look like a byte break.
    """
    legacy = data.get("false")
    return {"include_working_set_false": legacy}


async def _build() -> dict[str, dict]:
    search = await _capture_search()
    start_work = await _capture_start_work()
    return {
        "search": {
            "description": "Legacy (untriggered) search_knowledge serialization, frozen by T002",
            "tool": "search_knowledge",
            "serializer": "pydantic_core.to_json(dict, fallback=str, indent=2) as TextContent + CallToolResult.model_dump_json(by_alias=True, exclude_none=True)",
            "arguments": {"query": "q", "project_scope": ["p"]},
            "branches": search,
        },
        "start_work": {
            "description": "Legacy start_work serialization (include_working_set=false), frozen by T002",
            "tool": "start_work",
            "serializer": "json.dumps(body, ensure_ascii=False, separators=(',', ':')) via memory_result + CallToolResult.model_dump_json(by_alias=True, exclude_none=True)",
            **_normalise_scope(start_work),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify without writing")
    args = parser.parse_args(argv)

    payload = asyncio.run(_build())
    targets = {
        "legacy_search_knowledge.golden.json": payload["search"],
        "legacy_start_work.golden.json": payload["start_work"],
    }

    failures = []
    for name, data in targets.items():
        text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
        path = FIXTURE_DIR / name
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current != text:
                failures.append(name)
        else:
            path.write_text(text, encoding="utf-8", newline="\n")

    if args.check and failures:
        print("golden drift detected: " + ", ".join(failures), file=sys.stderr)
        return 1
    print("golden fixtures verified: " + ", ".join(targets) if args.check else "golden fixtures written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
