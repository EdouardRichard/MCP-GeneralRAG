"""FastAPI application entry point for RAG MCP Server.

Provides:
- REST management API on management_port (default 8000)
- Health endpoint
- Static file mount for frontend build (production)
- CORS for localhost development
- Lifespan-managed DB engine, shared services, and a periodic TTL cleanup loop
  (blueprint §20) that purges expired RetrievalRun records.

006 Runtime Hardening: the management process is WRITER-ONLY (FR-001) —
`--mode reader` fails loudly (readers run only the read-only MCP via
_run_mcp.py). Startup order (T024): acquire the single-writer lease (FR-002,
refusing write mode when another writer holds it) -> DB engine -> metrics
route -> TTL cleanup loop + lease renewal loop. The GET /runtime/metrics
route is a placeholder until US3 (T062) implements the aggregation endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from rag_mcp.api.middleware import RequestContextMiddleware
from rag_mcp.config import get_settings
from rag_mcp.config.timeout_profiles import validate_timeout_profiles

logger = logging.getLogger(__name__)


def validate_management_mode(mode: str) -> None:
    """FR-001: the management process is writer-only.

    A reader deployment runs only the read-only MCP process; starting the
    management API in reader mode is a deployment error and fails loudly.
    """
    if mode != "writer":
        raise ValueError(
            f"the management process does not support mode {mode!r}: readers "
            f"run only the read-only MCP via _run_mcp.py --mode reader and "
            f"never start a management plane (FR-001/FR-004)"
        )


def _validate_timeout_profiles_or_fail(settings) -> None:
    """T022/FR-021: reject reversed timeout profiles at startup, loudly."""
    errors = validate_timeout_profiles(settings.timeout_profiles)
    if errors:
        raise ValueError(
            "invalid timeout profile configuration: " + "; ".join(errors)
        )


def _validate_provider_config_or_fail(settings) -> None:
    """FR-011/SC-004: reject an invalid Provider configuration at startup.

    The management (writer) process validates the unified Provider run
    configuration before acquiring the lease; no silent fallback to an
    undeclared model is allowed.
    """
    from rag_mcp.providers.factory import validate_provider_config

    result = validate_provider_config(
        settings.providers,
        llm_base_url=settings.llm_base_url,
    )
    if not result.valid:
        raise ValueError(
            "invalid provider configuration: "
            + "; ".join(e.message for e in result.errors)
        )


async def _acquire_writer_lease(settings):
    """Writer startup: register the instance and acquire the lease (FR-002).

    Raises RuntimeError when the lease is held (never a silent downgrade to
    reader); the error carries the current holder's instance_id and expiry.
    """
    from rag_mcp.db import get_session_factory
    from rag_mcp.runtime.instance_registry import InstanceRegistryService
    from rag_mcp.runtime.write_coordinator import (
        LeaseAcquisition,
        PostgresLeaseWriteCoordinator,
    )

    instance_id = uuid.uuid4()
    factory = get_session_factory()
    registry = InstanceRegistryService(factory)
    registration = await registry.register(
        instance_id=instance_id,
        instance_mode="writer",
        process_role="management",
        worker_id=settings.worker_id,
        expiry_window_s=settings.lease_expiry_window_s,
    )
    if not registration.registered:
        raise RuntimeError(
            f"cannot register writer management instance: {registration.error}"
        )

    coordinator = PostgresLeaseWriteCoordinator(factory)
    result = await coordinator.acquire(
        holder_instance_id=instance_id,
        renew_interval_s=settings.lease_renew_interval_s,
        expiry_window_s=settings.lease_expiry_window_s,
    )
    if not result.acquired:
        await registry.deregister(instance_id)
        raise RuntimeError(f"refusing to enter write mode: {result.error}")
    logger.info(
        "writer lease %s acquired (instance %s)",
        result.lease_id, instance_id,
    )
    # holder_instance_id doubles as our instance identity for shutdown.
    return LeaseAcquisition(
        lease_id=result.lease_id,
        acquired=True,
        holder_instance_id=instance_id,
    )


async def _sync_domain_profiles() -> None:
    """Sync builtin domain profiles at startup (007, FR-005/SC-008).

    Failure raises (fails startup loudly) — never a silent degradation to
    hardcoded behaviour.
    """
    from rag_mcp.db import get_session_factory
    from rag_mcp.services.domain_profile_service import DomainProfileService

    factory = get_session_factory()
    async with factory() as session:
        service = DomainProfileService(session)
        repairs = await service.sync_builtin_profiles()
        await session.commit()
        logger.info("domain profile sync complete (%d repair(s))", repairs)


async def _release_writer_lease(lease) -> None:
    """Graceful shutdown: release the lease and deregister the instance."""
    from rag_mcp.db import get_session_factory
    from rag_mcp.runtime.instance_registry import InstanceRegistryService
    from rag_mcp.runtime.write_coordinator import PostgresLeaseWriteCoordinator

    holder = getattr(lease, "holder_instance_id", None)
    try:
        factory = get_session_factory()
        coordinator = PostgresLeaseWriteCoordinator(factory)
        await coordinator.release(lease.lease_id)
        if holder is not None:
            registry = InstanceRegistryService(factory)
            await registry.deregister(holder)
    except Exception:  # noqa: BLE001 - shutdown must proceed
        logger.exception("failed to release writer lease cleanly")


async def _lease_renewal_loop(lease_id: int, renew_interval_s: int, expiry_window_s: int) -> None:
    """Renew the writer lease every renew_interval_s (data-model §3.3)."""
    from rag_mcp.db import get_session_factory
    from rag_mcp.runtime.instance_registry import InstanceRegistryService
    from rag_mcp.runtime.write_coordinator import PostgresLeaseWriteCoordinator

    while True:
        await asyncio.sleep(renew_interval_s)
        try:
            factory = get_session_factory()
            coordinator = PostgresLeaseWriteCoordinator(factory)
            ok = await coordinator.renew(lease_id, expiry_window_s)
            if not ok:
                logger.error(
                    "writer lease %s could not be renewed (released/expired); "
                    "the management process keeps serving read paths but must "
                    "be restarted to re-enter write mode", lease_id,
                )
            else:
                active = await coordinator.get_active_lease()
                if active is not None and active.lease_id == lease_id:
                    await InstanceRegistryService(factory).heartbeat(active.holder_instance_id, expiry_window_s)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("lease renewal failed")


async def _ttl_cleanup_loop(interval_s: int, *, supervisor=None, owner=None) -> None:
    """Periodically purge expired runtime records and run consolidation maintenance.

    Covers the 001 retrieval_runs audit table, the 005 Agent orchestration
    runtime tables (T066) and — from 013 T084 — the automatic idle/volume
    consolidation admission, which always runs the existing housekeeping first.
    """
    from rag_mcp.db import get_session_factory
    from rag_mcp.services.maintenance_service import (
        purge_expired_agentic_runs,
        purge_expired_retrieval_runs,
        run_consolidation_maintenance,
        run_memory_maintenance,
    )

    while True:
        await asyncio.sleep(interval_s)
        factory = get_session_factory()

        async def legacy_housekeeping(factory=factory):
            async with factory() as session:
                await purge_expired_retrieval_runs(session)
                await purge_expired_agentic_runs(session)
                await session.commit()
                await run_memory_maintenance(session)

        try:
            if supervisor is None or owner is None:
                await legacy_housekeeping()
                continue
            await run_consolidation_maintenance(factory, owner, supervisor,
                                                legacy_housekeeping=legacy_housekeeping)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive on transient errors
            logger.exception("TTL cleanup failed")


async def _activity_publish_loop(interval_s: float) -> None:
    """Publish this process's bounded activity snapshot for cross-process checks."""
    from rag_mcp.db import get_session_factory
    from rag_mcp.runtime.activity import publish_activity

    while True:
        await asyncio.sleep(interval_s)
        try:
            factory = get_session_factory()
            async with factory() as session:
                await publish_activity(session)
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("activity publication failed")


