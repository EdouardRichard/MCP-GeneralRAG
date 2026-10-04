def test_projection_rebuild_registry_and_full_replay_fingerprint():
    from rag_mcp.runtime.projection_rebuild import ProjectionRebuilder

    rebuilder = ProjectionRebuilder()
    assert set(rebuilder.projection_types) >= {"relation", "vector", "file", "salience"}
    events = [{"event_id": 1, "event_type": "assert", "aggregate_id": 1, "knowledge_scope_id": 1, "payload": {"content_text": "x"}}]
    assert rebuilder.rebuild(events).fingerprint == rebuilder.rebuild(events, snapshot=None).fingerprint

