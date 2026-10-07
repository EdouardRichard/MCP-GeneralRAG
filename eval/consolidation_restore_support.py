"""T097 isolated authority restoration support (pure helpers, no CLI).

Each ``(round, arm)`` of a consolidation comparison must start from its own
restoration of the *same* sealed original authority, with no resource shared
with another arm or round. This module owns that resource identity and the
native restoration primitives:

* a fresh PostgreSQL database per identity, created by a native
  ``CREATE DATABASE ... TEMPLATE`` copy of the sealed capsule (no live guarded
  application-table import, no trigger disabling, no replication-role bypass);
* a fresh Qdrant store per identity: a real ``qdrant.exe`` process with its own
  ``storage_path``/``snapshots_path`` and its own HTTP/gRPC ports;
* a private writable ``data_root`` copied byte-for-byte from the capsule with a
  SHA256 manifest, so no arm shares a writable volume with another arm or with
  the sealed capsule.

Nothing here writes to a source/original store: sealing only reads the source
authority, and every arm is materialised into newly allocated identities.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ISOLATED_DATABASE_PREFIX = 'memory_consolidation_013_'
CAPSULE_VERSION = '013.restore.1'
ARMS = ('baseline', 'consolidated_direct', 'consolidated_candidate_expansion')
ROUNDS = ('record', 'replay')
QDRANT_VERSION = '1.19.0'
QDRANT_DEFAULT_URL = 'http://127.0.0.1:16333'
# Qdrant appends deep segment/wal paths under the private storage root; Windows
# refuses the resulting path past MAX_PATH, so the private root must stay short.
MAX_PRIVATE_STORAGE_PATH = 80
DEFAULT_QDRANT_BINARY = Path(
    'C:/Users/Richard/AppData/Local/Codex/013-isolation-20261006/restore-tools/'
    f'qdrant-{QDRANT_VERSION}/qdrant.exe'
)

# Immutable original authority + published evidence. These rows must be
# byte-identical in every restoration; they are the frozen input, not control.
AUTHORITY_TABLES = (
    ('knowledge_scopes', 'scope_id'),
    ('knowledge_sources', 'knowledge_scope_id'),
    ('knowledge_versions', 'knowledge_scope_id'),
    ('chunks', 'knowledge_scope_id'),
    ('memory_events', 'knowledge_scope_id'),
    ('memory_entries', 'knowledge_scope_id'),
    ('memory_links', 'knowledge_scope_id'),
    ('memory_summary_nodes', 'knowledge_scope_id'),
    ('memory_projection_meta', 'knowledge_scope_id'),
    ('memory_snapshots', 'knowledge_scope_id'),
    ('memory_archives', 'knowledge_scope_id'),
    ('scope_bindings', 'knowledge_scope_id'),
    ('soft_relation', 'knowledge_scope_id'),
    ('graph_edge', 'knowledge_scope_id'),
    ('evidence_ledger_entry', 'knowledge_scope_id'),
)

# Legitimately renewed runtime control: copied by the native restore but never
# part of the frozen authority digest (receipts are transaction-bound, leases
# and eligibility expire on real DB time).
CONTROL_TABLES = (
    ('consolidation_eligibilities', 'knowledge_scope_id'),
    ('consolidation_runs', 'knowledge_scope_id'),
    ('memory_projection_receipts', 'knowledge_scope_id'),
    ('memory_management_audits', 'knowledge_scope_id'),
)


class RestoreError(RuntimeError):
    """The requested restoration is not executable or not faithful."""


@dataclass(frozen=True)
class Identity:
    """One independent restoration target: (round, arm) -> resources."""

    round: str
    arm: str
    database: str
    data_root: Path
    qdrant_url: str
    qdrant_storage: Path
    qdrant_http_port: int
    qdrant_grpc_port: int

    @property
    def label(self) -> str:
        return f'{self.round}-{self.arm}'

    def as_record(self) -> dict:
        return {
            'round': self.round, 'arm': self.arm, 'label': self.label,
            'database': self.database, 'data_root': str(self.data_root),
            'qdrant_url': self.qdrant_url, 'qdrant_storage': str(self.qdrant_storage),
            'qdrant_http_port': self.qdrant_http_port, 'qdrant_grpc_port': self.qdrant_grpc_port,
        }


@dataclass
class RunIdentity:
    """The six allocated identities of one record/replay comparison run."""

    run_id: str
    identities: list[Identity] = field(default_factory=list)

    def get(self, round: str, arm: str) -> Identity:
        for identity in self.identities:
            if identity.round == round and identity.arm == arm:
                return identity
        raise RestoreError(f'no identity for {round}/{arm}')


# ---------------------------------------------------------------------------
# PostgreSQL: native database copy into a new offline target
# ---------------------------------------------------------------------------

def _settings_sync_url() -> str:
    url = os.environ.get('DATABASE_URL_SYNC')
    if not url:
        raise RestoreError('DATABASE_URL_SYNC is not configured')
    return url


def admin_engine():
    """AUTOCOMMIT engine on the server's ``postgres`` maintenance database."""
    url = make_url(_settings_sync_url()).set(database='postgres')
    return create_engine(url.render_as_string(hide_password=False), isolation_level='AUTOCOMMIT')


