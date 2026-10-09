#!/usr/bin/env python3
"""T055/T056: the 014 memory-continuity comparison runner (record/replay).

Two arms, two rounds, four independent restorations of the same sealed
authority (``memory_continuity_support.allocate_identities``):

* ``without_memory`` -- the baseline.  It carries **no** ``session_id`` and **no**
  ``memory_context``, shares no session and no delivered set with the memory arm,
  and its response is asserted to carry zero new fields
  (``related_memories``/``memory_notice``/``counts``/``working_set``).
* ``with_memory`` -- the same frozen input snapshot, query set, budget and
  environment with memory availability as the **only** enabled variable.

The arms are driven through the existing MCP tool boundary
(``rag_mcp.mcp.search_knowledge`` / ``rag_mcp.mcp.start_work``) and never through
014-specific internals; the imports are lazy so this module imports on a machine
where the 014 fields and every service do not exist yet.

Gate judgement (T056, contract §3/§5):

* quality: ``relative_gain = (with - without) / without >= 3%`` **or** the
  pre-frozen explicit criterion (``dataset.explicit_criterion``) is met;
* ``without_memory == 0`` => ``BASELINE_ZERO_NOT_COMPUTABLE``: the relative gain
  is ``None`` and is never replaced by a tiny/infinite substitute;
* ``default_enable_eligible = quality AND safety AND regression AND
  reproducibility == 'passed'``;
* the report **never** flips a configuration switch: it only carries the
  evidence for (or against) default enablement.

Exit codes: 0 pass / 1 fail / 2 incomplete evidence.  ``--output`` must be
unique and an existing report is never overwritten with different bytes.

Environment note (measured 2026-10-09, third round): the frozen scope's sealed
capsule is available (``C:\\t102\\capsule``, authority digest = the dataset's
``snapshot_hash``), so the record/replay rounds run against four real
restorations.  Each ``(round, arm)`` is bound to its own restored database,
Qdrant store and data root through :func:`identity_environment` before any tool
call; nothing falls back to the process-wide shared store.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import platform
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / 'eval', ROOT / 'backend' / 'src', ROOT / 'backend'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# The restoration/identity layer reads ``DATABASE_URL``/``DATABASE_URL_SYNC`` from
# the environment before any rag_mcp import happens, so the repository ``.env``
# must be loaded here (the runner may otherwise start before rag_mcp.config).
with contextlib.suppress(Exception):
    from dotenv import load_dotenv

    load_dotenv(ROOT / '.env')
    load_dotenv(Path.cwd() / '.env')

from memory_continuity_support import (
    ARMS,
    CacheIncomplete,
    CachedToolFailure,
    ComparisonFailed,
    DatasetInvalid,
    FULL_INTEGRITY_KEYS,
    NON_LATENCY_TOLERANCE,
    RELATIVE_GAIN_THRESHOLD,
    REPORT_TYPE,
    REPORT_VERSION,
    ROUNDS,
    ZERO_BASELINE_CODE,
    ZERO_SAFETY_KEYS,
    ArmObservation,
    PreflightIncomplete,
    ToolCallCache,
    allocate_identities,
    arm_parameters,
    arm_policy,
    cache_key,
    completion_rate,
    encode_report,
    explicit_criterion_check,
    load_dataset,
    locator_parts,
    redundancy,
    relative_gain,
    reproducibility_status,
    restore_identities,
    task_complete,
    validate_comparison_report,
    validate_dataset,
    zero_new_fields,
)

EXIT_OK, EXIT_FAILED, EXIT_INCOMPLETE = 0, 1, 2
SEARCH_TOOL = 'search_knowledge'
WORK_TOOL = 'start_work'
DEFAULT_CONFIGURATION = {
    'memory_aware_retrieval_enabled': False,
    'memory_consumption_projection_enabled': False,
    'switches_changed': False,
    'reason': ('evidence-only report: both 014 deployment switches stay false '
               'and no domain policy was published'),
}
EXIT_STATUS = {'passed': EXIT_OK, 'failed': EXIT_FAILED, 'incomplete': EXIT_INCOMPLETE}


def exit_code_for(status: str) -> int:
    """0 pass / 1 fail / 2 incomplete evidence."""
    try:
        return EXIT_STATUS[status]
    except KeyError as error:
        raise ComparisonFailed(f'unknown report status {status!r}') from error


# ---------------------------------------------------------------------------
# T056: gate judgement
# ---------------------------------------------------------------------------

def relative_gain_gate(gain: dict, *, threshold: float = RELATIVE_GAIN_THRESHOLD) -> tuple:
    """The 3 % relative-gain threshold, or a named not-computable baseline."""
    checks = {'relative_gain_threshold_met': False, 'baseline_zero': bool(gain['zero_baseline'])}
    reasons = []
    if gain['zero_baseline']:
        checks['code'] = ZERO_BASELINE_CODE
        reasons.append(ZERO_BASELINE_CODE)
    else:
        checks['relative_gain_threshold_met'] = bool(gain['value'] is not None
                                                     and gain['value'] >= threshold)
        if not checks['relative_gain_threshold_met']:
            reasons.append('RELATIVE_GAIN_BELOW_THRESHOLD')
    return checks, reasons


def quality_gate(*, gain: dict, explicit: dict) -> tuple:
    """Quality = relative gain >= 3 % **or** the pre-frozen explicit criterion."""
    checks, reasons = relative_gain_gate(gain)
    checks['explicit_criterion_met'] = bool(explicit['met'])
    checks['quality_met'] = bool(checks['relative_gain_threshold_met'] or checks['explicit_criterion_met'])
    if checks['baseline_zero'] and not checks['explicit_criterion_met']:
        # The baseline cannot carry a relative gain; the frozen explicit criterion
        # is the only substitute, and a failure to meet it is the reason.
        reasons.append('EXPLICIT_CRITERION_NOT_MET')
    if not checks['quality_met'] and not reasons:
        reasons.append('RELATIVE_GAIN_BELOW_THRESHOLD')
    return checks, list(dict.fromkeys(reasons))


def safety_gate(hard_metrics: dict) -> tuple:
    """Zero-tolerance safety and full-integrity rates; unobserved stays unobserved."""
    checks, reasons = {}, []
    unobserved, violations = [], 0
    for key in ZERO_SAFETY_KEYS + FULL_INTEGRITY_KEYS:
        value = (hard_metrics or {}).get(key)
        if value is None:
            unobserved.append(key)
            checks[key] = False
            reasons.append(f'SAFETY_OBSERVATION_INCOMPLETE:{key}')
            continue
        expected = 0 if key in ZERO_SAFETY_KEYS else 1.0
        checks[key] = value == expected
        if not checks[key]:
            violations += 1
            reasons.append(f'{key.upper()}_VIOLATION')
    checks['all_required_observed'] = not unobserved
    checks['violations'] = violations
    checks['zero_tolerance_clean'] = violations == 0
    return checks, reasons


def regression_gate(*, reproducibility: dict, cache: dict, regression_evidence: dict | None) -> tuple:
    """No regression: a reproduced run, zero replay network calls, the old-suite evidence."""
    evidence = regression_evidence or {}
    drift = reproducibility.get('max_non_latency_relative_drift')
    checks = {
        'reproducibility_passed': reproducibility.get('status') == 'passed',
        'replay_zero_network': bool(cache.get('replay_real_network_calls') == 0
                                    and cache.get('evidence_complete')),
        'non_latency_drift_within_tolerance': bool(
            drift is not None and drift <= NON_LATENCY_TOLERANCE),
        'legacy_contract_evidence_present': bool(evidence.get('legacy_contract')),
        'approved_window_change_recorded': evidence.get('delivered_ttl_seconds') == 3600,
    }
    checks['evidence_complete'] = bool(checks['legacy_contract_evidence_present']
                                       and checks['approved_window_change_recorded'])
    checks['regression_met'] = all(checks[key] for key in (
        'reproducibility_passed', 'replay_zero_network', 'non_latency_drift_within_tolerance',
        'legacy_contract_evidence_present', 'approved_window_change_recorded'))
    reasons = [f'{key.upper()}_FAILED' for key in (
        'reproducibility_passed', 'replay_zero_network', 'non_latency_drift_within_tolerance',
        'legacy_contract_evidence_present', 'approved_window_change_recorded') if not checks[key]]
    return checks, reasons


def default_enable_eligible(*, quality: dict, safety: dict, regression: dict,
                            reproducibility: dict) -> bool:
    """All three gates plus a reproduced run; the report changes no switch itself."""
    return bool(quality.get('quality_met') and safety.get('all_required_observed')
                and safety.get('violations') == 0 and regression.get('regression_met')
                and reproducibility.get('status') == 'passed')


# ---------------------------------------------------------------------------
# Tool boundary (existing MCP tools only; lazily imported)
# ---------------------------------------------------------------------------

def tool_payload(tool: str, query: dict, *, parameters: dict, policy: dict, scope_ref: str,
                 top_k: int = 5) -> dict:
    """The frozen per-arm call payload for one query.

    The baseline never receives ``session_id``/``memory_context`` and the memory
    arm's policy gates the working-set form, so memory availability is the only
    variable.  ``search_knowledge`` addresses memory through ``domain_scope``
    (the frozen scope slug); ``start_work`` takes the string ``scope_ref``.
    """
    if tool == WORK_TOOL:
        payload = {'scope_ref': scope_ref,
                   'include_working_set': bool(policy['working_set_enabled'])}
    else:
        payload = {'query': query['question'], 'domain_scope': [scope_ref],
                   'top_k': max(1, int(top_k))}
    if policy['memory_attachment_enabled']:
        if parameters.get('session_id') is not None:
            payload['session_id'] = parameters['session_id']
        if parameters.get('memory_context') is not None:
            payload['memory_context'] = parameters['memory_context']
    return payload


#: Process-wide read-only provider cache: the local CPU models are expensive to
#: load and are shared by all four identities (they carry no identity state).
_PROVIDERS: dict = {}


def _embedding_provider():
    if 'embedding' not in _PROVIDERS:
        from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider

        provider = LocalCPUEmbeddingProvider()
        warmup = getattr(provider, 'warmup', None)
        if callable(warmup):
            warmup()
        _PROVIDERS['embedding'] = provider
    return _PROVIDERS['embedding']


def _reranker():
    if 'reranker' not in _PROVIDERS:
        from rag_mcp.providers.local_cpu_reranker import LocalCPUReranker

        provider = LocalCPUReranker()
        warmup = getattr(provider, 'warmup', None)
        if callable(warmup):
            warmup()
        _PROVIDERS['reranker'] = provider
    return _PROVIDERS['reranker']


#: Every setting the arm path resolves from the environment (the settings object
#: is rebuilt on each ``get_settings()`` call), bound per identity.
_IDENTITY_ENV_KEYS = ('DATABASE_URL', 'DATABASE_URL_SYNC', 'QDRANT_URL', 'DATA_ROOT',
                      'MEMORY_AWARE_RETRIEVAL_ENABLED', 'MEMORY_CONSUMPTION_PROJECTION_ENABLED',
                      'AGENTIC_RETRIEVAL_ENABLED')


@contextlib.contextmanager
def identity_environment(identity, *, memory_enabled: bool):
    """Point the process at one identity's independent database/Qdrant/data root.

    Reuses the 013 restoration scheme's binding (``configure_arm``): the 014 tool
    path reads its settings from the environment on every call, so binding before
    the call is what makes each ``(round, arm)`` a genuinely independent
    restoration of the sealed capsule.
    """
    from sqlalchemy.engine import make_url

    base = os.environ.get('DATABASE_URL')
    if not base:
        raise PreflightIncomplete('DATABASE_URL is not configured')
    sync_base = os.environ.get('DATABASE_URL_SYNC') or base.replace('+asyncpg', '+psycopg2')
    previous = {key: os.environ.get(key) for key in _IDENTITY_ENV_KEYS}
    os.environ['DATABASE_URL'] = make_url(base).set(
        database=identity.database).render_as_string(hide_password=False)
    os.environ['DATABASE_URL_SYNC'] = make_url(sync_base).set(
        database=identity.database).render_as_string(hide_password=False)
    os.environ['QDRANT_URL'] = identity.qdrant_url
    os.environ['DATA_ROOT'] = str(identity.data_root)
    os.environ['MEMORY_AWARE_RETRIEVAL_ENABLED'] = 'true' if memory_enabled else 'false'
    os.environ['MEMORY_CONSUMPTION_PROJECTION_ENABLED'] = 'false'
    os.environ['AGENTIC_RETRIEVAL_ENABLED'] = 'false'
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def ensure_identity(capsule_dir: Path, identity) -> dict:
    """Restore the identity, or re-verify an already materialised restoration.

    The record and replay rounds are separate invocations, so the replay round
    must reuse the very same four identities.  An existing database/data root is
    re-verified (and its Qdrant process restarted when the previous process has
    exited) instead of being recreated.
    """
    from consolidation_restore_support import database_exists, restore_identity, start_qdrant, verify_identity

    capsule_dir = Path(capsule_dir)
    if database_exists(identity.database) and Path(identity.data_root).exists():
        try:
            return verify_identity(capsule_dir, identity)
        except Exception:  # noqa: BLE001 - a dead Qdrant process is not a digest mismatch
            start_qdrant(identity)
            return verify_identity(capsule_dir, identity)
    return restore_identity(capsule_dir, identity)


async def rebuild_identity_evidence_index(identity, *, scope_id: int) -> dict:
    """Rebuild the identity's derived evidence dense index from the restored chunks.

    The 013 capsule seals the memory dense collection but not the evidence index.
    A derived index is rebuildable from source metadata (Constitution VIII), so
    the dense collection is reconstructed here from the restored ``chunks`` rows
    with the frozen embedding model; the authority itself is untouched and the
    points carry exactly the published chunk identity.
    """
    from qdrant_client.models import PointStruct
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from rag_mcp.config import get_settings
    from rag_mcp.indexing.qdrant_client import QdrantStore

    with identity_environment(identity, memory_enabled=False):
        engine = create_async_engine(get_settings().database_url)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                rows = (await session.execute(text(
                    "select c.chunk_id, c.source_id, c.version_id, c.content_text, c.position_path, "
                    "c.chunk_type, c.start_line, c.end_line, c.index_version, c.embedding_model "
                    "from chunks c join knowledge_versions v on v.version_id = c.version_id "
                    "where c.knowledge_scope_id = :scope and v.status = 'published' "
                    "order by c.chunk_id"), {'scope': scope_id})).mappings().all()
        finally:
            await engine.dispose()
        if not rows:
            raise ComparisonFailed(
                f'{identity.label}: no published chunks to index for scope {scope_id}')
        grouped: dict[str, list] = {}
        for row in rows:
            grouped.setdefault(str(row['index_version']), []).append(row)
        store = QdrantStore()
        written: dict[str, int] = {}
        for index_version, group in grouped.items():
            collection = f'chunks_dense_{index_version}'
            vectors = await _embedding_provider().embed_texts([row['content_text'] for row in group])
            if not store.collection_exists(collection):
                store.create_collection(collection, dimension=len(vectors[0]))
            points = [
                PointStruct(
                    id=int(row['chunk_id']),
                    vector=vector,
                    payload={
                        'knowledge_scope_id': str(scope_id),
                        'source_id': str(row['source_id']),
                        'version_id': str(row['version_id']),
                        'chunk_id': str(row['chunk_id']),
                        'chunk_type': row['chunk_type'],
                        'position_path': row['position_path'],
                        'start_line': int(row['start_line']),
                        'end_line': int(row['end_line']),
                        'index_version': index_version,
                        'embedding_model': row['embedding_model'],
                    },
                )
                for row, vector in zip(group, vectors, strict=True)
            ]
            store.upsert_points(collection, points)
            written[collection] = len(points)
        return written


async def assert_identity_scope(identity, scope_ref: str) -> None:
    """Prove the restored identity actually serves the frozen scope."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from rag_mcp.config import get_settings

    with identity_environment(identity, memory_enabled=False):
        engine = create_async_engine(get_settings().database_url)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                found = await session.execute(
                    text("select scope_id from knowledge_scopes where slug = :slug and status = 'active'"),
                    {'slug': scope_ref})
                if found.first() is None:
                    raise ComparisonFailed(
                        f'{identity.label}: frozen scope {scope_ref!r} is absent from the restoration')
        finally:
            await engine.dispose()


