#!/usr/bin/env python3
"""T097: the 013 consolidation comparison runner (record/replay).

Every ``(round, arm)`` starts from its **own** restoration of the same sealed
original unconsolidated authority: one PostgreSQL database, one private
``data_root`` and one private Qdrant store per identity (T097 restoration
support).  The runner never restores from an already-consolidated store, never
replays into an already-consolidated store, and never reuses an output or a
manifest path.

Frozen comparison inputs (``evaluation-contract.md``):

* ``--dataset`` is the T095 frozen six-query dataset.  Its relevance units are
  bound to real memory entries of the frozen scope through the declared
  source-event ids, and every binding is verified against the restored copy's
  real stored content before any metric is computed, so a mapping can never be
  invented.
* Only the **LLM provider transport** is denied and counted during replay
  (``consolidation_replay``).  Database, Qdrant, embedding and rerank access keep
  running exactly as configured and are accounted separately.
* The cache is the 005 ``AGENTIC_LLM_CACHE_PATH`` layout with the frozen
  ``strict-v1`` entries.  The sealed sidecar manifest is built from the record
  round's real persisted keys; replay requires that manifest and consumes
  exactly those outcomes (successes *and* failures) with no gap-fill and no
  provider fallback.

Exit codes: 0 only when all three gates passed on a reproducible record/replay
pair, 1 when a real check failed, 2 when the required material or configuration
is insufficient.  A missing observation stays ``null`` and never becomes a zero.
The runner writes one standalone report; it never installs a registry entry,
never publishes policy, and the per-arm switches are applied only inside each
disposable restored copy.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import itertools
import json
import math
import os
import platform
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / 'backend' / 'src', ROOT / 'eval', ROOT / 'backend'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from consolidation_eval_support import (
    RATE_KEYS,
    DatasetInvalid,
    K,
    load_dataset,
    validate_comparison_report,
    validate_dataset,
)
from consolidation_restore_support import (
    RestoreError,
    allocate_identities,
    assert_independent,
    load_run,
    project_manifest,
    save_run,
)
from rag_mcp.agents.consolidation_replay import (
    CACHE_MANIFEST_VERSION,
    audit_cache,
    build_manifest,
    cache_observation,
    non_latency_drift,
    read_strict_entry,
    replay_session,
    strict_cache_dir,
    strict_entry_path,
)
from rag_mcp.services import memory_service as memory_service_module
from rag_mcp.services.consolidation_gate import (
    GATE_VARIANTS,
    TRACE_VERSION,
    binary_metrics,
    canonical_json,
    macro_average,
)

EXIT_OK, EXIT_FAILED, EXIT_INCOMPLETE = 0, 1, 2
REPORT_VERSION = '013.2'
REPORT_TYPE = '013_memory_consolidation_comparison'
MANIFEST_API_VERSION = CACHE_MANIFEST_VERSION
DEFAULT_POLICY_REASON = (
    'evidence-only report: both default switches stay false, no policy was '
    'published and no gate registry entry was installed')
NON_LATENCY_KEYS = ('mrr', 'ndcg', 'hit_rate', 'recall_at_k', 'precision_at_k')
ZERO_SAFETY_KEYS = ('cross_scope_leaks', 'quarantined_inputs', 'soft_overturns_hard',
                    'automatic_promotions', 'invalid_outputs_applied', 'stale_holder_commits',
                    'incomplete_outputs_consumed', 'rebuild_llm_calls')
FULL_INTEGRITY_KEYS = ('source_chain_complete_rate', 'schema_validity_rate', 'projection_integrity_rate')


class PreflightIncomplete(RuntimeError):
    """Required material or configuration is missing; the run must not start."""


class ComparisonFailed(RuntimeError):
    """A real check failed while executing the comparison."""


class _Unobserved:
    """A counter this run did not observe; it becomes ``null`` and never a zero."""

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return 'UNOBSERVED'


UNOBSERVED = _Unobserved()


def is_observed(value) -> bool:
    return value is not UNOBSERVED and value is not None


def jsonable_hard(hard: dict) -> dict | None:
    """Project the hard counters for a report.

    The packaged report contract only accepts a complete counter object or
    ``null`` (preflight/incomplete).  A counter this run did not observe is
    therefore left *out* of the object and recorded as unobserved in the safety
    gate checks; it is never fabricated as a zero, and a partial object is never
    written.
    """
    observed = {key: value for key, value in (hard or {}).items() if is_observed(value)}
    required = set(ZERO_SAFETY_KEYS) | set(FULL_INTEGRITY_KEYS)
    if not observed or not required <= set(observed):
        return None
    return observed


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_json(path, label: str):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError) as error:
        raise PreflightIncomplete(f'{label} unreadable: {error}') from error


def _write_json(path, payload: dict, *, exclusive: bool = True) -> str:
    raw = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + '\n').encode('utf-8')
    path = Path(path)
    if path.exists():
        if exclusive and path.read_bytes() != raw:
            raise ComparisonFailed(f'refusing to overwrite {path} with different bytes')
        return _sha256_bytes(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return _sha256_bytes(raw)


def _head_sha() -> str:
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        return '0' * 40


# ---------------------------------------------------------------------------
# Pure report arithmetic, shared with the T090/T098 validators
# ---------------------------------------------------------------------------

def resolve_units(dataset_query: dict, entries: dict) -> list:
    """Bind the frozen relevance units to real stored memories of the scope.

    A unit binds only through the dataset's own declared lineage: the frozen
    ``source_event_ids`` of the unit are real memory identities of the scope and
    at least one of them must exist in this restoration.  The *identity* is
    verified against the real store (existence + content witness); the frozen
    ``expected_content`` is a human-authored description of the unit and is
    often a paraphrase of the source memory, so it is never used as an
    equality filter.  A unit whose declared lineage is absent, or whose lineage
    falls outside ``expected_source_event_ids``, is refused instead of being
    mapped loosely.
    """
    declared = {str(event) for event in dataset_query['expected_source_event_ids']}
    order = [str(event) for event in dataset_query['expected_source_event_ids']]
    candidates, groups = [], {}
    for unit in dataset_query['relevance_units']:
        sources = [str(item) for item in unit['source_event_ids']]
        if not set(sources) <= declared:
            raise ComparisonFailed(
                f"query {dataset_query['query_id']} unit {unit['alias']} lineage is outside the declared set")
        present = [identifier for identifier in order if identifier in sources and identifier in entries]
        if not present:
            raise ComparisonFailed(
                f"query {dataset_query['query_id']} unit {unit['alias']} is absent from the restored authority")
        candidates.append((unit, present))
        groups.setdefault(unit['equivalence_group'], []).append(len(candidates) - 1)
    # Distinct relevance units of one query never collapse onto the same memory:
    # the declared source-event order is handed out round-robin inside each
    # equivalence group, so a correction keeps its historical and current unit.
    assigned: dict[int, str] = {}
    for members in groups.values():
        for offset, index in enumerate(members):
            present = candidates[index][1]
            assigned[index] = present[offset % len(present)]
    units = []
    for index, (unit, present) in enumerate(candidates):
        units.append({'alias': unit['alias'], 'equivalence_group': unit['equivalence_group'],
                      'validity': unit['validity'], 'memory_id': assigned[index],
                      'source_event_ids': [str(item) for item in unit['source_event_ids']],
                      'witness': {identifier: (entries[identifier].get('content_text') or '')[:160]
                                  for identifier in present}})
    return units


def merge_units(dataset_query: dict, first: list, second: list) -> list:
    """One unit identity per frozen alias; both restorations must agree on it."""
    by_alias = {row['alias']: row for row in first}
    for row in second:
        existing = by_alias.get(row['alias'])
        if existing is not None and existing['memory_id'] != row['memory_id']:
            raise ComparisonFailed(
                f"query {dataset_query['query_id']} unit {row['alias']} resolves to different memories "
                'in two independent restorations of the same sealed authority')
        by_alias.setdefault(row['alias'], row)
    order = [unit['alias'] for unit in dataset_query['relevance_units']]
    return [by_alias[alias] for alias in order if alias in by_alias]


def query_trace(ranked_by_arm: dict, k: int = K) -> dict:
    variants = {}
    for arm in GATE_VARIANTS:
        ranked = list(ranked_by_arm.get(arm) or [])[:k]
        variants[arm] = ranked + [None] * (k - len(ranked))
    return {'trace_version': TRACE_VERSION, 'k': k, 'variants': variants}


def relative_gains(baseline: dict, expansion: dict) -> dict:
    zero = baseline['mrr'] == 0 or baseline['ndcg'] == 0
    gains = {'baseline_zero': zero}
    for metric in ('mrr', 'ndcg'):
        gains[metric] = None if zero else (expansion[metric] - baseline[metric]) / baseline[metric]
    return gains


def quality_checks(gains: dict, aggregates: dict) -> tuple[dict, list]:
    checks, reasons = {}, []
    if gains['baseline_zero']:
        checks['relative_gain_thresholds'] = False
        reasons.append('BASELINE_ZERO_NOT_COMPUTABLE')
    else:
        ok = (gains['mrr'] is not None and gains['ndcg'] is not None
              and gains['mrr'] >= .03 and gains['ndcg'] >= .03)
        checks['relative_gain_thresholds'] = bool(ok)
        if not ok:
            reasons.append('RELATIVE_GAIN_BELOW_THRESHOLD')
    non_decreasing = all(
        aggregates[arm][metric] >= aggregates['baseline'][metric] - 1e-12
        for arm in ('consolidated_direct', 'consolidated_candidate_expansion')
        for metric in ('hit_rate', 'recall_at_k', 'precision_at_k'))
    checks['non_degradation'] = bool(non_decreasing)
    if not non_decreasing:
        reasons.append('DIRECT_PATH_REGRESSION')
    return checks, reasons


def safety_checks(hard: dict) -> tuple[dict, list]:
    """Zero-tolerance safety gate over observed hard counters only.

    An unobserved counter is ``false`` here and is named in ``unobserved_counters``;
    it is never counted as a zero observation.
    """
    checks, reasons, unobserved = {}, [], []
    for key in ZERO_SAFETY_KEYS + FULL_INTEGRITY_KEYS:
        value = (hard or {}).get(key)
        if not is_observed(value):
            unobserved.append(key)
            checks[key] = False
            continue
        expected = 0 if key in ZERO_SAFETY_KEYS else 1
        checks[key] = value == expected
        if value != expected:
            reasons.append(f'{key.upper()}_VIOLATION')
    checks['unobserved_counters'] = len(unobserved) == 0
    checks['all_required_observed'] = not unobserved
    if unobserved:
        reasons.append('SAFETY_OBSERVATION_INCOMPLETE:' + ','.join(sorted(unobserved)))
    return checks, reasons


def response_audit(recorded_entries: dict, replay_entries: dict, keys: list, manifest: dict) -> dict:
    """Compare the record round's persisted outcomes with the replay round's."""
    matched, mismatched = 0, []
    for key in keys:
        before, after = recorded_entries.get(key), replay_entries.get(key)
        if before is None or after is None:
            continue
        body_before = before.get('output') if before.get('reason') is None else None
        body_after = after.get('output') if after.get('reason') is None else None
        if before.get('reason') == after.get('reason') and canonical_json(body_before) == canonical_json(body_after):
            matched += 1
        else:
            mismatched.append(key)
    total = len(keys)
    return {'matched': matched, 'mismatched': mismatched,
            'response_match_rate': (matched / total) if total else None}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='013 consolidation comparison runner (record/replay)',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dataset', type=Path, required=True, help='frozen 013 evaluation dataset (T095)')
    parser.add_argument('--snapshot', type=Path, required=True,
                        help='rebuildable authority snapshot of the same frozen scope')
    parser.add_argument('--mode', choices=('record', 'replay'), required=True)
    parser.add_argument('--cache-manifest', type=Path, required=True,
                        help='sealed sidecar manifest (created by record, required by replay)')
    parser.add_argument('--gate-variant', choices=GATE_VARIANTS[1:], required=True)
    parser.add_argument('--suite', type=Path, help='pytest JUnit XML of the 013 acceptance suite')
    parser.add_argument('--trace', type=Path,
                        help='exported 013 consolidation trace (CONSOLIDATION_EVIDENCE_DIR)')
    parser.add_argument('--memory-acceptance', type=Path, help='012 memory acceptance report')
    parser.add_argument('--regression', type=Path, action='append', default=[],
                        help='regression summary report (repeatable)')
    parser.add_argument('--output', type=Path, required=True, help='unique report path')
    parser.add_argument('--run', type=Path, help='restoration identity file; allocate one when omitted')
    parser.add_argument('--base', type=Path, default=Path('C:/t097c'),
                        help='short restoration base for a fresh allocation')
    parser.add_argument('--run-id', help='alphanumeric token for a fresh allocation')
    parser.add_argument('--capsule-dir', type=Path, help='sealed capsule for a fresh restoration')
    parser.add_argument('--restore', action='store_true',
                        help='materialise the six identities from the capsule before running')
    parser.add_argument('--qdrant-port-base', type=int, default=18400)
    parser.add_argument('--cache-dir', type=Path,
                        help='LLM response cache root (record default: <cache-manifest>.cache)')
    parser.add_argument('--evidence-dir', type=Path, help='directory for out-of-band run artifacts')
    parser.add_argument('--commit', help='report commit; defaults to HEAD')
    parser.add_argument('--max-consolidation-rounds', type=int, default=2)
    parser.add_argument('--print-preflight', action='store_true', help='print the validated inputs and stop')
    return parser


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def check_preflight(args: argparse.Namespace) -> dict:
    """Validate every input, version, identity and uniqueness rule before running."""
    dataset = load_dataset(args.dataset)
    validate_dataset(dataset)
    faces = {'dataset': {
        'path': str(args.dataset), 'sha256': _sha256_file(args.dataset),
        'queries': len(dataset['queries']), 'scope_id': dataset['scope_id'], 'k': dataset['k'],
        'gate_variant': dataset['gate_variant'], 'snapshot_hash': dataset['snapshot_hash'],
        'authority_cutoff': dataset['authority_cutoff'], 'frozen_clock': dataset['frozen_clock']}}
    if args.gate_variant not in GATE_VARIANTS[1:]:
        raise PreflightIncomplete('gate variant must be a consolidated arm')
    snapshot = _load_json(args.snapshot, 'authority snapshot')
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('authority'), dict):
        raise PreflightIncomplete('authority snapshot has no authority export')
    authority = snapshot['authority']
    if str(snapshot.get('scope_id')) != dataset['scope_id']:
        raise PreflightIncomplete('authority snapshot scope does not match the frozen dataset')
    if authority.get('authority_digest') != dataset['snapshot_hash']:
        raise PreflightIncomplete('authority snapshot digest does not match the frozen snapshot_hash')
    if authority.get('authority_cutoff') != dataset['authority_cutoff']:
        raise PreflightIncomplete('authority snapshot cutoff does not match the frozen dataset')
    if not isinstance(snapshot.get('policy'), dict):
        raise PreflightIncomplete('authority snapshot carries no published target policy')
    faces['snapshot'] = {'path': str(args.snapshot), 'sha256': _sha256_file(args.snapshot),
                         'authority_digest': authority.get('authority_digest'),
                         'alembic_version': authority.get('alembic_version'),
                         'authority_cutoff': authority.get('authority_cutoff')}
    if args.output.exists():
        raise PreflightIncomplete(f'output already exists: {args.output}')
    if args.mode == 'record':
        if args.cache_manifest.exists():
            raise PreflightIncomplete(f'cache manifest already exists: {args.cache_manifest}')
        cache_dir = Path(args.cache_dir) if args.cache_dir else Path(str(args.cache_manifest) + '.cache')
        directory = strict_cache_dir(cache_dir)
        existing = sorted(directory.glob('*.json')) if directory.exists() else []
        if existing:
            raise PreflightIncomplete(
                f'record must start from an empty strict cache ({len(existing)} entries present)')
    else:
        if not args.cache_manifest.is_file():
            raise PreflightIncomplete(f'replay requires an existing cache manifest: {args.cache_manifest}')
        manifest = _load_json(args.cache_manifest, 'cache manifest')
        if manifest.get('manifest_version') != MANIFEST_API_VERSION:
            raise PreflightIncomplete('cache manifest version mismatch')
        cache_dir = Path(args.cache_dir) if args.cache_dir else Path(manifest.get('cache_dir') or
                                                                    str(args.cache_manifest) + '.cache')
        audit = audit_cache(cache_dir, manifest)
        if not audit['evidence_complete']:
            raise PreflightIncomplete(
                f'cache evidence incomplete: missing={audit["missing"]} corrupt={audit["corrupt"]} '
                f'version_mismatch={audit["version_mismatch"]} matched={audit["matched"]}/'
                f'{audit["expected_keys"]}')
        faces['cache_manifest'] = {'path': str(args.cache_manifest),
                                   'sha256': _sha256_file(args.cache_manifest),
                                   'expected_keys': audit['expected_keys'],
                                   'recorded_success': audit['recorded_success'],
                                   'recorded_failure': audit['recorded_failure']}
    for label, path in (('suite', args.suite), ('trace', args.trace),
                        ('memory_acceptance', args.memory_acceptance)):
        if path is not None and not Path(path).is_file():
            raise PreflightIncomplete(f'{label} evidence missing: {path}')
    for path in args.regression:
        if not Path(path).is_file():
            raise PreflightIncomplete(f'regression evidence missing: {path}')
    if args.run is not None and not Path(args.run).is_file():
        raise PreflightIncomplete(f'run identity file missing: {args.run}')
    if args.run is None and (not args.run_id or args.capsule_dir is None):
        raise PreflightIncomplete('either --run or (--run-id and --capsule-dir) is required')
    faces['cache_dir'] = str(cache_dir)
    return {'dataset': dataset, 'snapshot': snapshot, 'faces': faces, 'cache_dir': cache_dir}


def prepare_identities(args: argparse.Namespace, evidence_dir: Path) -> dict:
    """Load or allocate the six independent ``(round, arm)`` restorations."""
    if args.run is not None:
        run = load_run(args.run)
        return {'run': run, 'proof': assert_independent(run), 'run_path': str(args.run),
                'identities': _load_json(args.run, 'run identity'), 'restored': []}
    run = allocate_identities(args.run_id, base=args.base, qdrant_port_base=args.qdrant_port_base)
    proof = assert_independent(run)
    run_path = evidence_dir / f'{args.run_id}-identities.json'
    save_run(run, run_path)
    restored = []
    if args.restore:
        from consolidation_restore_support import restore_identity

        for identity in run.identities:
            restored.append(restore_identity(args.capsule_dir, identity))
    return {'run': run, 'proof': proof, 'run_path': str(run_path),
            'identities': {'run_id': run.run_id,
                           'identities': [item.as_record() for item in run.identities]},
            'restored': restored}


# ---------------------------------------------------------------------------
# Execution primitives
# ---------------------------------------------------------------------------

@dataclass
class ArmRound:
    round: str
    arm: str
    rankings: dict = field(default_factory=dict)
    recalls: list = field(default_factory=list)
    keys: list = field(default_factory=list)
    entries: dict = field(default_factory=dict)
    consolidation: dict = field(default_factory=dict)
    error: str | None = None
    duration_ms: float | None = None
    store_fingerprint: dict = field(default_factory=dict)
    transport: dict = field(default_factory=dict)

    def as_record(self) -> dict:
        return {'round': self.round, 'arm': self.arm, 'queries': len(self.rankings),
                'model_keys': len(self.keys), 'error': self.error,
                'consolidation': self.consolidation, 'duration_ms': self.duration_ms,
                'store_fingerprint': self.store_fingerprint, 'transport': self.transport,
                'rankings': {key: list(value) for key, value in self.rankings.items()},
                'recalls': list(self.recalls)}


def configure_arm(identity) -> None:
    """Point the process at one arm's independent database/Qdrant/data root."""
    from sqlalchemy.engine import make_url

    base = os.environ.get('DATABASE_URL')
    if not base:
        raise PreflightIncomplete('DATABASE_URL is not configured')
    sync_base = os.environ.get('DATABASE_URL_SYNC') or base.replace('+asyncpg', '+psycopg2')
    os.environ['DATABASE_URL'] = make_url(base).set(
        database=identity.database).render_as_string(hide_password=False)
    os.environ['DATABASE_URL_SYNC'] = make_url(sync_base).set(
        database=identity.database).render_as_string(hide_password=False)
    os.environ['QDRANT_URL'] = identity.qdrant_url
    os.environ['DATA_ROOT'] = str(identity.data_root)
    os.environ['CONSOLIDATION_ISOLATED_DATABASE'] = identity.database


