"""Contract test for the 007 MCP input extension (T026).

FR-007/FR-010/FR-021: search/get-evidence inputs relax required project_scope to
anyOf (project_scope OR domain_scope), add domain_scope, and the error-code enum
is additive (old codes kept + MISSING_KNOWLEDGE_SCOPE / AMBIGUOUS_DOMAIN_REF).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

_CONTRACTS = Path(__file__).resolve().parents[3] / "specs/007-knowledge-domain-generalization/contracts"


def _load(name: str) -> dict:
    with open(_CONTRACTS / name, encoding="utf-8") as f:
        return json.load(f)


def _merged(schema: dict, common: dict) -> dict:
    merged = copy.deepcopy(schema)
    merged.setdefault("$defs", {})
    merged["$defs"].update(copy.deepcopy(common["definitions"]))
    prefixes = (common["$id"] + "#/definitions/", "common.schema.json#/definitions/")

    def _rewrite(obj):
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if k == "$ref" and isinstance(v, str):
                    for p in prefixes:
                        if v.startswith(p):
                            obj[k] = "#/$defs/" + v[len(p):]
                            break
                else:
                    _rewrite(v)
        elif isinstance(obj, list):
            for item in obj:
                _rewrite(item)

    _rewrite(merged)
    return merged


def _search_validator() -> Draft202012Validator:
    return Draft202012Validator(_merged(_load("mcp-search-input.schema.json"), _load("common.schema.json")))


def _evidence_validator() -> Draft202012Validator:
    return Draft202012Validator(_merged(_load("mcp-get-evidence.schema.json"), _load("common.schema.json")))


def test_search_input_any_of():
    v = _search_validator()
    # only project_scope valid
    v.validate({"query": "q", "project_scope": ["p1"]})
    # only domain_scope valid
    v.validate({"query": "q", "domain_scope": ["public:法规库"]})
    # both missing -> invalid
    errors = list(v.iter_errors({"query": "q"}))
    assert errors


def test_evidence_input_any_of():
    v = _evidence_validator()
    v.validate({"input": {"evidence_id": "1", "project_scope": ["p1"]}, "output": {"evidence_id": "1", "status": "available"}})
    v.validate({"input": {"evidence_id": "1", "domain_scope": ["slug-x"]}, "output": {"evidence_id": "1", "status": "available"}})


def test_error_code_enum_additive():
    common = _load("common.schema.json")
    codes = common["definitions"]["KnowledgeScopeErrorCode"]["enum"]
    old = {"SYSTEM_ERROR", "MISSING_PROJECT_SCOPE", "AMBIGUOUS_PROJECT_REF", "INVALID_PROJECT_REF", "INDEX_UNAVAILABLE"}
    new = {"MISSING_KNOWLEDGE_SCOPE", "AMBIGUOUS_DOMAIN_REF"}
    assert old <= set(codes)
    assert new <= set(codes)