def require_isolated_database(database: str) -> str:
    if not database.startswith(ISOLATED_DATABASE_PREFIX):
        raise RestoreError(f'database {database!r} lacks the isolated {ISOLATED_DATABASE_PREFIX!r} prefix')
    return database


def database_exists(database: str) -> bool:
    engine = admin_engine()
    try:
        with engine.connect() as connection:
            return connection.scalar(
                text('SELECT 1 FROM pg_database WHERE datname = :name'), {'name': database}
            ) is not None
    finally:
        engine.dispose()


def terminate_connections(database: str) -> int:
    """Close every session on one of our own disposable target databases."""
    require_isolated_database(database)
    engine = admin_engine()
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text('SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
                     'WHERE datname = :name AND pid <> pg_backend_pid()'),
                {'name': database},
            ).all()
            return sum(1 for row in rows if row[0])
    finally:
        engine.dispose()


def create_database(database: str, *, template: str | None = None) -> None:
    """Create a new isolated database, optionally as a native copy of ``template``."""
    require_isolated_database(database)
    if template is not None:
        require_isolated_database(template)
    engine = admin_engine()
    try:
        with engine.connect() as connection:
            if connection.scalar(text('SELECT 1 FROM pg_database WHERE datname = :name'),
                                 {'name': database}) is not None:
                raise RestoreError(f'database {database!r} already exists')
            if template is not None:
                busy = connection.scalar(
                    text('SELECT count(*) FROM pg_stat_activity WHERE datname = :name AND pid <> pg_backend_pid()'),
                    {'name': template},
                )
                if busy:
                    raise RestoreError(f'template database {template!r} still has {busy} live session(s)')
                connection.execute(text(f'CREATE DATABASE "{database}" TEMPLATE "{template}"'))
            else:
                connection.execute(text(f'CREATE DATABASE "{database}"'))
    finally:
        engine.dispose()


def drop_database(database: str) -> None:
    require_isolated_database(database)
    terminate_connections(database)
    engine = admin_engine()
    try:
        with engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
    finally:
        engine.dispose()


def database_size_bytes(database: str) -> int | None:
    require_isolated_database(database)
    url = make_url(_settings_sync_url()).set(database=database)
    engine = create_engine(url.render_as_string(hide_password=False))
    try:
        with engine.connect() as connection:
            return int(connection.scalar(text('SELECT pg_database_size(current_database())')))
    except Exception:  # noqa: BLE001 - an unreadable size stays unknown, never fabricated
        return None
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Private data roots: byte copy with a SHA256 manifest
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def tree_manifest(root: Path) -> list[dict]:
    """Deterministic relative-path/size/sha256 manifest of a directory."""
    root = Path(root)
    if not root.exists():
        return []
    rows = []
    for path in sorted(item for item in root.rglob('*') if item.is_file()):
        rows.append({'path': path.relative_to(root).as_posix(), 'size': path.stat().st_size,
                     'sha256': _sha256_file(path)})
    return rows


