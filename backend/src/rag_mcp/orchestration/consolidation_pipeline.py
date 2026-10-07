"""Immutable boundaries for the offline consolidation pipeline."""
from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol

from rag_mcp.services.memory_reducer import require_reducer_state

PROPAGATION_MAX_DEPTH = 32
PROPAGATION_MAX_VISITED = 128
PROPAGATION_TRIGGER_KINDS = ('authority_event', 'evidence_revocation', 'support_expiry')


def __getattr__(name):
    """Re-export the adjudication context without a module-level import cycle."""
    if name == 'AdjudicationContext':
        from rag_mcp.services.consolidation_adjudicator import AdjudicationContext

        return AdjudicationContext
    raise AttributeError(name)


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value):
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def validate_contract(payload, validator):
    # JSON Schema's numeric comparisons alone do not reject Python NaN.
    try:
        json.dumps(payload, allow_nan=False)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid JSON contract value") from error
    validator.validate(payload)
    return freeze(payload)


@dataclass(frozen=True)
class SourceVersion:
    memory_id: int
    source_event_id: int
    state_event_id: int
    content_hash: str
    observed_at: datetime
    original_window_id: int | None = None

    @property
    def identity(self):
        return self.memory_id, self.source_event_id, self.state_event_id


@dataclass(frozen=True)
class WindowSnapshot:
    scope_id: int
    start: datetime
    end: datetime
    frozen_at: datetime
    high_water_mark: int
    input_episode_refs: tuple[SourceVersion, ...]
    reference_refs: tuple[SourceVersion, ...] = ()
    support_refs: tuple[SourceVersion, ...] = ()
    episodes: Mapping = field(default_factory=dict)
    references: Mapping = field(default_factory=dict)
    policy: Mapping = field(default_factory=dict)
    vocabulary: tuple = ()
    window_id: int | None = None
    original_window_id: int | None = None
    truncated: bool = False

    def __post_init__(self):
        for key in ('episodes', 'references', 'policy', 'vocabulary', 'input_episode_refs', 'reference_refs', 'support_refs'):
            object.__setattr__(self, key, freeze(getattr(self, key)))
        if any(value.tzinfo is None for value in (self.start, self.end, self.frozen_at)) or self.start > self.end:
            raise ValueError("window requires ordered timezone-aware timestamps")
        if set(ref.identity for ref in self.input_episode_refs) & set(ref.identity for ref in self.reference_refs):
            raise ValueError("references cannot be distiller sources")


@dataclass(frozen=True)
class CurrentSnapshot:
    scope_id: int
    high_water_mark: int
    entries: Mapping
    consolidation_state: Mapping
    vocabulary: tuple = ()
    quota_count: int = 0
    required_support: tuple = ()

    def __post_init__(self):
        for key in ('entries', 'consolidation_state', 'vocabulary', 'required_support'):
            object.__setattr__(self, key, freeze(getattr(self, key)))

    @classmethod
    def from_verified_state(cls, state, *, scope_id, high_water_mark, verified_complete, vocabulary=()):
        require_reducer_state(state)
        if verified_complete is not True:
            raise ValueError("selection requires verified complete authority")
        if any(row['knowledge_scope_id'] != scope_id for row in state['entries'].values()):
            raise ValueError("SCOPE_MISMATCH")
        return cls(scope_id, high_water_mark, state['entries'], state.get('consolidation_state', {}),
                   tuple(vocabulary), sum(row['status'] == 'active' and row.get('write_status', 'complete') == 'complete'
                                          for row in state['entries'].values()))


@dataclass(frozen=True)
class ProposalBatch:
    proposals: tuple
    deterministic_proposals: tuple = ()
    degraded: bool = False
    degradation_reasons: tuple[str, ...] = ()
    ttl_intents: tuple = ()
    model_and_version: str = ''
    usage: Mapping = field(default_factory=dict)

    def __post_init__(self):
        for key in ('proposals', 'deterministic_proposals', 'degradation_reasons', 'ttl_intents', 'usage'):
            object.__setattr__(self, key, freeze(getattr(self, key)))