async def call_tool(tool: str, payload: dict, *, identity, memory_enabled: bool):
    """Perform one real tool call inside the identity's isolated environment.

    The shared implementation used by the MCP tools is invoked with the
    identity's own session factory, Qdrant store, embedding/reranker providers
    and data root; the environment binding is what keeps the arms independent.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from rag_mcp.config import get_settings
    from rag_mcp.indexing.qdrant_client import QdrantStore
    from rag_mcp.services.memory_service import MemoryService

    with identity_environment(identity, memory_enabled=memory_enabled):
        engine = create_async_engine(get_settings().database_url)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            if tool == SEARCH_TOOL:
                from rag_mcp.mcp.search_knowledge import search_knowledge_core

                return await search_knowledge_core(
                    query=payload['query'],
                    project_scope=payload.get('project_scope') or [],
                    domain_scope=payload.get('domain_scope') or [],
                    top_k=int(payload.get('top_k') or 5),
                    task_context=payload.get('task_context'),
                    session_factory=factory,
                    qdrant_store=QdrantStore(),
                    embedding_provider=_embedding_provider(),
                    reranker=_reranker(),
                    session_id=payload.get('session_id'),
                    memory_context=payload.get('memory_context'),
                )
            if tool == WORK_TOOL:
                async with factory() as session:
                    service = MemoryService(session, embedding_provider=_embedding_provider(),
                                            qdrant_store=QdrantStore())
                    return await service.start_work(
                        scope_ref=payload['scope_ref'],
                        session_id=payload.get('session_id'),
                        include_working_set=(bool(payload.get('include_working_set'))
                                             and memory_enabled),
                    )
            raise ComparisonFailed(f'unknown tool {tool!r}')
        finally:
            await engine.dispose()


def tool_result_payload(result):
    """The structured payload of a ``CallToolResult`` (structuredContent first)."""
    structured = getattr(result, 'structuredContent', None)
    if structured is not None:
        return structured
    contents = getattr(result, 'content', None) or []
    for item in contents:
        text = getattr(item, 'text', None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                continue
    return {}


def observe_response(query: dict, response: dict, *, arm: str, round_name: str) -> ArmObservation:
    """Reduce one arm's real response to the rule-decidable outcome.

    Only the response's own locatable items are read: memory entries
    (``related_memories``, 014) and evidence entries (``evidence``, 001/002).  A
    required item is *hit* when its stable locator is resolved from the response
    and *cited* when that resolution carries a locatable citation; no model and no
    free-text guess is involved.
    """
    response = response if isinstance(response, dict) else {}
    delivered_locators, cited_locators, forbidden_hits = set(), set(), set()

    def resolve(locator: str, *, cited: bool) -> None:
        delivered_locators.add(locator)
        if cited:
            cited_locators.add(locator)

    memory_index = {str(item['memory_id']): item['locator']
                    for item in query['required_items'] if item.get('memory_id')}
    forbidden_index = {str(item['memory_id']): item['locator']
                       for item in query['forbidden_items'] if item.get('memory_id')}
    for entry in response.get('related_memories') or ():
        memory_id = str(entry.get('memory_id'))
        locator = memory_index.get(memory_id)
        if locator is not None:
            resolve(locator, cited=bool(entry.get('provenance')))
        forbidden = forbidden_index.get(memory_id)
        if forbidden is not None:
            forbidden_hits.add(forbidden)
    for entry in response.get('evidence') or ():
        position = ' > '.join(str(entry.get(key)) for key in
                              ('source_id', 'source_version', 'source_position') if entry.get(key))
        for item in query['required_items']:
            heading = locator_parts(item['locator'])['heading']
            if heading and heading in position:
                resolve(item['locator'], cited=bool(entry.get('source_position')))
        # Forbidden *claim* items (``banned_claim``/``superseded_item``) are
        # synthetic counter-claims, not headings: a shared-heading evidence match
        # says nothing about them.  They are detected only through their own
        # ``memory_id`` (above) or through an explicit scope leak (below).
    for item in query['forbidden_items']:
        if item['kind'] == 'out_of_scope':
            slug = locator_parts(item['locator'])['slug']
            for entry in response.get('related_memories') or ():
                if entry.get('scope_slug') not in (None, slug):
                    forbidden_hits.add(item['locator'])
    return ArmObservation(query_id=query['query_id'], arm=arm, round=round_name,
                          hits=tuple(delivered_locators), cited=tuple(cited_locators),
                          forbidden_hits=tuple(sorted(forbidden_hits)),
                          delivered=tuple(delivered_locators),
                          baseline_new_fields=tuple(zero_new_fields(response)) if arm == 'without_memory' else (),
                          raw=response if isinstance(response, dict) else {})


def arm_session_id(arm: str, snapshot_hash: str) -> str:
    """A stable, arm-distinct session UUID for the memory arm.

    The tool validates ``session_id`` as a UUID, and the record and replay rounds
    must use the same session for the same arm.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'014-continuity:{arm}:{snapshot_hash}'))


