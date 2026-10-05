from httpx import ASGITransport, AsyncClient
import pytest

from rag_mcp.server import create_app
from rag_mcp.db import get_session
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


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
