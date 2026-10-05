"""Immutable dense revisions share an index without sharing visibility."""
import asyncio
import pytest

from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
async def test_dense_revisions_do_not_allocate_a_collection_per_write(db_session):
    service = MemoryService(db_session)
    a, one = await scope_and_payload(db_session)
    b, two = await scope_and_payload(db_session)
    first = await service.record(one)
    old = await service.projections.current(a)
    old_collection, old_revision = old.payload["collection"], old.source_event_id
    second = await service.record(two)
    other = await service.projections.current(b)
    corrected = await service.record({**one, "content": "Corrected explicit scope procedure", "supersedes_memory_id": first["memory_id"]})
    current = await service.projections.current(a)
    assert old_collection == other.payload["collection"] == current.payload["collection"]
    from rag_mcp.indexing.memory_vectors import revision_filter
    for scope_id, revision, expected in ((a, old_revision, {first["memory_id"]}),
                                       (b, other.source_event_id, {second["memory_id"]}),
                                       (a, current.source_event_id, {first["memory_id"], corrected["memory_id"]})):
        points, _ = await asyncio.to_thread(service.projections.qdrant._client.scroll,
            collection_name=old_collection, scroll_filter=revision_filter(scope_id, revision), limit=100, with_payload=True)
        assert {point.payload["memory_id"] for point in points} == expected
        assert all(point.payload["knowledge_scope_id"] == str(scope_id) for point in points)
    recalled = await service.recall(scope_ref=[str(a)], query="explicit scope procedure")
    assert {row["memory_id"] for row in recalled["memories"]} == {corrected["memory_id"]}
    assert all(row["matches_replay"] for row in (await service.inspect_projections(a)).values())