def _consolidation_distiller(settings):
    """The writer's real Distiller, or None so rules-only degradation is explicit."""
    try:
        from rag_mcp.agents.memory_distiller import MemoryDistiller
        from rag_mcp.providers.factory import assemble_or_fail

        bundle = assemble_or_fail(settings)
        return MemoryDistiller(bundle.llm) if bundle.llm is not None else None
    except Exception:
        logger.exception("consolidation distiller unavailable; deterministic rules only")
        return None


def _build_supervisor(lease, settings):
    from rag_mcp.api.memory import _service as memory_service_factory
    from rag_mcp.db import get_session_factory
    from rag_mcp.services.consolidation_runtime import ConsolidationSupervisor

    return ConsolidationSupervisor(get_session_factory(), lease,
                                   distiller=_consolidation_distiller(settings),
                                   memory_service_factory=memory_service_factory)


async def _shutdown_recovery() -> None:
    """Final writer recovery while the lease is still valid (T084)."""
    from rag_mcp.db import get_session_factory
    from rag_mcp.services.maintenance_service import recover_promotion_observations

    factory = get_session_factory()
    async with factory() as session:
        await recover_promotion_observations(session)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Writer lifecycle: lease -> engine -> TTL cleanup + renewal loops.

    Startup order per T024: acquire the single-writer lease (fails loudly
    when held), then start the TTL cleanup and lease renewal loops. TTL
    cleanup belongs to the writer management process only (FR-004).
    """
    settings = get_settings()
    validate_management_mode(settings.instance_mode)
    _validate_timeout_profiles_or_fail(settings)
    _validate_provider_config_or_fail(settings)
    # 抢租约 -> 失败即拒启 (no silent degradation, FR-002)
    lease = await _acquire_writer_lease(settings)
    app.state.writer_lease = lease
    # 007: sync builtin domain profiles (drift repair; fails startup on error, FR-005/SC-008)
    await _sync_domain_profiles()
    # 013 T081/T082: the bounded consolidation supervisor is constructed only
    # after a valid writer lease, and the management process publishes its own
    # request-activity snapshot for cross-process automatic admission.
    from rag_mcp.runtime.activity import (
        PUBLISH_INTERVAL_SECONDS,
        publish_activity,
        release_activity,
        set_process_identity,
    )

    set_process_identity(lease.holder_instance_id, process_role="management",
                         instance_mode=settings.instance_mode)
    supervisor = _build_supervisor(lease, settings)
    app.state.consolidation_supervisor = supervisor
    renewal_task = asyncio.create_task(
        _lease_renewal_loop(
            lease.lease_id,
            settings.lease_renew_interval_s,
            settings.lease_expiry_window_s,
        )
    )
    cleanup_task = asyncio.create_task(
        _ttl_cleanup_loop(settings.retrieval_ttl_cleanup_interval_s, supervisor=supervisor, owner=lease)
    )
    activity_task = asyncio.create_task(_activity_publish_loop(PUBLISH_INTERVAL_SECONDS))
    background = (renewal_task, cleanup_task, activity_task)
    try:
        yield
    finally:
        # Stop accepting new runs and settle owned workers before the lease goes.
        try:
            await supervisor.shutdown()
        except Exception:
            logger.exception("failed to stop the consolidation supervisor cleanly")
        for task in background:
            task.cancel()
        for task in background:
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            from rag_mcp.db import get_session_factory

            factory = get_session_factory()
            async with factory() as session:
                await publish_activity(session)
                await session.commit()
        except Exception:
            logger.exception("failed to publish the final activity snapshot")
        try:
            await _shutdown_recovery()
        except Exception:
            logger.exception("final consolidation recovery failed")
        await _release_writer_lease(lease)
        app.state.writer_lease = None
        app.state.consolidation_supervisor = None
        try:
            from rag_mcp.db import get_session_factory

            factory = get_session_factory()
            async with factory() as session:
                await release_activity(session)
                await session.commit()
        except Exception:
            logger.exception("failed to release the activity signal")
        from rag_mcp.db import dispose_engine

        await dispose_engine()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    # 008 (FR-001/FR-007): build the FormatHandler registry at startup. A build
    # failure (missing frozen-native-parser dependency, duplicate format or
    # extension registration) fails startup loudly — there is no silent
    # fallback to the legacy if/elif dispatch chains.
    from rag_mcp.parsers.registry import FormatHandlerRegistry

    FormatHandlerRegistry.build()

    app = FastAPI(
        title="RAG MCP Management API",
        description="AI Engineering RAG MCP Server - Management REST API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}



    # Register API routers
    from rag_mcp.api.knowledge_sources import router as ks_router
    from rag_mcp.api.memory import router as memory_router
    from rag_mcp.api.projects import router as projects_router
    from rag_mcp.api.runtime_metrics import router as runtime_metrics_router
    from rag_mcp.api.sse import router as sse_router

    app.include_router(projects_router)
    app.include_router(ks_router)
    app.include_router(runtime_metrics_router)
    app.include_router(sse_router)
    app.include_router(memory_router)

    # Mount frontend static files if build exists
    frontend_dist = Path(__file__).parent.parent.parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        from fastapi.responses import FileResponse

        @app.get("/memories", include_in_schema=False)
        async def memory_page():
            return FileResponse(frontend_dist / "index.html")

        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="RAG MCP management API server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Management API port (default from MANAGEMENT_PORT, 8000)",
    )
    parser.add_argument(
        "--mode",
        default="writer",
        choices=["writer", "reader"],
        help="Instance mode (reader reserved for 006; writer only for 001)",
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=None,
        help="MCP port (informational; the MCP server runs via backend/_run_mcp.py)",
    )
    args = parser.parse_args()

    # FR-001: the management process is writer-only; refuse reader mode.
    try:
        validate_management_mode(args.mode)
    except ValueError as exc:
        parser.error(str(exc))

    port = args.port or get_settings().management_port
    logger.info("Starting management API (%s mode) on %s:%d", args.mode, args.host, port)
    uvicorn.run("rag_mcp.server:app", host=args.host, port=port)
