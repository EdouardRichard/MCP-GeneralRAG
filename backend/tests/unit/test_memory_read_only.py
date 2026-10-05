def test_projection_store_only_accepts_reducer_materialized_state():
    from rag_mcp.services.memory_projection_store import MemoryProjectionStore

    assert hasattr(MemoryProjectionStore, "upsert_from_reducer")
    assert not hasattr(MemoryProjectionStore, "update")
    assert not hasattr(MemoryProjectionStore, "delete")


def test_event_store_has_no_mutating_api():
    from rag_mcp.services.memory_event_store import MemoryEventStore

    assert not any(name in dir(MemoryEventStore) for name in ("update", "delete", "remove"))


def test_in_memory_projection_methods_cannot_bypass_log_authority():
    import pytest
    from rag_mcp.services.memory_projection_store import MemoryProjectionStore
    from rag_mcp.services.memory_reducer import reduce_events
    store = MemoryProjectionStore()
    state = reduce_events([{"event_id": 1, "aggregate_id": 1, "knowledge_scope_id": 1,
                            "event_type": "assert", "payload": {"content_text": "unlogged"}}])
    with pytest.raises(PermissionError, match="immutable log"):
        store.upsert_from_reducer(1, state)
    with pytest.raises(PermissionError, match="immutable log"):
        store.mark_failed(1, "dense")


async def test_low_level_upsert_cannot_accept_unsealed_values():
    import pytest
    from rag_mcp.models.memory_projection import MemoryEntry
    from rag_mcp.services.memory_projection_store import MemoryProjectionStore
    with pytest.raises(TypeError, match="reducer"):
        await MemoryProjectionStore()._upsert({}, 1, 1, MemoryEntry, {"memory_id": 1}, "memory_id")


async def test_every_adapter_rejects_unsealed_even_empty_state():
    import pytest
    from rag_mcp.services.memory_projection_store import MemoryProjectionStore
    store = MemoryProjectionStore()
    raw = {"entries": {}, "bindings": {}, "dense": {}, "links": {}, "summary": {}, "files": {}, "salience": {}}
    for name in ("relation", "dense", "links", "summary", "files", "salience", "bindings"):
        with pytest.raises(TypeError, match="reducer"):
            await getattr(store, f"_materialize_{name}")(raw, 1, 1)

