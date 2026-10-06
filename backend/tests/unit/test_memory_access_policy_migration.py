from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest


def _migration(monkeypatch, definition, *, event_count=0):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0093_memory_access_policy.py"
    spec = spec_from_file_location("memory_access_policy_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    state = {"definition": definition, "writes": []}

    def execute(statement):
        statement = str(statement)
        if statement.startswith("SELECT pg_get_functiondef"):
            return SimpleNamespace(scalar_one=lambda: state["definition"])
        if statement.startswith("SELECT count(*)"):
            return SimpleNamespace(scalar_one=lambda: event_count)
        state["definition"] = statement
        state["writes"].append(statement)

    monkeypatch.setattr(migration.op, "get_bind", lambda: SimpleNamespace(execute=execute))
    return migration, state


def test_access_policy_migration_preserves_other_reducer_semantics_and_reverses_without_events(monkeypatch):
    definition = """CREATE OR REPLACE FUNCTION memory_log_state(scope_id bigint, through_id bigint) RETURNS jsonb
        LANGUAGE plpgsql AS $$ BEGIN
        row_data := event.payload || jsonb_build_object('authority',event.authority);
        access_state := salience->mid;
        score := greatest(0.0,(access_state->>'salience')::double precision
            - (access_state->>'decay_rate')::double precision * greatest(0.0,age_days) + 1.0);
        salience := jsonb_set(salience,ARRAY[mid],access_state || jsonb_build_object('salience',score));
        END; $$;"""
    migration, state = _migration(monkeypatch, definition)
    migration.upgrade()
    assert state["definition"].replace(migration.ACCESS_AFTER, migration.ACCESS_BEFORE) == definition
    assert "COALESCE(event.payload->'decay_rate',access_state->'decay_rate')" in state["definition"]
    migration.downgrade()
    assert state["definition"] == definition
    assert len(state["writes"]) == 2


@pytest.mark.parametrize("definition", ["different reducer", "access_state := salience->mid;" * 2])
def test_access_policy_migration_refuses_unrecognized_reducer_without_partial_write(monkeypatch, definition):
    migration, state = _migration(monkeypatch, definition)
    with pytest.raises(RuntimeError, match="unexpected database access reducer version"):
        migration.upgrade()
    assert state["writes"] == []


def test_access_policy_migration_refuses_duplicate_application(monkeypatch):
    migration, state = _migration(monkeypatch, "access_state := salience->mid;")
    migration.upgrade()
    with pytest.raises(RuntimeError, match="unexpected database access reducer version"):
        migration.upgrade()
    assert len(state["writes"]) == 1


def test_access_policy_migration_cannot_discard_recorded_authority(monkeypatch):
    migration, state = _migration(monkeypatch, "access_state := salience->mid;", event_count=1)
    with pytest.raises(RuntimeError, match="retained authority events"):
        migration.downgrade()
    assert state["writes"] == []
