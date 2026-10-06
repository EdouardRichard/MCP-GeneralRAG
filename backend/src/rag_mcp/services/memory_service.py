from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select, text

from rag_mcp.errors import MemoryContentConflictError
from rag_mcp.indexing.qdrant_client import QdrantStore
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_management_audit import MemoryManagementAudit
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
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
