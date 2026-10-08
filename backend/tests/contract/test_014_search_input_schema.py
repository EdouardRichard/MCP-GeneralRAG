"""014 contract wiring: the local registry resolves every 014 schema (T009).

T009 only wires the contracts into the suite; T011 adds the byte-level
``search_knowledge`` input assertions and T033 the ``start_work`` ones. Everything
here is registry/schema level so it runs without a database or any service.
"""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from rag_mcp.mcp import create_mcp_server
from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider
from tests.contract import schema_registry_014 as reg


class _OfflineQdrant:
    _client = None


def _server():
    """The real FastMCP registration; no database or vector service is touched."""
    return create_mcp_server(
        session_factory=lambda: None,
        qdrant_store=_OfflineQdrant(),
        embedding_provider=LocalCPUEmbeddingProvider(),
        mode="writer",
    )

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


# --- T011: legacy property bytes, envelope and the two new signals -------------

LEGACY_009_PROPERTIES = ("query", "project_scope", "domain_scope", "task_context", "top_k")
NEW_SEARCH_SIGNALS = {"session_id", "memory_context"}


def test_legacy_009_property_json_is_byte_identical():
    reg.assert_legacy_property_bytes_unchanged(
        legacy_dir=reg.CONTRACTS_009,
        legacy_name="mcp-search-input.schema.json",
        new_name="mcp-search-input.schema.json",
        properties=LEGACY_009_PROPERTIES,
    )


def test_legacy_required_anyof_and_closedness_unchanged():
    legacy = reg.load("mcp-search-input.schema.json", reg.CONTRACTS_009)
    current = reg.load("mcp-search-input.schema.json")
    reg.assert_legacy_envelope_unchanged(
        legacy_schema=legacy, new_schema=current, name="search input"
    )


def test_014_search_input_only_adds_the_two_signals():
    reg.assert_legacy_subset_with_only_new_keys(
        legacy_schema=reg.load("mcp-search-input.schema.json", reg.CONTRACTS_009),
        new_schema=reg.load("mcp-search-input.schema.json"),
        expected_new_keys=NEW_SEARCH_SIGNALS,
        name="search input",
    )


def test_runtime_tool_input_schema_appends_only_the_two_signals():
    """The runtime signature is what clients see; its measured legacy order is frozen.

    Measured at the 014 baseline, FastMCP emits the runtime properties in
    *signature* order ``query, project_scope, domain_scope, top_k, task_context``,
    which differs from the 009 schema document order (``top_k`` is declared last
    there). Both orders are frozen: the document order by
    ``test_legacy_009_property_json_is_byte_identical`` and the runtime order here.
    """
    runtime_legacy_order = ("query", "project_scope", "domain_scope", "top_k", "task_context")
    server = _server()
    tool = server._tool_manager.get_tool("search_knowledge")
    schema = tool.fn_metadata.arg_model.model_json_schema(by_alias=True)
    properties = list(schema["properties"])
    legacy_order = [name for name in properties if name in runtime_legacy_order]
    assert legacy_order == list(runtime_legacy_order)
    assert set(properties) - set(runtime_legacy_order) == NEW_SEARCH_SIGNALS
    assert properties[-len(NEW_SEARCH_SIGNALS):] == ["session_id", "memory_context"]
    required = schema["required"]
    assert required == ["query"], "the new signals must stay optional"
    for signal in NEW_SEARCH_SIGNALS:
        assert signal not in required


def test_runtime_tool_must_not_forbid_extra_fields():
    """FR-001/§4.4: applying close_input_schema here would be a real break."""
    server = _server()
    tool = server._tool_manager.get_tool("search_knowledge")
    assert tool.parameters.get("additionalProperties", None) is not False, (
        "search_knowledge must not gain additionalProperties:false"
    )
    model = tool.fn_metadata.arg_model
    validated = model.model_validate({"query": "q", "project_scope": ["p"], "typo_field": 1})
    assert "typo_field" not in validated.model_dump(), "unknown fields stay silently ignored"


def test_legacy_search_input_still_rejects_an_empty_scope_at_schema_level():
    validator = reg.validator("mcp-search-input.schema.json")
    assert list(validator.iter_errors({"query": "q", "project_scope": []}))
    assert not list(validator.iter_errors({"query": "q", "domain_scope": ["public:x"]}))

