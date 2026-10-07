"""013 T091: record/replay safety for the frozen comparison cache.

The frozen comparison runs every arm twice from the same original
unconsolidated authority: a record round that performs the real model calls and
stores both successes and failures, and a replay round that must consume
exactly those recorded outcomes with no provider transport at all
(evaluation-contract.md "Cache/record/replay").

This module owns the pieces both rounds share:

* the exact ``(model, system, user)`` cache key, byte-compatible with the
  T070 ``AGENTIC_LLM_CACHE_PATH`` entries the 012 evaluation already uses;
* the sealed cache manifest and its read-only audit, which reports
  missing/corrupt/version-mismatched entries instead of repairing them;
* the transport denial gate: during a replay a cache miss is denied and
  counted, never sent to the provider and never written back;
* the round-comparison tolerances (non-latency drift <= 1 %, safety exact) and
  the original-unconsolidated start predicate.

Nothing here publishes, installs or mutates policy; it is evaluation plumbing.
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

CACHE_ENTRY_VERSION = '013.cache.1'
CACHE_MANIFEST_VERSION = '013.cache.1'
PARSER_VERSION = 'strict-v1'
REPLAY_DENIED_REASON = 'PROVIDER_NETWORK_ERROR'
NON_LATENCY_TOLERANCE = 0.01
PROVIDER_USAGE_KEYS = ('embedding_calls', 'rerank_calls', 'llm_calls',
                       'llm_prompt_chars', 'llm_completion_chars')
_READ_STATUSES = ('missing', 'corrupt', 'version_mismatch')


def cache_key(model, system_prompt: str, user_text: str) -> str:
    """Exact (model, system, user) key; never contains run/request/lease IDs."""
    canonical = json.dumps({'model': model, 'system': system_prompt, 'user': user_text},
                           sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def strict_cache_dir(cache_dir) -> Path:
    return Path(cache_dir) / PARSER_VERSION


def strict_entry_path(cache_dir, key: str) -> Path:
    return strict_cache_dir(cache_dir) / f'{key}.json'


def read_strict_entry(path):
    """Read one frozen entry without repairing it: (status, entry)."""
    path = Path(path)
    if not path.is_file():
        return 'missing', None
    try:
        entry = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        return 'corrupt', None
    if not isinstance(entry, dict) or 'reason' not in entry:
        return 'corrupt', None
    if entry.get('parser') != PARSER_VERSION:
        return 'version_mismatch', None
    if entry['reason'] is not None and not isinstance(entry['reason'], str):
        return 'corrupt', None
    if entry['reason'] is None and not isinstance(entry.get('output'), dict):
        return 'corrupt', None
    return 'ok', entry


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def body_digest(entry) -> str | None:
    """Body identity of a recorded outcome.

    Both a success body and a recorded failure reason are pinned, so a replay
    that returns a different reason (or a regenerated body) is detectable.
    """
    if not isinstance(entry, dict):
        return None
    if entry.get('reason') is None:
        if not isinstance(entry.get('output'), dict):
            return None
        material = {'output': entry['output']}
    else:
        material = {'reason': entry['reason']}
    return _sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode('utf-8'))


@dataclass
class ReplaySession:
    """Accounting for one round; denies transport and freezes cached bytes in replay."""

    mode: str
    denials: int = 0
    refused_writes: int = 0
    hits: int = 0
    misses: int = 0

    @property
    def replaying(self) -> bool:
        return self.mode == 'replay'


_active_session: ContextVar = ContextVar('consolidation_replay_session', default=None)


def current_session():
    return _active_session.get()


@contextmanager
def replay_session(mode: str):
    if mode not in ('record', 'replay'):
        raise ValueError('unknown comparison round mode')
    session = ReplaySession(mode=mode)
    token = _active_session.set(session)
    try:
        yield session
    finally:
        _active_session.reset(token)


def transport_denied() -> bool:
    """True when a real LLM transport attempt must be denied and counted."""
    session = _active_session.get()
    if session is None or not session.replaying:
        return False
    session.denials += 1
    return True


def cache_write_frozen() -> bool:
    """True when a cached byte must not be rewritten (replay keeps record bytes)."""
    session = _active_session.get()
    if session is None or not session.replaying:
        return False
    session.refused_writes += 1
    return True


# The record round's runner observes every persisted entry so the sealed manifest
# lists exactly the keys the comparison actually attempted (never a guess).  The
# observer is process-wide because the real persistence call happens inside the
# provider worker thread, which never inherits a context variable set by the
# caller; the runner is single-threaded between rounds, and a lock keeps the
# set/restore pair atomic.
_cache_observer: Callable[[str, dict], None] | None = None
_cache_observer_lock = threading.Lock()


def current_cache_observer():
    return _cache_observer


@contextmanager
def cache_observation(callback: Callable[[str, dict], None]):
    global _cache_observer
    with _cache_observer_lock:
        previous, _cache_observer = _cache_observer, callback
    try:
        yield
    finally:
        with _cache_observer_lock:
            _cache_observer = previous


def observe_cache_write(key: str, document: dict) -> None:
    observer = _cache_observer
    if observer is not None:
        observer(key, document)


def build_manifest(cache_dir, keys, *, model_version, dataset_hash, snapshot_hash, data_hash,
                   parser_version: str = PARSER_VERSION) -> dict:
    """Seal the record round's exact cache identity; never overwrites another manifest."""
    entries = []
    recorded_success = 0
    recorded_failure = 0
    for key in keys:
        path = strict_entry_path(cache_dir, key)
        status, entry = read_strict_entry(path)
        record = {'key': key, 'read_status': status, 'status': None,
                  'parser_version': parser_version, 'entry_sha256': None, 'body_sha256': None}
        if status == 'ok':
            record['parser_version'] = entry.get('parser')
            record['entry_sha256'] = _sha256(path.read_bytes())
            record['body_sha256'] = body_digest(entry)
            if entry['reason'] is None:
                record['status'] = 'success'
                recorded_success += 1
            else:
                record['status'] = 'failure'
                recorded_failure += 1
        entries.append(record)
    return {'manifest_version': CACHE_MANIFEST_VERSION, 'parser_version': parser_version,
            'cache_dir': str(cache_dir), 'model_version': model_version,
            'dataset_hash': dataset_hash, 'snapshot_hash': snapshot_hash, 'data_hash': data_hash,
            'expected_keys': len(entries), 'recorded_success': recorded_success,
            'recorded_failure': recorded_failure, 'entries': entries}


