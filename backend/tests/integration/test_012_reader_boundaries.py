import pytest

from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


def visible_characters(value):
    if isinstance(value, dict):
        return sum(visible_characters(item) for item in value.values())
    if isinstance(value, list):
        return sum(visible_characters(item) for item in value)
    return len(value) if isinstance(value, str) else 0


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
        if kwargs["collection_name"] == first_manifest.payload["collection"]:
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