def tree_digest(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def copy_tree(source: Path, target: Path) -> list[dict]:
    """Copy ``source`` bytes into a private ``target`` root; return its manifest."""
    source, target = Path(source), Path(target)
    if not source.exists():
        raise RestoreError(f'source data root missing: {source}')
    if target.exists():
        raise RestoreError(f'target data root already exists: {target}')
    target.mkdir(parents=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    copied = tree_manifest(target)
    expected = tree_manifest(source)
    if copied != expected:
        raise RestoreError('copied data root does not match the source byte-for-byte')
    return copied


def scope_relative_paths(root: Path, scopes: list[int]) -> list[str]:
    """The private data-root subtrees a scope actually owns, if they exist."""
    root = Path(root)
    present = []
    for scope in scopes:
        for relative in (f'{scope}', f'memory_projection/{scope}', f'memory_projection/archives/{scope}'):
            if (root / relative).exists():
                present.append(relative)
    return present


def scoped_manifest(root: Path, scopes: list[int]) -> list[dict]:
    root = Path(root)
    rows = []
    for relative in scope_relative_paths(root, scopes):
        for row in tree_manifest(root / relative):
            rows.append({**row, 'path': f'{relative}/{row["path"]}'})
    return sorted(rows, key=lambda row: row['path'])


def copy_tree_scoped(source: Path, target: Path, scopes: list[int]) -> list[dict]:
    """Copy only the frozen scopes' private subtrees, preserving relative paths."""
    source, target = Path(source), Path(target)
    if not source.exists():
        raise RestoreError(f'source data root missing: {source}')
    if target.exists():
        raise RestoreError(f'target data root already exists: {target}')
    relative_paths = scope_relative_paths(source, scopes)
    if not relative_paths:
        raise RestoreError(f'no private material for scopes {list(scopes)} under {source}')
    target.mkdir(parents=True)
    for relative in relative_paths:
        shutil.copytree(source / relative, target / relative, dirs_exist_ok=True)
    copied = tree_manifest(target)
    expected = scoped_manifest(source, scopes)
    if copied != expected:
        raise RestoreError('copied scoped data root does not match the source byte-for-byte')
    return copied


def verify_tree(root: Path, manifest: list[dict]) -> None:
    if tree_manifest(root) != manifest:
        raise RestoreError(f'data root {root} does not match its frozen manifest')


# ---------------------------------------------------------------------------
# Qdrant: one real server process per identity, with private storage
# ---------------------------------------------------------------------------

def qdrant_binary() -> Path:
    configured = os.environ.get('CONSOLIDATION_QDRANT_BINARY')
    binary = Path(configured) if configured else DEFAULT_QDRANT_BINARY
    if not binary.exists():
        raise RestoreError(f'Qdrant server binary not provisioned at {binary}')
    return binary


def qdrant_healthy(url: str, timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip('/') + '/healthz', timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def free_port(start: int, end: int) -> int:
    for port in range(start, end):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                continue
            return port
    raise RestoreError(f'no free port in {start}-{end}')


def qdrant_config(storage: Path, http_port: int, grpc_port: int) -> dict:
    storage = Path(storage)
    return {
        'storage': {
            'storage_path': str(storage / 'storage').replace('\\', '/'),
            'snapshots_path': str(storage / 'snapshots').replace('\\', '/'),
            'temp_path': str(storage / 'temp').replace('\\', '/'),
            'on_disk_payload': True,
        },
        'service': {
            'host': '127.0.0.1',
            'http_port': http_port,
            'grpc_port': grpc_port,
            'enable_cors': False,
        },
        'telemetry_disabled': True,
        'log_level': 'WARN',
    }


def _write_config(storage: Path, http_port: int, grpc_port: int) -> Path:
    storage = Path(storage)
    storage.mkdir(parents=True, exist_ok=True)
    for child in ('storage', 'snapshots', 'temp'):
        (storage / child).mkdir(exist_ok=True)
    config_path = storage / 'config.yaml'
    config_path.write_text(json.dumps(qdrant_config(storage, http_port, grpc_port), indent=2), encoding='utf-8')
    return config_path


def start_qdrant(identity: Identity, *, timeout: float = 120.0) -> int:
    """Start the identity's own Qdrant server; return its OS process id."""
    binary = qdrant_binary()
    if len(str(Path(identity.qdrant_storage).resolve())) > MAX_PRIVATE_STORAGE_PATH:
        raise RestoreError(
            f'{identity.label}: private Qdrant storage path is too long for Windows '
            f'({len(str(Path(identity.qdrant_storage).resolve()))} > {MAX_PRIVATE_STORAGE_PATH} chars); '
            'choose a shorter restoration base'
        )
    config_path = _write_config(identity.qdrant_storage, identity.qdrant_http_port, identity.qdrant_grpc_port)
    if qdrant_healthy(identity.qdrant_url):
        raise RestoreError(f'{identity.qdrant_url} already answers; refusing to reuse another store')
    log = Path(identity.qdrant_storage) / 'qdrant.log'
    handle = log.open('ab')
    process = subprocess.Popen(
        [str(binary), '--config-path', str(config_path)],
        stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        cwd=str(Path(identity.qdrant_storage)), env={**os.environ, 'QDRANT__TELEMETRY_DISABLED': 'true'},
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if qdrant_healthy(identity.qdrant_url):
            (Path(identity.qdrant_storage) / 'qdrant.pid').write_text(str(process.pid), encoding='utf-8')
            return process.pid
        if process.poll() is not None:
            raise RestoreError(f'Qdrant process for {identity.label} exited with {process.returncode}')
        time.sleep(0.5)
    process.kill()
    raise RestoreError(f'Qdrant for {identity.label} did not become healthy within {timeout}s')


def stop_qdrant(identity: Identity) -> None:
    pid_file = Path(identity.qdrant_storage) / 'qdrant.pid'
    if not pid_file.exists():
        return
    pid = int(pid_file.read_text(encoding='utf-8').strip())
    subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                   capture_output=True, check=False)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and qdrant_healthy(identity.qdrant_url):
        time.sleep(0.5)
    pid_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Identity allocation
# ---------------------------------------------------------------------------

def allocate_identities(run_id: str, *, base: Path, qdrant_port_base: int = 16400) -> RunIdentity:
    """Allocate one distinct database/root/Qdrant server per (round, arm)."""
    if not run_id or not run_id.isalnum():
        raise RestoreError('run_id must be a non-empty alphanumeric token')
    base = Path(base)
    run = RunIdentity(run_id=run_id)
    known_databases: set[str] = set()
    known_roots: set[str] = set()
    known_ports: set[int] = set()
    for index, (round_name, arm) in enumerate((r, a) for r in ROUNDS for a in ARMS):
        label = f'{round_name}-{arm}'
        # Short on-disk folder: Qdrant appends deep segment paths and Windows
        # rejects the resulting path once it passes MAX_PATH.
        folder = f'{index:02d}'
        database = f'{ISOLATED_DATABASE_PREFIX}{run_id}_{index}'.lower()
        data_root = base / run_id / folder / 'root'
        qdrant_storage = base / run_id / folder / 'q'
        http_port = qdrant_port_base + index * 2
        grpc_port = http_port + 1
        if database in known_databases or str(data_root) in known_roots or http_port in known_ports:
            raise RestoreError(f'identity collision while allocating {label}')
        known_databases.add(database)
        known_roots.add(str(data_root))
        known_ports.update({http_port, grpc_port})
        run.identities.append(Identity(
            round=round_name, arm=arm, database=database, data_root=data_root,
            qdrant_url=f'http://127.0.0.1:{http_port}', qdrant_storage=qdrant_storage,
            qdrant_http_port=http_port, qdrant_grpc_port=grpc_port,
        ))
    return run


def assert_independent(run: RunIdentity) -> dict:
    """Prove no two identities share a database, a root or a store endpoint."""
    for key, values in (('database', [i.database for i in run.identities]),
                        ('data_root', [str(i.data_root) for i in run.identities]),
                        ('qdrant_url', [i.qdrant_url for i in run.identities]),
                        ('qdrant_storage', [str(i.qdrant_storage) for i in run.identities])):
        if len(set(values)) != len(values):
            raise RestoreError(f'{key} identity reused across arms: {values}')
    return {'identities': len(run.identities), 'distinct_databases': len({i.database for i in run.identities}),
            'distinct_data_roots': len({str(i.data_root) for i in run.identities}),
            'distinct_qdrant_stores': len({i.qdrant_url for i in run.identities})}


def load_run(path: Path) -> RunIdentity:
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    run = RunIdentity(run_id=payload['run_id'])
    for row in payload['identities']:
        run.identities.append(Identity(
            round=row['round'], arm=row['arm'], database=row['database'],
            data_root=Path(row['data_root']), qdrant_url=row['qdrant_url'],
            qdrant_storage=Path(row['qdrant_storage']),
            qdrant_http_port=row['qdrant_http_port'], qdrant_grpc_port=row['qdrant_grpc_port'],
        ))
    return run


def save_run(run: RunIdentity, path: Path) -> None:
    payload = {'run_id': run.run_id,
               'identities': [identity.as_record() for identity in run.identities]}
    target = Path(path)
    if target.exists():
        raise RestoreError(f'refusing to overwrite existing run identity file {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')


# ---------------------------------------------------------------------------
# Canonical JSON + authority export
# ---------------------------------------------------------------------------

def jsonable(value):
    """JSON-safe projection of a database value (deterministic, lossless)."""
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode('ascii')
    return value


def canonical_json(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)


def canonical_digest(payload) -> str:
    return hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()


def _database_engine(database: str):
    require_isolated_database(database)
    url = make_url(_settings_sync_url()).set(database=database)
    return create_engine(url.render_as_string(hide_password=False))


def _scoped_rows(engine, table: str, column: str, scopes: list[int]) -> list[dict]:
    with engine.connect() as connection:
        result = connection.execute(
            text(f'SELECT * FROM "{table}" WHERE "{column}" = ANY(:scopes)'), {'scopes': scopes}
        )
        rows = [jsonable(dict(row)) for row in result.mappings()]
    return sorted(rows, key=canonical_json)


def authority_snapshot(database: str, *, scopes: list[int]) -> dict:
    """Read-only export of the frozen authority and published evidence of ``scopes``."""
    require_isolated_database(database)
    scopes = [int(scope) for scope in scopes]
    engine = _database_engine(database)
    try:
        with engine.connect() as connection:
            version = connection.scalar(text('SELECT version_num FROM alembic_version'))
            present = {int(row[0]) for row in connection.execute(
                text('SELECT scope_id FROM knowledge_scopes WHERE scope_id = ANY(:scopes)'),
                {'scopes': scopes})}
            if present != set(scopes):
                raise RestoreError(f'{database} is missing scopes {sorted(set(scopes) - present)}')
            profiles = [jsonable(dict(row)) for row in connection.execute(text(
                'SELECT * FROM domain_profiles WHERE domain_key IN '
                '(SELECT domain_key FROM knowledge_scopes WHERE scope_id = ANY(:scopes))'),
                {'scopes': scopes}).mappings()]
            cutoff = connection.scalar(
                text('SELECT coalesce(max(event_id), 0) FROM memory_events WHERE knowledge_scope_id = ANY(:scopes)'),
                {'scopes': scopes})
        profiles.sort(key=canonical_json)
        tables = {}
        for table, column in AUTHORITY_TABLES:
            rows = _scoped_rows(engine, table, column, scopes)
            tables[table] = {'rows': len(rows), 'digest': canonical_digest(rows)}
        control = {table: len(_scoped_rows(engine, table, column, scopes))
                   for table, column in CONTROL_TABLES}
        digest = canonical_digest({'scopes': sorted(scopes), 'tables': tables, 'profiles': profiles})
        return {'database': database, 'alembic_version': version, 'scopes': sorted(scopes),
                'authority_cutoff': int(cutoff or 0), 'tables': tables, 'control_rows': control,
                'profiles_digest': canonical_digest(profiles), 'profiles_rows': len(profiles),
                'authority_digest': digest}
    finally:
        engine.dispose()


def project_manifest(database: str, *, scopes: list[int]) -> dict:
    """Frozen projection manifest per scope (the real ``current()`` view identity)."""
    require_isolated_database(database)
    scopes = [int(scope) for scope in scopes]
    engine = _database_engine(database)
    try:
        rows = _scoped_rows(engine, 'memory_projection_meta', 'knowledge_scope_id', scopes)
    finally:
        engine.dispose()
    manifests = {}
    for scope in scopes:
        current = next((row for row in rows if row['projection_id'] == f'current:{scope}'), None)
        if current is None:
            manifests[str(scope)] = {'status': 'absent'}
            continue
        payload = current.get('payload') or {}
        versions = {row['projection_type']: row['projection_version'] for row in rows
                    if row['knowledge_scope_id'] == scope
                    and row['source_event_id'] == current['source_event_id']
                    and row['status'] == 'complete'}
        manifests[str(scope)] = {
            'status': current['status'], 'source_event_id': current['source_event_id'],
            'collection': payload.get('collection'), 'dense_revision': payload.get('dense_revision'),
            'projection_versions': versions,
        }
    return {'scopes': sorted(scopes), 'manifests': manifests, 'manifest_digest': canonical_digest(manifests)}


# ---------------------------------------------------------------------------
# Qdrant: sealed point export and per-identity import (no source writes)
# ---------------------------------------------------------------------------

def _qdrant_client(url: str):
    from qdrant_client import QdrantClient

    return QdrantClient(url=url, timeout=180, check_compatibility=False)


def _dump_vector(value):
    if isinstance(value, dict):
        return {str(key): _dump_vector(item) for key, item in value.items()}
    if hasattr(value, 'indices') and hasattr(value, 'values'):
        return {'__sparse__': {'indices': [int(item) for item in value.indices],
                               'values': [float(item) for item in value.values]}}
    return [float(item) for item in value]


def _load_vector(value):
    from qdrant_client.models import SparseVector

    if isinstance(value, dict):
        if set(value) == {'__sparse__'}:
            inner = value['__sparse__']
            return SparseVector(indices=inner['indices'], values=inner['values'])
        return {str(key): _load_vector(item) for key, item in value.items()}
    return [float(item) for item in value]


def _vectors_config(dump: dict):
    from qdrant_client.models import Distance, VectorParams

    fields = set(VectorParams.model_fields)
    if 'size' in dump:
        data = {key: value for key, value in dump.items() if key in fields}
        data['distance'] = Distance(data['distance'])
        return VectorParams(**data)
    config = {}
    for name, spec in dump.items():
        data = {key: value for key, value in spec.items() if key in fields}
        data['distance'] = Distance(data['distance'])
        config[name] = VectorParams(**data)
    return config


def _sparse_config(dump: dict | None):
    from qdrant_client.models import SparseVectorParams

    if not dump:
        return None
    fields = set(SparseVectorParams.model_fields)
    return {name: SparseVectorParams(**{key: value for key, value in spec.items() if key in fields})
            for name, spec in dump.items()}


def collection_layout(url: str, name: str) -> dict:
    """Record the faithful vector/sparse layout of one collection."""
    client = _qdrant_client(url)
    try:
        info = client.get_collection(collection_name=name)
        params = info.config.params
        dump = jsonable(params.model_dump(exclude_none=True))
        return {'name': name, 'vectors': dump.get('vectors'), 'sparse_vectors': dump.get('sparse_vectors'),
                'points_count': getattr(info, 'points_count', None),
                'config_digest': canonical_digest(dump)}
    finally:
        client.close()


def collection_names(url: str) -> list[str]:
    client = _qdrant_client(url)
    try:
        return sorted(collection.name for collection in client.get_collections().collections)
    finally:
        client.close()


def scope_filter(scopes: list[int]):
    """Match a scope payload whether it was stored as a string or as an integer."""
    from qdrant_client.models import FieldCondition, Filter, MatchAny

    return Filter(should=[
        FieldCondition(key='knowledge_scope_id', match=MatchAny(any=[str(scope) for scope in scopes])),
        FieldCondition(key='knowledge_scope_id', match=MatchAny(any=[int(scope) for scope in scopes])),
    ])


def export_points(url: str, name: str, scopes: list[int]) -> list[dict]:
    """Read the sealed scope's points out of a collection (read-only scroll)."""
    client = _qdrant_client(url)
    points, offset = [], None
    try:
        while True:
            batch, offset = client.scroll(collection_name=name, scroll_filter=scope_filter(scopes),
                                          limit=512, offset=offset, with_payload=True, with_vectors=True)
            for record in batch:
                points.append({'id': record.id, 'vector': _dump_vector(record.vector),
                               'payload': jsonable(record.payload or {})})
            if offset is None:
                break
    finally:
        client.close()
    return sorted(points, key=canonical_json)


def points_digest(points: list[dict]) -> str:
    return canonical_digest(points)


def import_points(url: str, layout: dict, points: list[dict]) -> None:
    """Create the identity's own collection and import the sealed points."""
    from qdrant_client.models import PointStruct

    client = _qdrant_client(url)
    try:
        name = layout['name']
        if client.collection_exists(name):
            raise RestoreError(f'{url} already has collection {name!r}; refusing to reuse another store')
        client.create_collection(collection_name=name, vectors_config=_vectors_config(layout['vectors']),
                                 sparse_vectors_config=_sparse_config(layout.get('sparse_vectors')))
        batch = []
        for point in points:
            batch.append(PointStruct(id=point['id'], vector=_load_vector(point['vector']), payload=point['payload']))
            if len(batch) >= 256:
                client.upsert(collection_name=name, points=batch, wait=True)
                batch = []
        if batch:
            client.upsert(collection_name=name, points=batch, wait=True)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Sealing and restoring
# ---------------------------------------------------------------------------

def _capsule_meta(capsule_dir: Path) -> dict:
    return json.loads((Path(capsule_dir) / 'capsule.json').read_text(encoding='utf-8'))


def seal_capsule(*, source_database: str, source_data_root: Path, capsule_dir: Path,
                 scopes: list[int], capsule_token: str, source_qdrant_url: str = QDRANT_DEFAULT_URL,
                 scope_only: bool = True, collections: list[str] | None = None) -> dict:
    """Seal the frozen authority into an immutable capsule (read-only on the source).

    The capsule owns one native PostgreSQL copy, one byte copy of the frozen
    scopes' private ``data_root`` subtrees and one point file per Qdrant
    collection for the frozen scope. It never overwrites an existing capsule and
    never writes to the source.
    """
    require_isolated_database(source_database)
    capsule_dir = Path(capsule_dir)
    if capsule_dir.exists():
        raise RestoreError(f'capsule already exists: {capsule_dir}')
    if not capsule_token.isalnum():
        raise RestoreError('capsule_token must be alphanumeric')
    scopes = [int(scope) for scope in scopes]
    capsule_dir.mkdir(parents=True)
    capsule_database = f'{ISOLATED_DATABASE_PREFIX}capsule_{capsule_token}'.lower()

    authority = authority_snapshot(source_database, scopes=scopes)
    manifest = project_manifest(source_database, scopes=scopes)
    create_database(capsule_database, template=source_database)

    if scope_only:
        data_root_manifest = copy_tree_scoped(Path(source_data_root), capsule_dir / 'data-root', scopes)
    else:
        data_root_manifest = copy_tree(Path(source_data_root), capsule_dir / 'data-root')

    client = _qdrant_client(source_qdrant_url)
    try:
        names = sorted(collection.name for collection in client.get_collections().collections)
    finally:
        client.close()
    if collections is not None:
        missing = sorted(set(collections) - set(names))
        if missing:
            raise RestoreError(f'declared collections do not exist in {source_qdrant_url}: {missing}')
        names = sorted(collections)
    qdrant_dir = capsule_dir / 'qdrant'
    qdrant_dir.mkdir()
    collections = {}
    for name in names:
        layout = collection_layout(source_qdrant_url, name)
        points = export_points(source_qdrant_url, name, scopes) if layout['points_count'] else []
        if points:
            with (qdrant_dir / f'{name}.jsonl').open('w', encoding='utf-8') as handle:
                for point in points:
                    handle.write(canonical_json(point) + '\n')
        collections[name] = {**layout, 'sealed_points': len(points), 'points_digest': points_digest(points)}

    payload = {
        'capsule_version': CAPSULE_VERSION,
        'sealed_at': datetime.now().astimezone().isoformat(),
        'capsule_token': capsule_token,
        'source_database': source_database,
        'source_data_root': str(source_data_root),
        'source_qdrant_url': source_qdrant_url,
        'capsule_database': capsule_database,
        'scopes': scopes,
        'alembic_version': authority['alembic_version'],
        'authority_cutoff': authority['authority_cutoff'],
        'authority': authority,
        'project_manifest': manifest,
        'data_root_manifest': data_root_manifest,
        'data_root_digest': tree_digest(data_root_manifest),
        'qdrant': collections,
    }
    (capsule_dir / 'capsule.json').write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
    return {'status': 'sealed', 'capsule_dir': str(capsule_dir), 'capsule_database': capsule_database,
            'authority_digest': authority['authority_digest'], 'data_root_digest': payload['data_root_digest'],
            'collections': {name: row['sealed_points'] for name, row in collections.items()}}


def restore_identity(capsule_dir: Path, identity: Identity) -> dict:
    """Materialise one identity from the capsule and verify it immediately."""
    capsule_dir = Path(capsule_dir)
    if Path(identity.data_root).exists():
        raise RestoreError(f'{identity.label}: data root already exists ({identity.data_root})')
    if database_exists(identity.database):
        raise RestoreError(f'{identity.label}: database already exists ({identity.database})')
    capsule = _capsule_meta(capsule_dir)
    _write_config(identity.qdrant_storage, identity.qdrant_http_port, identity.qdrant_grpc_port)
    create_database(identity.database, template=capsule['capsule_database'])
    copy_tree(capsule_dir / 'data-root', Path(identity.data_root))
    pid = start_qdrant(identity)
    imported = {}
    for name, layout in capsule['qdrant'].items():
        path = capsule_dir / 'qdrant' / f'{name}.jsonl'
        points = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
        import_points(identity.qdrant_url, layout, points)
        imported[name] = len(points)
    report = verify_identity(capsule_dir, identity)
    report.update({'status': 'restored', 'pid': pid, 'imported': imported})
    receipt = Path(identity.data_root).parent / 'restore-receipt.json'
    if receipt.exists():
        raise RestoreError(f'{identity.label}: restore receipt already exists')
    receipt.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')
    return report


def verify_identity(capsule_dir: Path, identity: Identity) -> dict:
    """Prove a restored identity still equals the sealed capsule."""
    capsule_dir = Path(capsule_dir)
    capsule = _capsule_meta(capsule_dir)
    scopes = capsule['scopes']
    authority = authority_snapshot(identity.database, scopes=scopes)
    if authority['authority_digest'] != capsule['authority']['authority_digest']:
        raise RestoreError(f'{identity.label}: restored authority differs from the sealed capsule')
    if authority['alembic_version'] != capsule['alembic_version']:
        raise RestoreError(f'{identity.label}: migration version drifted')
    if authority['authority_cutoff'] != capsule['authority_cutoff']:
        raise RestoreError(f'{identity.label}: authority cutoff drifted')
    manifest = project_manifest(identity.database, scopes=scopes)
    if manifest['manifest_digest'] != capsule['project_manifest']['manifest_digest']:
        raise RestoreError(f'{identity.label}: projection manifest differs from the sealed capsule')
    rows = tree_manifest(Path(identity.data_root))
    if tree_digest(rows) != capsule['data_root_digest']:
        raise RestoreError(f'{identity.label}: private data root differs from the sealed capsule')
    store = {}
    for name, layout in capsule['qdrant'].items():
        points = export_points(identity.qdrant_url, name, scopes)
        store[name] = {'points': len(points), 'digest': points_digest(points)}
        if points_digest(points) != layout['points_digest'] or len(points) != layout['sealed_points']:
            raise RestoreError(f'{identity.label}: Qdrant collection {name!r} differs from the sealed capsule')
    return {'label': identity.label, 'database': identity.database, 'data_root': str(identity.data_root),
            'qdrant_url': identity.qdrant_url, 'authority_digest': authority['authority_digest'],
            'manifest_digest': manifest['manifest_digest'], 'data_root_digest': capsule['data_root_digest'],
            'qdrant': store, 'alembic_version': authority['alembic_version'],
            'authority_cutoff': authority['authority_cutoff']}
