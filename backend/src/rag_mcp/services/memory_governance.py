"""Trusted management commands append events before any derived write."""
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.scope_binding import ScopeBinding
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_projection_store import ProjectionFailure
from rag_mcp.services.memory_reducer import projection_fingerprint, reduce_events
from rag_mcp.services.memory_validators import sanitize_submission
from rag_mcp.services.scope_binding_service import ScopeBindingService
from rag_mcp.utils.snowflake import generate_id


class PromotionUnavailable(ValueError):
    """The promotion request cannot be answered from persisted state."""


class PromotionNotFound(LookupError):
    """The target memory or task does not exist in the requested scope."""


def _management_effect_command(event, target):
    """Pure adapter for an existing authorized management retirement."""
    from rag_mcp.services.consolidation_adjudicator import _COMMAND_ISSUER_SEAL, _governed_command

    return _governed_command(event, target=target, _issuer=_COMMAND_ISSUER_SEAL)


def promotion_document(entry, *, memory_id, candidate_version, scope_id, actor, reason, requested_at):
    """Sanitized markdown source package for one explicit human promotion."""
    lines = [
        '# Promotion candidate', '',
        f'- memory_id: {memory_id}',
        f'- candidate_version: {candidate_version}',
        f'- scope_id: {scope_id}',
        f'- kind: {entry.get("kind")}',
        f'- provenance: {entry.get("provenance")}',
        f'- confidence: {entry.get("confidence")}',
        f'- promoted_by: {actor}',
        f'- reason: {reason}',
        f'- requested_at: {requested_at}',
        '', '## Content', '', entry.get('content_text', ''), '', '## Evidence anchors', '',
        '| evidence_id | source_id | version_id | version | position | content_hash |',
        '|---|---|---|---|---|---|',
    ]
    for attribution in entry.get('candidate_basis', {}).get('evidence_attributions', ()) or ():
        lines.append('| {evidence_id} | {source_id} | {version_id} | {version} | {position} | {content_hash} |'.format(
            **{key: attribution.get(key) for key in ('evidence_id', 'source_id', 'version_id', 'version',
                                                      'position', 'content_hash')}))
    return '\n'.join(lines) + '\n'



