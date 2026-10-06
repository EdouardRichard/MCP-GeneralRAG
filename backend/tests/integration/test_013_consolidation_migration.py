import importlib.util
import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json
import pytest
from sqlalchemy.engine import make_url

from rag_mcp.config import get_settings


BACKEND = Path(__file__).parents[2]
MIGRATION = BACKEND / 'alembic/versions/0095_memory_consolidation_loop.py'


def test_successor_revision_exists_without_changing_deployed_history():
    assert MIGRATION.exists(), '013 needs additive 0095 migration after deployed 0094'
    spec = importlib.util.spec_from_file_location('migration013', MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == '0094_memory_management_audit'


def alembic(database_url, *arguments):
    sync = make_url(database_url).set(drivername='postgresql')
    env = {**os.environ, 'DATABASE_URL': database_url,
           'DATABASE_URL_SYNC': sync.render_as_string(hide_password=False), 'PYTHONPATH': 'src;../eval'}
    return subprocess.run([sys.executable, '-m', 'alembic', *arguments], cwd=BACKEND,
                          env=env, capture_output=True, text=True, timeout=120)


def connect(url):
    return psycopg2.connect(dbname=url.database, user=url.username, password=url.password,
                            host=url.host, port=url.port)


def publish_0094_manifest(target):
    archive = subprocess.run(['git', 'archive', '6796c0c', 'backend/src'], cwd=BACKEND.parent,
                             capture_output=True, check=True)
    with TemporaryDirectory(prefix='legacy013_source_') as legacy_source:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as source:
            source.extractall(legacy_source, filter='data')
        env = {**os.environ,
            'DATABASE_URL': target.set(drivername='postgresql+asyncpg').render_as_string(hide_password=False),
            'DATABASE_URL_SYNC': target.set(drivername='postgresql').render_as_string(hide_password=False),
            'PYTHONPATH': os.pathsep.join((str(Path(legacy_source) / 'backend/src'), str(BACKEND.parent / 'eval'))),
            'DATA_ROOT': str(Path(os.environ['DATA_ROOT']) / ('legacy013_' + uuid4().hex))}
        script = """
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from rag_mcp.config import get_settings
from rag_mcp.services.memory_service import MemoryService
from tests.integration.consolidation_fixtures import StableEmbedding

async def main():
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        service = MemoryService(session, embedding_provider=StableEmbedding())
        report = await service.rebuild(1, actor='management', reason='Publish actual 0094 fixture')
        assert all(row['matches_replay'] for row in report.values())
        manifest = await service.projections.current(1)
        assert manifest.status == 'complete' and manifest.payload['verification_version'] == 1
        assert 'consolidation_state' not in manifest.payload['state']
    await engine.dispose()

asyncio.run(main())
"""
        result = subprocess.run([sys.executable, '-c', script], cwd=BACKEND, env=env,
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr


async def verify_upgraded_legacy_snapshot(target, legacy_manifest):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
    from rag_mcp.services.consolidation_runtime import ConsolidationRuntime, ConsolidationRuntimeError
    from rag_mcp.services.memory_reducer import projection_fingerprint
    engine = create_async_engine(target.set(drivername='postgresql+asyncpg'))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            runtime = ConsolidationRuntime(session, owner=None)
            current = await runtime.read_snapshot(1)
            assert current.high_water_mark == 3 and set(current.entries) == {1, 2, 3}
            assert current.consolidation_state['window_seals'] == {}
            original_get = session.get
            corrupted_state = {**legacy_manifest[2]['state'], 'entries': {}}
            for changes in (
                {'fingerprint': '0' * 64},
                {'payload': {**legacy_manifest[2], 'verification_version': 999}},
                {'payload': {**legacy_manifest[2], 'state': corrupted_state},
                 'fingerprint': projection_fingerprint(corrupted_state)},
            ):
                fake = SimpleNamespace(status='complete', source_event_id=3, projection_version='012-v1', fingerprint=legacy_manifest[1],
                                       payload=legacy_manifest[2])
                for key, value in changes.items():
                    setattr(fake, key, value)
                async def altered_get(model, key, **kwargs):
                    return fake if model is MemoryProjectionMeta else await original_get(model, key, **kwargs)
                with patch.object(session, 'get', altered_get):
                    with pytest.raises(ConsolidationRuntimeError, match='CONSOLIDATION_COMPLETE_MANIFEST_REQUIRED'):
                        await runtime.read_snapshot(1)
    finally:
        await engine.dispose()


def test_populated_012_upgrade_preserves_flat_events_base_edges_and_revision_history():
    url = make_url(get_settings().database_url_sync)
    isolated = os.environ.get('CONSOLIDATION_ISOLATED_DATABASE')
    assert isolated and url.database == isolated, '013 migrations require the explicitly isolated database'
    database = 'test013_migration_' + uuid4().hex
    admin = connect(url)
    admin.autocommit = True
    with admin.cursor() as cursor:
        cursor.execute('CREATE DATABASE ' + database)
    target = url.set(database=database)
    try:
        before = alembic(target.set(drivername='postgresql+asyncpg').render_as_string(hide_password=False),
                         'upgrade', '0094_memory_management_audit')
        assert before.returncode == 0, before.stderr
        with connect(target) as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO knowledge_scopes(scope_id,scope_type,name,slug,domain_key,status) VALUES (1,'public','legacy','legacy013','generic','active')")
                cursor.execute("INSERT INTO knowledge_sources(source_id,knowledge_scope_id,filename,content_hash,format,size_bytes,status) VALUES (11,1,'legacy.md',%s,'markdown',15,'published')", ('0' * 64,))
                cursor.execute("INSERT INTO knowledge_versions(version_id,knowledge_scope_id,version_number,status) VALUES (12,1,1,'published')")
                cursor.execute("INSERT INTO chunks(chunk_id,source_id,version_id,knowledge_scope_id,content_text,position_path,chunk_type,start_line,end_line,token_count,embedding_model,index_version) VALUES (123,11,12,1,'Legacy evidence','legacy#evidence','paragraph',1,1,2,'fixture-v1','fixture-v1')")
                cursor.execute('SELECT * FROM chunks WHERE chunk_id=123')
                old_chunk = cursor.fetchone()
                for identifier, event_type, payload in (
                    (1, 'assert', {'kind': 'episodic', 'provenance': 'hard', 'content_text': 'Legacy episode', 'evidence_refs': ['123']}),
                    (2, 'revise', {'kind': 'episodic', 'provenance': 'hard', 'content_text': 'Corrected episode', 'evidence_refs': ['123'], 'supersedes_memory_id': 1}),
                    (3, 'consolidate', {'kind': 'semantic', 'provenance': 'distilled', 'content_text': 'Legacy flat consolidate', 'evidence_refs': []}),
                ):
                    payload['content_hash'] = str(identifier).zfill(64)
                    payload['tags'] = []
                    payload['created_at'] = payload['updated_at'] = '2026-10-06T00:00:00+00:00'
                    cursor.execute("INSERT INTO memory_events(event_id,event_type,aggregate_id,knowledge_scope_id,payload,authority,scope_meta,mutability,provenance_meta,recoverability,actor,request_id,occurred_at) VALUES (%s,%s,%s,1,%s,'{}','{}','{}','{}','{}','memory_tool','legacy',clock_timestamp())",
                                   (identifier, event_type, identifier, json.dumps(payload)))
                    cursor.execute('SET LOCAL ROLE rag_memory_reducer')
                    cursor.execute("SELECT set_config('rag_memory.reducer_event',%s,true)", (str(identifier),))
                    cursor.execute('SELECT memory_log_state(1,%s)', (identifier,))
                    state = cursor.fetchone()[0]
                    for key, row in state['links'].items():
                        cursor.execute('INSERT INTO memory_links(row_id,knowledge_scope_id,revision_id,node_key,data) VALUES (%s,1,%s,%s,%s)',
                                       (f'1:{identifier}:{key}', identifier, key, json.dumps(row)))
                    if identifier == 3:
                        cursor.execute('SELECT * FROM memory_entries LIMIT 0')
                        entry_columns = [column.name for column in cursor.description]
                        for row in state['entries'].values():
                            values = {**{key: value for key, value in row.items() if key in entry_columns},
                                      'write_status': 'failed'}
                            cursor.execute(sql.SQL('INSERT INTO memory_entries ({}) VALUES ({})').format(
                                sql.SQL(',').join(map(sql.Identifier, values)),
                                sql.SQL(',').join(sql.Placeholder() for _ in values)),
                                [Json(value) if isinstance(value, (dict, list)) else value for value in values.values()])
                    cursor.execute('RESET ROLE')
                cursor.execute('SELECT row_id,revision_id,node_key,data FROM memory_links ORDER BY row_id')
                old_links = cursor.fetchall()
                entry_query = sql.SQL('SELECT {} FROM memory_entries ORDER BY memory_id').format(
                    sql.SQL(',').join(map(sql.Identifier, entry_columns)))
                cursor.execute('SELECT memory_log_state(1,3)')
                old_state = cursor.fetchone()[0]
        publish_0094_manifest(target)
        with connect(target) as connection:
            with connection.cursor() as cursor:
                cursor.execute(entry_query)
                old_entries = cursor.fetchall()
                assert all(row[entry_columns.index('write_status')] == 'complete' for row in old_entries)
                cursor.execute("SELECT source_event_id,fingerprint,payload FROM memory_projection_meta WHERE projection_id='current:1'")
                legacy_manifest = cursor.fetchone()
                assert legacy_manifest[0] == 3 and 'consolidation_state' not in legacy_manifest[2]['state']
        upgraded = alembic(target.set(drivername='postgresql+asyncpg').render_as_string(hide_password=False), 'upgrade', 'head')
        assert upgraded.returncode == 0, upgraded.stderr
        with connect(target) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT row_id,revision_id,node_key,data FROM memory_links ORDER BY row_id')
                assert cursor.fetchall() == old_links
                cursor.execute('SELECT relation_type,to_kind,from_id,to_id,confidence,provenance FROM memory_links ORDER BY row_id')
                typed = cursor.fetchall()
                assert any(row[:4] == ('evidence', 'evidence', '2', '123') for row in typed)
                assert any(row[:4] == ('supersedes', 'memory', '2', '1') for row in typed)
                assert all(row[4:] == (None, 'deterministic') for row in typed)
                cursor.execute('SELECT * FROM chunks WHERE chunk_id=123')
                assert cursor.fetchone() == old_chunk
                cursor.execute(entry_query)
                assert cursor.fetchall() == old_entries
                cursor.execute('SELECT source_event_id,state_event_id,keywords,context_digest,context_version,context_source_event_id,promotion_pointer,candidate_version,candidate_basis FROM memory_entries ORDER BY memory_id')
                defaults = cursor.fetchall()
                assert len(defaults) == 3
                assert all(row[0] == row[1] and row[2:] == ([], None, None, None, None, None, None) for row in defaults)
                cursor.execute('SELECT memory_log_state(1,3)')
                new_state = cursor.fetchone()[0]
                assert {key: new_state[key] for key in old_state} == old_state
                assert new_state['consolidation_state']['window_seals'] == {}
                cursor.execute("SELECT memory_link_vocabulary FROM domain_profiles WHERE domain_key='generic'")
                assert cursor.fetchone()[0] == []
                cursor.execute("INSERT INTO consolidation_runs(run_id,observation_seq,knowledge_scope_id,trigger,execution_context,status) VALUES (%s,1,1,'manual','distiller_window','admitted') RETURNING provider_usage", (str(uuid4()),))
                usage = cursor.fetchone()[0]
                assert usage['source'] == 'unavailable'
                assert all(usage[key] is None for key in ('input_tokens', 'output_tokens', 'cost_usd'))
                cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname='uq_consolidation_scope_active'")
                index = cursor.fetchone()[0]
                assert 'UNIQUE' in index and "state" in index and 'now()' not in index
                cursor.execute("SELECT source_event_id,fingerprint,payload FROM memory_projection_meta WHERE projection_id='current:1'")
                assert cursor.fetchone() == legacy_manifest
        asyncio.run(verify_upgraded_legacy_snapshot(target, legacy_manifest))
        with connect(target) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT source_event_id,fingerprint,payload FROM memory_projection_meta WHERE projection_id='current:1'")
                assert cursor.fetchone() == legacy_manifest
                cursor.execute("INSERT INTO memory_events(event_id,event_type,aggregate_id,knowledge_scope_id,payload,authority,scope_meta,mutability,provenance_meta,recoverability,actor,request_id,occurred_at) VALUES (4,'consolidate',4,1,'{\"payload_version\":2}','{}','{}','{}','{}','{}','memory_tool','v2-downgrade-test',clock_timestamp())")
        refused = alembic(target.set(drivername='postgresql+asyncpg').render_as_string(hide_password=False),
                          'downgrade', '0094_memory_management_audit')
        assert refused.returncode != 0
        assert 'cannot downgrade' in refused.stderr.lower()
    finally:
        with admin.cursor() as cursor:
            cursor.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s', (database,))
            cursor.execute('DROP DATABASE ' + database)
        admin.close()
