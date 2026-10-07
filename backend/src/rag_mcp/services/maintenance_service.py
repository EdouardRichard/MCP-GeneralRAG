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
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.retrieval_run import RetrievalRun
from rag_mcp.models.runtime import RuntimeMaintenanceLog
from rag_mcp.orchestration.models import (
    AgenticRetrievalRun,
    AgentJudgment,
    ContextSelectionList,
    EvidenceLedgerEntry,
)
from rag_mcp.runtime.activity import get_runtime_activity
from rag_mcp.services.memory_policy import MemoryPolicy
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
    """Resumption dispatch goes through the unified tracked scheduling path (T084).

    Phase 6 dispatched promotion resumption with a raw fire-and-forget task that
    no automatic-admission check could observe. It now shares the single
    activity-visible ingestion scheduling entry point.
    """
    from rag_mcp.runtime.scheduling import schedule_ingestion

    schedule_ingestion(source_id)


#: The only provider of trusted ``support_maintenance`` contexts is registered by
#: writer governance (T059/T060). It is never constructed from request bodies,
#: model output or ordinary maintenance code.
_SUPPORT_MAINTENANCE_SOURCE = None


def register_support_maintenance_source(source):
    """Register the trusted writer hook that yields ``(scope_id, context)`` pairs."""
    global _SUPPORT_MAINTENANCE_SOURCE
    _SUPPORT_MAINTENANCE_SOURCE = source
    return source


async def run_consolidation_maintenance(session_factory, owner, supervisor, *, scopes=None, activity=None,
                                        now=None, legacy_housekeeping=None, support_requests=None):
    """Writer maintenance tick for consolidation (T084/T086).

    Order is fixed: the existing TTL/recovery/purge work runs first, then the
    *current* automatic conditions are re-verified (policy/config, live writer
    lease, real eligible unconsumed pending count, idle_seconds, no foreground/
    ingestion/rebuild activity, fresh cross-process observation) before any
    automatic admission. Manual runs bypass idle only. Busy/full/capacity and
    stale hints are discarded with a reason — never retained for a later tick.

    Returns a per-scope report of admission, skip reasons and the honest purge
    count (``purged_consolidation_observations`` counts deleted observation
    rows, which is the unit the frozen ``purged_consolidation_runs`` column
    actually stores).
    """
    from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
    from rag_mcp.orchestration.consolidation_pipeline import pending_input_count
    from rag_mcp.runtime.activity import (
        REASON_IDLE_INSUFFICIENT,
        admission_activity_reason,
        collect_peer_volume_hints,
        drain_volume_hints,
        observe_peers,
        process_identity,
    )
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, ConsolidationRuntimeError

    activity = activity or get_runtime_activity()
    report = {'purged_consolidation_observations': 0, 'promotions_recovered': 0, 'admitted': [],
              'skipped': [], 'thresholds': {},
              'activity': {'foreground_active': 0, 'ingestion_active': 0, 'rebuild_active': 0,
                           'peers': 0, 'reason': None, 'idle_seconds': None}}
    if legacy_housekeeping is not None:
        await legacy_housekeeping()

    # 1. Guarded 7-day audit TTL purge: never deletes authority, valid links or
    #    active eligibility, and is audited by its own maintenance log row.
    try:
        async with session_factory() as session:
            report['purged_consolidation_observations'] = await ConsolidationRuntime(
                session, owner=owner).purge_expired_observations()
    except ConsolidationRuntimeError as error:
        report['skipped'].append({'scope_id': None, 'trigger': 'maintenance', 'reason': error.code})
        return report

    # 2. Recovery: append real promotion outcomes that were missed by an
    #    interrupted ingestion attempt or a shutdown, so a completed attempt is
    #    never reported as merely 'uploaded'.
    try:
        async with session_factory() as session:
            report['promotions_recovered'] = await recover_promotion_observations(session)
    except Exception:
        logger.exception('promotion observation recovery failed')

    # 3. Current cross-process activity observation (own + peers).
    identity = process_identity()
    async with session_factory() as session:
        peers = await observe_peers(session, exclude_instance_id=identity[0])
    own = activity.snapshot()
    idle_seconds = activity.idle_seconds()
    activity_reason = admission_activity_reason(own=own, peers=peers)
    report['activity'] = {'foreground_active': own.foreground_active,
                          'ingestion_active': own.ingestion_active, 'rebuild_active': own.rebuild_active,
                          'peers': len(peers), 'reason': activity_reason, 'idle_seconds': idle_seconds}

    # 4. Necessary writer support maintenance: a trusted hook constructs the
    #    support_maintenance context. It shares the same eligibility, lease,
    #    fence, capacity and worker bound, runs even while the ordinary switches
    #    are false, and is never disguised as an ordinary trigger.
    requests = list(support_requests or ())
    if not requests and _SUPPORT_MAINTENANCE_SOURCE is not None:
        try:
            async with session_factory() as session:
                requests = list(await _SUPPORT_MAINTENANCE_SOURCE(session) or ())
        except Exception:
            logger.exception('support maintenance hook failed')
    for scope_id, context in requests:
        try:
            token = await supervisor.submit(scope_id, trigger='support_maintenance', actor='management',
                                            context=context)
        except ConsolidationRuntimeError as error:
            report['skipped'].append({'scope_id': scope_id, 'trigger': 'support_maintenance',
                                      'reason': error.code})
        else:
            report['admitted'].append({'scope_id': scope_id, 'run_id': str(token.run_id),
                                       'trigger': 'support_maintenance'})

    # 5. Automatic idle/volume: every condition is re-checked against current
    #    authority. Hints are single-shot nudges; a rejection discards one.
    hints = set(drain_volume_hints()) | set(collect_peer_volume_hints(peers))
    if scopes is None:
        async with session_factory() as session:
            discovered = (await session.execute(select(MemoryProjectionMeta.knowledge_scope_id).where(
                MemoryProjectionMeta.projection_type == 'manifest',
                MemoryProjectionMeta.status == 'complete').distinct().limit(64))).scalars().all()
        candidates = set(discovered)
    else:
        candidates = set(scopes)
    candidates |= hints

    reference = now
    for scope_id in sorted(candidates):
        trigger = 'volume' if scope_id in hints else 'idle'
        async with session_factory() as session:
            scope = await session.get(KnowledgeScope, scope_id)
            profile = await session.get(DomainProfile, scope.domain_key) if scope is not None else None
            policy = MemoryPolicy.model_validate((profile.memory_policy if profile else None) or {})
        if scope is None or scope.status != 'active':
            _skip(report, scope_id, trigger, 'MISSING_KNOWLEDGE_SCOPE')
            continue
        if not policy.consolidation_enabled:
            _skip(report, scope_id, trigger, 'CONSOLIDATION_DISABLED')
            continue
        if policy.consolidation is None:
            _skip(report, scope_id, trigger, 'CONSOLIDATION_CONFIGURATION_REQUIRED')
            continue
        if activity_reason is not None:
            _skip(report, scope_id, trigger, activity_reason)
            continue
        if idle_seconds < policy.consolidation.idle_seconds:
            _skip(report, scope_id, trigger, REASON_IDLE_INSUFFICIENT)
            continue
        async with session_factory() as session:
            runtime = ConsolidationRuntime(session, owner=owner)
            current = await runtime.read_snapshot(scope_id)
            moment = reference or await runtime._clock()
            eligible = pending_input_count(current, now=moment)
        report['thresholds'][str(scope_id)] = {'eligible': eligible,
                                               'threshold': policy.consolidation.volume_threshold}
        if trigger == 'volume' and eligible < policy.consolidation.volume_threshold:
            # The hint was stale: it is invalidated, not queued for later.
            _skip(report, scope_id, trigger, 'below_volume_threshold')
            continue
        if eligible < 1:
            _skip(report, scope_id, trigger, 'no_pending_input')
            continue
        try:
            token = await supervisor.submit(scope_id, trigger=trigger, actor='maintenance')
        except ConsolidationRuntimeError as error:
            _skip(report, scope_id, trigger, error.code)
        else:
            report['admitted'].append({'scope_id': scope_id, 'run_id': str(token.run_id),
                                       'trigger': trigger})
    return report