@dataclass(frozen=True)
class Decision:
    decision_id: str
    decision: str
    reason_codes: tuple[str, ...]
    approved_effects: tuple = ()
    expected_versions: tuple[SourceVersion, ...] = ()
    source_outcomes: tuple = ()
    proof: Mapping = field(default_factory=dict)
    rule_version: str = '013.1'
    children: tuple = ()

    def __post_init__(self):
        for key in ('reason_codes', 'approved_effects', 'expected_versions', 'source_outcomes', 'proof', 'children'):
            object.__setattr__(self, key, freeze(getattr(self, key)))
        if self.decision not in ('accept', 'reject') or self.decision == 'reject' and (
            self.approved_effects or self.source_outcomes):
            raise ValueError("rejected decisions cannot carry effects")


@dataclass(frozen=True)
class CommitOutcome:
    status: str
    output_memory_ids: tuple[int, ...] = ()
    output_event_ids: tuple[int, ...] = ()
    pending_result_keys: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    failed_result_keys: tuple[str, ...] = ()

    def __post_init__(self):
        if self.status not in ('completed', 'pending', 'rejected', 'rolled_back', 'failure'):
            raise ValueError("invalid commit outcome")
        for key in ('output_memory_ids', 'output_event_ids', 'pending_result_keys', 'reason_codes', 'failed_result_keys'):
            object.__setattr__(self, key, tuple(getattr(self, key)))


_SUPPORT_HOOK_SEAL = object()


@dataclass(frozen=True)
class TrustedContext:
    execution_context: str = 'distiller_window'
    historical_source_refs: tuple = ()
    propagation_trigger: Mapping = field(default_factory=dict)
    _seal: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, 'historical_source_refs', freeze(self.historical_source_refs))
        object.__setattr__(self, 'propagation_trigger', freeze(self.propagation_trigger))
        if self.execution_context not in ('distiller_window', 'deterministic_propagation'):
            raise ValueError("invalid execution context")
        if self.execution_context == 'deterministic_propagation' and (
            self._seal is not _SUPPORT_HOOK_SEAL or not self.historical_source_refs or not self.propagation_trigger):
            raise PermissionError("TRUSTED_CONTEXT_REQUIRED")

    @property
    def trusted_support_hook(self):
        return self.execution_context == 'deterministic_propagation' and self._seal is _SUPPORT_HOOK_SEAL


class Propose(Protocol):
    async def __call__(self, window: WindowSnapshot, distiller: Any, *, current: CurrentSnapshot,
                       context: Any, policy: Any, now: datetime, provider: Any = None) -> ProposalBatch: ...


async def propose(window, distiller, *, current, context, policy, now, provider=None):
    """Prepare independent rules first, then accept only a complete model package.

    No effect is applied here. Both proposal sets still require pure adjudication;
    TTL intents use the same adjudicator's existing governed lifecycle path.
    """
    from jsonschema import Draft202012Validator, ValidationError

    from rag_mcp.agents.llm_client import safe_failure_code
    from rag_mcp.agents.memory_distiller import MemoryDistiller
    from rag_mcp.services.consolidation_runtime import ConsolidationUsage, DistillerProvider

    rules = deterministic_proposals(current, context=context, policy=policy, now=now)
    intents = ttl_intents(current, now=now)
    config = policy.consolidation
    reasons, proposals = [], ()
    usage = ConsolidationUsage().to_dict()
    model = distiller.model_and_version if distiller else ''
    if config is None:
        reasons.append('CONSOLIDATION_CONFIGURATION_REQUIRED')
    elif not policy.consolidation_enabled:
        reasons.append('CONSOLIDATION_DISABLED')
    elif config.max_llm_calls == 0:
        reasons.append('MODEL_BUDGET_DISABLED')
    elif distiller is None:
        reasons.append('MODEL_CONFIGURATION_REQUIRED')
    elif current.scope_id != window.scope_id or context.window != window:
        reasons.append('SCOPE_MISMATCH')
    else:
        outcome = await (provider or DistillerProvider()).run(
            distiller, {'window': replace(window, policy=policy.model_dump())}, timeout_s=config.llm_timeout_seconds)
        usage = outcome.usage
        if outcome.reason:
            reasons.append(outcome.reason)
        else:
            result = outcome.result
            if result.degraded or not result.schema_valid:
                # AgentBase may attach a prefix; never propagate arbitrary exception/body text.
                code = (result.error or '').removeprefix('execute() raised: ')
                reasons.append(code if safe_failure_code(code) else 'AGENT_EXECUTION_FAILED')
            try:
                validate_contract(result.output, Draft202012Validator(MemoryDistiller.NODE_SCHEMA))
                if len(result.output['proposals']) > config.max_proposals:
                    raise ValueError('proposal budget exceeded')
            except (ValueError, TypeError, RecursionError, ValidationError):
                reasons.append('FALLBACK_INVALID' if result.degraded else 'MODEL_SCHEMA_INVALID')
                package = {'proposals': []}
            else:
                package = result.output
            proposals = package['proposals']
    return ProposalBatch(proposals, rules, bool(reasons), tuple(dict.fromkeys(reasons)), intents, model, usage)


