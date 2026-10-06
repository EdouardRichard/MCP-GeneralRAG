"""Nonempty projection trajectories, rather than comparing a reducer to itself."""
from copy import deepcopy

import pytest

from rag_mcp.services.memory_reducer import reduce_events, projection_fingerprint


PROJECTIONS = ("entries", "dense", "links", "summary", "files", "salience")
AXES = ("authority", "scope_meta", "mutability", "provenance_meta", "recoverability", "actionability")


def governed_fact(event_id=1, memory_id=10, **extra):
    return {**fact(event_id, memory_id, **extra),
            "authority": {"source": "validated_evidence", "event": event_id},
            "scope_meta": {"knowledge_scope_id": 7, "boundary": "project"},
            "mutability": {"correction": "supersede"},
            "provenance_meta": {"attributions": [{"evidence_id": "101"}], "validator": "v1"},
            "recoverability": {"source": "event_log", "checkpoint": event_id},
            "actionability": "evidence"}


def projection_rows(state, name):
    if name == "summary":
        return [row for rows in state[name].values() for row in rows]
    return list(state[name].values())


@pytest.mark.parametrize("name", PROJECTIONS)
def test_all_six_axes_survive_nonempty_projection_and_access(name):
    source = governed_fact()
    source["payload"].update({axis: "payload must not forge governance" for axis in AXES})
    access = {**event(2, "access"), **{axis: {"source": "usage"} for axis in AXES}}
    state = reduce_events([source, access])
    rows = projection_rows(state, name)
    assert rows
    for row in rows:
        assert {axis: row.get(axis) for axis in AXES} == {axis: source[axis] for axis in AXES}


@pytest.mark.parametrize("name", PROJECTIONS)
def test_governance_axes_survive_supersede_retirement_and_rollback(name):
    source = governed_fact()
    replacement = governed_fact(2, 20, supersedes_memory_id=10)
    replacement["event_type"] = "revise"
    history = [source, replacement, event(3, "access", 20), event(4, "retract", 20)]
    deleted = reduce_events(history)
    for row in projection_rows(deleted, name):
        original = source if row["memory_id"] == 10 else replacement
        assert {axis: row.get(axis) for axis in AXES} == {axis: original[axis] for axis in AXES}
    restored = reduce_events([*history, event(5, "rollback", event_point=1, reason="restore")])
    for row in projection_rows(restored, name):
        original = source if row["memory_id"] == 10 else replacement
        assert {axis: row.get(axis) for axis in AXES} == {axis: original[axis] for axis in AXES}
    assert restored["salience"][20]["access_count"] == 1


def test_legacy_events_get_context_defaults_without_fabricating_trust():
    source = fact()
    state = reduce_events([source])
    for name in PROJECTIONS:
        for row in projection_rows(state, name):
            assert all(axis in row for axis in AXES)
            assert row["authority"] == {"source": "event_log", "event_id": 1}
            assert row["scope_meta"] == {"knowledge_scope_id": 7}
            assert row["provenance_meta"] == {"provenance": "hard", "evidence_refs": ["101"], "inference_meta": None}
            assert row["actionability"] is None


def test_explicit_empty_and_null_axis_values_are_preserved():
    source = {**fact(), **{axis: {} for axis in AXES[:-1]}, "actionability": None}
    for name in PROJECTIONS:
        for row in projection_rows(reduce_events([source]), name):
            assert {axis: row.get(axis) for axis in AXES} == {axis: source[axis] for axis in AXES}


def event(event_id, event_type="assert", memory_id=10, scope=7, **payload):
    return {
        "event_id": event_id, "event_type": event_type, "aggregate_id": memory_id,
        "knowledge_scope_id": scope, "occurred_at": f"2026-10-05T00:00:{event_id:02d}+00:00",
        "payload": payload,
    }


def fact(event_id=1, memory_id=10, scope=7, **extra):
    return event(event_id, memory_id=memory_id, scope=scope, content_text="Published fact",
                 kind="semantic", provenance="hard", evidence_refs=["101"], **extra)


def test_every_business_projection_contains_traceable_data():
    state = reduce_events([fact()])
    assert set(PROJECTIONS).issubset(state), "four business projections are missing"
    for name in PROJECTIONS:
        assert state[name], f"{name} is an empty placeholder"
        serialized = str(state[name])
        assert "101" in serialized, f"{name} lost evidence provenance"
        assert "knowledge_scope_id" in serialized, f"{name} lost isolation metadata"


def test_revise_creates_a_new_identity_and_closes_the_old_interval():
    old = fact()
    new = event(2, "revise", 20, content_text="Corrected fact", kind="semantic",
                provenance="hard", evidence_refs=["102"], supersedes_memory_id=10)
    state = reduce_events([old, new])
    assert state["entries"][10]["status"] == "superseded"
    assert state["entries"][10]["content_text"] == "Published fact"
    assert state["entries"][10]["superseded_by"] == 20
    assert state["entries"][10]["valid_to"] == new["occurred_at"]
    assert state["entries"][20]["supersedes_memory_id"] == 10
    assert state["entries"][20]["evidence_refs"] == ["102"]


def test_quarantine_and_retraction_propagate_to_all_consumable_views():
    history = [fact(), fact(2, 20, status="quarantined")]
    state = reduce_events(history + [event(3, "retract", reason="retired")])
    assert state["entries"][20]["status"] == "quarantined"
    assert state["entries"][10]["status"] == "retired"
    for name in ("dense", "links", "summary", "files"):
        assert not state.get(name), f"{name} exposes deleted or quarantined content"


def test_usage_cannot_change_fact_or_trust_metadata():
    original = reduce_events([fact()])["entries"][10]
    access = event(2, "access", content_text="overwrite", provenance="soft", confidence=1.0)
    state = reduce_events([fact(), access])
    assert state["entries"][10] == original
    assert state["salience"][10]["access_count"] == 1


def test_cross_scope_revision_is_rejected():
    with pytest.raises(ValueError, match="SCOPE"):
        reduce_events([fact(), event(2, "retract", scope=8)])


def test_rollback_restores_state_and_preserves_usage_and_other_scope():
    history = [fact(), fact(2, 30, 8), event(3, "access"), event(4, "retract")]
    saved = deepcopy(history)
    state = reduce_events(history + [event(5, "rollback", event_point=1, reason="human correction")])
    assert state["entries"][10]["status"] == "active"
    assert state["entries"][30]["knowledge_scope_id"] == 8
    assert state["salience"][10]["access_count"] == 1
    for name in PROJECTIONS:
        assert state[name], f"rollback did not restore {name}"
    assert history == saved, "event history was mutated"
    assert projection_fingerprint(state) == projection_fingerprint(reduce_events(history + [event(5, "rollback", event_point=1, reason="human correction")]))


def test_projection_repository_rejects_dictionary_with_entries_key():
    from rag_mcp.services.memory_projection_store import MemoryProjectionStore
    with pytest.raises(TypeError, match="reducer"):
        MemoryProjectionStore().upsert_from_reducer(10, {"entries": {10: {"content_text": "forged"}}})