def _skip(report, scope_id, trigger, reason):
    report['skipped'].append({'scope_id': scope_id, 'trigger': trigger, 'reason': reason})


async def recover_promotion_observations(session):
    """Append missing real promotion outcomes (T084 recovery/shutdown path)."""
    from rag_mcp.models.knowledge_source import KnowledgeSource
    from rag_mcp.models.memory_projection import MemoryEntry
    from rag_mcp.models.processing_run import ProcessingRun
    from rag_mcp.services.memory_event_store import MemoryEventStore
    from rag_mcp.services.memory_service import MemoryService

    if get_settings().instance_mode != "writer":
        raise PermissionError("MEMORY_WRITE_UNAVAILABLE")
    service = MemoryService(session)
    rows = (await session.execute(select(MemoryEntry.knowledge_scope_id, MemoryEntry.promotion_pointer)
                                  .where(MemoryEntry.promotion_pointer.isnot(None)))).all()
    recovered = 0
    for scope_id, pointer in rows:
        source_id = (pointer or {}).get('source_id')
        if source_id is None:
            continue
        if await session.get(KnowledgeSource, source_id) is None:
            continue
        runs = (await session.execute(select(ProcessingRun.run_id).where(
            ProcessingRun.source_id == source_id))).scalars().all()
        if not runs:
            continue
        history = await MemoryEventStore(session).replay(scope_id)
        request = next((event for event in reversed(history) if event['event_type'] == 'grant'
                        and event['payload'].get('grant_type') == 'promotion_requested'
                        and event['payload'].get('source_id') == source_id), None)
        if request is None:
            continue
        real = await service.promotion_status(task_id=request['event_id'], scope_id=scope_id)
        recorded_attempts = [str(item) for item in (pointer or {}).get('attempt_run_ids', [])]
        real_attempts = [str(item) for item in real['attempt_run_ids']]
        if (pointer or {}).get('status') == real['status'] and recorded_attempts == real_attempts:
            continue
        await service.observe_promotion(source_id=source_id)
        recovered += 1
    return recovered


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
    from rag_mcp.runtime.projection_rebuild import MemoryHistory
    from rag_mcp.services.memory_service import MemoryService
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
