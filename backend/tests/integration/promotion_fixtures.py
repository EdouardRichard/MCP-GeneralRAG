"""Shared Phase 6 (US6) fixtures: one committed candidate and its promotion.

T066/T067 exercise the real writer path: a published same-scope corpus anchor,
one real consolidation commit that marks the semantic output as a promotion
candidate, then the explicit human promotion that shares the upload
registration steps.
"""
from datetime import UTC, datetime
from hashlib import sha256

from rag_mcp.models.chunk import Chunk
from rag_mcp.models.knowledge_source import KnowledgeSource
from rag_mcp.models.knowledge_version import KnowledgeVersion
from rag_mcp.orchestration.consolidation_pipeline import ProposalBatch, thaw
from rag_mcp.services.consolidation_adjudicator import (
    AdjudicationContext,
    adjudicate_batch,
    memory_ref,
)
from rag_mcp.services.consolidation_commit import read_evidence
from rag_mcp.services.consolidation_runtime import ConsolidationRuntime
from rag_mcp.services.memory_policy import MemoryPolicy
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.utils.snowflake import generate_id
from tests.integration.consolidation_fixtures import (
    StableEmbedding,
    create_scope,
    recorded_episode,
)
from tests.integration.test_013_consolidation_dependencies import keep_lease_alive
from tests.unit.consolidation_cases import facts

ANCHOR_TEXT = 'Published anchor body'
ANCHOR_POSITION = 'section/1'
CONCLUSION = 'Promotable conclusion'


async def published_anchor(session, scope_id, *, text=ANCHOR_TEXT, position=ANCHOR_POSITION):
    """A published same-scope corpus chunk usable as a hard candidate anchor."""
    source_id, version_id, chunk_id = generate_id(), generate_id(), generate_id()
    session.add(KnowledgeSource(source_id=source_id, knowledge_scope_id=scope_id, filename='anchor.md',
                                content_hash=sha256(text.encode()).hexdigest(), format='markdown',
                                size_bytes=len(text), status='published'))
    session.add(KnowledgeVersion(version_id=version_id, knowledge_scope_id=scope_id, version_number=1,
                                 capabilities={}, status='published', graph_ready=False,
                                 published_at=datetime.now(UTC)))
    session.add(Chunk(chunk_id=chunk_id, source_id=source_id, version_id=version_id,
                      knowledge_scope_id=scope_id, content_text=text, position_path=position,
                      chunk_type='markdown', start_line=1, end_line=1, token_count=5,
                      embedding_model='test', index_version='test'))
    await session.commit()
    return {'source_id': source_id, 'version_id': version_id, 'chunk_id': chunk_id,
            'content_hash': sha256(text.encode()).hexdigest(), 'position': position, 'text': text}


async def committed_candidate(session, owner, *, confidence=.97, content=CONCLUSION):
    """One real consolidation run whose semantic output becomes a candidate."""
    scope = await create_scope(session)
    service = MemoryService(session, embedding_provider=StableEmbedding())
    anchor = await published_anchor(session, scope)
    source = (await recorded_episode(service, scope, 'Observed source'))['memory_id']
    runtime = ConsolidationRuntime(session, owner=owner, memory_service=service)
    await keep_lease_alive(session, owner)
    token = await runtime.admit(scope, trigger='manual')
    window = await runtime.select_and_seal(token)
    current = await runtime.read_snapshot(scope)
    proposal = {'proposal_id': 'p0', 'action': 'extract_fact',
                'source_refs': [memory_ref(current.entries[source])], 'kind': 'semantic',
                'content': content, 'confidence': confidence, 'evidence_refs': [str(anchor['chunk_id'])],
                'justification': 'Observed behavior'}
    batch = ProposalBatch([proposal])
    support = await read_evidence(session, {str(anchor['chunk_id'])})
    context = AdjudicationContext(window=window, inferences={'p0': facts(proposal)},
                                  support_facts=support, support_versions=support)
    policy = MemoryPolicy.model_validate(thaw(window.policy))
    decisions = adjudicate_batch(batch, current, policy, current.vocabulary,
                                 {'count': current.quota_count, 'limit': policy.per_scope_memory_quota},
                                 context, datetime.now(UTC))
    assert decisions.groups and [d.decision for d in decisions.decisions] == ['accept']
    await session.rollback()
    outcome = await service.commit_approved(decisions, token, runtime=runtime, batch=batch, context=context)
    assert outcome.status == 'completed', outcome.reason_codes
    snapshot = await runtime.read_snapshot(scope)
    memory = snapshot.entries[outcome.output_memory_ids[0]]
    await session.rollback()
    assert memory['candidate_version'], memory.get('candidate_basis')
    return {'scope': scope, 'service': service, 'runtime': runtime, 'anchor': anchor,
            'memory': memory, 'memory_id': memory['memory_id'],
            'candidate_version': memory['candidate_version']}


async def promote(session, fixture, *, reason='approved by operator', candidate_version=None,
                  memory_id=None, scope_id=None):
    return await MemoryService(session, embedding_provider=StableEmbedding()).promote_candidate(
        scope_id=scope_id if scope_id is not None else fixture['scope'],
        memory_id=memory_id if memory_id is not None else fixture['memory_id'],
        candidate_version=candidate_version if candidate_version is not None else fixture['candidate_version'],
        actor='management', reason=reason)
