from rag_mcp.services.memory_reducer import reduce_events, projection_fingerprint


def test_online_materialization_matches_replay_for_business_events():
    events = [
        {"event_id": 1, "event_type": "assert", "aggregate_id": 1, "knowledge_scope_id": 10, "payload": {"content_text": "a", "provenance": "hard"}},
        {"event_id": 2, "event_type": "revise", "aggregate_id": 1, "knowledge_scope_id": 10, "payload": {"content_text": "b"}},
        {"event_id": 3, "event_type": "retract", "aggregate_id": 1, "knowledge_scope_id": 10, "payload": {}},
        {"event_id": 4, "event_type": "access", "aggregate_id": 1, "knowledge_scope_id": 10, "payload": {}},
    ]
    assert projection_fingerprint(reduce_events(events)) == projection_fingerprint(reduce_events(list(reversed(events))))
    assert reduce_events(events)["entries"][1]["status"] == "retired"

