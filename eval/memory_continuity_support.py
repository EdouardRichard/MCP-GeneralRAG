#!/usr/bin/env python3
"""T054: 014 continuity evaluation support (dataset validation, arms, metrics,
report encoding, record/replay cache).

Evaluation-side only: the backend never imports this module.  Frozen rules live
in ``specs/014-memory-aware-retrieval/contracts/continuity-evaluation-contract.md``
(§2 dataset, §3 judgement, §4 reproducibility, §5 report) and
``data-model.md`` §7.6/§7.7; this module implements them and invents nothing.

Design boundaries:

* **No LLM anywhere in the control path.**  ``model`` is the explicit frozen
  value ``"none"``; every decision here is a pure rule
  (``task_complete``/``completion_rate``/``relative_gain``/``redundancy``).
* **Stable anchors only.**  A required item's ``locator`` is
  ``<scope slug>#heading:<heading path>[ > <role>:<token>]``; a runtime
  ``memory_id`` is an *optional* same-snapshot consistency check and can never be
  the only anchor (011 FR-007 discipline).
* **No service dependency at import time.**  PostgreSQL/Qdrant restore
  primitives are imported lazily inside the restore functions, so the contract
  tests import this module on a machine where every service is closed.
* **Honest observations.**  A metric this run did not observe stays ``None``; it
  is never fabricated as a zero, and a zero baseline is
  ``BASELINE_ZERO_NOT_COMPUTABLE`` rather than a tiny/infinite substitute.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

K = 5
DATASET_VERSION_PREFIX = '014.'
MIN_QUERIES = 15
CATEGORIES = ('resume_after_break', 'recall_last_decision', 'lesson_effective', 'preference_applied')
LANGUAGES = ('zh', 'en')
REVIEW_STATUSES = frozenset({'reviewed', 'pending_review'})
FROZEN_FIELDS = ('budget', 'clock', 'implementation', 'model', 'policy', 'prompt',
                 'recall', 'schema', 'snapshot', 'vocabulary')
ARMS = ('without_memory', 'with_memory')
ROUNDS = ('record', 'replay')
RELATIVE_GAIN_THRESHOLD = 0.03
ZERO_BASELINE_CODE = 'BASELINE_ZERO_NOT_COMPUTABLE'
NON_LATENCY_TOLERANCE = 0.01
REPORT_VERSION = '014.1'
REPORT_TYPE = '014_memory_continuity_comparison'
CACHE_MANIFEST_VERSION = '014.cache.1'
CACHE_PARSER_VERSION = 'continuity-v1'
# The 013 isolation scheme's guarded restore primitives are reused verbatim; the
# prefix is imported lazily so every 014 identity goes through the same guard.
ISOLATED_DATABASE_PREFIX = 'memory_consolidation_013_'
# Response fields that only the 014 memory path adds.  The baseline arm must
# carry none of them (contract §1).
NEW_RESPONSE_FIELDS = ('related_memories', 'memory_notice', 'counts', 'working_set')
# Zero-tolerance safety counters and the full-integrity rates (contract §6).
ZERO_SAFETY_KEYS = ('cross_domain_leaks', 'quarantined_memory_inputs',
                    'memory_context_detection_out_of_order', 'memory_entries_with_evidence_locators')
FULL_INTEGRITY_KEYS = ('mcp_schema_validity_rate', 'evidence_source_locatable_rate',
                       'memory_provenance_complete_rate', 'memory_context_detection_first_rate')
# The frozen report contract (§5) plus the two evidence-only additions.
REPORT_KEYS = ('schema_version', 'report_type', 'generated_at', 'commit', 'status', 'environment',
               'dataset_version', 'snapshot_hash', 'k', 'queries', 'aggregates', 'relative_gain',
               'zero_baseline', 'criteria', 'redundancy', 'reproducibility', 'hard_metrics',
               'cache', 'gates', 'default_enable_eligible', 'evidence_paths', 'failed_paths',
               'default_configuration')

SLUG = re.compile(r'^[a-z0-9][a-z0-9-]*$')
DECIMAL = re.compile(r'^[0-9]+$')
HASH = re.compile(r'^[a-f0-9]{64}$')
VERSION = re.compile(rf'^{re.escape(DATASET_VERSION_PREFIX)}eval\.[0-9]+$')
ITEM_ROLE = re.compile(r'^(action|decision|correction|preference|fact):[a-z0-9][a-z0-9-]*$')
FORBIDDEN_KINDS = ('out_of_scope', 'superseded_item', 'banned_claim')


class DatasetInvalid(ValueError):
    """The frozen continuity dataset or a report does not satisfy the contract."""


class ComparisonFailed(RuntimeError):
    """A real comparison check failed; the run must not claim a gate passed."""


class PreflightIncomplete(RuntimeError):
    """Required material or configuration is missing; the run must not start."""


class CacheIncomplete(RuntimeError):
    """The replay cache lacks a recorded outcome (missing/corrupt/version)."""


class CachedToolFailure(RuntimeError):
    """A recorded failure replayed from the sealed cache (never re-run)."""


class RestoreIncomplete(RuntimeError):
    """A restoration identity could not be materialised or verified."""


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def load_dataset(path) -> dict:
    """Strict JSON load (no duplicate keys, no non-finite numbers)."""
    def pairs(items):
        keys = [key for key, _ in items]
        if len(set(keys)) != len(keys):
            raise DatasetInvalid('duplicate JSON object key')
        return dict(items)

    def constant(value):
        raise DatasetInvalid('non-finite JSON number')

    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise DatasetInvalid(f'dataset unreadable: {error}') from error
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise DatasetInvalid(f'invalid dataset JSON: {error}') from error


def make_locator(slug: str, heading: str, item: str | None = None) -> str:
    """Build the cross-environment stable anchor ``<slug>#heading:<h>[ > role:token]``."""
    locator = f'{slug}#heading:{heading}'
    return locator if item is None else f'{locator} > {item}'


