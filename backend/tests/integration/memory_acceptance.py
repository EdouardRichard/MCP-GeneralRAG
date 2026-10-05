from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from rag_mcp.runtime.instance_registry import InstanceRegistryService
from rag_mcp.runtime.write_coordinator import PostgresLeaseWriteCoordinator


@asynccontextmanager
async def writer_owner(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    registry, coordinator = InstanceRegistryService(factory), PostgresLeaseWriteCoordinator(factory)
    identifier = uuid4()
    registered = await registry.register(identifier, "writer", "management", expiry_window_s=300)
    assert registered.registered, registered.error
    lease = await coordinator.acquire(identifier, expiry_window_s=300)
    assert lease.acquired, lease.error
    try:
        yield SimpleNamespace(lease_id=lease.lease_id, holder_instance_id=identifier)
    finally:
        await coordinator.release(lease.lease_id)
        await registry.deregister(identifier)
