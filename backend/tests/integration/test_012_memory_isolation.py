from rag_mcp.services.memory_reducer import reduce_events


def test_explicit_scope_union_does_not_cross_leak():
    events = [
        {"event_id": 1, "event_type": "assert", "aggregate_id": 1, "knowledge_scope_id": 10, "payload": {"content_text": "A"}},
        {"event_id": 2, "event_type": "assert", "aggregate_id": 2, "knowledge_scope_id": 20, "payload": {"content_text": "B"}},
    ]
    state = reduce_events(events)
    assert {v["knowledge_scope_id"] for v in state["entries"].values() if v["knowledge_scope_id"] == 10} == {10}
    assert all(v["knowledge_scope_id"] in {10, 20} for v in state["entries"].values())
