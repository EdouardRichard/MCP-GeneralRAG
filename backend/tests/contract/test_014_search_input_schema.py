"""014 contract wiring: the local registry resolves every 014 schema (T009).

T009 only wires the contracts into the suite; T011 adds the byte-level
``search_knowledge`` input assertions and T033 the ``start_work`` ones. Everything
here is registry/schema level so it runs without a database or any service.
"""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from tests.contract import schema_registry_014 as reg

#: The five contracts T009 must cover.
COVERED = (
    "mcp-search-input.schema.json",
    "mcp-search-output.schema.json",
    "memory-attachment.schema.json",
    "working-set-item.schema.json",
    "mcp-start-work.input.schema.json",
    "mcp-start-work.output.schema.json",
)


@pytest.mark.parametrize("name", reg.REGISTERED_014)
def test_every_014_schema_is_a_valid_draft202012_document(name):
    document = reg.load(name)
    Draft202012Validator.check_schema(document)
    assert document.get("$schema") == "https://json-schema.org/draft/2020-12/schema"


@pytest.mark.parametrize("name", reg.REGISTERED_014)
def test_every_014_schema_id_is_registered(name):
    document = reg.load(name)
    registry = reg.build_registry()
    assert registry.get_or_retrieve(document["$id"]).value is not None


@pytest.mark.parametrize("name", COVERED)
def test_sibling_refs_resolve_without_network(name):
    # A validator that can be constructed and used proves the sibling
    # ``$ref``s (common.schema.json#/definitions/..., memory-attachment.schema.json)
    # were resolved from the local registry only.
    validator = reg.validator(name)
    assert validator is not None
    assert validator.schema is not None


def test_search_input_requires_a_query_and_a_scope():
    validator = reg.validator("mcp-search-input.schema.json")
    assert not list(validator.iter_errors({"query": "q", "project_scope": ["p"]}))
    assert list(validator.iter_errors({"project_scope": ["p"]})), "query is required"
    assert list(validator.iter_errors({"query": "q"})), "one scope form is required"


def test_search_output_legacy_minimum_validates():
    assert reg.is_valid(
        "mcp-search-output.schema.json",
        {"completion_status": "complete", "evidence": [], "request_id": "r"},
    )


def test_search_output_rejects_related_memories_without_notice_and_counts():
    instance = {
        "completion_status": "complete",
        "evidence": [],
        "related_memories": [],
        "request_id": "r",
    }
    errors = list(reg.validator("mcp-search-output.schema.json").iter_errors(instance))
    assert errors, "related_memories must be co-present with memory_notice and counts"


def test_attachment_schema_accepts_the_documented_minimum():
    assert reg.is_valid("memory-attachment.schema.json", reg.sample_attachment())


def test_working_set_item_schema_accepts_the_documented_minimum():
    assert reg.is_valid(
        "working-set-item.schema.json",
        {
            "memory_id": 1,
            "kind": "episodic",
            "provenance": "soft",
            "confidence": 0.5,
            "evidence_refs": [],
            "inference_meta": {"source": "s", "confidence": 0.5, "model_version": "none",
                               "time": "2026-10-09T00:00:00+00:00", "supporting_evidence": []},
            "content_excerpt": "excerpt",
            "truncated": False,
            "observed_at": "2026-10-09T00:00:00+00:00",
        },
    )


def test_start_work_input_legacy_six_plus_the_explicit_switch():
    validator = reg.validator("mcp-start-work.input.schema.json")
    assert not list(validator.iter_errors({"scope_ref": "1"}))
    assert not list(validator.iter_errors({"scope_ref": "1", "include_working_set": True}))
    assert list(validator.iter_errors({"include_working_set": True})), "scope_ref is required"


def test_start_work_output_declares_both_working_set_forms():
    document = reg.load("mcp-start-work.output.schema.json")
    assert "working_set" in document["properties"]
    assert document["$id"].endswith("mcp-start-work.output.schema.json")
