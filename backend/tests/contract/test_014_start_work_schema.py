"""014 T033: the ``start_work`` input increment and the two mutually exclusive forms.

FR-024/SC-009 and contracts/field-order-contract.md §3/§5:

* the 012 six properties are byte-identical (canonical JSON — the 012 artifact is
  written compactly and 014 pretty-printed, so re-indentation is not a change) and
  ``required`` is unchanged; ``include_working_set`` is the only addition and
  defaults to ``false``;
* the output has exactly two mutually exclusive shapes: legacy
  ``{"memories": [...]}`` and 014 ``{"memories": [...], "working_set": {...}}``;
* the top-level **runtime** order is
  ``[scope, domain_brief, digest, working_set, read_guidance, counts,
  package_fingerprint, request_id]`` for both switch values.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.services.memory_reader import MemoryReader, READ_GUIDANCE
from rag_mcp.services.scope_resolver import MemoryScopeResolver
from tests.contract import schema_registry_014 as reg

START_WORK = "mcp-start-work.input.schema.json"
LEGACY_012_PROPERTIES = ("scope_ref", "session_id", "task_hint", "agent_id", "include", "budget")
NEW_START_WORK_KEY = "include_working_set"
RUNTIME_TOP_LEVEL_ORDER = ["scope", "domain_brief", "digest", "working_set", "read_guidance",
                           "counts", "package_fingerprint", "request_id"]
LEGACY_WORKING_SET_KEYS = ["memories"]
EXPERIMENTAL_WORKING_SET_KEYS = ["memories", "working_set"]
WORKING_SET_SUBKEYS = ["open_items", "recent_activity", "procedural", "decisions", "truncated",
                       "session_resolved"]


@pytest.fixture(autouse=True)
def _enable_the_014_deployment_switch(monkeypatch):
    """T086: the tool surface only exposes the new form while the switch is on."""
    monkeypatch.setenv("MEMORY_AWARE_RETRIEVAL_ENABLED", "true")


# --- input contract -----------------------------------------------------------


def test_012_six_properties_are_unchanged():
    reg.assert_legacy_property_json_identical(
        legacy_dir=reg.CONTRACTS_012,
        legacy_name=START_WORK,
        new_name=START_WORK,
        properties=LEGACY_012_PROPERTIES,
    )


def test_012_required_is_unchanged():
    legacy = reg.load(START_WORK, reg.CONTRACTS_012)
    current = reg.load(START_WORK)
    assert legacy["required"] == current["required"] == ["scope_ref"]
    assert legacy["additionalProperties"] == current["additionalProperties"] is False


def test_start_work_only_adds_the_explicit_switch():
    reg.assert_legacy_subset_with_only_new_keys(
        legacy_schema=reg.load(START_WORK, reg.CONTRACTS_012),
        new_schema=reg.load(START_WORK),
        expected_new_keys={NEW_START_WORK_KEY},
        name="start_work input",
    )


def test_the_switch_defaults_to_false():
    schema = reg.load(START_WORK)
    assert schema["properties"][NEW_START_WORK_KEY]["type"] == "boolean"
    assert schema["properties"][NEW_START_WORK_KEY]["default"] is False
    assert NEW_START_WORK_KEY not in schema["required"]


def test_runtime_argument_model_appends_only_the_switch():
    server = _server()
    tool = server._tool_manager.get_tool("start_work")
    properties = list(tool.fn_metadata.arg_model.model_json_schema(by_alias=True)["properties"])
    legacy_order = [name for name in properties if name in LEGACY_012_PROPERTIES]
    assert legacy_order == list(LEGACY_012_PROPERTIES)
    assert set(properties) - set(LEGACY_012_PROPERTIES) == {NEW_START_WORK_KEY}
    assert properties[-1] == NEW_START_WORK_KEY
    model = tool.fn_metadata.arg_model
    assert model.model_fields[NEW_START_WORK_KEY].default is False
    # StrictBool: a string must never be coerced into the switch.
    with pytest.raises(Exception):  # noqa: PT011 - pydantic's ValidationError
        model.model_validate({"scope_ref": "1", NEW_START_WORK_KEY: "true"})


def test_the_switch_is_explicit_and_never_inferred_from_other_arguments():
    """session_id/agent_id/budget must not act as implicit switches (§4.2)."""
    schema = reg.load(START_WORK)
    for key in ("session_id", "agent_id", "budget", "task_hint"):
        assert "switch" not in schema["properties"][key].get("description", "").lower()


# --- runtime order and the two shapes ----------------------------------------


def _server(session=None):
    server = FastMCP("start-work-014")
    from rag_mcp.mcp.start_work import register_start_work_tool

    holder = session or _Session()
    register_start_work_tool(server, lambda: _context(holder), None, None)
    return server


import contextlib  # noqa: E402


@contextlib.asynccontextmanager
async def _context(session):
    yield session


class _Session:
    def __init__(self):
        self.audits = []

    async def get(self, model, key):
        if model is KnowledgeScope:
            return SimpleNamespace(slug="scope", domain_key="generic")
        if model is DomainProfile:
            return SimpleNamespace(description="", memory_policy={})
        return None

    async def commit(self):
        return None

    def add(self, row):
        self.audits.append(row)


def _rows():
    return {
        1: {
            "memory_id": 1, "knowledge_scope_id": 7, "kind": "episodic", "provenance": "soft",
            "confidence": 0.8, "title": None, "content_text": "an open episodic memory",
            "evidence_refs": [], "retention_stage": "active",
            "inference_meta": {"source": "s", "confidence": 0.8, "model_version": "none",
                               "time": "2026-10-09T00:00:00+00:00", "supporting_evidence": []},
            "valid_from": None, "valid_to": None, "observed_at": "2026-10-09T10:00:00+00:00",
            "session_id": None, "agent_id": None, "status": "active", "superseded_by": None,
            "write_status": "complete", "expires_at": None,
        },
        2: {
            "memory_id": 2, "knowledge_scope_id": 7, "kind": "procedural", "provenance": "soft",
            "confidence": 0.7, "title": None, "content_text": "a procedural habit",
            "evidence_refs": [], "retention_stage": "active",
            "inference_meta": {"source": "s", "confidence": 0.7, "model_version": "none",
                               "time": "2026-10-09T00:00:00+00:00", "supporting_evidence": []},
            "valid_from": None, "valid_to": None, "observed_at": "2026-10-09T09:00:00+00:00",
            "session_id": None, "agent_id": None, "status": "active", "superseded_by": None,
            "write_status": "complete", "expires_at": None,
        },
    }


def _install(monkeypatch):
    async def resolve(self, reference):
        return 7

    async def views(self, *args, **kwargs):
        return _rows(), {}, [], []

    monkeypatch.setattr(MemoryScopeResolver, "resolve", resolve)
    monkeypatch.setattr(MemoryReader, "_views", views)


@pytest.mark.parametrize("include_working_set", [False, True])
def test_top_level_runtime_order_is_frozen_for_both_switch_values(monkeypatch, include_working_set):
    _install(monkeypatch)
    server = _server()
    result = asyncio.run(server.call_tool("start_work", {
        "scope_ref": "7", "include_working_set": include_working_set,
    }))
    body = result.structuredContent
    assert list(body) == RUNTIME_TOP_LEVEL_ORDER
    assert result.content[0].text.index('"scope"') < result.content[0].text.index('"domain_brief"')
    assert body["read_guidance"] == READ_GUIDANCE


def test_legacy_form_has_no_working_set_subkey(monkeypatch):
    _install(monkeypatch)
    server = _server()
    result = asyncio.run(server.call_tool("start_work", {"scope_ref": "7"}))
    body = result.structuredContent
    assert list(body["working_set"]) == LEGACY_WORKING_SET_KEYS


def test_legacy_form_is_selected_by_default(monkeypatch):
    _install(monkeypatch)
    server = _server()
    result = asyncio.run(server.call_tool("start_work", {"scope_ref": "7"}))
    assert list(result.structuredContent["working_set"]) == LEGACY_WORKING_SET_KEYS


def test_experimental_form_adds_the_working_set_subkey_with_six_keys(monkeypatch):
    _install(monkeypatch)
    server = _server()
    result = asyncio.run(server.call_tool("start_work", {
        "scope_ref": "7", "include_working_set": True,
    }))
    body = result.structuredContent
    assert list(body["working_set"]) == EXPERIMENTAL_WORKING_SET_KEYS
    assert list(body["working_set"]["working_set"]) == WORKING_SET_SUBKEYS


def test_the_two_forms_are_mutually_exclusive(monkeypatch):
    _install(monkeypatch)
    server = _server()
    legacy = asyncio.run(server.call_tool("start_work", {"scope_ref": "7"})).structuredContent
    experimental = asyncio.run(server.call_tool("start_work", {
        "scope_ref": "7", "include_working_set": True,
    })).structuredContent
    assert ("working_set" in legacy["working_set"]) is False
    assert ("working_set" in experimental["working_set"]) is True
    # the legacy body is a strict subset of the experimental one for the envelope
    assert list(legacy) == list(experimental) == RUNTIME_TOP_LEVEL_ORDER


def test_the_experimental_buckets_are_deterministic_and_do_not_leak_scope(monkeypatch):
    _install(monkeypatch)
    server = _server()
    arguments = {"scope_ref": "7", "include_working_set": True}
    first = asyncio.run(server.call_tool("start_work", arguments)).structuredContent
    second = asyncio.run(server.call_tool("start_work", arguments)).structuredContent

    def without_request_id(body):
        return {key: value for key, value in body.items() if key != "request_id"}

    # package_fingerprint is part of the body, so identical inputs must give
    # identical bytes.
    assert without_request_id(first) == without_request_id(second)

    derived = first["working_set"]["working_set"]
    assert [item["memory_id"] for item in derived["open_items"]] == [1]
    assert [item["memory_id"] for item in derived["procedural"]] == [2]
    assert derived["recent_activity"] == []
    assert derived["session_resolved"] is None
    for bucket in ("open_items", "recent_activity", "procedural"):
        for item in derived[bucket]:
            assert "knowledge_scope_id" not in item


def test_output_schema_declares_both_forms_and_the_subkey_is_optional():
    document = reg.load("mcp-start-work.output.schema.json")
    working_set = document["properties"]["working_set"]
    assert set(working_set["properties"]) == {"memories", "working_set"}
    assert working_set.get("required") in (None, [])
    assert working_set["additionalProperties"] is False


def test_014_start_work_output_validates_both_forms():
    validator = reg.validator("mcp-start-work.output.schema.json")
    baseline = {
        "scope": {}, "domain_brief": {}, "digest": {"memories": []},
        "working_set": {"memories": []}, "read_guidance": "Verify anchors.",
        "counts": {"returned": 0}, "package_fingerprint": "0" * 64, "request_id": "r",
    }
    assert not list(validator.iter_errors(baseline))
    experimental = {**baseline, "working_set": {
        "memories": [],
        "working_set": {"open_items": [], "recent_activity": [], "procedural": [],
                        "decisions": [], "truncated": False, "session_resolved": None},
    }}
    assert not list(validator.iter_errors(experimental))


def test_the_deployment_switch_gates_the_experimental_form(monkeypatch):
    """T086/FR-035: while the 014 switch is off the tool surface stays legacy."""
    _install(monkeypatch)
    monkeypatch.setenv("MEMORY_AWARE_RETRIEVAL_ENABLED", "false")
    server = _server()
    result = asyncio.run(server.call_tool("start_work", {
        "scope_ref": "7", "include_working_set": True,
    }))
    assert list(result.structuredContent["working_set"]) == LEGACY_WORKING_SET_KEYS