async def run_arm(identity, *, dataset: dict, cache: ToolCallCache, round_name: str,
                  scope_ref: str) -> dict:
    """Drive one arm of one round through the sealed cache boundary."""
    rows = {}
    #: A stable, arm-distinct UUID: the tool validates ``session_id`` as a UUID,
    #: and record/replay must use the same session for the same arm.
    session_id = arm_session_id(identity.arm, dataset['snapshot_hash'])
    parameters = arm_parameters(identity.arm, session_id=session_id,
                                memory_context=('resume the interrupted task in this scope'
                                                if identity.arm == 'with_memory' else None))
    policy = arm_policy(identity.arm)
    await assert_identity_scope(identity, scope_ref)
    for query in dataset['queries']:
        key = cache_key(SEARCH_TOOL, identity.arm, query['query_id'])
        payload = tool_payload(SEARCH_TOOL, query, parameters=parameters, policy=policy,
                               scope_ref=scope_ref, top_k=int(dataset.get('k') or 5))
        try:
            response = await cache.invoke_async(
                key, lambda payload=payload: call_tool(
                    SEARCH_TOOL, payload, identity=identity,
                    memory_enabled=bool(policy['memory_attachment_enabled'])))
        except CachedToolFailure as error:
            rows[(round_name, identity.arm, query['query_id'])] = ArmObservation(
                query_id=query['query_id'], arm=identity.arm, round=round_name, error=str(error))
            continue
        except Exception as error:  # noqa: BLE001 - a real arm failure is reported, never hidden
            rows[(round_name, identity.arm, query['query_id'])] = ArmObservation(
                query_id=query['query_id'], arm=identity.arm, round=round_name,
                error=f'{type(error).__name__}: {error}')
            continue
        observation = observe_response(query, response, arm=identity.arm, round_name=round_name)
        if identity.arm == 'without_memory':
            violations = zero_new_fields(response)
            observation.baseline_new_fields = tuple(violations)
            if violations:
                # Contract §1: the unique enabled variable is memory availability.
                # A polluted baseline response is a measured contract violation, so
                # it is recorded (and reported as failed) instead of being hidden.
                observation.error = f'BASELINE_NEW_FIELDS:{",".join(violations)}'
        rows[(round_name, identity.arm, query['query_id'])] = observation
    return rows


