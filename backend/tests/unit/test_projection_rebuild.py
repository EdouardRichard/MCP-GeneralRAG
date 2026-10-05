def test_projection_rebuild_registry_and_full_replay_fingerprint():
    from rag_mcp.runtime.projection_rebuild import ProjectionRebuilder

    rebuilder = ProjectionRebuilder()
    assert set(rebuilder.projection_types) >= {"relation", "vector", "file", "salience"}
    events = [{"event_id": 1, "event_type": "assert", "aggregate_id": 1, "knowledge_scope_id": 1, "payload": {"content_text": "x"}}]
    assert rebuilder.rebuild(events).fingerprint == rebuilder.rebuild(events, snapshot=None).fingerprint


def test_verified_reducer_checkpoint_accepts_incremental_access_revision_and_binding():
    from rag_mcp.services.memory_reducer import reduce_events, projection_fingerprint
    first = {"event_id": 1, "aggregate_id": 1, "knowledge_scope_id": 7, "event_type": "assert",
             "occurred_at": "2026-10-01T00:00:00+00:00", "payload": {"content_text": "Old", "provenance": "soft"}}
    grant = {"event_id": 2, "aggregate_id": 2, "knowledge_scope_id": 7, "event_type": "grant",
             "payload": {"binding_id": 2, "binding_kind": "dir_name", "binding_value": "project", "priority": 0, "status": "active"}}
    delta = [
        {"event_id": 3, "aggregate_id": 1, "knowledge_scope_id": 7, "event_type": "access", "occurred_at": "2026-10-02T00:00:00+00:00", "payload": {}},
        {"event_id": 4, "aggregate_id": 4, "knowledge_scope_id": 7, "event_type": "revise", "occurred_at": "2026-10-03T00:00:00+00:00", "payload": {"content_text": "New", "provenance": "soft", "supersedes_memory_id": 1}},
        {**grant, "event_id": 5, "payload": {**grant["payload"], "status": "disabled"}},
    ]
    checkpoint = reduce_events([first, grant])
    incremental = reduce_events(delta, initial_state=checkpoint)
    assert projection_fingerprint(incremental) == projection_fingerprint(reduce_events([first, grant, *delta]))
    assert incremental["salience"][1]["access_count"] == 1
    assert incremental["entries"][1]["superseded_by"] == 4
    assert len(incremental["bindings"]) == 1

