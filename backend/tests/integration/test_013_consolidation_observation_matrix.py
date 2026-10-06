import asyncio
from dataclasses import replace

import pytest

from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch, run_pipeline, thaw
from tests.integration.consolidation_commit_fixtures import prepared


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,status', [('complete', 'succeeded'), ('pending', 'failed'), ('partial', 'partial'),
    ('rejected', 'no_change'), ('degraded', 'degraded'), ('cancelled', 'interrupted')])
async def test_observations_distinguish_acceptance_publication_and_usage(db_session, memory_writer_owner, monkeypatch, mode, status):
    fixture = await prepared(db_session, memory_writer_owner, count=2 if mode == 'partial' else 1, shared=False)
    service, runtime, token, batch, context, _ = fixture
    async def selector(token):
        return context.window
    async def proposer(*args, **kwargs):
        assert not db_session.in_transaction()
        if mode == 'cancelled':
            raise asyncio.CancelledError()
        if mode == 'degraded':
            return ProposalBatch([], degraded=True, degradation_reasons=['MODEL_CONFIGURATION_REQUIRED'])
        if mode == 'rejected':
            proposals = thaw(batch.proposals)
            for proposal in proposals:
                proposal['confidence'] = .1
            return replace(batch, proposals=proposals)
        return batch
    if mode in ('partial', 'pending'):
        original = service.projections._materialize_dense
        calls = 0
        async def fail(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == (2 if mode == 'partial' else 1):
                raise OSError('external publication failure')
            return await original(*args, **kwargs)
        monkeypatch.setattr(service.projections, '_materialize_dense', fail)
    if mode == 'cancelled':
        with pytest.raises(asyncio.CancelledError):
            await run_pipeline(runtime, token, distiller=None, select=selector, propose_stage=proposer)
    else:
        outcome = await run_pipeline(runtime, token, distiller=None, select=selector, propose_stage=proposer)
    observation = await runtime.latest_observation(token.run_id)
    assert observation.status == status
    if mode == 'cancelled':
        assert not observation.output_memory_ids
        return
    assert observation.output_memory_ids == list(outcome.output_memory_ids)
    assert observation.provider_usage['input_tokens'] is None and observation.provider_usage['cost_usd'] is None
    if mode in ('pending', 'partial'):
        assert observation.pending_result_keys and all(d['decision'] == 'accept' for d in observation.adjudications)
        assert len(observation.output_memory_ids) == (1 if mode == 'partial' else 0)
    if mode == 'partial':
        assert sorted(d['publication'] for d in observation.adjudications) == ['committed', 'pending']
    if mode == 'rejected':
        assert 'all_rejected' in observation.degradation_reasons


@pytest.mark.asyncio
async def test_empty_pipeline_records_no_change_without_effects(db_session, memory_writer_owner):
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
    from rag_mcp.services.memory_service import MemoryService
    from tests.integration.consolidation_fixtures import StableEmbedding, create_scope
    scope = await create_scope(db_session)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    runtime = ConsolidationRuntime(db_session, owner=memory_writer_owner, memory_service=service)
    token = await runtime.admit(scope, trigger='manual')
    result = await run_pipeline(runtime, token, distiller=None)
    latest = await runtime.latest_observation(token.run_id)
    assert result.reason_codes == ('empty_window',) and latest.status == 'no_change'
    assert latest.degradation_reasons == ['empty_window'] and not latest.output_event_ids