def observe_hard_metrics(observations: dict) -> dict:
    """Rule-based hard-metric observations from the real tool responses.

    Only what a response really shows is observed (contract §6).  A counter this
    run cannot witness -- for example the detection *order*, which needs the
    attach-layer trace, or a per-entry provenance field absent from every
    response -- stays ``None``: unobserved, never a fabricated zero.
    """
    metrics = {**dict.fromkeys(ZERO_SAFETY_KEYS, None), **dict.fromkeys(FULL_INTEGRITY_KEYS, None)}
    responses = [observation.raw for observation in observations.values() if observation.raw]
    if not responses:
        return metrics
    schema_ok = 0
    evidence_total = evidence_locatable = 0
    memory_total = memory_provenance = memory_evidence_locators = quarantined = 0
    cross_scope = 0
    scope_seen = False
    for response in responses:
        if not isinstance(response, dict):
            continue
        schema_ok += int('completion_status' in response)
        if 'completion_status' not in response:
            continue
        for entry in response.get('evidence') or ():
            evidence_total += 1
            evidence_locatable += int(all(entry.get(key) is not None for key in
                                          ('source_id', 'source_version', 'source_position')))
        scope = response.get('scope') or {}
        scope_slug = scope.get('slug') if isinstance(scope, dict) else None
        for entry in response.get('related_memories') or ():
            memory_total += 1
            memory_provenance += int(bool(entry.get('provenance')))
            memory_evidence_locators += int(entry.get('source_position') is not None
                                            or entry.get('source_version') is not None)
            quarantined += int(entry.get('status') not in (None, 'active'))
            if scope_slug is not None:
                scope_seen = True
                cross_scope += int(entry.get('scope_slug') not in (None, scope_slug))
    metrics['mcp_schema_validity_rate'] = schema_ok / len(responses)
    if evidence_total:
        metrics['evidence_source_locatable_rate'] = evidence_locatable / evidence_total
    if memory_total:
        metrics['memory_provenance_complete_rate'] = memory_provenance / memory_total
        metrics['memory_entries_with_evidence_locators'] = memory_evidence_locators
        metrics['quarantined_memory_inputs'] = quarantined
    if scope_seen:
        metrics['cross_domain_leaks'] = cross_scope
    return metrics