class SelectWindow(Protocol):
    def __call__(self, current: CurrentSnapshot, *, policy: Any, now: datetime,
                 start: datetime | None = None, token: Any = None) -> WindowSnapshot: ...


class Adjudicate(Protocol):
    def __call__(self, proposal: Mapping, current: CurrentSnapshot, policy: Any, vocabulary: tuple,
                 quota: Mapping, context: TrustedContext, now: datetime) -> Decision: ...


class CommitApproved(Protocol):
    async def __call__(self, decisions: tuple[Decision, ...], token: Any) -> CommitOutcome: ...


async def run_pipeline(runtime, token, *, distiller, select=None, propose_stage=None, adjudicate_stage=None, commit_stage=None):
    from rag_mcp.services.consolidation_adjudicator import AdjudicationContext, adjudicate_batch
    from rag_mcp.services.memory_policy import MemoryPolicy

    window = await (select or runtime.select_and_seal)(token)
    if not window.input_episode_refs:
        return CommitOutcome('rejected', reason_codes=('empty_window',))
    current = await runtime.read_snapshot(token.scope_id)
    policy = MemoryPolicy.model_validate(thaw(window.policy))
    context = AdjudicationContext(window=window)
    now = await runtime._clock()
    await runtime.session.rollback()
    await runtime.observe(token, status='proposing')
    import asyncio
    try:
        batch = await (propose_stage or propose)(window, distiller, current=current, context=context, policy=policy, now=now)
    except asyncio.CancelledError:
        await runtime.observe(token, status='interrupted', degradation_reasons=['PROVIDER_INTERRUPTED'])
        raise
    inferences = {}
    for proposal in batch.proposals:
        if proposal.get('action') in ('extract_fact', 'distill_procedure'):
            refs = proposal['source_refs']
            inferences[proposal['proposal_id']] = {'inference_meta': {
                'source': 'memory_distiller', 'confidence': proposal['confidence'],
                'model_version': batch.model_and_version or 'injected_distiller', 'time': window.frozen_at.isoformat(),
                'supporting_evidence': [f"memory:{r['memory_id']}" for r in refs]},
                'source_lineage': [{key: ref[key] for key in ('memory_id', 'source_event_id', 'content_hash')} for ref in refs],
                'fact_anchors': list(proposal.get('evidence_refs', ()))}
    context = replace(context, inferences=inferences)
    from rag_mcp.services.consolidation_commit import read_evidence
    from rag_mcp.services.consolidation_runtime import ConsolidationUsage
    identifiers = {identifier for p in (*batch.deterministic_proposals, *batch.proposals) for identifier in p.get('evidence_refs', ())}
    identifiers.update(identifier for entry in current.entries.values() for identifier in entry.get('evidence_refs', ()))
    support = await read_evidence(runtime.session, identifiers)
    await runtime.session.rollback()
    context = replace(context, support_facts=support, support_versions=support)
    batch = replace(batch, usage={**ConsolidationUsage().to_dict(), **thaw(batch.usage)})
    decisions = (adjudicate_stage or adjudicate_batch)(batch, current, policy, current.vocabulary,
        {'count': current.quota_count, 'limit': policy.per_scope_memory_quota}, context, now)
    await runtime.observe(token, status='adjudicating', provider_usage=thaw(batch.usage),
        degradation_reasons=list(batch.degradation_reasons), adjudications=[{
            'decision_id': d.decision_id, 'decision': d.decision, 'reason_codes': list(d.reason_codes),
            'publication': 'not_committed'} for d in decisions.decisions])
    outcome = await (commit_stage or runtime.memory_service.commit_approved)(
        decisions, token, runtime=runtime, batch=batch, context=context)
    await runtime.observe_result(token, decisions, outcome, batch=batch)
    return outcome


