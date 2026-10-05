from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from rag_mcp.mcp.serialization import close_input_schema, memory_error, memory_result
from rag_mcp.services.memory_service import MemoryService


def register_recall_memory_tool(server, session_factory, embedding_provider, qdrant_store):
    @server.tool(name="recall_memory", annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True))
    async def recall_memory(
        scope_ref: Annotated[list[str], Field(min_length=1)],
        query: Annotated[str | None, Field(max_length=2000)] = None, memory_ids: list[int] | None = None,
        kind: Literal["episodic", "semantic", "procedural"] | None = None,
        session_id: UUID | None = None, agent_id: str | None = None, time_window: dict | None = None,
        as_of: datetime | None = None, include_superseded: bool = False, include_delivered: bool = False,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> CallToolResult:
        """Recall only explicitly scoped completed memory; semantic status is verified in PG."""
        try:
            async with session_factory() as session:
                result = await MemoryService(session, embedding_provider=embedding_provider, qdrant_store=qdrant_store).recall(
                    scope_ref=scope_ref, query=query, memory_ids=memory_ids, kind=kind,
                    session_id=str(session_id) if session_id else None, agent_id=agent_id, time_window=time_window,
                    as_of=as_of, include_superseded=include_superseded, include_delivered=include_delivered, limit=limit)
                return memory_result(result, is_error=result["completion_status"] == "failed")
        except Exception as exception:
            return memory_error(exception)
    close_input_schema(server, "recall_memory")
