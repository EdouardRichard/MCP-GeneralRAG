import json
from contextlib import asynccontextmanager

import pytest
from mcp.server.fastmcp import FastMCP
from rag_mcp.mcp import create_mcp_server
from rag_mcp.mcp.get_evidence import register_get_evidence_tool
from rag_mcp.mcp.list_knowledge_domains import register_list_knowledge_domains_tool
from rag_mcp.mcp.search_knowledge import register_search_knowledge_tool
from rag_mcp.indexing.qdrant_client import QdrantStore
from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider


def legacy_server(factory, qdrant, embedding):
    server = FastMCP("legacy-three-tool-client")
    register_search_knowledge_tool(server, factory, qdrant, embedding, None)
    register_get_evidence_tool(server, factory)
    register_list_knowledge_domains_tool(server, factory)
    return server


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["writer", "reader"])
async def test_actual_legacy_tool_schemas_and_response_bytes_survive_memory_registration(db_session, mode, monkeypatch):
    from uuid import UUID
    monkeypatch.setattr("uuid.uuid4", lambda: UUID("00000000-0000-4000-8000-000000000001"))
    @asynccontextmanager
    async def factory():
        yield db_session
    qdrant, embedding = QdrantStore(), LocalCPUEmbeddingProvider()
    baseline = legacy_server(factory, qdrant, embedding)
    extended = create_mcp_server(session_factory=factory, qdrant_store=qdrant, embedding_provider=embedding, mode=mode)
    before = {tool.name: tool for tool in await baseline.list_tools()}
    after = {tool.name: tool for tool in await extended.list_tools()}
    for name, tool in before.items():
        assert json.dumps(tool.model_dump(), sort_keys=True) == json.dumps(after[name].model_dump(), sort_keys=True)
    assert len(after) == (6 if mode == "writer" else 5)
    assert ("record_memory" in after) == (mode == "writer")
    for name, arguments in (("list_knowledge_domains", {}),
                            ("get_evidence", {"evidence_id": "123"}),
                            ("search_knowledge", {"query": "no implicit scope", "project_scope": []})):
        old = await baseline.call_tool(name, arguments)
        new = await extended.call_tool(name, arguments)
        assert old == new, name