def deterministic_proposals(current, *, context, policy, now):
    """Generate only mechanically provable work; approval remains adjudicate's job."""
    from rag_mcp.services.consolidation_adjudicator import Rejection, _correction, equivalent, memory_ref, stable_key

    if policy.consolidation is None or context.window is None:
        return ()
    sources = [current.entries.get(v.memory_id) for v in context.window.input_episode_refs]
    sources = [r for r in sources if r and r.get('status') == 'active' and r.get('kind') == 'episodic']
    if not sources:
        return ()
    source_refs = [memory_ref(sources[0])]
    refs = context.window.input_episode_refs + context.window.reference_refs
    targets = [current.entries[v.memory_id] for v in refs if v.memory_id in current.entries]
    targets.sort(key=lambda row: row['memory_id'])
    proposals, merged = [], set()
    for index, keeper in enumerate(targets):
        if keeper['memory_id'] in merged:
            continue
        duplicates = [r for r in targets[index + 1:] if r['memory_id'] not in merged and equivalent(keeper, r)]
        if duplicates:
            duplicates = duplicates[:32]
            merged.update(r['memory_id'] for r in duplicates)
            proposals.append({'action': 'merge_duplicate', 'survivor_ref': memory_ref(keeper),
                              'duplicate_refs': [memory_ref(r) for r in duplicates],
                              'equivalence_basis': 'exact content and compatible authority metadata'})
    for target in targets:
        if target['memory_id'] in merged:
            continue
        correction_found = False
        for correcting in targets:
            try:
                _correction(target, correcting, current, context)
            except Rejection:
                continue
            proposals.append({'action': 'invalidate_contradiction', 'target_ref': memory_ref(target),
                              'correcting_ref': memory_ref(correcting),
                              'contradiction_basis': 'authoritative single-pointer correction'})
            correction_found = True
            break
        if correction_found:
            continue
        for required in target.get('required_support', ()):
            support = context.support_facts.get(required.get('evidence_id'), {})
            if support.get('status') == 'withdrawn' and support.get('version_id') == required.get('version_id'):
                proposals.append({'action': 'invalidate_contradiction', 'target_ref': memory_ref(target),
                                  'correcting_ref': None, 'contradiction_basis': 'current required support withdrawn'})
                break
    for proposal in proposals:
        proposal.update(source_refs=source_refs, confidence=1., evidence_refs=[], justification='deterministic rule')
        proposal['proposal_id'] = 'r' + stable_key(proposal)[:63]
    return freeze(proposals)


_TTL_SEAL = object()


@dataclass(frozen=True)
class TTLIntent:
    scope_id: int
    target_ref: Mapping
    retention_stage: str
    _seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, 'target_ref', freeze(self.target_ref))


def ttl_intents(current, *, now):
    from rag_mcp.services.consolidation_adjudicator import memory_ref

    if now.tzinfo is None:
        raise ValueError('timezone-aware clock required')
    transitions = {'active': 'compressed', 'compressed': 'archived', 'archived': 'tombstone'}
    return tuple(TTLIntent(current.scope_id, memory_ref(row), transitions[row['retention_stage']], _TTL_SEAL)
                 for _, row in sorted(current.entries.items())
                 if row.get('knowledge_scope_id') == current.scope_id and row.get('status') == 'active'
                 and row.get('write_status', 'complete') == 'complete'
                 and row.get('retention_stage') in transitions and row.get('expires_at')
                 and datetime.fromisoformat(row['expires_at']) <= now)


