def test_projection_store_only_accepts_reducer_materialized_state():
    from rag_mcp.services.memory_projection_store import MemoryProjectionStore

    assert hasattr(MemoryProjectionStore, "upsert_from_reducer")
    assert not hasattr(MemoryProjectionStore, "update")
    assert not hasattr(MemoryProjectionStore, "delete")


def test_event_store_has_no_mutating_api():
    from rag_mcp.services.memory_event_store import MemoryEventStore

    assert not any(name in dir(MemoryEventStore) for name in ("update", "delete", "remove"))

