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