def recorded_responses(observations: dict) -> dict:
    """The record round's normalized arm outcomes, keyed for the replay audit."""
    return {f'{arm}:{query_id}': observation.normalized()
            for (_round, arm, query_id), observation in observations.items()}


def replay_comparison(manifest: dict, observations: dict, query_ids: list) -> dict:
    """Compare the sealed record outcomes with this replay round's outcomes.

    Both arms and both outcome kinds are compared; a replayed failure must replay
    as the same failure.  The auxiliary drift is the worst relative change of the
    delivered-item count (a non-latency measurement).
    """
    recorded = manifest.get('responses') or {}
    matched, compared, mismatched, drift = 0, 0, [], None
    for query_id in query_ids:
        for arm in ARMS:
            before = recorded.get(f'{arm}:{query_id}')
            after = observations.get(('replay', arm, query_id))
            if before is None or after is None:
                continue
            compared += 1
            now = after.normalized()
            if before == now:
                matched += 1
            else:
                mismatched.append(f'{arm}:{query_id}')
            baseline = max(int(before.get('delivered') or 0), 1)
            change = abs(int(now.get('delivered') or 0) - int(before.get('delivered') or 0)) / baseline
            drift = change if drift is None else max(drift, change)
    return {'matched': matched, 'compared': compared, 'mismatched': mismatched,
            'response_match_rate': None if compared == 0 else matched / compared,
            'max_non_latency_relative_drift': drift}


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def _difference(without: dict, with_: dict) -> str:
    if with_['task_complete'] and without['task_complete']:
        return 'both arms complete the frozen task'
    if with_['task_complete']:
        missed = len(without['missing']) + len(without['uncited'])
        return (f"with_memory completes the frozen task; without_memory does not "
                f"({missed} required item(s) missing or uncited)")
    if without['task_complete']:
        return 'without_memory completes the frozen task; with_memory does not (regression)'
    return (f"neither arm completes: with_memory missing={len(with_['missing'])} "
            f"uncited={len(with_['uncited'])} forbidden={len(with_['forbidden'])}")


