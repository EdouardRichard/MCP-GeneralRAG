import json

import pytest

from rag_mcp.agents.memory_distiller import MemoryDistiller
from rag_mcp.orchestration.consolidation_pipeline import adjudicate_ttl, propose
from tests.unit.consolidation_cases import NOW, POLICY, decide, proposal
from tests.unit.distiller_cases import fixture, transport


INVALID = [None, {}, {'proposals': [{}]}, {'proposals': [proposal(action='unknown')]},
           {'proposals': [proposal(confidence=float('nan'))]}, {'proposals': [proposal(confidence=float('inf'))]},
           {'proposals': [proposal(confidence=2)]}, {'proposals': [proposal(), {}]},
           {'proposals': [proposal(scope_id=2)]}, {'proposals': [proposal()] * 129},
           {'proposals': [{k: v for k, v in proposal().items() if k != 'confidence'}]}]


@pytest.mark.parametrize('packet', INVALID)
async def test_whole_invalid_package_degrades_preserving_real_rules_and_ttl(monkeypatch, packet):
    agent, _, _ = transport(monkeypatch, content=json.dumps(packet))
    current, ctx = fixture()
    batch = await propose(ctx.window, agent, current=current, context=ctx, policy=POLICY, now=NOW)
    assert batch.degraded and batch.degradation_reasons and batch.proposals == ()
    assert batch.deterministic_proposals and len(batch.ttl_intents) == 1
    assert decide(batch.deterministic_proposals[0], current, ctx).decision == 'accept'
    assert adjudicate_ttl(batch.ttl_intents[0], current, now=NOW).approved_effects[0]['value']['retention_stage'] == 'compressed'


@pytest.mark.parametrize('failure', ['missing_client', 'zero_budget', 'missing_config', 'disabled', 'over_budget', 'none', 'exception'])
async def test_optional_model_failures_match_normal_deterministic_effects(monkeypatch, failure):
    agent, _, calls = transport(monkeypatch)
    current, ctx = fixture()
    normal = await propose(ctx.window, agent, current=current, context=ctx, policy=POLICY, now=NOW)
    assert not normal.degraded and len(normal.proposals) == 1
    policy = POLICY
    if failure == 'missing_client':
        agent = MemoryDistiller()
    elif failure == 'zero_budget':
        policy = POLICY.model_copy(update={'consolidation': POLICY.consolidation.model_copy(update={'max_llm_calls': 0})})
    elif failure == 'missing_config':
        agent = MemoryDistiller(__import__('rag_mcp.agents.llm_client', fromlist=['LLMClient']).LLMClient('', '', ''))
    elif failure == 'disabled':
        policy = POLICY.model_copy(update={'consolidation_enabled': False})
    elif failure == 'over_budget':
        policy = POLICY.model_copy(update={'consolidation': POLICY.consolidation.model_copy(update={'max_proposals': 1})})
        monkeypatch.setattr(agent, 'execute', lambda _: {'proposals': [proposal(), proposal('p1')]})
    elif failure == 'none':
        monkeypatch.setattr(agent, 'execute', lambda _: None)
    else:
        def fail(_):
            raise RuntimeError('foreign-scope failure password=do-not-retain')
        monkeypatch.setattr(agent, 'execute', fail)
    bad = await propose(ctx.window, agent, current=current, context=ctx, policy=policy, now=NOW)
    assert bad.degraded and bad.proposals == ()
    assert bad.deterministic_proposals == normal.deterministic_proposals
    assert bad.ttl_intents == normal.ttl_intents
    assert len(calls) == 1


@pytest.mark.parametrize('fallback', [{}, {'proposals': [proposal(), {}]}, {'proposals': [proposal(confidence=float('nan'))]}, 'raise'])
async def test_agentbase_fallback_revalidated_and_trusted_empty_used(monkeypatch, caplog, fallback):
    agent, _, _ = transport(monkeypatch, content='malformed')
    def failed(_):
        if fallback == 'raise':
            raise ValueError('foreign-scope body password=hidden-secret')
        return fallback
    monkeypatch.setattr(agent, 'fallback', failed)
    current, ctx = fixture()
    batch = await propose(ctx.window, agent, current=current, context=ctx, policy=POLICY, now=NOW)
    assert batch.degraded and batch.proposals == ()
    assert 'FALLBACK_INVALID' in batch.degradation_reasons
    assert 'MODEL_JSON_INVALID' in batch.degradation_reasons
    assert 'hidden-secret' not in caplog.text and 'foreign-scope body' not in caplog.text


async def test_rules_are_built_before_model_and_missing_policy_still_yields_ttl(monkeypatch):
    from rag_mcp.orchestration import consolidation_pipeline as pipeline
    current, ctx = fixture()
    agent, _, _ = transport(monkeypatch)
    events = []
    for name in ('deterministic_proposals', 'ttl_intents'):
        original = getattr(pipeline, name)
        def wrap(*args, _original=original, _name=name, **kwargs):
            events.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(pipeline, name, wrap)
    monkeypatch.setattr(agent, 'execute', lambda _: events.append('model') or {'proposals': []})
    await propose(ctx.window, agent, current=current, context=ctx, policy=POLICY, now=NOW)
    assert events == ['deterministic_proposals', 'ttl_intents', 'model']
    policy = POLICY.model_copy(update={'consolidation_enabled': False, 'consolidation': None})
    batch = await propose(ctx.window, agent, current=current, context=ctx, policy=policy, now=NOW)
    assert batch.degraded and len(batch.ttl_intents) == 1


async def test_exception_and_schema_logs_never_retain_raw_failure_body(monkeypatch, caplog):
    agent, _, _ = transport(monkeypatch)
    current, ctx = fixture()
    def fail(_):
        raise ValueError('foreign-scope body password=hidden-secret')
    monkeypatch.setattr(agent, 'execute', fail)
    batch = await propose(ctx.window, agent, current=current, context=ctx, policy=POLICY, now=NOW)
    assert batch.degraded and 'AGENT_EXECUTION_FAILED' in batch.degradation_reasons
    monkeypatch.setattr(agent, 'execute', lambda _: {'foreign-scope body': 'password=hidden-secret'})
    batch = await propose(ctx.window, agent, current=current, context=ctx, policy=POLICY, now=NOW)
    assert batch.degraded and 'MODEL_SCHEMA_INVALID' in batch.degradation_reasons
    assert 'foreign-scope' not in caplog.text and 'hidden-secret' not in caplog.text
