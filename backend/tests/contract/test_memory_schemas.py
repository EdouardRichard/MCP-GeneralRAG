import json
from pathlib import Path


def test_memory_contract_schemas_load():
    root = Path(__file__).parents[3] / "specs/012-memory-foundation-write-read-loop/contracts"
    names = ["mcp-record-memory.input.schema.json", "mcp-record-memory.output.schema.json", "mcp-recall-memory.input.schema.json", "mcp-recall-memory.output.schema.json", "mcp-start-work.input.schema.json", "mcp-start-work.output.schema.json", "memory-entry.schema.json", "memory-event.schema.json", "memory-management.schema.json", "error-codes.json"]
    for name in names:
        assert json.loads((root / name).read_text(encoding="utf-8"))

