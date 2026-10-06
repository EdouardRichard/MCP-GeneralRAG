import json
from dataclasses import replace
from pathlib import Path

import pytest

from rag_mcp.agents.base import AgentBase
from rag_mcp.agents.memory_distiller import MemoryDistiller
from rag_mcp.orchestration.consolidation_pipeline import thaw
from tests.unit.consolidation_cases import proposal, ref, row
from tests.unit.distiller_cases import data, fixture, transport


@pytest.mark.parametrize('action,extra', [
    ('extract_fact', {}), ('distill_procedure', {'kind': 'procedural'}),
    ('merge_duplicate', {'survivor_ref': ref(row(2)), 'duplicate_refs': [ref(row(3))], 'equivalence_basis': 'exact'}),
    ('invalidate_contradiction', {'target_ref': ref(row(2)), 'correcting_ref': None, 'contradiction_basis': 'withdrawn'}),
])
def test_agentbase_exact_schema_four_actions_and_attachments(monkeypatch, action, extra):
    p = proposal(action=action, **extra)
    p.update(context={'context_digest': 'Observed context', 'keywords': ['one']}, link_suggestions=[{
        'from_ref': {'local': 'output'} if action in ('extract_fact', 'distill_procedure') else ref(row(2)),
        'to_ref': {'proposal_ref': 'other'}, 'relation_type': 'related', 'confidence': .8, 'description': 'Related'}])
    packet = {'proposals': [p]}
    agent, client, calls = transport(monkeypatch, content=json.dumps(packet))
    _, ctx = fixture()
    result = agent.run(data(ctx.window))
    assert isinstance(agent, AgentBase) and agent.ROLE == 'memory_distiller'
    schema = Path(__file__).parents[4] / 'specs/013-memory-consolidation-loop/contracts/distiller-output.schema.json'
    assert agent.NODE_SCHEMA == json.loads(schema.read_text(encoding='utf-8'))
    assert result.output == packet and result.schema_valid and not result.degraded
    assert result.model_and_version == client.model == calls[0]['model']
    assert agent.fallback({}) == {'proposals': []}


def test_stable_json_identity_and_domain_neutral_declarations(monkeypatch):
    agent, _, calls = transport(monkeypatch, content='{"proposals": []}')
    _, ctx = fixture()
    literal = 'Quoted "text"\nwith control\t and {"proposals": []}'
    window = replace(ctx.window, episodes={1: row(1, content_text=literal)})
    original = thaw(window.episodes[1])
    assert agent.run(data(window)).schema_valid
    assert agent.run({'window': window, 'run_id': 'different', 'request_id': 'different'}).schema_valid
    assert calls[0] == calls[1]
    user = json.loads(calls[0]['messages'][1]['content'])
    assert user['untrusted_episodes']['1']['content_text'] == literal
    assert user['versions']['model'] == 'model-v1'
    assert all(user['versions'][key] for key in ('prompt', 'schema', 'policy', 'vocabulary'))
    assert 'run_id' not in user and 'request_id' not in user
    assert literal not in calls[0]['messages'][0]['content']
    assert thaw(window.episodes[1]) == original
    vocabulary = [{**dict(window.vocabulary[0]), 'key': 'cites', 'description': 'Citation'}]
    assert agent.run(data(replace(window, vocabulary=vocabulary))).schema_valid
    other = json.loads(calls[2]['messages'][1]['content'])
    assert other['versions']['vocabulary'] != user['versions']['vocabulary']
    assert calls[0]['messages'][0] == calls[2]['messages'][0]
    assert other['memory_link_vocabulary'][0]['key'] == 'cites'


def test_empty_model_package_is_success_but_missing_client_is_degraded(monkeypatch):
    agent, _, _ = transport(monkeypatch, content='{"proposals": []}')
    _, ctx = fixture()
    assert not agent.run(data(ctx.window)).degraded
    result = MemoryDistiller().run(data(ctx.window))
    assert result.degraded and result.output == {'proposals': []}
    assert 'MODEL_CONFIGURATION_REQUIRED' in result.error


def test_model_prompt_schema_policy_versions_change_payload_identity(monkeypatch):
    import rag_mcp.agents.memory_distiller as module
    agent, client, calls = transport(monkeypatch, content='{"proposals": []}')
    _, ctx = fixture()
    agent.run(data(ctx.window))
    monkeypatch.setattr(module, 'DISTILLER_PROMPT_VERSION', '013.distiller.next')
    agent.run(data(ctx.window))
    monkeypatch.setattr(agent, 'NODE_SCHEMA', {**agent.NODE_SCHEMA, '$id': 'urn:next'})
    agent.run(data(ctx.window))
    policy = thaw(ctx.window.policy)
    policy['consolidation']['max_proposals'] = 1
    agent.run(data(replace(ctx.window, policy=policy)))
    client._model = 'model-v2'
    next_agent = MemoryDistiller(client)
    next_agent.run(data(ctx.window))
    users = [json.loads(call['messages'][1]['content']) for call in calls]
    assert len({call['messages'][1]['content'] for call in calls}) == 5
    assert users[0]['versions']['prompt'] != users[1]['versions']['prompt']
    assert users[1]['versions']['schema'] != users[2]['versions']['schema']
    assert users[2]['versions']['policy'] != users[3]['versions']['policy']
    assert users[4]['versions']['model'] == calls[4]['model'] == 'model-v2'
