"""Contract test for the 009 task_context generalization (T017).

FR-009/FR-010/SC-006: task_context keeps the coding-domain convention fields
current_file/current_symbol/work_phase (field name + type + work_phase enum
byte-identical to 007), and adds an optional free-string activity field (any
knowledge domain). activity is optional, missing is fine, and it does not change
the legacy field shape.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

_CONTRACTS_009 = (
    Path(__file__).resolve().parents[3] / "specs" / "009-domain-neutral-retrieval" / "contracts"
)
_CONTRACTS_007 = (
    Path(__file__).resolve().parents[3] / "specs" / "007-knowledge-domain-generalization" / "contracts"
)


def _load(dir_: Path, name: str) -> dict:
    with open(dir_ / name, encoding="utf-8") as f:
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
    return Draft202012Validator(
        _merged(
            _load(_CONTRACTS_009, "mcp-search-input.schema.json"),
            _load(_CONTRACTS_009, "common.schema.json"),
        )
    )


def _task_context_props(schema: dict) -> dict:
    return schema["properties"]["task_context"]["properties"]


def test_activity_field_accepted():
    _search_validator().validate({
        "query": "q",
        "domain_scope": ["public:x"],
        "task_context": {"activity": "reviewing the contract"},
    })


def test_activity_is_optional_and_free_string():
    v = _search_validator()
    v.validate({"query": "q", "domain_scope": ["public:x"], "task_context": {"activity": "任意自由文本 123"}})
    # missing activity is fine (optional)
    v.validate({"query": "q", "domain_scope": ["public:x"], "task_context": {"current_file": "a.py"}})


def test_activity_has_max_length_4000():
    props = _task_context_props(_load(_CONTRACTS_009, "mcp-search-input.schema.json"))
    assert props["activity"]["type"] == "string"
    assert props["activity"]["maxLength"] == 4000


def test_legacy_fields_type_and_enum_byte_identical_to_007():
    s009 = _load(_CONTRACTS_009, "mcp-search-input.schema.json")
    s007 = _load(_CONTRACTS_007, "mcp-search-input.schema.json")
    tc009 = _task_context_props(s009)
    tc007 = _task_context_props(s007)
    for field in ("current_file", "current_symbol", "work_phase"):
        assert tc009[field]["type"] == tc007[field]["type"]
    # work_phase enum byte-identical (FR-009)
    assert tc009["work_phase"]["enum"] == tc007["work_phase"]["enum"]


def test_coding_domain_fields_annotated():
    props = _task_context_props(_load(_CONTRACTS_009, "mcp-search-input.schema.json"))
    for field in ("current_file", "current_symbol", "work_phase"):
        assert "编码域约定字段" in props[field]["description"]
        assert "向后兼容" in props[field]["description"]
