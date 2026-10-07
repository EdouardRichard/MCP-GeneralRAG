"""013 evaluation dataset validation and three-arm metric adapter (T095/T096/T098).

Pure evaluation-side code. The backend never imports this module; this module
reuses the shared pure backend validator and metric implementation
(``services/consolidation_gate.py``) instead of defining a wider rule set of its
own, exactly as ``evaluation-contract.md`` requires.

Frozen metric definitions (T090 handoff, shared with the production validator):

* all five rates are scored inside the frozen ``k = 5`` window;
* MRR/nDCG use the true physical rank, never a re-numbered deduplicated list;
* a duplicated alias gains 0 after its first occurrence;
* ``precision_at_k`` is divided by ``k`` and a missing rank contributes 0;
* a zero baseline is ``not_computable``: the relative gain is ``null`` and the
  report can never be ``passed``/default-enable eligible.

The dataset validator is the prerequisite T095 must run before any real provider
call. It enforces the structural contract (distinct query ids, coverage slots,
2+2+2 primary classes, both extraction kinds, non-empty expected content,
locatable sources, legal lineage and equivalence groups). It deliberately does
not invent domain semantics: the domain expert freezes the actual expected
content, and no failure query is ever removed after a run.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from rag_mcp.services.consolidation_gate import (
    GATE_VARIANTS,
    TRACE_VERSION,
    binary_metrics,
    canonical_json,
    macro_average,
    recompute_query_metrics,
    validate_report,
)

K = 5
DATASET_VERSION_PREFIX = '013.'
COVERAGE_SLOTS = ('extract_fact_01', 'distill_procedure_01', 'correct_01', 'correct_02',
                  'merge_01', 'merge_02')
PRIMARY_CLASSES = ('extraction', 'correction', 'merge')
FROZEN_FIELDS = ('model', 'prompt', 'schema', 'policy', 'vocabulary', 'recall', 'budget',
                 'implementation', 'snapshot', 'clock')
RATE_KEYS = ('mrr', 'ndcg', 'hit_rate', 'recall_at_k', 'precision_at_k')
HASH = re.compile(r'^[a-f0-9]{64}$')
DECIMAL = re.compile(r'^[1-9][0-9]*$')


class DatasetInvalid(ValueError):
    """The frozen evaluation dataset does not satisfy the contract."""


def load_dataset(path):
    """Strict JSON load (no duplicate keys, no non-finite numbers)."""
    def pairs(items):
        keys = [key for key, _ in items]
        if len(set(keys)) != len(keys):
            raise DatasetInvalid('duplicate JSON object key')
        return dict(items)

    def constant(value):
        raise DatasetInvalid('non-finite JSON number')

    try:
        raw = path.read_bytes() if hasattr(path, 'read_bytes') else bytes(path)
    except OSError as error:
        raise DatasetInvalid(f'dataset unreadable: {error}') from error
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise DatasetInvalid('invalid dataset JSON') from error


def _nonempty_string(value, where):
    if not isinstance(value, str) or not value.strip():
        raise DatasetInvalid(f'{where} must be a non-empty string')
    return value


def _timestamp(value, where):
    _nonempty_string(value, where)
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise DatasetInvalid(f'{where} is not an ISO timestamp') from error
    if stamp.tzinfo is None:
        raise DatasetInvalid(f'{where} requires a timezone')
    return value


def validate_dataset(dataset):
    """Structural validation; raises :class:`DatasetInvalid` on any violation."""
    if not isinstance(dataset, dict):
        raise DatasetInvalid('dataset must be an object')
    for key in ('dataset_version', 'k', 'gate_variant', 'scope_id', 'snapshot_hash',
                'authority_cutoff', 'frozen_clock', 'frozen', 'domain_profile', 'queries'):
        if key not in dataset:
            raise DatasetInvalid(f'dataset missing {key}')
    version = _nonempty_string(dataset['dataset_version'], 'dataset_version')
    if not version.startswith(DATASET_VERSION_PREFIX):
        raise DatasetInvalid('dataset_version must be an 013.x version')
    if dataset['k'] != K:
        raise DatasetInvalid('dataset k must be the frozen k=5')
    if dataset['gate_variant'] not in GATE_VARIANTS[1:]:
        raise DatasetInvalid('dataset gate_variant must be a consolidated arm')
    if not isinstance(dataset['scope_id'], str) or not DECIMAL.match(dataset['scope_id']):
        raise DatasetInvalid('dataset scope_id must be a decimal string')
    if not isinstance(dataset['snapshot_hash'], str) or not HASH.match(dataset['snapshot_hash']):
        raise DatasetInvalid('dataset snapshot_hash must be a sha256 hex digest')
    if not isinstance(dataset['authority_cutoff'], int) or dataset['authority_cutoff'] <= 0:
        raise DatasetInvalid('dataset authority_cutoff must be a positive integer')
    _timestamp(dataset['frozen_clock'], 'frozen_clock')
    frozen = dataset['frozen']
    if not isinstance(frozen, dict):
        raise DatasetInvalid('dataset frozen versions must be an object')
    for field in FROZEN_FIELDS:
        _nonempty_string(frozen.get(field), f'frozen.{field}')
    profile = dataset['domain_profile']
    if not isinstance(profile, dict) or not profile.get('domain_key'):
        raise DatasetInvalid('dataset domain_profile requires a domain_key')
    if not isinstance(profile.get('declared_topic_adaptations', []), list):
        raise DatasetInvalid('declared_topic_adaptations must be a list')

    queries = dataset['queries']
    if not isinstance(queries, list) or len(queries) < 6:
        raise DatasetInvalid('dataset requires at least six queries')
    identifiers = [query.get('query_id') for query in queries]
    if len(set(identifiers)) != len(identifiers) or any(not identifier for identifier in identifiers):
        raise DatasetInvalid('dataset query ids must be distinct and non-empty')
    slots = [query.get('coverage_slot') for query in queries]
    if sorted(slots) != sorted(COVERAGE_SLOTS):
        raise DatasetInvalid('dataset must bind each frozen coverage slot exactly once')
    categories = [query.get('primary_category') for query in queries]
    for category in PRIMARY_CLASSES:
        if categories.count(category) < 2:
            raise DatasetInvalid('dataset must cover each primary class at least twice')
    kinds = {query.get('extraction_kind') for query in queries
             if query.get('primary_category') == 'extraction'}
    if kinds != {'semantic', 'procedural'}:
        raise DatasetInvalid('dataset requires semantic and procedural extraction')
    if any(query.get('primary_category') not in PRIMARY_CLASSES for query in queries):
        raise DatasetInvalid('dataset primary_category invalid')
    for query in queries:
        _validate_query(query, dataset['scope_id'])
    return dataset


def _validate_query(query, scope_id):
    where = f"query {query.get('query_id')}"
    if not isinstance(query, dict):
        raise DatasetInvalid('dataset query must be an object')
    _nonempty_string(query.get('question'), f'{where}.question')
    if query.get('scope_id') != scope_id:
        raise DatasetInvalid(f'{where} must belong to the frozen scope')
    category = query['primary_category']
    if category == 'extraction' and query.get('extraction_kind') not in ('semantic', 'procedural'):
        raise DatasetInvalid(f'{where} extraction kind invalid')
    if category != 'extraction' and query.get('extraction_kind') is not None:
        raise DatasetInvalid(f'{where} must not declare an extraction kind')
    expected = query.get('expected_content')
    if not isinstance(expected, list) or not expected:
        raise DatasetInvalid(f'{where} requires non-empty expected content')
    for value in expected:
        _nonempty_string(value, f'{where}.expected_content entry')

    locators = query.get('locators')
    if not isinstance(locators, list) or not locators:
        raise DatasetInvalid(f'{where} requires locatable corpus/event positions')
    event_ids, chunk_ids = set(), set()
    for locator in locators:
        if not isinstance(locator, dict) or locator.get('kind') not in ('event', 'chunk'):
            raise DatasetInvalid(f'{where} locator kind invalid')
        if locator['kind'] == 'event':
            identifier = str(locator.get('event_id'))
            if not DECIMAL.match(identifier):
                raise DatasetInvalid(f'{where} event locator id invalid')
            event_ids.add(identifier)
        else:
            identifier = str(locator.get('chunk_id'))
            if not DECIMAL.match(identifier):
                raise DatasetInvalid(f'{where} chunk locator id invalid')
            _nonempty_string(locator.get('position_path'), f'{where} chunk position_path')
            chunk_ids.add(identifier)
    expected_ids = query.get('expected_source_event_ids')
    if not isinstance(expected_ids, list) or not expected_ids:
        raise DatasetInvalid(f'{where} requires expected_source_event_ids')
    if not set(map(str, expected_ids)) <= event_ids:
        raise DatasetInvalid(f'{where} expected source events are not locatable')

    units = query.get('relevance_units')
    if not isinstance(units, list) or not units:
        raise DatasetInvalid(f'{where} requires relevance units')
    aliases, groups = [], {}
    for unit in units:
        if not isinstance(unit, dict):
            raise DatasetInvalid(f'{where} relevance unit must be an object')
        alias = _nonempty_string(unit.get('alias'), f'{where}.relevance_units.alias')
        _nonempty_string(unit.get('expected_content'), f'{where}.relevance_units.expected_content')
        _nonempty_string(unit.get('equivalence_group'), f'{where}.relevance_units.equivalence_group')
        if unit.get('validity') not in ('current', 'historical', 'withdrawn'):
            raise DatasetInvalid(f'{where} relevance unit validity invalid')
        source_ids = unit.get('source_event_ids')
        if not isinstance(source_ids, list) or not source_ids:
            raise DatasetInvalid(f'{where} relevance unit requires a source chain')
        if not set(map(str, source_ids)) <= event_ids:
            raise DatasetInvalid(f'{where} relevance unit lineage is not locatable')
        group = unit['equivalence_group']
        content = unit['expected_content']
        if group in groups and groups[group] != content:
            raise DatasetInvalid(f'{where} equivalence group mixes different content')
        groups[group] = content
        aliases.append(alias)
    if len(set(aliases)) != len(aliases):
        raise DatasetInvalid(f'{where} relevance aliases must be distinct')
    return query


def query_metrics(ranked_aliases, relevance_units, k=K):
    """Frozen-Window binary metrics at true physical rank (shared implementation)."""
    return binary_metrics(ranked_aliases, relevance_units, k)


def trace_for(ranked_by_arm, k=K):
    """Frozen ``013.trace.1`` result trace from per-arm physical-rank aliases."""
    variants = {}
    for arm in GATE_VARIANTS:
        ranked = list(ranked_by_arm.get(arm) or [])
        if len(ranked) > k:
            ranked = ranked[:k]
        variants[arm] = ranked + [None] * (k - len(ranked))
    return {'trace_version': TRACE_VERSION, 'k': k, 'variants': variants}


def cross_check_012_metric_functions(ranked_aliases, relevance_units, k=K):
    """Prove the frozen adapter agrees with ``eval/run_eval.py``.

    The 012 functions have no duplicate-alias rule, so the comparison uses a
    ranking with distinct aliases only; a divergence raises instead of being
    silently tolerated.
    """
    from run_eval import compute_mrr, compute_ndcg_at_k

    ranked = list(ranked_aliases)[:k]
    if len({alias for alias in ranked if alias is not None}) != len(
            [alias for alias in ranked if alias is not None]):
        raise DatasetInvalid('012 cross-check requires distinct aliases')
    units = [unit for unit in relevance_units]
    metrics = binary_metrics(ranked, units, k)
    expected_mrr = compute_mrr(units, ranked)
    expected_ndcg = compute_ndcg_at_k(units, ranked, k) if units else 0.0
    if abs(metrics['mrr'] - expected_mrr) > 1e-12 or abs(metrics['ndcg'] - expected_ndcg) > 1e-12:
        raise DatasetInvalid('frozen metrics diverge from the 012 MRR/nDCG functions')
    return metrics


def relative_gains(baseline, expansion):
    """Relative gains; a zero baseline stays not-computable (never epsilon)."""
    zero = baseline['mrr'] == 0 or baseline['ndcg'] == 0
    gains = {'baseline_zero': zero}
    for metric in ('mrr', 'ndcg'):
        gains[metric] = None if zero else (expansion[metric] - baseline[metric]) / baseline[metric]
    return gains


def arm_report(queries, traces, *, k=K, latency=None, cost=None):
    """Per-query and macro metrics for the three arms; direct fallback is visible.

    ``traces`` maps ``query_id -> {arm: [alias per physical rank]}`` and
    ``latency``/``cost`` map ``(query_id, arm) -> value`` (``None`` = unmeasured,
    never fabricated as zero).
    """
    per_query, direct_fallback = [], []
    for query in queries:
        units = [unit['alias'] for unit in query['relevance_units']]
        ranked = traces.get(query['query_id'])
        if not isinstance(ranked, dict) or set(ranked) != set(GATE_VARIANTS):
            raise DatasetInvalid(f"query {query['query_id']} requires all three frozen arms")
        row = {'query_id': query['query_id'], 'coverage_slot': query['coverage_slot'],
               'primary_category': query['primary_category'],
               'extraction_kind': query.get('extraction_kind')}
        for arm in GATE_VARIANTS:
            metrics = dict(binary_metrics(ranked[arm], units, k))
            metrics['latency_p50_ms'] = (latency or {}).get((query['query_id'], arm))
            metrics['latency_p95_ms'] = None
            metrics['cost_usd'] = (cost or {}).get((query['query_id'], arm))
            row[arm] = metrics
        if [alias for alias in ranked['consolidated_direct'] if alias] == \
                [alias for alias in ranked['consolidated_candidate_expansion'] if alias]:
            direct_fallback.append(query['query_id'])
        per_query.append(row)
    aggregates = {arm: macro_average([{key: row[arm][key] for key in RATE_KEYS} for row in per_query])
                  for arm in GATE_VARIANTS}
    return {'k': k, 'per_query': per_query, 'aggregates': aggregates,
            'relative_gains': relative_gains(aggregates['baseline'],
                                             aggregates['consolidated_candidate_expansion']),
            'direct_fallback_queries': direct_fallback}


def validate_comparison_report(report, *, expected_binding=None, e2e_evidence=None,
                               old_suite_evidence=None):
    """T098 entry point: shared 013.2 validation plus eval-level totality checks.

    Only returns a decision; it never installs a registry entry, never publishes
    a policy and never rewrites a binding. A passed report without the real E2E
    evidence index and the old-suite evidence is refused as incomplete evidence.
    """
    validate_report(report)
    if report['status'] == 'passed':
        if e2e_evidence is None:
            raise DatasetInvalid('passed report requires the real 013 E2E evidence index')
        _validate_e2e_evidence(e2e_evidence)
        if not old_suite_evidence:
            raise DatasetInvalid('passed report requires the 012/001-012 old-suite evidence')
    if expected_binding is not None and report['gate_binding'] is not None \
            and canonical_json(dict(report['gate_binding'])) != canonical_json(dict(expected_binding)):
        raise DatasetInvalid('report binding does not match the current trusted binding')
    cache = report['cache']
    recorded = cache['recorded_success'] + cache['recorded_failure']
    replayed = cache['replayed_success'] + cache['replayed_failure']
    if report['status'] == 'passed' and (recorded != cache['expected_keys'] or replayed != recorded):
        raise DatasetInvalid('cache response coverage is not 100%')
    if report['status'] == 'passed' and (cache['record_real_network_calls'] < 1
                                         or cache['replay_real_network_calls'] != 0):
        raise DatasetInvalid('replay must deny every real LLM transport call')
    for row in report['queries']:
        recomputed = recompute_query_metrics(row, report['k'])
        for arm in GATE_VARIANTS:
            for metric in RATE_KEYS:
                if abs(row[arm][metric] - recomputed[arm][metric]) > 1e-12:
                    raise DatasetInvalid('query metrics are not the frozen physical-rank result')
    return {'status': report['status'], 'gate_variant': report['gate_variant'],
            'default_enable_eligible': report['default_enable_eligible'],
            'binding': dict(report['gate_binding']) if report['gate_binding'] else None}


def _validate_e2e_evidence(evidence):
    """The real E2E evidence index must cover every T092/T093 class."""
    scenarios = set()
    for test in evidence.get('tests', []):
        for record in test.get('records', []):
            scenarios.add(record.get('scenario'))
    required = {'batch_distillation', 'deterministic_merge', 'deterministic_correction',
                'soft_overturn_refusal', 'model_schema_fault', 'benefit_gate_control',
                'manual_candidate_promotion'}
    missing = required - scenarios
    if missing:
        raise DatasetInvalid(f'013 E2E evidence incomplete: {sorted(missing)}')
    counts = evidence.get('hard_counts') or {}
    for name in ('cross_scope_leaks', 'soft_overturns_hard', 'automatic_promotions',
                 'invalid_outputs_applied', 'stale_holder_commits',
                 'incomplete_outputs_consumed', 'rebuild_llm_calls'):
        if counts.get(name) is None:
            raise DatasetInvalid(f'013 E2E evidence has no observation for {name}')
        if counts[name] != 0:
            raise DatasetInvalid(f'013 E2E evidence observed {name}={counts[name]}')
    for name in ('source_chain_complete_rate', 'projection_integrity_rate'):
        if counts.get(name) != 1:
            raise DatasetInvalid(f'013 E2E evidence observed {name}={counts.get(name)!r}')
    if evidence.get('exitstatus') != 0:
        raise DatasetInvalid('013 E2E evidence run did not succeed')
