"""MCP acceptance test for list_knowledge_domains (007, T053).

FR-014/FR-015/SC-004/SC-006 + T046: exercise the tool through the FastMCP
entry layer (registration + call_tool), validate the ACTUAL response against
list-domains.output.schema.json, assert active-only filtering (archived/deleting
excluded) and metadata-only shape. This closes the gap left by T029 (schema-file
contract) and T044 (core-function metadata check) — neither went through the MCP
tool layer with the declared output schema.

The test database is shared across runs, so assertions are data-independent:
they pin the test's own freshly-created scope IDs rather than assuming an empty
or fixed global domain set. The empty-instance edge ({domains: []}) is covered by
the list-domains.output.schema.json contract sample (T029).
"""
from __future__ import annotations

import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from rag_mcp.mcp.list_knowledge_domains import register_list_knowledge_domains_tool
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.utils.snowflake import generate_id

_CONTRACTS = Path(__file__).resolve().parents[3] / "specs/007-knowledge-domain-generalization/contracts"

_METADATA_KEYS = {"id", "slug", "name", "scope_type", "domain_key", "capabilities"}
_CAPABILITY_KEYS = {"supported_formats", "has_graph"}


def _merged_schema() -> dict:
    schema = copy.deepcopy(json.loads((_CONTRACTS / "list-domains.output.schema.json").read_text(encoding="utf-8")))
    common = json.loads((_CONTRACTS / "common.schema.json").read_text(encoding="utf-8"))
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


def _normalize(result) -> dict:
    """call_tool returns a tuple (content_blocks, structured_content) for a
    dict-returning tool; unwrap the JSON text of the first text content block."""
    if isinstance(result, dict):
        return result
    if isinstance(result, tuple):
        result = result[0]
    text = "".join(getattr(b, "text", "") for b in result if getattr(b, "type", None) == "text")
    return json.loads(text) if text.strip() else {}


def _mk_scope(session, scope_type="public", name=None, status="active"):
    sid = generate_id()
    session.add(KnowledgeScope(
        scope_id=sid, scope_type=scope_type, name=name or ("T-" + str(sid)),
        domain_key="se-project", slug="s-" + str(sid), status=status))
    return sid


@pytest.mark.asyncio
async def test_list_domains_registered_readonly():
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test-list-domains")
    register_list_knowledge_domains_tool(server, lambda: None)
    tools = await server.list_tools()
    tool = next(t for t in tools if t.name == "list_knowledge_domains")
    assert tool is not None
    ann = tool.annotations
    readonly = getattr(ann, "readOnlyHint", None) if ann is not None else None
    if isinstance(ann, dict):
        readonly = ann.get("readOnlyHint")
    assert readonly is True


@pytest.mark.asyncio
async def test_list_domains_active_only_and_schema_valid(db_session):
    from mcp.server.fastmcp import FastMCP

    active_public = _mk_scope(db_session, "public", "T053 Active Public")
    active_project = _mk_scope(db_session, "project", "T053 Active Project")
    archived = _mk_scope(db_session, "public", "T053 Archived", status="archived")
    deleting = _mk_scope(db_session, "project", "T053 Deleting", status="deleting")
    await db_session.commit()

    @asynccontextmanager
    async def sf():
        yield db_session

    server = FastMCP("test-list-domains")
    register_list_knowledge_domains_tool(server, sf)
    data = _normalize(await server.call_tool("list_knowledge_domains", {}))

    assert "domains" in data
    by_id = {d["id"]: d for d in data["domains"]}

    # active-only: this test's active scopes present, archived/deleting excluded
    assert str(active_public) in by_id
    assert str(active_project) in by_id
    assert str(archived) not in by_id
    assert str(deleting) not in by_id

    # SC-006: metadata-only shape, no knowledge content fields
    for d in data["domains"]:
        assert set(d.keys()) == _METADATA_KEYS
        assert set(d["capabilities"].keys()) == _CAPABILITY_KEYS

    # SC-004: the ACTUAL tool response validates against the declared schema
    Draft202012Validator(_merged_schema()).validate(data)


@pytest.mark.asyncio
async def test_list_domains_empty_instance_empty_success():
    """US3-AC3 / SC-006: no active domains -> {"domains": []} success (no error).

    Closes the T053 residual: the empty-instance edge was previously deferred to
    the T029 schema sample and never exercised through the MCP tool layer.
    """
    from mcp.server.fastmcp import FastMCP

    class _EmptyScalars:
        def all(self):
            return []

    class _EmptyResult:
        def scalars(self):
            return _EmptyScalars()

    class _EmptySession:
        async def execute(self, *args, **kwargs):
            return _EmptyResult()

    @asynccontextmanager
    async def sf():
        yield _EmptySession()

    server = FastMCP("test-list-domains-empty")
    register_list_knowledge_domains_tool(server, sf)
    data = _normalize(await server.call_tool("list_knowledge_domains", {}))

    assert data == {"domains": []}
