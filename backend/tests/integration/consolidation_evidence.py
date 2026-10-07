"""T094: real 013 acceptance-evidence observation and exclusive export.

The fixture records what the real isolated integration tests actually observed
(test nodeid, scenario, scope/run/eligibility identity, event and memory ids,
manifest cutoff, hard checks and the real LLM transport trace) and writes it,
plus a reconstructable authority snapshot and a frozen environment manifest,
under ``CONSOLIDATION_EVIDENCE_DIR``.

Caliber follows the existing 012 observer ``eval/memory_pytest_evidence.py``:
scenario/scope ids/request ids/fingerprints/paths with real elapsed time. The
012 observer and its old evidence are not modified.

Discipline:

* export only ever creates new files (``x`` mode); an existing file with
  different bytes is refused, never overwritten;
* every record is sanitized with the shared ``sanitize_consolidation_audit``
  (same-scope only, credentials redacted, unsafe/raw bodies withheld);
* an unobserved hard count stays ``null`` - it is never fabricated as ``0``;
* a conflict between two observed values of the same hard check is exported as
  a conflict and never silently resolved.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter

TRACE_NAME = 'consolidation-trace.json'
SNAPSHOT_NAME = 'authority-snapshot.json'
MANIFEST_NAME = 'dataset-manifest.json'
EVIDENCE_VERSION = '013.evidence.1'
METRIC_TRACE_VERSION = '013.trace.1'
HARD_ZERO_CHECKS = ('cross_scope_leaks', 'quarantined_inputs', 'soft_overturns_hard',
                    'automatic_promotions', 'invalid_outputs_applied', 'stale_holder_commits',
                    'incomplete_outputs_consumed', 'rebuild_llm_calls')
HARD_ONE_CHECKS = ('source_chain_complete_rate', 'schema_validity_rate', 'projection_integrity_rate')
HARD_CHECKS = (*HARD_ZERO_CHECKS, *HARD_ONE_CHECKS)


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _sanitized(record):
    from rag_mcp.services.memory_validators import sanitize_consolidation_audit

    scope = record.get('scope_id') or record.get('knowledge_scope_id') or 0
    try:
        return _jsonable(sanitize_consolidation_audit(_jsonable(record), scope_id=scope))
    except (TypeError, ValueError):
        return {'scenario': record.get('scenario'), 'redaction': 'unavailable'}


class EvidenceObserver:
    """Per-test recorder; always available, exported only when a bundle exists."""

    def __init__(self, bundle, nodeid):
        self.bundle = bundle
        self.nodeid = nodeid
        self.entries = []

    def record(self, scenario, **fields):
        entry = _sanitized({'scenario': scenario, 'nodeid': self.nodeid, **fields})
        self.entries.append(entry)
        if self.bundle is not None:
            self.bundle.add_record(self.nodeid, entry)
        return entry

    def last(self, scenario):
        for entry in reversed(self.entries):
            if entry['scenario'] == scenario:
                return entry
        return None

    def check(self, name, passed):
        if name not in HARD_CHECKS:
            raise ValueError(f'unknown 013 hard check {name!r}')
        if self.bundle is not None:
            self.bundle.add_check(self.nodeid, name, passed)
        return passed

    async def capture_authority(self, session, scope_id):
        material = await capture_authority(session, scope_id)
        self.record('authority_snapshot', scope_id=str(scope_id), cutoff=material['cutoff'],
                    event_count=len(material['source_events']),
                    published_evidence_count=len(material['published_evidence']),
                    projection_fingerprints=material['projection_fingerprints'])
        if self.bundle is not None:
            self.bundle.add_snapshot(str(scope_id), material)
        return material


class EvidenceBundle:
    """Session-scoped collector; every export refuses to overwrite other bytes."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.started_at = datetime.now(UTC).isoformat()
        self.records: dict[str, list] = {}
        self.checks: dict[str, dict] = {}
        self.memory_calls: list = []
        self.snapshots: dict[str, dict] = {}
        self.finalized = False

    def add_record(self, nodeid, entry):
        self.records.setdefault(nodeid, []).append(entry)

    def add_check(self, nodeid, name, passed):
        # A boolean observation is exported as its numeric 0/1 so the manifest
        # stays a real count/rate instead of a JSON boolean.
        value = int(passed) if isinstance(passed, bool) else passed
        self.checks.setdefault(name, {}).setdefault(nodeid, []).append(value)

    def add_memory_call(self, nodeid, call):
        self.memory_calls.append(_sanitized({'nodeid': nodeid, **call}))

    def add_snapshot(self, scope_id, material):
        self.snapshots[scope_id] = material

    def hard_counts(self):
        counts, conflicts = {}, {}
        for name in HARD_CHECKS:
            observations = [value for values in self.checks.get(name, {}).values() for value in values]
            if not observations:
                counts[name] = None
                continue
            if len(set(observations)) != 1:
                counts[name] = None
                conflicts[name] = observations
                continue
            counts[name] = observations[0]
        return counts, conflicts

    def _trace_document(self, exitstatus):
        counts, conflicts = self.hard_counts()
        return {
            'evidence_version': EVIDENCE_VERSION,
            'metric_trace_version': METRIC_TRACE_VERSION,
            'generated_at': datetime.now(UTC).isoformat(),
            'started_at': self.started_at,
            'exitstatus': int(exitstatus),
            'hard_counts': counts,
            'hard_count_conflicts': conflicts,
            'tests': [{'nodeid': nodeid, 'records': entries} for nodeid, entries in self.records.items()],
            'checks': self.checks,
            'memory_calls': self.memory_calls,
        }

    def _snapshot_document(self):
        scopes = {}
        for scope_id, material in self.snapshots.items():
            body = {key: value for key, value in material.items() if key != 'snapshot_sha256'}
            scopes[scope_id] = {**body, 'snapshot_sha256': material['snapshot_sha256']}
        return {'snapshot_version': EVIDENCE_VERSION, 'generated_at': datetime.now(UTC).isoformat(),
                'scope_count': len(scopes), 'scopes': scopes}

    def _manifest_document(self, exitstatus):
        counts, conflicts = self.hard_counts()
        dataset_path = _env('CONSOLIDATION_DATASET_PATH')
        dataset_hash = (sha256(Path(dataset_path).read_bytes()).hexdigest()
                        if dataset_path and Path(dataset_path).is_file() else None)
        return {
            'manifest_version': EVIDENCE_VERSION,
            'generated_at': datetime.now(UTC).isoformat(),
            'exitstatus': int(exitstatus),
            'k': 5,
            'metric_trace_version': METRIC_TRACE_VERSION,
            'frozen_clock': _env('CONSOLIDATION_FROZEN_CLOCK'),
            'dataset_path': dataset_path,
            'dataset_sha256': dataset_hash,
            'scope_ids': sorted(self.snapshots),
            'authority_snapshot_sha256': {scope_id: material['snapshot_sha256']
                                          for scope_id, material in self.snapshots.items()},
            'hard_counts': counts,
            'hard_count_conflicts': conflicts,
            'observed_hard_checks': sorted(name for name, value in counts.items() if value is not None),
            'unobserved_hard_checks': sorted(name for name, value in counts.items() if value is None),
            'default_configuration': {'consolidation_enabled': False, 'link_expansion_enabled': False,
                                      'policy_published': False},
        }

    @staticmethod
    def _write(path: Path, document):
        raw = json.dumps(document, ensure_ascii=True, sort_keys=True, indent=2).encode('utf-8')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != raw:
                raise RuntimeError(f'consolidation evidence exists with different content: {path}')
            return sha256(raw).hexdigest()
        with path.open('xb') as stream:
            stream.write(raw)
        return sha256(raw).hexdigest()

    def finalize(self, exitstatus):
        if self.finalized:
            return
        self.finalized = True
        self._write(self.directory / TRACE_NAME, self._trace_document(exitstatus))
        self._write(self.directory / SNAPSHOT_NAME, self._snapshot_document())
        self._write(self.directory / MANIFEST_NAME, self._manifest_document(exitstatus))


