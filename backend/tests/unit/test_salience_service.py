import pytest


def test_salience_cold_start_decay_and_no_decay_gate():
    from rag_mcp.services.salience_service import SalienceService

    service = SalienceService()
    assert service.initial() == 0.0
    assert service.update(0.0, access_count=1, age_days=0) == 1.0
    assert service.rank_signal(1.0, decay_rate=0.0) == 0.0


def test_forced_decay_is_linear_in_inactivity_not_salience_multiplier():
    from rag_mcp.services.salience_service import SalienceService
    service = SalienceService(beta=.05)
    assert service.update(10, access_count=0, age_days=20) == 9
    assert service.update(0, access_count=0, age_days=20) == 0


def test_rank_signal_requires_explicit_decay_execution():
    from rag_mcp.services.salience_service import SalienceService
    service = SalienceService()
    assert service.rank_signal(10, decay_rate=.05) == 0
    assert service.rank_signal(10, decay_rate=.05, age_days=20) == 9


def test_zero_access_long_inactivity_and_clock_reversal_boundaries():
    from rag_mcp.services.salience_service import SalienceService
    service = SalienceService()
    for days in (0, 20, 10000):
        assert service.update(0, access_count=0, age_days=days) == 0
        assert service.rank_signal(0, decay_rate=.05, age_days=days) == 0
    assert service.rank_signal(1, decay_rate=.05, age_days=20) == 0
    assert service.rank_signal(1, decay_rate=.05, age_days=10000) == 0
    assert service.rank_signal(1, decay_rate=.05, age_days=-10) == 1
    assert service.update(1, access_count=1, age_days=-10) == 2
    assert SalienceService(beta=.2).update(1, access_count=1, age_days=5) == 1
    assert service.rank_signal(2, decay_rate=.2, age_days=5) == 1


def _policy_history():
    from copy import deepcopy

    source = {"event_id": 1, "aggregate_id": 10, "knowledge_scope_id": 7,
              "event_type": "assert", "occurred_at": "2026-01-01T00:00:00+00:00",
              "payload": {"content_text": "Keep facts unchanged.", "kind": "procedural",
                          "provenance": "soft", "evidence_refs": ["source-1"],
                          "inference_meta": {"source": "reviewed inference"}, "decay_rate": .05},
              "authority": {"source": "validated_memory"}, "scope_meta": {"knowledge_scope_id": 7},
              "mutability": {"correction": "supersede"}, "provenance_meta": {"source": "reviewed inference"},
              "recoverability": {"source": "event_log"}, "actionability": "reference_only"}

    def event(identifier, kind, stamp, payload):
        return {**deepcopy(source), "event_id": identifier, "event_type": kind,
                "aggregate_id": 10 if kind == "access" else identifier,
                "occurred_at": stamp, "payload": payload}

    return [source,
            event(2, "access", "2026-01-01T00:00:00+00:00", {"decay_rate": .05}),
            event(3, "grant", "2026-01-02T00:00:00+00:00",
                  {"policy_after": {"decay_rate": .2}, "domain_key": "custom"}),
            event(4, "access", "2026-01-06T00:00:00+00:00", {"decay_rate": .2})]


def test_access_replays_the_rate_captured_after_policy_override():
    import pytest
    from rag_mcp.services.memory_reducer import GOVERNANCE_AXES, projection_fingerprint, reduce_events
    from rag_mcp.services.salience_service import SalienceService

    events = _policy_history()
    before = reduce_events(events[:1])
    after = reduce_events(events)
    state = after["salience"][10]
    assert state["salience"] == pytest.approx(1.)
    assert state["decay_rate"] == .2
    assert state["access_count"] == 2
    assert state["last_access_at"] == state["reinforced_at"] == events[-1]["occurred_at"]
    assert after["entries"] == before["entries"]
    assert {axis: state[axis] for axis in GOVERNANCE_AXES} == {
        axis: before["salience"][10][axis] for axis in GOVERNANCE_AXES}
    assert SalienceService().rank_signal(state["salience"], decay_rate=.2) == 0
    assert SalienceService().rank_signal(state["salience"], decay_rate=.2, age_days=2) == pytest.approx(.6)
    incremental = reduce_events(events[3:], initial_state=reduce_events(events[:3]))
    assert projection_fingerprint(incremental) == projection_fingerprint(after)