def audit_cache(cache_dir, manifest) -> dict:
    """Read-only audit of a sealed manifest; missing/corrupt/version are reported, not fixed."""
    records = list(manifest.get('entries') or ())
    counts = {'expected_keys': len(records), 'matched': 0, 'missing': 0, 'corrupt': 0,
              'version_mismatch': 0, 'recorded_success': 0, 'recorded_failure': 0, 'keys': {}}
    sealed_parser = manifest.get('parser_version', PARSER_VERSION)
    for record in records:
        key = record['key']
        path = strict_entry_path(cache_dir, key)
        status, entry = read_strict_entry(path)
        if status == 'ok':
            if sealed_parser != entry.get('parser') or record.get('parser_version') != entry.get('parser'):
                status = 'version_mismatch'
            elif record.get('entry_sha256') != _sha256(path.read_bytes()) or record.get('body_sha256') != body_digest(entry):
                status = 'corrupt'
        counts['keys'][key] = status
        if status == 'ok':
            counts['matched'] += 1
            if record.get('status') == 'success':
                counts['recorded_success'] += 1
            elif record.get('status') == 'failure':
                counts['recorded_failure'] += 1
        elif status in _READ_STATUSES:
            counts[status] += 1
    counts['evidence_complete'] = bool(
        counts['expected_keys'] and counts['matched'] == counts['expected_keys']
        and counts['missing'] == 0 and counts['corrupt'] == 0 and counts['version_mismatch'] == 0)
    return counts


def _field(receipt, name):
    if isinstance(receipt, dict):
        return receipt.get(name)
    return getattr(receipt, name, None)


def _sum_or_none(receipts, name):
    """Unknown provider usage stays null; it is never reported as a measured zero."""
    values = [_field(receipt, name) for receipt in receipts]
    if not values or any(value is None for value in values):
        return None
    return sum(values)


def aggregate_usage(receipts, *, source: str, latency_ms=None) -> dict:
    """Shape one round's usage for the report; replay adds zero provider usage."""
    receipts = list(receipts)
    provider = dict.fromkeys(PROVIDER_USAGE_KEYS, 0)
    if source == 'replay_zero':
        return {'source': 'replay_zero', 'provider_usage': provider, 'input_tokens': 0,
                'output_tokens': 0, 'cost_usd': 0, 'latency_ms': latency_ms}
    for receipt in receipts:
        provider['llm_calls'] += _field(receipt, 'transport_calls') or 0
        provider['llm_prompt_chars'] += _field(receipt, 'prompt_chars') or 0
        provider['llm_completion_chars'] += _field(receipt, 'completion_chars') or 0
    return {'source': source, 'provider_usage': provider,
            'input_tokens': _sum_or_none(receipts, 'input_tokens'),
            'output_tokens': _sum_or_none(receipts, 'output_tokens'),
            'cost_usd': _sum_or_none(receipts, 'cost_usd'), 'latency_ms': latency_ms}


def non_latency_drift(recorded, replayed):
    """Maximum relative drift over non-latency metrics; None when nothing is comparable."""
    drifts = []
    for key, before in recorded.items():
        if 'latency' in key.lower() or key not in replayed:
            continue
        after = replayed[key]
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            continue
        if before == 0:
            drifts.append(0.0 if after == 0 else float('inf'))
        else:
            drifts.append(abs(after - before) / abs(before))
    return max(drifts) if drifts else None


def within_non_latency_tolerance(recorded, replayed, tolerance: float = NON_LATENCY_TOLERANCE) -> bool:
    drift = non_latency_drift(recorded, replayed)
    return drift is not None and drift <= tolerance


def safety_exact_match(recorded, replayed) -> bool:
    """Safety metrics carry zero tolerance: exact equality or the round fails."""
    return dict(recorded) == dict(replayed)


def unconsolidated_start_reasons(view) -> list:
    """Reasons a restored start is not the frozen original unconsolidated authority.

    ``view`` is the runner's flat projection of one restored authority copy:
    scope, authority cutoff, current manifest cutoff, complete projection
    version count and the 013-effect/pending counters. T097 maps the exported
    authority snapshot into this view; the predicate itself is pure.
    """
    reasons = []
    scope_id = view.get('scope_id')
    if not isinstance(scope_id, str) or not scope_id.isdecimal() or scope_id.startswith('0'):
        reasons.append('SCOPE_MISSING')
    if view.get('manifest_cutoff_event_id') != view.get('authority_cutoff_event_id'):
        reasons.append('MANIFEST_CUTOFF_NOT_ORIGINAL')
    if view.get('complete_projection_versions') != 6:
        reasons.append('PROJECTION_INCOMPLETE')
    if view.get('consolidation_effect_count') != 0:
        reasons.append('NOT_AN_ORIGINAL_START')
    if view.get('pending_effect_count') != 0:
        reasons.append('PENDING_EFFECTS')
    return reasons
