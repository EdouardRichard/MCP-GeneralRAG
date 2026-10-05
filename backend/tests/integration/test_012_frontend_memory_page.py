from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient


def test_frontend_memory_page_and_api_exist():
    root = Path(__file__).parents[3] / "frontend/src"
    assert (root / "pages/MemoriesPage.tsx").exists()
    assert (root / "api/memories.ts").exists()


@pytest.mark.asyncio
async def test_production_memory_route_and_api_empty_error_states(db_session):
    from rag_mcp.server import create_app
    from rag_mcp.db import get_session
    from tests.integration.test_012_live_reader import scope_and_payload
    assert (Path(__file__).parents[3] / "frontend/dist/index.html").exists(), "build the real frontend before acceptance"
    app = create_app()
    async def sessions():
        yield db_session
    app.dependency_overrides[get_session] = sessions
    sid, _ = await scope_and_payload(db_session)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        page = await client.get("/memories")
        assert page.status_code == 200, "production memory deep link cannot load the React application"
        assert 'id="root"' in page.text and 'type="module"' in page.text
        empty = await client.get("/api/memories", params={"scope_ref": str(sid)})
        assert empty.status_code == 200 and empty.json()["memories"] == []
        missing = await client.get("/api/memories", params={"scope_ref": "unknown-scope-for-012"})
        assert missing.status_code == 400 and missing.json()["detail"]["code"] == "MISSING_KNOWLEDGE_SCOPE"
        assert (await client.get("/api/memories")).status_code == 422
        assert (await client.get("/api/unknown")).status_code == 404
