"""T041: contract tests for ``GET /api/memories/stats`` (FR-045, SC-016, SC-022).

The endpoint is driven through the real ASGI app over ``ASGITransport`` with a
real writer lease and the production session dependency (the same shape the
existing 012/015 suites use); nothing about the endpoint's own logic is stubbed.

Session discipline matters here: ``require_writer`` takes ``FOR UPDATE`` on the
lease row, so a request served from a long-lived test session keeps that lock for
the whole test and deadlocks ``writer_owner`` when it later updates the same rows.
Each request therefore gets its own short-lived session (exactly like
``conftest.test_client``), and seeding commits before any request is made.

Covered:

* the live response validates against ``memory-stats-response.schema.json``
  (Draft 2020-12; the schema uses no relative ``$ref``, checked here explicitly);
* negative controls: the schema rejects a payload carrying any of
  ``content`` / ``content_excerpt`` / ``title`` / ``evidence`` / ``query``;
* ``TRACE_BODY_ENABLED=true`` and ``false`` produce key-for-key identical
  responses apart from the timestamp -- turning body tracing on must not add a
  single body field to this endpoint (the 006 privacy guardrail);
* ``GET /runtime/metrics`` still satisfies the untouched 006 contract, and the
  006 contract declares none of the 015 key set, so this endpoint did not get
  merged into it.

This environment ships no ``rfc3339-validator``, so ``format: date-time`` is not
enforced by jsonschema; the timestamp is checked explicitly instead.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from jsonschema import Draft202012Validator, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_mcp.db import get_session
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.runtime import WriterLease
from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.utils.snowflake import generate_id
from tests.integration.memory_acceptance import writer_owner
from tests.memory_eval_datasets import CONTRACTS, load_schema

STATS_SCHEMA_NAME = "memory-stats-response.schema.json"
METRICS_SCHEMA_NAME = "runtime-metrics.schema.json"
COMMON_006_SCHEMA_NAME = "common.schema.json"
METRICS_CONTRACTS = CONTRACTS.parents[1] / "006-runtime-hardening" / "contracts"

#: The five free-text keys the contract must make impossible by construction.
FORBIDDEN_TEXT_KEYS = ("content", "content_excerpt", "title", "evidence", "query")

#: The exact ten root keys T007/T039 freeze.
CONTRACT_ROOT_KEYS = {
    "scope_id", "domain_key", "generated_at", "total", "kind_distribution",
    "provenance_distribution", "status_distribution", "salience_distribution",
    "consolidation_run_count", "rollback_count",
}


def _stats_validator() -> Draft202012Validator:
    schema = load_schema(STATS_SCHEMA_NAME)
    assert "$ref" not in json.dumps(schema), "the stats schema must not carry relative $refs"
    return Draft202012Validator(schema)


def _metrics_validator() -> Draft202012Validator:
    """The 006 contract, composed the way that contract itself is written."""
    schema = json.loads((METRICS_CONTRACTS / METRICS_SCHEMA_NAME).read_text(encoding="utf-8"))
    common = json.loads((METRICS_CONTRACTS / COMMON_006_SCHEMA_NAME).read_text(encoding="utf-8"))
    merged = dict(schema)
    merged["definitions"] = {**schema.get("definitions", {}), **common.get("definitions", {})}
    text = json.dumps(merged).replace(f"{COMMON_006_SCHEMA_NAME}#/definitions/", "#/definitions/")
    return Draft202012Validator(json.loads(text))


def _valid_stats_payload(**overrides) -> dict:
    payload = {
        "scope_id": "123456789",
        "domain_key": "generic",
        "generated_at": "2026-10-09T12:00:00+00:00",
        "total": 3,
        "kind_distribution": {"episodic": 1, "semantic": 1, "procedural": 1},
        "provenance_distribution": {"hard": 1, "soft": 1, "distilled": 1},
        "status_distribution": {"active": 2, "superseded": 1, "retired": 0, "quarantined": 0},
        "salience_distribution": {
            "p50": 0.2, "p90": 0.6, "p95": 0.8,
            "buckets": [{"lower": lower, "upper": upper, "count": 0}
                        for lower, upper in ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6),
                                             (0.6, 0.8), (0.8, 1.0), (1.0, None))],
        },
        "consolidation_run_count": 0,
        "rollback_count": 1,
    }
    payload.update(overrides)
    return payload


def _empty_domain_payload() -> dict:
    return _valid_stats_payload(
        total=0,
        kind_distribution={"episodic": 0, "semantic": 0, "procedural": 0},
        provenance_distribution={"hard": 0, "soft": 0, "distilled": 0},
        status_distribution={"active": 0, "superseded": 0, "retired": 0, "quarantined": 0},
        salience_distribution={
            "p50": None, "p90": None, "p95": None,
            "buckets": [{"lower": lower, "upper": upper, "count": 0}
                        for lower, upper in ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6),
                                             (0.6, 0.8), (0.8, 1.0), (1.0, None))],
        },
        consolidation_run_count=0, rollback_count=0)


@pytest.fixture
def app_under_test():
    """The real app, with its dependency overrides restored afterwards."""
    from rag_mcp.server import app

    original = dict(app.dependency_overrides)
    yield app
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


@pytest.fixture
def client_factory(engine, app_under_test):
    """A real ASGI client; every request gets its own short-lived session."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    created = []

    def build():
        async def sessions():
            async with factory() as session:
                yield session

        app_under_test.dependency_overrides[get_session] = sessions
        client = AsyncClient(transport=ASGITransport(app=app_under_test), base_url="http://test")
        created.append(client)
        return client

    yield build, app_under_test


