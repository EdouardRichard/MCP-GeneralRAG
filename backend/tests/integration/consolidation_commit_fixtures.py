from datetime import UTC, datetime

from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch, thaw
from rag_mcp.services.consolidation_adjudicator import AdjudicationContext, adjudicate_batch, memory_ref
from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
from rag_mcp.services.memory_policy import MemoryPolicy
from rag_mcp.services.memory_service import MemoryService
from tests.integration.consolidation_fixtures import StableEmbedding, create_scope, recorded_episode
from tests.unit.consolidation_cases import facts


async def prepared(session, owner, *, count=1, shared=True, links=False):
    scope = await create_scope(session)
    service = MemoryService(session, embedding_provider=StableEmbedding())
    sources = []
    for index in range(1 if shared else count):
        sources.append((await recorded_episode(service, scope, f'Observed source {index}'))['memory_id'])
    reference = None
    if links:
        from rag_mcp.models.domain_profile import DomainProfile
        from rag_mcp.models.knowledge_scope import KnowledgeScope
        from tests.unit.consolidation_cases import VOCAB
        reference = (await recorded_episode(service, scope, 'Approved semantic reference', kind='semantic'))['memory_id']
        profile = await session.get(DomainProfile, (await session.get(KnowledgeScope, scope)).domain_key)
        profile.memory_link_vocabulary = thaw(VOCAB)
        await session.commit()
    runtime = ConsolidationRuntime(session, owner=owner, memory_service=service)
    token = await runtime.admit(scope, trigger='manual')
    window = await runtime.select_and_seal(token)
    current = await runtime.read_snapshot(scope)
    proposals = []
    for index in range(count):
        proposals.append({'proposal_id': f'p{index}', 'action': 'extract_fact',
            'source_refs': [memory_ref(current.entries[sources[0 if shared else index]])],
            'kind': 'semantic', 'content': f'Approved conclusion {index}', 'confidence': .87,
            'evidence_refs': [], 'justification': 'Observed behavior',
            'context': {'context_digest': f'Navigation summary {index}', 'keywords': ['second', 'first']}})
        if reference:
            proposals[-1]['link_suggestions'] = [{'from_ref': {'local': 'output'}, 'to_ref': memory_ref(current.entries[reference]),
                'relation_type': 'related', 'description': 'Approved association', 'confidence': .9}]
    context = AdjudicationContext(window=window, inferences={p['proposal_id']: facts(p) for p in proposals})
    policy = MemoryPolicy.model_validate(thaw(window.policy))
    batch = ProposalBatch(proposals)
    decisions = adjudicate_batch(batch, current, policy, current.vocabulary,
        {'count': current.quota_count, 'limit': policy.per_scope_memory_quota}, context, datetime.now(UTC))
    assert decisions.groups and all(d.decision == 'accept' for d in decisions.decisions)
    await session.rollback()
    return service, runtime, token, batch, context, decisions


async def commit(fixture):
    service, runtime, token, batch, context, decisions = fixture
    return await service.commit_approved(decisions, token, runtime=runtime, batch=batch, context=context)
