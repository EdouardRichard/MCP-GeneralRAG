"""Pure budget checks for the memory reader envelopes (T104/T105)."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

from rag_mcp.mcp.serialization import memory_result
from rag_mcp.mcp.recall_memory import register_recall_memory_tool
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.services.memory_reader import MemoryReader, serialized_characters
from rag_mcp.services.scope_resolver import MemoryScopeResolver


def test_recall_character_count_matches_mcp_json_mirror():
    body = {
        "completion_status": "partial",
        "memories": [{"memory_id": 7, "content_excerpt": "x" * 300,
                      "inference_meta": {"source": "m" * 200}}],
        "counts": {"mode": "timeline", "returned": 1, "characters": 0},
        "memory_notice": {"failed_paths": ["dense_unavailable"], "untrusted": True},
        "request_id": "00000000-0000-0000-0000-000000000007",
    }
    body["counts"]["characters"] = serialized_characters(body)
    result = memory_result(body)
    assert body["counts"]["characters"] == len(result.content[0].text)


@pytest.mark.asyncio
async def test_start_work_keeps_measurable_minimal_envelope_with_many_failures(monkeypatch):
    class Session:
        def __init__(self):
            # 014 T029: start_work also records its delivered-channel audit row,
            # so the fake session has to accept the additive write. The package
            # body assertions below still pin the 012 bytes.
            self.audits = []

        async def get(self, model, key):
            if model is KnowledgeScope:
                return SimpleNamespace(slug="scope", domain_key="generic")
            if model is DomainProfile:
                return SimpleNamespace(description="", memory_policy={
                    "start_work_budgets": {"minimal": 250},
                })
            raise AssertionError(model)

        async def commit(self):
            return None

        def add(self, row):
            self.audits.append(row)

    async def resolve(self, reference):
        return 7

    async def views(self, *args, **kwargs):
        return {}, {}, [], ["relation", "dense", "links", "summary", "files", "salience", "integrity"]

    monkeypatch.setattr(MemoryScopeResolver, "resolve", resolve)
    monkeypatch.setattr(MemoryReader, "_views", views)

    session = Session()
    result = await MemoryReader(session, None).start_work(scope_ref="7", budget="minimal")
    body = {key: value for key, value in result.items() if key != "request_id"}
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    assert len(encoded) <= 250
    assert body["read_guidance"]
    assert body["counts"]["characters"] == len(encoded)
    # The additive audit write must not change the package body.
    assert session.audits and session.audits[-1].channel == "start_work"


@pytest.mark.asyncio
async def test_recall_keeps_committed_result_when_session_exit_times_out(monkeypatch):
    class Session:
        def __init__(self):
            self.audits = []

        async def execute(self, *args):
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

        def add(self, audit):
            self.audits.append(audit)

    session = Session()

    class Context:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc_info):
            await asyncio.sleep(3.2)

    async def resolve_many(self, reference):
        return [7]

    async def views(self, *args, **kwargs):
        return {}, {}, [], []

    monkeypatch.setattr(MemoryScopeResolver, "resolve_many", resolve_many)
    monkeypatch.setattr(MemoryReader, "_views", views)
    server = FastMCP("recall-cleanup")
    register_recall_memory_tool(server, lambda: Context(), None, None)

    result = await server.call_tool("recall_memory", {"scope_ref": ["7"]})
    assert not result.isError
    assert session.audits
    assert result.structuredContent["request_id"] == session.audits[-1].request_id