def locator_parts(locator: str) -> dict:
    """Parse a locator; raises :class:`DatasetInvalid` when it is not a stable anchor."""
    if not isinstance(locator, str) or not locator.strip():
        raise DatasetInvalid('locator must be a non-empty string')
    if '#' not in locator:
        raise DatasetInvalid(
            f'locator {locator!r} must be "<scope slug>#heading:<heading path>" '
            '(a runtime memory_id is never the only anchor)')
    slug, _, anchor = locator.partition('#')
    if not SLUG.match(slug):
        raise DatasetInvalid(f'locator {locator!r} has no valid scope slug')
    if not anchor.startswith('heading:'):
        raise DatasetInvalid(f'locator {locator!r} must anchor a structural heading path')
    body = anchor[len('heading:'):]
    heading, _, item = body.partition(' > ')
    if not heading.strip():
        raise DatasetInvalid(f'locator {locator!r} carries an empty heading path')
    if item and not ITEM_ROLE.match(item):
        raise DatasetInvalid(f'locator {locator!r} carries an invalid item selector')
    return {'slug': slug, 'heading': heading, 'item': item or None, 'anchor': body}


def _nonempty(value, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetInvalid(f'{where} must be a non-empty string')
    return value


def _required_item(item, where: str) -> dict:
    if not isinstance(item, dict):
        raise DatasetInvalid(f'{where} must be an object')
    if 'locator' not in item:
        raise DatasetInvalid(f'{where} carries no locator')
    locator_parts(item['locator'])
    if not isinstance(item.get('require_citation'), bool):
        raise DatasetInvalid(f'{where}.require_citation must be a boolean')
    memory_id = item.get('memory_id')
    if memory_id is not None and not DECIMAL.match(str(memory_id)):
        raise DatasetInvalid(f'{where}.memory_id must be a decimal string or absent')
    return item


def validate_dataset(dataset) -> dict:
    """Structural validation of the frozen continuity dataset (contract §2)."""
    if not isinstance(dataset, dict):
        raise DatasetInvalid('the 014 dataset must be a frozen object, not a bare array')
    for key in ('dataset_version', 'frozen', 'snapshot_hash', 'source', 'scope_id', 'k', 'queries'):
        if key not in dataset:
            raise DatasetInvalid(f'dataset missing {key}')
    if not VERSION.match(_nonempty(dataset['dataset_version'], 'dataset_version')):
        raise DatasetInvalid('dataset_version must be an 014.eval.N version')
    if dataset['k'] != K:
        raise DatasetInvalid('dataset k must be the frozen k=5')
    if not isinstance(dataset['snapshot_hash'], str) or not HASH.match(dataset['snapshot_hash']):
        raise DatasetInvalid('dataset snapshot_hash must be a sha256 hex digest')
    if not isinstance(dataset['scope_id'], str) or not DECIMAL.match(dataset['scope_id']):
        raise DatasetInvalid('dataset scope_id must be a decimal string')

    frozen = dataset['frozen']
    if not isinstance(frozen, dict):
        raise DatasetInvalid('dataset frozen identity map must be an object')
    for field_name in FROZEN_FIELDS:
        _nonempty(frozen.get(field_name), f'frozen.{field_name}')
    if frozen['model'] != 'none':
        raise DatasetInvalid('frozen.model must be the explicit "none": 014 has no LLM in the control path')

    source = dataset['source']
    if not isinstance(source, dict):
        raise DatasetInvalid('dataset source must be an object')
    _nonempty(source.get('scope_slug'), 'source.scope_slug')
    _nonempty(source.get('corpus'), 'source.corpus')
    _nonempty(source.get('human_review'), 'source.human_review')
    if source.get('scope_id') != dataset['scope_id']:
        raise DatasetInvalid('source.scope_id must match the dataset scope_id')
    if not isinstance(source.get('grounding'), list) or not source['grounding']:
        raise DatasetInvalid('source.grounding must name the real frozen material')

    criterion = dataset.get('explicit_criterion')
    if not isinstance(criterion, dict) or not isinstance(criterion.get('minimum_completed_with_memory'), int):
        raise DatasetInvalid('dataset explicit_criterion must be frozen before the run')

    queries = dataset['queries']
    if not isinstance(queries, list) or len(queries) < MIN_QUERIES:
        raise DatasetInvalid(f'dataset requires at least {MIN_QUERIES} queries')
    identifiers = [query.get('query_id') for query in queries]
    if len(set(identifiers)) != len(identifiers) or any(not identifier for identifier in identifiers):
        raise DatasetInvalid('dataset query ids must be unique and non-empty')
    counts = {category: 0 for category in CATEGORIES}
    languages = {language: 0 for language in LANGUAGES}
    for query in queries:
        _validate_query(query, dataset)
        counts[query['category']] += 1
        languages[query['language']] += 1
    for category, count in counts.items():
        if count < 1:
            raise DatasetInvalid(f'dataset category {category} is not covered')
    if languages['zh'] < 2:
        raise DatasetInvalid('dataset requires at least two zh queries')
    if criterion.get('queries_total') != len(queries):
        raise DatasetInvalid('explicit_criterion.queries_total must equal the frozen query count')
    return dataset


def _validate_query(query, dataset: dict) -> None:
    where = f"query {query.get('query_id') if isinstance(query, dict) else '?'}"
    if not isinstance(query, dict):
        raise DatasetInvalid('dataset query must be an object')
    _nonempty(query.get('query_id'), f'{where}.query_id')
    _nonempty(query.get('question'), f'{where}.question')
    _nonempty(query.get('criterion'), f'{where}.criterion')
    if query.get('category') not in CATEGORIES:
        raise DatasetInvalid(f'{where} category invalid')
    if query.get('language') not in LANGUAGES:
        raise DatasetInvalid(f'{where} language invalid')
    if query.get('scope_id') != dataset['scope_id']:
        raise DatasetInvalid(f'{where} must belong to the frozen scope')

    items = query.get('required_items')
    if not isinstance(items, list) or not items:
        raise DatasetInvalid(f'{where} required_items must be a non-empty list')
    for index, item in enumerate(items):
        _required_item(item, f'{where}.required_items[{index}]')

    if 'forbidden_items' not in query:
        raise DatasetInvalid(f'{where} must carry the forbidden_items key')
    forbidden = query['forbidden_items']
    if not isinstance(forbidden, list):
        raise DatasetInvalid(f'{where}.forbidden_items must be a list')
    for index, item in enumerate(forbidden):
        if not isinstance(item, dict) or not item.get('locator') or not item.get('reason'):
            raise DatasetInvalid(f'{where}.forbidden_items[{index}] requires locator and reason')
        if item.get('kind') not in FORBIDDEN_KINDS:
            raise DatasetInvalid(f'{where}.forbidden_items[{index}].kind is not decidable')
        locator_parts(item['locator'])

    meta = query.get('_meta')
    if not isinstance(meta, dict):
        raise DatasetInvalid(f'{where} carries no _meta review record')
    status = meta.get('review_status')
    if status not in REVIEW_STATUSES:
        raise DatasetInvalid(
            f'{where} review_status {status!r} is outside {sorted(REVIEW_STATUSES)}')
    notes = meta.get('review_notes')
    grounded = meta.get('grounded_source')
    if not isinstance(notes, str) or not notes.strip():
        raise DatasetInvalid(f'{where} claims {status} but carries no review record (review_notes)')
    if not isinstance(grounded, str) or not grounded.strip():
        raise DatasetInvalid(f'{where} claims {status} without a grounded_source '
                             '(a fabricated review claim)')


# ---------------------------------------------------------------------------
# Frozen metrics (pure rules; no model anywhere)
# ---------------------------------------------------------------------------

@dataclass
class ArmObservation:
    """One arm's rule-decidable outcome for one frozen query."""

    query_id: str
    arm: str
    round: str = 'record'
    hits: tuple = ()
    cited: tuple = ()
    forbidden_hits: tuple = ()
    delivered: tuple = ()
    latency_ms: float | None = None
    cost_usd: float | None = None
    error: str | None = None
    baseline_new_fields: tuple = ()
    raw: dict = field(default_factory=dict)

    def normalized(self) -> dict:
        """The record/replay comparison identity of this outcome."""
        return {'hits': sorted(self.hits), 'cited': sorted(self.cited),
                'forbidden_hits': sorted(self.forbidden_hits), 'error': self.error,
                'delivered': len(self.delivered)}


def task_complete(query: dict, observation: ArmObservation) -> dict:
    """Binary, rule-decidable task completion (contract §3).

    ``task_complete = (every required item hit) AND (every item that requires a
    citation carries one) AND (zero forbidden/out-of-scope/invalid items)``.
    """
    required = [item['locator'] for item in query['required_items']]
    citation_required = [item['locator'] for item in query['required_items']
                         if item.get('require_citation')]
    hits, cited, forbidden = set(observation.hits), set(observation.cited), list(observation.forbidden_hits)
    missing = [locator for locator in required if locator not in hits]
    uncited = [locator for locator in citation_required if locator not in cited]
    complete = not missing and not uncited and not forbidden and observation.error is None
    return {'task_complete': bool(complete), 'hit': [locator for locator in required if locator in hits],
            'missing': missing, 'uncited': uncited, 'forbidden': forbidden,
            'citation_required': citation_required}


def completion_rate(completed) -> float:
    """``completed / queries``; an empty set has no rate (0.0, never fabricated)."""
    rows = list(completed)
    if not rows:
        return 0.0
    return sum(1 for value in rows if value) / len(rows)


def relative_gain(without_memory: float, with_memory: float) -> dict:
    """``(with - without) / without``; a zero baseline stays not computable."""
    zero = without_memory == 0
    value = None if zero else (with_memory - without_memory) / without_memory
    return {'value': value, 'zero_baseline': bool(zero),
            'code': ZERO_BASELINE_CODE if zero else None,
            'formula': '(with_memory - without_memory) / without_memory',
            'threshold': RELATIVE_GAIN_THRESHOLD}


def redundancy(items) -> dict:
    """``1 - distinct_items / total_items`` (deterministic, recomputable)."""
    rows = list(items)
    distinct = len(set(rows))
    total = len(rows)
    return {'total_items': total, 'distinct_items': distinct,
            'value': None if total == 0 else 1 - distinct / total,
            'formula': '1 - distinct_items / total_items',
            'scope': 'auxiliary observation only; never a gate (contract §3)'}


def explicit_criterion_check(rows, criterion: dict) -> dict:
    """The pre-frozen explicit completion criterion (contract §3, default >=12/15).

    ``rows`` are the ``with_memory`` arm's per-query results
    (``{'category', 'task_complete'}``).  This is the substitute judgement when
    the baseline is zero; it is frozen before the run, never chosen afterwards.
    """
    by_category: dict[str, int] = {category: 0 for category in CATEGORIES}
    completed = 0
    for row in rows:
        by_category.setdefault(row['category'], 0)
        if row['task_complete']:
            completed += 1
            by_category[row['category']] = by_category.get(row['category'], 0) + 1
    minimum = int(criterion['minimum_completed_with_memory'])
    per_category = int(criterion['per_category_minimum_completed'])
    covered = all(by_category.get(category, 0) >= per_category for category in CATEGORIES)
    return {'met': bool(completed >= minimum and covered),
            'completed_with_memory': completed,
            'queries_total': criterion.get('queries_total'),
            'completed_by_category': by_category,
            'minimum_completed_with_memory': minimum,
            'per_category_minimum_completed': per_category,
            'source': criterion.get('source')}


def replay_response_audit(record_rows: dict, replay_rows: dict, query_ids) -> dict:
    """Compare the record round's arm outcomes with the replay round's.

    Both arms and the success *and* failure outcomes are compared on the
    normalized rule-decidable outcome, so a replay that silently re-runs a
    recorded failure cannot pass as a reproduction.
    """
    matched, mismatched, compared = 0, [], 0
    for query_id in query_ids:
        for arm in ARMS:
            before = record_rows.get(('record', arm, query_id))
            after = replay_rows.get(('replay', arm, query_id))
            if before is None or after is None:
                continue
            compared += 1
            if before.normalized() == after.normalized():
                matched += 1
            else:
                mismatched.append(f'{arm}:{query_id}')
    return {'matched': matched, 'compared': compared, 'mismatched': mismatched,
            'match_rate': None if compared == 0 else matched / compared}


def reproducibility_status(*, response_match_rate, max_non_latency_relative_drift,
                           replay_real_network_calls: int, evidence_complete: bool,
                           tolerance: float = NON_LATENCY_TOLERANCE) -> str:
    """Observed record/replay reproduction, never the CLI round label.

    An unmeasured drift, a missing response comparison or incomplete cache
    evidence is ``incomplete``; a real drift over the 1 % tolerance or a real
    network call during replay is ``failed``.
    """
    if not evidence_complete or response_match_rate is None or max_non_latency_relative_drift is None:
        return 'incomplete'
    if (response_match_rate == 1 and max_non_latency_relative_drift <= tolerance
            and replay_real_network_calls == 0):
        return 'passed'
    return 'failed'


# ---------------------------------------------------------------------------
# The two arms: baseline disables the parameters, with_memory enables them
# ---------------------------------------------------------------------------

def baseline_parameters() -> dict:
    """The baseline arm's call parameters: no session, no memory context."""
    return {'session_id': None, 'memory_context': None}


def arm_parameters(arm: str, *, session_id: str | None = None,
                   memory_context: str | None = None) -> dict:
    """Frozen per-arm parameters; the two arms never share a session."""
    if arm == 'without_memory':
        return baseline_parameters()
    if arm != 'with_memory':
        raise ComparisonFailed(f'unknown arm {arm!r}')
    return {'session_id': session_id, 'memory_context': memory_context}


def arm_policy(arm: str) -> dict:
    """The runner-owned arm switch: the only enabled variable is memory availability."""
    if arm == 'without_memory':
        return {'memory_attachment_enabled': False, 'working_set_enabled': False}
    if arm == 'with_memory':
        return {'memory_attachment_enabled': True, 'working_set_enabled': True}
    raise ComparisonFailed(f'unknown arm {arm!r}')


def zero_new_fields(response) -> list:
    """The 014-only fields present in a response (the baseline must carry none)."""
    if not isinstance(response, dict):
        return []
    return [name for name in NEW_RESPONSE_FIELDS if name in response]


def assert_baseline_zero_new_fields(response) -> None:
    """Contract §1: the baseline response must carry zero new fields."""
    found = zero_new_fields(response)
    if found:
        raise ComparisonFailed(
            f'baseline response carries new field(s) {found}; the unique enabled variable '
            'is memory availability, so the baseline must stay byte-identical in shape')


# ---------------------------------------------------------------------------
# 2 arms x 2 rounds: four independent restorations
# ---------------------------------------------------------------------------

def allocate_identities(run_id: str, *, base, qdrant_port_base: int = 18400):
    """One independent database/data root/Qdrant store per ``(round, arm)``.

    The 013 isolation scheme's guarded primitives are reused verbatim (native
    ``CREATE DATABASE ... TEMPLATE`` capsule copy, byte-copied private data root,
    one real Qdrant process per identity); the run id and the ``014_`` infix keep
    every 014 identity disjoint from any 013 identity.
    """
    from consolidation_restore_support import ISOLATED_DATABASE_PREFIX as PREFIX
    from consolidation_restore_support import Identity, RunIdentity

    if not run_id or not run_id.isalnum():
        raise ComparisonFailed('run_id must be a non-empty alphanumeric token')
    base = Path(base)
    run = RunIdentity(run_id=run_id)
    seen_databases, seen_roots, seen_ports = set(), set(), set()
    for index, (round_name, arm) in enumerate((r, a) for r in ROUNDS for a in ARMS):
        database = f'{PREFIX}014_{run_id}_{index}'.lower()
        data_root = base / run_id / f'{index:02d}' / 'root'
        qdrant_storage = base / run_id / f'{index:02d}' / 'q'
        http_port = qdrant_port_base + index * 2
        grpc_port = http_port + 1
        if database in seen_databases or str(data_root) in seen_roots or http_port in seen_ports:
            raise ComparisonFailed(f'identity collision while allocating {round_name}/{arm}')
        seen_databases.add(database)
        seen_roots.add(str(data_root))
        seen_ports.update({http_port, grpc_port})
        run.identities.append(Identity(
            round=round_name, arm=arm, database=database, data_root=data_root,
            qdrant_url=f'http://127.0.0.1:{http_port}', qdrant_storage=qdrant_storage,
            qdrant_http_port=http_port, qdrant_grpc_port=grpc_port))
    assert_independent(run)
    return run


def assert_independent(run) -> dict:
    """Prove no two identities share a database, a root or a store endpoint."""
    for label, values in (('database', [item.database for item in run.identities]),
                          ('data_root', [str(item.data_root) for item in run.identities]),
                          ('qdrant_url', [item.qdrant_url for item in run.identities]),
                          ('qdrant_storage', [str(item.qdrant_storage) for item in run.identities])):
        if len(set(values)) != len(values):
            raise ComparisonFailed(f'{label} identity reused across arms/rounds: {values}')
    return {'identities': len(run.identities),
            'distinct_databases': len({item.database for item in run.identities}),
            'distinct_data_roots': len({str(item.data_root) for item in run.identities}),
            'distinct_qdrant_stores': len({item.qdrant_url for item in run.identities}),
            'arms': sorted({item.arm for item in run.identities}),
            'rounds': sorted({item.round for item in run.identities})}


def restore_identities(capsule_dir, run) -> list:
    """Materialise and verify every identity from the sealed capsule.

    Reuses the 013 restore path, which writes a per-identity ``restore-receipt``
    (authority digest, alembic version, projection manifest digest, data-root
    digest, Qdrant point digests).  That receipt is the restoration credential
    the report publishes; it is never synthesised here.
    """
    from consolidation_restore_support import restore_identity

    receipts = []
    for identity in run.identities:
        receipts.append(restore_identity(Path(capsule_dir), identity))
    return receipts


def restoration_receipts(run) -> dict:
    """Read back the restoration credentials written by the sealed restore."""
    receipts = {}
    for identity in run.identities:
        path = Path(identity.data_root).parent / 'restore-receipt.json'
        receipts[identity.label] = (json.loads(path.read_text(encoding='utf-8'))
                                    if path.exists() else None)
    return receipts


# ---------------------------------------------------------------------------
# Record/replay cache: recorded outcomes only, zero real calls on replay
# ---------------------------------------------------------------------------

def cache_key(tool: str, arm: str, query_id: str) -> str:
    """The frozen request identity of one arm/query tool call."""
    raw = json.dumps({'tool': tool, 'arm': arm, 'query_id': query_id},
                     sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def entry_path(cache_dir, key: str) -> Path:
    return Path(cache_dir) / f'{key}.json'


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class ToolCallCache:
    """The sealed boundary of one tool call: record once, replay exactly once.

    ``record`` performs the real call and persists the outcome (success *and*
    failure).  ``replay`` consumes exactly the recorded outcome and never calls
    the wrapped tool; a missing, corrupt or version-mismatched entry is
    ``incomplete`` evidence, which the report maps to exit code 2.
    """

    def __init__(self, cache_dir, *, mode: str):
        if mode not in ('record', 'replay'):
            raise ValueError(f'mode must be record or replay, not {mode!r}')
        self.cache_dir = Path(cache_dir)
        self.mode = mode
        self.real_calls = 0

    def _read(self, key: str) -> dict:
        path = entry_path(self.cache_dir, key)
        if not path.is_file():
            raise CacheIncomplete(f'cache entry missing for key {key} ({path})')
        try:
            entry = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeDecodeError) as error:
            raise CacheIncomplete(f'cache entry corrupt for key {key}: {error}') from error
        if not isinstance(entry, dict) or entry.get('parser') != CACHE_PARSER_VERSION:
            raise CacheIncomplete(
                f'cache entry version mismatch for key {key}: {entry.get("parser")!r}')
        return entry

    def _write(self, key: str, entry: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        entry_path(self.cache_dir, key).write_text(
            json.dumps(entry, sort_keys=True), encoding='utf-8')

    def invoke(self, key: str, call):
        """Invoke one tool boundary under the cache; failures are recorded too."""
        if self.mode == 'replay':
            entry = self._read(key)
            if entry.get('reason') is not None:
                raise CachedToolFailure(entry['reason'])
            return entry.get('output')
        self.real_calls += 1
        try:
            output = call()
        except Exception as error:  # noqa: BLE001 - a real failure is a recorded outcome
            self._write(key, {'parser': CACHE_PARSER_VERSION,
                              'reason': f'{type(error).__name__}: {error}', 'output': None})
            raise
        self._write(key, {'parser': CACHE_PARSER_VERSION, 'reason': None, 'output': output})
        return output

    def seal(self, manifest_path, *, dataset_hash: str, snapshot_hash: str,
             model_version: str = 'none', responses: dict | None = None,
             hard_metrics: dict | None = None) -> dict:
        """Freeze the recorded key set into a sidecar manifest (never overwritten).

        ``responses`` carries the record round's normalized arm outcomes and
        ``hard_metrics`` the counters this round really observed; the replay round
        compares against them and never re-derives them.
        """
        keys = sorted(path.stem for path in self.cache_dir.glob('*.json')) if self.cache_dir.exists() else []
        entries, success, failure = [], 0, 0
        for key in keys:
            entry = self._read(key)
            body = json.dumps(entry.get('output'), sort_keys=True, separators=(',', ':'))
            status = 'failure' if entry.get('reason') is not None else 'success'
            success += status == 'success'
            failure += status == 'failure'
            entries.append({'key': key, 'status': status, 'parser_version': entry['parser'],
                            'entry_sha256': _sha256_bytes(
                                entry_path(self.cache_dir, key).read_bytes()),
                            'body_sha256': _sha256_bytes(body.encode('utf-8'))})
        manifest = {'manifest_version': CACHE_MANIFEST_VERSION, 'parser_version': CACHE_PARSER_VERSION,
                    'cache_dir': str(self.cache_dir), 'model_version': model_version,
                    'dataset_hash': dataset_hash, 'snapshot_hash': snapshot_hash,
                    'expected_keys': len(entries), 'recorded_success': success,
                    'recorded_failure': failure, 'entries': entries,
                    'responses': dict(responses or {}),
                    'hard_metrics': dict(hard_metrics or {})}
        raw = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')
        path = Path(manifest_path)
        if path.exists():
            if path.read_bytes() != raw:
                raise ComparisonFailed(f'refusing to overwrite {path} with different bytes')
            return manifest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return manifest

    @staticmethod
    def load_manifest(manifest_path) -> dict:
        path = Path(manifest_path)
        if not path.is_file():
            raise PreflightIncomplete(f'replay requires an existing cache manifest: {path}')
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeDecodeError) as error:
            raise PreflightIncomplete(f'cache manifest unreadable: {error}') from error
        if manifest.get('manifest_version') != CACHE_MANIFEST_VERSION:
            raise PreflightIncomplete('cache manifest version mismatch')
        return manifest

    def audit(self, keys) -> dict:
        """Report the real evidence state of the sealed keys (no gap-fill)."""
        counts = {'expected_keys': len(list(keys)), 'matched': 0, 'missing': 0, 'corrupt': 0,
                  'version_mismatch': 0, 'recorded_success': 0, 'recorded_failure': 0}
        for key in keys:
            path = entry_path(self.cache_dir, key)
            if not path.is_file():
                counts['missing'] += 1
                continue
            try:
                entry = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError, UnicodeDecodeError):
                counts['corrupt'] += 1
                continue
            if not isinstance(entry, dict) or entry.get('parser') != CACHE_PARSER_VERSION:
                counts['version_mismatch'] += 1
                continue
            counts['matched'] += 1
            if entry.get('reason') is None:
                counts['recorded_success'] += 1
            else:
                counts['recorded_failure'] += 1
        counts['replayed_success'] = counts['recorded_success']
        counts['replayed_failure'] = counts['recorded_failure']
        counts['evidence_complete'] = bool(counts['expected_keys']) and counts['matched'] == counts['expected_keys']
        return counts


