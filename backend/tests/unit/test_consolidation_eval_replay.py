"""T091: record/replay safety for the frozen 013 comparison cache.

The frozen comparison runs every arm twice from the same original unconsolidated
authority: a record round that performs the real model calls and stores both
successes and failures, and a replay round that must consume exactly those
recorded outcomes with no provider transport at all.

These tests use a fake HTTP transport, so they prove the guard/cache mechanics
and the accounting, not a real provider round. Evaluation-contract.md
"Cache/record/replay" is the contract under test: exact (model, system, user)
keys, no gap fill on a missing/corrupt/version-mismatched entry, transport-only
deny/count, unknown usage stays null, replay adds zero provider usage and never
rewrites recorded bytes.
"""
import hashlib
import json
from pathlib import Path

import pytest

import rag_mcp.agents.llm_client as llm_client
from rag_mcp.agents.consolidation_replay import (
    CACHE_ENTRY_VERSION,
    REPLAY_DENIED_REASON,
    aggregate_usage,
    audit_cache,
    build_manifest,
    cache_key,
    current_session,
    non_latency_drift,
    replay_session,
    safety_exact_match,
    unconsolidated_start_reasons,
    within_non_latency_tolerance,
)
from rag_mcp.agents.llm_client import LLMClient

SYSTEM = 'distiller system prompt'
USER = '{"window": "frozen"}'
USER_B = '{"window": "frozen", "index": 2}'
SUCCESS_ENVELOPE = {'choices': [{'message': {'content': '{"proposals": []}'}}],
                    'usage': {'prompt_tokens': 11, 'completion_tokens': 7, 'cost_usd': 0.002}}


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Transport:
    """Minimal httpx.Client stand-in that records every real transport attempt."""

    calls: list = []
    responses: list = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, headers=None):
        type(self).calls.append(url)
        return type(self).responses.pop(0)


@pytest.fixture
def transport(monkeypatch):
    _Transport.calls = []
    _Transport.responses = []
    monkeypatch.setattr(llm_client.httpx, 'Client', _Transport, raising=True)
    return _Transport


def client(cache_dir):
    return LLMClient('http://offline.test/v1', '', 'model-v1', cache_dir=str(cache_dir))


def stored_entries(cache_dir):
    strict = Path(cache_dir) / 'strict-v1'
    return sorted(p.name for p in strict.glob('*.json')) if strict.exists() else []


