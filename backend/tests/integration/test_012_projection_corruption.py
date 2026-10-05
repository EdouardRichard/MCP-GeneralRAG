import asyncio
from pathlib import Path

import pytest
from qdrant_client.models import PointStruct
from sqlalchemy import select

from rag_mcp.services.memory_service import MemoryService
from rag_mcp.indexing.memory_vectors import revision_point_id
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["dense", "file", "salience"])
async def test_integrity_detects_real_corruption_and_event_rebuild_repairs_it(db_session, path):
    service = MemoryService(db_session)
    sid, payload = await scope_and_payload(db_session)
    memory = await service.record(payload)
    manifest = await service.projections.current(sid)
    if path == "dense":
        client = service.projections.qdrant._client
        point = (await asyncio.to_thread(client.retrieve, collection_name=manifest.payload["collection"],
            ids=[revision_point_id(sid, manifest.source_event_id, memory["memory_id"])], with_vectors=True))[0]
        vector = [0.] * len(point.vector)
        vector[0] = 1.
        await asyncio.to_thread(client.upsert, collection_name=manifest.payload["collection"], points=[PointStruct(id=point.id, vector=vector, payload=point.payload)], wait=True)
    elif path == "file":
        directory = Path(manifest.payload["root"]) / str(sid) / str(manifest.source_event_id)
        (directory / "unlogged.md").write_text("forged file", encoding="utf-8")
    else:
        # Registry provenance is not an authority source. Do not use it to fill
        # in missing verification of the actual salience-to-entry join.
        from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
        from sqlalchemy import text
        async with db_session.begin_nested():
            await db_session.execute(text("ALTER TABLE memory_salience DISABLE TRIGGER memory_salience_log_parity"))
            await db_session.execute(text("SELECT set_config('rag_memory.reducer_event', :event, true)"), {"event": str(memory["memory_id"])})
            await db_session.execute(text("UPDATE memory_salience SET access_count=999 WHERE memory_id=:mid"), {"mid": memory["memory_id"]})
            await db_session.execute(text("ALTER TABLE memory_salience ENABLE TRIGGER memory_salience_log_parity"))
            report = await service.inspect_projections(sid)
            assert not report["salience"]["matches_replay"]
        await db_session.rollback()
        await service.rebuild(sid, actor="management")
        assert all(row["matches_replay"] for row in (await service.inspect_projections(sid)).values())
        return
    report = await service.inspect_projections(sid)
    assert not report[path]["matches_replay"], f"{path} corruption was accepted as replay-equivalent"
    await service.rebuild(sid, actor="management")
    assert all(row["matches_replay"] for row in (await service.inspect_projections(sid)).values())