def build_report(*, dataset: dict, observations: dict, faces: dict, reproducibility_evidence: dict,
                 hard_metrics: dict, cache: dict, regression_evidence: dict | None = None,
                 evidence_paths=(), environment: dict | None = None, rounds=ROUNDS,
                 report_round: str = 'record', generated_at: str | None = None,
                 commit: str | None = None, default_configuration: dict | None = None) -> dict:
    """Assemble the frozen 014.1 report from observed arm outcomes and gates."""
    queries, failed_paths, baseline_violations = [], [], []
    if report_round not in rounds:
        raise ComparisonFailed(f'report round {report_round!r} is outside the frozen rounds {rounds}')
    for query in dataset['queries']:
        row = {'query_id': query['query_id'], 'category': query['category'],
               'language': query['language'], 'criterion': query['criterion'],
               'required_items': json.loads(json.dumps(query['required_items'])),
               'forbidden_items': json.loads(json.dumps(query['forbidden_items']))}
        for arm in ARMS:
            observation = observations.get((report_round, arm, query['query_id']))
            if observation is None:
                failed_paths.append(f"{arm}:{query['query_id']}")
                block = {'task_complete': False, 'hit': [], 'missing': [], 'uncited': [],
                         'forbidden': [], 'citation_required': [], 'delivered': [],
                         'latency_ms': None, 'cost_usd': None, 'error': 'NO_OBSERVATION'}
            else:
                if observation.error:
                    failed_paths.append(f"{arm}:{query['query_id']}")
                verdict = task_complete(query, observation)
                block = {**verdict, 'delivered': list(observation.delivered),
                         'latency_ms': observation.latency_ms, 'cost_usd': observation.cost_usd,
                         'error': observation.error}
                if arm == 'without_memory' and observation.baseline_new_fields:
                    baseline_violations.append(
                        {'query_id': query['query_id'],
                         'fields': list(observation.baseline_new_fields)})
            row[arm] = block
        row['difference'] = _difference(row['without_memory'], row['with_memory'])
        queries.append(row)

    without_rate = completion_rate([row['without_memory']['task_complete'] for row in queries])
    with_rate = completion_rate([row['with_memory']['task_complete'] for row in queries])
    aggregates = {
        'without_memory': {'completed': sum(1 for row in queries if row['without_memory']['task_complete']),
                           'queries': len(queries), 'completion_rate': without_rate},
        'with_memory': {'completed': sum(1 for row in queries if row['with_memory']['task_complete']),
                        'queries': len(queries), 'completion_rate': with_rate},
    }
    gain = relative_gain(without_rate, with_rate)
    explicit = explicit_criterion_check(
        [{'category': row['category'], 'task_complete': row['with_memory']['task_complete']}
         for row in queries], dataset['explicit_criterion'])
    quality, quality_reasons = quality_gate(gain=gain, explicit=explicit)

    match = reproducibility_evidence.get('response_match_rate')
    drift = reproducibility_evidence.get('max_non_latency_relative_drift')
    replay_calls = reproducibility_evidence.get('replay_real_network_calls', 0)
    evidence_complete = bool(reproducibility_evidence.get('evidence_complete'))
    reproducibility = {
        'status': reproducibility_status(
            response_match_rate=match, max_non_latency_relative_drift=drift,
            replay_real_network_calls=replay_calls, evidence_complete=evidence_complete),
        'non_latency_relative_tolerance': NON_LATENCY_TOLERANCE,
        'max_non_latency_relative_drift': drift, 'response_match_rate': match,
        'record_real_network_calls': reproducibility_evidence.get('record_real_network_calls'),
        'replay_real_network_calls': replay_calls, 'evidence_complete': evidence_complete,
    }
    safety, safety_reasons = safety_gate(hard_metrics)
    regression, regression_reasons = regression_gate(
        reproducibility=reproducibility, cache=cache, regression_evidence=regression_evidence)

    measured_failure = (not quality['quality_met'] or safety['violations'] > 0
                        or reproducibility['status'] == 'failed'
                        or cache.get('replay_real_network_calls', 0) != 0)
    if baseline_violations:
        # A baseline response carrying 014-only fields breaks the single-variable
        # contract: that is a measured failure, never an "incomplete evidence" excuse.
        status = 'failed'
    elif failed_paths:
        status = 'incomplete'
    elif measured_failure:
        status = 'failed'
    elif (reproducibility['status'] != 'passed' or not safety['all_required_observed']
          or not regression['evidence_complete']):
        status = 'incomplete'
    else:
        status = 'passed'
    eligible = default_enable_eligible(quality=quality, safety=safety, regression=regression,
                                       reproducibility=reproducibility)
    if status == 'passed' and not eligible:  # pragma: no cover - defensive, mirrors validate_report
        status = 'incomplete'
    if eligible and status != 'passed':  # pragma: no cover - defensive
        eligible = False

    criteria = {'relative_gain_threshold': RELATIVE_GAIN_THRESHOLD,
                'relative_gain_value': gain['value'],
                'relative_gain_threshold_met': quality['relative_gain_threshold_met'],
                'explicit_criterion': json.loads(json.dumps(dataset['explicit_criterion'])),
                'explicit_criterion_met': quality['explicit_criterion_met'],
                'explicit_criterion_source': 'dataset.explicit_criterion (frozen before the run)',
                'quality_met': quality['quality_met'], 'reasons': quality_reasons}
    zero_baseline = {'is_zero': gain['zero_baseline'], 'code': gain['code'],
                     'without_memory_completion_rate': without_rate}
    environment_block = {
        'host': platform.node(), 'python': platform.python_version(),
        'database': 'isolated 2 arms x 2 rounds (one database per identity)',
        'qdrant': 'isolated 2 arms x 2 rounds (one private store per identity)',
        'data_root': 'isolated 2 arms x 2 rounds (one private root per identity)',
        'dataset_path': faces.get('dataset', {}).get('path'),
        'dataset_hash': faces.get('dataset', {}).get('sha256'),
        'snapshot_hash': dataset['snapshot_hash'], 'model': dataset['frozen']['model'],
        'frozen': json.loads(json.dumps(dataset['frozen'])),
        'restoration_receipts': faces.get('restoration_receipts'),
    }
    environment_block.update(environment or {})
    environment_block['baseline_new_fields'] = baseline_violations

    gates = {
        'quality': {'status': 'passed' if quality['quality_met'] else 'failed',
                    'checks': quality, 'reasons': quality_reasons,
                    'evidence': [f"dataset:{faces.get('dataset', {}).get('sha256')}",
                                 f"rounds:{len(rounds)}"]},
        'safety': {'status': ('passed' if safety['all_required_observed'] and safety['violations'] == 0
                              else 'failed' if safety['violations'] else 'incomplete'),
                   'checks': safety, 'reasons': safety_reasons,
                   'evidence': ['observed:' + (','.join(sorted(
                       key for key, value in (hard_metrics or {}).items() if value is not None)) or 'none')]},
        'regression': {'status': ('passed' if regression['regression_met']
                                  else 'failed' if regression['reproducibility_passed'] is False
                                  and regression['evidence_complete'] else 'incomplete'),
                       'checks': regression, 'reasons': regression_reasons,
                       'evidence': [str(path) for path in evidence_paths]},
    }
    return encode_report(
        dataset=dataset, generated_at=generated_at or datetime.now(UTC).isoformat(),
        commit=commit or _head_sha(), status=status, environment=environment_block,
        queries=queries, aggregates=aggregates, relative_gain=gain, zero_baseline=zero_baseline,
        criteria=criteria, redundancy=redundancy(
            [locator for row in queries for locator in row['with_memory']['delivered']]),
        reproducibility=reproducibility, hard_metrics=json.loads(json.dumps(hard_metrics)),
        cache=cache, gates=gates, default_enable_eligible=eligible,
        evidence_paths=list(evidence_paths), failed_paths=list(dict.fromkeys(failed_paths)),
        default_configuration=json.loads(json.dumps(default_configuration or DEFAULT_CONFIGURATION)))


# ---------------------------------------------------------------------------
# Preflight and CLI
# ---------------------------------------------------------------------------

def _sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _head_sha() -> str:
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        return '0' * 40