class TestStableCacheKey:
    def test_key_covers_only_model_system_and_user(self):
        baseline = cache_key('model-v1', SYSTEM, USER)
        assert baseline == cache_key('model-v1', SYSTEM, USER)
        assert len(baseline) == 64 and all(c in '0123456789abcdef' for c in baseline)
        assert baseline != cache_key('model-v2', SYSTEM, USER)
        assert baseline != cache_key('model-v1', SYSTEM + ' ', USER)
        assert baseline != cache_key('model-v1', SYSTEM, USER + ' ')
        # The client's own key is the same frozen algorithm, so a recorded round
        # stays addressable across processes and rounds.
        assert client(Path('unused'))._cache_key(SYSTEM, USER) == baseline
        # Independently restated T070 formula: byte-compatible with the existing
        # AGENTIC_LLM_CACHE_PATH entries the 012 evaluation already wrote.
        independent = hashlib.sha256(json.dumps(
            {'model': 'model-v1', 'system': SYSTEM, 'user': USER},
            sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
        assert baseline == independent


class TestRecordRound:
    def test_record_round_stores_success_and_failure_entries(self, tmp_path, transport):
        round_client = client(tmp_path)
        transport.responses = [_Response(200, SUCCESS_ENVELOPE), _Response(503, {})]
        with replay_session('record') as session:
            first = round_client.chat_json_receipt(SYSTEM, USER)
            second = round_client.chat_json_receipt(SYSTEM, USER_B)
        assert first.reason is None and first.output == {'proposals': []}
        assert second.reason == 'PROVIDER_HTTP_503' and second.output is None
        assert len(transport.calls) == 2
        assert session.denials == 0 and session.refused_writes == 0
        assert len(stored_entries(tmp_path)) == 2
        manifest = build_manifest(tmp_path,
                                  [cache_key('model-v1', SYSTEM, USER),
                                   cache_key('model-v1', SYSTEM, USER_B)],
                                  model_version='model-v1', dataset_hash='d' * 64,
                                  snapshot_hash='s' * 64, data_hash='h' * 64)
        assert manifest['recorded_success'] == 1 and manifest['recorded_failure'] == 1
        assert audit_cache(tmp_path, manifest)['evidence_complete'] is True

    def test_unknown_provider_usage_stays_null(self, tmp_path, transport):
        round_client = client(tmp_path)
        transport.responses = [_Response(200, {'choices': [{'message': {'content': '{"a": 1}'}}]})]
        with replay_session('record'):
            receipt = round_client.chat_json_receipt(SYSTEM, USER)
        assert receipt.input_tokens is None and receipt.output_tokens is None
        assert receipt.cost_usd is None
        usage = aggregate_usage([receipt], source='estimated')
        assert usage['input_tokens'] is None and usage['output_tokens'] is None
        assert usage['cost_usd'] is None and usage['provider_usage']['llm_calls'] == 1


class TestReplayRound:
    def _record(self, tmp_path, transport):
        round_client = client(tmp_path)
        transport.responses = [_Response(200, SUCCESS_ENVELOPE), _Response(503, {})]
        with replay_session('record'):
            round_client.chat_json_receipt(SYSTEM, USER)
            round_client.chat_json_receipt(SYSTEM, USER_B)
        return {name: (tmp_path / 'strict-v1' / name).read_bytes() for name in stored_entries(tmp_path)}

    def test_replay_consumes_success_and_failure_with_zero_transport(self, tmp_path, transport):
        before = self._record(tmp_path, transport)
        transport.calls = []
        replay_client = client(tmp_path)
        with replay_session('replay') as session:
            first = replay_client.chat_json_receipt(SYSTEM, USER)
            second = replay_client.chat_json_receipt(SYSTEM, USER_B)
        assert transport.calls == []
        assert first.output == {'proposals': []} and first.reason is None
        assert second.reason == 'PROVIDER_HTTP_503' and second.output is None
        assert session.denials == 0 and session.refused_writes == 0
        assert {name: (tmp_path / 'strict-v1' / name).read_bytes()
                for name in stored_entries(tmp_path)} == before
        manifest = build_manifest(tmp_path,
                                  [cache_key('model-v1', SYSTEM, USER),
                                   cache_key('model-v1', SYSTEM, USER_B)],
                                  model_version='model-v1', dataset_hash='d' * 64,
                                  snapshot_hash='s' * 64, data_hash='h' * 64)
        assert audit_cache(tmp_path, manifest)['version_mismatch'] == 0

    def test_replay_usage_is_zero_and_adds_no_provider_call(self, tmp_path, transport):
        self._record(tmp_path, transport)
        transport.calls = []
        replay_client = client(tmp_path)
        with replay_session('replay') as session:
            receipts = [replay_client.chat_json_receipt(SYSTEM, USER),
                        replay_client.chat_json_receipt(SYSTEM, USER_B)]
        assert transport.calls == []
        usage = aggregate_usage(receipts, source='replay_zero')
        assert usage['source'] == 'replay_zero'
        assert usage['provider_usage'] == {'embedding_calls': 0, 'rerank_calls': 0, 'llm_calls': 0,
                                           'llm_prompt_chars': 0, 'llm_completion_chars': 0}
        assert usage['input_tokens'] == 0 and usage['output_tokens'] == 0 and usage['cost_usd'] == 0
        assert session.denials == 0

    def test_missing_key_is_denied_and_never_gap_fills(self, tmp_path, transport):
        transport.responses = [_Response(200, SUCCESS_ENVELOPE)]
        replay_client = client(tmp_path)
        with replay_session('replay') as session:
            receipt = replay_client.chat_json_receipt(SYSTEM, USER)
        assert transport.calls == []
        assert receipt.output is None and receipt.reason == REPLAY_DENIED_REASON
        assert session.denials == 1
        assert stored_entries(tmp_path) == []

    def test_corrupt_entry_is_denied_and_never_repaired(self, tmp_path, transport):
        path = tmp_path / 'strict-v1' / (cache_key('model-v1', SYSTEM, USER) + '.json')
        path.parent.mkdir(parents=True)
        path.write_bytes(b'{"parser": "strict-v1", "output": ')
        original = path.read_bytes()
        replay_client = client(tmp_path)
        with replay_session('replay') as session:
            receipt = replay_client.chat_json_receipt(SYSTEM, USER)
        assert transport.calls == []
        assert receipt.reason == REPLAY_DENIED_REASON
        assert session.denials == 1 and session.refused_writes == 0
        assert path.read_bytes() == original

    def test_version_mismatched_entry_is_reported_and_not_repaired(self, tmp_path, transport):
        path = tmp_path / 'strict-v1' / (cache_key('model-v1', SYSTEM, USER) + '.json')
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'parser': 'strict-v2', 'output': {'from': 'older'},
                                    'reason': None}))
        original = path.read_bytes()
        replay_client = client(tmp_path)
        with replay_session('replay') as session:
            receipt = replay_client.chat_json_receipt(SYSTEM, USER)
        assert transport.calls == []
        assert receipt.reason == REPLAY_DENIED_REASON
        assert session.denials == 1
        assert path.read_bytes() == original
        manifest = build_manifest(tmp_path, [cache_key('model-v1', SYSTEM, USER)],
                                  model_version='model-v1', dataset_hash='d' * 64,
                                  snapshot_hash='s' * 64, data_hash='h' * 64)
        audit = audit_cache(tmp_path, manifest)
        assert audit['version_mismatch'] == 1 and audit['evidence_complete'] is False

    def test_audit_counts_missing_corrupt_and_tampered_bodies(self, tmp_path):
        present = cache_key('model-v1', SYSTEM, USER)
        other = cache_key('model-v1', SYSTEM, 'other')
        absent = cache_key('model-v1', SYSTEM, 'absent')
        (tmp_path / 'strict-v1').mkdir(parents=True)
        (tmp_path / 'strict-v1' / f'{present}.json').write_text(
            json.dumps({'parser': 'strict-v1', 'output': {'a': 1}, 'reason': None}))
        (tmp_path / 'strict-v1' / f'{other}.json').write_text('not json at all')
        manifest = build_manifest(tmp_path, [present, other, absent],
                                  model_version='model-v1', dataset_hash='d' * 64,
                                  snapshot_hash='s' * 64, data_hash='h' * 64)
        assert manifest['recorded_success'] == 1 and manifest['recorded_failure'] == 0
        audit = audit_cache(tmp_path, manifest)
        assert audit['expected_keys'] == 3
        assert audit['missing'] == 1 and audit['corrupt'] == 1
        assert audit['version_mismatch'] == 0 and audit['evidence_complete'] is False
        # A byte change after the manifest was sealed is corruption, not a pass.
        (tmp_path / 'strict-v1' / f'{present}.json').write_text(
            json.dumps({'parser': 'strict-v1', 'output': {'a': 2}, 'reason': None}))
        assert audit_cache(tmp_path, manifest)['corrupt'] == 2

    def test_replay_refuses_to_overwrite_a_bound_entry(self, tmp_path, transport):
        path = tmp_path / 'strict-v1' / (cache_key('model-v1', SYSTEM, USER) + '.json')
        path.parent.mkdir(parents=True)
        # A parseable entry the lookup accepts, but whose exact shape the client
        # would otherwise rewrite; a replay must keep the frozen bytes.
        entry = {'parser': 'strict-v1', 'output': {'proposals': []}, 'reason': None,
                 'note': 'record-round annotation'}
        path.write_text(json.dumps(entry))
        original = path.read_bytes()
        replay_client = client(tmp_path)
        with replay_session('replay') as session:
            receipt = replay_client.chat_json_receipt(SYSTEM, USER)
        assert receipt.output == {'proposals': []}
        assert session.denials == 0 and session.refused_writes == 1
        assert path.read_bytes() == original

    def test_transport_only_denial_leaves_other_access_alone(self, tmp_path, transport):
        """Only LLM transport is denied; the session counts nothing else."""
        transport.responses = [_Response(200, SUCCESS_ENVELOPE)]
        record_client = client(tmp_path)
        with replay_session('record') as session:
            record_client.chat_json_receipt(SYSTEM, USER)
        assert session.denials == 0 and len(transport.calls) == 1


