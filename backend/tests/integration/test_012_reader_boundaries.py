import pytest
import json
from types import SimpleNamespace

from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


def visible_characters(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


@pytest.mark.asyncio
async def test_complete_recall_and_work_bodies_include_envelope_text_in_budget(monkeypatch):
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    from rag_mcp.services.memory_reader import MemoryReader, public_entry
    from rag_mcp.services.scope_resolver import MemoryScopeResolver

    row = {"memory_id": 1, "knowledge_scope_id": 7, "kind": "procedural", "provenance": "soft",
           "content_text": "C" * 4000, "evidence_refs": [], "inference_meta": {"source": ""},
           "status": "active", "observed_at": "2020-01-01T00:00:00+00:00",
           "valid_from": "2020-01-01T00:00:00+00:00", "valid_to": None, "expires_at": None}
    row["inference_meta"]["source"] = "M" * (6000 - visible_characters(public_entry(row)))

    class Session:
        async def execute(self, *args):
            return None

        async def commit(self):
            return None

        def add(self, audit):
            return None

        async def get(self, model, key):
            if model is KnowledgeScope:
                return SimpleNamespace(slug="scope-" + "s" * 50, domain_key="custom-" + "k" * 40)
            return SimpleNamespace(description="D" * 4000, memory_policy={})

    async def resolve_many(self, reference):
        return [7]

    async def resolve(self, reference):
        return 7

    async def views(self, *args, **kwargs):
        return {index: {**row, "memory_id": index} for index in range(1, 21)}, {}, [], []

    monkeypatch.setattr(MemoryScopeResolver, "resolve_many", resolve_many)
    monkeypatch.setattr(MemoryScopeResolver, "resolve", resolve)
    monkeypatch.setattr(MemoryReader, "_views", views)
    reader = MemoryReader(Session(), None)
    result = await reader.recall(scope_ref=["7"])
    assert visible_characters(result) <= 6000
    assert result["counts"]["characters"] == visible_characters(result)
    row["inference_meta"] = None
    for budget, maximum in (("standard", 2000), ("compact", 800), ("minimal", 300)):
        result = await reader.start_work(scope_ref="7", budget=budget)
        body = {key: value for key, value in result.items() if key != "request_id"}
        assert visible_characters(body) <= maximum
        assert body["counts"]["characters"] == visible_characters(body)
        assert len(body["package_fingerprint"]) == 64
        assert body["read_guidance"]


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["valid_from", "valid_to", "expires_at"])
async def test_stable_package_omits_time_sensitive_entries_across_clock_boundaries(monkeypatch, boundary):
    from datetime import datetime, timedelta, timezone
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    import rag_mcp.services.memory_reader as module
    from rag_mcp.services.scope_resolver import MemoryScopeResolver

    pivot = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = {1: {"memory_id": 1, "knowledge_scope_id": 7, "kind": "episodic", "provenance": "soft",
                "content_text": "Temporally limited fact.", "status": "active", "evidence_refs": [], "inference_meta": None,
                "observed_at": (pivot - timedelta(days=1)).isoformat(),
                "valid_from": (pivot - timedelta(days=1)).isoformat(), "valid_to": None, "expires_at": None}}
    rows[1][boundary] = pivot.isoformat()
    rows[2] = {**rows[1], "memory_id": 2, "content_text": "Stable current fact.",
               "valid_from": (pivot - timedelta(days=1)).isoformat(), "valid_to": None, "expires_at": None}

    class Session:
        def __init__(self):
            # 014 T029 adds an additive delivered-channel audit write to
            # start_work; the byte-stability assertions below are unchanged.
            self.audits = []

        async def get(self, model, key):
            return SimpleNamespace(slug="scope", domain_key="generic") if model is KnowledgeScope else SimpleNamespace(description="", memory_policy={})

        async def commit(self):
            return None

        def add(self, row):
            self.audits.append(row)

    async def resolve(self, reference):
        return 7

    async def views(self, *args, **kwargs):
        return rows, {}, [], []

    clock = pivot - timedelta(seconds=1)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock

    monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(MemoryScopeResolver, "resolve", resolve)
    monkeypatch.setattr(module.MemoryReader, "_views", views)
    reader = module.MemoryReader(Session(), None)
    before = await reader.start_work(scope_ref="7")
    clock = pivot + timedelta(seconds=1)
    after = await reader.start_work(scope_ref="7")
    assert {key: value for key, value in before.items() if key != "request_id"} == {key: value for key, value in after.items() if key != "request_id"}
    assert [item["memory_id"] for item in after["working_set"]["memories"]] == [2]
    assert "Temporally limited fact." not in str(after)


