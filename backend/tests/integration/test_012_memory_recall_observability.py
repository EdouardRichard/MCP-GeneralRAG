import pytest
import asyncio
from time import monotonic
from sqlalchemy import select, text

from rag_mcp.models.memory_recall_run import MemoryRecallRun
from rag_mcp.services.memory_reader import MemoryReader
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
@pytest.mark.parametrize("slow_stage", ["resolver", "views", "commit", "rollback"])
async def test_entire_recall_obeys_deadline_with_slow_dependency(monkeypatch, slow_stage):
    from rag_mcp.services.scope_resolver import MemoryScopeResolver

    class Session:
        def __init__(self):
            self.audits = []

        async def execute(self, statement):
            return None

        def add(self, audit):
            self.audits.append(audit)

        async def commit(self):
            if slow_stage == "commit":
                await asyncio.sleep(3.2)

        async def rollback(self):
            if slow_stage == "rollback":
                await asyncio.sleep(3.2)

    async def resolve(self, reference):
        if slow_stage == "resolver":
            await asyncio.sleep(3.2)
        return [7]

    async def views(self, scope_ids, **kwargs):
        if slow_stage in {"views", "rollback"}:
            await asyncio.sleep(3.2)
        return {}, {}, [], []

    monkeypatch.setattr(MemoryScopeResolver, "resolve_many", resolve)
    monkeypatch.setattr(MemoryReader, "_views", views)
    session = Session()
    started = monotonic()
    result = await MemoryReader(session, None).recall(scope_ref=["7"])
    assert monotonic() - started < 3.1
    assert result["completion_status"] == "failed"
    assert result["memories"] == []
    assert result["error"]["code"] == "MEMORY_TIMEOUT"
    assert "recall_timeout" in result["memory_notice"]["failed_paths"]
    if slow_stage in {"resolver", "views"}:
        assert session.audits[-1].request_id == result["request_id"]
        assert session.audits[-1].degraded


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