class MemoryGovernance:
    def __init__(self, service):
        self.service, self.session = service, service.session

    async def execute(self, action, *, scope_id, actor, reason, memory_id=None, event_point=None,
                      time_point=None, binding_id=None, binding_kind=None, binding_value=None,
                      priority=0, status="active", retention_stage=None, policy=None):
        if actor != "management" or not isinstance(scope_id, int) or isinstance(scope_id, bool) or action not in {"access", "retire", "purge", "rollback", "binding", "lifecycle", "policy"}:
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("MEMORY_PROVENANCE_INVALID: reason required")
        scope = await self.session.get(KnowledgeScope, scope_id)
        if scope is None or scope.status != "active":
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:scope)"), {"scope": scope_id})
        history = await MemoryEventStore(self.session).replay(scope_id)
        state = reduce_events(history)
        current = await self.service.projections.current(scope_id)
        if history and (current is None or current.source_event_id != history[-1]["event_id"]):
            raise ValueError("MEMORY_WRITE_UNAVAILABLE")
        event_id, request_id = generate_id(), str(uuid4())
        payload = {"reason": reason}
        target = state["entries"].get(memory_id)
        if action in {"access", "retire", "purge"}:
            if target is None or target["knowledge_scope_id"] != scope_id:
                raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
            if action == "access" and target["status"] != "active":
                raise ValueError("MEMORY_WRITE_UNAVAILABLE")
            if action == "access":
                from rag_mcp.services.memory_policy import MemoryPolicy
                profile = await self.session.get(DomainProfile, scope.domain_key, populate_existing=True)
                if profile is None:
                    raise ValueError("MEMORY_WRITE_UNAVAILABLE")
                payload["decay_rate"] = MemoryPolicy.model_validate(profile.memory_policy or {}).decay_rate
            event_type = "access" if action == "access" else "retract"
            aggregate_id = memory_id
            if action == "purge":
                payload["purge"] = True
        elif action == "lifecycle":
            if target is None or target["status"] != "active" or retention_stage != {"active": "compressed", "compressed": "archived", "archived": "tombstone"}.get(target["retention_stage"]):
                raise ValueError("MEMORY_WRITE_UNAVAILABLE: invalid retention transition")
            event_type, aggregate_id = "grant", memory_id
            payload["retention_stage"] = retention_stage
        elif action == "rollback":
            from rag_mcp.services.rollback_service import RollbackService
            plan = RollbackService().rollback(history, scope_id=scope_id, actor=actor, event_point=event_point, time_point=time_point)
            event_point = plan["event_point"]
            event_type, aggregate_id = "rollback", event_id
            payload["event_point"] = event_point
            payload['payload_version'] = 2
        elif action == "policy":
            from rag_mcp.services.domain_profile_service import assert_not_builtin
            from rag_mcp.services.memory_policy import MemoryPolicy
            assert_not_builtin(scope.domain_key)
            profile = await self.session.scalar(select(DomainProfile).where(
                DomainProfile.domain_key == scope.domain_key).with_for_update())
            if profile is None or profile.is_builtin:
                raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
            before_policy = profile.memory_policy or {}
            after_policy = MemoryPolicy.model_validate({**before_policy, **(policy or {})}).model_dump()
            payload.update(domain_key=scope.domain_key, policy_before=before_policy, policy_after=after_policy)
            event_type, aggregate_id = "grant", event_id
        else:
            if binding_kind not in {"workdir_prefix", "git_remote", "dir_name"} or status not in {"active", "disabled"}:
                raise ValueError("MEMORY_PROVENANCE_INVALID: binding")
            if not isinstance(priority, int) or isinstance(priority, bool):
                raise ValueError("MEMORY_PROVENANCE_INVALID: priority")
            if not isinstance(binding_value, str) or not binding_value.strip():
                raise ValueError("MISSING_KNOWLEDGE_SCOPE")
            normalizer = ScopeBindingService([])
            if binding_kind == "workdir_prefix":
                binding_value = normalizer._normalize_path(binding_value)
            elif binding_kind == "git_remote":
                binding_value = normalizer.normalize_remote(binding_value)
            elif any(character in binding_value for character in "/\\"):
                raise ValueError("MEMORY_PROVENANCE_INVALID: dir_name")
            existing = await self.session.scalar(select(ScopeBinding).where(
                ScopeBinding.binding_kind == binding_kind, ScopeBinding.binding_value == binding_value))
            if existing and existing.knowledge_scope_id != scope_id:
                raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
            if binding_id and (not existing or existing.binding_id != binding_id):
                raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
            binding_id = existing.binding_id if existing else event_id
            payload.update(binding_id=binding_id, binding_kind=binding_kind, binding_value=binding_value, priority=priority, status=status)
            event_type, aggregate_id = "grant", binding_id
        payload, _ = sanitize_submission(payload)
        now = datetime.now(UTC)
        event = MemoryEvent(event_id=event_id, aggregate_id=aggregate_id, knowledge_scope_id=scope_id,
            event_type=event_type, payload=payload, actor="management", request_id=request_id, occurred_at=now,
            authority={"source": "management"}, scope_meta={"knowledge_scope_id": scope_id},
            mutability={"correction": "append_event"}, provenance_meta={"source": "management"},
            recoverability={"source": "event_log"}, actionability="audit")
        candidate = {column.name: getattr(event, column.name) for column in MemoryEvent.__table__.columns if column.name != "created_at"}
        if action in {'retire', 'purge'} and target.get('provenance') == 'hard':
            from rag_mcp.services.consolidation_adjudicator import guard_effect

            command = _management_effect_command(candidate, target)
            checked = guard_effect({'operation': 'invalidate', 'aggregate_id': memory_id}, target, command=command)
            if checked.decision != 'accept':
                raise PermissionError('HARD_MEMORY_PROTECTED')
        after = reduce_events([*history, candidate])
        impact = {"memory_ids": sorted(mid for mid in set(state["entries"]) | set(after["entries"])
                                        if state["entries"].get(mid) != after["entries"].get(mid)),
                  "scope_ids": [scope_id]}
        result = {"scope_id": scope_id, "event_id": event_id, "request_id": request_id, "impact": impact,
                  "before_fingerprint": projection_fingerprint(state), "after_fingerprint": projection_fingerprint(after)}
        event.payload = {**payload, **{key: result[key] for key in ("impact", "before_fingerprint", "after_fingerprint")}}
        fields = {column.name: getattr(event, column.name) for column in MemoryEvent.__table__.columns if column.name != "created_at"}
        self.service._ensure_vector_store()
        try:
            async with self.session.begin_nested():
                if action == "policy":
                    profile.memory_policy = after_policy
                    await self.session.flush()
                await MemoryEventStore(self.session).append(event)
                after = reduce_events(await MemoryEventStore(self.session).replay(scope_id))
                try:
                    await self.service.projections.materialize(after, scope_id, event_id)
                    integrity = await self.service.projections.inspect(after, scope_id)
                except ProjectionFailure:
                    raise
                except Exception as error:
                    raise ProjectionFailure("integrity") from error
                if not all(item["matches_replay"] for item in integrity.values()):
                    raise ProjectionFailure("integrity")
            await self.session.commit()
        except ProjectionFailure as failure:
            if failure.path == "relation":
                await self.session.rollback()
                raise
            await MemoryEventStore(self.session).append(MemoryEvent(**fields))
            after = reduce_events(await MemoryEventStore(self.session).replay(scope_id))
            await self.service.projections.retain_failure(after, scope_id, event_id, failure.path)
            await self.session.commit()
            raise ValueError("MEMORY_WRITE_UNAVAILABLE") from None
        except Exception:
            await self.session.rollback()
            raise
        return result

    # ------------------------------------------------------------------
    # Explicit human promotion (013 T072)
    # ------------------------------------------------------------------

    async def promote(self, *, scope_id, memory_id, candidate_version, actor, reason, request_id=None):
        """One explicit writer management action creates the stable promotion task.

        The current scope, candidate marker and every corpus anchor are
        re-verified inside the short locked transaction; the sanitized raw
        source, the uploaded KnowledgeSource, exactly one pending initial
        ProcessingRun and the permanent pointer grant commit together, and the
        caller schedules ingestion only after this transaction commits.
        """
        from rag_mcp.services.consolidation_adjudicator import candidate_eligibility
        from rag_mcp.services.consolidation_commit import read_evidence
        from rag_mcp.services.knowledge_source_registration import RegistrationError, register_uploaded_source
        from rag_mcp.services.memory_policy import MemoryPolicy

        if actor != "management" or not isinstance(scope_id, int) or isinstance(scope_id, bool) or scope_id <= 0:
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
        if not isinstance(memory_id, int) or isinstance(memory_id, bool) or memory_id <= 0:
            raise PromotionNotFound("MEMORY_PROMOTION_NOT_FOUND")
        if not isinstance(candidate_version, str) or len(candidate_version) != 64 or any(
                character not in "0123456789abcdef" for character in candidate_version):
            raise ValueError("MEMORY_CANDIDATE_VERSION_CHANGED")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
            raise ValueError("MEMORY_PROVENANCE_INVALID: reason required")
        scope = await self.session.get(KnowledgeScope, scope_id)
        if scope is None or scope.status != "active":
            raise PermissionError("MEMORY_ROLLBACK_FORBIDDEN")
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:scope)"), {"scope": scope_id})
        history = await MemoryEventStore(self.session).replay(scope_id)
        state = reduce_events(history)
        current = await self.service.projections.current(scope_id)
        if history and (current is None or current.source_event_id != history[-1]["event_id"]):
            raise ValueError("MEMORY_WRITE_UNAVAILABLE")
        entry = state["entries"].get(memory_id)
        if entry is None:
            await self.session.rollback()
            raise PromotionNotFound("MEMORY_PROMOTION_NOT_FOUND")
        pointer = entry.get("promotion_pointer")
        if pointer is not None and pointer["candidate_version"] == candidate_version:
            result = _promotion_result(pointer, reused=True)
            await self.session.rollback()
            return result
        if entry.get("candidate_version") != candidate_version:
            await self.session.rollback()
            raise ValueError("MEMORY_CANDIDATE_VERSION_CHANGED")
        profile = await self.session.get(DomainProfile, scope.domain_key)
        policy = MemoryPolicy.model_validate(profile.memory_policy or {})
        if policy.consolidation is None:
            await self.session.rollback()
            raise ValueError("MEMORY_CANDIDATE_NOT_ELIGIBLE: consolidation configuration absent")
        identifiers = {str(reference) for reference in entry.get("evidence_refs") or ()}
        facts = await read_evidence(self.session, identifiers, locked=True) if identifiers else {}
        eligible, reasons = candidate_eligibility(entry, facts, scope_id=scope_id,
                                                  threshold=policy.consolidation.candidate_min_confidence)
        if not eligible:
            await self.session.rollback()
            raise ValueError(f"MEMORY_CANDIDATE_NOT_ELIGIBLE: {reasons[0]}")
        now = datetime.now(UTC)
        request_id = str(request_id or uuid4())
        filename = f"promotion-{memory_id}-{candidate_version[:16]}.md"
        document = promotion_document(entry, memory_id=memory_id, candidate_version=candidate_version,
                                      scope_id=scope_id, actor=actor, reason=reason,
                                      requested_at=now.isoformat())
        clean, sanitized = sanitize_submission({"content": document})
        if sanitized.status != "active" or clean["content"] != document:
            await self.session.rollback()
            raise ValueError("MEMORY_CANDIDATE_NOT_ELIGIBLE: promotion content is unsafe")
        try:
            registration = await register_uploaded_source(self.session, scope_id=scope_id,
                content=document.encode("utf-8"), filename=filename, format="markdown", now=now)
        except RegistrationError as error:
            await self.session.rollback()
            raise PromotionUnavailable("MEMORY_PROMOTION_UNAVAILABLE") from error
        event_id = generate_id()
        pointer = {
            "task_id": str(event_id), "request_event_id": event_id, "memory_id": memory_id,
            "candidate_version": candidate_version, "scope_id": scope_id, "actor": actor, "reason": reason,
            "request_id": request_id, "source_id": registration.source.source_id,
            "initial_processing_run_id": registration.initial_run.run_id,
            "content_hash": registration.content_hash, "filename": filename, "format": "markdown",
            "requested_at": now.isoformat(),
            "evidence_attributions": [dict(item) for item in entry["candidate_basis"]["evidence_attributions"]],
            "status": "uploaded", "published_version_id": None, "result": None,
            "attempt_run_ids": [registration.initial_run.run_id],
            "authority_event_ids": [event_id],
            "attempts": [{"run_id": registration.initial_run.run_id, "run_type": "initial", "status": "pending",
                          "observed_at": now.isoformat(), "event_id": event_id}],
        }
        payload = {"payload_version": 2, "grant_type": "promotion_requested", "memory_id": memory_id,
                   "candidate_version": candidate_version, "source_id": registration.source.source_id,
                   "request_id": request_id, "reason": reason, "pointer": pointer}
        payload, _ = sanitize_submission(payload)
        event = MemoryEvent(event_id=event_id, aggregate_id=memory_id, knowledge_scope_id=scope_id,
            event_type="grant", payload=payload, actor="management", request_id=request_id, occurred_at=now,
            authority={"source": "management"}, scope_meta={"knowledge_scope_id": scope_id},
            mutability={"correction": "append_event"}, provenance_meta={"source": "management"},
            recoverability={"source": "event_log"}, actionability="audit")
        self.service._ensure_vector_store()
        try:
            async with self.session.begin_nested():
                await MemoryEventStore(self.session).append(event)
                after = reduce_events(await MemoryEventStore(self.session).replay(scope_id))
                await self.service.projections.materialize(after, scope_id, event_id)
                integrity = await self.service.projections.inspect(after, scope_id)
                if not all(item["matches_replay"] for item in integrity.values()):
                    raise ProjectionFailure("integrity")
            await self.session.commit()
        except ProjectionFailure:
            await self.session.rollback()
            raise PromotionUnavailable("MEMORY_PROMOTION_UNAVAILABLE") from None
        except IntegrityError:
            # A concurrent identical request won the unique (scope, memory,
            # candidate_version) race; return the persisted original task.
            await self.session.rollback()
            history = await MemoryEventStore(self.session).replay(scope_id)
            existing = (reduce_events(history)["entries"].get(memory_id) or {}).get("promotion_pointer")
            if existing is None or existing["candidate_version"] != candidate_version:
                raise PromotionUnavailable("MEMORY_PROMOTION_UNAVAILABLE") from None
            return _promotion_result(existing, reused=True)
        except Exception:
            await self.session.rollback()
            raise
        return _promotion_result(pointer, reused=False)

    async def observe_promotion(self, *, source_id, status=None, result=None):
        """Append a permanent promotion_observed grant for real attempts (T074).

        Uploaded, processing and failed never report published: the recorded
        status comes from the actual source/run/version facts unless an explicit
        pre-dispatch failure is being recorded. A regular upload has no promotion
        request and is left untouched. The original request grant is never
        mutated; each new permanent observation extends the pointer history.
        """
        from rag_mcp.models.knowledge_source import KnowledgeSource
        from rag_mcp.models.processing_run import ProcessingRun
        from rag_mcp.services.memory_validators import sanitize_submission

        source = await self.session.get(KnowledgeSource, source_id, populate_existing=True)
        if source is None:
            raise PromotionNotFound("MEMORY_PROMOTION_NOT_FOUND")
        scope_id = source.knowledge_scope_id
        history = await MemoryEventStore(self.session).replay(scope_id)
        request = next((event for event in reversed(history) if event["event_type"] == "grant"
                        and event["payload"].get("grant_type") == "promotion_requested"
                        and event["payload"].get("source_id") == source_id), None)
        if request is None:
            return None
        state = reduce_events(history)
        entry = state["entries"].get(request["payload"]["memory_id"]) or {}
        pointer = deepcopy(entry.get("promotion_pointer") or request["payload"]["pointer"])
        observed = await self.service.promotion_status(task_id=request["event_id"], scope_id=scope_id)
        run = await self.session.scalar(select(ProcessingRun).where(ProcessingRun.source_id == source_id)
                                        .order_by(ProcessingRun.run_id.desc()).limit(1))
        event_id, now = generate_id(), datetime.now(UTC)
        attempts = list(pointer["attempts"])
        if run is not None:
            attempts = [item for item in attempts if item["run_id"] != run.run_id] + [
                {"run_id": run.run_id, "run_type": run.run_type, "status": run.status,
                 "observed_at": now.isoformat(), "event_id": event_id}]
            attempts.sort(key=lambda item: item["run_id"])
        pointer.update(status=status or observed["status"],
                       published_version_id=observed["published_version_id"],
                       result=result if result is not None else pointer["result"],
                       attempt_run_ids=[item["run_id"] for item in attempts], attempts=attempts,
                       authority_event_ids=[*pointer["authority_event_ids"], event_id])
        payload = {"payload_version": 2, "grant_type": "promotion_observed",
                   "memory_id": pointer["memory_id"], "source_id": source_id,
                   "request_id": pointer["request_id"], "pointer": pointer}
        payload, _ = sanitize_submission(payload)
        event = MemoryEvent(event_id=event_id, aggregate_id=pointer["memory_id"], knowledge_scope_id=scope_id,
            event_type="grant", payload=payload, actor="management", request_id=pointer["request_id"],
            occurred_at=now, authority={"source": "management"}, scope_meta={"knowledge_scope_id": scope_id},
            mutability={"correction": "append_event"}, provenance_meta={"source": "management"},
            recoverability={"source": "event_log"}, actionability="audit")
        self.service._ensure_vector_store()
        try:
            async with self.session.begin_nested():
                await MemoryEventStore(self.session).append(event)
                after = reduce_events(await MemoryEventStore(self.session).replay(scope_id))
                await self.service.projections.materialize(after, scope_id, event_id)
                integrity = await self.service.projections.inspect(after, scope_id)
                if not all(item["matches_replay"] for item in integrity.values()):
                    raise ProjectionFailure("integrity")
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return await self.service.promotion_status(task_id=request["event_id"], scope_id=scope_id)


def _promotion_result(pointer, *, reused):
    return {"schema_version": 1, "scope_id": pointer["scope_id"], "memory_id": pointer["memory_id"],
            "candidate_version": pointer["candidate_version"], "task_id": pointer["task_id"],
            "source_id": pointer["source_id"], "initial_processing_run_id": pointer["initial_processing_run_id"],
            "status": pointer["status"], "version_id": pointer["published_version_id"],
            "request_id": pointer["request_id"], "reused": reused}