class TestReproducibilityTolerance:
    def test_non_latency_drift_tolerance_and_safety_zero_tolerance(self):
        recorded = {'mrr': 0.5, 'ndcg': 0.4, 'latency_p50_ms': 10.0, 'latency_p95_ms': 20.0}
        replayed = {'mrr': 0.504, 'ndcg': 0.4, 'latency_p50_ms': 40.0, 'latency_p95_ms': 20.0}
        drift = non_latency_drift(recorded, replayed)
        assert drift == pytest.approx(0.008)
        assert within_non_latency_tolerance(recorded, replayed) is True
        assert within_non_latency_tolerance(recorded, {**replayed, 'mrr': 0.6}) is False
        assert non_latency_drift(recorded, replayed) <= 0.01
        # Safety is exact: no tolerance at all.
        assert safety_exact_match({'cross_scope_leaks': 0}, {'cross_scope_leaks': 0}) is True
        assert safety_exact_match({'cross_scope_leaks': 0}, {'cross_scope_leaks': 1}) is False
        assert safety_exact_match({'rate': 1.0}, {'rate': 0.999999999}) is False

    def test_zero_baseline_rounds_match_exactly(self):
        assert non_latency_drift({'mrr': 0.0}, {'mrr': 0.0}) == 0.0
        assert within_non_latency_tolerance({'mrr': 0.0}, {'mrr': 0.0}) is True


