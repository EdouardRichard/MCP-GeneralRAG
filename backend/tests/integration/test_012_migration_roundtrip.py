"""Real migration roundtrip in a disposable PostgreSQL database."""
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import create_engine, text

from rag_mcp.config import get_settings


def test_retention_migration_empty_database_roundtrip():
    url = get_settings().database_url_sync
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = "memory_migration_" + uuid4().hex
    isolated = admin.url.set(database=name)
    env = {**os.environ, "DATABASE_URL": isolated.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False),
           "DATABASE_URL_SYNC": isolated.render_as_string(hide_password=False)}
    def migrate(target, operation="upgrade"):
        result = subprocess.run([sys.executable, "-m", "alembic", operation, target], env=env,
                                cwd=Path(__file__).parents[2], capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stderr
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(isolated)
    try:
        migrate("0088_memory_db_replay")
        def definitions():
            with engine.connect() as connection:
                return [connection.scalar(text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
                                          {"signature": signature}) for signature in
                        ("memory_log_state(bigint,bigint)", "verify_memory_log_projection()")]
        prior = definitions()
        migrate("head")
        assert definitions() != prior
        migrate("0088_memory_db_replay", "downgrade")
        assert definitions() == prior
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_name='memory_entries' AND column_name='retention_stage'")) == 0
        migrate("head")
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