def adjudicate_ttl(intent, current, *, now):
    from rag_mcp.services.consolidation_adjudicator import adjudicate_lifecycle, reject

    if not isinstance(intent, TTLIntent) or intent._seal is not _TTL_SEAL:
        return reject('TRUSTED_CONTEXT_REQUIRED')
    return adjudicate_lifecycle(intent, current, now=now)


def pending_input_count(current: CurrentSnapshot, *, now) -> int:
    """Eligible unconsumed episodic inputs in the verified complete prefix.

    This is the maintenance-side re-verification of a volume hint: the same
    filters the selector applies (four-state eligibility, complete write,
    high-water prefix, consumed registry, expiry and content safety) minus the
    per-run batch/character budget, so a raw projection row count can never
    stand in for real pending work.
    """
    from rag_mcp.services.memory_validators import detect_submission, redact_submission

    if now.tzinfo is None:
        raise ValueError('timezone-aware clock required')
    consumed = {tuple(value['source_version']) for value in current.consolidation_state.get(
        'potential_source_outcomes', {}).values() if value.get('outcome') == 'consumed_on_complete'}
    count = 0
    for identifier, frozen in current.entries.items():
        row = thaw(frozen)
        source = row.get('source_event_id')
        state = row.get('state_event_id') or source
        if (row.get('status') != 'active' or row.get('knowledge_scope_id') != current.scope_id
                or row.get('kind') != 'episodic' or row.get('write_status', 'complete') != 'complete'
                or not source or source > current.high_water_mark or state > current.high_water_mark
                or (identifier, source, state) in consumed):
            continue
        if any(row.get(key) and datetime.fromisoformat(row[key]) <= now for key in ('expires_at', 'valid_to')):
            continue
        if datetime.fromisoformat(row['observed_at']) >= now:
            continue
        cleaned = redact_submission(row)
        if detect_submission({**cleaned, 'content': cleaned.get('content_text', '')}).status != 'active':
            continue
        count += 1
    return count


def select_window(current: CurrentSnapshot, *, policy, now, start=None, token=None,
                  consumed_versions=(), incomplete_memory_ids=(), original_window=None) -> WindowSnapshot:
    """Select bounded read sets from an already verified authority prefix."""
    from rag_mcp.services.memory_validators import detect_submission, redact_submission

    config = policy.consolidation
    if config is None:
        raise ValueError('CONSOLIDATION_CONFIGURATION_REQUIRED')
    if now.tzinfo is None:
        raise ValueError('timezone-aware clock required')
    if token is not None and token.scope_id != current.scope_id:
        raise ValueError('SCOPE_MISMATCH')
    consumed = set(tuple(value) for value in consumed_versions)
    consumed.update(tuple(value['source_version']) for value in current.consolidation_state.get(
        'potential_source_outcomes', {}).values() if value.get('outcome') == 'consumed_on_complete')
    incomplete = set(incomplete_memory_ids)
    eligible = []
    for identifier, frozen in current.entries.items():
        row = thaw(frozen)
        source = row.get('source_event_id')
        state = row.get('state_event_id') or source
        if (row.get('status') != 'active' or row.get('knowledge_scope_id') != current.scope_id
            or identifier in incomplete or row.get('write_status', 'complete') != 'complete'
            or not source or source > current.high_water_mark or state > current.high_water_mark
            or (identifier, source, state) in consumed):
            continue
        expires_at = row.get('expires_at')
        valid_to = row.get('valid_to')
        if any(value and datetime.fromisoformat(value) <= now for value in (expires_at, valid_to)):
            continue
        observed = datetime.fromisoformat(row['observed_at'])
        cleaned = redact_submission(row)
        checked = detect_submission({**cleaned, 'content': cleaned.get('content_text', '')})
        if checked.status != 'active':
            continue
        reference = SourceVersion(identifier, source, state, row.get('content_hash', ''), observed)
        eligible.append((reference, cleaned))
    episode_rows = [(ref, row) for ref, row in eligible if row.get('kind') == 'episodic' and ref.observed_at < now]
    checkpoint = current.consolidation_state.get('potential_checkpoint')
    earliest = min((ref.observed_at for ref, _ in episode_rows), default=now)
    if start is None:
        start = min(datetime.fromisoformat(checkpoint), earliest) if checkpoint else earliest
    end, high_water = now, current.high_water_mark
    window_id = original_id = None
    if original_window is not None:
        start, end = original_window.start, original_window.end
        now, high_water = original_window.frozen_at, original_window.high_water_mark
        window_id = original_window.window_id
        original_id = original_window.original_window_id or window_id
    episode_rows = sorted(((ref, row) for ref, row in episode_rows
                           if start <= ref.observed_at < end and ref.source_event_id <= high_water),
                          key=lambda pair: (pair[0].observed_at, pair[0].source_event_id))
    reference_rows = sorted(((ref, row) for ref, row in eligible if row.get('kind') in ('semantic', 'procedural')),
                            key=lambda pair: pair[0].memory_id)
    inputs, references, chars = [], [], 0
    for pair in episode_rows:
        if len(inputs) >= config.batch_size:
            break
        size = len(json.dumps(pair[1], sort_keys=True, ensure_ascii=False, allow_nan=False))
        if chars + size > config.max_input_chars:
            continue
        inputs.append(pair)
        chars += size
    for pair in reference_rows:
        if len(references) >= config.reference_limit:
            break
        size = len(json.dumps(pair[1], sort_keys=True, ensure_ascii=False, allow_nan=False))
        if chars + size > config.max_input_chars:
            continue
        references.append(pair)
        chars += size
    return WindowSnapshot(current.scope_id, start, end, now, high_water,
        tuple(ref for ref, _ in inputs), tuple(ref for ref, _ in references),
        episodes={ref.memory_id: row for ref, row in inputs}, references={ref.memory_id: row for ref, row in references},
        policy=policy.model_dump(), vocabulary=current.vocabulary, window_id=window_id,
        original_window_id=original_id, truncated=len(inputs) < len(episode_rows))


