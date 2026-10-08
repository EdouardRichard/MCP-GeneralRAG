"""Local 014 contract registry and reusable cross-artifact assertions (T003).

This module is the single place that knows how to

* load the 014 contract schemas and resolve their **sibling** ``$ref``s
  (``common.schema.json#/definitions/...``, ``memory-attachment.schema.json``),
* prove that a legacy property block is **byte-identical** to its 009/007 original,
* prove that a 014 schema only **adds** the expected keys on top of the legacy set,
* prove **bidirectional** non-mixing between ``evidence[]`` items and
  ``related_memories[]`` attachment items, and
* prove that the attachment vocabulary does not drift from 012 ``memory-entry``.

Every helper raises ``AssertionError`` with the offending path/value so a failing
contract test reports the drift rather than just ``False is not True``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_ROOT = REPO_ROOT / "specs"

CONTRACTS_014 = SPEC_ROOT / "014-memory-aware-retrieval" / "contracts"
CONTRACTS_009 = SPEC_ROOT / "009-domain-neutral-retrieval" / "contracts"
CONTRACTS_007 = SPEC_ROOT / "007-knowledge-domain-generalization" / "contracts"
CONTRACTS_012 = SPEC_ROOT / "012-memory-foundation-write-read-loop" / "contracts"

#: 014 schemas that declare an absolute ``$id`` and may be referenced by siblings.
REGISTERED_014 = (
    "common.schema.json",
    "mcp-search-input.schema.json",
    "mcp-search-output.schema.json",
    "memory-attachment.schema.json",
    "mcp-start-work.input.schema.json",
    "mcp-start-work.output.schema.json",
    "working-set-item.schema.json",
)


def load(name: str, directory: Path = CONTRACTS_014) -> dict:
    """Load one contract schema (or JSON document) from ``directory``."""
    with open(directory / name, encoding="utf-8") as handle:
        return json.load(handle)


def raw_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- registry -----------------------------------------------------------------


def build_registry() -> Registry:
    """Register every 014 ``$id`` (plus the 009/007 originals they inherit)."""
    registry = Registry()
    for name in REGISTERED_014:
        document = load(name)
        registry = registry.with_resource(document["$id"], Resource.from_contents(document))
    for directory in (CONTRACTS_009, CONTRACTS_007):
        for path in sorted(directory.glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            identifier = document.get("$id")
            if identifier:
                registry = registry.with_resource(identifier, Resource.from_contents(document))
    return registry


def validator(name: str, *, pointer: str | None = None) -> Draft202012Validator:
    """A Draft202012 validator for a 014 schema, with sibling ``$ref`` resolved.

    ``pointer`` selects a sub-schema (e.g. ``/properties/evidence/items``) while
    keeping the document's base URI so its relative ``$ref``s still resolve.
    """
    document = load(name)
    schema = document
    if pointer:
        for token in pointer.strip("/").split("/"):
            schema = schema[token.replace("~1", "/").replace("~0", "~")]
    return Draft202012Validator(schema, registry=build_registry())


def is_valid(name: str, instance: object, *, pointer: str | None = None) -> bool:
    return not list(validator(name, pointer=pointer).iter_errors(instance))


# --- raw byte extraction ------------------------------------------------------


def _skip_ws(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _scan_string(text: str, index: int) -> int:
    """Return the index just past the closing quote of the string at ``index``."""
    assert text[index] == '"', f"expected a string at {index}"
    index += 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == '"':
            return index + 1
        index += 1
    raise ValueError("unterminated string")


def _scan_value(text: str, index: int) -> int:
    """Return the index just past the JSON value starting at ``index``."""
    index = _skip_ws(text, index)
    char = text[index]
    if char == '"':
        return _scan_string(text, index)
    if char in "{[":
        closing = "}" if char == "{" else "]"
        depth = 0
        while index < len(text):
            char = text[index]
            if char == '"':
                index = _scan_string(text, index)
                continue
            if char in "{[":  # noqa: SIM114 - explicit depth tracking
                depth += 1
            elif char in "}]":
                depth -= 1
                if depth == 0:
                    return index + 1
            index += 1
        raise ValueError("unterminated container")
    while index < len(text) and text[index] not in ",}] \t\r\n":
        index += 1
    return index


def object_member_span(text: str, start: int, member: str) -> tuple[int, int, int]:
    """Locate ``member`` inside the object starting at ``start``.

    Returns ``(key_start, value_start, value_end)``. Raises ``KeyError`` when the
    object has no such member. Only top-level members of that object are
    considered, so a nested ``properties`` object can never be mistaken for the
    root one and a key mentioned inside a description string can never match.
    """
    assert text[start] == "{", f"expected an object at {start}"
    index = _skip_ws(text, start + 1)
    while index < len(text) and text[index] != "}":
        key_end = _scan_string(text, index)
        key = json.loads(text[index:key_end])
        cursor = _skip_ws(text, key_end)
        assert text[cursor] == ":", f"expected ':' after key {key!r}"
        value_start = _skip_ws(text, cursor + 1)
        value_end = _scan_value(text, value_start)
        if key == member:
            return index, value_start, value_end
        index = _skip_ws(text, value_end)
        if index < len(text) and text[index] == ",":
            index = _skip_ws(text, index + 1)
    raise KeyError(member)


def raw_property_text(path: Path, property_name: str) -> str:
    """Extract the exact source text of one top-level ``properties`` member.

    The comparison must be on the **bytes as written**, not on a re-serialized
    dict, so this structurally scans the file instead of parsing and re-dumping
    it. Raises ``KeyError`` when the property is absent.
    """
    text = raw_text(path)
    root_start = _skip_ws(text, 0)
    try:
        _, properties_start, properties_end = object_member_span(text, root_start, "properties")
    except KeyError as error:
        raise KeyError(f"{path.name}: no top-level properties object") from error
    try:
        _, value_start, value_end = object_member_span(text, properties_start, property_name)
    except KeyError as error:
        raise KeyError(f"{path.name}: property {property_name!r} not found") from error
    assert value_end <= properties_end
    return text[value_start:value_end]


# --- reusable assertions ------------------------------------------------------


def assert_legacy_property_bytes_unchanged(
    *,
    legacy_dir: Path,
    legacy_name: str,
    new_name: str,
    properties: tuple[str, ...],
    new_dir: Path = CONTRACTS_014,
) -> None:
    """Assert each legacy property's **source text** is byte-identical in 014."""
    legacy_path, new_path = legacy_dir / legacy_name, new_dir / new_name
    for property_name in properties:
        expected = raw_property_text(legacy_path, property_name)
        actual = raw_property_text(new_path, property_name)
        assert actual == expected, (
            f"{new_name}: property {property_name!r} is not byte-identical to "
            f"{legacy_name}\n--- legacy ---\n{expected}\n--- 014 ---\n{actual}"
        )