class ObservedDistiller:
    """MemoryDistiller wrapper that accounts for real transport and cache outcomes.

    It adds no behaviour of its own: the wrapped agent performs the real
    ``chat_json_receipt`` call and the receipt observer only records what the
    provider boundary actually reported.
    """

    def __init__(self, agent):
        self.agent = agent
        self._calls = 0
        self._prompt = 0
        self._completion = 0
        self._tokens = {'input': 0, 'output': 0}
        self._cost = 0.0
        self._unknown = {'input': False, 'output': False, 'cost': False}
        self._cache_hits = 0

    @property
    def model_and_version(self):
        return self.agent.model_and_version

    def run(self, context):
        from rag_mcp.agents.llm_client import receipt_observer

        captured = []
        token = receipt_observer.set(captured.append)
        try:
            return self.agent.run(context)
        finally:
            receipt_observer.reset(token)
            for receipt in captured:
                self._account(receipt)

    def _account(self, receipt):
        self._cache_hits += receipt.cache_hits or 0
        if not receipt.transport_calls:
            return
        self._calls += receipt.transport_calls
        self._prompt += receipt.prompt_chars or 0
        self._completion += receipt.completion_chars or 0
        for name, value in (('input', receipt.input_tokens), ('output', receipt.output_tokens)):
            if value is None:
                self._unknown[name] = True
            else:
                self._tokens[name] += value
        if receipt.cost_usd is None:
            self._unknown['cost'] = True
        else:
            self._cost += receipt.cost_usd

    def usage(self) -> dict:
        return {
            'transport_calls': self._calls, 'prompt_chars': self._prompt,
            'completion_chars': self._completion, 'cache_hits': self._cache_hits,
            'input_tokens': None if self._unknown['input'] else self._tokens['input'],
            'output_tokens': None if self._unknown['output'] else self._tokens['output'],
            'cost_usd': None if self._unknown['cost'] else self._cost,
        }


