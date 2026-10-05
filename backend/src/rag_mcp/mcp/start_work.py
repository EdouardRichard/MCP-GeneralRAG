from typing import Annotated, Literal
from uuid import UUID

from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from rag_mcp.mcp.serialization import close_input_schema, memory_error, memory_result
from rag_mcp.services.memory_service import MemoryService


def register_start_work_tool(server, session_factory, embedding_provider, qdrant_store):
    @server.tool(name="start_work", annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True))
    async def start_work(
        scope_ref: Annotated[str, Field(min_length=1)], session_id: UUID | None = None,
        task_hint: str | None = None, agent_id: str | None = None,
        include: Literal["both"] = "both", budget: Literal["standard", "compact", "minimal"] = "standard",
    ) -> CallToolResult:
        """Read a stable scoped digest and working set; never write memory, sessions or package snapshots."""
        try:
            async with session_factory() as session:
                result = await MemoryService(session, embedding_provider=embedding_provider, qdrant_store=qdrant_store).start_work(
                    scope_ref=scope_ref, session_id=str(session_id) if session_id else None, task_hint=task_hint,
                    agent_id=agent_id, include=include, budget=budget)
                return memory_result(result)
        except Exception as exception:
            return memory_error(exception)
    close_input_schema(server, "start_work")
