import json
from pathlib import Path
from jsonschema import Draft202012Validator
import pytest


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