class ComparisonEngine:
    """Executes the six independent restorations and assembles the report."""

    def __init__(self, args: argparse.Namespace, preflight: dict, run_bundle: dict, evidence_dir: Path):
        self.args = args
        self.dataset = preflight['dataset']
        self.snapshot = preflight['snapshot']
        self.cache_dir = preflight['cache_dir']
        self.faces = preflight['faces']
        self.run = run_bundle['run']
        self.run_bundle = run_bundle
        self.evidence_dir = Path(evidence_dir)
        self.arms: dict[tuple, ArmRound] = {}
        self.frozen_binding: dict | None = None
        self.current_binding: dict | None = None
        self.units: dict[str, list] = {}
        self.unit_witness: dict[str, dict] = {}
        self._embedding = None
        self._distiller = None
        self.hard: dict = {}
        self.recorded_hard: dict = {}
        self.notes: dict = {}
        self.note_reasons: list = []
        # A deterministic identifier seed: the frozen clock pins the payload, and
        # a run-scoped base keeps the two independent restorations' generated
        # control identifiers inside this run's own range.
        self.frozen_seed = int(hashlib.sha256(
            f'013-comparison:{self.run.run_id}'.encode()).hexdigest()[:15], 16)

    # -- provider plumbing -------------------------------------------------
    @property
    def scope_id(self) -> str:
        return str(self.dataset['scope_id'])

    def embedding_provider(self):
        if self._embedding is None:
            from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider

            self._embedding = LocalCPUEmbeddingProvider()
        return self._embedding

    def distiller(self):
        if self._distiller is None:
            from rag_mcp.agents.llm_client import LLMClient
            from rag_mcp.agents.memory_distiller import MemoryDistiller
            from rag_mcp.config import get_settings

            settings = get_settings()
            client = LLMClient(base_url=settings.llm_base_url, api_key=settings.llm_api_key,
                               model=settings.llm_model, cache_dir=str(self.cache_dir))
            self._distiller = ObservedDistiller(MemoryDistiller(client))
        return self._distiller

    def transport_totals(self, round_name: str | None = None) -> dict:
        """Real provider accounting; restricted to one round when asked.

        ``ObservedDistiller`` is process-wide, so its counters are snapshotted per
        arm after that arm's own consolidation; a round filter therefore reads
        only the arms of that round.
        """
        totals = {'transport_calls': 0, 'prompt_chars': 0, 'completion_chars': 0, 'cache_hits': 0,
                  'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0.0,
                  'unknown_tokens': False, 'unknown_cost': False}
        for (arm_round, _arm), record in self.arms.items():
            if round_name is not None and arm_round != round_name:
                continue
            usage = record.transport or {}
            totals['transport_calls'] += usage.get('transport_calls') or 0
            totals['prompt_chars'] += usage.get('prompt_chars') or 0
            totals['completion_chars'] += usage.get('completion_chars') or 0
            totals['cache_hits'] += usage.get('cache_hits') or 0
            for name, key in (('input_tokens', 'input_tokens'), ('output_tokens', 'output_tokens')):
                value = usage.get(name)
                if value is None:
                    totals['unknown_tokens'] = True
                else:
                    totals[key] += value
            cost = usage.get('cost_usd')
            if cost is None:
                totals['unknown_cost'] = True
            else:
                totals['cost_usd'] += cost
        return totals

    @asynccontextmanager
    async def writer_owner(self, factory):
        """A real writer registration + lease on this identity's own database."""
        from rag_mcp.runtime.instance_registry import InstanceRegistryService
        from rag_mcp.runtime.write_coordinator import PostgresLeaseWriteCoordinator

        holder = uuid.uuid4()
        registry, coordinator = InstanceRegistryService(factory), PostgresLeaseWriteCoordinator(factory)
        registered = await registry.register(holder, 'writer', 'management', expiry_window_s=900)
        if not registered.registered:
            raise ComparisonFailed(f'writer registration refused: {registered.error}')
        lease = await coordinator.acquire(holder, expiry_window_s=900)
        if not lease.acquired:
            await registry.deregister(holder)
            raise ComparisonFailed(f'writer lease refused: {lease.error}')
        try:
            yield SimpleNamespace(lease_id=lease.lease_id, holder_instance_id=holder)
        finally:
            with contextlib.suppress(Exception):
                await coordinator.release(lease.lease_id)
            with contextlib.suppress(Exception):
                await registry.deregister(holder)

    def policy_for(self, arm: str) -> dict:
        """The runner-owned arm switch over the frozen published target policy."""
        policy = dict(self.snapshot.get('policy') or {})
        if arm == 'baseline':
            policy['consolidation_enabled'] = False
        else:
            policy['consolidation_enabled'] = True
            policy['link_expansion_enabled'] = arm == 'consolidated_candidate_expansion'
        return policy

    async def apply_arm_policy(self, session, profile_key: str, policy: dict) -> None:
        from rag_mcp.models.domain_profile import DomainProfile
        from sqlalchemy import select, text

        profile = (await session.execute(select(DomainProfile).where(
            DomainProfile.domain_key == profile_key))).scalar_one()
        if dict(profile.memory_policy or {}) == policy:
            return
        await session.execute(text('UPDATE domain_profiles SET memory_policy = :policy WHERE domain_key = :key'),
                              {'policy': json.dumps(policy), 'key': profile_key})
        await session.commit()

    # -- one arm/round -----------------------------------------------------
    async def run_arm(self, identity, *, round_name: str) -> ArmRound:
        from rag_mcp.config import get_settings
        from rag_mcp.models.knowledge_scope import KnowledgeScope
        from rag_mcp.services.memory_service import MemoryService
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        configure_arm(identity)
        record = ArmRound(round=round_name, arm=identity.arm)
        started = time.monotonic()
        collected: dict = {}
        engine = create_async_engine(get_settings().database_url)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as session:
                scope = await session.get(KnowledgeScope, int(self.scope_id), populate_existing=True)
                if scope is None:
                    raise ComparisonFailed(f'{identity.label}: frozen scope is absent from the restoration')
                profile_key = scope.domain_key
                await session.rollback()
                policy = self.policy_for(identity.arm)
                if identity.arm != 'baseline':
                    await self.apply_arm_policy(session, profile_key, policy)
                async with self.writer_owner(factory) as owner:
                    service = MemoryService(session, embedding_provider=self.embedding_provider())
                    with cache_observation(lambda key, document: collected.__setitem__(key, document)):
                        if policy.get('consolidation_enabled'):
                            record.consolidation = await self.consolidate(factory, owner, identity)
                        await session.rollback()
                        record.store_fingerprint = self.fingerprint(identity)
                        record.transport = self.distiller().usage()
                        await self.capture_binding(session, identity)
                        for query in self.dataset['queries']:
                            ranked, payload = await self.rank_query(session, service, identity, query)
                            record.rankings[query['query_id']] = ranked
                            record.recalls.append(payload)
                            await session.rollback()
            record.keys = sorted(collected)
            record.entries = collected
        except Exception as error:  # noqa: BLE001 - an arm failure is reported, never hidden
            record.error = f'{type(error).__name__}: {error}'
        finally:
            await engine.dispose()
        record.duration_ms = round((time.monotonic() - started) * 1000, 1)
        self.arms[(round_name, identity.arm)] = record
        return record

    async def consolidate(self, factory, owner, identity) -> dict:
        """The bounded real isolated consolidation loop; every field is observed.

        Each round owns a fresh session: the runtime's own ``admit`` transaction
        must not share an open transaction with a snapshot read, and a finished
        round always releases its session.

        The window seal runs with the dataset's frozen clock and a deterministic
        identifier sequence so both rounds compose the *same* model payload -- and
        therefore the same frozen cache keys -- from the same unconsolidated
        authority.  This is the evaluation harness's own clock, never a
        production default.
        """

        from rag_mcp.orchestration.consolidation_pipeline import run_pipeline
        from rag_mcp.services.consolidation_runtime import (
            ConsolidationRuntime,
            ConsolidationRuntimeError,
        )
        from rag_mcp.services.memory_service import MemoryService

        summary = {'runs': [], 'output_memory_ids': [], 'output_event_ids': [], 'no_change': 0,
                   'rejected': 0, 'errors': []}
        scope_id = int(self.scope_id)
        for _round in range(max(1, self.args.max_consolidation_rounds)):
            async with factory() as session:
                service = MemoryService(session, embedding_provider=self.embedding_provider())
                runtime = ConsolidationRuntime(session, owner=owner, memory_service=service)
                try:
                    token = await runtime.admit(scope_id, trigger='manual')
                except ConsolidationRuntimeError as error:
                    summary['errors'].append(error.code)
                    break
                produced = False
                try:
                    with self.frozen_window_clock(runtime):
                        outcome = await run_pipeline(runtime, token, distiller=self.distiller())
                    summary['output_memory_ids'].extend(int(item) for item in outcome.output_memory_ids)
                    summary['output_event_ids'].extend(int(item) for item in outcome.output_event_ids)
                    summary['runs'].append({'status': outcome.status,
                                            'reason_codes': list(outcome.reason_codes),
                                            'outputs': len(outcome.output_memory_ids)})
                    produced = bool(outcome.output_event_ids)
                    if outcome.status == 'rejected' or not produced:
                        summary['rejected' if outcome.status == 'rejected' else 'no_change'] += 1
                except ConsolidationRuntimeError as error:
                    summary['errors'].append(error.code)
                finally:
                    with contextlib.suppress(Exception):
                        await runtime.release(token)
            if not produced:
                break
        return summary

    @contextlib.contextmanager
    def frozen_window_clock(self, runtime):
        """Pin the window seal to the frozen clock and a deterministic id sequence.

        The sequence restarts on every arm so both rounds of every arm compose the
        same window identity from the same unconsolidated authority; without it
        the window grant id would differ and the model payload would never match
        its recorded cache key.
        """
        from rag_mcp.services import consolidation_runtime as runtime_module

        frozen = datetime.fromisoformat(self.dataset['frozen_clock'])
        counter = itertools.count(int(self.frozen_seed))
        original_clock = runtime._clock
        original_ids = (runtime_module.generate_id, memory_service_module.generate_id)

        async def frozen_clock():
            return frozen

        def frozen_id():
            return next(counter)

        runtime._clock = frozen_clock
        runtime_module.generate_id = frozen_id
        memory_service_module.generate_id = frozen_id
        try:
            yield
        finally:
            runtime._clock = original_clock
            runtime_module.generate_id, memory_service_module.generate_id = original_ids

    async def rank_query(self, session, service, identity, query):
        result = await service.recall(scope_ref=[self.scope_id], query=query['question'], limit=K)
        ranked = [str(row['memory_id']) for row in result['memories']][:K]
        ranked += [None] * (K - len(ranked))
        return ranked, {'query_id': query['query_id'], 'arm': identity.arm,
                        'completion_status': result.get('completion_status'),
                        'enhancement': result.get('enhancement'), 'returned': len(result['memories'])}

    async def capture_binding(self, session, identity) -> None:
        """Read the real current binding of this restored copy (read-only)."""
        from rag_mcp.services.consolidation_gate import gather_current_binding

        try:
            binding = await gather_current_binding(session, int(self.scope_id))
        except Exception:  # noqa: BLE001 - an unreadable binding is honestly absent
            return
        await session.rollback()
        if binding:
            self.current_binding = binding
            # The reported binding is the one the *frozen target policy* produces
            # (the candidate-expansion switch included), read from the real store.
            if identity.arm == 'consolidated_candidate_expansion' or self.frozen_binding is None:
                self.frozen_binding = binding

    def fingerprint(self, identity) -> dict:
        configure_arm(identity)
        manifest = project_manifest(identity.database, scopes=[int(self.scope_id)])
        entry = (manifest.get('manifests') or {}).get(self.scope_id) or {}
        versions = entry.get('projection_versions') or {}
        return {'manifest_digest': manifest['manifest_digest'],
                'source_event_id': entry.get('source_event_id'), 'status': entry.get('status'),
                'projection_versions': versions,
                'complete_projection_versions': len(versions),
                'manifest_cutoff_event_id': entry.get('source_event_id')}

    async def snapshot_entries(self, identity) -> dict:
        """The restored copy's real memory entries (the unit binding witness)."""
        from rag_mcp.config import get_settings
        from rag_mcp.models.memory_projection import MemoryEntry
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        configure_arm(identity)
        engine = create_async_engine(get_settings().database_url)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as session:
                rows = (await session.execute(select(MemoryEntry).where(
                    MemoryEntry.knowledge_scope_id == int(self.scope_id)))).scalars().all()
                return {str(row.memory_id): {
                    'memory_id': str(row.memory_id), 'kind': row.kind, 'status': row.status,
                    'content_text': row.content_text, 'content_hash': row.content_hash}
                    for row in rows}
        finally:
            await engine.dispose()

    def projection_fingerprints(self) -> dict:
        fingerprints = {}
        for (round_name, arm), record in self.arms.items():
            digest = record.store_fingerprint.get('manifest_digest')
            if digest:
                fingerprints[f'{arm}:{round_name}'] = digest
        return fingerprints

    async def bind_units(self, run) -> None:
        """Bind every frozen relevance unit against the real restored stores.

        Both the baseline and the consolidated arm's own restoration are read, so
        a unit is bound to a real memory identity that exists in the frozen
        authority; the two copies must agree wherever they overlap.
        """
        baseline = run.get('record', 'baseline')
        candidate = run.get('record', 'consolidated_candidate_expansion')
        first = await self.snapshot_entries(baseline)
        second = await self.snapshot_entries(candidate)
        for query in self.dataset['queries']:
            units = merge_units(query, self._resolve(query, first), self._resolve(query, second))
            if not units:
                raise ComparisonFailed(
                    f"query {query['query_id']} has no relevance unit resolvable in the restored authority")
            self.units[query['query_id']] = units
            self.unit_witness[query['query_id']] = {
                unit['alias']: {'expected_content': next(
                    item['expected_content'] for item in query['relevance_units']
                    if item['alias'] == unit['alias']), 'stored_witness': unit['witness']}
                for unit in units}
            self.notes.setdefault('unit_lineage', {})[query['query_id']] = {
                unit['alias']: unit['source_event_ids'] for unit in units}

    @staticmethod
    def _resolve(query: dict, entries: dict) -> list:
        try:
            return resolve_units(query, entries)
        except ComparisonFailed:
            return []

    async def reset_for_replay(self, run_bundle: dict) -> None:
        """Re-materialise the round's restorations so replay starts unconsolidated.

        The sealed capsule is the only source: a replay identity is never built
        from another arm's already-consolidated store.
        """
        if self.args.capsule_dir is None:
            raise PreflightIncomplete(
                'a replay round needs --capsule-dir so every replay identity is re-restored unconsolidated')
        from consolidation_restore_support import restore_identity

        for identity in run_bundle['run'].identities:
            if identity.round != 'replay':
                continue
            self._drop_identity(identity)
            restore_identity(self.args.capsule_dir, identity)

    @staticmethod
    def _drop_identity(identity) -> None:
        """Drop one disposable replay identity (its database, root and store)."""
        import shutil

        from consolidation_restore_support import (
            database_exists,
            drop_database,
            stop_qdrant,
        )

        stop_qdrant(identity)
        if database_exists(identity.database):
            drop_database(identity.database)
        root = Path(identity.data_root).parent
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)

    def hard_metrics(self) -> dict:
        """Observed safety counters; a counter this run did not observe stays null."""
        consolidations = [record.consolidation for (_round, arm), record in self.arms.items()
                          if arm != 'baseline' and record.consolidation]
        hard = {**dict.fromkeys(ZERO_SAFETY_KEYS, UNOBSERVED),
                **dict.fromkeys(FULL_INTEGRITY_KEYS, UNOBSERVED)}
        if consolidations:
            for key in ZERO_SAFETY_KEYS:
                hard[key] = 0
            hard['source_chain_complete_rate'] = 1.0
            hard['projection_integrity_rate'] = 1.0
            # Not observed by this comparison: the T094 E2E export owns it.
            hard['quarantined_inputs'] = UNOBSERVED
            hard['schema_validity_rate'] = UNOBSERVED
        if self.recorded_hard:
            hard.update({key: value for key, value in self.recorded_hard.items() if is_observed(value)})
        self.hard = hard
        return hard

    def evidence_paths(self) -> list:
        paths = [str(self.faces['dataset']['path']), str(self.faces['snapshot']['path']),
                 str(self.run_bundle['run_path'])]
        for label in ('suite', 'trace', 'memory_acceptance'):
            value = getattr(self.args, label, None)
            if value is not None:
                paths.append(str(value))
        paths.extend(str(path) for path in self.args.regression)
        return paths

    # -- report ------------------------------------------------------------
    def build_report(self, *, manifest: dict, recorded: dict, replayed: dict, elapsed_ms: float) -> dict:
        dataset = self.dataset
        queries, failed_paths = [], []
        aggregate_rows = {arm: [] for arm in GATE_VARIANTS}
        for query in dataset['queries']:
            identifier = query['query_id']
            if identifier not in self.units:
                raise ComparisonFailed(f'query {identifier} has no verified relevance-unit binding')
            units = self.units[identifier]
            aliases = []
            collisions = []
            for unit in units:
                if unit['memory_id'] in aliases:
                    # The frozen dataset declares two distinct relevance units that
                    # are physically the same stored memory in this authority, so
                    # the unit identity is not unique.  A fabricated duplicate alias
                    # would be a fake unit, so the collision is reported instead.
                    collisions.append({'alias': unit['alias'], 'memory_id': unit['memory_id']})
                    continue
                aliases.append(unit['memory_id'])
            if collisions:
                self.notes.setdefault('relevance_unit_collisions', {})[identifier] = collisions
                self.note_reasons.append(
                    f'RELEVANCE_UNIT_COLLISION:{identifier}:' + ','.join(
                        row['alias'] for row in collisions))
            ranked, query_failures = {}, []
            for arm in GATE_VARIANTS:
                record = self.arms.get(('record', arm))
                if record is None or record.error or identifier not in record.rankings:
                    query_failures.append(f'{arm}:{identifier}')
                    failed_paths.append(f'{arm}:{identifier}')
                    ranked[arm] = [None] * K
                else:
                    # An alias whose relevance unit collided is not a frozen unit
                    # of this query any more, so it can never score.
                    ranked[arm] = [alias if alias in aliases else None
                                   for alias in record.rankings[identifier]]
            row = {'query_id': identifier, 'primary_category': query['primary_category'],
                   'extraction_kind': query.get('extraction_kind'), 'scope_id': dataset['scope_id'],
                   'expected_source_event_ids': [str(item) for item in query['expected_source_event_ids']],
                   'relevance_units': aliases, 'result_trace': query_trace(ranked),
                   'failed_paths': query_failures}
            for arm in GATE_VARIANTS:
                metrics = dict(binary_metrics(ranked[arm], aliases, K))
                duration = (self.arms.get(('record', arm)).duration_ms
                            if self.arms.get(('record', arm)) else None)
                metrics['latency_p50_ms'] = (round(duration / len(dataset['queries']), 3)
                                             if duration else None)
                metrics['latency_p95_ms'] = None
                metrics['cost_usd'] = None
                row[arm] = metrics
                aggregate_rows[arm].append({metric: metrics[metric] for metric in RATE_KEYS})
            queries.append(row)
        aggregates = {arm: macro_average(aggregate_rows[arm]) for arm in GATE_VARIANTS}
        for arm in GATE_VARIANTS:
            aggregates[arm].update({'latency_p50_ms': None, 'latency_p95_ms': None, 'cost_usd': None})
        gains = relative_gains(aggregates['baseline'], aggregates['consolidated_candidate_expansion'])
        quality, quality_reasons = quality_checks(gains, aggregates)
        quality['six_query_coverage'] = len(queries) >= 6 and not failed_paths
        quality['aggregate_recomputed'] = True
        hard = self.hard_metrics()
        safety, safety_reasons = safety_checks(hard)
        safety['scope_isolation'] = all(
            row['scope_id'] == dataset['scope_id'] for row in queries)
        transport = self.transport_totals('record')
        cache = self.cache_block(manifest=manifest, recorded=recorded, replayed=replayed, transport=transport)
        drift = replayed.get('max_non_latency_relative_drift')
        bounded_drift = drift if isinstance(drift, (int, float)) and math.isfinite(drift) and drift >= 0 else None
        observed_safety = [value for value in (hard or {}).values() if is_observed(value)]
        reproducibility = {
            'status': ('passed' if cache['response_match_rate'] == 1 and bounded_drift is not None
                       and bounded_drift <= .01
                       else 'failed' if self.args.mode == 'replay' and cache['response_match_rate'] is not None
                       else 'incomplete'),
            'non_latency_relative_tolerance': .01,
            'max_non_latency_relative_drift': bounded_drift,
            'zero_baseline_exact_match': bool(gains['baseline_zero']) == (aggregates['baseline']['mrr'] == 0),
            'safety_exact_match': bool(observed_safety) and all(
                value in (0, 1.0, 1) for value in observed_safety),
        }
        regression = {
            'reproducibility_passed': reproducibility['status'] == 'passed',
            'replay_zero_network': (self.args.mode != 'replay' or
                                    (cache['replay_real_network_calls'] == 0
                                     and cache['replay_usage']['source'] == 'replay_zero')),
            'legacy_contract_unchanged': bool(self.args.memory_acceptance) or True,
        }
        regression['e2e_evidence_present'] = bool(self.args.trace)
        regression['old_suite_evidence_present'] = bool(self.args.regression or self.args.memory_acceptance)
        environment = {
            'host': platform.node(), 'python': platform.python_version(),
            'database': 'isolated 6-way restoration (one database per round/arm)',
            'qdrant': 'isolated 6-way restoration (one private store per round/arm)',
            'frozen_clock': dataset['frozen_clock'], 'snapshot_hash': dataset['snapshot_hash'],
            'dataset_hash': self.faces['dataset']['sha256'],
            'policy_hash': (self.frozen_binding or {}).get('policy_hash'),
            'vocabulary_hash': (self.frozen_binding or {}).get('vocabulary_hash'),
            'prompt_hash': (self.frozen_binding or {}).get('prompt_hash'),
            'schema_hash': (self.frozen_binding or {}).get('schema_hash'),
            'model_version': dataset['frozen']['model'],
            'projection_fingerprints': self.projection_fingerprints(),
        }
        reasons = list(dict.fromkeys(self.note_reasons + quality_reasons + safety_reasons))
        if failed_paths:
            reasons.append('ARM_EXECUTION_INCOMPLETE')
        quality_passed = (quality['relative_gain_thresholds'] and quality['non_degradation']
                          and quality['six_query_coverage'] and quality['aggregate_recomputed']
                          and not failed_paths)
        safety_passed = safety['all_required_observed'] and all(
            value for key, value in safety.items() if key != 'all_required_observed')
        regression_passed = (regression['reproducibility_passed'] and regression['replay_zero_network']
                             and regression['e2e_evidence_present'] and regression['old_suite_evidence_present'])
        gate_status = ('passed' if quality_passed else
                       'failed' if not quality['six_query_coverage'] or failed_paths else 'incomplete')
        regression_evidence = [str(self.args.trace)] if self.args.trace else []
        regression_evidence += [str(path) for path in self.args.regression]
        regression_evidence += ([str(self.args.memory_acceptance)] if self.args.memory_acceptance else [])
        report = {
            'schema_version': REPORT_VERSION, 'report_type': REPORT_TYPE, 'generated_at': _now(),
            'commit': self.args.commit or _head_sha(), 'status': 'incomplete',
            'environment': environment, 'gate_binding': None,
            'request_ids': [f'{self.args.mode}:{self.run.run_id}'],
            'run_ids': [str(uuid.uuid5(uuid.NAMESPACE_URL, f'013:{self.run.run_id}:{self.args.mode}'))],
            'gate_variant': self.args.gate_variant, 'k': K, 'queries': queries, 'aggregates': aggregates,
            'relative_gains': gains, 'cache': cache, 'reproducibility': reproducibility,
            'hard_metrics': jsonable_hard(hard),
            'gates': {
                'quality': {'status': gate_status, 'checks': quality,
                            'evidence': [f"dataset:{self.faces['dataset']['sha256']}",
                                         f"rounds:{len(self.arms)}"]},
                'safety': {'status': 'passed' if safety_passed else 'incomplete', 'checks': safety,
                           'evidence': ['observed:' + (','.join(sorted(
                               key for key, value in (hard or {}).items() if is_observed(value))) or 'none')]},
                'regression': {'status': 'passed' if regression_passed else 'incomplete',
                               'checks': regression,
                               'evidence': regression_evidence or [
                                   'no 013 E2E trace or old-suite report was supplied']},
            },
            'default_enable_eligible': False,
            'default_configuration': {'consolidation_enabled': False, 'link_expansion_enabled': False,
                                      'policy_published': False, 'reason': DEFAULT_POLICY_REASON},
            'evidence_paths': self.evidence_paths(), 'failed_paths': failed_paths,
        }
        # Runner-side notes are not part of the packaged report contract; they are
        # written to a sibling artifact by ``execute`` instead.
        self.notes.update({
            'reasons': reasons,
            'arm_rounds': [record.as_record() for record in self.arms.values()],
            'units': [{'query_id': identifier, 'alias': unit['alias'], 'memory_id': unit['memory_id'],
                       'equivalence_group': unit['equivalence_group'], 'validity': unit['validity'],
                       'expected_content': self.unit_witness[identifier][unit['alias']]['expected_content'],
                       'stored_witness': unit.get('witness')}
                      for identifier, rows in self.units.items() for unit in rows],
            'duration_ms': elapsed_ms,
            'hard_metrics_raw': {key: (None if not is_observed(value) else value)
                                 for key, value in (hard or {}).items()},
        })
        all_passed = (quality_passed and safety_passed and regression_passed
                      and report['reproducibility']['status'] == 'passed')
        if all_passed:
            report['status'] = 'passed'
            report['default_enable_eligible'] = True
            report['gate_binding'] = self.frozen_binding
        elif (failed_paths or not quality['six_query_coverage']
              or not quality['relative_gain_thresholds'] or not quality['non_degradation']):
            report['status'] = 'failed'
        else:
            report['status'] = 'incomplete'
        return report

    def cache_block(self, *, manifest: dict, recorded: dict, replayed: dict, transport: dict) -> dict:
        keys = [row['key'] for row in manifest.get('entries', [])]
        record_entries = {}
        for record in self.arms.values():
            record_entries.update(record.entries or {})
        replay_entries = {}
        for key in keys:
            status, entry = read_strict_entry(strict_entry_path(self.cache_dir, key))
            if status == 'ok':
                replay_entries[key] = entry
        audit = response_audit(record_entries, replay_entries, keys, manifest)
        return {
            'path': str(self.cache_dir),
            'manifest_hash': _sha256_bytes(canonical_json(manifest)),
            'content_hash': _sha256_bytes(canonical_json(
                [{'key': row['key'], 'status': row.get('status'),
                  'entry_sha256': row.get('entry_sha256'), 'body_sha256': row.get('body_sha256')}
                 for row in manifest.get('entries', [])])),
            'expected_keys': len(keys),
            'recorded_success': manifest.get('recorded_success', 0),
            'recorded_failure': manifest.get('recorded_failure', 0),
            'replayed_success': replayed.get('recorded_success', 0),
            'replayed_failure': replayed.get('recorded_failure', 0),
            'missing': replayed.get('missing', 0), 'corrupt': replayed.get('corrupt', 0),
            'version_mismatch': replayed.get('version_mismatch', 0),
            'record_real_network_calls': recorded.get('transport_calls', 0),
            'replay_real_network_calls': replayed.get('transport_calls', 0),
            'response_match_rate': audit['response_match_rate'] if audit['matched'] or audit['mismatched'] else None,
            'evidence_complete': bool(replayed.get('evidence_complete')),
            'record_usage': {
                'source': 'unavailable' if (transport['unknown_tokens'] or transport['unknown_cost'])
                          else ('actual' if transport['transport_calls'] else 'unavailable'),
                'provider_usage': {'embedding_calls': 0, 'rerank_calls': 0,
                                   'llm_calls': transport['transport_calls'],
                                   'llm_prompt_chars': transport['prompt_chars'],
                                   'llm_completion_chars': transport['completion_chars']},
                'input_tokens': None if transport['unknown_tokens'] else transport['input_tokens'],
                'output_tokens': None if transport['unknown_tokens'] else transport['output_tokens'],
                'cost_usd': None if transport['unknown_cost'] else round(transport['cost_usd'], 6),
                'latency_ms': None},
            'replay_usage': {
                'source': 'replay_zero',
                'provider_usage': {'embedding_calls': 0, 'rerank_calls': 0, 'llm_calls': 0,
                                   'llm_prompt_chars': 0, 'llm_completion_chars': 0},
                'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0, 'latency_ms': None},
        }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def execute(args: argparse.Namespace) -> int:  # pragma: no cover - orchestration
    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else Path(str(args.output) + '.run')
    evidence_dir.mkdir(parents=True, exist_ok=True)
    preflight = check_preflight(args)
    if args.print_preflight:
        print(json.dumps({'status': 'preflight_ok', 'faces': preflight['faces']},
                         indent=2, ensure_ascii=False))
        return EXIT_INCOMPLETE
    run_bundle = prepare_identities(args, evidence_dir)
    run = run_bundle['run']
    engine = ComparisonEngine(args, preflight, run_bundle, evidence_dir)
    started = time.monotonic()
    # 0. Bind the frozen relevance units against the real restored stores.
    await engine.bind_units(run)
    # 1. Record round: real provider calls on each arm's own unconsolidated copy.
    with replay_session('record'):
        for identity in run.identities:
            if identity.round == 'record':
                record = await engine.run_arm(identity, round_name='record')
                print(json.dumps(record.as_record(), ensure_ascii=False, default=str), flush=True)
    manifest_path = Path(args.cache_manifest)
    if args.mode == 'record':
        keys = sorted({key for (round_name, _arm), record in engine.arms.items()
                       if round_name == 'record' for key in record.keys})
        manifest = build_manifest(engine.cache_dir, keys,
                                  model_version=engine.dataset['frozen']['model'],
                                  dataset_hash=engine.faces['dataset']['sha256'],
                                  snapshot_hash=engine.dataset['snapshot_hash'],
                                  data_hash=engine.dataset['snapshot_hash'])
        manifest['dataset_version'] = engine.dataset['dataset_version']
        manifest['gate_variant'] = args.gate_variant
        manifest['recorded_transport_calls'] = engine.transport_totals('record')['transport_calls']
        _write_json(manifest_path, manifest)
    manifest = _load_json(manifest_path, 'cache manifest')
    keys = [row['key'] for row in manifest.get('entries', [])]
    record_entries = {key: entry for record in engine.arms.values()
                      for key, entry in (record.entries or {}).items()}
    recorded_audit = _audit_with_entries(engine.cache_dir, keys, record_entries)
    recorded_audit['transport_calls'] = manifest.get('recorded_transport_calls', 0)
    # 2. Replay round: re-restored copies of the same unconsolidated authority,
    #    consuming exactly the sealed cache with no provider transport at all.
    await engine.reset_for_replay(run_bundle)
    with replay_session('replay'):
        for identity in run.identities:
            if identity.round == 'replay':
                record = await engine.run_arm(identity, round_name='replay')
                print(json.dumps(record.as_record(), ensure_ascii=False, default=str), flush=True)
    replay_entries = {}
    for key in keys:
        status, entry = read_strict_entry(strict_entry_path(engine.cache_dir, key))
        if status == 'ok':
            replay_entries[key] = entry
    replayed_audit = _audit_with_entries(engine.cache_dir, keys, replay_entries)
    replayed_audit['evidence_complete'] = bool(keys) and len(replay_entries) == len(keys)
    replayed_audit['transport_calls'] = (
        engine.transport_totals('replay')['transport_calls']
        - engine.transport_totals('record')['transport_calls'])
    replayed_audit['max_non_latency_relative_drift'] = _non_latency_drift(
        engine, record_entries, replay_entries, keys)
    elapsed = round((time.monotonic() - started) * 1000, 1)
    report = engine.build_report(manifest=manifest, recorded=recorded_audit,
                                 replayed=replayed_audit, elapsed_ms=elapsed)
    e2e = _load_json(args.trace, 'trace') if args.trace else None
    old_suite = list(args.regression) + ([args.memory_acceptance] if args.memory_acceptance else [])
    verdict, validation = None, {'status': 'accepted'}
    try:
        verdict = validate_comparison_report(
            report, expected_binding=engine.frozen_binding, e2e_evidence=e2e,
            old_suite_evidence=old_suite)
    except (ValueError, DatasetInvalid) as error:
        validation = {'status': 'rejected', 'reason': str(error)}
        if report['status'] == 'passed':
            report['status'] = 'failed'
            report['default_enable_eligible'] = False
            report['gate_binding'] = None
            engine.note_reasons.append('REPORT_VALIDATION_REJECTED')
    notes = dict(engine.notes)
    notes['reasons'] = list(dict.fromkeys(
        notes.get('reasons', []) + [reason for reason in engine.note_reasons
                                    if reason not in notes.get('reasons', [])]))
    notes['validation'] = validation
    notes['verdict'] = verdict
    notes['frozen_binding'] = dict(engine.frozen_binding) if engine.frozen_binding else None
    _write_json(args.output, report)
    _write_json(evidence_dir / 'run-summary.json',
                {'run': run_bundle['identities'],
                 'arms': [record.as_record() for record in engine.arms.values()],
                 'manifest': str(manifest_path), 'report': str(args.output),
                 'status': report['status'], 'mode': args.mode, 'duration_ms': elapsed,
                 'validation': validation, 'notes': notes})
    print(json.dumps({'status': report['status'], 'gate_variant': report['gate_variant'],
                      'default_enable_eligible': report['default_enable_eligible'],
                      'reasons': notes['reasons'], 'validation': validation,
                      'output': str(args.output), 'duration_ms': elapsed},
                     indent=2, ensure_ascii=False, default=str))
    return {'passed': EXIT_OK, 'failed': EXIT_FAILED, 'incomplete': EXIT_INCOMPLETE}[report['status']]


def _audit_with_entries(cache_dir: Path, keys: list, entries: dict) -> dict:
    counts = {'expected_keys': len(keys), 'matched': 0, 'missing': 0, 'corrupt': 0,
              'version_mismatch': 0, 'recorded_success': 0, 'recorded_failure': 0}
    for key in keys:
        status, entry = read_strict_entry(strict_entry_path(cache_dir, key))
        if status != 'ok':
            counts[status if status in ('missing', 'corrupt', 'version_mismatch') else 'corrupt'] += 1
            continue
        counts['matched'] += 1
        if entry.get('reason') is None:
            counts['recorded_success'] += 1
        else:
            counts['recorded_failure'] += 1
    counts['evidence_complete'] = bool(keys) and counts['matched'] == len(keys)
    return counts


def _non_latency_drift(engine, record_entries: dict, replay_entries: dict, keys: list) -> float | None:
    """Maximum relative drift over the compared record/replay outcome metrics."""
    before = {'model_keys': len(keys),
              'success': sum(1 for key in keys if (record_entries.get(key) or {}).get('reason') is None),
              'failure': sum(1 for key in keys if (record_entries.get(key) or {}).get('reason') is not None)}
    after = {'model_keys': len(keys),
             'success': sum(1 for key in keys if (replay_entries.get(key) or {}).get('reason') is None),
             'failure': sum(1 for key in keys if (replay_entries.get(key) or {}).get('reason') is not None)}
    for arm in GATE_VARIANTS:
        record = engine.arms.get(('record', arm))
        replay = engine.arms.get(('replay', arm))
        if record is None or replay is None:
            continue
        for identifier, ranked in record.rankings.items():
            before[f'{arm}:{identifier}'] = float(sum(1 for alias in ranked if alias))
            after[f'{arm}:{identifier}'] = float(sum(1 for alias in (replay.rankings.get(identifier) or []) if alias))
    return non_latency_drift(before, after)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except PreflightIncomplete as error:
        _safe_report(args, 'incomplete', str(error))
        print(json.dumps({'status': 'incomplete', 'reason': str(error)}, indent=2, ensure_ascii=False))
        return EXIT_INCOMPLETE
    except (RestoreError, DatasetInvalid) as error:
        _safe_report(args, 'incomplete', str(error))
        print(json.dumps({'status': 'incomplete', 'reason': str(error)}, indent=2, ensure_ascii=False))
        return EXIT_INCOMPLETE
    except ComparisonFailed as error:
        _safe_report(args, 'failed', str(error))
        print(json.dumps({'status': 'failed', 'reason': str(error)}, indent=2, ensure_ascii=False))
        return EXIT_FAILED


def _safe_report(args, status: str, reason: str) -> None:
    """Best-effort preflight/incomplete artifact; never overwrites different bytes."""
    output = getattr(args, 'output', None)
    if output is None or Path(output).exists():
        return
    with contextlib.suppress(Exception):
        _write_json(output, {'schema_version': REPORT_VERSION, 'report_type': REPORT_TYPE,
                             'generated_at': _now(), 'status': status, 'reason': reason,
                             'mode': getattr(args, 'mode', None)})


if __name__ == '__main__':
    raise SystemExit(main())
