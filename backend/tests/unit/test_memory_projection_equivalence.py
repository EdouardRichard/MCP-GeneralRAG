from rag_mcp.services.memory_reducer import reduce_events, projection_fingerprint


def test_online_and_replay_reducers_are_equivalent():
    events = [
        {"event_id": 1, "event_type": "assert", "aggregate_id": 10,
         "knowledge_scope_id": 7, "payload": {"content_text": "a", "kind": "episodic", "provenance": "hard"}},
        {"event_id": 2, "event_type": "access", "aggregate_id": 10,
         "knowledge_scope_id": 7, "payload": {}},
        {"event_id": 3, "event_type": "revise", "aggregate_id": 10,
         "knowledge_scope_id": 7, "payload": {"content_text": "b", "valid_from": "2026-01-01T00:00:00+00:00"}},
    ]
    online = reduce_events(events)
    replay = reduce_events(tuple(events))
    assert projection_fingerprint(online) == projection_fingerprint(replay)
    assert online["entries"][10]["content_text"] == "b"
    assert online["salience"][10]["access_count"] == 1


def test_reducer_preserves_scope_provenance_and_retracts():
    events = [
        {"event_id": 1, "event_type": "assert", "aggregate_id": 10,
         "knowledge_scope_id": 7, "payload": {"content_text": "a", "provenance": "hard", "evidence_refs": ["e1"]}},
        {"event_id": 2, "event_type": "retract", "aggregate_id": 10,
         "knowledge_scope_id": 7, "payload": {}},
    ]
    state = reduce_events(events)
    entry = state["entries"][10]
    assert entry["status"] == "retired"
    assert entry["knowledge_scope_id"] == 7
    assert entry["evidence_refs"] == ["e1"]
