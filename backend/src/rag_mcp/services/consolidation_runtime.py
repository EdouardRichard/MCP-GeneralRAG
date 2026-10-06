"""Short, fenced control transactions for the offline consolidation loop."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from rag_mcp.agents.llm_client import LLMCallReceipt, receipt_observer
from rag_mcp.config import get_settings
from rag_mcp.config.domain_profiles import memory_vocabulary_version, validate_memory_link_vocabulary
from rag_mcp.models.consolidation_run import ConsolidationEligibility, ConsolidationRunObservation
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
from rag_mcp.models.runtime import RuntimeMaintenanceLog, WriterLease
from rag_mcp.orchestration.consolidation_pipeline import (
    CurrentSnapshot,
    SourceVersion,
    TrustedContext,
    WindowSnapshot,
    select_window,
    thaw,
)
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_policy import MemoryPolicy
from rag_mcp.services.memory_reducer import projection_fingerprint, reduce_events
from rag_mcp.services.memory_validators import redact_submission, sanitize_consolidation_audit
from rag_mcp.services.provider_usage import ProviderUsageAccumulator
from rag_mcp.utils.snowflake import generate_id


class ConsolidationRuntimeError(ValueError):
    def __init__(self, code, *, run_id=None):
        self.code, self.run_id = code, run_id
        super().__init__(code)


_PROVIDER_SLOTS = threading.BoundedSemaphore(2)
_PROVIDER_THREADS = ThreadPoolExecutor(max_workers=2, thread_name_prefix='memory-distiller')


class _CallAccounting:
    def __init__(self):
        self._lock = threading.Lock()
        self._receipt = LLMCallReceipt()

    def record(self, receipt):
        with self._lock:
            self._receipt = receipt

    def snapshot(self):
        with self._lock:
            receipt = self._receipt
        usage = ConsolidationUsage()
        if receipt.cache_hits:
            usage.record_cache_hit()
        if receipt.transport_calls:
            usage.record_transport(prompt_chars=receipt.prompt_chars, completion_chars=receipt.completion_chars,
                                   input_tokens=receipt.input_tokens, output_tokens=receipt.output_tokens,
                                   cost_usd=receipt.cost_usd)
        return usage.to_dict()


@dataclass(frozen=True)
class ProviderOutcome:
    result: object | None
    reason: str | None
    usage: object


def _run_distiller(agent, data, accounting):
    observer_token = receipt_observer.set(accounting.record)
    try:
        return agent.run(data)
    finally:
        receipt_observer.reset(observer_token)
        # This finally belongs to the synchronous worker, not its async waiter.
        _PROVIDER_SLOTS.release()


class DistillerProvider:
    """Process-wide limit on actual synchronous calls; full capacity rejects."""

    async def run(self, agent, data, *, timeout_s):
        from rag_mcp.orchestration.consolidation_pipeline import freeze

        accounting = _CallAccounting()
        if not _PROVIDER_SLOTS.acquire(blocking=False):
            return ProviderOutcome(None, 'PROVIDER_CAPACITY', freeze(accounting.snapshot()))
        try:
            # Exclude request/run/token and arbitrary handles from worker arguments.
            work = _PROVIDER_THREADS.submit(_run_distiller, agent, freeze({'window': data['window']}), accounting)
        except BaseException:
            _PROVIDER_SLOTS.release()
            raise
        future = asyncio.wrap_future(work)
        # Drain abandoned exceptions without retaining or delivering late results.
        future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            result = await asyncio.wait_for(asyncio.shield(future), timeout=timeout_s)
            return ProviderOutcome(result, None, freeze(accounting.snapshot()))
        except TimeoutError:
            return ProviderOutcome(None, 'PROVIDER_TIMEOUT', freeze(accounting.snapshot()))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - abandoned workers must yield sanitized failure diagnostics
            return ProviderOutcome(None, 'AGENT_EXECUTION_FAILED', freeze(accounting.snapshot()))


@dataclass(frozen=True)
class EligibilityToken:
    eligibility_id: UUID
    scope_id: int
    run_id: UUID
    holder_instance_id: UUID
    writer_lease_id: int
    eligibility_version: int

    def to_dict(self):
        return {key: str(value) if isinstance(value, UUID) else value for key, value in asdict(self).items()}


class ConsolidationUsage:
    def __init__(self):
        self.provider = ProviderUsageAccumulator()
        self.cache_hits = 0
        self.source = 'unavailable'
        self.input_tokens = self.output_tokens = self.cost_usd = None
        self._unknown = {'input_tokens': False, 'output_tokens': False, 'cost_usd': False}

    def record_cache_hit(self):
        self.cache_hits += 1

    def record_transport(self, *, prompt_chars=0, completion_chars=0, input_tokens=None, output_tokens=None,
                         cost_usd=None, source='actual'):
        if source not in ('actual', 'estimated', 'unavailable'):
            raise ValueError('invalid usage source')
        values = {'input_tokens': input_tokens, 'output_tokens': output_tokens, 'cost_usd': cost_usd}
        for key, value in values.items():
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or value < 0):
                raise ValueError('invalid provider usage')
            if key.endswith('tokens') and value is not None and not isinstance(value, int):
                raise ValueError('token usage must be an integer')
        self.provider.llm_calls += 1
        self.provider.llm_prompt_chars += max(0, prompt_chars)
        self.provider.llm_completion_chars += max(0, completion_chars)
        for key, value in values.items():
            self._unknown[key] |= value is None
            if self._unknown[key]:
                setattr(self, key, None)
            else:
                setattr(self, key, (getattr(self, key) or 0) + value)
        self.source = 'unavailable' if any(self._unknown.values()) else (
            'estimated' if source == 'estimated' or self.source == 'estimated' else source)

    def to_dict(self):
        return {**self.provider.to_dict(), 'cache_hits': self.cache_hits, 'source': self.source,
                'input_tokens': self.input_tokens, 'output_tokens': self.output_tokens, 'cost_usd': self.cost_usd}


class CommitFence:
    def __init__(self, runtime, token, context, started_at):
        self.runtime, self.token, self.context, self.started_at = runtime, token, context, started_at

    async def validate_before_publish(self):
        now = await self.runtime._clock()
        if now - self.started_at >= timedelta(seconds=30):
            raise ConsolidationRuntimeError('CONSOLIDATION_COMMIT_TIMEOUT')
        await self.runtime._validate_token(self.token, now=now)
        await self.runtime._validate_policy(self.token.scope_id, self.context)


class ConsolidationRuntime:
    eligibility_ttl_seconds = 120
    heartbeat_interval_seconds = 20
    commit_timeout_seconds = 30

    def __init__(self, session, *, owner, memory_service=None):
        self.session, self.owner, self.memory_service = session, owner, memory_service

    @asynccontextmanager
    async def _transaction(self):
        # Flushed ORM and raw SQL writes are invisible to the pending-object sets.
        if self.session.in_transaction():
            raise ConsolidationRuntimeError('CONSOLIDATION_TRANSACTION_BUSY')
        async with self.session.begin():
            await self.session.execute(text("SET LOCAL statement_timeout='30s'"))
            await self.session.execute(text("SET LOCAL idle_in_transaction_session_timeout='30s'"))
            yield

    async def _clock(self):
        return await self.session.scalar(text('SELECT clock_timestamp()'))

    async def _lock_scope(self, scope_id):
        if isinstance(scope_id, bool) or not isinstance(scope_id, int) or scope_id <= 0:
            raise ConsolidationRuntimeError('MISSING_KNOWLEDGE_SCOPE')
        locked = await self.session.scalar(text('SELECT pg_try_advisory_xact_lock(:scope)'), {'scope': scope_id})
        if not locked:
            active = await self.session.scalar(select(ConsolidationEligibility).where(
                ConsolidationEligibility.knowledge_scope_id == scope_id, ConsolidationEligibility.state == 'active',
                ConsolidationEligibility.expires_at > func.clock_timestamp()))
            if active:
                raise ConsolidationRuntimeError('CONSOLIDATION_BUSY', run_id=active.run_id)
            raise ConsolidationRuntimeError('CONSOLIDATION_SCOPE_WRITE_BUSY')

    async def _live_lease(self, *, lease_id=None, holder=None):
        await self.session.execute(text('RESET ROLE'))
        lease_id = self.owner.lease_id if lease_id is None else lease_id
        holder = self.owner.holder_instance_id if holder is None else holder
        lease = await self.session.scalar(select(WriterLease).where(WriterLease.lease_id == lease_id)
                                           .with_for_update(read=True).execution_options(populate_existing=True))
        now = await self._clock()
        if (lease is None or lease.state != 'active' or lease.expires_at <= now
            or lease.holder_instance_id != holder or holder != self.owner.holder_instance_id
            or lease_id != self.owner.lease_id):
            raise ConsolidationRuntimeError('WRITER_LEASE_LOST')
        return lease

    async def _validate_policy(self, scope_id, context):
        scope = await self.session.scalar(select(KnowledgeScope).where(KnowledgeScope.scope_id == scope_id)
                                           .with_for_update(read=True).execution_options(populate_existing=True))
        if scope is None or scope.status != 'active':
            raise ConsolidationRuntimeError('MISSING_KNOWLEDGE_SCOPE')
        profile = await self.session.scalar(select(DomainProfile).where(DomainProfile.domain_key == scope.domain_key)
                                             .with_for_update(read=True).execution_options(populate_existing=True))
        if context.execution_context == 'deterministic_propagation':
            # Trusted writer maintenance/governance support hook only: the same
            # scope eligibility, lease and fence apply, but the ordinary
            # consolidation switches never gate a necessary-support denial.
            if not context.trusted_support_hook:
                raise ConsolidationRuntimeError('TRUSTED_CONTEXT_REQUIRED')
            await self._verify_support_proof(scope_id, context)
            return MemoryPolicy.model_validate(profile.memory_policy or {}), profile
        captured = profile.memory_policy or {}
        if captured.get('consolidation_enabled') and captured.get('consolidation') is None:
            raise ConsolidationRuntimeError('CONSOLIDATION_CONFIGURATION_REQUIRED')
        policy = MemoryPolicy.model_validate(captured)
        if not policy.consolidation_enabled:
            raise ConsolidationRuntimeError('CONSOLIDATION_DISABLED')
        if policy.consolidation is None:
            raise ConsolidationRuntimeError('CONSOLIDATION_CONFIGURATION_REQUIRED')
        return policy, profile

    @staticmethod
    def _matches(row, token):
        return row is not None and (row.eligibility_id, row.knowledge_scope_id, row.run_id, row.holder_instance_id,
            row.writer_lease_id, row.eligibility_version) == (token.eligibility_id, token.scope_id, token.run_id,
            token.holder_instance_id, token.writer_lease_id, token.eligibility_version)

    async def _validate_token(self, token, *, now=None):
        row = await self.session.scalar(select(ConsolidationEligibility).where(
            ConsolidationEligibility.eligibility_id == token.eligibility_id).with_for_update()
            .execution_options(populate_existing=True))
        now = await self._clock() if now is None else now
        if not self._matches(row, token) or row.state != 'active' or row.expires_at <= now:
            raise ConsolidationRuntimeError('ELIGIBILITY_LOST')
        await self._live_lease(lease_id=token.writer_lease_id, holder=token.holder_instance_id)
        return row

    @asynccontextmanager
    async def commit_fence(self, token, *, context=None):
        context = context or TrustedContext()
        async with self._transaction():
            started_at = await self._clock()
            await self._lock_scope(token.scope_id)
            await self._validate_token(token)
            await self._validate_policy(token.scope_id, context)
            fence = CommitFence(self, token, context, started_at)
            yield fence
            await fence.validate_before_publish()

    async def admit(self, scope_id, *, trigger, request_id=None, actor='management', context=None, run_id=None):
        from rag_mcp.orchestration.consolidation_pipeline import propagation_trigger_material

        context = context or TrustedContext()
        maintenance = trigger == 'support_maintenance'
        if maintenance:
            # Only the trusted writer support hook may construct this context.
            if not context.trusted_support_hook:
                raise ConsolidationRuntimeError('TRUSTED_CONTEXT_REQUIRED')
            try:
                propagation_trigger_material(dict(context.propagation_trigger))
            except (TypeError, ValueError):
                raise ConsolidationRuntimeError('TRUSTED_CONTEXT_REQUIRED') from None
        elif trigger not in ('manual', 'idle', 'volume') or context.execution_context != 'distiller_window':
            raise ConsolidationRuntimeError('TRUSTED_CONTEXT_REQUIRED')
        try:
            async with self._transaction():
                await self._lock_scope(scope_id)
                # The domain/configuration gate is answered before occupancy: a
                # disabled or unconfigured domain never reports a busy run.
                await self._live_lease()
                await self._validate_policy(scope_id, context)
                active = await self.session.scalar(select(ConsolidationEligibility).where(
                    ConsolidationEligibility.knowledge_scope_id == scope_id, ConsolidationEligibility.state == 'active')
                    .with_for_update().execution_options(populate_existing=True))
                now = await self._clock()
                superseded = None
                if active and active.expires_at > now:
                    # Only the trusted support hook may preempt an ordinary
                    # distiller window; it may never preempt another maintenance
                    # wave, so the same-scope exclusivity still holds.
                    latest = await self.latest_observation(active.run_id) if maintenance else None
                    if latest is None or latest.trigger == 'support_maintenance':
                        raise ConsolidationRuntimeError('CONSOLIDATION_BUSY', run_id=active.run_id)
                    superseded = active.run_id
                if active:
                    active.state = 'expired'
                    active.released_at = now
                    await self.session.flush()
                version = (await self.session.scalar(select(func.max(ConsolidationEligibility.eligibility_version))
                    .where(ConsolidationEligibility.knowledge_scope_id == scope_id)) or 0) + 1
                token = EligibilityToken(uuid4(), scope_id, run_id or uuid4(), self.owner.holder_instance_id,
                                         self.owner.lease_id, version)
                self.session.add(ConsolidationEligibility(eligibility_id=token.eligibility_id,
                    knowledge_scope_id=scope_id, run_id=token.run_id, holder_instance_id=token.holder_instance_id,
                    writer_lease_id=token.writer_lease_id, eligibility_version=version, state='active',
                    acquired_at=now, renewed_at=now, expires_at=now + timedelta(seconds=120)))
                await self.session.flush()
                observation = {'status': 'admitted', 'trigger': trigger,
                    'execution_context': context.execution_context, 'request_id': request_id or str(uuid4()),
                    'actor': actor, 'provider_usage': ConsolidationUsage().to_dict(), 'eligibility_state': 'active'}
                if maintenance:
                    observation.update(window=None, input_event_ids=[],
                        historical_source_refs=thaw(context.historical_source_refs),
                        propagation_trigger=thaw(context.propagation_trigger))
                if superseded is not None:
                    observation['degradation_reasons'] = ['superseded_ordinary_eligibility']
                await self._observe_locked(token, **observation)
            return token
        except IntegrityError as error:
            async with self._transaction():
                active = await self.session.scalar(select(ConsolidationEligibility).where(
                    ConsolidationEligibility.knowledge_scope_id == scope_id, ConsolidationEligibility.state == 'active'))
                active_run = active.run_id if active else None
            if active_run:
                raise ConsolidationRuntimeError('CONSOLIDATION_BUSY', run_id=active_run) from None
            raise error

    async def takeover(self, old_token):
        async with self._transaction():
            await self._lock_scope(old_token.scope_id)
            row = await self.session.scalar(select(ConsolidationEligibility).where(
                ConsolidationEligibility.eligibility_id == old_token.eligibility_id).with_for_update()
                .execution_options(populate_existing=True))
            if not self._matches(row, old_token):
                raise ConsolidationRuntimeError('ELIGIBILITY_LOST')
            latest = await self.latest_observation(old_token.run_id)
            trigger, request, actor = (latest.trigger, latest.request_id, latest.actor) if latest else ('manual', None, 'management')
        return await self.admit(old_token.scope_id, trigger=trigger, run_id=old_token.run_id,
                                request_id=request, actor=actor)

    async def append_propagation_seal(self, token, material, *, context):
        """Persist permanent continuation material for a wave with no effect.

        This is the trusted control grant `consolidation_propagation`: it never
        writes an empty success, never consumes a source and never carries
        create/merge/link/context/candidate authority.
        """
        from rag_mcp.services.memory_projection_store import ProjectionFailure
        from rag_mcp.services.memory_service import MemoryService

        async with self.commit_fence(token, context=context) as fence:
            now = await self._clock()
            identifier = generate_id()
            payload = {'payload_version': 2, 'grant_type': 'consolidation_propagation',
                'trigger': thaw(material['trigger']),
                'visited_memory_ids': list(material['visited_memory_ids']),
                'depth': int(material['depth']),
                'frontier_memory_ids': list(material['frontier_memory_ids']),
                'continuation_key': material['continuation_key'],
                'vocabulary_version': material['vocabulary_version'],
                'control_adjudication': {'decision': 'seal_propagation', 'effect': 'control_only',
                                         'rule_version': '013.propagation.1'},
                'eligibility_token': token.to_dict()}
            fields = {'event_id': identifier, 'aggregate_id': identifier, 'event_type': 'grant',
                'knowledge_scope_id': token.scope_id, 'payload': payload, 'actor': 'management',
                'request_id': str(uuid4()), 'occurred_at': now,
                'authority': {'source': 'consolidation_control'}, 'scope_meta': {'knowledge_scope_id': token.scope_id},
                'mutability': {'correction': 'append_event'}, 'provenance_meta': {'source': 'consolidation_control'},
                'recoverability': {'source': 'event_log'}, 'actionability': 'audit'}
            await self.session.execute(text("SELECT set_config('rag_memory.consolidation_token',:token,true)"),
                                       {'token': str(token.eligibility_id)})
            service = self.memory_service or MemoryService(self.session)
            service._ensure_vector_store()
            try:
                async with self.session.begin_nested():
                    await MemoryEventStore(self.session).append(MemoryEvent(**fields))
                    state = reduce_events(await MemoryEventStore(self.session).replay(token.scope_id))
                    await service.projections.materialize(state, token.scope_id, identifier)
                    await fence.validate_before_publish()
            except ProjectionFailure as error:
                if error.path == 'relation':
                    raise
                await MemoryEventStore(self.session).append(MemoryEvent(**fields))
                state = reduce_events(await MemoryEventStore(self.session).replay(token.scope_id))
                await service.projections.retain_failure(state, token.scope_id, identifier, error.path)
            await self._observe_locked(token, status='no_change',
                                       degradation_reasons=['propagation_frontier_retained'])
        return identifier

    async def _verify_support_proof(self, scope_id, context):
        """Re-verify the trigger's current invalidation proof at every fence.

        A stale proof (republished evidence, reactivated support) revokes the
        maintenance admission and any pending commit, including grant-only
        continuation seals.
        """
        from rag_mcp.services.consolidation_commit import read_evidence

        trigger = context.propagation_trigger
        proof = trigger.get('proof') or {}
        if trigger.get('evidence_id') is not None:
            facts = await read_evidence(self.session, [str(trigger['evidence_id'])], locked=True)
            fact = facts.get(str(trigger['evidence_id']))
            if (fact is None or fact.get('status') != 'withdrawn'
                or str(fact.get('version_id')) != str(trigger.get('version_id'))):
                raise ConsolidationRuntimeError('CONTRADICTION_NOT_PROVEN')
            return
        cause = proof.get('cause_memory_id', proof.get('memory_id'))
        if isinstance(cause, bool) or not isinstance(cause, int):
            raise ConsolidationRuntimeError('TRUSTED_CONTEXT_REQUIRED')
        current = await self.read_snapshot(scope_id)
        row = current.entries.get(cause)
        now = await self._clock()

        def past(value):
            if value is None:
                return False
            stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value)
            return stamp <= now

        if (row is not None and row.get('status') == 'active'
            and not past(row.get('expires_at')) and not past(row.get('valid_to'))):
            raise ConsolidationRuntimeError('CONTRADICTION_NOT_PROVEN')

    async def heartbeat(self, token):
        async with self._transaction():
            await self._lock_scope(token.scope_id)
            row = await self._validate_token(token)
            now = await self._clock()
            row.renewed_at, row.expires_at = now, now + timedelta(seconds=120)
        return token

    async def release(self, token):
        async with self._transaction():
            await self._lock_scope(token.scope_id)
            row = await self.session.scalar(select(ConsolidationEligibility).where(
                ConsolidationEligibility.eligibility_id == token.eligibility_id).with_for_update()
                .execution_options(populate_existing=True))
            if not self._matches(row, token) or row.state != 'active':
                return False
            await self._live_lease(lease_id=token.writer_lease_id, holder=token.holder_instance_id)
            row.state, row.released_at = 'released', await self._clock()
            await self._observe_locked(token, eligibility_state='released')
        return True

    async def latest_observation(self, run_id):
        return await self.session.scalar(select(ConsolidationRunObservation).where(
            ConsolidationRunObservation.run_id == run_id).order_by(ConsolidationRunObservation.observation_seq.desc()).limit(1))

    async def _observe_locked(self, token, **changes):
        previous = await self.latest_observation(token.run_id)
        skip = {'run_id', 'observation_seq', 'created_at', 'ttl_expires_at'}
        values = {column.name: deepcopy(getattr(previous, column.name)) for column in previous.__table__.columns
                  if column.name not in skip} if previous else {}
        allowed = set(ConsolidationRunObservation.__table__.columns.keys()) - skip - {
            'knowledge_scope_id', 'eligibility_id', 'eligibility_version', 'holder_instance_id', 'writer_lease_id'}
        if set(changes) - allowed:
            raise ValueError('unrecognized consolidation observation field')
        usage = changes.get('provider_usage')
        if isinstance(usage, ConsolidationUsage):
            changes['provider_usage'] = usage.to_dict()
        values.update(sanitize_consolidation_audit(thaw(changes), scope_id=token.scope_id))
        now = await self._clock()
        high_water = await self.session.scalar(select(func.max(ConsolidationEligibility.observation_seq_high_water))
            .where(ConsolidationEligibility.run_id == token.run_id)) or 0
        sequence = max(high_water, previous.observation_seq if previous else 0) + 1
        eligibility = await self.session.get(ConsolidationEligibility, token.eligibility_id)
        eligibility.observation_seq_high_water = sequence
        observation = ConsolidationRunObservation(**{**values, 'run_id': token.run_id,
            'observation_seq': sequence, 'knowledge_scope_id': token.scope_id,
            'eligibility_id': token.eligibility_id, 'eligibility_version': token.eligibility_version,
            'holder_instance_id': token.holder_instance_id, 'writer_lease_id': token.writer_lease_id,
            'created_at': now, 'ttl_expires_at': now + timedelta(days=get_settings().retrieval_ttl_days)})
        self.session.add(observation)
        await self.session.flush()
        return observation

    async def observe(self, token, **changes):
        async with self._transaction():
            await self._lock_scope(token.scope_id)
            await self._validate_token(token)
            observation = await self._observe_locked(token, **changes)
        return observation

    async def observe_result(self, token, decisions, outcome, *, batch):
        published = set(outcome.output_event_ids)
        status = ('partial' if published and (outcome.pending_result_keys or outcome.failed_result_keys) else
                  'failed' if outcome.pending_result_keys or outcome.status in ('failure', 'rolled_back') else
                  'degraded' if batch.degraded else 'succeeded' if published else 'no_change')
        reasons = list(batch.degradation_reasons) + list(outcome.reason_codes)
        if not decisions.groups and not reasons:
            reasons.append('all_rejected')
        publication = {}
        async with self._transaction():
            current = await self.read_snapshot(token.scope_id)
            results = current.consolidation_state['potential_results']
            for group in decisions.groups:
                result = results.get(group.group_key, {})
                state = ('committed' if not result.get('rolled_back') and published.intersection(result.get('event_ids', ()))
                         else 'pending' if group.group_key in outcome.pending_result_keys
                         else 'failed' if group.group_key in outcome.failed_result_keys else 'not_committed')
                publication.update(dict.fromkeys(group.decision_ids, state))
        return await self.observe(token, status=status, output_memory_ids=list(outcome.output_memory_ids),
            output_event_ids=list(outcome.output_event_ids), pending_result_keys=list(outcome.pending_result_keys),
            provider_usage=thaw(batch.usage), degradation_reasons=reasons,
            adjudications=[{'decision_id': d.decision_id, 'decision': d.decision, 'reason_codes': list(d.reason_codes),
                'publication': publication.get(d.decision_id, 'not_committed')} for d in decisions.decisions])

    async def purge_expired_observations(self):
        async with self._transaction():
            await self._live_lease()
            ids = (await self.session.execute(select(ConsolidationRunObservation.run_id,
                ConsolidationRunObservation.observation_seq).where(ConsolidationRunObservation.ttl_expires_at < func.clock_timestamp()))).all()
            if not ids:
                return 0
            log_id = generate_id()
            self.session.add(RuntimeMaintenanceLog(log_id=log_id, event_type='ttl_purge', purged_consolidation_runs=len(ids)))
            await self.session.flush()
            await self.session.execute(text("SELECT set_config('rag_memory.writer_lease',:lease,true),"
                "set_config('rag_memory.writer_holder',:holder,true),set_config('rag_memory.maintenance_log',:log,true)"),
                {'lease': str(self.owner.lease_id), 'holder': str(self.owner.holder_instance_id), 'log': str(log_id)})
            await self.session.execute(text('SET LOCAL ROLE rag_consolidation_maintenance'))
            for run_id, seq in ids:
                await self.session.execute(delete(ConsolidationRunObservation).where(
                    ConsolidationRunObservation.run_id == run_id, ConsolidationRunObservation.observation_seq == seq))
        return len(ids)

    async def read_snapshot(self, scope_id):
        scope = await self.session.get(KnowledgeScope, scope_id, populate_existing=True)
        if scope is None or scope.status != 'active':
            raise ConsolidationRuntimeError('MISSING_KNOWLEDGE_SCOPE')
        profile = await self.session.get(DomainProfile, scope.domain_key, populate_existing=True)
        vocabulary = validate_memory_link_vocabulary(profile.memory_link_vocabulary or [])
        manifest = await self.session.get(MemoryProjectionMeta, f'current:{scope_id}', populate_existing=True)
        if manifest is None and await self.session.scalar(select(MemoryEvent.event_id).where(
                MemoryEvent.knowledge_scope_id == scope_id).limit(1)) is not None:
            raise ConsolidationRuntimeError('CONSOLIDATION_COMPLETE_MANIFEST_REQUIRED')
        high_water = manifest.source_event_id if manifest and manifest.status == 'complete' else 0
        state = reduce_events(await MemoryEventStore(self.session).replay(scope_id, through_event_id=high_water))
        if manifest:
            replay = state.export()
            saved = (manifest.payload or {}).get('state')
            if isinstance(saved, dict) and 'consolidation_state' not in saved:
                # 0094 published this exact version without the empty 013 control registry.
                legacy_keys = {'entries', 'dense', 'links', 'summary', 'files', 'salience', 'bindings'}
                empty_controls = reduce_events([])['consolidation_state']
                if (manifest.projection_version != '012-v1' or manifest.payload.get('verification_version') != 1
                    or set(saved) != legacy_keys or replay['consolidation_state'] != empty_controls):
                    raise ConsolidationRuntimeError('CONSOLIDATION_COMPLETE_MANIFEST_REQUIRED')
                del replay['consolidation_state']
            if (manifest.status != 'complete' or high_water <= 0
                or projection_fingerprint(replay) != manifest.fingerprint
                or projection_fingerprint(replay) != projection_fingerprint(saved)):
                raise ConsolidationRuntimeError('CONSOLIDATION_COMPLETE_MANIFEST_REQUIRED')
        return CurrentSnapshot.from_verified_state(state, scope_id=scope_id, high_water_mark=high_water,
                                                   verified_complete=True, vocabulary=vocabulary)

    async def retry_window(self, scope_id, window_id):
        current = await self.read_snapshot(scope_id)
        seal = current.consolidation_state.get('window_seals', {}).get(str(window_id))
        if seal is None:
            raise ConsolidationRuntimeError('CONSOLIDATION_WINDOW_UNAVAILABLE')
        state = reduce_events(await MemoryEventStore(self.session).replay(scope_id, through_event_id=seal['high_water_mark']))
        def refs(name):
            return tuple(SourceVersion(**{**thaw(ref), 'observed_at':
                datetime.fromisoformat(ref['observed_at'])}) for ref in seal[name])
        inputs, references, supports = refs('source_refs'), refs('reference_refs'), refs('support_refs')
        return WindowSnapshot(scope_id, datetime.fromisoformat(seal['start']), datetime.fromisoformat(seal['end']),
            datetime.fromisoformat(seal['frozen_at']), seal['high_water_mark'], inputs, references, supports,
            episodes={ref.memory_id: redact_submission(state['entries'][ref.memory_id]) for ref in inputs},
            references={ref.memory_id: redact_submission(state['entries'][ref.memory_id]) for ref in references},
            policy=seal['captured_policy'], vocabulary=seal['captured_vocabulary'], window_id=window_id,
            original_window_id=seal.get('original_window_id') or window_id,
            truncated=sum(row.get('kind') == 'episodic' and row.get('status') == 'active'
                and seal['start'] <= row['observed_at'] < seal['end'] for row in state['entries'].values()) > len(inputs))

    async def select_and_seal(self, token):
        from rag_mcp.services.memory_projection_store import ProjectionFailure
        from rag_mcp.services.memory_service import MemoryService
        pending = False
        async with self.commit_fence(token) as fence:
            current = await self.read_snapshot(token.scope_id)
            policy, profile = await self._validate_policy(token.scope_id, TrustedContext())
            now = await self._clock()
            consumed = {tuple(value['source_version']) for value in current.consolidation_state.get(
                'potential_source_outcomes', {}).values() if value.get('outcome') == 'consumed_on_complete'}
            for saved_id, seal in sorted(current.consolidation_state.get('window_seals', {}).items(), key=lambda pair: int(pair[0])):
                def still_unprocessed(ref):
                    row = current.entries.get(ref['memory_id'])
                    return row is not None and row.get('status') == 'active' and row.get('kind') == 'episodic' and (
                        row.get('memory_id'), row.get('source_event_id'), row.get('state_event_id') or row.get('source_event_id')) == (
                        ref['memory_id'], ref['source_event_id'], ref['state_event_id']) and (
                        ref['memory_id'], ref['source_event_id'], ref['state_event_id']) not in consumed and (
                        not row.get('expires_at') or datetime.fromisoformat(row['expires_at']) > now)
                if any(still_unprocessed(ref) for ref in seal['source_refs']):
                    retry = await self.retry_window(token.scope_id, int(saved_id))
                    await self._observe_locked(token, status='selecting', window={
                        'window_id': retry.window_id, 'start': retry.start.isoformat(), 'end': retry.end.isoformat(),
                        'high_water_mark': retry.high_water_mark}, input_event_ids=[ref.source_event_id for ref in retry.input_episode_refs],
                        reference_versions=[thaw(asdict(ref)) for ref in retry.reference_refs])
                    return retry
            window = select_window(current, policy=policy, now=now, token=token)
            if not window.input_episode_refs:
                await self._observe_locked(token, status='no_change', window=None, input_event_ids=[],
                    degradation_reasons=['input_budget_excluded' if window.truncated else 'empty_window'])
                return window
            latest_event = await self.session.scalar(select(func.max(MemoryEvent.event_id)).where(
                MemoryEvent.knowledge_scope_id == token.scope_id))
            if latest_event != current.high_water_mark:
                raise ConsolidationRuntimeError('CONSOLIDATION_PENDING_RECOVERY_REQUIRED')
            identifier = generate_id()
            payload = {'payload_version': 2, 'grant_type': 'consolidation_window',
                'start': window.start.isoformat(), 'end': window.end.isoformat(), 'frozen_at': window.frozen_at.isoformat(),
                'high_water_mark': window.high_water_mark, 'source_refs': [thaw(asdict(ref)) for ref in window.input_episode_refs],
                'reference_refs': [thaw(asdict(ref)) for ref in window.reference_refs],
                'support_refs': [thaw(asdict(ref)) for ref in window.support_refs], 'original_window_id': window.original_window_id,
                'captured_policy': policy.model_dump(), 'captured_vocabulary': profile.memory_link_vocabulary or [],
                'policy_hash': hashlib.sha256(json.dumps(policy.model_dump(), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
                'vocabulary_hash': memory_vocabulary_version(profile.memory_link_vocabulary or []),
                'control_adjudication': {'decision': 'seal_window', 'effect': 'control_only', 'rule_version': '013.window.1'},
                'eligibility_token': token.to_dict()}
            fields = {'event_id': identifier, 'aggregate_id': identifier, 'event_type': 'grant',
                'knowledge_scope_id': token.scope_id, 'payload': payload, 'actor': 'management',
                'request_id': str(uuid4()), 'occurred_at': now,
                'authority': {'source': 'consolidation_control'}, 'scope_meta': {'knowledge_scope_id': token.scope_id},
                'mutability': {'correction': 'append_event'}, 'provenance_meta': {'source': 'consolidation_control'},
                'recoverability': {'source': 'event_log'}, 'actionability': 'audit'}
            await self.session.execute(text("SELECT set_config('rag_memory.consolidation_token',:token,true)"),
                                       {'token': str(token.eligibility_id)})
            service = self.memory_service or MemoryService(self.session)
            service._ensure_vector_store()
            try:
                async with self.session.begin_nested():
                    await MemoryEventStore(self.session).append(MemoryEvent(**fields))
                    state = reduce_events(await MemoryEventStore(self.session).replay(token.scope_id))
                    await service.projections.materialize(state, token.scope_id, identifier)
                    await fence.validate_before_publish()
            except ProjectionFailure as error:
                if error.path == 'relation':
                    raise
                await MemoryEventStore(self.session).append(MemoryEvent(**fields))
                state = reduce_events(await MemoryEventStore(self.session).replay(token.scope_id))
                await service.projections.retain_failure(state, token.scope_id, identifier, error.path)
                await self._observe_locked(token, status='failed', degradation_reasons=['window_publication_pending'])
                # Retaining the control grant does not publish or consume its inputs.
                pending = True
            window = replace(window, window_id=identifier)
            if not pending:
                await self._observe_locked(token, status='selecting', window={
                    'window_id': identifier, 'start': window.start.isoformat(), 'end': window.end.isoformat(),
                    'high_water_mark': window.high_water_mark}, input_event_ids=[ref.source_event_id for ref in window.input_episode_refs],
                    reference_versions=[thaw(asdict(ref)) for ref in window.reference_refs])
        if pending:
            raise ConsolidationRuntimeError('CONSOLIDATION_WINDOW_PUBLICATION_PENDING')
        return window
