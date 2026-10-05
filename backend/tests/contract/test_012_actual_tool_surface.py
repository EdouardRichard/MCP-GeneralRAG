"""Inspect actual FastMCP registration, not a separately maintained name list."""
import pytest

from rag_mcp.mcp import create_mcp_server
from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["writer", "reader"])
async def test_actual_tool_names_and_read_only_annotations(mode):
    server = create_mcp_server(embedding_provider=LocalCPUEmbeddingProvider(), mode=mode)
    tools = {tool.name: tool for tool in await server.list_tools()}
    expected = {"search_knowledge", "get_evidence", "list_knowledge_domains", "recall_memory", "start_work"}
    if mode == "writer":
        expected.add("record_memory")
    assert set(tools) == expected
    for name in ("recall_memory", "start_work"):
        assert tools[name].annotations is not None, f"{name} has no actual ToolAnnotations"
        assert tools[name].annotations.readOnlyHint is True
        assert tools[name].annotations.idempotentHint is True
        assert tools[name].annotations.destructiveHint is False
    if mode == "writer":
        assert tools["record_memory"].annotations.readOnlyHint is False
        assert tools["record_memory"].annotations.idempotentHint is False


@pytest.mark.asyncio
async def test_generated_memory_schema_exposes_contract_inputs_only():
    server = create_mcp_server(embedding_provider=LocalCPUEmbeddingProvider(), mode="writer")
    tools = {tool.name: tool for tool in await server.list_tools()}
    expected = {
        "record_memory": {"scope_ref", "kind", "content", "provenance", "evidence_refs", "inference_meta",
                          "confidence", "title", "tags", "session_id", "agent_id", "task_context", "supersedes_memory_id"},
        "recall_memory": {"scope_ref", "query", "memory_ids", "kind", "session_id", "agent_id", "time_window",
                          "as_of", "include_superseded", "include_delivered", "limit"},
        "start_work": {"scope_ref", "session_id", "task_hint", "agent_id", "include", "budget"},
    }
    for name, fields in expected.items():
        schema = tools[name].inputSchema
        assert set(schema["properties"]) == fields
        assert "scope_ref" in schema["required"]
        assert schema.get("additionalProperties") is False


def test_unknown_mode_does_not_silently_become_reader():
    with pytest.raises(ValueError, match="mode"):
        create_mcp_server(embedding_provider=LocalCPUEmbeddingProvider(), mode="typo")
