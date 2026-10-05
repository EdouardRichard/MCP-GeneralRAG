import pytest
from sqlalchemy import select, text

from rag_mcp.models.memory_recall_run import MemoryRecallRun
from rag_mcp.services.memory_reader import MemoryReader
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
async def test_database_read_timeout_returns_failure_and_persists_audit(db_session, monkeypatch):
    sid, _ = await scope_and_payload(db_session)
    async def blocked(self, scope_ids, **kwargs):
        await self.session.execute(text("SELECT pg_sleep(10)"))
    monkeypatch.setattr(MemoryReader, "_views", blocked)
    result = await MemoryService(db_session).recall(scope_ref=[str(sid)])
    assert result["completion_status"] == "failed" and result["error"]["code"] == "MEMORY_TIMEOUT"
    audit = await db_session.scalar(select(MemoryRecallRun).where(MemoryRecallRun.request_id == result["request_id"]))
    assert audit.degraded and audit.failed_paths == ["recall_timeout"]
    assert await db_session.scalar(text("SELECT 1")) == 1
