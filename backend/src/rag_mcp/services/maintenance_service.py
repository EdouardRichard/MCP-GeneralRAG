"""MaintenanceService: periodic housekeeping for append-only run records.

Implements the RetrievalRun TTL cleanup required by blueprint §20: run state
and trace records are retained for a bounded window (default 7 days, set via
"expires_at") and then purged. Purging is the only code path allowed to
delete "retrieval_runs" rows (the table is otherwise append-only).

005 (T066): the four Agent-orchestration runtime tables are TTL-bounded the
same way — expired "agentic_retrieval_run" rows are purged together with
their cascading "evidence_ledger_entry" / "agent_judgment" /
"context_selection_list" rows. Purging is the only deletion path for these
otherwise append-only tables; unexpired runs and other projects' data are
never touched, and no runtime state is written back to the knowledge base
(FR-011/SC-014, blueprint §20).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_mcp.config import get_settings
from rag_mcp.models.retrieval_run import RetrievalRun
from rag_mcp.models.runtime import RuntimeMaintenanceLog
from rag_mcp.orchestration.models import (
    AgenticRetrievalRun,
    AgentJudgment,
    ContextSelectionList,
    EvidenceLedgerEntry,
)
from rag_mcp.utils.snowflake import generate_id

logger = logging.getLogger(__name__)


async def purge_expired_retrieval_runs(
    session: AsyncSession,
    now: datetime | None = None,
) -> int:
    """Delete retrieval run records whose ``expires_at`` has passed.

    Args:
        session: Async SQLAlchemy session (caller manages transaction scope).
        now: Reference timestamp; defaults to current UTC time. Injectable for
            deterministic testing.

    Returns:
        Number of rows deleted.

    Notes:
        The caller is responsible for committing the transaction. This keeps
        the helper composable inside larger maintenance transactions.
    """
    reference = now or datetime.now(timezone.utc)
    result = await session.execute(
        delete(RetrievalRun).where(RetrievalRun.expires_at < reference)
    )
    deleted = result.rowcount or 0
    if deleted:
        logger.info("Purged %d expired retrieval_runs (before %s)", deleted, reference)
    return deleted


async def purge_expired_agentic_runs(
    session: AsyncSession,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete expired 005 runtime rows in FK-safe order (T066, blueprint §20).

    Order: context_selection_list (FK -> ledger) -> evidence_ledger_entry ->
    agent_judgment -> agentic_retrieval_run. Only rows belonging to runs
    whose ttl_expires_at has passed are removed; unexpired runs and other
    projects' data stay untouched. No knowledge-base or vector-store writes
    happen here (FR-011/SC-014).

    Args:
        session: Async SQLAlchemy session (caller manages transaction scope).
        now: Reference timestamp; defaults to current UTC time. Injectable
            for deterministic testing.

    Returns:
        Per-table deleted row counts.
    """
    reference = now or datetime.now(timezone.utc)
    result = await session.execute(
        select(AgenticRetrievalRun.run_id).where(
            AgenticRetrievalRun.ttl_expires_at < reference
        )
    )
    run_ids = [row[0] for row in result.all()]
    if not run_ids:
        return {"runs": 0, "ledger_entries": 0, "judgments": 0, "selections": 0}

    run_id_strs = [str(run_id) for run_id in run_ids]
    sel = await session.execute(
        delete(ContextSelectionList).where(ContextSelectionList.run_id.in_(run_id_strs))
    )
    led = await session.execute(
        delete(EvidenceLedgerEntry).where(EvidenceLedgerEntry.run_id.in_(run_id_strs))
    )
    jud = await session.execute(
        delete(AgentJudgment).where(AgentJudgment.run_id.in_(run_id_strs))
    )
    runs = await session.execute(
        delete(AgenticRetrievalRun).where(AgenticRetrievalRun.run_id.in_(run_ids))
    )
    counts = {
        "runs": runs.rowcount or 0,
        "ledger_entries": led.rowcount or 0,
        "judgments": jud.rowcount or 0,
        "selections": sel.rowcount or 0,
    }
    logger.info(
        "Purged expired agentic runtime rows (before %s): %s", reference, counts,
    )
    return counts


def compute_expires_at(now: datetime | None = None) -> datetime:
    """FR-019: expires_at = write time + RETRIEVAL_TTL_DAYS (configurable).

    Replaces the former server_default '7 days' constant so the retention
    window is runtime-configuration driven.
    """
    reference = now or datetime.now(timezone.utc)
    settings = get_settings()
    return reference + timedelta(days=int(settings.retrieval_ttl_days))


