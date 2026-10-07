"""Unified, activity-visible scheduling for ingestion and rebuild work (013 T082/T084).

Phase 6 scheduled ingestion with a raw fire-and-forget ``create_task`` that no
automatic-admission check could observe. Every ingestion/rebuild scheduling
entry point (uploads, reprocess, promotion resumption, crash recovery) now goes
through this module, which:

- counts the *scheduled* task from the moment it is created (before the
  coroutine starts), not just while it happens to be running;
- releases that count in a ``finally`` so failures and cancellations cannot
  pin the process busy forever;
- keeps the existing ``INGESTION_BACKGROUND=false`` semantics unchanged.
"""

from __future__ import annotations

import asyncio
import logging

from rag_mcp.config import get_settings
from rag_mcp.runtime.activity import get_runtime_activity

logger = logging.getLogger(__name__)


def schedule_ingestion(source_id: int, *, graph_ready: bool = False, retry: bool = False,
                       initial_run_id: int | None = None) -> bool:
    """Schedule real ingestion work as an activity-tracked background task."""
    from rag_mcp.api.knowledge_sources import _run_ingestion

    if not get_settings().ingestion_background:
        logger.info("Background ingestion disabled; source %s stays 'uploaded'", source_id)
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No running event loop; skipping background ingestion")
        return False
    tracker = get_runtime_activity()
    tracker.begin('ingestion')
    try:
        loop.create_task(_tracked(_run_ingestion, source_id, graph_ready=graph_ready, retry=retry,
                                  initial_run_id=initial_run_id))
    except BaseException:
        tracker.end('ingestion')
        raise
    logger.info("Scheduled ingestion for source %s", source_id)
    return True


async def _tracked(runner, source_id, *, graph_ready, retry, initial_run_id) -> None:
    try:
        await runner(source_id, graph_ready=graph_ready, retry=retry, initial_run_id=initial_run_id)
    finally:
        # Failure, cancellation and success all release the scheduled-work count.
        get_runtime_activity().end('ingestion')