@pytest.mark.asyncio
async def test_large_inference_metadata_cannot_escape_recall_or_work_budget(db_session):
    sid, payload = await scope_and_payload(db_session)
    payload["inference_meta"]["source"] = "M" * 8000
    service = MemoryService(db_session)
    await service.record(payload)
    recall = await service.recall(scope_ref=[str(sid)])
    assert visible_characters(recall["memories"]) <= 6000
    for budget, maximum in (("standard", 2000), ("compact", 800), ("minimal", 300)):
        result = await service.start_work(scope_ref=str(sid), budget=budget)
        values = {key: result[key] for key in ("scope", "domain_brief", "digest", "working_set", "read_guidance")}
        assert visible_characters(values) <= maximum
        assert result["read_guidance"]


@pytest.mark.asyncio
async def test_historical_superseded_requires_explicit_permission(db_session):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    first = await service.record(payload)
    manifest = await service.projections.current(sid)
    point = manifest.payload["state"]["entries"][str(first["memory_id"])]["valid_from"]
    await service.record({**payload, "content": "The corrected fact.", "supersedes_memory_id": first["memory_id"]})
    assert (await service.recall(scope_ref=[str(sid)], as_of=point))["memories"] == []
    allowed = await service.recall(scope_ref=[str(sid)], as_of=point, include_superseded=True)
    assert [row["memory_id"] for row in allowed["memories"]] == [first["memory_id"]]


@pytest.mark.asyncio
async def test_partial_dense_failure_preserves_successful_scope_intersection(db_session, monkeypatch):
    sid, payload = await scope_and_payload(db_session)
    other, second_payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    await service.record(payload)
    second = await service.record(second_payload)
    first_manifest = await service.projections.current(sid)
    original = service.projections.qdrant._client.query_points
    def partially_available(**kwargs):
        if str(sid) in kwargs["query_filter"].model_dump_json():
            return original(**kwargs, score_threshold=1.1)
        raise OSError("one scope failed")
    monkeypatch.setattr(service.projections.qdrant._client, "query_points", partially_available)
    result = await service.recall(scope_ref=[str(sid), str(other)], query="scoped procedure")
    assert result["completion_status"] == "partial"
    assert [row["memory_id"] for row in result["memories"]] == [second["memory_id"]]


@pytest.mark.asyncio
async def test_work_package_refreshes_after_domain_policy_change(db_session):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    await service.record(payload)
    before = await service.start_work(scope_ref=str(sid))
    profile = await db_session.get(DomainProfile, "generic")
    original = profile.memory_policy
    try:
        profile.memory_policy = {**original, "decay_rate": .07}
        await db_session.commit()
        after = await service.start_work(scope_ref=str(sid))
        assert after["package_fingerprint"] != before["package_fingerprint"]
        assert after["domain_brief"]["policy_fingerprint"] != before["domain_brief"]["policy_fingerprint"]
    finally:
        profile.memory_policy = original
        await db_session.commit()


@pytest.mark.asyncio
async def test_custom_domain_work_budgets_are_consumed(db_session):
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    from uuid import uuid4
    sid, payload = await scope_and_payload(db_session)
    key = "budget-" + uuid4().hex
    db_session.add(DomainProfile(domain_key=key, name=key, supported_formats=["markdown"], graph_relations={},
        default_capabilities={}, memory_policy={"start_work_budgets": {"full": 600, "compact": 400, "minimal": 250}}))
    (await db_session.get(KnowledgeScope, sid)).domain_key = key
    await db_session.commit()
    service = MemoryService(db_session)
    for index in range(3):
        await service.record({**payload, "content": str(index) + "Scoped procedure. " * 50})
    for budget, maximum in (("standard", 600), ("compact", 400), ("minimal", 250)):
        result = await service.start_work(scope_ref=str(sid), budget=budget)
        assert visible_characters({key: result[key] for key in ("scope", "domain_brief", "digest", "working_set", "read_guidance")}) <= maximum
