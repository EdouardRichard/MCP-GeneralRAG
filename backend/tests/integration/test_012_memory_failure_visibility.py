import pytest


@pytest.mark.asyncio
async def test_failed_projection_is_not_complete_or_recallable(db_session, monkeypatch):
    from rag_mcp.services.memory_service import MemoryService
    from tests.integration.test_012_live_reader import scope_and_payload
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    initial = await service.record(payload)
    async def failed(*args, **kwargs):
        raise OSError("dense unavailable")
    monkeypatch.setattr(service.projections, "_materialize_dense", failed)
    with pytest.raises(ValueError, match="MEMORY_WRITE_UNAVAILABLE"):
        await service.record({**payload, "content": "The uncompleted correction", "supersedes_memory_id": initial["memory_id"]})
    result = await service.recall(scope_ref=[str(sid)])
    assert result["completion_status"] == "partial"
    assert [row["memory_id"] for row in result["memories"]] == [initial["memory_id"]]
    assert result["memory_notice"]["failed_paths"] == ["dense"]
    package = await service.start_work(scope_ref=str(sid))
    assert [row["memory_id"] for row in package["digest"]["memories"]] == [initial["memory_id"]]
    monkeypatch.undo()
    assert all(row["matches_replay"] for row in (await service.rebuild(sid, actor="management")).values())


@pytest.mark.asyncio
async def test_failed_policy_projection_rebuild_restores_profile_without_replaying_old_grants(db_session, monkeypatch):
    from copy import deepcopy
    from uuid import uuid4
    from rag_mcp.models.domain_profile import DomainProfile
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    from rag_mcp.services.memory_event_store import MemoryEventStore
    from rag_mcp.services.memory_service import MemoryService
    from tests.integration.test_012_live_reader import scope_and_payload

    sid, payload = await scope_and_payload(db_session)
    scope = await db_session.get(KnowledgeScope, sid)
    seed = await db_session.get(DomainProfile, "generic")
    key = "failed-policy-" + uuid4().hex
    db_session.add(DomainProfile(domain_key=key, name=key, supported_formats=["markdown"], graph_relations={},
        default_capabilities={}, memory_policy=deepcopy(seed.memory_policy)))
    scope.domain_key = key
    await db_session.commit()
    service = MemoryService(db_session)
    await service.record(payload)

    async def failed(*args, **kwargs):
        raise OSError("dense unavailable")

    monkeypatch.setattr(service.projections, "_materialize_dense", failed)
    with pytest.raises(ValueError, match="MEMORY_WRITE_UNAVAILABLE"):
        await service.govern("policy", scope_id=sid, actor="management", reason="raise decay", policy={"decay_rate": .2})
    events = await MemoryEventStore(db_session).replay(sid)
    assert events[-1]["event_type"] == "grant" and events[-1]["payload"]["policy_after"]["decay_rate"] == .2
    profile = await db_session.get(DomainProfile, key, populate_existing=True)
    assert profile.memory_policy["decay_rate"] == seed.memory_policy["decay_rate"]
    monkeypatch.undo()
    report = await service.rebuild(sid, actor="management", reason="recover policy")
    assert all(row["matches_replay"] for row in report.values())
    profile = await db_session.get(DomainProfile, key, populate_existing=True)
    assert profile.memory_policy["decay_rate"] == .2


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["assert", "supersede", "retire"])
async def test_inspect_exception_after_external_write_retains_recovery_authority(db_session, monkeypatch, action):
    from rag_mcp.services.memory_service import MemoryService
    from rag_mcp.services.memory_event_store import MemoryEventStore
    from tests.integration.test_012_live_reader import scope_and_payload

    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    first = await service.record(payload)
    before = await MemoryEventStore(db_session).replay(sid)
    completed_point = (await service.projections.current(sid)).source_event_id
    original = service.projections.inspect

    async def failed(state, scope):
        if service.projections._candidate_revision is None:
            raise OSError("verification filesystem or Qdrant failed")
        return await original(state, scope)

    monkeypatch.setattr(service.projections, "inspect", failed)
    with pytest.raises(ValueError, match="MEMORY_WRITE_UNAVAILABLE"):
        if action == "retire":
            await service.govern("retire", scope_id=sid, memory_id=first["memory_id"], actor="management", reason="retirement")
        else:
            await service.record({**payload, "content": "Unverified new fact.",
                                  **({"supersedes_memory_id": first["memory_id"]} if action == "supersede" else {})})
    history = await MemoryEventStore(db_session).replay(sid)
    assert len(history) == len(before) + 1
    assert (await service.projections.current(sid)).source_event_id == completed_point
    result = await service.recall(scope_ref=[str(sid)])
    assert [row["memory_id"] for row in result["memories"]] == [first["memory_id"]]
    assert result["completion_status"] == "partial"
    monkeypatch.undo()
    report = await service.rebuild(sid, actor="management")
    assert all(row["matches_replay"] for row in report.values())
    recovered = await service.recall(scope_ref=[str(sid)])
    expected = [] if action == "retire" else [history[-1]["aggregate_id"]] if action == "supersede" else [history[-1]["aggregate_id"], first["memory_id"]]
    assert [row["memory_id"] for row in recovered["memories"]] == expected