async def _seed_domain(engine, *, content: str = "015 stats contract probe.", kind: str = "episodic",
                       provenance: str = "soft", scope_id: int | None = None) -> int:
    """Create (or extend) a scope with one committed memory; returns the scope id."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    sid = generate_id() if scope_id is None else scope_id
    async with factory() as session:
        if scope_id is None:
            session.add(KnowledgeScope(scope_id=sid, name=f"015 stats {uuid4()}",
                                       slug=f"c015-eval-stats-{sid}", scope_type="project",
                                       domain_key="generic"))
        await session.commit()
        service = MemoryService(session, embedding_provider=LocalCPUEmbeddingProvider())
        written = await service.record({
            "scope_id": sid, "kind": kind, "provenance": provenance, "content": content,
            "inference_meta": {"source": "015 T041", "confidence": 0.8, "model_version": "015.eval.1",
                               "time": datetime.now(UTC).isoformat(), "supporting_evidence": []},
        })
        await session.commit()
        assert written["memory_id"] is not None
    return sid


@asynccontextmanager
async def live_writer_lease(engine):
    """A verifiably active, unexpired writer lease.

    ``writer_owner`` refuses to enter write mode while another instance holds an
    unexpired lease (FR-002), and the 015 database is shared, so a concurrent run
    can legitimately hold it.  The endpoint only demands a *real* live lease, so
    when acquisition loses the race this adopts the live lease row for the test's
    app state -- read back from the database, not fabricated, and still verified
    by the production ``require_writer`` query on every request.
    """
    try:
        async with writer_owner(engine) as owner:
            yield owner
        return
    except AssertionError:
        pass

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        row = (await session.execute(
            select(WriterLease.lease_id, WriterLease.holder_instance_id)
            .where(WriterLease.state == "active", WriterLease.expires_at > func.now())
            .order_by(WriterLease.lease_id.desc()).limit(1))).first()
        await session.rollback()
    assert row is not None, "neither this run nor any concurrent run holds a live writer lease"
    yield SimpleNamespace(lease_id=row[0], holder_instance_id=row[1])


# --------------------------------------------------------------------------- #
# positive: the live response validates against its own schema
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_live_stats_response_satisfies_its_schema(engine, client_factory):
    build, app = client_factory
    sid = await _seed_domain(engine)
    client = build()
    async with live_writer_lease(engine) as lease:
        app.state.writer_lease = lease
        try:
            async with client:
                response = await client.get("/api/memories/stats", params={"scope_ref": str(sid)})
        finally:
            app.state.writer_lease = None

    assert response.status_code == 200, response.text
    body = response.json()
    _stats_validator().validate(body)
    assert set(body) == CONTRACT_ROOT_KEYS
    assert body["scope_id"] == str(sid)
    assert body["domain_key"] == "generic"
    assert body["total"] == 1
    assert body["kind_distribution"] == {"episodic": 1, "semantic": 0, "procedural": 0}
    assert body["provenance_distribution"] == {"hard": 0, "soft": 1, "distilled": 0}
    assert body["status_distribution"] == {"active": 1, "superseded": 0, "retired": 0, "quarantined": 0}
    assert body["rollback_count"] == 0 and body["consolidation_run_count"] == 0
    assert sum(bucket["count"] for bucket in body["salience_distribution"]["buckets"]) == body["total"]
    # No rfc3339-validator in this environment, so the timestamp is checked here.
    parsed = datetime.fromisoformat(body["generated_at"])
    assert parsed.tzinfo is not None
    assert abs((datetime.now(UTC) - parsed).total_seconds()) < 300


@pytest.mark.asyncio
async def test_stats_total_matches_browse_and_follows_real_writes(engine, client_factory):
    build, app = client_factory
    sid = await _seed_domain(engine)
    client = build()
    async with live_writer_lease(engine) as lease:
        app.state.writer_lease = lease
        try:
            async with client:
                first = (await client.get("/api/memories/stats", params={"scope_ref": str(sid)})).json()
                # A second real write in the same domain: hard provenance would need
                # a published evidence anchor, which is a different suite's subject.
                await _seed_domain(engine, content="015 stats contract probe two.",
                                   kind="semantic", scope_id=sid)
                grown = (await client.get("/api/memories/stats", params={"scope_ref": str(sid)})).json()
                browse = (await client.get("/api/memories", params={"scope_ref": str(sid)})).json()
        finally:
            app.state.writer_lease = None

    assert first["total"] == 1
    assert grown["total"] == 2
    assert grown["kind_distribution"] == {"episodic": 1, "semantic": 1, "procedural": 0}
    assert browse["total"] == grown["total"]


@pytest.mark.asyncio
async def test_zero_body_by_construction_on_the_live_response(engine, client_factory):
    build, app = client_factory
    sid = await _seed_domain(engine, content="015 SECRET BODY MARKER must not appear.")
    client = build()
    async with live_writer_lease(engine) as lease:
        app.state.writer_lease = lease
        try:
            async with client:
                response = await client.get("/api/memories/stats", params={"scope_ref": str(sid)})
        finally:
            app.state.writer_lease = None

    assert response.status_code == 200, response.text
    body = response.json()

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in FORBIDDEN_TEXT_KEYS, f"free-text key {key!r} at {path}"
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(body)
    assert "SECRET BODY MARKER" not in response.text
    assert set(body) == CONTRACT_ROOT_KEYS


@pytest.mark.asyncio
async def test_missing_scope_ref_is_rejected_and_unknown_scope_is_refused(engine, client_factory):
    build, app = client_factory
    client = build()
    async with live_writer_lease(engine) as lease:
        app.state.writer_lease = lease
        try:
            async with client:
                missing = await client.get("/api/memories/stats")
                unknown = await client.get("/api/memories/stats", params={"scope_ref": "no-such-domain-015"})
        finally:
            app.state.writer_lease = None

    assert missing.status_code == 422, missing.text
    assert unknown.status_code == 400, unknown.text
    assert unknown.json()["detail"]["code"] in {"MISSING_KNOWLEDGE_SCOPE", "AMBIGUOUS_DOMAIN_REF"}


# --------------------------------------------------------------------------- #
# negative controls: the schema is load-bearing for the privacy guardrail
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("free_text_key", FORBIDDEN_TEXT_KEYS)
def test_schema_rejects_a_payload_carrying_a_free_text_key(free_text_key):
    validator = _stats_validator()
    validator.validate(_valid_stats_payload())
    with pytest.raises(ValidationError):
        validator.validate(_valid_stats_payload(**{free_text_key: "leaked"}))


@pytest.mark.parametrize("nested", ["salience_distribution", "kind_distribution"])
def test_schema_rejects_a_free_text_key_nested_in_a_distribution(nested):
    """``additionalProperties: false`` holds at every level, not only at the root."""
    validator = _stats_validator()
    payload = _valid_stats_payload()
    payload[nested] = {**payload[nested], "content": "leaked"}
    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_schema_rejects_a_missing_contract_block_and_a_negative_count():
    validator = _stats_validator()
    incomplete = _valid_stats_payload()
    del incomplete["consolidation_run_count"]
    with pytest.raises(ValidationError):
        validator.validate(incomplete)
    with pytest.raises(ValidationError):
        validator.validate(_valid_stats_payload(total=-1))
    # An empty domain is a real zero with null quantiles, and that must validate.
    validator.validate(_empty_domain_payload())


def test_schema_rejects_a_root_key_outside_the_frozen_ten():
    validator = _stats_validator()
    with pytest.raises(ValidationError):
        validator.validate(_valid_stats_payload(**{"domain_stats": {}}))


# --------------------------------------------------------------------------- #
# the privacy guardrail: TRACE_BODY_ENABLED must not change a single key
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_trace_body_switch_does_not_change_the_response(monkeypatch, engine, client_factory):
    build, app = client_factory
    sid = await _seed_domain(engine, content="015 TRACE BODY MARKER must not appear.")
    client = build()
    responses = {}
    async with live_writer_lease(engine) as lease:
        app.state.writer_lease = lease
        try:
            async with client:
                for enabled in ("true", "false"):
                    monkeypatch.setenv("TRACE_BODY_ENABLED", enabled)
                    responses[enabled] = await client.get(
                        "/api/memories/stats", params={"scope_ref": str(sid)})
        finally:
            app.state.writer_lease = None

    assert responses["true"].status_code == 200, responses["true"].text
    assert responses["false"].status_code == 200, responses["false"].text

    def keys(node, path=""):
        found = []
        if isinstance(node, dict):
            for key, value in node.items():
                found.append(f"{path}/{key}")
                found.extend(keys(value, f"{path}/{key}"))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                found.extend(keys(value, f"{path}[{index}]"))
        return found

    on, off = responses["true"].json(), responses["false"].json()
    assert keys(on) == keys(off), "TRACE_BODY_ENABLED changed the key set of the stats endpoint"
    stripped = [{key: value for key, value in body.items() if key != "generated_at"} for body in (on, off)]
    assert json.dumps(stripped[0], sort_keys=True) == json.dumps(stripped[1], sort_keys=True)
    assert "TRACE BODY MARKER" not in responses["true"].text
    assert "TRACE BODY MARKER" not in responses["false"].text
    assert set(on) == CONTRACT_ROOT_KEYS


# --------------------------------------------------------------------------- #
# regression: the 006 contract and its endpoint are untouched
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_runtime_metrics_still_matches_the_untouched_006_contract(engine, client_factory):
    build, app = client_factory
    client = build()
    async with live_writer_lease(engine) as lease:
        app.state.writer_lease = lease
        try:
            async with client:
                metrics = await client.get("/runtime/metrics")
        finally:
            app.state.writer_lease = None

    assert metrics.status_code == 200, metrics.text
    body = metrics.json()
    _metrics_validator().validate(body)
    assert set(body) == {
        "generated_at", "window", "request_totals", "completion_status_distribution",
        "latency", "subpath_timings_ms", "provider_usage", "ttl_purge", "active_instances",
    }
    assert set(body["provider_usage"]) == {
        "embedding_calls", "rerank_calls", "llm_calls", "llm_prompt_chars", "llm_completion_chars",
    }
    # The statistics endpoint must not have been folded into this readout: none of
    # the 015-only keys may appear.  `generated_at`/`scope_id` are shared by both
    # contracts, so only the 015-specific vocabulary is asserted here.
    for key in ("kind_distribution", "provenance_distribution", "status_distribution",
                "salience_distribution", "rollback_count", "consolidation_run_count"):
        assert key not in body


def _declared_property_keys(schema: dict) -> set[str]:
    """Every property name the schema itself declares, at any depth."""
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                found.update(properties)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return found


def test_the_006_contract_files_never_describe_the_statistics_block():
    """A pin on the contract this endpoint is forbidden to touch (SC-022).

    ``git status --porcelain specs/006-*`` is empty and no 006 file is in
    ``git diff --stat``; this test adds the structural half so a future edit that
    tried to fold the 015 readout into the 006 contract fails here as well.  The
    comparison is on declared property *names*, not raw substrings -- the 006
    contract legitimately declares ``completion_status_distribution``, which a
    naive substring search would flag as 015's ``status_distribution``.
    """
    metrics_keys = _declared_property_keys(
        json.loads((METRICS_CONTRACTS / METRICS_SCHEMA_NAME).read_text(encoding="utf-8")))
    assert "completion_status_distribution" in metrics_keys, (
        "the pin must be non-vacuous: the neighbouring 006 key must be found")
    for name in (METRICS_SCHEMA_NAME, COMMON_006_SCHEMA_NAME):
        declared = _declared_property_keys(
            json.loads((METRICS_CONTRACTS / name).read_text(encoding="utf-8")))
        for key in ("kind_distribution", "salience_distribution", "provenance_distribution",
                    "status_distribution", "rollback_count", "consolidation_run_count"):
            assert key not in declared, f"{name} must not declare the 015 statistics key {key!r}"
