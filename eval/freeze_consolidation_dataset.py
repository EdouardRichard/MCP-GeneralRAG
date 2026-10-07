#!/usr/bin/env python3
"""T095: freeze the real consolidation evaluation dataset.

Builds ``eval/consolidation_eval_dataset.json`` from *real* isolated material:
one new public scope with its own published corpus, its declared evaluation
setup histories recorded through the ordinary ``MemoryService`` path, a legally
published enabled target policy, and the real published chunk positions and
memory event ids as locators.

Nothing is invented: every ``event_id``/``chunk_id``/``position_path`` in the
output is read back from the isolated database after the real publication, and
the dataset is validated by ``eval/consolidation_eval_support.validate_dataset``
before it is written (exclusive creation, never overwritten).

Usage (through the isolation runner, from the repo root):

    python .superpowers/sdd/013-tasks/isolation_runner.py eval \
      eval/freeze_consolidation_dataset.py \
      --scope-slug c013-eval-meeting-notes --domain-key c013-eval-generic \
      --corpus eval/corpora/generic/team_meeting_notes.md \
      --output eval/consolidation_eval_dataset.json
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (_REPO_ROOT / 'backend' / 'src', _REPO_ROOT / 'eval', _REPO_ROOT / 'backend'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from consolidation_eval_support import load_dataset, validate_dataset
from consolidation_restore_support import (
    authority_snapshot,
    canonical_digest,
)
from rag_mcp.config import get_settings
from rag_mcp.config.domain_profiles import DISTILLER_PROMPT_VERSION
from rag_mcp.indexing.qdrant_client import QdrantStore
from rag_mcp.models.chunk import Chunk
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.knowledge_source import KnowledgeSource
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.runtime.instance_registry import InstanceRegistryService
from rag_mcp.runtime.write_coordinator import (
    PostgresLeaseWriteCoordinator,
)
from rag_mcp.services.ingestion_service import IngestionService
from rag_mcp.services.memory_governance import MemoryGovernance
from rag_mcp.services.memory_policy import ConsolidationPolicy, MemoryPolicy
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.utils.hashing import hash_bytes
from rag_mcp.utils.snowflake import generate_id
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# (label, content, kind, supersedes label, provenance)
SETUP_HISTORIES: tuple[tuple[str, str, str, str | None, str], ...] = (
    ('fact_scope_rule',
     ('Every retrieval request must carry an explicit scope reference; '
      'implicit whole-library search is forbidden.'),
     'episodic', None, 'soft'),
    ('procedure_onboarding',
     ('New team members read the constitution first, then the 1.0 architecture '
      'blueprint; the evaluation README describes how to rerun every baseline report.'),
     'episodic', None, 'soft'),
    ('embedding_obsolete', 'The approved embedding upgrade for the next release is text-embedding-3-large.',
     'episodic', None, 'soft'),
    ('embedding_current', 'The approved embedding upgrade for the next release is BAAI/bge-m3.',
     'episodic', 'embedding_obsolete', 'soft'),
    ('frontend_obsolete', 'The frontend management console rewrite is owned by Wei Zhang.',
     'episodic', None, 'soft'),
    ('frontend_current', 'The frontend management console rewrite (React + antd) is owned by Maria Rodriguez.',
     'episodic', 'frontend_obsolete', 'soft'),
    ('domain_profile_alt_a',
     ('Domain differences are expressed declaratively through domain profiles '
      'instead of code paths.'),
     'episodic', None, 'soft'),
    ('domain_profile_alt_b',
     ('Supported formats and graph vocabularies are declared through domain profiles '
      'rather than code paths.'),
     'semantic', None, 'soft'),
    ('reranker_episodic', 'Li benchmarks reranker latency on CPU instances, due 2026-09-08.',
     'episodic', None, 'soft'),
    ('reranker_procedural',
     ('Benchmark the reranker latency on CPU instances before the 2026-09-08 deadline; '
      'Li owns it.'),
     'semantic', None, 'soft'),
)
CONTENT_BY_LABEL = {label: content for label, content, *_ in SETUP_HISTORIES}
# The declared evaluation setup clock: fixed so a resumed freeze is idempotent.
SETUP_CLOCK = '2026-10-07T00:00:00+00:00'


def inference_meta() -> dict:
    return {'source': '013 T095 declared evaluation setup', 'confidence': .8, 'model_version': 'fixture-v1',
            'time': SETUP_CLOCK, 'supporting_evidence': []}


def head_sha() -> str:
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=_REPO_ROOT, text=True).strip()


def schema_ref() -> str:
    path = _REPO_ROOT / 'specs' / '013-memory-consolidation-loop' / 'contracts' / 'benefit-report.schema.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    return str(payload.get('version') or payload.get('$id') or '013.2')


async def ensure_scope(factory, slug: str, domain_key: str) -> int:
    async with factory() as session:
        existing = (await session.execute(select(KnowledgeScope).where(KnowledgeScope.slug == slug))).scalars().first()
        if existing is not None:
            if existing.domain_key != domain_key:
                raise RuntimeError(f'scope {slug!r} already uses domain_key {existing.domain_key!r}')
            return int(existing.scope_id)
        session.add(DomainProfile(domain_key=domain_key, name=domain_key, supported_formats=['markdown'],
                                  graph_relations={}, default_capabilities={}, is_builtin=False, memory_policy={}))
        await session.flush()
        scope = KnowledgeScope(scope_id=generate_id(), scope_type='public', slug=slug, name=slug,
                               domain_key=domain_key)
        session.add(scope)
        await session.commit()
        return int(scope.scope_id)


async def ingest_corpus(factory, embedding, scope_id: int, corpus: Path, filename: str) -> dict:
    settings = get_settings()
    raw = corpus.read_bytes()
    async with factory() as session:
        existing = (await session.execute(select(KnowledgeSource).where(
            KnowledgeSource.knowledge_scope_id == scope_id,
            KnowledgeSource.filename == filename))).scalars().first()
        if existing is not None and existing.status == 'published':
            return {'source_id': int(existing.source_id), 'status': 'skipped_already_published'}
        source_id = int(generate_id())
        save_dir = Path(settings.data_root) / str(scope_id) / str(source_id)
        save_dir.mkdir(parents=True, exist_ok=True)
        (save_dir / filename).write_bytes(raw)
        await session.execute(text(
            'INSERT INTO knowledge_sources (source_id, knowledge_scope_id, filename, content_hash, format, '
            "size_bytes, status) VALUES (:sid, :ksid, :fn, :ch, 'markdown', :sz, 'uploaded')"),
            {'sid': source_id, 'ksid': scope_id, 'fn': filename, 'ch': hash_bytes(raw), 'sz': len(raw)})
        await session.commit()
        service = IngestionService(session, embedding, QdrantStore(url=settings.qdrant_url))
        await service.ingest(source_id, graph_ready=False)
        await session.commit()
    return {'source_id': source_id, 'status': 'ingested', 'content_hash': hash_bytes(raw),
            'size_bytes': len(raw), 'data_root_path': f'{scope_id}/{source_id}/{filename}'}


async def publish_target_policy(factory, embedding, scope_id: int, policy: dict) -> dict:
    async with factory() as session:
        governance = MemoryGovernance(MemoryService(session, embedding_provider=embedding))
        return await governance.execute('policy', scope_id=scope_id, actor='management',
                                        reason='T095 freeze the enabled target consolidation policy',
                                        policy=policy)


async def release_stale_leases(factory) -> list[int]:
    """Release active writer leases left by an interrupted isolated run (project cleanup caliber)."""
    from rag_mcp.models.runtime import WriterLease

    coordinator, registry = PostgresLeaseWriteCoordinator(factory), InstanceRegistryService(factory)
    async with factory() as session:
        rows = (await session.execute(select(WriterLease.lease_id, WriterLease.holder_instance_id,
                                             WriterLease.state))).all()
    released = []
    for lease_id, holder, state in rows:
        if state == 'active':
            await coordinator.release(lease_id)
            await registry.deregister(holder)
            released.append(int(lease_id))
    return released


async def record_histories(factory, embedding, scope_id: int) -> dict[str, int]:
    """Publish the declared setup histories; an already published one is reused.

    A resumed freeze must not re-record a content that the ordinary dedup path
    already owns (its stored submission metadata has the first run's declared
    clock), so the real published identity is reused instead of a conflict.
    """
    results: dict[str, int] = {}
    existing = await event_ids_by_content(factory, scope_id)
    async with factory() as session:
        service = MemoryService(session, embedding_provider=embedding)
        for label, content, kind, supersedes, provenance in SETUP_HISTORIES:
            if content in existing:
                results[label] = existing[content]
                continue
            payload = {'scope_id': scope_id, 'kind': kind, 'content': content, 'provenance': provenance,
                       'inference_meta': inference_meta(), 'confidence': .8}
            if supersedes is not None:
                payload['supersedes_memory_id'] = results[supersedes]
            outcome = await service.record(payload)
            results[label] = int(outcome['memory_id'])
            await session.commit()
    return results


async def event_ids_by_content(factory, scope_id: int) -> dict[str, int]:
    async with factory() as session:
        rows = (await session.execute(select(MemoryEvent.event_id, MemoryEvent.payload).where(
            MemoryEvent.knowledge_scope_id == scope_id))).all()
    mapping: dict[str, int] = {}
    for event_id, payload in rows:
        content = (payload or {}).get('content_text')
        if content:
            mapping[content] = int(event_id)
    return mapping


async def scope_chunks(factory, scope_id: int) -> list[dict]:
    async with factory() as session:
        rows = (await session.execute(select(Chunk.chunk_id, Chunk.position_path).where(
            Chunk.knowledge_scope_id == scope_id))).all()
    return sorted(({'chunk_id': int(chunk_id), 'position_path': position or ''} for chunk_id, position in rows),
                  key=lambda row: row['chunk_id'])


def chunk_for(chunks: list[dict], needle: str) -> dict:
    match = next((row for row in chunks if needle.lower() in row['position_path'].lower()), None)
    if match is None:
        raise RuntimeError(f'no published chunk of this scope matches {needle!r}; '
                           f'positions={[row["position_path"] for row in chunks]}')
    return match


def build_query(identifier: str, slot: str, question: str, category: str, scope_id: int,
                events: dict[str, int], units: list[dict], *, kind: str | None = None,
                chunk: dict | None = None) -> dict:
    labels = sorted({label for unit in units for label in unit['events']})
    locators = [{'kind': 'event', 'event_id': str(events[label])} for label in labels]
    if chunk is not None:
        locators.append({'kind': 'chunk', 'chunk_id': str(chunk['chunk_id']),
                         'position_path': chunk['position_path']})
    query = {'query_id': identifier, 'coverage_slot': slot, 'question': question,
             'primary_category': category, 'scope_id': str(scope_id),
             'expected_content': list(dict.fromkeys(unit['expected_content'] for unit in units)),
             'locators': locators,
             'expected_source_event_ids': [str(events[label]) for label in labels],
             'relevance_units': [{'alias': unit['alias'], 'expected_content': unit['expected_content'],
                                  'equivalence_group': unit['group'], 'validity': unit['validity'],
                                  'source_event_ids': [str(events[label]) for label in unit['events']]}
                                 for unit in units]}
    if category == 'extraction':
        query['extraction_kind'] = kind
    return query


def build_dataset(*, scope_id: int, domain_key: str, events: dict[str, int], chunks: list[dict],
                  version: str, snapshot_hash: str, cutoff: int, clock: str, frozen: dict) -> dict:
    architecture = chunk_for(chunks, 'Architecture Review')
    weekly = chunk_for(chunks, 'Weekly Sync')
    # A *correction* query declares two physically distinct relevance units: the
    # unit the correction superseded (historical) and the unit that holds now
    # (current).  Each unit therefore owns exactly its own real event; a unit that
    # declared both events could not be told apart from its sibling and would bind
    # both aliases onto one memory.
    queries = [
        build_query('q_extract_fact_01', 'extract_fact_01',
                    'Which retrieval-scope rule did the 2026-08-25 Architecture Review fix?',
                    'extraction', scope_id, events, kind='semantic', chunk=architecture, units=[{
                        'alias': 'ru-scope-rule', 'group': 'eq-scope-rule', 'validity': 'current',
                        'expected_content': 'Every retrieval request must carry an explicit scope reference; '
                                            'implicit whole-library search is forbidden.',
                        'events': ['fact_scope_rule']}]),
        build_query('q_distill_procedure_01', 'distill_procedure_01',
                    'What onboarding sequence does the team prescribe for new members?',
                    'extraction', scope_id, events, kind='procedural', units=[{
                        'alias': 'ru-onboarding-procedure', 'group': 'eq-onboarding-procedure',
                        'validity': 'current',
                        'expected_content': 'Read the constitution first, then the 1.0 architecture blueprint; '
                                            'the evaluation README describes how to rerun every baseline report.',
                        'events': ['procedure_onboarding']}]),
        build_query('q_correct_01', 'correct_01',
                    'Which embedding upgrade is approved for the next release now, and what did it replace?',
                    'correction', scope_id, events, chunk=weekly, units=[
                        {'alias': 'ru-embedding-superseded', 'group': 'eq-embedding-superseded',
                         'validity': 'historical',
                         'expected_content': 'The approved embedding upgrade for the next release is '
                                             'text-embedding-3-large.',
                         'events': ['embedding_obsolete']},
                        {'alias': 'ru-embedding-current', 'group': 'eq-embedding-current', 'validity': 'current',
                         'expected_content': 'The approved embedding upgrade for the next release is BAAI/bge-m3.',
                         'events': ['embedding_current']}]),
        build_query('q_correct_02', 'correct_02',
                    'Who owns the frontend management console rewrite, and who owned it before?',
                    'correction', scope_id, events, chunk=weekly, units=[
                        {'alias': 'ru-frontend-owner-superseded', 'group': 'eq-frontend-owner-superseded',
                         'validity': 'historical',
                         'expected_content': 'The frontend management console rewrite was owned by Wei Zhang.',
                         'events': ['frontend_obsolete']},
                        {'alias': 'ru-frontend-owner-current', 'group': 'eq-frontend-owner-current',
                         'validity': 'current',
                         'expected_content': 'The frontend management console rewrite (React + antd) is owned by '
                                             'Maria Rodriguez.',
                         'events': ['frontend_current']}]),
        build_query('q_merge_01', 'merge_01',
                    'How are domain format and vocabulary differences expressed?',
                    'merge', scope_id, events, chunk=architecture, units=[
                        {'alias': 'ru-domain-profile-a', 'group': 'eq-domain-profile', 'validity': 'current',
                         'expected_content': 'Domain differences are expressed declaratively through domain '
                                             'profiles instead of code paths.',
                         'events': ['domain_profile_alt_a']},
                        {'alias': 'ru-domain-profile-b', 'group': 'eq-domain-profile', 'validity': 'current',
                         'expected_content': 'Domain differences are expressed declaratively through domain '
                                             'profiles instead of code paths.',
                         'events': ['domain_profile_alt_b']}]),
        build_query('q_merge_02', 'merge_02',
                    'Which CPU reranker latency benchmark is outstanding and who owns it?',
                    'merge', scope_id, events, chunk=weekly, units=[
                        {'alias': 'ru-reranker-benchmark-episodic', 'group': 'eq-reranker-benchmark',
                         'validity': 'current',
                         'expected_content': 'Li benchmarks reranker latency on CPU instances, due 2026-09-08.',
                         'events': ['reranker_episodic']},
                        {'alias': 'ru-reranker-benchmark-procedural', 'group': 'eq-reranker-benchmark',
                         'validity': 'current',
                         'expected_content': 'Li benchmarks reranker latency on CPU instances, due 2026-09-08.',
                         'events': ['reranker_procedural']}]),
    ]
    return {
        'dataset_version': version, 'k': 5, 'gate_variant': 'consolidated_candidate_expansion',
        'scope_id': str(scope_id), 'snapshot_hash': snapshot_hash, 'authority_cutoff': cutoff,
        'frozen_clock': clock, 'frozen': frozen,
        'domain_profile': {
            'domain_key': domain_key,
            'declared_topic_adaptations': [
                ('the contract illustrative export/invoice topics are replaced by the real '
                 'team_meeting_notes.md retrieval-platform topics of this frozen scope'),
                'all six queries resolve inside this one frozen scope with its own domain profile',
                'the declared evaluation setup histories are not past user activity',
            ],
        },
        'source': {'corpus': 'eval/corpora/generic/team_meeting_notes.md', 'chunks': len(chunks)},
        'queries': queries,
    }


async def freeze(args: argparse.Namespace) -> int:
    from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider

    settings = get_settings()
    database = make_url(settings.database_url).database
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    registry, coordinator = InstanceRegistryService(factory), PostgresLeaseWriteCoordinator(factory)
    holder = uuid4()
    embedding = LocalCPUEmbeddingProvider()
    lease = None
    try:
        scope_id = await ensure_scope(factory, args.scope_slug, args.domain_key)
        ingestion = await ingest_corpus(factory, embedding, scope_id, args.corpus, args.corpus.name)
        await release_stale_leases(factory)
        registered = await registry.register(holder, 'writer', 'management', expiry_window_s=900)
        if not registered.registered:
            raise RuntimeError(f'writer registration refused: {registered.error}')
        lease = await coordinator.acquire(holder, expiry_window_s=900)
        if not lease.acquired:
            raise RuntimeError(f'writer lease refused: {lease.error}')
        policy = {'consolidation_enabled': True,
                  'consolidation': ConsolidationPolicy().model_dump()}
        policy_result = await publish_target_policy(factory, embedding, scope_id, policy)
        await record_histories(factory, embedding, scope_id)
        events = await event_ids_by_content(factory, scope_id)
        chunks = await scope_chunks(factory, scope_id)
        async with factory() as session:
            profile = (await session.execute(select(DomainProfile).where(
                DomainProfile.domain_key == args.domain_key))).scalar_one()
            profile_policy = dict(profile.memory_policy or {})
            vocabulary = profile.memory_link_vocabulary or {}
    finally:
        with contextlib.suppress(Exception):
            # Releasing an already-gone lease must not hide the real failure.
            if lease is not None and lease.acquired:
                await coordinator.release(lease.lease_id)
            await registry.deregister(holder)
        await engine.dispose()

    missing = [label for label, content in CONTENT_BY_LABEL.items() if content not in events]
    if missing:
        print(json.dumps({'status': 'failed', 'reason': f'no real event observed for {missing}'}))
        return 1
    label_events = {label: events[content] for label, content in CONTENT_BY_LABEL.items()}

    snapshot = authority_snapshot(database, scopes=[scope_id])
    snapshot_hash = snapshot['authority_digest']
    clock = datetime.now(UTC).replace(microsecond=0).isoformat()
    model_policy = MemoryPolicy.model_validate(profile_policy)
    budget = {key: getattr(model_policy, key) for key in ('per_scope_memory_quota', 'episodic_ttl_days')
              if hasattr(model_policy, key)}
    recall = {'top_k_default': settings.retrieval.top_k_default,
              'top_k_max': settings.retrieval.top_k_max,
              'rerank_budget': settings.hybrid_retrieval.rerank_budget,
              'reranker_model': settings.hybrid_retrieval.reranker_model,
              'embedding_model': settings.embedding_model,
              'llm_model': settings.llm_model}
    frozen = {'model': settings.embedding_model, 'prompt': DISTILLER_PROMPT_VERSION, 'schema': schema_ref(),
              'policy': canonical_digest(profile_policy),
              'vocabulary': canonical_digest(vocabulary),
              'recall': canonical_digest(recall),
              'budget': canonical_digest(budget if budget else profile_policy),
              'implementation': head_sha(), 'snapshot': snapshot_hash, 'clock': clock}
    dataset = build_dataset(scope_id=scope_id, domain_key=args.domain_key, events=label_events, chunks=chunks,
                            version=args.dataset_version, snapshot_hash=snapshot_hash,
                            cutoff=snapshot['authority_cutoff'], clock=clock, frozen=frozen)
    validate_dataset(dataset)
    if args.snapshot_out is not None:
        args.snapshot_out.write_text(json.dumps({'scope_id': scope_id, 'authority': snapshot,
                                                 'policy': profile_policy, 'frozen_clock': clock,
                                                 'frozen': frozen}, indent=2, sort_keys=True, default=str),
                                     encoding='utf-8')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dataset, indent=2, ensure_ascii=False, sort_keys=True) + '\n',
                           encoding='utf-8')
    load_dataset(args.output)
    print(json.dumps({'status': 'frozen', 'output': str(args.output), 'scope_id': scope_id,
                      'queries': len(dataset['queries']), 'snapshot_hash': snapshot_hash,
                      'authority_cutoff': snapshot['authority_cutoff'], 'chunks': len(chunks),
                      'policy_event': policy_result['event_id'], 'events': label_events,
                      'ingestion': ingestion}, indent=2, default=str))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope-slug', required=True)
    parser.add_argument('--domain-key', required=True)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dataset-version', default='013.eval.1')
    parser.add_argument('--snapshot-out', type=Path)
    args = parser.parse_args(argv)
    if args.output.exists():
        print(json.dumps({'status': 'refused', 'reason': f'{args.output} already exists'}))
        return 2
    return asyncio.run(freeze(args))


if __name__ == '__main__':
    raise SystemExit(main())
