import pytest
import json
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


async def retained_failed_state(session, monkeypatch):
    from rag_mcp.services.memory_event_store import MemoryEventStore
    from rag_mcp.services.memory_reducer import reduce_events

    sid, payload = await scope_and_payload(session)
    service = MemoryService(session)

    async def unavailable(*args):
        raise OSError("injected external failure")

    monkeypatch.setattr(service.projections, "_materialize_dense", unavailable)
    with pytest.raises(ValueError, match="MEMORY_WRITE_UNAVAILABLE"):
        await service.record(payload)
    history = await MemoryEventStore(session).replay(sid)
    return service, sid, reduce_events(history), history[-1]["event_id"]


@pytest.mark.asyncio
async def test_valid_reducer_cannot_publish_failed_state_through_runtime_upsert(db_session, monkeypatch):
    from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
    from rag_mcp.services.memory_reducer import projection_fingerprint

    service, sid, state, event = await retained_failed_state(db_session, monkeypatch)
    with pytest.raises(PermissionError, match="publication|verification"):
        await service.projections._upsert(state, sid, event, MemoryProjectionMeta, {
            "projection_id": f"current:{sid}", "projection_type": "manifest", "status": "complete",
            "knowledge_scope_id": sid, "source_event_id": event, "fingerprint": projection_fingerprint(state),
            "payload": {"state": state.export(), "collection": "forged", "root": "/forged", "dense_revision": event},
        }, "projection_id")


@pytest.mark.asyncio
@pytest.mark.parametrize("publication", ["manifest", "relation"])
async def test_legal_reducer_role_and_event_do_not_authorize_unverified_completion(db_session, monkeypatch, publication):
    from rag_mcp.services.memory_reducer import projection_fingerprint

    service, sid, state, event = await retained_failed_state(db_session, monkeypatch)
    await service.projections._authorize(state, sid, event)
    with pytest.raises(DBAPIError, match="publication|verification"):
        async with db_session.begin_nested():
            if publication == "relation":
                await db_session.execute(text("UPDATE memory_entries SET write_status='complete' WHERE knowledge_scope_id=:scope"), {"scope": sid})
            else:
                await db_session.execute(text("INSERT INTO memory_projection_meta "
                    "(projection_id,projection_type,status,knowledge_scope_id,source_event_id,fingerprint,payload) "
                    "VALUES (:id,'manifest','complete',:scope,:event,:fingerprint,CAST(:payload AS jsonb))"),
                    {"id": f"current:{sid}", "scope": sid, "event": event, "fingerprint": projection_fingerprint(state),
                     "payload": json.dumps({"state": state.export(), "collection": "forged", "root": "/forged", "dense_revision": event})})


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["collection", "root", "dense_revision", "fingerprint"])
async def test_verified_materialization_cannot_publish_forged_descriptors(db_session, monkeypatch, field):
    from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
    from rag_mcp.services.memory_event_store import MemoryEventStore

    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    original = service.projections._upsert

    async def forged(state, scope, event, model, values, key, **kwargs):
        if model is MemoryProjectionMeta and values["projection_type"] == "manifest":
            values = {**values, "payload": {**values["payload"]}}
            if field == "fingerprint":
                values[field] = "f" * 64
            else:
                values["payload"][field] = event + 1 if field == "dense_revision" else "forged"
        return await original(state, scope, event, model, values, key, **kwargs)

    monkeypatch.setattr(service.projections, "_upsert", forged)
    with pytest.raises(ValueError, match="MEMORY_WRITE_UNAVAILABLE"):
        await service.record(payload)
    assert await service.projections.current(sid) is None
    assert len(await MemoryEventStore(db_session).replay(sid)) == 1
    assert (await service.recall(scope_ref=[str(sid)]))["memories"] == []


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
    with pytest.raises(DBAPIError, match="replay|authority|immutable|publication|verification"):
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
    assert not await db_session.scalar(text("SELECT has_table_privilege('rag_memory_reducer','memory_projection_receipts','INSERT')"))


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