def support_maintenance_context(*, historical_source_refs, propagation_trigger,
                                support_facts=None, support_versions=None):
    """Trusted support hook: the only constructor of a propagation context.

    Writer maintenance/governance code calls this; REST, MCP, proposal payloads
    and model output cannot, because the hook seal never leaves this module.
    """
    from rag_mcp.services.consolidation_adjudicator import AdjudicationContext

    return AdjudicationContext(
        execution_context='deterministic_propagation',
        historical_source_refs=tuple(historical_source_refs or ()),
        propagation_trigger=dict(propagation_trigger or {}),
        support_facts=dict(support_facts or {}),
        support_versions=dict(support_versions or {}),
        _seal=_SUPPORT_HOOK_SEAL)


def _live_supports(row):
    """Unique live-dependency out-edges captured at approval time."""
    edges = []
    for key in sorted((row or {}).get('approved_links', {})):
        link = row['approved_links'][key]
        if (link.get('category') == 'live_dependency' and link.get('propagation') == 'to_to_from'
                and link.get('from_id') == row.get('memory_id')):
            edges.append((link.get('to_id'), link.get('relation_type')))
    return edges


def _propagation_target(row, current, now):
    if row is None or row.get('knowledge_scope_id') != current.scope_id:
        return False
    if row.get('status') != 'active' or row.get('write_status', 'complete') != 'complete':
        return False
    try:
        if any(row.get(key) and datetime.fromisoformat(row[key]) <= now for key in ('expires_at', 'valid_to')):
            return False
        if row.get('valid_from') and datetime.fromisoformat(row['valid_from']) > now:
            return False
    except (TypeError, ValueError):
        return False
    return True


