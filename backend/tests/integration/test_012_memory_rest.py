from httpx import ASGITransport, AsyncClient
import pytest

from rag_mcp.server import create_app
from rag_mcp.db import get_session
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
async def test_custom_policy_rest_update_is_audited_and_lease_loss_refuses_mutation(db_session, engine):
    from uuid import uuid4
    from sqlalchemy import select, func
    from rag_mcp.models.domain_profile import DomainProfile
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    from rag_mcp.models.memory_event import MemoryEvent
    from rag_mcp.runtime.write_coordinator import PostgresLeaseWriteCoordinator
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from tests.integration.memory_acceptance import writer_owner
    sid, payload = await scope_and_payload(db_session)
    key = "policy-" + uuid4().hex
    seed = await db_session.get(DomainProfile, "generic")
    db_session.add(DomainProfile(domain_key=key, name=key, supported_formats=["markdown"], graph_relations={},
        default_capabilities={}, memory_policy=seed.memory_policy))
    (await db_session.get(KnowledgeScope, sid)).domain_key = key
    await db_session.commit()
    service = MemoryService(db_session)
    first = await service.record(payload)
    before = await service.start_work(scope_ref=str(sid))
    app = create_app()
    async def sessions():
        yield db_session
    app.dependency_overrides[get_session] = sessions
    async with writer_owner(engine) as owner:
        app.state.writer_lease = owner
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            command = {"scope_id": sid, "reason": "Tune the custom domain", "policy": {"decay_rate": .07, "per_scope_memory_quota": 1}}
            response = await client.post("/api/memories/policy", json=command)
            assert response.status_code == 200, response.text
            data = response.json()
            event = await db_session.get(MemoryEvent, data["event_id"])
            assert event.event_type == "grant" and event.payload["domain_key"] == key
            assert event.payload["policy_after"]["decay_rate"] == .07
            assert event.payload["policy_before"]["decay_rate"] == .05
            assert (await client.get("/api/memories/policy", params={"scope_ref": str(sid)})).json()["policy"]["per_scope_memory_quota"] == 1
            assert (await service.start_work(scope_ref=str(sid)))["package_fingerprint"] != before["package_fingerprint"]
            with pytest.raises(ValueError, match="MEMORY_QUOTA_EXCEEDED"):
                await service.record({**payload, "content": "Another procedure"})
            await db_session.rollback()
            invalid = await client.post("/api/memories/policy", json={**command, "policy": {"decay_rate": -1}})
            assert invalid.status_code == 422
            retired = await client.post("/api/memories/retire", json={"scope_id": sid, "memory_id": first["memory_id"], "reason": "obsolete"})
            assert retired.status_code == 200, retired.text
            assert (await service.recall(scope_ref=[str(sid)]))["memories"] == []
            restored = await client.post("/api/memories/rollback", json={"scope_id": sid, "event_point": first["memory_id"], "reason": "human restoration"})
            assert restored.status_code == 200, restored.text
            rebuilt = await client.post("/api/memories/rebuild", json={"scope_id": sid, "reason": "verify derived state"})
            assert rebuilt.status_code == 200 and all(row["matches_replay"] for row in rebuilt.json()["projections"].values())
            before_count = await db_session.scalar(select(func.count()).select_from(MemoryEvent).where(MemoryEvent.knowledge_scope_id == sid))
            await db_session.commit()
            await PostgresLeaseWriteCoordinator(async_sessionmaker(engine, expire_on_commit=False)).release(owner.lease_id)
            refused = await client.post("/api/memories/policy", json=command)
            assert refused.status_code == 503
            assert await db_session.scalar(select(func.count()).select_from(MemoryEvent).where(MemoryEvent.knowledge_scope_id == sid)) == before_count


@pytest.mark.asyncio
async def test_management_browse_requires_explicit_scope_and_returns_safe_ids(db_session):
    app = create_app()
    async def sessions():
        yield db_session
    app.dependency_overrides[get_session] = sessions
    sid, payload = await scope_and_payload(db_session)
    result = await MemoryService(db_session).record({**payload, "title": "password=privatecredential"})
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        scopes = await client.get("/api/memories/scopes")
        assert scopes.status_code == 200, "management memory router is not registered"
        assert any(row["scope_id"] == str(sid) for row in scopes.json()["items"])
        assert (await client.get("/api/memories")).status_code == 422
        response = await client.get("/api/memories", params={"scope_ref": str(sid)})
        assert response.status_code == 200
        row = response.json()["memories"][0]
        assert row["memory_id"] == str(result["memory_id"])
        assert row["knowledge_scope_id"] == str(sid)
        assert row["projection_status"] == "complete" and "privatecredential" not in response.text
        assert all(key in row for key in ("valid_from", "valid_to", "evidence_refs", "injection_flags"))
        other, _ = await scope_and_payload(db_session)
        empty = await client.get("/api/memories", params={"scope_ref": str(other)})
        assert empty.json()["memories"] == []
        failed = await client.get("/api/memories", params={"scope_ref": "absent-memory-scope"})
        assert failed.status_code == 400 and failed.json()["detail"]["code"] == "MISSING_KNOWLEDGE_SCOPE"


@pytest.mark.asyncio
async def test_management_mutations_require_live_writer_lease(db_session):
    app = create_app()
    async def sessions():
        yield db_session
    app.dependency_overrides[get_session] = sessions
    sid, _ = await scope_and_payload(db_session)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/memories/rollback", json={"scope_id": sid, "event_point": 1, "reason": "human correction"})
        assert response.status_code == 503, "a process without writer ownership can mutate memory"
        assert response.json()["detail"]["code"] == "MEMORY_WRITE_UNAVAILABLE"
