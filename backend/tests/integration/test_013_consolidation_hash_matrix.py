import asyncio
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_service import MemoryContentConflictError, MemoryService
from rag_mcp.utils.snowflake import generate_id
from tests.integration.consolidation_fixtures import StableEmbedding, create_scope


async def ordinary(session):
    scope = await create_scope(session)
    service = MemoryService(session, embedding_provider=StableEmbedding())
    payload = {'scope_id': scope, 'kind': 'episodic', 'provenance': 'soft', 'content': 'Ordinary protected body',
        'inference_meta': {'source': 'fixture', 'confidence': .8, 'model_version': 'fixture-v1',
            'time': datetime.now(UTC).isoformat(), 'supporting_evidence': []}}
    return service, payload


@pytest.mark.asyncio
@pytest.mark.parametrize('retired', [False, True])
async def test_ordinary_same_hash_dedup_and_metadata_conflict_across_states(db_session, retired):
    service, payload = await ordinary(db_session)
    first = await service.record(payload)
    if retired:
        await service.govern('retire', scope_id=payload['scope_id'], memory_id=first['memory_id'], actor='management', reason='retire fixture')
    before = await MemoryEventStore(db_session).replay(payload['scope_id'])
    again = await service.record(payload)
    assert again['memory_id'] == first['memory_id'] and again['status'] == ('retired' if retired else 'active')
    assert await MemoryEventStore(db_session).replay(payload['scope_id']) == before
    with pytest.raises(MemoryContentConflictError):
        await service.record({**payload, 'title': 'conflicting metadata'})


@pytest.mark.asyncio
async def test_ordinary_pending_duplicate_cannot_be_revived(db_session, monkeypatch):
    service, payload = await ordinary(db_session)
    async def fail(*args, **kwargs):
        raise OSError('external failure')
    monkeypatch.setattr(service.projections, '_materialize_dense', fail)
    with pytest.raises(ValueError, match='MEMORY_WRITE_UNAVAILABLE'):
        await service.record(payload)
    before = await MemoryEventStore(db_session).replay(payload['scope_id'])
    with pytest.raises(ValueError, match='MEMORY_WRITE_UNAVAILABLE'):
        await service.record(payload)
    assert await MemoryEventStore(db_session).replay(payload['scope_id']) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('forgery', ['ordinary', 'flat_distilled', 'v2_marker'])
async def test_immutable_insert_guard_rejects_duplicate_and_forged_exemptions(db_session, forgery):
    service, payload = await ordinary(db_session)
    first = await service.record(payload)
    source = await db_session.get(MemoryEvent, first['memory_id'])
    fields = {c.name: deepcopy(getattr(source, c.name)) for c in MemoryEvent.__table__.columns if c.name != 'created_at'}
    identifier = generate_id()
    fields.update(event_id=identifier, aggregate_id=identifier, request_id='duplicate-guard')
    if forgery != 'ordinary':
        fields['event_type'] = 'consolidate'
        fields['payload']['provenance'] = 'distilled'
    if forgery == 'v2_marker':
        fields['payload'].update(payload_version=2, operation='create')
    await db_session.rollback()
    with pytest.raises(DBAPIError):
        async with db_session.begin():
            db_session.add(MemoryEvent(**fields))
            await db_session.flush()
    assert not await db_session.get(MemoryEvent, identifier)


@pytest.mark.asyncio
async def test_concurrent_ordinary_insert_has_database_hash_race_guard(db_session):
    service, payload = await ordinary(db_session)
    first = await service.record(payload)
    source = await db_session.get(MemoryEvent, first['memory_id'])
    template = {c.name: deepcopy(getattr(source, c.name)) for c in MemoryEvent.__table__.columns if c.name != 'created_at'}
    new_scope = await create_scope(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async def insert():
        identifier = generate_id()
        fields = deepcopy(template)
        fields.update(event_id=identifier, aggregate_id=identifier, knowledge_scope_id=new_scope, request_id=str(identifier))
        fields['scope_meta'] = {'knowledge_scope_id': new_scope}
        try:
            async with factory() as session, session.begin():
                session.add(MemoryEvent(**fields))
                await session.flush()
            return True
        except DBAPIError:
            return False
    assert sorted(await asyncio.gather(insert(), insert())) == [False, True]
    assert len((await db_session.scalars(select(MemoryEvent).where(MemoryEvent.knowledge_scope_id == new_scope))).all()) == 1
