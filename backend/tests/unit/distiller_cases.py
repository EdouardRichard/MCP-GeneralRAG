"""Concrete Phase 3 packets and offline httpx transport fixtures."""
import json
from dataclasses import replace

import httpx

from rag_mcp.agents.llm_client import LLMClient
from rag_mcp.agents.memory_distiller import MemoryDistiller
from rag_mcp.orchestration.consolidation_pipeline import thaw
from tests.unit.consolidation_cases import NOW, POLICY, VOCAB, proposal, row, setup


def fixture():
    entries = {i: row(i) for i in (1, 2, 3)}
    entries[4] = row(4, expires_at=NOW.isoformat())
    current, ctx = setup(entries=entries, sources=[1, 2, 3])
    window = replace(ctx.window, episodes={i: entries[i] for i in (1, 2, 3)},
                     policy=POLICY.model_dump(), vocabulary=VOCAB)
    return current, replace(ctx, window=window)


def data(window):
    return {'window': window, 'run_id': 'run-one', 'request_id': 'request-one'}


def transport(monkeypatch, *, content=None, status=200, error=None, envelope=None, cache_dir=None):
    calls = []
    original = httpx.Client

    def handle(request):
        calls.append(json.loads(request.content))
        if error:
            raise error
        body = envelope if envelope is not None else {
            'choices': [{'message': {'content': content if content is not None else json.dumps({'proposals': [proposal()]})}}],
            'usage': {'prompt_tokens': 17, 'completion_tokens': 11}}
        return httpx.Response(status, json=body)

    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    client = LLMClient('http://offline.test/v1', '', 'model-v1', cache_dir=cache_dir)
    return MemoryDistiller(client), client, calls


def model_packet(batch):
    return thaw(batch.proposals)
