from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select, text

from rag_mcp.errors import MemoryContentConflictError
from rag_mcp.indexing.qdrant_client import QdrantStore
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.knowledge_source import KnowledgeSource
from rag_mcp.models.knowledge_version import KnowledgeVersion
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_management_audit import MemoryManagementAudit
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
from rag_mcp.models.processing_run import ProcessingRun
from rag_mcp.models.session import MemorySession
from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_projection_store import MemoryProjectionStore, ProjectionFailure
from rag_mcp.services.memory_reducer import reduce_events
from rag_mcp.services.memory_validators import (
    MemoryProvenanceValidator,
    check_quota,
    derive_ttl,
    detect_submission,
    redact_submission,
    validate_supersede,
)
from rag_mcp.utils.snowflake import generate_id


def _hard_replacement_command(event, target, validation):
    """Pure adapter called only after the existing record authorization checks."""
    from rag_mcp.services.consolidation_adjudicator import _COMMAND_ISSUER_SEAL, _governed_command

    return _governed_command(event, target=target, validation=validation, _issuer=_COMMAND_ISSUER_SEAL)


class MemoryService:
    def __init__(self, session, projection_store=None, *, embedding_provider=None, qdrant_store=None, projection_root=None):
        self.session = session
        self.projections = projection_store or MemoryProjectionStore(session,
            embedding_provider=embedding_provider or LocalCPUEmbeddingProvider(),
            qdrant_store=qdrant_store, projection_root=projection_root)

    def _ensure_vector_store(self):
        if self.projections.qdrant is None:
            self.projections.qdrant = QdrantStore()

    async def recall(self, **parameters):
        from rag_mcp.services.memory_reader import MemoryReader
        return await MemoryReader(self.session, self.projections).recall(**parameters)

    async def start_work(self, **parameters):
        from rag_mcp.services.memory_reader import MemoryReader
        return await MemoryReader(self.session, self.projections).start_work(**parameters)

    async def govern(self, action, **parameters):
        from rag_mcp.services.memory_governance import MemoryGovernance
        return await MemoryGovernance(self).execute(action, **parameters)

    async def apply_event(self, event_data):
        # Raw caller events are not an authorized memory-write surface.
        raise PermissionError("MEMORY_WRITE_UNAVAILABLE: use validated memory commands")

    async def commit_approved(self, decisions, token, *, runtime, batch, context):
        from rag_mcp.services.consolidation_commit import commit_approved
        return await commit_approved(self, decisions, token, runtime=runtime, batch=batch, context=context)

    async def promotion_candidates(self, *, scope_id, limit=50, offset=0):
        """Derived candidate read model with current promotability (T073).

        Candidates come from authoritative approved markers; every item is
        re-verified against the current corpus anchors so an already marked but
        no longer eligible candidate stays visible for audit without claiming it
        is still promotable.
        """
        from rag_mcp.services.consolidation_adjudicator import candidate_eligibility
        from rag_mcp.services.consolidation_commit import read_evidence
        from rag_mcp.services.memory_policy import MemoryPolicy

        scope = await self.session.get(KnowledgeScope, scope_id)
        if scope is None or scope.status != "active":
            raise ValueError("MISSING_KNOWLEDGE_SCOPE")
        profile = await self.session.get(DomainProfile, scope.domain_key)
        policy = MemoryPolicy.model_validate((profile.memory_policy if profile else None) or {})
        threshold = policy.consolidation.candidate_min_confidence if policy.consolidation else 1.0
        state = reduce_events(await MemoryEventStore(self.session).replay(scope_id))
        marked = [row for row in state["entries"].values() if row.get("candidate_version")]
        identifiers = {str(reference) for row in marked for reference in row.get("evidence_refs") or ()}
        facts = await read_evidence(self.session, identifiers) if identifiers else {}
        items = []
        for row in sorted(marked, key=lambda item: (item.get("observed_at") or "", item["memory_id"]), reverse=True):
            eligible, reasons = candidate_eligibility(row, facts, scope_id=scope_id, threshold=threshold)
            items.append({"memory_id": row["memory_id"], "kind": row.get("kind"),
                          "provenance": row.get("provenance"), "confidence": row.get("confidence"),
                          "promote_candidate_at": row.get("promote_candidate_at"),
                          "candidate_version": row.get("candidate_version"),
                          "evidence_attributions": [dict(item) for item in
                                                    (row.get("candidate_basis") or {}).get("evidence_attributions", ())],
                          "promotable": eligible, "ineligibility_reasons": list(reasons),
                          "promotion_pointer": row.get("promotion_pointer")})
        return {"scope_id": scope_id, "items": items[offset:offset + limit], "total": len(items)}

    async def promote_candidate(self, *, scope_id, memory_id, candidate_version, actor, reason, request_id=None):
        """Explicit human promotion short transaction (T072)."""
        from rag_mcp.services.memory_governance import MemoryGovernance

        return await MemoryGovernance(self).promote(scope_id=scope_id, memory_id=memory_id,
                                                    candidate_version=candidate_version, actor=actor,
                                                    reason=reason, request_id=request_id)

    async def promotion_status(self, *, task_id, scope_id):
        """Stable promotion task report derived from actual facts (T073)."""
        from rag_mcp.models.chunk import Chunk

        if isinstance(task_id, str) and task_id.isdecimal():
            task_id = int(task_id)
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id <= 0:
            raise LookupError("MEMORY_PROMOTION_NOT_FOUND")
        history = await MemoryEventStore(self.session).replay(scope_id)
        request = next((event for event in history if event["event_id"] == task_id
                        and event["event_type"] == "grant"
                        and event["payload"].get("grant_type") in ("promotion_requested", "promotion_observed")), None)
        if request is None:
            raise LookupError("MEMORY_PROMOTION_NOT_FOUND")
        state = reduce_events(history)
        entry = state["entries"].get(request["payload"]["memory_id"]) or {}
        pointer = entry.get("promotion_pointer") or request["payload"]["pointer"]
        source = await self.session.get(KnowledgeSource, pointer["source_id"], populate_existing=True)
        runs = (await self.session.execute(select(ProcessingRun).where(
            ProcessingRun.source_id == pointer["source_id"]).order_by(ProcessingRun.run_id))).scalars().all()
        attempt_run_ids = [run.run_id for run in runs] or list(pointer["attempt_run_ids"])
        published_version_id = None
        if source is not None and source.status == "published":
            published_version_id = await self.session.scalar(
                select(KnowledgeVersion.version_id)
                .join(Chunk, Chunk.version_id == KnowledgeVersion.version_id)
                .where(Chunk.source_id == pointer["source_id"], KnowledgeVersion.status == "published")
                .order_by(KnowledgeVersion.version_number.desc()).limit(1))
        if source is None:
            status = "failed" if pointer["result"] else "accepted"
        elif published_version_id is not None:
            status = "published"
        elif source.status in ("failed", "deleted"):
            status = "failed"
        elif source.status == "processing" or any(run.status == "running" for run in runs):
            status = "processing"
        elif pointer["status"] == "failed" and pointer["result"]:
            status = "failed"
        else:
            status = "uploaded"
        return {"task_id": str(task_id), "memory_id": pointer["memory_id"],
                "candidate_version": pointer["candidate_version"], "source_id": pointer["source_id"],
                "initial_processing_run_id": pointer["initial_processing_run_id"],
                "attempt_run_ids": attempt_run_ids, "status": status,
                "published_version_id": published_version_id, "result": pointer["result"],
                "authority_event_ids": list(pointer["authority_event_ids"])}

    async def observe_promotion(self, *, source_id, status=None, result=None):
        """Append a permanent promotion_observed grant for real attempts (T074).

        Uploaded, processing and failed never report published: the recorded
        status comes from the actual source/run/version facts unless an explicit
        pre-dispatch failure is being recorded. Regular uploads have no
        promotion request and are left untouched. The original request pointer
        is never mutated; a new permanent observation extends its history.
        """
        from rag_mcp.services.memory_governance import MemoryGovernance

        return await MemoryGovernance(self).observe_promotion(source_id=source_id, status=status, result=result)

    async def recover_consolidation(self, token, *, runtime):
        from rag_mcp.services.consolidation_commit import recover_consolidation
        return await recover_consolidation(self, token, runtime=runtime)

    async def record(self, payload):
        scope_id = payload.get("scope_id")
        scope = await self.session.get(KnowledgeScope, scope_id) if isinstance(scope_id, int) else None
        if not scope or scope.status != "active":
            raise ValueError("MISSING_KNOWLEDGE_SCOPE")
        clean = redact_submission(payload)
        validation = await MemoryProvenanceValidator(self.session).validate(clean)
        sanitized = detect_submission(clean)
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:scope)"), {"scope": scope_id})
        profile = await self.session.get(DomainProfile, scope.domain_key)
        policy = profile.memory_policy or {}
        metadata = {key: clean.get(key) for key in (
            "kind", "provenance", "inference_meta", "confidence", "title", "session_id", "agent_id",
            "task_context", "supersedes_memory_id")}
        metadata["evidence_refs"] = sorted(set(clean.get("evidence_refs") or []))
        metadata["tags"] = sorted(set(clean.get("tags") or []))
        digest = hashlib.sha256(sanitized.content.encode()).hexdigest()
        matches = (await self.session.scalars(select(MemoryEntry).where(
            MemoryEntry.knowledge_scope_id == scope_id, MemoryEntry.content_hash == digest
        ).order_by(MemoryEntry.source_event_id, MemoryEntry.memory_id))).all()
        request_id = str(uuid4())
        if matches:
            if any(row.write_status != "complete" for row in matches):
                raise ValueError("MEMORY_WRITE_UNAVAILABLE")
            conflict = next((row for row in matches if row.submission_meta != metadata), None)
            if conflict:
                raise MemoryContentConflictError(conflict.memory_id)
            existing = matches[0]
            return {"memory_id": existing.memory_id, "status": existing.status,
                    "provenance_validation": validation, "injection_flags": existing.injection_flags,
                    "request_id": request_id}
        history = await MemoryEventStore(self.session).replay(scope_id)
        current = await self.projections.current(scope_id)
        if history and (not current or current.source_event_id != history[-1]["event_id"]):
            raise ValueError("MEMORY_WRITE_UNAVAILABLE")
        if clean.get("supersedes_memory_id"):
            target = await self.session.get(MemoryEntry, clean["supersedes_memory_id"])
            validate_supersede({**clean, "target": {"scope_id": target.knowledge_scope_id,
                "status": target.status, "provenance": target.provenance} if target else {}})
        count = await self.session.scalar(select(func.count()).select_from(MemoryEntry).where(
            MemoryEntry.knowledge_scope_id == scope_id, MemoryEntry.status == "active", MemoryEntry.write_status == "complete"
        ))
        check_quota(count, policy.get("per_scope_memory_quota", 5000))
        now = datetime.now(UTC)
        ttl = derive_ttl(clean["kind"], policy)
        identifier = generate_id()
        event_payload = {**metadata, "content_text": sanitized.content, "content_hash": digest,
            "submission_meta": metadata, "status": sanitized.status, "injection_flags": sanitized.injection_flags,
            "provenance_validation": validation, "decay_rate": policy.get("decay_rate", .05),
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
            "expires_at": (now + timedelta(days=ttl)).isoformat() if ttl is not None else None}
        event = MemoryEvent(event_id=identifier, aggregate_id=identifier,
            event_type="revise" if clean.get("supersedes_memory_id") else "assert",
            knowledge_scope_id=scope_id, payload=event_payload, actor="memory_tool", request_id=request_id,
            session_id=clean.get("session_id"), occurred_at=now, valid_from=now,
            authority={"source": "validated_evidence" if clean["provenance"] == "hard" else "inference"},
            scope_meta={"knowledge_scope_id": scope_id}, mutability={"correction": "supersede"},
            provenance_meta=validation, recoverability={"source": "event_log"}, actionability="evidence")
        event_fields = {column.name: getattr(event, column.name) for column in MemoryEvent.__table__.columns if column.name != "created_at"}
        if clean.get('supersedes_memory_id') and target.provenance == 'hard':
            from rag_mcp.services.consolidation_adjudicator import guard_effect

            target_fact = {key: getattr(target, key) for key in (
                'memory_id', 'knowledge_scope_id', 'source_event_id', 'state_event_id', 'content_hash', 'provenance')}
            target_fact['state_event_id'] = target_fact['state_event_id'] or target_fact['source_event_id']
            command = _hard_replacement_command(event_fields, target_fact, validation)
            checked = guard_effect({'operation': 'replace', 'aggregate_id': target.memory_id,
                                    'replacement_id': identifier}, target_fact, command=command)
            if checked.decision != 'accept':
                raise PermissionError('HARD_MEMORY_PROTECTED')
        try:
            async with self.session.begin_nested():
                await MemoryEventStore(self.session).append(event)
                state = reduce_events(await MemoryEventStore(self.session).replay(scope_id))
                self._ensure_vector_store()
                try:
                    await self.projections.materialize(state, scope_id, identifier)
                    integrity = await self.projections.inspect(state, scope_id)
                except ProjectionFailure:
                    raise
                except Exception as error:
                    raise ProjectionFailure("integrity") from error
                if not all(row["matches_replay"] for row in integrity.values()):
                    raise ProjectionFailure("integrity")
                if clean.get("session_id"):
                    session = await self.session.get(MemorySession, clean["session_id"])
                    if session is None:
                        self.session.add(MemorySession(session_id=clean["session_id"], agent_id=clean.get("agent_id") or "unknown",
                            primary_scope_id=scope_id, started_at=now, last_active_at=now, status="active", expires_at=now + timedelta(days=7)))
                    else:
                        session.last_active_at = now
                        session.expires_at = now + timedelta(days=7)
            await self.session.commit()
        except ProjectionFailure as failure:
            if failure.path == "relation":
                await self.session.rollback()
                raise
            # The savepoint restored the previous PG view and left our scoped
            # transaction lock held. Retain the failed command without moving
            # the completed manifest consumed by readers.
            try:
                await MemoryEventStore(self.session).append(MemoryEvent(**event_fields))
                state = reduce_events(await MemoryEventStore(self.session).replay(scope_id))
                await self.projections.retain_failure(state, scope_id, identifier, failure.path)
                await self.session.commit()
            except Exception:
                await self.session.rollback()
                raise
            raise ValueError(f"MEMORY_WRITE_UNAVAILABLE:{failure.path}") from None
        except Exception:
            await self.session.rollback()
            raise
        return {"memory_id": identifier, "status": sanitized.status, "provenance_validation": validation,
                "injection_flags": sanitized.injection_flags, "request_id": request_id}

    async def inspect_projections(self, scope_id):
        self._ensure_vector_store()
        state = reduce_events(await MemoryEventStore(self.session).replay(scope_id))
        return await self.projections.inspect(state, scope_id)

    async def rebuild(self, scope_id, *, actor, reason="management rebuild", since_event_id=None, request_id=None):
        if actor != "management" or not isinstance(scope_id, int) or isinstance(scope_id, bool):
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:scope)"), {"scope": scope_id})
        if since_event_id is not None:
            if not isinstance(since_event_id, int) or isinstance(since_event_id, bool) or since_event_id <= 0:
                raise ValueError("MEMORY_WRITE_UNAVAILABLE: invalid rebuild event point")
            point = await self.session.get(MemoryEvent, since_event_id)
            if point is None:
                raise ValueError("MEMORY_WRITE_UNAVAILABLE: invalid rebuild event point")
            if point.knowledge_scope_id != scope_id:
                raise ValueError("MEMORY_EVIDENCE_SCOPE_MISMATCH")
        history = await MemoryEventStore(self.session).replay(scope_id)
        if not history:
            raise ValueError("MEMORY_WRITE_UNAVAILABLE")
        from rag_mcp.runtime.projection_rebuild import MemoryHistory
        recovered = await MemoryHistory(self).load(scope_id, since_event_id=since_event_id)
        state = recovered.state
        current = await self.projections.current(scope_id)
        completed_event_id = current.source_event_id if current else 0
        pending_event_ids = set((await self.session.execute(select(MemoryProjectionMeta.source_event_id).where(
            MemoryProjectionMeta.knowledge_scope_id == scope_id, MemoryProjectionMeta.projection_type == "pending",
            MemoryProjectionMeta.status == "failed", MemoryProjectionMeta.source_event_id > completed_event_id))).scalars().all())
        self._ensure_vector_store()
        try:
            async with self.session.begin_nested():
                for event in history:
                    payload = event["payload"]
                    if event["event_id"] not in pending_event_ids or event["event_type"] != "grant" or "policy_after" not in payload:
                        continue
                    profile = await self.session.scalar(select(DomainProfile).where(
                        DomainProfile.domain_key == payload["domain_key"]).with_for_update())
                    if profile is None or profile.is_builtin:
                        raise ValueError("MEMORY_WRITE_UNAVAILABLE: pending policy domain unavailable")
                    if profile.memory_policy == payload["policy_after"]:
                        continue
                    if (profile.memory_policy or {}) != payload["policy_before"]:
                        raise ValueError("MEMORY_WRITE_UNAVAILABLE: pending policy conflicts with current profile")
                    profile.memory_policy = payload["policy_after"]
                    await self.session.flush()
                await self.projections.materialize(state, scope_id, history[-1]["event_id"])
                report = await self.projections.inspect(state, scope_id)
                if not all(row["matches_replay"] for row in report.values()):
                    raise ProjectionFailure("integrity")
                versions = await self.projections.versions(scope_id)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        for name, row in report.items():
            row.update(recovery_source=recovered.source, source_event_id=history[-1]["event_id"], knowledge_scope_id=scope_id,
                       scope_id=scope_id, since_event_id=since_event_id,
                       range={"from_event_id": history[0]["event_id"], "through_event_id": history[-1]["event_id"],
                              "since_event_id": since_event_id, "event_count": len(history)},
                       cross_scope_check={"passed": True, "foreign_scope_count": 0, "scope_ids": [scope_id]},
                       schema_version=versions["schema_version"], projection_version=versions["projection_versions"][name])
            if name == "dense":
                row["index_version"] = versions["index_version"]
        audit_request_id = request_id or str(uuid4())
        self.session.add(MemoryManagementAudit(
            request_id=audit_request_id, operation="rebuild", actor=actor,
            knowledge_scope_id=scope_id, reason=reason,
            source_event_id=history[-1]["event_id"], since_event_id=since_event_id,
            result={"scope_id": scope_id, "projections": report},
        ))
        await self.session.commit()
        for row in report.values():
            row["request_id"] = audit_request_id
        return report
