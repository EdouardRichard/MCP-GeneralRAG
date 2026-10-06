"""Real synchronous httpx boundary tests, with no external store writes."""
import asyncio
import json
import threading

import httpx
import pytest

from rag_mcp.orchestration.consolidation_pipeline import propose
from rag_mcp.services.consolidation_runtime import DistillerProvider
from tests.unit.consolidation_cases import NOW, POLICY, proposal
from tests.unit.distiller_cases import data, fixture, transport


@pytest.mark.parametrize('options,reason,actual', [
    ({}, None, 1), ({'status': 429}, 'PROVIDER_HTTP_429', 1), ({'status': 500}, 'PROVIDER_HTTP_500', 1),
    ({'error': httpx.ConnectError('foreign-scope password=secret-value')}, 'PROVIDER_NETWORK_ERROR', 1),
    ({'error': httpx.ReadTimeout('foreign-scope password=secret-value')}, 'PROVIDER_TIMEOUT', 1),
    ({'content': ''}, 'MODEL_JSON_INVALID', 1), ({'envelope': {}}, 'PROVIDER_RESPONSE_INVALID', 1),
    ({'content': 'prefix {"proposals": []}'}, 'MODEL_JSON_INVALID', 1),
    ({'content': '{"proposals": []} {"proposals": []}'}, 'MODEL_JSON_INVALID', 1),
    ({'content': '{"broken": [{"proposals": []}'}, 'MODEL_JSON_INVALID', 1),
    ({'content': '{"proposals": [], "proposals": []}'}, 'MODEL_JSON_INVALID', 1),
    ({'envelope': {'choices': []}}, 'PROVIDER_RESPONSE_INVALID', 1),
    ({'envelope': {'choices': [{'message': {}}]}}, 'PROVIDER_RESPONSE_INVALID', 1),
    ({'raw_envelope': 'foreign-scope password=secret-value'}, 'PROVIDER_RESPONSE_INVALID', 1),
    ({'content': 'x' * 1000001}, 'MODEL_RESPONSE_TOO_LARGE', 1),
])
async def test_real_client_faults_have_per_call_receipts(monkeypatch, caplog, options, reason, actual):
    agent, client, calls = transport(monkeypatch, **options)
    # Shared compatibility counters must not be used to infer this call's transport.
    client.calls = 700
    current, ctx = fixture()
    batch = await propose(ctx.window, agent, current=current, context=ctx, policy=POLICY, now=NOW)
    assert batch.usage['llm_calls'] == actual and len(calls) == actual
    assert batch.usage['cache_hits'] == 0
    assert batch.usage['cost_usd'] is None
    if reason:
        assert batch.degraded and reason in batch.degradation_reasons and batch.proposals == ()
    else:
        assert not batch.degraded and len(batch.proposals) == 1
        assert batch.usage['input_tokens'] == 17 and batch.usage['output_tokens'] == 11
    assert batch.deterministic_proposals and batch.ttl_intents
    assert 'secret-value' not in caplog.text and 'foreign-scope' not in caplog.text


@pytest.mark.parametrize('status', [200, 429])
async def test_strict_cache_replays_success_and_failure_receipts(monkeypatch, tmp_path, status):
    agent, _, calls = transport(monkeypatch, status=status, cache_dir=str(tmp_path))
    current, ctx = fixture()
    first = await propose(ctx.window, agent, current=current, context=ctx, policy=POLICY, now=NOW)
    second = await propose(ctx.window, agent, current=current, context=ctx, policy=POLICY, now=NOW)
    assert len(calls) == 1
    assert first.usage['llm_calls'] == 1 and first.usage['cache_hits'] == 0
    assert second.usage['llm_calls'] == 0 and second.usage['cache_hits'] == 1
    assert second.usage['input_tokens'] is None and second.usage['cost_usd'] is None
    assert second.proposals == first.proposals and second.degradation_reasons == first.degradation_reasons


def test_corrupt_cache_reason_cannot_inject_log_or_diagnostic_body(monkeypatch, tmp_path, caplog):
    agent, _, calls = transport(monkeypatch, status=429, cache_dir=str(tmp_path))
    _, ctx = fixture()
    assert agent.run(data(ctx.window)).degraded
    path = next((tmp_path / 'strict-v1').glob('*.json'))
    path.write_text(json.dumps({'parser': 'strict-v1', 'output': None,
                               'reason': 'foreign-scope password=private-cache-value'}), encoding='utf-8')
    result = agent.run(data(ctx.window))
    assert len(calls) == 2 and 'PROVIDER_HTTP_429' in result.error
    assert 'private-cache-value' not in caplog.text and 'foreign-scope' not in caplog.text


async def spin_until(predicate):
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(.005)
    raise AssertionError('underlying call did not reach expected state')