def property_json_text(path: Path, property_name: str) -> str:
    """The canonical JSON text of one property, independent of source formatting."""
    document = json.loads(raw_text(path))
    return json.dumps(document["properties"][property_name], ensure_ascii=False, sort_keys=False)


def assert_legacy_property_json_identical(
    *,
    legacy_dir: Path,
    legacy_name: str,
    new_name: str,
    properties: tuple[str, ...],
    new_dir: Path = CONTRACTS_014,
) -> None:
    """Assert each legacy property's canonical JSON is byte-identical in 014.

    Used where the legacy artifact is written in a different indentation style
    than the 014 contract (012 ``mcp-start-work.input.schema.json`` is compact,
    014 is pretty-printed). Re-indenting a property is not a contract change, but
    any change to a key, type, bound, enum, default or description is caught
    here byte-for-byte.
    """
    legacy_path, new_path = legacy_dir / legacy_name, new_dir / new_name
    for property_name in properties:
        expected = property_json_text(legacy_path, property_name)
        actual = property_json_text(new_path, property_name)
        assert actual == expected, (
            f"{new_name}: property {property_name!r} is not byte-identical (canonical JSON) to "
            f"{legacy_name}\n--- legacy ---\n{expected}\n--- 014 ---\n{actual}"
        )


def assert_legacy_envelope_unchanged(
    *,
    legacy_schema: dict,
    new_schema: dict,
    keys: tuple[str, ...] = ("required", "anyOf", "additionalProperties", "type"),
    name: str = "",
) -> None:
    """Assert declared envelope keywords (``required``/``anyOf``/...) are unchanged."""
    for key in keys:
        if key not in legacy_schema and key not in new_schema:
            continue
        assert legacy_schema.get(key) == new_schema.get(key), (
            f"{name}: {key!r} changed\nlegacy={legacy_schema.get(key)!r}\n014={new_schema.get(key)!r}"
        )


