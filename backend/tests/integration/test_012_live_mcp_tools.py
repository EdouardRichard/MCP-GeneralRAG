import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from mcp.types import CallToolResult
from sqlalchemy import select, func

from rag_mcp.mcp import create_mcp_server
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider
from rag_mcp.utils.snowflake import generate_id


@pytest.mark.asyncio
async def test_actual_mcp_calls_persist_and_serialize_one_fact_source(db_session, memory_writer_owner):
    sid = generate_id()
    db_session.add(KnowledgeScope(scope_id=sid, name="MCP acceptance", slug=f"mcp-{sid}", scope_type="project", domain_key="generic"))
    await db_session.commit()
    @asynccontextmanager
    async def sessions():
        yield db_session
    provider = LocalCPUEmbeddingProvider()
    server = create_mcp_server(session_factory=sessions, embedding_provider=provider, mode="writer")
    payload = {"scope_ref": str(sid), "kind": "procedural", "content": f"Maintain explicit scope {uuid4()}.",
        "provenance": "soft", "inference_meta": {"source": "012 MCP acceptance", "confidence": .8,
        "model_version": "acceptance-v1", "time": datetime.now(timezone.utc).isoformat(), "supporting_evidence": []}}
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert set(tools["record_memory"].inputSchema["properties"]) >= set(payload), "internal placeholder signature exposed"
    record = await server.call_tool("record_memory", payload)
    assert isinstance(record, CallToolResult) and not record.isError
    assert json.loads(record.content[0].text) == record.structuredContent
    identifier = record.structuredContent["memory_id"]
    recall = await server.call_tool("recall_memory", {"scope_ref": [str(sid)], "memory_ids": [identifier]})
    assert isinstance(recall, CallToolResult)
    assert json.loads(recall.content[0].text) == recall.structuredContent
    assert recall.structuredContent["memories"][0]["memory_id"] == identifier
    work = await server.call_tool("start_work", {"scope_ref": str(sid)})
    assert json.loads(work.content[0].text) == work.structuredContent
    assert work.structuredContent["digest"]["memories"][0]["memory_id"] == identifier
    before = await db_session.scalar(select(func.count()).select_from(MemoryEvent))
    rejected = await server.call_tool("record_memory", {**payload, "content": "unanchored fact", "provenance": "hard", "inference_meta": None})
    assert rejected.isError
    assert rejected.structuredContent["error"]["code"] == "MEMORY_EVIDENCE_ANCHOR_REQUIRED"
    assert json.loads(rejected.content[0].text) == rejected.structuredContent
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent)) == before


@pytest.mark.asyncio
async def test_writer_tool_refuses_without_management_ownership(db_session):
    from tests.integration.test_012_live_reader import scope_and_payload
    sid, payload = await scope_and_payload(db_session)
    @asynccontextmanager
    async def sessions():
        yield db_session
    server = create_mcp_server(session_factory=sessions, embedding_provider=LocalCPUEmbeddingProvider(), mode="writer")
    arguments = {key: value for key, value in payload.items() if key != "scope_id"}
    result = await server.call_tool("record_memory", {**arguments, "scope_ref": str(sid)})
    assert result.isError and result.structuredContent["error"]["code"] == "MEMORY_WRITE_UNAVAILABLE"
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent).where(MemoryEvent.knowledge_scope_id == sid)) == 0


@pytest.mark.asyncio
async def test_management_renewal_keeps_owner_registration_alive(engine, monkeypatch):
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from rag_mcp import server as management
    from rag_mcp.models.runtime import InstanceRegistry
    from tests.integration.memory_acceptance import writer_owner
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with writer_owner(engine) as owner:
        async with factory() as session:
            original = (await session.get(InstanceRegistry, owner.holder_instance_id)).last_heartbeat_at
        calls = 0
        async def one_cycle(seconds):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise asyncio.CancelledError
        monkeypatch.setattr(management.asyncio, "sleep", one_cycle)
        monkeypatch.setattr("rag_mcp.db.get_session_factory", lambda: factory)
        with pytest.raises(asyncio.CancelledError):
            await management._lease_renewal_loop(owner.lease_id, 0, 300)
        async with factory() as session:
            registered = await session.get(InstanceRegistry, owner.holder_instance_id)
            assert registered.last_heartbeat_at > original