def _write_json(path, payload: dict, *, exclusive: bool = True) -> str:
    """Write UTF-8 JSON explicitly (Windows cp936 consoles must never see it)."""
    raw = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + '\n').encode('utf-8')
    path = Path(path)
    if path.exists():
        if exclusive and path.read_bytes() != raw:
            raise ComparisonFailed(f'refusing to overwrite {path} with different bytes')
        return hashlib.sha256(raw).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def check_preflight(args: argparse.Namespace) -> dict:
    """Validate every input, version, identity and uniqueness rule before running."""
    dataset = load_dataset(args.dataset)
    validate_dataset(dataset)
    faces = {'dataset': {'path': str(args.dataset), 'sha256': _sha256_file(args.dataset),
                         'queries': len(dataset['queries']),
                         'dataset_version': dataset['dataset_version'],
                         'snapshot_hash': dataset['snapshot_hash'], 'k': dataset['k']}}
    if args.output is not None and Path(args.output).exists():
        raise PreflightIncomplete(f'output already exists: {args.output}')
    cache_dir = Path(args.cache_dir) if args.cache_dir else Path(str(args.cache_manifest) + '.cache')
    if args.mode == 'record':
        if Path(args.cache_manifest).exists():
            raise PreflightIncomplete(f'cache manifest already exists: {args.cache_manifest}')
    else:
        manifest = ToolCallCache.load_manifest(args.cache_manifest)
        audit = ToolCallCache(cache_dir, mode='replay').audit(
            [row['key'] for row in manifest.get('entries', [])])
        if not audit['evidence_complete']:
            raise PreflightIncomplete(
                f'cache evidence incomplete: missing={audit["missing"]} corrupt={audit["corrupt"]} '
                f'version_mismatch={audit["version_mismatch"]} matched={audit["matched"]}/'
                f'{audit["expected_keys"]}')
        faces['cache_manifest'] = {'path': str(args.cache_manifest),
                                   'sha256': _sha256_file(args.cache_manifest),
                                   'expected_keys': audit['expected_keys']}
    if args.snapshot is not None:
        snapshot_path = Path(args.snapshot)
        if not snapshot_path.is_file():
            raise PreflightIncomplete(f'authority snapshot missing: {snapshot_path}')
        snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
        if str(snapshot.get('scope_id')) != dataset['scope_id']:
            raise PreflightIncomplete('authority snapshot scope does not match the frozen dataset')
        if snapshot.get('snapshot_hash') not in (None, dataset['snapshot_hash']):
            raise PreflightIncomplete('authority snapshot digest does not match the frozen dataset')
        faces['snapshot'] = {'path': str(snapshot_path), 'sha256': _sha256_file(snapshot_path),
                             'snapshot_hash': dataset['snapshot_hash']}
    elif args.capsule_dir is not None:
        capsule_path = Path(args.capsule_dir) / 'capsule.json'
        if not capsule_path.is_file():
            raise PreflightIncomplete(f'sealed capsule missing: {capsule_path}')
        capsule = json.loads(capsule_path.read_text(encoding='utf-8'))
        if dataset['scope_id'] not in [str(scope) for scope in capsule.get('scopes', [])]:
            raise PreflightIncomplete('sealed capsule does not contain the frozen scope')
        faces['capsule'] = {'path': str(args.capsule_dir), 'sha256': _sha256_file(capsule_path),
                            'authority_digest': (capsule.get('authority') or {}).get('authority_digest')}
    else:
        raise PreflightIncomplete(
            'incomplete evidence: either --snapshot or --capsule-dir is required to prove the '
            'frozen input snapshot before any arm runs')
    faces['cache_dir'] = str(cache_dir)
    return {'dataset': dataset, 'faces': faces, 'cache_dir': cache_dir}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='014 memory-continuity comparison runner (record/replay)',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dataset', type=Path, required=True,
                        help='frozen 014 continuity dataset (eval/memory_continuity_eval_dataset.json)')
    parser.add_argument('--mode', choices=('record', 'replay'), required=True)
    parser.add_argument('--cache-manifest', type=Path, required=True,
                        help='sealed sidecar manifest (created by record, required by replay)')
    parser.add_argument('--output', type=Path, required=True, help='unique report path; never overwritten')
    parser.add_argument('--run-id', help='alphanumeric token for a fresh 2x2 identity allocation')
    parser.add_argument('--run', type=Path, help='restoration identity file; allocate one when omitted')
    parser.add_argument('--run-out', type=Path,
                        help='where a fresh allocation is persisted for the replay invocation '
                             '(default: <evidence-dir>/identities.json)')
    parser.add_argument('--base', type=Path, default=Path('C:/t014c'),
                        help='short restoration base for a fresh allocation')
    parser.add_argument('--capsule-dir', type=Path, help='sealed capsule of the frozen snapshot')
    parser.add_argument('--snapshot', type=Path, help='read-only authority snapshot of the frozen scope')
    parser.add_argument('--qdrant-port-base', type=int, default=18900)
    parser.add_argument('--cache-dir', type=Path, help='record/replay cache root')
    parser.add_argument('--evidence-dir', type=Path, help='directory for out-of-band run artifacts')
    parser.add_argument('--regression', type=Path, action='append', default=[],
                        help='011/012/013 regression summary report (repeatable)')
    parser.add_argument('--delivered-ttl-seconds', type=int, default=3600,
                        help='approved delivered-set window (7 days -> 3600 s), recorded as evidence')
    parser.add_argument('--commit', help='report commit; defaults to HEAD')
    parser.add_argument('--print-preflight', action='store_true',
                        help='print the validated inputs and stop')
    return parser


