"""Immutable boundaries for the offline consolidation pipeline."""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol

from rag_mcp.services.memory_reducer import require_reducer_state


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
                   tuple(vocabulary), sum(row['status'] == 'active' for row in state['entries'].values()))


@dataclass(frozen=True)
class ProposalBatch:
    proposals: tuple
    deterministic_proposals: tuple = ()
    degraded: bool = False
    degradation_reasons: tuple[str, ...] = ()

    def __post_init__(self):
        for key in ('proposals', 'deterministic_proposals', 'degradation_reasons'):
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

    def __post_init__(self):
        for key in ('reason_codes', 'approved_effects', 'expected_versions', 'source_outcomes', 'proof'):
            object.__setattr__(self, key, freeze(getattr(self, key)))
        if self.decision not in ('accept', 'reject') or self.decision == 'reject' and self.approved_effects:
            raise ValueError("rejected decisions cannot carry effects")


@dataclass(frozen=True)
class CommitOutcome:
    status: str
    output_memory_ids: tuple[int, ...] = ()
    output_event_ids: tuple[int, ...] = ()
    pending_result_keys: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self):
        if self.status not in ('completed', 'pending', 'rejected', 'rolled_back', 'failure'):
            raise ValueError("invalid commit outcome")
        for key in ('output_memory_ids', 'output_event_ids', 'pending_result_keys', 'reason_codes'):
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
    def __call__(self, window: WindowSnapshot, distiller: Any) -> ProposalBatch: ...


class SelectWindow(Protocol):
    def __call__(self, current: CurrentSnapshot, *, policy: Any, now: datetime,
                 start: datetime | None = None, token: Any = None) -> WindowSnapshot: ...


class Adjudicate(Protocol):
    def __call__(self, proposal: Mapping, current: CurrentSnapshot, policy: Any, vocabulary: tuple,
                 quota: Mapping, context: TrustedContext, now: datetime) -> Decision: ...


class CommitApproved(Protocol):
    async def __call__(self, decisions: tuple[Decision, ...], token: Any) -> CommitOutcome: ...


def select_window(current: CurrentSnapshot, *, policy, now, start=None, token=None,
                  consumed_versions=(), incomplete_memory_ids=(), original_window=None) -> WindowSnapshot:
    """Select bounded read sets from an already verified authority prefix."""
    from rag_mcp.services.memory_validators import redact_submission, detect_submission

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
                            key=lambda pair: pair[0].memory_id)[:config.reference_limit]
    inputs, references, chars = [], [], 0
    for pair in episode_rows[:config.batch_size]:
        size = len(json.dumps(pair[1], sort_keys=True, ensure_ascii=False, allow_nan=False))
        if chars + size > config.max_input_chars:
            break
        inputs.append(pair)
        chars += size
    for pair in reference_rows:
        size = len(json.dumps(pair[1], sort_keys=True, ensure_ascii=False, allow_nan=False))
        if chars + size > config.max_input_chars:
            break
        references.append(pair)
        chars += size
    return WindowSnapshot(current.scope_id, start, end, now, high_water,
        tuple(ref for ref, _ in inputs), tuple(ref for ref, _ in references),
        episodes={ref.memory_id: row for ref, row in inputs}, references={ref.memory_id: row for ref, row in references},
        policy=policy.model_dump(), vocabulary=current.vocabulary, window_id=window_id,
        original_window_id=original_id, truncated=len(inputs) < len(episode_rows))
