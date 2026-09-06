"""Contract test for the 009 SourcePosition description (T021).

FR-012/FR-014: SourcePosition description is the full locator-prefix table
(aligned with 008 locator-prefixes.md), type: string is unchanged, and no new
pattern constraint is introduced (Constitution VII).
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

_CONTRACTS = (
    Path(__file__).resolve().parents[3] / "specs" / "009-domain-neutral-retrieval" / "contracts"
)


def _load(name: str) -> dict:
    with open(_CONTRACTS / name, encoding="utf-8") as f:
        return json.load(f)


def _source_position() -> dict:
    return _load("common.schema.json")["definitions"]["SourcePosition"]


def test_source_position_type_is_string():
    assert _source_position()["type"] == "string"


def test_source_position_has_no_pattern():
    assert "pattern" not in _source_position()


def test_source_position_has_locator_prefix_table():
    desc = _source_position()["description"]
    for token in ("# 标题路径", "page:N", "符号路径", "sheet:", "path:", "msg:"):
        assert token in desc, f"missing locator prefix token {token!r}"


def test_source_position_is_not_a_java_singleton():
    desc = _source_position()["description"]
    # The old 007 singleton phrasing is gone; the description is the full table.
    assert "Markdown 为章节路径" not in desc
    assert "Java 为全限定符号路径" not in desc


def test_common_schema_is_valid_json_schema():
    Draft202012Validator.check_schema(_load("common.schema.json"))