async def record_ttl_purge(
    session: AsyncSession,
    *,
    purged_retrieval_runs: int = 0,
    purged_agentic_runs: int = 0,
    purged_maintenance_logs: int = 0,
) -> RuntimeMaintenanceLog:
    """Append a TTL purge audit row (FR-016, append-only — only INSERT)."""
    log = RuntimeMaintenanceLog(
        log_id=generate_id(),
        event_type="ttl_purge",
        purged_retrieval_runs=max(0, purged_retrieval_runs),
        purged_agentic_runs=max(0, purged_agentic_runs),
        purged_maintenance_logs=max(0, purged_maintenance_logs),
    )
    session.add(log)
    return log


async def run_ttl_purge(
    session: AsyncSession,
    now: datetime | None = None,
) -> dict[str, int]:
    """Writer maintenance: purge expired rows and audit the counts (T060).

    Purges expired retrieval_runs and 005 agentic rows, then records a
    runtime_maintenance_log row with the counts. Runs on the writer
    management process only (readers never run maintenance, FR-004).
    """
    reference = now or datetime.now(timezone.utc)
    retrieval = await purge_expired_retrieval_runs(session, now=reference)
    agentic = await purge_expired_agentic_runs(session, now=reference)
    maintenance = await _purge_expired_maintenance_logs(session, now=reference)
    await record_ttl_purge(
        session,
        purged_retrieval_runs=retrieval,
        purged_agentic_runs=sum(agentic.values()),
        purged_maintenance_logs=maintenance,
    )
    return {
        "purged_retrieval_runs": retrieval,
        "purged_agentic_runs": sum(agentic.values()),
        "purged_maintenance_logs": maintenance,
    }


async def _purge_expired_maintenance_logs(
    session: AsyncSession, now: datetime | None = None
) -> int:
    """Self-purge old maintenance log rows by the same TTL window."""
    reference = now or datetime.now(timezone.utc)
    settings = get_settings()
    cutoff = reference - timedelta(days=int(settings.retrieval_ttl_days))
    result = await session.execute(
        delete(RuntimeMaintenanceLog).where(RuntimeMaintenanceLog.created_at < cutoff)
    )
    return result.rowcount or 0


class MaintenanceService:
    """Service facade for scheduled maintenance operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def purge_expired_retrieval_runs(
        self,
        now: datetime | None = None,
    ) -> int:
        """Purge expired retrieval runs and commit the transaction."""
        deleted = await purge_expired_retrieval_runs(self._session, now=now)
        await self._session.commit()
        return deleted

    async def purge_expired_agentic_runs(
        self,
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Purge expired 005 runtime rows and commit the transaction (T066)."""
        counts = await purge_expired_agentic_runs(self._session, now=now)
        await self._session.commit()
        return counts


async def resume_promotions(session, *, scopes=None, schedule=None, now=None, service=None):
    """Resume only already human-authorized, undispatched promotion pointers (T075).

    Revalidates scope and current candidate eligibility before dispatching; an
    invalidated candidate is recorded as a failed task and never scheduled. It
    never creates a promotion request for a candidate: a task exists only
    because an explicit writer human request already created it.
    """
    from rag_mcp.models.domain_profile import DomainProfile
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    from rag_mcp.models.knowledge_source import KnowledgeSource
    from rag_mcp.models.memory_projection import MemoryEntry
    from rag_mcp.models.processing_run import ProcessingRun
    from rag_mcp.services.consolidation_adjudicator import candidate_eligibility
    from rag_mcp.services.consolidation_commit import read_evidence
    from rag_mcp.services.memory_event_store import MemoryEventStore
    from rag_mcp.services.memory_policy import MemoryPolicy
    from rag_mcp.services.memory_reducer import reduce_events
    from rag_mcp.services.memory_service import MemoryService

    if get_settings().instance_mode != "writer":
        raise PermissionError("MEMORY_WRITE_UNAVAILABLE")
    if scopes is not None and (not scopes or any(not isinstance(sid, int) or isinstance(sid, bool) or sid <= 0
                                                 for sid in scopes)):
        raise ValueError("MISSING_KNOWLEDGE_SCOPE")
    statement = select(MemoryEntry.knowledge_scope_id).where(MemoryEntry.promotion_pointer.isnot(None)).distinct()
    if scopes is not None:
        statement = statement.where(MemoryEntry.knowledge_scope_id.in_(scopes))
    scope_ids = sorted((await session.execute(statement)).scalars().all())
    service = service or MemoryService(session)
    dispatch = schedule or _default_promotion_schedule
    resumed, failed = [], []
    for scope_id in scope_ids:
        scope = await session.get(KnowledgeScope, scope_id)
        if scope is None or scope.status != "active":
            continue
        profile = await session.get(DomainProfile, scope.domain_key)
        policy = MemoryPolicy.model_validate((profile.memory_policy if profile else None) or {})
        threshold = policy.consolidation.candidate_min_confidence if policy.consolidation else 1.0
        state = reduce_events(await MemoryEventStore(session).replay(scope_id))
        for row in sorted(state["entries"].values(), key=lambda item: item["memory_id"]):
            pointer = row.get("promotion_pointer")
            if not pointer or pointer["status"] != "uploaded":
                continue
            run = await session.get(ProcessingRun, pointer["initial_processing_run_id"])
            source = await session.get(KnowledgeSource, pointer["source_id"])
            if (run is None or run.status != "pending" or source is None or source.status != "uploaded"):
                continue   # already dispatched, published, or otherwise not resumable
            identifiers = {str(reference) for reference in row.get("evidence_refs") or ()}
            facts = await read_evidence(session, identifiers) if identifiers else {}
            eligible, reasons = candidate_eligibility(row, facts, scope_id=scope_id, threshold=threshold)
            if eligible:
                dispatch(pointer["source_id"])
                resumed.append({"task_id": pointer["task_id"], "memory_id": row["memory_id"],
                                "source_id": pointer["source_id"],
                                "initial_processing_run_id": pointer["initial_processing_run_id"]})
            else:
                await service.observe_promotion(source_id=pointer["source_id"], status="failed",
                                                result="MEMORY_CANDIDATE_NOT_ELIGIBLE")
                failed.append({"task_id": pointer["task_id"], "memory_id": row["memory_id"],
                               "source_id": pointer["source_id"],
                               "initial_processing_run_id": pointer["initial_processing_run_id"],
                               "reason": reasons[0] if reasons else "MEMORY_CANDIDATE_NOT_ELIGIBLE"})
    return {"resumed": resumed, "failed": failed}


