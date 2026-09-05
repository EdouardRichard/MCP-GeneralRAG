"""Contract test for list_knowledge_domains output (T029).

FR-014/FR-022/SC-006: the list output schema is valid, and the response
contains no knowledge content.
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


def _merged() -> dict:
    schema = copy.deepcopy(_load("list-domains.output.schema.json"))
    common = _load("common.schema.json")
    schema.setdefault("$defs", {})
    schema["$defs"].update(copy.deepcopy(common["definitions"]))
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

    _rewrite(schema)
    return schema


def test_list_domains_schema_valid():
    Draft202012Validator.check_schema(_load("list-domains.output.schema.json"))


def test_sample_domains_validate():
    v = Draft202012Validator(_merged())
    v.validate({"domains": []})
    v.validate({"domains": [{
        "id": "123", "slug": "regs", "name": "法规库", "scope_type": "public",
        "domain_key": "generic", "capabilities": {"supported_formats": ["markdown"], "has_graph": False},
    }]})


def test_no_knowledge_content_fields():
    """FR-022: the schema forbids knowledge-content fields."""
    schema = _load("list-domains.output.schema.json")
    item = schema["properties"]["domains"]["items"]
    assert "content" not in item["properties"]
    assert "chunk" not in item["properties"]
    assert "evidence" not in item["properties"]
    assert "excerpt" not in item["properties"]