# ---------------------------------------------------------------------------
# Report encoding and validation
# ---------------------------------------------------------------------------

def encode_report(*, dataset: dict, generated_at: str, commit: str, status: str, environment: dict,
                  queries: list, aggregates: dict, relative_gain: dict, zero_baseline: dict,
                  criteria: dict, redundancy: dict, reproducibility: dict, hard_metrics: dict,
                  cache: dict, gates: dict, default_enable_eligible: bool, evidence_paths: list,
                  failed_paths: list, default_configuration: dict) -> dict:
    """Assemble the frozen 014.1 report (contract §5)."""
    report = {
        'schema_version': REPORT_VERSION, 'report_type': REPORT_TYPE, 'generated_at': generated_at,
        'commit': commit, 'status': status, 'environment': environment,
        'dataset_version': dataset['dataset_version'], 'snapshot_hash': dataset['snapshot_hash'],
        'k': dataset['k'], 'queries': queries, 'aggregates': aggregates,
        'relative_gain': relative_gain, 'zero_baseline': zero_baseline, 'criteria': criteria,
        'redundancy': redundancy, 'reproducibility': reproducibility, 'hard_metrics': hard_metrics,
        'cache': cache, 'gates': gates, 'default_enable_eligible': bool(default_enable_eligible),
        'evidence_paths': list(evidence_paths), 'failed_paths': list(failed_paths),
        'default_configuration': default_configuration,
    }
    validate_report(report)
    return report


