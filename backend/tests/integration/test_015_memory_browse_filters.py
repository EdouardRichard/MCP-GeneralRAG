"""T043 backend grounding: the six browse filter dimensions actually narrow.

FR-036 requires six-dimensional filtering. Before this test the browse endpoint
accepted only ``scope_ref``/``limit``/``offset`` and silently ignored the five
filter dimensions, so the UI could send them and get an unfiltered page. This
drives the REAL ASGI app against real PG rows and asserts each dimension narrows
the result set and that ``total`` is the filtered total (not the unfiltered one).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.utils.snowflake import generate_id

INFERENCE_META = {
    "source": "015 browse filter grounding",
    "confidence": 0.8,
    "model_version": "015-filter-v1",
    "time": datetime.now(UTC).isoformat(),
    "supporting_evidence": [],
}


async def _client(session, engine):
    from rag_mcp.api.knowledge_sources import get_session as ks_get_session
    from rag_mcp.api.projects import get_session as projects_get_session
    from rag_mcp.api.runtime_metrics import get_session as metrics_get_session
    from rag_mcp.server import app

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _session():
        async with factory() as candidate:
            yield candidate

    app.dependency_overrides[projects_get_session] = _session
    app.dependency_overrides[ks_get_session] = _session
    app.dependency_overrides[metrics_get_session] = _session
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), app


@pytest.mark.asyncio
async def test_six_dimension_filters_narrow_the_browse_page(db_session, engine):
    sid = generate_id()
    db_session.add(
        KnowledgeScope(
            scope_id=sid,
            name=f"015 filter grounding {sid}",
            slug=f"c015-browse-filter-{sid}",
            scope_type="project",
            domain_key="generic",
        )
    )
    await db_session.commit()

    service = MemoryService(db_session)
    session_a, session_b = str(uuid4()), str(uuid4())
    specs = (
        ("procedural", session_a, "Use an explicit scope for every memory request."),
        ("semantic", session_a, "Release notes stay inside the declared knowledge scope."),
        ("episodic", session_b, "The archive decision was revisited after the dependency slipped."),
    )
    for kind, session_id, content in specs:
        await service.record(
            {
                "scope_id": sid,
                "kind": kind,
                "content": content,
                "provenance": "soft",
                "inference_meta": dict(INFERENCE_META),
                "session_id": session_id,
            }
        )

    client, app = await _client(db_session, engine)
    try:
        async with client:
            base = await client.get("/api/memories", params={"scope_ref": str(sid), "limit": 20})
            assert base.status_code == 200, base.text
            payload = base.json()
            assert payload["total"] == 3, payload
            assert len(payload["memories"]) == 3
            # the response shape must not have gained or lost a body-carrying key set
            assert set(payload) == {"memories", "total", "scope_id"}
            assert all("content_excerpt" in item for item in payload["memories"])

            async def filtered(**params):
                response = await client.get("/api/memories", params={"scope_ref": str(sid), "limit": 20, **params})
                assert response.status_code == 200, response.text
                return response.json()

            by_kind = await filtered(kind="semantic")
            assert by_kind["total"] == 1, by_kind
            assert {item["kind"] for item in by_kind["memories"]} == {"semantic"}

            by_status = await filtered(status="active")
            assert by_status["total"] == 3, by_status
            assert by_status["total"] != 0

            by_provenance = await filtered(provenance="soft")
            assert by_provenance["total"] == 3, by_provenance
            assert await filtered(provenance="hard") == {**by_provenance, "memories": [], "total": 0}

            by_session = await filtered(session_id=session_a)
            assert by_session["total"] == 2, by_session
            assert {item["session_id"] for item in by_session["memories"]} == {session_a}

            # a filter that cannot match must return zero, never the unfiltered page
            assert (await filtered(kind="distilled-nonsense"))["total"] == 0

            # narrowing composes and the total stays the filtered total
            composed = await filtered(kind="procedural", session_id=session_a)
            assert composed["total"] == 1, composed

            # min_salience is a real dimension: 0 keeps everything, 1.0 (max) keeps nothing
            assert (await filtered(min_salience=0))["total"] == 3
            assert (await filtered(min_salience=1))["total"] == 0

            # an unknown domain reference is still rejected with candidates present
            rejected = await client.get("/api/memories", params={"scope_ref": "   ", "limit": 20})
            assert rejected.status_code == 400, rejected.text
            detail = rejected.json()["detail"]
            assert detail["code"] == "MISSING_KNOWLEDGE_SCOPE"
            assert detail.get("candidates"), detail
    finally:
        await client.aclose()
        app.dependency_overrides.clear()
