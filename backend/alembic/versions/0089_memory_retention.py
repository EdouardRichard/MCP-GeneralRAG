"""Extend both deterministic reducers with event-derived retention stages."""
from alembic import op
import sqlalchemy as sa
import importlib.util
from pathlib import Path

revision = "0089_memory_retention"
down_revision = "0088_memory_db_replay"
branch_labels = None
depends_on = None


def replace_fragment(definition, before, after, *, count=1):
    if definition.count(before) != count:
        raise RuntimeError("unexpected database reducer version; refusing partial migration")
    return definition.replace(before, after)


def upgrade():
    op.add_column("memory_entries", sa.Column("retention_stage", sa.String(16), nullable=False, server_default="active"))
    connection = op.get_bind()
    definition = connection.execute(sa.text("SELECT pg_get_functiondef('memory_log_state(bigint,bigint)'::regprocedure)")).scalar_one()
    definition = replace_fragment(definition, "'source_event_id',event.event_id)", "'source_event_id',event.event_id,'retention_stage','active')")
    definition = replace_fragment(definition, "'status','retired','valid_to',stamp,'invalidated_at',stamp)",
        "'status','retired','retention_stage','tombstone','valid_to',stamp,'invalidated_at',stamp)", count=2)
    definition = replace_fragment(definition, """ELSIF event.event_type='grant' AND event.payload ? 'binding_id' THEN
                    SELECT jsonb_object_agg(key,value) INTO row_data FROM jsonb_each(event.payload)
                        WHERE key IN ('binding_id','binding_kind','binding_value','priority','status');
                    bindings := jsonb_set(bindings,ARRAY[event.payload->>'binding_id'],row_data || jsonb_build_object('knowledge_scope_id',scope_id));""", """ELSIF event.event_type='grant' THEN
                    IF event.payload ? 'binding_id' THEN
                        SELECT jsonb_object_agg(key,value) INTO row_data FROM jsonb_each(event.payload)
                            WHERE key IN ('binding_id','binding_kind','binding_value','priority','status');
                        bindings := jsonb_set(bindings,ARRAY[event.payload->>'binding_id'],row_data || jsonb_build_object('knowledge_scope_id',scope_id));
                    ELSIF event.payload ? 'retention_stage' THEN
                        row_data := entries->mid;
                        IF row_data IS NULL OR row_data->>'status'<>'active' OR event.payload->>'retention_stage' IS DISTINCT FROM
                            (CASE row_data->>'retention_stage' WHEN 'active' THEN 'compressed' WHEN 'compressed' THEN 'archived' WHEN 'archived' THEN 'tombstone' END)
                            THEN RAISE EXCEPTION 'invalid immutable authority retention transition'; END IF;
                        row_data := row_data || jsonb_build_object('retention_stage',event.payload->>'retention_stage');
                        IF event.payload->>'retention_stage'='tombstone' THEN
                            row_data := row_data || jsonb_build_object('status','retired','valid_to',stamp,'invalidated_at',stamp);
                        END IF;
                        entries := jsonb_set(entries,ARRAY[mid],row_data);
                    END IF;""")
    definition = replace_fragment(definition, """dense := jsonb_set(dense,ARRAY[pair.key],row_data);""", """branch := scope_id::text || '/' || COALESCE(row_data->>'kind','episodic');
                path := '012-v1/' || branch || '/' || pair.key || '.md';
                IF row_data->>'retention_stage' IN ('compressed','archived') THEN path := path || '.gz'; END IF;
                IF row_data->>'retention_stage'='archived' THEN path := 'archives/' || path; END IF;
                files := jsonb_set(files,ARRAY[path],row_data || jsonb_build_object('path',path,
                    'body','# Memory ' || pair.key || chr(10) || chr(10) || memory_sorted_json(row_data)));
                IF row_data->>'retention_stage'='archived' THEN CONTINUE; END IF;
                dense := jsonb_set(dense,ARRAY[pair.key],row_data);""")
    definition = replace_fragment(definition, """                path := '012-v1/' || branch || '/' || pair.key || '.md';
                files := jsonb_set(files,ARRAY[path],row_data || jsonb_build_object('path',path,
                    'body','# Memory ' || pair.key || chr(10) || chr(10) || memory_sorted_json(row_data)));
            END LOOP;""", """            END LOOP;""")
    connection.execute(sa.text(definition))
    guard = connection.execute(sa.text("SELECT pg_get_functiondef('verify_memory_log_projection()'::regprocedure)")).scalar_one()
    guard = replace_fragment(guard, "ARRAY['status','superseded_by','source_event_id']", "ARRAY['status','superseded_by','source_event_id','retention_stage']")
    connection.execute(sa.text(guard))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM memory_events")).scalar_one():
        raise RuntimeError("cannot remove retention metadata with retained events")
    previous = Path(__file__).with_name("0088_memory_database_replay.py")
    spec = importlib.util.spec_from_file_location("memory_database_replay_0088", previous)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.upgrade()
    op.drop_column("memory_entries", "retention_stage")