def assert_legacy_subset_with_only_new_keys(
    *,
    legacy_schema: dict,
    new_schema: dict,
    expected_new_keys: set[str],
    name: str = "",
) -> None:
    """Assert ``legacy ⊆ 014`` and the difference is exactly ``expected_new_keys``.

    Also asserts the legacy properties keep their **relative order** as a prefix
    of the 014 property order, because FastMCP derives ``inputSchema`` property
    order from the signature and clients observe it.
    """
    legacy_keys = list(legacy_schema["properties"])
    new_keys = list(new_schema["properties"])
    assert set(legacy_keys) <= set(new_keys), (
        f"{name}: 014 dropped legacy properties {sorted(set(legacy_keys) - set(new_keys))}"
    )
    assert set(new_keys) - set(legacy_keys) == set(expected_new_keys), (
        f"{name}: unexpected new properties {sorted(set(new_keys) - set(legacy_keys) - set(expected_new_keys))} / "
        f"missing expected {sorted(set(expected_new_keys) - (set(new_keys) - set(legacy_keys)))}"
    )
    assert new_keys[: len(legacy_keys)] == legacy_keys, (
        f"{name}: legacy property order changed\nlegacy={legacy_keys}\n014={new_keys[:len(legacy_keys)]}"
    )
    for key in legacy_keys:
        assert legacy_schema["properties"][key] == new_schema["properties"][key], (
            f"{name}: property {key!r} changed value"
        )


def sample_evidence_item() -> dict:
    """A minimal valid ``evidence[]`` item (007/009 vocabulary)."""
    return {
        "evidence_id": "e-1",
        "content_excerpt": "excerpt",
        "source_version": 1,
        "source_position": "doc.md#L1",
        "knowledge_scope_id": "1",
        "knowledge_scope_type": "project",
        "relevance_score": 0.9,
    }


def sample_attachment(*, provenance: str = "soft", **overrides) -> dict:
    """A minimal valid ``related_memories[]`` attachment item (014 vocabulary)."""
    attachment = {
        "memory_id": 7,
        "knowledge_scope_id": 1,
        "kind": "episodic",
        "provenance": provenance,
        "confidence": 0.8 if provenance != "hard" else None,
        "content_excerpt": "remembered excerpt",
        "truncated": False,
        "content_length": 18,
        "evidence_refs": [],
        "inference_meta": (
            None if provenance == "hard" else
            {"source": "consolidation", "confidence": 0.8, "model_version": "none",
             "time": "2026-10-09T00:00:00+00:00", "supporting_evidence": []}
        ),
        "valid_from": None,
        "valid_to": None,
        "observed_at": "2026-10-09T00:00:00+00:00",
        "session_id": None,
        "agent_id": None,
        "status": "active",
        "superseded_by": None,
        "injection_flags": {},
        "attach_reason": "session_recent",
        "match": {"dense_similarity": 0.7, "recency_rank": 1, "kind_rank": 1, "salience": None,
                  "fused_score": 0.01},
    }
    attachment.update(overrides)
    return attachment


EVIDENCE_ITEM_POINTER = "/properties/evidence/items"


def assert_bidirectional_non_mixing(
    *,
    evidence_schema_name: str = "mcp-search-output.schema.json",
    attachment_schema_name: str = "memory-attachment.schema.json",
) -> None:
    """Assert neither field accepts the other's item shape, in both directions.

    An attachment must be rejected as ``evidence[]`` and an evidence item must be
    rejected as an attachment. Both directions are schema-level
    (``additionalProperties: false`` plus disjoint required sets), so this holds
    independently of any runtime assembly bug.
    """
    evidence_validator = validator(evidence_schema_name, pointer=EVIDENCE_ITEM_POINTER)
    attachment_validator = validator(attachment_schema_name)

    attachment_errors = list(evidence_validator.iter_errors(sample_attachment()))
    assert attachment_errors, (
        "attachment item must NOT validate as an evidence[] item (FR-003 field separation)"
    )
    evidence_errors = list(attachment_validator.iter_errors(sample_evidence_item()))
    assert evidence_errors, (
        "evidence item must NOT validate as a related_memories[] attachment (FR-003 field separation)"
    )


