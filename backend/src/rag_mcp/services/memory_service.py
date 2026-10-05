from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, text

from rag_mcp.errors import MemoryContentConflictError
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_projection_store import MemoryProjectionStore, ProjectionFailure
from rag_mcp.services.memory_reducer import reduce_events
from rag_mcp.services.memory_validators import redact_submission, detect_submission
from rag_mcp.services.memory_validators import MemoryProvenanceValidator, check_quota, derive_ttl, validate_supersede
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.models.session import MemorySession
from rag_mcp.indexing.qdrant_client import QdrantStore
from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider
from rag_mcp.utils.snowflake import generate_id


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
        existing = await self.session.scalar(select(MemoryEntry).where(
            MemoryEntry.knowledge_scope_id == scope_id, MemoryEntry.content_hash == digest
        ))
        request_id = str(uuid4())
        if existing:
            if existing.write_status != "complete":
                raise ValueError("MEMORY_WRITE_UNAVAILABLE")
            if existing.submission_meta != metadata:
                raise MemoryContentConflictError(existing.memory_id)
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
        now = datetime.now(timezone.utc)
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
        try:
            async with self.session.begin_nested():
                await MemoryEventStore(self.session).append(event)
                state = reduce_events(await MemoryEventStore(self.session).replay(scope_id))
                self._ensure_vector_store()
                await self.projections.materialize(state, scope_id, identifier)
                integrity = await self.projections.inspect(state, scope_id)
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

    async def rebuild(self, scope_id, *, actor):
        if actor != "management" or not isinstance(scope_id, int) or isinstance(scope_id, bool):
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:scope)"), {"scope": scope_id})
        history = await MemoryEventStore(self.session).replay(scope_id)
        if not history:
            raise ValueError("MEMORY_WRITE_UNAVAILABLE")
        from rag_mcp.runtime.projection_rebuild import MemoryHistory
        recovered = await MemoryHistory(self).load(scope_id)
        state = recovered.state
        self._ensure_vector_store()
        try:
            async with self.session.begin_nested():
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
                       schema_version=versions["schema_version"], projection_version=versions["projection_versions"][name])
            if name == "dense":
                row["index_version"] = versions["index_version"]
        return report
