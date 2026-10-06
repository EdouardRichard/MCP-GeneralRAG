def test_projection_rebuild_registry_and_full_replay_fingerprint():
    from rag_mcp.runtime.projection_rebuild import ProjectionRebuilder

    rebuilder = ProjectionRebuilder()
    assert set(rebuilder.projection_types) >= {"relation", "vector", "file", "salience"}
    events = [{"event_id": 1, "event_type": "assert", "aggregate_id": 1, "knowledge_scope_id": 1, "payload": {"content_text": "x"}}]
    assert rebuilder.rebuild(events).fingerprint == rebuilder.rebuild(events, snapshot=None).fingerprint


def test_incremental_rebuild_keeps_prefix_and_falls_back_for_rollback_dependencies():
    from rag_mcp.runtime.projection_rebuild import ProjectionRebuilder
    events = [
        {"event_id": 1, "aggregate_id": 1, "knowledge_scope_id": 7, "event_type": "assert",
         "occurred_at": "2026-10-01T00:00:00+00:00", "payload": {"content_text": "Old", "provenance": "soft"}},
        {"event_id": 2, "aggregate_id": 2, "knowledge_scope_id": 7, "event_type": "revise",
         "occurred_at": "2026-10-02T00:00:00+00:00", "payload": {"content_text": "New", "provenance": "soft", "supersedes_memory_id": 1}},
    ]
    rebuilder = ProjectionRebuilder()
    rebuilt = rebuilder.rebuild(events, since_event_id=1)
    assert rebuilt.source == "prefix_delta"
    assert rebuilt.fingerprint == rebuilder.rebuild(events).fingerprint
    events.append({"event_id": 3, "aggregate_id": 3, "knowledge_scope_id": 7, "event_type": "rollback",
        "occurred_at": "2026-10-03T00:00:00+00:00", "payload": {"event_point": 1, "reason": "dependency"}})
    rebuilt = rebuilder.rebuild(events, since_event_id=2)
    assert rebuilt.source == "full_log"
    assert rebuilt.fingerprint == rebuilder.rebuild(events).fingerprint


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


def _checkpoint(events):
    from rag_mcp.runtime.projection_rebuild import SNAPSHOT_VIEWS
    from rag_mcp.services.memory_reducer import reduce_events, projection_fingerprint

    state = reduce_events(events)
    return {"status": "complete", "schema_version": 1, "scope_id": events[0]["knowledge_scope_id"],
            "covered_through_event_id": events[-1]["event_id"], "source_events": events,
            "state_fingerprint": projection_fingerprint(state),
            "fingerprints": {name: projection_fingerprint(state[key]) for name, key in SNAPSHOT_VIEWS.items()}}


def test_snapshot_incremental_replay_falls_back_for_rollback_dependencies():
    from rag_mcp.runtime.projection_rebuild import ProjectionRebuilder

    events = [{"event_id": 1, "aggregate_id": 1, "knowledge_scope_id": 7, "event_type": "assert",
               "occurred_at": "2026-10-01T00:00:00+00:00", "payload": {"content_text": "Fact", "provenance": "soft"}}]
    snapshot = _checkpoint(events)
    events = [*events, {"event_id": 2, "aggregate_id": 2, "knowledge_scope_id": 7, "event_type": "rollback",
                       "occurred_at": "2026-10-02T00:00:00+00:00", "payload": {"event_point": 1, "reason": "restore"}}]
    rebuilder = ProjectionRebuilder()
    recovered = rebuilder.rebuild(events, snapshot=snapshot, since_event_id=1)
    assert recovered.source == "full_log"
    assert recovered.fingerprint == rebuilder.rebuild(events).fingerprint


def test_semantically_invalid_snapshot_falls_back_to_full_log():
    from rag_mcp.runtime.projection_rebuild import ProjectionRebuilder

    events = [{"event_id": 1, "aggregate_id": 1, "knowledge_scope_id": 7, "event_type": "assert",
               "payload": {"content_text": "Fact"}}]
    valid = _checkpoint(events)
    forged = _checkpoint([{**events[0], "payload": {"content_text": "Forged"}}])
    rebuilder = ProjectionRebuilder()
    for damaged in ({**valid, "source_events": []},
                    {**valid, "source_events": [{**events[0], "payload": {"content_text": "Forged"}}]},
                    {**valid, "covered_through_event_id": 2},
                    {**valid, "covered_through_event_id": "invalid"}, forged, []):
        recovered = rebuilder.rebuild(events, snapshot=damaged)
        assert recovered.source == "full_log"
        assert recovered.fingerprint == rebuilder.rebuild(events).fingerprint


async def test_history_checks_authority_ids_independently_of_snapshot(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from rag_mcp.runtime.projection_rebuild import MemoryHistory
    from rag_mcp.services.memory_event_store import MemoryEventStore

    class Session:
        async def execute(self, statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [1, 2]))

    async def incomplete_replay(store, scope_id):
        return [{"event_id": 2, "knowledge_scope_id": scope_id}]

    monkeypatch.setattr(MemoryEventStore, "replay", incomplete_replay)
    history = MemoryHistory(SimpleNamespace(session=Session()))
    with pytest.raises(ValueError, match="incomplete immutable checkpoint log"):
        await history.load(7)


async def test_history_rejects_payload_covered_point_different_from_snapshot_row(monkeypatch):
    from types import SimpleNamespace
    import hashlib
    from rag_mcp.runtime.projection_rebuild import MemoryHistory, ProjectionRebuilder, encoded
    from rag_mcp.services.memory_event_store import MemoryEventStore

    events = [{"event_id": 1, "aggregate_id": 1, "knowledge_scope_id": 7, "event_type": "assert",
               "payload": {"content_text": "Fact"}}]
    valid = _checkpoint(events)

    class Session:
        async def execute(self, statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [1]))

    async def replay(store, scope_id):
        return events

    async def latest(scope_id):
        return SimpleNamespace(covered_through_event_id=2, payload=valid,
                               fingerprint=hashlib.sha256(encoded(valid)).hexdigest())

    async def archives(scope_id, replayed):
        pass

    monkeypatch.setattr(MemoryEventStore, "replay", replay)
    history = MemoryHistory(SimpleNamespace(session=Session()))
    monkeypatch.setattr(history, "_latest", latest)
    monkeypatch.setattr(history, "_verify_archives", archives)
    recovered = await history.load(7)
    assert recovered.source == "full_log"
    assert recovered.fingerprint == ProjectionRebuilder().rebuild(events).fingerprint