async def execute(args: argparse.Namespace) -> int:  # pragma: no cover - needs live services
    """The real record/replay run (T058).  Needs PostgreSQL, Qdrant and the MCP tools."""
    from consolidation_restore_support import load_run, save_run

    preflight = check_preflight(args)
    dataset = preflight['dataset']
    faces = dict(preflight['faces'])
    if args.print_preflight:
        print(json.dumps({'status': 'preflight_ok', 'faces': faces}, indent=2, ensure_ascii=False))
        return EXIT_INCOMPLETE
    if args.run is not None:
        run = load_run(Path(args.run))
    elif args.run_id:
        run = allocate_identities(args.run_id, base=args.base, qdrant_port_base=args.qdrant_port_base)
    else:
        raise PreflightIncomplete('either --run or --run-id is required to allocate the 2x2 identities')
    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else Path(str(args.output) + '.run')
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if args.run is None:
        # The replay round is a separate invocation; its identities must be the
        # very same four restorations, so the allocation is persisted here.
        run_out = Path(args.run_out) if args.run_out else evidence_dir / 'identities.json'
        save_run(run, run_out)
        faces['identities'] = {'path': str(run_out), 'sha256': _sha256_file(run_out)}
    if args.capsule_dir is not None:
        faces['restoration_receipts'] = [ensure_identity(Path(args.capsule_dir), identity)
                                         for identity in run.identities]
        # The capsule is a consolidation capsule: it carries the memory dense
        # collection but not the evidence index.  Rebuild that derived index in
        # each identity from the restored published chunks before any arm runs.
        faces['evidence_index_rebuilds'] = {
            identity.label: await rebuild_identity_evidence_index(
                identity, scope_id=int(dataset['scope_id']))
            for identity in run.identities
        }
    cache_dir = Path(preflight['cache_dir'])
    scope_ref = dataset['source'].get('scope_slug') or dataset['scope_id']
    observations = {}
    if args.mode == 'record':
        cache = ToolCallCache(cache_dir, mode='record')
        for identity in [item for item in run.identities if item.round == 'record']:
            observations.update(await run_arm(identity, dataset=dataset, cache=cache,
                                              round_name='record', scope_ref=scope_ref))
        manifest = cache.seal(args.cache_manifest, dataset_hash=faces['dataset']['sha256'],
                              snapshot_hash=dataset['snapshot_hash'],
                              model_version=dataset['frozen']['model'],
                              responses=recorded_responses(observations),
                              hard_metrics=observe_hard_metrics(observations))
    else:
        manifest = ToolCallCache.load_manifest(args.cache_manifest)
    replay_cache = ToolCallCache(cache_dir, mode='replay')
    for identity in [item for item in run.identities if item.round == 'replay']:
        observations.update(await run_arm(identity, dataset=dataset, cache=replay_cache,
                                          round_name='replay', scope_ref=scope_ref))
    keys = [row['key'] for row in manifest.get('entries', [])]
    audit = replay_cache.audit(keys)
    audit['real_calls'] = replay_cache.real_calls
    query_ids = [query['query_id'] for query in dataset['queries']]
    if args.mode == 'replay':
        comparison = replay_comparison(manifest, observations, query_ids)
        evidence_complete = bool(audit['evidence_complete'] and replay_cache.real_calls == 0
                                 and comparison['compared'] == len(query_ids) * len(ARMS))
    else:
        # A single record round cannot claim a reproduction: the replayed round is
        # a separate sealed invocation, so the reproduction evidence stays open.
        comparison = {'response_match_rate': None, 'max_non_latency_relative_drift': None,
                      'mismatched': [], 'matched': 0, 'compared': 0}
        evidence_complete = False
    reproducibility_evidence = {
        'response_match_rate': comparison['response_match_rate'],
        'max_non_latency_relative_drift': comparison['max_non_latency_relative_drift'],
        'record_real_network_calls': manifest.get('expected_keys'),
        'replay_real_network_calls': replay_cache.real_calls,
        'evidence_complete': evidence_complete,
    }
    report = build_report(
        dataset=dataset, observations=observations, faces=faces,
        reproducibility_evidence=reproducibility_evidence,
        hard_metrics=observe_hard_metrics(observations),
        cache={**audit, 'path': str(cache_dir), 'manifest_hash': _sha256_file(args.cache_manifest),
               'response_match_rate': comparison['response_match_rate'],
               'record_real_network_calls': manifest.get('expected_keys', 0)},
        regression_evidence={'legacy_contract': [str(path) for path in args.regression],
                             'delivered_ttl_seconds': args.delivered_ttl_seconds},
        evidence_paths=[str(args.dataset), str(args.cache_manifest)] + [str(path) for path in args.regression],
        report_round=args.mode, commit=args.commit)
    validate_comparison_report(report, evidence={'cache': str(args.cache_manifest),
                                                 'restoration': faces.get('restoration_receipts')})
    _write_json(args.output, report)
    # Per-round summary: the record and replay rounds share one evidence dir.
    _write_json(evidence_dir / f'run-summary-{args.mode}.json',
                {'report': str(args.output), 'status': report['status'], 'mode': args.mode,
                 'replay_comparison': comparison, 'mismatched': comparison['mismatched'],
                 'restoration': faces.get('restoration_receipts')})
    print(json.dumps({'status': report['status'],
                      'default_enable_eligible': report['default_enable_eligible'],
                      'relative_gain': report['relative_gain'], 'output': str(args.output)},
                     indent=2, ensure_ascii=False, default=str))
    return exit_code_for(report['status'])


def _safe_report(args: argparse.Namespace, status: str, reason: str) -> None:
    """Best-effort preflight/incomplete artifact; never overwrites different bytes."""
    output = getattr(args, 'output', None)
    if output is None or Path(output).exists():
        return
    with contextlib.suppress(Exception):
        _write_json(output, {'schema_version': REPORT_VERSION, 'report_type': REPORT_TYPE,
                             'generated_at': datetime.now(UTC).isoformat(), 'status': status,
                             'reason': reason, 'mode': getattr(args, 'mode', None)})


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except (PreflightIncomplete, DatasetInvalid, CacheIncomplete) as error:
        _safe_report(args, 'incomplete', str(error))
        print(json.dumps({'status': 'incomplete', 'reason': str(error)}, indent=2, ensure_ascii=False))
        return EXIT_INCOMPLETE
    except ComparisonFailed as error:
        _safe_report(args, 'failed', str(error))
        print(json.dumps({'status': 'failed', 'reason': str(error)}, indent=2, ensure_ascii=False))
        return EXIT_FAILED


if __name__ == '__main__':
    raise SystemExit(main())