def validate_report(report) -> None:
    """Structural validation of a 014.1 report; raises :class:`ComparisonFailed`."""
    if not isinstance(report, dict):
        raise ComparisonFailed('report must be an object')
    missing = [key for key in REPORT_KEYS if key not in report]
    if missing:
        raise ComparisonFailed(f'report missing keys: {missing}')
    unexpected = sorted(set(report) - set(REPORT_KEYS))
    if unexpected:
        raise ComparisonFailed(f'report carries keys outside the frozen contract: {unexpected}')
    if report['schema_version'] != REPORT_VERSION:
        raise ComparisonFailed(f'report schema_version must be {REPORT_VERSION}')
    if report['k'] != K:
        raise ComparisonFailed('report k must be the frozen k=5')
    if report['status'] not in ('passed', 'failed', 'incomplete'):
        raise ComparisonFailed(f'report status {report["status"]!r} is invalid')
    if set(report['gates']) != {'quality', 'safety', 'regression'}:
        raise ComparisonFailed('report requires the three gates quality/safety/regression')
    if set(report['aggregates']) != set(ARMS):
        raise ComparisonFailed('report aggregates must cover both arms')
    for row in report['queries']:
        for arm in ARMS:
            if arm not in row:
                raise ComparisonFailed(f"query {row.get('query_id')} carries no {arm} result")
    if report['default_configuration']['switches_changed'] is not False:
        raise ComparisonFailed('the report must never flip a configuration switch')
    if report['default_enable_eligible'] and report['status'] != 'passed':
        raise ComparisonFailed('default_enable_eligible requires status=passed')
    if report['status'] == 'passed' and report['default_enable_eligible'] is not True:
        raise ComparisonFailed('status=passed requires default_enable_eligible=true')


def validate_comparison_report(report, *, evidence=None) -> dict:
    """The eval-level decision: a passed report needs complete, real evidence.

    Only returns a decision; it installs no gate entry, publishes no policy and
    changes no switch.
    """
    validate_report(report)
    if report['status'] == 'passed':
        if evidence is None:
            raise ComparisonFailed('a passed report requires the run evidence index')
        if report['reproducibility']['status'] != 'passed':
            raise ComparisonFailed('a passed report requires reproducibility==passed')
        if not report['cache']['evidence_complete']:
            raise ComparisonFailed('a passed report requires complete cache evidence')
    return {'status': report['status'], 'default_enable_eligible': report['default_enable_eligible'],
            'dataset_version': report['dataset_version'], 'snapshot_hash': report['snapshot_hash']}


def sanitized_timestamp() -> str:
    return datetime.now().astimezone().isoformat()
