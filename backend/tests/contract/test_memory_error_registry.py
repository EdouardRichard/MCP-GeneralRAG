import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[3]
CONTRACT = ROOT / "specs/012-memory-foundation-write-read-loop/contracts/error-codes.json"


def historical_codes():
    codes = {"INVALID_INPUT", "INVALID_EVIDENCE_ID"}

    def visit(node, key=""):
        if isinstance(node, dict):
            if key == "code" or key.endswith("ErrorCode"):
                codes.update(node.get("enum", []))
            for name, value in node.items():
                visit(value, name)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    for feature in (ROOT / "specs").iterdir():
        if feature.name[:3].isdigit() and 1 <= int(feature.name[:3]) <= 11:
            for path in (feature / "contracts").glob("*.json"):
                visit(json.loads(path.read_text(encoding="utf-8")))
    return codes


def test_memory_contract_preserves_every_historical_error_code():
    codes = set(json.loads(CONTRACT.read_text(encoding="utf-8"))["items"]["enum"])
    assert historical_codes() <= codes
    assert "MEMORY_CONTENT_CONFLICT" in codes


def test_production_error_registry_matches_contract_and_preserves_legacy_codes():
    from rag_mcp.errors import ERROR_CODES, LEGACY_ERROR_CODES, MEMORY_ERROR_CODES

    assert historical_codes() <= LEGACY_ERROR_CODES
    assert ERROR_CODES == frozenset(json.loads(CONTRACT.read_text(encoding="utf-8"))["items"]["enum"])
    assert MEMORY_ERROR_CODES <= ERROR_CODES


@pytest.mark.parametrize("code", ["MEMORY_CONTENT_CONFLICT", "MEMORY_TIMEOUT", "MEMORY_QUOTA_EXCEEDED"])
def test_registered_memory_errors_keep_their_public_codes(code):
    from rag_mcp.mcp.serialization import memory_error

    result = memory_error(ValueError(code + ":private detail"))
    assert result.isError is True
    assert result.structuredContent["error"] == {"code": code, "message": code}