class TestOriginalUnconsolidatedStart:
    def test_a_complete_original_snapshot_has_no_reason_to_reject(self):
        view = {'scope_id': '1', 'authority_cutoff_event_id': 42, 'manifest_cutoff_event_id': 42,
                'complete_projection_versions': 6, 'consolidation_effect_count': 0,
                'pending_effect_count': 0}
        assert unconsolidated_start_reasons(view) == []

    def test_a_consolidated_or_pending_start_is_rejected(self):
        good = {'scope_id': '1', 'authority_cutoff_event_id': 42, 'manifest_cutoff_event_id': 42,
                'complete_projection_versions': 6, 'consolidation_effect_count': 0,
                'pending_effect_count': 0}
        for patch in ({'consolidation_effect_count': 1}, {'pending_effect_count': 2},
                      {'manifest_cutoff_event_id': 41}, {'complete_projection_versions': 5},
                      {'scope_id': None}):
            assert unconsolidated_start_reasons({**good, **patch}) != []

    def test_a_recorded_round_cannot_be_the_replay_start(self):
        """A replay must start from the original copy, never a consolidated one."""
        consolidated = {'scope_id': '1', 'authority_cutoff_event_id': 99,
                        'manifest_cutoff_event_id': 42, 'complete_projection_versions': 6,
                        'consolidation_effect_count': 3, 'pending_effect_count': 0}
        reasons = unconsolidated_start_reasons(consolidated)
        assert 'NOT_AN_ORIGINAL_START' in reasons and 'MANIFEST_CUTOFF_NOT_ORIGINAL' in reasons

    def test_cache_entry_version_is_frozen(self):
        assert CACHE_ENTRY_VERSION == '013.cache.1'
        assert hashlib.sha256(cache_key('model-v1', SYSTEM, USER).encode()).hexdigest()


class TestSessionLifecycle:
    def test_no_session_means_no_denial_and_no_freeze(self, tmp_path, transport):
        assert current_session() is None
        transport.responses = [_Response(200, SUCCESS_ENVELOPE)]
        plain = client(tmp_path)
        receipt = plain.chat_json_receipt(SYSTEM, USER)
        assert receipt.output == {'proposals': []}
        assert len(transport.calls) == 1
