import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID
from jsonschema import Draft202012Validator
import pytest

from rag_mcp.services.scope_binding_service import ScopeBindingError


def test_memory_contract_schemas_load():
    root = Path(__file__).parents[3] / "specs/012-memory-foundation-write-read-loop/contracts"
    names = ["mcp-record-memory.input.schema.json", "mcp-record-memory.output.schema.json", "mcp-recall-memory.input.schema.json", "mcp-recall-memory.output.schema.json", "mcp-start-work.input.schema.json", "mcp-start-work.output.schema.json", "memory-entry.schema.json", "memory-event.schema.json", "memory-management.schema.json", "error-codes.json"]
    for name in names:
        schema = json.loads((root / name).read_text(encoding="utf-8"))
        assert schema
        if name.endswith(".schema.json"):
            Draft202012Validator.check_schema(schema)


def test_acceptance_report_requires_suite_host_and_seventeen_criteria():
    root = Path(__file__).parents[3] / "specs/012-memory-foundation-write-read-loop/contracts"
    schema = json.loads((root / "acceptance-report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert not validator.is_valid({"report_type": "012_memory_acceptance", "status": "passed"})
    criteria = schema["properties"]["success_criteria"]
    assert criteria["minItems"] == criteria["maxItems"] == 17
    assert schema["properties"]["host"]["required"] == ["name", "workspace", "status", "evidence"]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments,failure,code,candidates", [
    ({"scope_ref": ["explicit"], "memory_ids": [1], "query": "conflict"},
     None, "MEMORY_IDS_QUERY_CONFLICT", None),
    ({"scope_ref": [" "]}, None, "MISSING_KNOWLEDGE_SCOPE", None),
    ({"scope_ref": ["ambiguous"]}, ScopeBindingError("AMBIGUOUS_DOMAIN_REF", [7, 9]),
     "AMBIGUOUS_DOMAIN_REF", [7, 9]),
    ({"scope_ref": ["explicit"]}, TimeoutError("private timeout detail"), "MEMORY_TIMEOUT", None),
    ({"scope_ref": ["explicit"]}, RuntimeError("private system detail"), "SYSTEM_ERROR", None),
])
async def test_actual_recall_failures_satisfy_output_schema(arguments, failure, code, candidates):
    from mcp.server.fastmcp import FastMCP
    from mcp.shared.memory import create_connected_server_and_client_session
    from rag_mcp.mcp.recall_memory import register_recall_memory_tool

    @asynccontextmanager
    async def sessions():
        if failure is not None:
            raise failure
        # Conflict and blank scope validation stop before database access.
        yield None

    server = FastMCP("recall-error-contract")
    register_recall_memory_tool(server, sessions, None, None)
    schema_path = Path(__file__).parents[3] / "specs/012-memory-foundation-write-read-loop/contracts/mcp-recall-memory.output.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("recall_memory", arguments)
    assert result.isError
    body = result.structuredContent
    Draft202012Validator(schema).validate(body)
    assert body["completion_status"] == "failed"
    assert body["memories"] == []
    assert body["counts"]["returned"] == 0
    assert body["error"] == {"code": code, "message": code, **({"candidates": candidates} if candidates else {})}
    assert str(UUID(body["request_id"])) == body["request_id"]
    assert json.loads(result.content[0].text) == body


def test_shared_memory_error_keeps_existing_json_bytes(monkeypatch):
    from rag_mcp.mcp import serialization

    request_id = UUID("00000000-0000-0000-0000-000000000001")
    monkeypatch.setattr(serialization, "uuid4", lambda: request_id)
    result = serialization.memory_error(ScopeBindingError("AMBIGUOUS_DOMAIN_REF", [7, 9]))
    assert result.content[0].text == ('{"error":{"code":"AMBIGUOUS_DOMAIN_REF","message":"AMBIGUOUS_DOMAIN_REF",'
                                   '"candidates":[7,9]},"request_id":"00000000-0000-0000-0000-000000000001"}')
    assert set(result.structuredContent) == {"error", "request_id"}
    assert json.loads(result.content[0].text) == result.structuredContent