def test_later_policy_and_rollback_preserve_recorded_access_dynamics():
    from copy import deepcopy
    from rag_mcp.services.memory_reducer import projection_fingerprint, reduce_events

    events = _policy_history()
    original = deepcopy(events)
    before = reduce_events(events)
    events.append({**events[2], "event_id": 5, "aggregate_id": 5,
                   "payload": {"policy_after": {"decay_rate": .9}, "domain_key": "custom"}})
    assert projection_fingerprint(reduce_events(events)) == projection_fingerprint(before)
    events.append({**events[-1], "event_id": 6, "event_type": "rollback",
                   "payload": {"event_point": 1, "reason": "Restore authority facts"}})
    after = reduce_events(events)
    assert after["salience"] == before["salience"]
    assert after["salience"][10]["decay_rate"] == .2
    assert after["entries"] == reduce_events(original[:1])["entries"]
    assert events[:4] == original


def test_legacy_access_keeps_last_recorded_rate_and_explicit_zero_is_preserved():
    import pytest
    from rag_mcp.services.memory_reducer import reduce_events
    from rag_mcp.services.salience_service import SalienceService

    events = _policy_history()
    events.append({**events[-1], "event_id": 5, "occurred_at": "2026-01-07T00:00:00+00:00",
                   "payload": {"reason": "Legacy access has no captured policy"}})
    legacy = reduce_events(events)["salience"][10]
    assert legacy["decay_rate"] == .2
    assert legacy["salience"] == pytest.approx(1.8)
    events.append({**events[-1], "event_id": 6, "occurred_at": "2026-01-08T00:00:00+00:00",
                   "payload": {"decay_rate": 0.}})
    no_decay = reduce_events(events)["salience"][10]
    assert no_decay["decay_rate"] == 0.
    assert no_decay["salience"] == pytest.approx(2.8)
    assert SalienceService().rank_signal(no_decay["salience"], decay_rate=0., age_days=1) == 0.


@pytest.mark.parametrize(("policy", "rate", "expected_salience"), [
    ({}, .05, 1.75), ({"decay_rate": .2}, .2, 1.), ({"decay_rate": 0.}, 0., 2.),
])
def test_governance_access_captures_the_resolved_current_policy(monkeypatch, policy, rate, expected_salience):
    import asyncio
    from contextlib import asynccontextmanager
    from copy import deepcopy
    from datetime import datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from rag_mcp.models.domain_profile import DomainProfile
    from rag_mcp.models.memory_event import MemoryEvent
    from rag_mcp.services import memory_governance
    from rag_mcp.services.memory_reducer import reduce_events

    history = _policy_history()[:3]
    profile = SimpleNamespace(memory_policy=policy)

    async def get(model, identifier, **kwargs):
        if model is DomainProfile:
            assert identifier == "custom"
            return profile
        return SimpleNamespace(status="active", domain_key="custom")

    @asynccontextmanager
    async def nested():
        yield

    session = SimpleNamespace(get=AsyncMock(side_effect=get), execute=AsyncMock(),
                              begin_nested=nested, commit=AsyncMock(), rollback=AsyncMock())

    class EventStore:
        def __init__(self, session):
            pass

        async def replay(self, scope_id):
            return deepcopy(history)

        async def append(self, event):
            history.append({column.name: getattr(event, column.name)
                            for column in MemoryEvent.__table__.columns if column.name != "created_at"})

    projections = SimpleNamespace(current=AsyncMock(return_value=SimpleNamespace(source_event_id=3)),
                                 materialize=AsyncMock(), inspect=AsyncMock(return_value={
                                     name: {"matches_replay": True} for name in (
                                         "relation", "dense", "links", "summary", "file", "salience")}))
    service = SimpleNamespace(session=session, projections=projections, _ensure_vector_store=lambda: None)
    monkeypatch.setattr(memory_governance, "MemoryEventStore", EventStore)
    monkeypatch.setattr(memory_governance, "generate_id", lambda: 4)
    monkeypatch.setattr(memory_governance, "datetime", SimpleNamespace(
        now=lambda zone: datetime.fromisoformat("2026-01-06T00:00:00+00:00")))
    result = asyncio.run(memory_governance.MemoryGovernance(service).execute(
        "access", scope_id=7, memory_id=10, actor="management", reason="Reviewed the procedure"))
    event = history[-1]
    assert event["payload"]["decay_rate"] == rate
    assert event["event_type"] == "access" and result["event_id"] == 4
    assert reduce_events(history)["salience"][10]["salience"] == expected_salience
    profile.memory_policy = {"decay_rate": .9}
    assert event["payload"]["decay_rate"] == rate
    assert reduce_events(history)["salience"][10]["decay_rate"] == rate