async def test_blocked_sync_transport_keeps_slots_after_timeout_and_cancel(monkeypatch):
    original = httpx.Client
    gates = [threading.Event(), threading.Event()]
    entered, exited = [], []
    lock = threading.Lock()
    def handle(request):
        with lock:
            index = len(entered)
            entered.append(index)
            assert len(entered) - len(exited) <= 2
        try:
            if index < 2:
                assert gates[index].wait(10)
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'proposals': [proposal()]})}}]})
        finally:
            exited.append(index)
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    from rag_mcp.agents.llm_client import LLMClient
    from rag_mcp.agents.memory_distiller import MemoryDistiller
    agent = MemoryDistiller(LLMClient('http://offline.test', '', 'model-v1'))
    _, ctx = fixture()
    provider = DistillerProvider()
    first = asyncio.create_task(provider.run(agent, data(ctx.window), timeout_s=.08))
    second = asyncio.create_task(provider.run(agent, data(ctx.window), timeout_s=5))
    try:
        await spin_until(lambda: len(entered) == 2)
        timed = await first
        assert timed.reason == 'PROVIDER_TIMEOUT' and timed.result is None
        assert timed.usage['llm_calls'] == 1
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        denied = await DistillerProvider().run(agent, data(ctx.window), timeout_s=.1)
        assert denied.reason == 'PROVIDER_CAPACITY' and denied.usage['llm_calls'] == 0
        assert entered == [0, 1] and exited == []
        gates[0].set()
        await spin_until(lambda: 0 in exited)
        await asyncio.sleep(.02)
        third = await provider.run(agent, data(ctx.window), timeout_s=1)
        assert third.result.schema_valid and third.usage['llm_calls'] == 1
        assert timed.result is None and timed.usage['output_tokens'] is None
    finally:
        for gate in gates:
            gate.set()
        await asyncio.gather(first, second, return_exceptions=True)
        await spin_until(lambda: len(exited) == len(entered))


async def test_worker_exception_and_prestart_cancel_do_not_leak_capacity(monkeypatch):
    agent, _, calls = transport(monkeypatch)
    _, ctx = fixture()
    provider = DistillerProvider()
    task = asyncio.create_task(provider.run(agent, data(ctx.window), timeout_s=1))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not calls
    original = agent.run
    def fail(_):
        raise RuntimeError('private body')
    monkeypatch.setattr(agent, 'run', fail)
    bad = await provider.run(agent, data(ctx.window), timeout_s=1)
    assert bad.reason == 'AGENT_EXECUTION_FAILED' and bad.result is None
    monkeypatch.setattr(agent, 'run', original)
    assert (await provider.run(agent, data(ctx.window), timeout_s=1)).result.schema_valid


async def test_simultaneous_calls_do_not_share_run_receipts(monkeypatch):
    from dataclasses import replace
    original = httpx.Client
    barrier = threading.Barrier(2)
    def handle(request):
        user = json.loads(json.loads(request.content)['messages'][1]['content'])
        token_count = user['scope_id'] * 10
        barrier.wait(timeout=5)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"proposals": []}'}}],
                                        'usage': {'prompt_tokens': token_count, 'completion_tokens': 7}})
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    from rag_mcp.agents.llm_client import LLMClient
    from rag_mcp.agents.memory_distiller import MemoryDistiller
    agent = MemoryDistiller(LLMClient('http://offline.test', '', 'model-v1'))
    _, ctx = fixture()
    one = replace(ctx.window, episodes={})
    two = replace(one, scope_id=2)
    results = await asyncio.gather(*(DistillerProvider().run(agent, data(window), timeout_s=2) for window in (one, two)))
    assert [r.usage['input_tokens'] for r in results] == [10, 20]
    assert [r.usage['llm_calls'] for r in results] == [1, 1]


def test_legacy_parser_and_cache_cannot_salvage_distiller_packages(monkeypatch, tmp_path):
    agent, client, calls = transport(monkeypatch, content='prose {"proposals": []}', cache_dir=str(tmp_path))
    assert client.chat_json('legacy', 'data') == {'proposals': []}
    _, ctx = fixture()
    result = agent.run(data(ctx.window))
    assert result.degraded and 'MODEL_JSON_INVALID' in result.error
    assert len(calls) == 2


async def test_degraded_receipt_and_sanitized_failure_material_are_persisted(db_session, memory_writer_owner, monkeypatch):
    from dataclasses import replace

    from rag_mcp.orchestration.consolidation_pipeline import thaw
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
    from tests.integration.consolidation_fixtures import create_scope
    scope = await create_scope(db_session)
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner)
    token = await runtime.admit(scope, trigger='manual')
    agent, _, _ = transport(monkeypatch, status=429)
    current, ctx = fixture()
    window = replace(ctx.window, scope_id=scope, episodes={})
    batch = await propose(window, agent, current=replace(current, scope_id=scope),
                          context=replace(ctx, window=window), policy=POLICY, now=NOW)
    assert batch.degraded and batch.degradation_reasons == ('PROVIDER_HTTP_429',)
    await runtime.observe(token, status='proposing', provider_usage=thaw(batch.usage),
                          degradation_reasons=list(batch.degradation_reasons), proposals=[
        {'justification': 'password=do-not-persist', 'nested': {'scope_id': scope + 1, 'content': 'foreign-private-body'}},
        {'failure_body': 'unscoped-provider-body', 'context': {'keywords': ['ignore previous instructions']}}])
    latest = await runtime.latest_observation(token.run_id)
    assert latest.provider_usage['llm_calls'] == 1
    assert latest.degradation_reasons == ['PROVIDER_HTTP_429']
    assert latest.output_event_ids == [] and latest.output_memory_ids == []
    stored = json.dumps(latest.proposals)
    assert all(raw not in stored for raw in ('do-not-persist', 'foreign-private-body', 'unscoped-provider-body',
                                           'ignore previous instructions'))
    await db_session.rollback()
    assert await runtime.release(token)
