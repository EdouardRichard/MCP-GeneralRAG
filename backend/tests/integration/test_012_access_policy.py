"""Access policy metadata survives actual REST, PG replay, and history recovery."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import text

from rag_mcp.db import get_session
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_salience import MemorySalience
from rag_mcp.runtime.projection_rebuild import MemoryHistory
from rag_mcp.server import create_app
from rag_mcp.services import memory_governance, memory_reader, memory_service
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_reducer import GOVERNANCE_AXES, projection_fingerprint, reduce_events
from tests.integration.memory_acceptance import writer_owner
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
async def test_rest_access_policy_is_immutable_and_rebuild_rollback_preserve_it(db_session, engine, monkeypatch):
    sid, payload = await scope_and_payload(db_session)
    domain_key = "access-policy-" + uuid4().hex
    seed = await db_session.get(DomainProfile, "generic")
    db_session.add(DomainProfile(domain_key=domain_key, name=domain_key, supported_formats=["markdown"],
        graph_relations={}, default_capabilities={}, memory_policy=deepcopy(seed.memory_policy)))
    (await db_session.get(KnowledgeScope, sid)).domain_key = domain_key
    await db_session.commit()
    clock = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)}

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    for module in (memory_service, memory_governance, memory_reader):
        monkeypatch.setattr(module, "datetime", FixedClock)
    service = memory_service.MemoryService(db_session)
    first = await service.record({**payload, "evidence_refs": ["policy-source"]})
    mid = first["memory_id"]
    initial = reduce_events(await MemoryEventStore(db_session).replay(sid))
    app = create_app()

    async def sessions():
        yield db_session

    app.dependency_overrides[get_session] = sessions
    async with writer_owner(engine) as owner:
        app.state.writer_lease = owner
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            usage = {"scope_id": sid, "memory_id": mid, "reason": "Reviewed procedure"}
            response = await client.post("/api/memories/usage", json=usage)
            assert response.status_code == 200, response.text
            clock["now"] = datetime(2026, 1, 2, tzinfo=timezone.utc)
            command = {"scope_id": sid, "reason": "Use current decay dynamics", "policy": {"decay_rate": .2}}
            response = await client.post("/api/memories/policy", json=command)
            assert response.status_code == 200, response.text
            snapshot = await MemoryHistory(service).capture(sid, force=True)
            clock["now"] = datetime(2026, 1, 6, tzinfo=timezone.utc)
            response = await client.post("/api/memories/usage", json=usage)
            assert response.status_code == 200, response.text
            events = await MemoryEventStore(db_session).replay(sid)
            accesses = [event for event in events if event["event_type"] == "access"]
            assert [event["payload"]["decay_rate"] for event in accesses] == [.05, .2]
            original_accesses = deepcopy(accesses)
            state = reduce_events(events)
            signal = state["salience"][mid]
            assert signal["access_count"] == 2 and signal["decay_rate"] == .2
            assert signal["salience"] == pytest.approx(1.)
            assert signal["last_access_at"] == signal["reinforced_at"] == clock["now"].isoformat()
            assert state["entries"] == initial["entries"]
            assert {axis: signal[axis] for axis in GOVERNANCE_AXES} == {
                axis: initial["salience"][mid][axis] for axis in GOVERNANCE_AXES}
            sql_state = await db_session.scalar(text(
                "SELECT memory_log_state(:scope, :point)"
            ), {"scope": sid, "point": events[-1]["event_id"]})
            assert sql_state["salience"][str(mid)] == signal
            persisted = await db_session.get(MemorySalience, mid, populate_existing=True)
            assert persisted.salience == pytest.approx(1.) and persisted.decay_rate == .2
            assert persisted.access_count == 2
            restored = await MemoryHistory(service).load(sid)
            assert restored.source == "snapshot_delta"
            assert restored.fingerprint == projection_fingerprint(state)
            assert snapshot["source_events"][-1]["event_type"] == "grant"

            async def candidates(self, manifests, query, limit, kind, session_id):
                return {mid: .9}, [], []

            monkeypatch.setattr(memory_reader.MemoryReader, "_dense", candidates)
            clock["now"] = datetime(2026, 1, 8, tzinfo=timezone.utc)
            recalled = await service.recall(scope_ref=[str(sid)], query="procedure")
            assert recalled["completion_status"] == "complete"
            assert recalled["memories"][0]["match"]["salience"] == pytest.approx(.6)
            assert reduce_events(await MemoryEventStore(db_session).replay(sid))["salience"] == state["salience"]
            response = await client.post("/api/memories/policy", json={**command, "policy": {"decay_rate": .9}})
            assert response.status_code == 200, response.text
            later = reduce_events(await MemoryEventStore(db_session).replay(sid))
            assert later["salience"] == state["salience"] and later["entries"] == initial["entries"]
            expired_signal = await service.recall(scope_ref=[str(sid)], query="procedure")
            assert expired_signal["memories"][0]["match"]["salience"] is None
            rebuilt = await client.post("/api/memories/rebuild", json={"scope_id": sid, "reason": "Verify rate replay"})
            assert rebuilt.status_code == 200, rebuilt.text
            assert all(row["matches_replay"] for row in rebuilt.json()["projections"].values())
            rollback = await client.post("/api/memories/rollback", json={
                "scope_id": sid, "event_point": mid, "reason": "Restore facts without undoing accesses"})
            assert rollback.status_code == 200, rollback.text
            history = await MemoryEventStore(db_session).replay(sid)
            after = reduce_events(history)
            assert after["entries"] == initial["entries"] and after["salience"] == state["salience"]
            assert [event for event in history if event["event_type"] == "access"] == original_accesses
            sql_state = await db_session.scalar(text(
                "SELECT memory_log_state(:scope, :point)"
            ), {"scope": sid, "point": history[-1]["event_id"]})
            assert sql_state["salience"][str(mid)] == after["salience"][mid]
            full = await service.rebuild(sid, actor="management")
            assert all(row["matches_replay"] for row in full.values())
            assert (await service.inspect_projections(sid))["salience"]["matches_replay"]
            profile = await db_session.get(DomainProfile, domain_key, populate_existing=True)
            rollback_rate = profile.memory_policy["decay_rate"]
            clock["now"] = datetime(2026, 1, 9, tzinfo=timezone.utc)
            response = await client.post("/api/memories/usage", json=usage)
            assert response.status_code == 200, response.text
            final_events = await MemoryEventStore(db_session).replay(sid)
            assert final_events[-1]["payload"]["decay_rate"] == rollback_rate
            final = reduce_events(final_events)
            assert final["salience"][mid]["decay_rate"] == rollback_rate
            assert final["salience"][mid]["salience"] == pytest.approx(max(0., 2. - 3 * rollback_rate))
            assert final["entries"] == initial["entries"]
            assert [event for event in final_events if event["event_type"] == "access"][:2] == original_accesses