def propagation_trigger_material(trigger):
    """Lower a trusted in-context trigger to its exact schema material."""
    keys = ('kind', 'event_id', 'evidence_id', 'version', 'observed_at', 'proof')
    missing = [key for key in keys if key not in trigger]
    if missing:
        raise ValueError('PROPAGATION_TRIGGER_INVALID')
    kind = trigger['kind']
    if kind not in PROPAGATION_TRIGGER_KINDS:
        raise ValueError('PROPAGATION_TRIGGER_INVALID')
    proof = trigger['proof']
    if not isinstance(proof, Mapping) or not proof:
        raise ValueError('PROPAGATION_TRIGGER_INVALID')
    if trigger['event_id'] is None and trigger['evidence_id'] is None:
        raise ValueError('PROPAGATION_TRIGGER_INVALID')
    try:
        observed = datetime.fromisoformat(trigger['observed_at'])
    except (TypeError, ValueError):
        raise ValueError('PROPAGATION_TRIGGER_INVALID') from None
    if observed.tzinfo is None:
        raise ValueError('PROPAGATION_TRIGGER_INVALID')
    return freeze({'kind': kind, 'event_id': trigger['event_id'], 'evidence_id': trigger['evidence_id'],
                   'version': str(trigger['version']), 'observed_at': trigger['observed_at'],
                   'proof': thaw(proof)})


def plan_propagation(current, *, context, now):
    """Bounded reverse live-dependency plan; no Distiller, no source consumption."""
    from rag_mcp.services.consolidation_adjudicator import memory_ref, stable_key

    if not getattr(context, 'trusted_support_hook', False):
        raise PermissionError('TRUSTED_CONTEXT_REQUIRED')
    if now.tzinfo is None:
        raise ValueError('timezone-aware clock required')
    trigger = thaw(context.propagation_trigger or {})
    material_trigger = thaw(propagation_trigger_material(trigger))
    proof = dict(trigger.get('proof') or {})
    reference = dict(trigger.get('target_ref') or {})
    root = reference.get('memory_id')
    if isinstance(root, bool) or not isinstance(root, int):
        raise TypeError('PROPAGATION_TRIGGER_INVALID')
    live = proof.get('kind') == 'live_dependency'
    if live:
        if (isinstance(proof.get('cause_memory_id'), bool) or not isinstance(proof.get('cause_memory_id'), int)
                or not isinstance(proof.get('relation_type'), str) or not proof['relation_type']):
            raise ValueError('PROPAGATION_TRIGGER_INVALID')
        anchor, relation = proof['cause_memory_id'], proof['relation_type']
    else:
        anchor, relation = None, None
    if anchor is not None and proof.get('memory_id') is not None and proof['memory_id'] != root:
        raise ValueError('PROPAGATION_TRIGGER_INVALID')

    visited, depths, frontier, proposals = set(), {}, [], []
    queue = deque([(root, anchor, relation, 1)])
    while queue:
        mid, cause_id, relation_type, depth = queue.popleft()
        if mid in visited:
            continue
        if len(visited) >= PROPAGATION_MAX_VISITED:
            frontier.append(mid)
            continue
        visited.add(mid)
        depths[mid] = depth
        row = current.entries.get(mid)
        if cause_id is not None and (cause_id, relation_type) not in _live_supports(row):
            # Only a declared live-dependency dependent carries lifecycle impact;
            # association and historical lineage never propagate.
            continue
        within = depth <= PROPAGATION_MAX_DEPTH
        if not within:
            frontier.append(mid)
        elif _propagation_target(row, current, now):
            # A non-live trigger authorizes its own root through the current
            # evidence/authority proof; descendants carry the live-edge claim.
            dependency = ({'kind': 'live_dependency', 'cause_memory_id': cause_id, 'relation_type': relation_type}
                          if cause_id is not None else None)
            proposal = {
                'proposal_id': 'm' + stable_key({'scope': current.scope_id, 'target': memory_ref(row),
                                                 'trigger': material_trigger, 'dependency': dependency})[:63],
                'action': 'invalidate_contradiction', 'target_ref': memory_ref(row), 'correcting_ref': None,
                'contradiction_basis': 'necessary support denial reached this dependent',
                'source_refs': [], 'confidence': 1., 'evidence_refs': [],
                'justification': 'deterministic propagation'}
            if dependency is not None:
                proposal['propagation_proof'] = dependency
            proposals.append(proposal)
        for child, child_relation in _live_supports_inverse(current, mid):
            queue.append((child, mid, child_relation, depth + 1))
    depths_of_proposals = [depths[proposal['target_ref']['memory_id']] for proposal in proposals]
    material = {'trigger': material_trigger, 'visited_memory_ids': sorted(visited),
                'depth': max(depths_of_proposals, default=0), 'frontier_memory_ids': sorted(set(frontier)),
                'vocabulary_version': stable_key(list(current.vocabulary))}
    material['continuation_key'] = stable_key({'scope': current.scope_id, 'material': material})
    for proposal in proposals:
        # The permanent continuation material travels with the approved effect so
        # the commit path never has to re-plan or re-read authority.
        proposal['propagation_material'] = material
    return proposals, material


