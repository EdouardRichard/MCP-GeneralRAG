"""Contract test for domain-profiles.management.schema.json (007, T001).

FR-003/FR-004/FR-021: the management schema's profile record and
scope_assignment structures are valid JSON Schema 2020-12, and the builtin seed
content shape (config/domain_profiles.py) matches the declared contract.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from rag_mcp.config.domain_profiles import BUILTIN_DOMAIN_PROFILES

_CONTRACTS = (
    Path(__file__).resolve().parents[3] / "specs" / "007-knowledge-domain-generalization" / "contracts"
)


def _load(name: str) -> dict:
    with open(_CONTRACTS / name, encoding="utf-8") as f:
        return json.load(f)


def _merged(schema: dict, common: dict) -> dict:
    """Inline common definitions and rewrite $refs (same approach as 006)."""
    merged = copy.deepcopy(schema)
    merged.setdefault("$defs", {})
    merged["$defs"].update(copy.deepcopy(common["definitions"]))
    prefixes = (
        common["$id"] + "#/definitions/",
        "common.schema.json#/definitions/",
    )

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


def _validator() -> Draft202012Validator:
    schema = _merged(_load("domain-profiles.management.schema.json"), _load("common.schema.json"))
    return Draft202012Validator(schema)


def _profile_record(key: str) -> dict:
    seed = BUILTIN_DOMAIN_PROFILES[key]
    return {
        "domain_key": key,
        "name": seed["name"],
        "description": seed.get("description"),
        "supported_formats": seed["supported_formats"],
        "chunk_type_extensions": seed.get("chunk_type_extensions"),
        "graph_relations": seed["graph_relations"],
        "prompt_overrides": seed.get("prompt_overrides"),
        "default_capabilities": seed["default_capabilities"],
        "is_builtin": seed["is_builtin"],
    }


def test_schema_is_valid_json_schema():
    Draft202012Validator.check_schema(_load("domain-profiles.management.schema.json"))


def test_profile_record_shape_validates():
    validator = _validator()
    for key in BUILTIN_DOMAIN_PROFILES:
        validator.validate({"profile": _profile_record(key)})


def test_scope_assignment_shape_validates():
    validator = _validator()
    validator.validate({"profile": _profile_record("se-project"), "scope_assignment": {"domain_key": "generic", "slug": "regulations"}})
    validator.validate({"profile": _profile_record("se-project"), "scope_assignment": {"slug": "my-domain"}})


def test_builtin_seed_is_declaration_only():
    """FR-006: profile declarations must not contain knowledge content."""
    se = BUILTIN_DOMAIN_PROFILES["se-project"]
    assert set(se["supported_formats"]) == {
        "markdown", "java", "openapi", "ddl", "go", "python", "word", "pdf",
    }
    assert set(se["graph_relations"].keys()) == {
        "calls", "called_by", "fk_references", "fk_referenced_by",
    }
    assert se["is_builtin"] is True
    assert BUILTIN_DOMAIN_PROFILES["generic"]["is_builtin"] is True
    assert BUILTIN_DOMAIN_PROFILES["generic"]["graph_relations"] == {}
