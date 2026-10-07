"""Shared Phase 7 (T077-T089) fixtures: bounded supervisor wiring, spies and helpers."""
from __future__ import annotations

import asyncio
import threading
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.services.consolidation_runtime import ConsolidationSupervisor
from rag_mcp.utils.snowflake import generate_id


class SpyResult:
    """Minimal AgentResult shape consumed by ``propose``."""

    def __init__(self, output, *, degraded=False, schema_valid=True, error=None):
        self.output, self.degraded, self.schema_valid, self.error = output, degraded, schema_valid, error


class FakeClock:
    """Deterministic monotonic clock for idle-window assertions."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def quiet_tracker(clock, *, idle=120.0):
    """A tracker whose idle window already satisfies the default policy."""
    from rag_mcp.runtime.activity import RuntimeActivity

    tracker = RuntimeActivity(monotonic=clock)
    clock.now += idle
    return tracker


class SpyDistiller:
    """Offline stand-in for MemoryDistiller; records real provider entries.

    ``gate`` blocks the synchronous worker thread (so an actual provider slot
    stays occupied) until the test releases it.
    """

    model_and_version = 'spy-distiller-v1'

    def __init__(self, package=None, *, gate: threading.Event | None = None):
        self.package = {'proposals': []} if package is None else package
        self.gate = gate
        self.calls = []
        self.entered = threading.Event()

    def run(self, data):
        self.calls.append(data)
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(60), 'distiller gate was never released'
        return SpyResult(self.package)


def session_factory_for(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def supervisor_for(engine, owner, **options) -> ConsolidationSupervisor:
    """A supervisor wired to the isolated stores with the deterministic embedding.

    Production wires ``memory_service_factory`` to the management API's real
    provider bundle; tests use the same shapes without loading bge-m3.
    """
    from rag_mcp.services.memory_service import MemoryService
    from tests.integration.consolidation_fixtures import StableEmbedding

    options.setdefault('memory_service_factory',
                       lambda session: MemoryService(session, embedding_provider=StableEmbedding()))
    return ConsolidationSupervisor(session_factory_for(engine), owner, **options)


async def settle(supervisor, scope_id, timeout=240):
    """Wait for the scope's owned worker to finish (it never raises)."""
    task = supervisor.worker_task(scope_id)
    if task is None:
        for _ in range(int(timeout * 20)):
            if supervisor.active_run(scope_id) is None:
                return
            await asyncio.sleep(.05)
        raise AssertionError('no consolidation worker settled for scope')
    await asyncio.wait_for(asyncio.shield(task), timeout)


async def scope_with_policy(session, *, policy=None, enabled=True):
    """Domain profile + active scope with an explicit consolidation policy."""
    key = '013-p7-' + uuid4().hex
    session.add(DomainProfile(domain_key=key, name=key, supported_formats=['markdown'], graph_relations={},
                              default_capabilities={}, is_builtin=False,
                              memory_policy=({'consolidation_enabled': enabled, 'consolidation': {}}
                                             if policy is None else policy)))
    await session.flush()
    scope = KnowledgeScope(scope_id=generate_id(), scope_type='public', slug=key, name=key, domain_key=key)
    session.add(scope)
    await session.commit()
    return scope.scope_id


async def episodes(session, scope_id, count=1):
    """Real active episodic inputs (commits through the ordinary write path)."""
    from rag_mcp.services.memory_service import MemoryService
    from tests.integration.consolidation_fixtures import StableEmbedding, recorded_episode

    service = MemoryService(session, embedding_provider=StableEmbedding())
    identifiers = []
    for index in range(count):
        recorded = await recorded_episode(service, scope_id, f'Phase 7 observation {uuid4().hex} {index}')
        identifiers.append(recorded['memory_id'])
    return identifiers


async def run_maintenance(engine, owner, supervisor, **options):
    from rag_mcp.services.maintenance_service import run_consolidation_maintenance

    return await run_consolidation_maintenance(session_factory_for(engine), owner, supervisor, **options)


async def reset_activity_state(db_session):
    """Hermetic per-test activity state: process counters, hints and signals.

    The activity signal table is operational state in a shared isolated DB, so a
    leftover row from an earlier (possibly failed) run must never be read as a
    live peer observation.
    """
    from sqlalchemy import text

    from rag_mcp.runtime.activity import get_runtime_activity, reset_peer_volume_cursor

    tracker = get_runtime_activity()
    tracker.reset()
    reset_peer_volume_cursor()
    await db_session.execute(text('DELETE FROM runtime_activity_signals'))
    await db_session.commit()
