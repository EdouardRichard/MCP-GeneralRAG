"""One canonical structured result and its deterministic JSON mirror."""
import json
from uuid import uuid4

from mcp.types import CallToolResult, TextContent

from rag_mcp.errors import MEMORY_ERROR_CODES, MemoryContentConflictError


def memory_result(body, *, is_error=False):
    return CallToolResult(structuredContent=body,
        content=[TextContent(type="text", text=json.dumps(body, ensure_ascii=False, separators=(",", ":")))],
        isError=is_error)


def memory_error(exception):
    code = str(exception).split(":", 1)[0]
    if isinstance(exception, TimeoutError):
        code = "MEMORY_TIMEOUT"
    if code not in MEMORY_ERROR_CODES:
        code = "MEMORY_PROVENANCE_INVALID" if isinstance(exception, ValueError) else "SYSTEM_ERROR"
    error = {"code": code, "message": code}
    if isinstance(exception, MemoryContentConflictError):
        error["memory_id"] = exception.memory_id
    if getattr(exception, "candidates", None):
        error["candidates"] = exception.candidates
    return memory_result({"error": error, "request_id": str(uuid4())}, is_error=True)


def close_input_schema(server, name):
    # FastMCP's generated argument model otherwise silently ignores extra fields.
    tool = server._tool_manager.get_tool(name)
    tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
    tool.fn_metadata.arg_model.model_rebuild(force=True)
    tool.parameters = tool.fn_metadata.arg_model.model_json_schema(by_alias=True)