def _live_supports_inverse(current, target_id):
    dependents = []
    for mid, row in current.entries.items():
        if row.get('knowledge_scope_id') != current.scope_id or mid == target_id:
            continue
        for to_id, relation in _live_supports(row):
            if to_id == target_id:
                dependents.append((mid, relation))
    dependents.sort()
    return dependents


async def run_propagation(runtime, token, *, context):
    """Adjudicate and publish one deterministic propagation wave.

    Shares the ordinary scope eligibility, writer lease, token fence and final
    publication path; it never selects a window, calls the Distiller, creates,
    merges or derives links/context/candidates, and never consumes a source.
    """
    from rag_mcp.models.domain_profile import DomainProfile
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    from rag_mcp.services.consolidation_adjudicator import adjudicate_batch
    from rag_mcp.services.consolidation_commit import read_evidence
    from rag_mcp.services.memory_policy import MemoryPolicy

    if not getattr(context, 'trusted_support_hook', False):
        from rag_mcp.services.consolidation_runtime import ConsolidationRuntimeError

        raise ConsolidationRuntimeError('TRUSTED_CONTEXT_REQUIRED')
    current = await runtime.read_snapshot(token.scope_id)
    scope = await runtime.session.get(KnowledgeScope, token.scope_id, populate_existing=True)
    profile = await runtime.session.get(DomainProfile, scope.domain_key, populate_existing=True)
    policy = MemoryPolicy.model_validate(profile.memory_policy or {})
    now = await runtime._clock()
    proposals, material = plan_propagation(current, context=context, now=now)
    identifiers = {attribution['evidence_id'] for row in current.entries.values()
                   for attribution in (row.get('adjudication') or {}).get('evidence_attributions', ()) or ()}
    identifiers.update(identifier for proposal in proposals for identifier in proposal.get('evidence_refs', ()))
    support = await read_evidence(runtime.session, identifiers) if identifiers else {}
    await runtime.session.rollback()
    context = replace(context, support_facts=support, support_versions=support)
    from rag_mcp.services.consolidation_runtime import ConsolidationUsage

    usage = ConsolidationUsage().to_dict()
    # No model runs during maintenance: usage is an explicit actual zero.
    usage.update(source='actual', input_tokens=0, output_tokens=0, cost_usd=0)
    batch = ProposalBatch((), tuple(proposals), model_and_version='deterministic', usage=usage)
    decisions = adjudicate_batch(batch, current, policy, current.vocabulary,
        {'count': current.quota_count, 'limit': policy.per_scope_memory_quota}, context, now)
    outcome = await runtime.memory_service.commit_approved(decisions, token, runtime=runtime,
                                                           batch=batch, context=context)
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntimeError

    fence_lost = any(code in ('ELIGIBILITY_LOST', 'WRITER_LEASE_LOST') for code in outcome.reason_codes)
    if not fence_lost and not outcome.output_event_ids and material['visited_memory_ids']:
        try:
            # A wave with no lifecycle effect still persists its continuation
            # material as a trusted control grant, never as an empty success.
            await runtime.append_propagation_seal(token, material, context=context)
        except ConsolidationRuntimeError:
            fence_lost = True
        if not outcome.reason_codes:
            reasons = tuple(dict.fromkeys(code for decision in decisions.decisions
                                          for child in (decision, *decision.children)
                                          if child.decision == 'reject' for code in child.reason_codes))
            outcome = replace(outcome, reason_codes=reasons or ('NO_PROPAGATION_EFFECT',))
    try:
        await runtime.observe_result(token, decisions, outcome, batch=batch)
    except ConsolidationRuntimeError:
        pass
    return outcome
