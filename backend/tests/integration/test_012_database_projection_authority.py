import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
@pytest.mark.parametrize("table,assignment", [
    ("memory_entries", "status='retired'"),
    ("memory_salience", "access_count=999"),
    ("memory_summary_nodes", "data='[]'::jsonb"),
    ("memory_projection_meta", "payload=jsonb_set(payload,'{state,entries}', '{}'::jsonb)"),
])
async def test_valid_event_guc_cannot_authorize_unlogged_projection_change(db_session, table, assignment):
    sid, payload = await scope_and_payload(db_session)
    memory = await MemoryService(db_session).record(payload)
    await db_session.execute(text("SELECT set_config('rag_memory.reducer_event', :event, true)"),
                             {"event": str(memory["memory_id"])})
    where = "memory_id=:id" if table in {"memory_entries", "memory_salience"} else "knowledge_scope_id=:scope"
    with pytest.raises(DBAPIError, match="replay|authority|immutable"):
        async with db_session.begin_nested():
            await db_session.execute(text(f"UPDATE {table} SET {assignment} WHERE {where}"),
                                     {"id": memory["memory_id"], "scope": sid})


@pytest.mark.asyncio
async def test_database_runtime_roles_have_no_projection_mutation_privileges(db_session):
    roles = (await db_session.execute(text("SELECT rolname FROM pg_roles WHERE rolname IN ('rag_memory_reader','rag_memory_reducer')"))).scalars().all()
    assert set(roles) == {"rag_memory_reader", "rag_memory_reducer"}
    for table in ("memory_events", "memory_entries", "memory_links", "memory_summary_nodes", "memory_salience", "memory_projection_meta", "scope_bindings"):
        for permission in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not await db_session.scalar(text("SELECT has_table_privilege('rag_memory_reader', :table, :permission)"),
                                               {"table": table, "permission": permission})
        assert not await db_session.scalar(text("SELECT has_table_privilege('rag_memory_reader', :table, 'INSERT')"), {"table": table})
    assert not await db_session.scalar(text("SELECT has_table_privilege('rag_memory_reducer','memory_events','UPDATE')"))
    assert not await db_session.scalar(text("SELECT has_table_privilege('rag_memory_reducer','memory_events','DELETE')"))


@pytest.mark.asyncio
async def test_projection_pipeline_executes_with_restricted_database_role(db_session, monkeypatch):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    original = service.projections._upsert
    roles = []
    async def observed(*args, **kwargs):
        roles.append(await db_session.scalar(text("SELECT current_user")))
        return await original(*args, **kwargs)
    monkeypatch.setattr(service.projections, "_upsert", observed)
    await service.record(payload)
    assert roles and set(roles) == {"rag_memory_reducer"}


@pytest.mark.asyncio
async def test_read_queries_use_database_role_without_projection_write_access(db_session, monkeypatch):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    await service.record(payload)
    original = db_session.execute
    roles = []
    async def observed(statement, *args, **kwargs):
        if "memory_projection_meta" in str(statement):
            roles.append((await original(text("SELECT current_user"))).scalar_one())
        return await original(statement, *args, **kwargs)
    monkeypatch.setattr(db_session, "execute", observed)
    await service.recall(scope_ref=[str(sid)])
    await service.start_work(scope_ref=str(sid))
    assert roles and set(roles) == {"rag_memory_reader"}