def _env(name):
    import os

    return os.environ.get(name) or None


async def capture_authority(session, scope_id):
    """Real authority material for one scope: events, published evidence, policy.

    Everything is read through the existing read-only services; the projection
    manifest supplies the verified cutoff and the six logical fingerprints. The
    returned material is what a future T097 restoration must reproduce.
    """
    from sqlalchemy import select

    from rag_mcp.models.chunk import Chunk
    from rag_mcp.models.domain_profile import DomainProfile
    from rag_mcp.models.knowledge_scope import KnowledgeScope
    from rag_mcp.models.knowledge_source import KnowledgeSource
    from rag_mcp.models.knowledge_version import KnowledgeVersion
    from rag_mcp.services.memory_event_store import MemoryEventStore
    from rag_mcp.services.memory_projection_store import MemoryProjectionStore

    await session.rollback()
    scope = await session.get(KnowledgeScope, scope_id, populate_existing=True)
    if scope is None:
        raise ValueError('MISSING_KNOWLEDGE_SCOPE')
    profile = await session.get(DomainProfile, scope.domain_key, populate_existing=True)
    events = await MemoryEventStore(session).replay(scope_id)
    manifest = await MemoryProjectionStore(session).current(scope_id)
    rows = (await session.execute(select(Chunk, KnowledgeVersion, KnowledgeSource)
            .join(KnowledgeVersion, Chunk.version_id == KnowledgeVersion.version_id)
            .join(KnowledgeSource, Chunk.source_id == KnowledgeSource.source_id)
            .where(Chunk.knowledge_scope_id == scope_id,
                   KnowledgeVersion.status == 'published'))).all()
    published = sorted(({'chunk_id': str(chunk.chunk_id), 'source_id': str(source.source_id),
                         'version_id': str(version.version_id), 'version_number': version.version_number,
                         'position_path': chunk.position_path, 'content_text': chunk.content_text,
                         'content_hash': sha256(chunk.content_text.encode()).hexdigest(),
                         'chunk_type': chunk.chunk_type, 'embedding_model': chunk.embedding_model,
                         'index_version': chunk.index_version, 'source_status': source.status,
                         'source_filename': source.filename,
                         'source_content_hash': source.content_hash}
                        for chunk, version, source in rows), key=lambda row: int(row['chunk_id']))
    fingerprints = {}
    memory_ids = []
    if manifest is not None:
        raw = (manifest.payload or {}).get('fingerprints') or {}
        fingerprints = {name: (value if isinstance(value, str)
                               else value.get('fingerprint') if isinstance(value, dict) else None)
                        for name, value in raw.items()}
        fingerprints = {name: value for name, value in fingerprints.items() if value}
        if not fingerprints:
            fingerprints = {'state': manifest.fingerprint}
        entries = ((manifest.payload or {}).get('state') or {}).get('entries') or {}
        memory_ids = sorted((str(identifier) for identifier in entries), key=int)
    material = {
        'scope_id': str(scope_id),
        'scope': {'scope_type': scope.scope_type, 'slug': scope.slug,
                  'domain_key': scope.domain_key, 'status': scope.status},
        'profile': {'domain_key': profile.domain_key, 'name': profile.name,
                    'description': profile.description,
                    'memory_policy': _jsonable(profile.memory_policy or {}),
                    'memory_link_vocabulary': _jsonable(profile.memory_link_vocabulary or []),
                    'is_builtin': bool(profile.is_builtin)},
        'source_events': _jsonable(events),
        'source_event_ids': [str(event['event_id']) for event in events],
        'published_evidence': published,
        'cutoff': int(manifest.source_event_id) if manifest is not None else 0,
        'manifest_fingerprint': manifest.fingerprint if manifest is not None else None,
        'projection_fingerprints': fingerprints,
        'memory_ids': memory_ids,
        'data_root': _env('DATA_ROOT'),
        'captured_at': datetime.now(UTC).isoformat(),
    }
    material['snapshot_sha256'] = sha256(json.dumps(
        {key: value for key, value in material.items() if key != 'captured_at'},
        ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    await session.rollback()
    frozen = _env('CONSOLIDATION_FROZEN_CLOCK')
    if frozen:
        material['frozen_clock'] = frozen
    return material


def instrument(monkeypatch, observer):
    """Observe the real memory services with the 012 observer caliber.

    Only the observation is added: the wrapped call is the production method and
    its result is returned unchanged, so no test outcome depends on this.
    """
    from rag_mcp.services.memory_event_store import MemoryEventStore
    from rag_mcp.services.memory_projection_store import MemoryProjectionStore
    from rag_mcp.services.memory_service import MemoryService

    def observe(operation, parameters, result, elapsed):
        record = {'elapsed_seconds': round(elapsed, 6),
                  'request_ids': [str(result['request_id'])] if isinstance(result, dict)
                  and result.get('request_id') else []}
        scope = parameters.get('scope_id')
        if scope is not None:
            record['scope_id'] = str(scope)
        if isinstance(result, dict):
            record['status'] = result.get('completion_status', result.get('status', 'returned'))
            if 'counts' in result:
                record['counts'] = result['counts']
            if 'memories' in result:
                record['memory_ids'] = [str(row['memory_id']) for row in result['memories']]
        return record

    for name in ('record', 'recall', 'govern'):
        original = getattr(MemoryService, name)

        async def wrapped(self, *args, __original=original, __name=name, **kwargs):
            parameters = dict(args[0]) if args and isinstance(args[0], dict) else dict(kwargs)
            if __name == 'govern' and args:
                parameters['action'] = args[0]
            start = perf_counter()
            result = await __original(self, *args, **kwargs)
            observer.record('memory_' + __name, **observe(__name, parameters, result,
                                                          perf_counter() - start))
            return result

        monkeypatch.setattr(MemoryService, name, wrapped)

    original_inspect = MemoryProjectionStore.inspect

    async def inspected(self, state, scope_id):
        result = await original_inspect(self, state, scope_id)
        observer.record('six_projection_integrity', scope_id=str(scope_id),
                        status='passed' if all(row['matches_replay'] for row in result.values()) else 'failed',
                        failed_paths=[name for name, row in result.items() if not row['matches_replay']])
        return result

    monkeypatch.setattr(MemoryProjectionStore, 'inspect', inspected)

    original_replay = MemoryEventStore.replay

    async def replayed(self, scope_id, **kwargs):
        events = await original_replay(self, scope_id, **kwargs)
        observer.record('event_log', scope_id=str(scope_id), status='observed',
                        event_ids=[str(event['event_id']) for event in events])
        return events

    monkeypatch.setattr(MemoryEventStore, 'replay', replayed)
