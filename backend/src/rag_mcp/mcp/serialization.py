"""One canonical structured result and its deterministic JSON mirror."""
import json
from uuid import uuid4

from mcp.types import CallToolResult, TextContent


def memory_result(body, *, is_error=False):
    return CallToolResult(structuredContent=body,
        content=[TextContent(type="text", text=json.dumps(body, ensure_ascii=False, separators=(",", ":")))],
        isError=is_error)


def memory_error(exception):
    known = {"MISSING_KNOWLEDGE_SCOPE", "AMBIGUOUS_DOMAIN_REF", "MEMORY_EVIDENCE_ANCHOR_REQUIRED",
        "MEMORY_EVIDENCE_SCOPE_MISMATCH", "MEMORY_INFERENCE_META_INCOMPLETE", "MEMORY_PROVENANCE_INVALID",
        "MEMORY_KIND_INVALID", "MEMORY_SUPERSEDE_TARGET_INVALID", "MEMORY_QUOTA_EXCEEDED",
        "MEMORY_WRITE_UNAVAILABLE", "MEMORY_IDS_QUERY_CONFLICT", "MEMORY_ROLLBACK_FORBIDDEN", "MEMORY_TIMEOUT"}
    code = str(exception).split(":", 1)[0]
    if isinstance(exception, TimeoutError):
        code = "MEMORY_TIMEOUT"
    if code not in known:
        code = "MEMORY_PROVENANCE_INVALID" if isinstance(exception, ValueError) else "SYSTEM_ERROR"
    error = {"code": code, "message": code}
    if getattr(exception, "candidates", None):
        error["candidates"] = exception.candidates
    return memory_result({"error": error, "request_id": str(uuid4())}, is_error=True)


def close_input_schema(server, name):
    # FastMCP's generated argument model otherwise silently ignores extra fields.
    tool = server._tool_manager.get_tool(name)
    tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
    tool.fn_metadata.arg_model.model_rebuild(force=True)
    tool.parameters = tool.fn_metadata.arg_model.model_json_schema(by_alias=True)