# 012 ``memory-entry`` shared vocabulary. The comparison basis is the 012 schema
# itself (field names / types / enum lists) plus the runtime ``public_entry``
# shape, per data-model §7.1: ``inference_meta`` lives only in 012 ``$defs``.
MEMORY_ENTRY_FIELDS = (
    "memory_id", "knowledge_scope_id", "kind", "provenance", "title", "confidence",
    "content_excerpt", "truncated", "content_length", "evidence_refs", "valid_from",
    "valid_to", "observed_at", "session_id", "agent_id", "status", "superseded_by", "match",
)

#: 014-only keys that 012 has no equivalent for (must be justified, not accidental).
ATTACHMENT_ONLY_KEYS = {"inference_meta", "injection_flags", "attach_reason"}


def _json_type_names(schema: dict) -> set[str]:
    """Declared JSON types, inferred from ``enum`` when ``type`` is absent."""
    declared = schema.get("type")
    if declared is not None:
        return {declared} if isinstance(declared, str) else set(declared)
    enum = schema.get("enum")
    if enum:
        names = set()
        for value in enum:
            if isinstance(value, bool):
                names.add("boolean")
            elif isinstance(value, str):
                names.add("string")
            elif isinstance(value, int):
                names.add("integer")
            elif isinstance(value, float):
                names.add("number")
            elif value is None:
                names.add("null")
        return names
    return set()


#: Shared fields whose 014 constraint is deliberately narrower than 012, with the
#: documented reason. Anything else that narrows is drift and fails the assertion.
ATTACHMENT_DOCUMENTED_NARROWINGS: dict[str, str] = {
    "content_excerpt": "014 tightens the excerpt to 200 chars (012 is 300)",
    "valid_to": "attachment items are always open, so valid_to is pinned to null",
    "superseded_by": "attachment items are never superseded, so superseded_by is pinned to null",
    "status": 'only "active" entries reach the attachment layer',
}


def assert_attachment_vocabulary_matches_012() -> None:
    """Assert the attachment field vocabulary does not drift from 012 memory-entry.

    Every narrowing relative to 012 must appear in
    :data:`ATTACHMENT_DOCUMENTED_NARROWINGS`; a new narrowing, a widened enum, a
    changed type or a changed key set all fail with the offending field named.
    """
    attachment = load("memory-attachment.schema.json")
    entry = load("memory-entry.schema.json", CONTRACTS_012)
    properties = attachment["properties"]
    entry_properties = entry["properties"]

    assert set(properties) - set(entry_properties) == ATTACHMENT_ONLY_KEYS, (
        "014 attachment key set drifted: "
        f"extra={sorted(set(properties) - set(entry_properties) - ATTACHMENT_ONLY_KEYS)} "
        f"missing={sorted(set(entry_properties) - set(properties))}"
    )
    for field in MEMORY_ENTRY_FIELDS:
        assert field in properties, f"014 attachment dropped 012 field {field!r}"
        expected_types = _json_type_names(entry_properties[field])
        actual_types = _json_type_names(properties[field])
        if actual_types != expected_types:
            assert field in ATTACHMENT_DOCUMENTED_NARROWINGS, (
                f"014 attachment field {field!r} type drifted without a documented reason: "
                f"012={sorted(expected_types)} 014={sorted(actual_types)}"
            )
            assert actual_types < expected_types, (
                f"014 attachment field {field!r} changed type rather than narrowing: "
                f"012={sorted(expected_types)} 014={sorted(actual_types)}"
            )
        if "enum" in entry_properties[field]:
            actual_enum = set(properties[field].get("enum", ()))
            expected_enum = set(entry_properties[field]["enum"])
            if actual_enum != expected_enum:
                assert field in ATTACHMENT_DOCUMENTED_NARROWINGS, (
                    f"014 attachment field {field!r} changed its enum without a documented reason"
                )
            assert actual_enum <= expected_enum, (
                f"014 attachment field {field!r} widened the 012 enum: "
                f"{sorted(actual_enum - expected_enum)}"
            )
    assert properties["content_excerpt"]["maxLength"] == 200
    assert entry_properties["content_excerpt"]["maxLength"] == 300
    assert entry.get("$defs", {}).get("inferenceMeta"), "012 keeps inference_meta in $defs only"
    for field in ("source_position", "source_version", "relevance_score"):
        assert field not in properties, (
            f"attachment must not declare evidence locating field {field!r} (Constitution IV)"
        )


def deep_copy(value: dict) -> dict:
    return copy.deepcopy(value)
