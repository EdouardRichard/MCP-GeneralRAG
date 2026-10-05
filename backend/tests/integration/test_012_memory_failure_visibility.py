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