def _default_promotion_schedule(source_id):
    from rag_mcp.api.knowledge_sources import _schedule_ingestion

    _schedule_ingestion(source_id)


async def purge_expired_memory_runtime(session, now=None):
    from rag_mcp.models.memory_recall_run import MemoryRecallRun
    from rag_mcp.models.session import MemorySession
    if get_settings().instance_mode != "writer":
        raise PermissionError("MEMORY_WRITE_UNAVAILABLE")
    reference = now or datetime.now(timezone.utc)
    audits = await session.execute(delete(MemoryRecallRun).where(MemoryRecallRun.expires_at < reference))
    sessions = await session.execute(delete(MemorySession).where(MemorySession.expires_at < reference))
    return {"audits": audits.rowcount or 0, "sessions": sessions.rowcount or 0}


async def run_memory_maintenance(session, *, scope_ids=None, now=None, service=None):
    from rag_mcp.models.memory_projection import MemoryEntry
    from rag_mcp.services.memory_service import MemoryService
    from rag_mcp.runtime.projection_rebuild import MemoryHistory
    if get_settings().instance_mode != "writer":
        raise PermissionError("MEMORY_WRITE_UNAVAILABLE")
    if scope_ids is not None and (not scope_ids or any(not isinstance(sid, int) or isinstance(sid, bool) or sid <= 0 for sid in scope_ids)):
        raise ValueError("MISSING_KNOWLEDGE_SCOPE")
    reference = now or datetime.now(timezone.utc)
    service = service or MemoryService(session)
    statement = select(MemoryEntry.knowledge_scope_id).where(MemoryEntry.write_status == "complete").distinct()
    if scope_ids is not None:
        statement = statement.where(MemoryEntry.knowledge_scope_id.in_(scope_ids))
    scopes = (await session.execute(statement)).scalars().all()
    result = {"compressed": 0, "archived": 0, "tombstone": 0, "snapshots": 0, "archived_access": 0}
    for sid in scopes:
        rows = (await session.execute(select(MemoryEntry).where(MemoryEntry.knowledge_scope_id == sid,
            MemoryEntry.write_status == "complete", MemoryEntry.status == "active", MemoryEntry.expires_at <= reference))).scalars().all()
        transitions = [(row.memory_id, {"active": "compressed", "compressed": "archived", "archived": "tombstone"}[row.retention_stage]) for row in rows]
        for mid, stage in transitions:
            await service.govern("lifecycle", scope_id=sid, actor="management", memory_id=mid,
                                 retention_stage=stage, reason="Expired memory retention maintenance")
            result[stage] += 1
        history = MemoryHistory(service)
        if await history.capture(sid, now=reference):
            result["snapshots"] += 1
        archive = await history.archive(sid, now=reference)
        result["archived_access"] += archive["access_count"]
    await session.commit()
    result.update(await purge_expired_memory_runtime(session, now=reference))
    await session.commit()
    return result
