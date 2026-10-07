"""T096/T097/T098: contract tests for the 013 comparison runner.

Pure tests.  They prove the frozen relevance-unit binding, the record/replay
cache sealing and response audit, the preflight/exit-code contract, the
three-gate arithmetic and the report shape accepted by the shared 013.2
validator.  No database, provider or store is required; the executable
record/replay evidence is produced by ``eval/run_consolidation_comparison.py``
itself against the isolated restorations (T102).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _path in (ROOT / 'eval', ROOT / 'backend' / 'src'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from consolidation_eval_support import K, validate_comparison_report
from run_consolidation_comparison import (
    EXIT_INCOMPLETE,
    MANIFEST_API_VERSION,
    UNOBSERVED,
    WINDOW_ID_STRIDE,
    ArmRound,
    ComparisonEngine,
    ComparisonFailed,
    PreflightIncomplete,
    _audit_with_entries,
    _non_latency_drift,
    check_preflight,
    finalize_safety,
    main,
    merge_safety,
    merge_units,
    quality_checks,
    query_trace,
    relative_gains,
    resolve_units,
    response_audit,
    safety_checks,
    safety_entry,
)

from rag_mcp.agents.consolidation_replay import (
    CACHE_MANIFEST_VERSION,
    build_manifest,
    cache_observation,
    strict_cache_dir,
    strict_entry_path,
)
from rag_mcp.services.consolidation_gate import GATE_CHECKS, GATE_VARIANTS, TRACE_VERSION

SCOPE = '366084747748704256'
CONTENT = {f'unit-{index}': f'frozen content {index}' for index in range(1, 8)}


def dataset_document():
    """A six-query frozen dataset in the T095 shape."""
    categories = {'extract_fact_01': ('extraction', 'semantic'),
                  'distill_procedure_01': ('extraction', 'procedural'),
                  'correct_01': ('correction', None), 'correct_02': ('correction', None),
                  'merge_01': ('merge', None), 'merge_02': ('merge', None)}
    queries = []
    for index, (slot, (category, kind)) in enumerate(categories.items()):
        alias = f'unit-{index + 1}'
        query = {
            'query_id': f'q_{slot}', 'coverage_slot': slot, 'primary_category': category,
            'extraction_kind': kind, 'question': f'What is frozen for {slot}?', 'scope_id': SCOPE,
            'expected_content': [CONTENT[alias]],
            'expected_source_event_ids': [str(1000 + index)],
            'locators': [{'kind': 'event', 'event_id': str(1000 + index)},
                         {'kind': 'chunk', 'chunk_id': str(500 + index), 'position_path': f'section/{index}'}],
            'relevance_units': [{'alias': alias, 'expected_content': CONTENT[alias],
                                 'equivalence_group': f'eq-{alias}', 'source_event_ids': [str(1000 + index)],
                                 'validity': 'current'}]}
        queries.append(query)
    return {
        'dataset_version': '013.eval.1', 'k': K, 'gate_variant': 'consolidated_candidate_expansion',
        'scope_id': SCOPE, 'snapshot_hash': 'b' * 64, 'authority_cutoff': 4242,
        'frozen_clock': '2026-10-07T00:00:00+00:00',
        'frozen': {field: f'{field}-v1' for field in
                   ('model', 'prompt', 'schema', 'policy', 'vocabulary', 'recall', 'budget',
                    'implementation', 'snapshot', 'clock')},
        'domain_profile': {'domain_key': 'c013-eval-generic', 'declared_topic_adaptations': ['notes']},
        'queries': queries}


def snapshot_document(policy=None):
    return {'scope_id': SCOPE,
            'authority': {'authority_digest': 'b' * 64, 'authority_cutoff': 4242,
                          'alembic_version': '0104_runtime_activity_signals'},
            'policy': policy or {'consolidation_enabled': True, 'link_expansion_enabled': False},
            'frozen_clock': '2026-10-07T00:00:00+00:00'}


def write_inputs(tmp_path, *, policy=None):
    dataset_path = tmp_path / 'dataset.json'
    dataset_path.write_text(json.dumps(dataset_document()), encoding='utf-8')
    snapshot_path = tmp_path / 'snapshot.json'
    snapshot_path.write_text(json.dumps(snapshot_document(policy)), encoding='utf-8')
    return dataset_path, snapshot_path


def base_args(tmp_path, *, mode='record', **overrides):
    dataset_path, snapshot_path = write_inputs(tmp_path)
    arguments = {'dataset': dataset_path, 'snapshot': snapshot_path, 'mode': mode,
                 'cache_manifest': tmp_path / 'cache-manifest.json',
                 'gate_variant': 'consolidated_candidate_expansion',
                 'output': tmp_path / 'report.json', 'suite': None, 'trace': None,
                 'memory_acceptance': None, 'regression': [], 'cache_dir': None,
                 'evidence_dir': None, 'commit': None, 'run': None, 'run_id': 't097test',
                 'capsule_dir': tmp_path / 'capsule', 'base': tmp_path / 'runs',
                 'qdrant_port_base': 18400, 'max_consolidation_rounds': 2,
                 'print_preflight': False, 'restore': False}
    arguments.update(overrides)
    return SimpleNamespace(**arguments)


# ---------------------------------------------------------------------------
# T096: frozen relevance-unit binding
# ---------------------------------------------------------------------------

def test_unit_binding_uses_declared_lineage_and_keeps_a_real_store_witness():
    query = dataset_document()['queries'][0]
    memory_id = query['expected_source_event_ids'][0]
    entries = {memory_id: {'memory_id': memory_id, 'content_text': CONTENT['unit-1']}}
    resolved = resolve_units(query, entries)
    assert len(resolved) == 1
    unit = resolved[0]
    assert unit['alias'] == 'unit-1' and unit['memory_id'] == memory_id
    assert unit['source_event_ids'] == [memory_id]
    assert unit['witness'] == {memory_id: CONTENT['unit-1']}
    # A frozen expected_content that is only a paraphrase of the source memory is
    # not a filter; the declared lineage is the identity.
    paraphrased = {memory_id: {'memory_id': memory_id,
                               'content_text': f'Intro sentence. {CONTENT["unit-1"]}'}}
    assert resolve_units(query, paraphrased)[0]['memory_id'] == memory_id
    # A unit whose declared lineage is outside expected_source_event_ids is refused.
    tampered = json.loads(json.dumps(query))
    tampered['relevance_units'][0]['source_event_ids'] = ['777']
    with pytest.raises(ComparisonFailed, match='outside the declared set'):
        resolve_units(tampered, entries)
    # A unit whose declared lineage does not exist in this restoration is refused.
    with pytest.raises(ComparisonFailed, match='absent from the restored authority'):
        resolve_units(query, {})


def test_merge_units_agrees_across_independent_restorations_and_rejects_drift():
    query = dataset_document()['queries'][0]
    memory_id = query['expected_source_event_ids'][0]
    first = [{'alias': 'unit-1', 'memory_id': memory_id}]
    second = [{'alias': 'unit-1', 'memory_id': memory_id}]
    assert merge_units(query, first, second) == first
    drifted = [{'alias': 'unit-1', 'memory_id': '999'}]
    with pytest.raises(ComparisonFailed, match='different memories'):
        merge_units(query, first, drifted)


def test_trace_and_relative_gains_follow_the_frozen_metric_definitions():
    trace = query_trace({'baseline': ['a'], 'consolidated_direct': [],
                         'consolidated_candidate_expansion': ['c'] * 9})
    assert trace['trace_version'] == TRACE_VERSION and trace['k'] == K
    assert trace['variants']['baseline'] == ['a', None, None, None, None]
    assert trace['variants']['consolidated_candidate_expansion'] == ['c'] * 5
    assert relative_gains({'mrr': 0, 'ndcg': .5}, {'mrr': .9, 'ndcg': .9}) == {
        'baseline_zero': True, 'mrr': None, 'ndcg': None}
    gains = relative_gains({'mrr': .5, 'ndcg': .5}, {'mrr': .55, 'ndcg': .6})
    assert gains == {'baseline_zero': False, 'mrr': pytest.approx(.1), 'ndcg': pytest.approx(.2)}


def test_quality_gate_needs_both_metrics_three_percent_and_no_non_degradation():
    aggregates = {'baseline': {'mrr': .5, 'ndcg': .5, 'hit_rate': .5, 'recall_at_k': .5,
                               'precision_at_k': .5},
                  'consolidated_direct': {'mrr': .52, 'ndcg': .52, 'hit_rate': .5,
                                          'recall_at_k': .5, 'precision_at_k': .5},
                  'consolidated_candidate_expansion': {'mrr': .55, 'ndcg': .55, 'hit_rate': .5,
                                                       'recall_at_k': .5, 'precision_at_k': .5}}
    checks, reasons = quality_checks(relative_gains(aggregates['baseline'],
                                                    aggregates['consolidated_candidate_expansion']),
                                     aggregates)
    assert checks == {'relative_gain_thresholds': True, 'non_degradation': True} and reasons == []
    # MRR passes but nDCG does not: the AND threshold must fail.
    weak = {'baseline': dict(aggregates['baseline']),
            'consolidated_direct': dict(aggregates['consolidated_direct']),
            'consolidated_candidate_expansion': {**aggregates['consolidated_candidate_expansion'],
                                                 'ndcg': .51}}
    checks, reasons = quality_checks(relative_gains(weak['baseline'],
                                                    weak['consolidated_candidate_expansion']), weak)
    assert checks['relative_gain_thresholds'] is False and 'RELATIVE_GAIN_BELOW_THRESHOLD' in reasons
    # A recall drop on the direct path is never hidden.
    regressed = {**weak, 'consolidated_direct': {**weak['consolidated_direct'], 'recall_at_k': .4}}
    checks, reasons = quality_checks(relative_gains(regressed['baseline'],
                                                    regressed['consolidated_candidate_expansion']),
                                     regressed)
    assert checks['non_degradation'] is False and 'DIRECT_PATH_REGRESSION' in reasons
    # A zero baseline is not computable rather than a fabricated gain.
    zero = {key: {**value, 'mrr': 0, 'ndcg': 0} for key, value in aggregates.items()}
    checks, reasons = quality_checks(relative_gains(zero['baseline'],
                                                    zero['consolidated_candidate_expansion']), zero)
    assert checks['relative_gain_thresholds'] is False and 'BASELINE_ZERO_NOT_COMPUTABLE' in reasons


def test_safety_gate_has_zero_tolerance_and_keeps_unobserved_counters_null():
    complete = {name: 0 for name in ('cross_scope_leaks', 'quarantined_inputs', 'soft_overturns_hard',
                                     'automatic_promotions', 'invalid_outputs_applied',
                                     'stale_holder_commits', 'incomplete_outputs_consumed',
                                     'rebuild_llm_calls')}
    complete.update({'source_chain_complete_rate': 1.0, 'schema_validity_rate': 1.0,
                     'projection_integrity_rate': 1.0})
    checks, reasons = safety_checks(complete)
    assert checks['all_required_observed'] is True and all(
        value for key, value in checks.items() if key != 'all_required_observed') and reasons == []
    broken = {**complete, 'stale_holder_commits': 1}
    checks, reasons = safety_checks(broken)
    assert checks['stale_holder_commits'] is False and 'STALE_HOLDER_COMMITS_VIOLATION' in reasons
    partial = {**complete, 'quarantined_inputs': None}
    checks, reasons = safety_checks(partial)
    assert checks['all_required_observed'] is False
    assert any(reason.startswith('SAFETY_OBSERVATION_INCOMPLETE') for reason in reasons)
    assert checks['quarantined_inputs'] is False


# ---------------------------------------------------------------------------
# T097: cache sealing, response audit and drift
# ---------------------------------------------------------------------------

def _strict_entry(cache_dir, key, *, output=None, reason=None):
    directory = strict_cache_dir(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    document = {'parser': 'strict-v1', 'output': output, 'reason': reason}
    strict_entry_path(cache_dir, key).write_text(json.dumps(document), encoding='utf-8')
    return document


def test_cache_observation_reports_the_exact_keys_the_provider_persisted(tmp_path, monkeypatch):
    """The manifest keys come from the real provider persistence path.

    ``tests/unit/distiller_cases.transport`` answers the real synchronous httpx
    boundary, so the strict cache entry is written by
    ``LLMClient.chat_json_receipt`` itself and the observer reports exactly that
    key instead of a predicted one.
    """
    from tests.unit.distiller_cases import transport

    seen = {}
    with cache_observation(lambda key, document: seen.__setitem__(key, document)):
        _agent, client, calls = transport(monkeypatch, content=json.dumps({'ok': True}),
                                          cache_dir=str(tmp_path))
        client.chat_json_receipt('system prompt', 'user payload')
    assert len(calls) == 1
    assert len(seen) == 1
    key, document = next(iter(seen.items()))
    assert len(key) == 64 and document['reason'] is None
    assert document['output'] == {'ok': True}
    # The key is the frozen (model, system, user) identity, not a run/request id.
    from rag_mcp.agents.consolidation_replay import cache_key

    assert key == cache_key(client.model, 'system prompt', 'user payload')


def test_sealed_manifest_and_response_audit_cover_success_and_failure(tmp_path):
    entries = {'k1': _strict_entry(tmp_path, 'k1', output={'proposals': [{'proposal_id': 'p'}]}),
               'k2': _strict_entry(tmp_path, 'k2', reason='MODEL_JSON_INVALID')}
    manifest = build_manifest(tmp_path, sorted(entries), model_version='m1', dataset_hash='d' * 64,
                              snapshot_hash='s' * 64, data_hash='a' * 64)
    assert manifest['manifest_version'] == CACHE_MANIFEST_VERSION == MANIFEST_API_VERSION
    assert manifest['expected_keys'] == 2 and manifest['recorded_success'] == 1
    assert manifest['recorded_failure'] == 1
    assert all(row['read_status'] == 'ok' for row in manifest['entries'])
    # Every recorded entry is byte-pinned; a failure entry has no response body.
    assert all(row['entry_sha256'] for row in manifest['entries'])
    body_hashes = {row['key']: row['body_sha256'] for row in manifest['entries']}
    assert body_hashes['k1'] and body_hashes['k2']
    assert body_hashes['k1'] != body_hashes['k2']
    audit = response_audit(entries, entries, sorted(entries), manifest)
    assert audit['response_match_rate'] == 1.0 and audit['mismatched'] == []
    # A changed success body is a real mismatch; a replayed failure must keep its
    # exact recorded reason instead of being regenerated.
    replayed = {'k1': {'parser': 'strict-v1', 'output': {'proposals': [{'proposal_id': 'q'}]},
                       'reason': None},
                'k2': {'parser': 'strict-v1', 'output': None, 'reason': 'MODEL_SCHEMA_INVALID'}}
    audit = response_audit(entries, replayed, sorted(entries), manifest)
    assert audit['matched'] == 0 and audit['mismatched'] == ['k1', 'k2']
    assert audit['response_match_rate'] == 0.0
    counts = _audit_with_entries(tmp_path, ['k1', 'k2', 'absent'], {})
    assert counts['missing'] == 1 and counts['matched'] == 2
    assert counts['recorded_success'] == 1 and counts['recorded_failure'] == 1
    assert counts['evidence_complete'] is False


def test_non_latency_drift_reports_the_worst_relative_change():
    dataset = dataset_document()
    engine = SimpleNamespace(arms={})
    for arm in GATE_VARIANTS:
        record, replay = ArmRound(round='record', arm=arm), ArmRound(round='replay', arm=arm)
        for query in dataset['queries']:
            identifier = query['query_id']
            record.rankings[identifier] = [query['expected_source_event_ids'][0]]
            replay.rankings[identifier] = [query['expected_source_event_ids'][0]]
        engine.arms[('record', arm)] = record
        engine.arms[('replay', arm)] = replay
    assert _non_latency_drift(engine, {}, {}, []) == pytest.approx(0.0)
    for query in dataset['queries']:
        engine.arms[('replay', 'consolidated_direct')].rankings[query['query_id']] = []
    drift = _non_latency_drift(engine, {}, {}, [])
    assert drift == pytest.approx(1.0), 'a full loss of ranked units must exceed the 1% tolerance'


# ---------------------------------------------------------------------------
# T097: preflight, uniqueness and exit codes
# ---------------------------------------------------------------------------

def test_preflight_accepts_matching_inputs_and_freezes_the_faces(tmp_path):
    preflight = check_preflight(base_args(tmp_path))
    assert preflight['faces']['dataset']['snapshot_hash'] == 'b' * 64
    assert preflight['faces']['dataset']['queries'] == 6
    assert preflight['faces']['snapshot']['authority_digest'] == 'b' * 64


@pytest.mark.parametrize('mutation,message', [
    ('digest', 'digest does not match'),
    ('cutoff', 'cutoff does not match'),
    ('scope', 'scope does not match'),
    ('policy', 'published target policy'),
])
def test_preflight_refuses_a_snapshot_from_another_authority(tmp_path, mutation, message):
    args = base_args(tmp_path)
    snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
    if mutation == 'digest':
        snapshot['authority']['authority_digest'] = 'c' * 64
    elif mutation == 'cutoff':
        snapshot['authority']['authority_cutoff'] = 1
    elif mutation == 'scope':
        snapshot['scope_id'] = '1'
    else:
        snapshot.pop('policy')
    args.snapshot.write_text(json.dumps(snapshot), encoding='utf-8')
    with pytest.raises(PreflightIncomplete, match=message):
        check_preflight(args)


def test_preflight_refuses_existing_output_manifest_and_replay_without_manifest(tmp_path):
    args = base_args(tmp_path)
    args.output.write_text('{"else": 1}', encoding='utf-8')
    with pytest.raises(PreflightIncomplete, match='output already exists'):
        check_preflight(args)
    args.output.unlink()
    args.cache_manifest.write_text(json.dumps({'manifest_version': MANIFEST_API_VERSION}),
                                   encoding='utf-8')
    with pytest.raises(PreflightIncomplete, match='manifest already exists'):
        check_preflight(args)
    Path(tmp_path / 'other').mkdir(parents=True, exist_ok=True)
    replay = base_args(tmp_path / 'other', mode='replay')
    with pytest.raises(PreflightIncomplete, match='requires an existing cache manifest'):
        check_preflight(replay)

def test_preflight_replay_refuses_incomplete_or_wrong_version_cache(tmp_path):
    args = base_args(tmp_path, mode='replay')
    _strict_entry(args.cache_manifest.parent / f'{args.cache_manifest.name}.cache', 'k1',
                  output={'ok': True})
    args.cache_manifest.write_text(json.dumps({
        'manifest_version': MANIFEST_API_VERSION, 'parser_version': 'strict-v1',
        'cache_dir': str(args.cache_manifest.parent / f'{args.cache_manifest.name}.cache'),
        'model_version': 'm', 'dataset_hash': 'd' * 64, 'snapshot_hash': 's' * 64, 'data_hash': 'a' * 64,
        'expected_keys': 2, 'recorded_success': 2, 'recorded_failure': 0,
        'entries': [{'key': 'k1', 'read_status': 'ok', 'status': 'success', 'parser_version': 'strict-v1',
                     'entry_sha256': None, 'body_sha256': None},
                    {'key': 'k2', 'read_status': 'ok', 'status': 'success', 'parser_version': 'strict-v1',
                     'entry_sha256': None, 'body_sha256': None}]}), encoding='utf-8')
    with pytest.raises(PreflightIncomplete, match='cache evidence incomplete'):
        check_preflight(args)
    args.cache_manifest.write_text(json.dumps({'manifest_version': '013.cache.0'}), encoding='utf-8')
    with pytest.raises(PreflightIncomplete, match='version mismatch'):
        check_preflight(args)


def test_cli_exit_codes_are_incomplete_for_preflight_and_refuse_reuse(tmp_path, capsys):
    args = base_args(tmp_path)
    argv = ['--dataset', str(args.dataset), '--snapshot', str(args.snapshot), '--mode', 'replay',
            '--cache-manifest', str(args.cache_manifest), '--gate-variant', args.gate_variant,
            '--output', str(args.output), '--run', str(tmp_path / 'absent.json')]
    assert main(argv) == EXIT_INCOMPLETE
    assert json.loads(capsys.readouterr().out)['status'] == 'incomplete'
    assert json.loads(args.output.read_text(encoding='utf-8'))['status'] == 'incomplete'


# ---------------------------------------------------------------------------
# T098: the runner's report shape through the shared validator
# ---------------------------------------------------------------------------

def _engine(tmp_path, *, record_errors=None, rankings=None):
    args = base_args(tmp_path)
    dataset = dataset_document()
    preflight = {'dataset': dataset, 'snapshot': snapshot_document(),
                 'faces': {'dataset': {'path': str(args.dataset), 'sha256': 'e' * 64},
                           'snapshot': {'path': str(args.snapshot), 'sha256': 'f' * 64}},
                 'cache_dir': tmp_path / 'cache'}
    run = SimpleNamespace(run_id='t097test')
    bundle = {'run': run, 'run_path': str(tmp_path / 'run.json'), 'identities': {'identities': []},
              'proof': {'identities': 6}}
    engine = ComparisonEngine(args, preflight, bundle, tmp_path)
    engine.units = {query['query_id']: [{'alias': query['relevance_units'][0]['alias'],
                                         'equivalence_group': 'eq', 'validity': 'current',
                                         'memory_id': query['expected_source_event_ids'][0]}]
                    for query in dataset['queries']}
    engine.unit_witness = {query['query_id']: {
        query['relevance_units'][0]['alias']: {
            'expected_content': query['relevance_units'][0]['expected_content'],
            'stored_witness': {query['expected_source_event_ids'][0]: 'stored body'}}}
        for query in dataset['queries']}
    engine.frozen_binding = {field: ('1' * 64) for field in
                             ('data_hash', 'policy_hash', 'vocabulary_hash', 'prompt_hash',
                              'schema_hash', 'implementation_hash', 'recall_config_hash')}
    engine.frozen_binding.update({'scope_id': SCOPE, 'model_version': 'm1'})
    for arm in GATE_VARIANTS:
        record = ArmRound(round='record', arm=arm, duration_ms=10.0,
                          store_fingerprint={'manifest_digest': '9' * 64})
        if record_errors and arm in record_errors:
            record.error = 'RuntimeError: boom'
        for index, query in enumerate(dataset['queries']):
            alias = query['expected_source_event_ids'][0]
            ranked = rankings.get(arm, [alias] * 5) if rankings else [alias] * 5
            record.rankings[query['query_id']] = list(ranked)
        engine.arms[('record', arm)] = record
    engine.hard = {'cross_scope_leaks': 0, 'quarantined_inputs': 0, 'soft_overturns_hard': 0,
                   'automatic_promotions': 0, 'invalid_outputs_applied': 0,
                   'stale_holder_commits': 0, 'incomplete_outputs_consumed': 0,
                   'rebuild_llm_calls': 0, 'source_chain_complete_rate': 1.0,
                   'schema_validity_rate': 1.0, 'projection_integrity_rate': 1.0}
    return engine


def _manifest(tmp_path, keys=()):
    return {'manifest_version': MANIFEST_API_VERSION, 'cache_dir': str(tmp_path / 'cache'),
            'expected_keys': len(keys), 'recorded_success': len(keys), 'recorded_failure': 0,
            'entries': [{'key': key, 'status': 'success', 'entry_sha256': '1' * 64,
                         'body_sha256': '2' * 64} for key in keys]}


def test_record_report_is_schema_valid_and_never_claims_eligibility(tmp_path):
    """Identical arms must fail the quality gate rather than claim a gain."""
    engine = _engine(tmp_path)
    report = engine.build_report(manifest=_manifest(tmp_path), recorded={'transport_calls': 3},
                                 replayed={'transport_calls': 0, 'evidence_complete': True},
                                 elapsed_ms=1.0)
    assert report['status'] == 'failed', 'a zero observed gain is never an incomplete excuse'
    assert report['default_enable_eligible'] is False
    assert report['default_configuration']['consolidation_enabled'] is False
    assert report['default_configuration']['link_expansion_enabled'] is False
    assert report['default_configuration']['policy_published'] is False
    assert report['gate_binding'] is None
    assert report['hard_metrics'] is None, 'this two-round comparison observed no consolidation counters'
    assert report['gates']['safety']['checks']['all_required_observed'] is False
    validate_comparison_report(report)
    assert [row['query_id'] for row in report['queries']] == [
        query['query_id'] for query in dataset_document()['queries']]
    assert all(row['result_trace']['trace_version'] == TRACE_VERSION for row in report['queries'])
    assert engine.notes['reasons'] and any(
        reason in engine.notes['reasons'] for reason in
        ('BASELINE_ZERO_NOT_COMPUTABLE', 'RELATIVE_GAIN_BELOW_THRESHOLD'))


def test_report_marks_an_arm_failure_as_failed_and_keeps_the_failed_path(tmp_path):
    engine = _engine(tmp_path, record_errors={'consolidated_direct'})
    report = engine.build_report(manifest=_manifest(tmp_path), recorded={}, replayed={}, elapsed_ms=1.0)
    assert report['status'] == 'failed'
    assert report['default_enable_eligible'] is False
    assert any(path.startswith('consolidated_direct:') for path in report['failed_paths'])
    validate_comparison_report(report)


def test_report_gates_cannot_pass_when_e2e_and_old_suite_evidence_is_absent(tmp_path):
    """The T098 entry point refuses passed reports without the real evidence.

    The positive fixture is the shared 013.2 report fixture (a synthetic
    label-level control, explicitly not real acceptance evidence); the eval rule
    must still refuse it until the real 013 E2E index and the old-suite reports
    are supplied.
    """
    from consolidation_eval_support import DatasetInvalid

    from tests.unit.consolidation_gate import binding, build_report

    bound = binding(SCOPE)
    report = build_report(bound)
    from rag_mcp.services.consolidation_gate import validate_report

    validate_report(report)
    with pytest.raises(DatasetInvalid, match='E2E evidence'):
        validate_comparison_report(report)
    with pytest.raises(DatasetInvalid, match='old-suite evidence'):
        validate_comparison_report(report, e2e_evidence=_e2e_evidence())
    decision = validate_comparison_report(report, e2e_evidence=_e2e_evidence(),
                                          old_suite_evidence=['012 acceptance report'])
    assert decision['status'] == 'passed' and decision['default_enable_eligible'] is True
    # A binding that no longer matches the current trusted binding is refused even
    # with complete evidence.
    with pytest.raises(DatasetInvalid, match='current trusted binding'):
        validate_comparison_report(report, expected_binding=binding('1'),
                                   e2e_evidence=_e2e_evidence(),
                                   old_suite_evidence=['012 acceptance report'])
    # The runner's own report builder never produces a passed report from a
    # single record round: it has no replay comparison to reproduce.
    engine = _engine(tmp_path)
    own = engine.build_report(manifest=_manifest(tmp_path), recorded={}, replayed={}, elapsed_ms=1.0)
    assert own['gates']['regression']['checks']['e2e_evidence_present'] is False
    assert own['status'] == 'failed' and own['default_enable_eligible'] is False


def _e2e_evidence(hard_counts=None, exitstatus=0):
    scenarios = ('batch_distillation', 'deterministic_merge', 'deterministic_correction',
                 'soft_overturn_refusal', 'model_schema_fault', 'benefit_gate_control',
                 'manual_candidate_promotion')
    counts = {name: 0 for name in ('cross_scope_leaks', 'soft_overturns_hard', 'automatic_promotions',
                                   'invalid_outputs_applied', 'stale_holder_commits',
                                   'incomplete_outputs_consumed', 'rebuild_llm_calls')}
    counts.update({'source_chain_complete_rate': 1.0, 'projection_integrity_rate': 1.0})
    counts.update(hard_counts or {})
    return {'exitstatus': exitstatus,
            'tests': [{'nodeid': 'tests/integration/test_013_consolidation_e2e.py::t',
                       'records': [{'scenario': name} for name in scenarios]}],
            'hard_counts': counts}


# ---------------------------------------------------------------------------
# T102: observed safety counters and round-scoped window identifiers
# ---------------------------------------------------------------------------

def test_safety_counters_are_observed_from_real_window_inputs_and_outcomes():
    """The two previously unobserved counters come from real observations only."""
    active = safety_entry({'runs': [{'status': 'rejected', 'reason_codes': ['PROVIDER_TIMEOUT']}],
                           'windows': 1},
                          input_statuses={'11': {'status': 'active'}},
                          scope_statuses={'11': {'status': 'active'},
                                          '12': {'status': 'active'}})
    assert active['window_inputs'] == 1 and active['window_quarantined_ids'] == []
    assert active['scope_inputs'] == 2 and active['scope_quarantined_ids'] == []
    assert active['schema_attempts'] == 1 and active['schema_invalid'] == 0
    quarantined = safety_entry({'runs': [{'status': 'rejected', 'reason_codes': []}], 'windows': 1},
                               input_statuses={'11': {'status': 'active'}},
                               scope_statuses={'11': {'status': 'active'},
                                               '12': {'status': 'quarantined'}})
    assert quarantined['scope_quarantined_ids'] == ['12']
    merged = merge_safety([active, quarantined])
    assert merged['windows'] == 2 and merged['window_inputs'] == 2 and merged['scope_inputs'] == 4
    counters, rate, observations = finalize_safety(merged)
    # A quarantined memory the window correctly excluded is evidence of correct
    # filtering, not an admitted input: the contract requires the window to
    # exclude non-active sources, so only an admitted one may fail the gate.  The
    # exclusion is still audited, never hidden.
    assert counters == 0
    assert observations['excluded_nonactive_ids'] == ['12']
    assert rate == 1.0
    assert observations['source'].startswith('013 comparison runner')
    # A non-active memory that really reached a sealed window is a violation.
    admitted = safety_entry({'runs': [{'status': 'rejected', 'reason_codes': []}], 'windows': 1},
                            input_statuses={'11': {'status': 'quarantined'}},
                            scope_statuses={'11': {'status': 'quarantined'}})
    counters, _, admitted_observations = finalize_safety(merge_safety([admitted]))
    assert counters == 1, 'an admitted quarantined input must never be reported as zero'
    assert admitted_observations['quarantined_input_ids'] == ['11']


def test_safety_counters_stay_unobserved_without_a_real_observation():
    """No window and no model package means null, never a fabricated zero."""
    counters, rate, observations = finalize_safety(merge_safety([]))
    assert counters is UNOBSERVED and rate is UNOBSERVED
    assert observations['windows'] == 0 and observations['schema_attempts'] == 0
    # A model package refused by schema validation is a real observation of a
    # failing schema-validity rate, not an unobserved counter.  The agent's own
    # verdict is as binding as the pipeline's reason code.
    invalid = safety_entry({'runs': [{'status': 'rejected', 'reason_codes': ['MODEL_SCHEMA_INVALID']}],
                            'windows': 1},
                           input_statuses={'11': {'status': 'active'}},
                           scope_statuses={'11': {'status': 'active'}})
    counters, rate, _ = finalize_safety(merge_safety([invalid]))
    assert counters == 0 and rate == 0.0
    agent_only = safety_entry({'runs': [{'status': 'rejected', 'reason_codes': []}], 'windows': 1},
                              input_statuses={'11': {'status': 'active'}},
                              scope_statuses={'11': {'status': 'active'}},
                              agent_attempts=2, agent_invalid=1)
    assert agent_only['schema_attempts'] == 2 and agent_only['schema_invalid'] == 1
    _, rate, _ = finalize_safety(merge_safety([agent_only]))
    assert rate == 0.5


def test_window_identifier_stride_keeps_the_two_rounds_disjoint(tmp_path):
    """Record and replay seal the same payload but never share generated ids."""
    engine = _engine(tmp_path)
    engine.frozen_seed = 12345
    ids = {}
    for name in ('record', 'replay'):
        with engine.frozen_window_clock(SimpleNamespace(_clock=None), round_name=name):
            from rag_mcp.services import consolidation_runtime as runtime_module

            ids[name] = [runtime_module.generate_id() for _ in range(3)]
    assert ids['record'] == [12345, 12346, 12347]
    assert ids['replay'] == [12345 + WINDOW_ID_STRIDE, 12346 + WINDOW_ID_STRIDE, 12347 + WINDOW_ID_STRIDE]
    assert not set(ids['record']) & set(ids['replay'])
    # Re-running the record round reproduces the identical sequence: the seal is
    # pinned, so the frozen cache key of the first round is reproducible.
    with engine.frozen_window_clock(SimpleNamespace(_clock=None), round_name='record'):
        from rag_mcp.services import consolidation_runtime as runtime_module

        assert [runtime_module.generate_id() for _ in range(3)] == ids['record']


def test_reproducibility_status_is_the_observed_comparison_not_the_round_label(tmp_path):
    """One invocation runs both rounds; the verdict must follow the measurement."""
    engine = _engine(tmp_path)
    replayed = {'transport_calls': 0, 'evidence_complete': True, 'recorded_success': 2,
                'recorded_failure': 0, 'missing': 0, 'corrupt': 0, 'version_mismatch': 0,
                'response_match_rate': 1.0, 'max_non_latency_relative_drift': 0.0}
    report = engine.build_report(manifest=_manifest(tmp_path), recorded={}, replayed=replayed,
                                 elapsed_ms=1.0)
    assert engine.args.mode == 'record'
    assert report['reproducibility']['status'] == 'passed'
    assert report['reproducibility']['max_non_latency_relative_drift'] == 0.0
    assert report['gates']['regression']['checks']['replay_zero_network'] is True
    # An unmeasured drift is never a pass, and a drift over tolerance fails.
    for drift, expected in ((None, 'incomplete'), (0.5, 'failed')):
        report = engine.build_report(manifest=_manifest(tmp_path), recorded={},
                                     replayed=dict(replayed,
                                                   max_non_latency_relative_drift=drift),
                                     elapsed_ms=1.0)
        assert report['reproducibility']['status'] == expected


def test_arm_transport_is_the_arms_own_delta_not_a_running_total(tmp_path):
    """A process-wide cumulative counter must not be reported as one arm's usage."""
    engine = _engine(tmp_path)
    before = {'transport_calls': 6, 'prompt_chars': 84446, 'completion_chars': 16713, 'cache_hits': 2,
              'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0.0}
    engine._distiller = SimpleNamespace(usage=lambda: dict(before))
    assert engine.transport_delta(before) == {
        'transport_calls': 0, 'prompt_chars': 0, 'completion_chars': 0, 'cache_hits': 0,
        'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0.0}
    after = dict(before, transport_calls=8, cache_hits=3)
    engine._distiller = SimpleNamespace(usage=lambda: dict(after))
    delta = engine.transport_delta(before)
    assert delta['transport_calls'] == 2 and delta['cache_hits'] == 1
    # Reading the counter must never create the distiller for a baseline arm.
    fresh = _engine(tmp_path)
    fresh._distiller = None
    assert fresh.transport_snapshot()['transport_calls'] == 0 and fresh._distiller is None


def test_warm_up_really_awaits_the_embedding_provider(tmp_path):
    """The documented warm-up must actually run, not create an un-awaited coroutine.

    ``embed_query`` is async; calling it without awaiting produced a 0 ms warm-up
    and left the first recorded query to pay the model load, which is exactly the
    latency-limited query the warm-up exists to prevent.
    """
    import asyncio

    engine = _engine(tmp_path)
    calls = []

    class _Provider:
        async def embed_query(self, text):
            await asyncio.sleep(0)
            calls.append(text)
            return [0.0]

    engine._embedding = _Provider()
    elapsed = asyncio.run(engine.warm_up())
    assert calls == ['013 comparison warm-up']
    assert elapsed >= 0.0


def test_one_real_transport_attempt_is_credited_once_across_its_two_receipts():
    """``chat_json_receipt`` emits a started and a settled receipt per attempt.

    Both carry the same ``call_id``, so accounting must credit the attempt once
    with its settled numbers.  Accumulating both counted every real model call
    twice: the sealed T102 evidence reported 4 calls and 84 446 prompt chars for
    2 real calls of a 20 KB payload.
    """
    from rag_mcp.agents.llm_client import LLMCallReceipt

    from run_consolidation_comparison import ObservedDistiller

    observed = ObservedDistiller(SimpleNamespace(model_and_version='m1'))
    observed._account(LLMCallReceipt(transport_calls=1, prompt_chars=20292, call_id=1))
    observed._account(LLMCallReceipt(transport_calls=1, prompt_chars=20292, completion_chars=7800,
                                     input_tokens=6852, output_tokens=4961, cost_usd=0.0, call_id=1))
    usage = observed.usage()
    assert usage['transport_calls'] == 1 and usage['prompt_chars'] == 20292
    assert usage['completion_chars'] == 7800
    assert usage['input_tokens'] == 6852 and usage['output_tokens'] == 4961
    # A second attempt is a second call, and its unknown usage stays null.
    observed._account(LLMCallReceipt(transport_calls=1, prompt_chars=20291, call_id=2))
    usage = observed.usage()
    assert usage['transport_calls'] == 2 and usage['prompt_chars'] == 20292 + 20291
    assert usage['input_tokens'] is None and usage['output_tokens'] is None
    assert usage['cost_usd'] is None
    # A cache-hit receipt is not a transport attempt and is counted separately.
    observed._account(LLMCallReceipt(reason='PROVIDER_TIMEOUT', cache_hits=1))
    assert observed.usage()['transport_calls'] == 2
    assert observed.usage()['cache_hits'] == 1


def test_safety_gate_emits_the_aggregate_check_the_shared_validator_requires():
    """``hard_metrics_zero`` is required by ``consolidation_gate.GATE_CHECKS``.

    Without it the shared production validator rejects any report whose gates
    passed with "report gate checks incomplete", so ``status=passed`` was
    unreachable no matter how clean the run was.
    """
    from rag_mcp.services.consolidation_gate import GATE_CHECKS

    complete = {name: 0 for name in ('cross_scope_leaks', 'quarantined_inputs', 'soft_overturns_hard',
                                     'automatic_promotions', 'invalid_outputs_applied',
                                     'stale_holder_commits', 'incomplete_outputs_consumed',
                                     'rebuild_llm_calls')}
    complete.update({'source_chain_complete_rate': 1.0, 'schema_validity_rate': 1.0,
                     'projection_integrity_rate': 1.0})
    checks, reasons = safety_checks(complete)
    assert checks['hard_metrics_zero'] is True and reasons == []
    assert 'hard_metrics_zero' in GATE_CHECKS['safety']
    # A nonzero zero-tolerance counter and an unobserved counter both fail it.
    assert safety_checks({**complete, 'cross_scope_leaks': 1})[0]['hard_metrics_zero'] is False
    assert safety_checks({**complete, 'quarantined_inputs': None})[0]['hard_metrics_zero'] is False
    # An incomplete integrity rate is not a "zero counter" violation.
    broken = safety_checks({**complete, 'schema_validity_rate': 0.25})[0]
    assert broken['hard_metrics_zero'] is True and broken['schema_validity_rate'] is False


def test_green_runner_report_is_accepted_as_passed_by_the_shared_validator(tmp_path):
    """A green run must be able to emit a report the production validator accepts.

    Regression for two structural defects that made ``status=passed``
    unreachable: ``environment.model_version`` carried the frozen *retrieval*
    model instead of the model under test pinned by the gate binding (the shared
    validator answered "report environment diverges from gate binding"), and the
    safety gate never emitted the ``hard_metrics_zero`` check (answered "report
    gate checks incomplete").  Either one made the runner's own
    ``validate_comparison_report`` flip a successful run to ``failed``.
    """
    from rag_mcp.services.consolidation_gate import validate_report

    from consolidation_eval_support import validate_comparison_report as entry_point

    engine = _engine(tmp_path)
    engine.args.trace = tmp_path / 'trace.json'
    engine.args.memory_acceptance = tmp_path / '012-acceptance.json'
    engine.args.regression = [tmp_path / '012_regression_summary.json']
    # A real, non-zero baseline with a >3 % consolidation gain on both metrics.
    # The frozen physical-rank trace carries the resolved memory ids, not labels.
    for query in dataset_document()['queries']:
        identifier = query['query_id']
        memory_id = query['expected_source_event_ids'][0]
        engine.arms[('record', 'baseline')].rankings[identifier] = [None, None, None, None, memory_id]
        for arm in ('consolidated_direct', 'consolidated_candidate_expansion'):
            engine.arms[('record', arm)].rankings[identifier] = [memory_id] * 5
    # A real observed consolidation window: one model package, schema-valid.
    observed = engine.arms[('record', 'consolidated_direct')]
    observed.consolidation = {'windows': 1, 'runs': [{'status': 'completed', 'reason_codes': [],
                                                      'outputs': 1}],
                              'window_inputs': {'1000': {'status': 'active'}}}
    observed.safety = {'windows': 1, 'schema_attempts': 1, 'schema_invalid': 0, 'schema_reasons': [],
                       'window_inputs': 1, 'window_quarantined_inputs': [],
                       'scope_inputs': 1, 'scope_quarantined_ids': []}
    replayed = {'transport_calls': 0, 'evidence_complete': True, 'recorded_success': 1,
                'recorded_failure': 0, 'missing': 0, 'corrupt': 0, 'version_mismatch': 0,
                'response_match_rate': 1.0, 'max_non_latency_relative_drift': 0.0}
    report = engine.build_report(manifest=_manifest(tmp_path, ['k1']),
                                 recorded={'transport_calls': 1, 'evidence_complete': True},
                                 replayed=replayed, elapsed_ms=6.0)
    assert report['status'] == 'passed' and report['default_enable_eligible'] is True
    assert report['environment']['model_version'] == engine.frozen_binding['model_version']
    assert report['gates']['safety']['checks']['hard_metrics_zero'] is True
    assert GATE_CHECKS['safety'] <= set(report['gates']['safety']['checks'])
    validate_report(report)
    decision = entry_point(report, expected_binding=engine.frozen_binding,
                           e2e_evidence=_e2e_evidence(), old_suite_evidence=['012 report'])
    assert decision['status'] == 'passed' and decision['binding'] == engine.frozen_binding

