from typing import Annotated, Literal
from uuid import UUID

from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field, StrictFloat, StrictInt

from rag_mcp.mcp.serialization import close_input_schema, memory_error, memory_result
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.services.scope_resolver import MemoryScopeResolver


def register_record_memory_tool(server, session_factory, embedding_provider, qdrant_store):
    @server.tool(name="record_memory", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False))
    async def record_memory(
        scope_ref: Annotated[str, Field(min_length=1)],
        kind: Literal["episodic", "semantic", "procedural"],
        content: Annotated[str, Field(min_length=1, max_length=4000)],
        provenance: Literal["hard", "soft", "distilled"],
        evidence_refs: list[str] | None = None, inference_meta: dict | None = None,
        confidence: Annotated[StrictFloat | None, Field(ge=0, le=1)] = None,
        title: str | None = None, tags: list[str] | None = None, session_id: UUID | None = None,
        agent_id: str | None = None, task_context: dict | None = None, supersedes_memory_id: StrictInt | None = None,
    ) -> CallToolResult:
        """Record scoped, sanitized memory with validated provenance and synchronous projections."""
        try:
            async with session_factory() as session:
                scope_id = await MemoryScopeResolver(session).resolve(scope_ref)
                payload = {"scope_id": scope_id, "kind": kind, "content": content, "provenance": provenance,
                    "evidence_refs": evidence_refs, "inference_meta": inference_meta, "confidence": confidence,
                    "title": title, "tags": tags, "session_id": str(session_id) if session_id else None,
                    "agent_id": agent_id, "task_context": task_context, "supersedes_memory_id": supersedes_memory_id}
                result = await MemoryService(session, embedding_provider=embedding_provider, qdrant_store=qdrant_store).record(payload)
                return memory_result(result)
        except Exception as exception:
            return memory_error(exception)
    close_input_schema(server, "record_memory")
