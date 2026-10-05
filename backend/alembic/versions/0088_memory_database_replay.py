"""Verify derived writes against log replay, with explicit runtime roles."""
from alembic import op
import sqlalchemy as sa

revision = "0088_memory_db_replay"
down_revision = "0087_memory_history"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='rag_memory_reader') THEN
                CREATE ROLE rag_memory_reader NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='rag_memory_reducer') THEN
                CREATE ROLE rag_memory_reducer NOLOGIN;
            END IF;
        END $$;
        GRANT USAGE ON SCHEMA public TO rag_memory_reader,rag_memory_reducer;
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO rag_memory_reader,rag_memory_reducer;
        GRANT INSERT ON memory_recall_runs TO rag_memory_reader;
        GRANT INSERT ON memory_events,memory_snapshots,memory_archives,memory_archived_events TO rag_memory_reducer;
        GRANT INSERT,UPDATE ON memory_entries,memory_salience,memory_links,memory_summary_nodes,
            memory_projection_meta,scope_bindings,sessions TO rag_memory_reducer;
        GRANT INSERT ON memory_recall_runs TO rag_memory_reducer;

        CREATE OR REPLACE FUNCTION memory_isoformat(value timestamptz) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT to_char(value AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS') ||
                CASE WHEN to_char(value AT TIME ZONE 'UTC','US')='000000' THEN ''
                     ELSE '.' || to_char(value AT TIME ZONE 'UTC','US') END || '+00:00';
        $$;
        CREATE OR REPLACE FUNCTION memory_sorted_json(value jsonb) RETURNS text
        LANGUAGE plpgsql IMMUTABLE STRICT AS $$
        DECLARE result text;
        BEGIN
            IF jsonb_typeof(value)='object' THEN
                SELECT '{' || COALESCE(string_agg(to_jsonb(key)::text || ': ' || memory_sorted_json(item), ', ' ORDER BY key COLLATE "C"),'') || '}'
                  INTO result FROM jsonb_each(value) AS pair(key,item);
            ELSIF jsonb_typeof(value)='array' THEN
                SELECT '[' || COALESCE(string_agg(memory_sorted_json(item), ', ' ORDER BY ordinal),'') || ']'
                  INTO result FROM jsonb_array_elements(value) WITH ORDINALITY AS pair(item,ordinal);
            ELSE
                result := value::text;
            END IF;
            RETURN result;
        END; $$;
        CREATE OR REPLACE FUNCTION memory_log_state(scope_id bigint, through_id bigint) RETURNS jsonb
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            event memory_events%ROWTYPE; entries jsonb := '{}'; salience jsonb := '{}'; bindings jsonb := '{}';
            dense jsonb := '{}'; links jsonb := '{}'; summary jsonb := '{}'; files jsonb := '{}';
            mid text; target text; stamp text; row_data jsonb; restored jsonb; pair record; ref jsonb;
            branch text; path text; access_state jsonb; age_days double precision; score double precision;
        BEGIN
            FOR event IN SELECT * FROM memory_events WHERE knowledge_scope_id=scope_id AND event_id<=through_id ORDER BY event_id LOOP
                mid := event.aggregate_id::text;
                stamp := memory_isoformat(event.occurred_at);
                IF event.event_type IN ('assert','revise','consolidate') THEN
                    IF entries ? mid THEN RAISE EXCEPTION 'duplicate immutable authority identity'; END IF;
                    IF event.event_type='revise' THEN
                        target := event.payload->>'supersedes_memory_id';
                        IF NOT entries ? target OR entries->target->>'status'<>'active'
                           OR (entries->target->>'provenance'='hard' AND event.payload->>'provenance'<>'hard') THEN
                            RAISE EXCEPTION 'invalid immutable authority revision';
                        END IF;
                        entries := jsonb_set(entries,ARRAY[target], entries->target || jsonb_build_object(
                            'status','superseded','superseded_by',event.aggregate_id,
                            'valid_to',COALESCE(event.payload->>'valid_from',stamp),'invalidated_at',stamp));
                    END IF;
                    row_data := event.payload || jsonb_build_object('memory_id',event.aggregate_id,'knowledge_scope_id',scope_id,
                        'status',COALESCE(event.payload->>'status','active'),'valid_from',COALESCE(event.payload->>'valid_from',stamp),
                        'valid_to',NULL,'observed_at',stamp,'superseded_by',NULL,'invalidated_at',NULL,'source_event_id',event.event_id);
                    entries := jsonb_set(entries,ARRAY[mid],row_data);
                    salience := jsonb_set(salience,ARRAY[mid],jsonb_build_object('memory_id',event.aggregate_id,'knowledge_scope_id',scope_id,
                        'salience',0.0,'access_count',0,'decay_rate',COALESCE(event.payload->'decay_rate','0.05'::jsonb),
                        'last_access_at',NULL,'reinforced_at',NULL,'evidence_refs',COALESCE(event.payload->'evidence_refs','[]'::jsonb),
                        'provenance',event.payload->'provenance','inference_meta',event.payload->'inference_meta'));
                ELSIF event.event_type='retract' THEN
                    IF NOT entries ? mid THEN RAISE EXCEPTION 'missing immutable authority target'; END IF;
                    entries := jsonb_set(entries,ARRAY[mid],entries->mid || jsonb_build_object('status','retired','valid_to',stamp,'invalidated_at',stamp));
                ELSIF event.event_type='access' THEN
                    IF NOT entries ? mid THEN RAISE EXCEPTION 'missing immutable authority target'; END IF;
                    access_state := salience->mid;
                    age_days := COALESCE(extract(epoch FROM event.occurred_at-(access_state->>'last_access_at')::timestamptz)/86400.0,0);
                    score := greatest(0.0,(access_state->>'salience')::double precision
                        - (access_state->>'decay_rate')::double precision * greatest(0.0,age_days) + 1.0);
                    salience := jsonb_set(salience,ARRAY[mid],access_state || jsonb_build_object('salience',score,
                        'access_count',(access_state->>'access_count')::integer+1,'last_access_at',stamp,'reinforced_at',stamp));
                ELSIF event.event_type='rollback' THEN
                    IF NOT EXISTS (SELECT 1 FROM memory_events WHERE knowledge_scope_id=scope_id
                        AND event_id=(event.payload->>'event_point')::bigint AND event_id<event.event_id)
                        THEN RAISE EXCEPTION 'invalid immutable authority rollback'; END IF;
                    restored := memory_log_state(scope_id,(event.payload->>'event_point')::bigint);
                    FOR pair IN SELECT * FROM jsonb_each(entries) LOOP
                        IF NOT (restored->'entries') ? pair.key THEN
                            entries := jsonb_set(entries,ARRAY[pair.key],pair.value || jsonb_build_object('status','retired','valid_to',stamp,'invalidated_at',stamp));
                        END IF;
                    END LOOP;
                    entries := entries || (restored->'entries');
                    FOR pair IN SELECT * FROM jsonb_each(bindings) LOOP
                        bindings := jsonb_set(bindings,ARRAY[pair.key],pair.value || jsonb_build_object('status','disabled'));
                    END LOOP;
                    bindings := bindings || (restored->'bindings');
                ELSIF event.event_type='grant' AND event.payload ? 'binding_id' THEN
                    SELECT jsonb_object_agg(key,value) INTO row_data FROM jsonb_each(event.payload)
                        WHERE key IN ('binding_id','binding_kind','binding_value','priority','status');
                    bindings := jsonb_set(bindings,ARRAY[event.payload->>'binding_id'],row_data || jsonb_build_object('knowledge_scope_id',scope_id));
                END IF;
            END LOOP;
            FOR pair IN SELECT * FROM jsonb_each(entries) ORDER BY key::bigint LOOP
                row_data := pair.value;
                IF row_data->>'status' IN ('retired','quarantined') THEN CONTINUE; END IF;
                dense := jsonb_set(dense,ARRAY[pair.key],row_data);
                FOR ref IN SELECT * FROM jsonb_array_elements(COALESCE(row_data->'evidence_refs','[]'::jsonb)) LOOP
                    links := jsonb_set(links,ARRAY[pair.key || '/evidence/' || (ref #>> '{}')],row_data ||
                        jsonb_build_object('from_id',pair.key::bigint,'to_id',ref,'relation','evidence'));
                END LOOP;
                IF row_data->>'supersedes_memory_id' IS NOT NULL THEN
                    links := jsonb_set(links,ARRAY[pair.key || '/supersedes'],row_data ||
                        jsonb_build_object('from_id',pair.key::bigint,'to_id',row_data->'supersedes_memory_id','relation','supersedes'));
                END IF;
                branch := scope_id::text || '/' || COALESCE(row_data->>'kind','episodic');
                summary := jsonb_set(summary,ARRAY[branch],COALESCE(summary->branch,'[]'::jsonb) || jsonb_build_array(row_data));
                path := '012-v1/' || branch || '/' || pair.key || '.md';
                files := jsonb_set(files,ARRAY[path],row_data || jsonb_build_object('path',path,
                    'body','# Memory ' || pair.key || chr(10) || chr(10) || memory_sorted_json(row_data)));
            END LOOP;
            RETURN jsonb_build_object('entries',entries,'dense',dense,'links',links,'summary',summary,'files',files,'salience',salience,'bindings',bindings);
        END; $$;
        CREATE OR REPLACE FUNCTION verify_memory_log_projection() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE authority_id bigint; authority_scope bigint; state jsonb; expected jsonb; field text; key text;
        BEGIN
            authority_id := NULLIF(current_setting('rag_memory.reducer_event',true),'')::bigint;
            SELECT knowledge_scope_id INTO authority_scope FROM memory_events WHERE memory_events.event_id=authority_id;
            IF authority_scope IS NULL OR authority_id IS DISTINCT FROM (SELECT max(memory_events.event_id) FROM memory_events WHERE knowledge_scope_id=authority_scope)
                THEN RAISE EXCEPTION 'projection authority requires latest immutable log replay'; END IF;
            state := memory_log_state(authority_scope,authority_id);
            IF TG_TABLE_NAME='memory_entries' THEN
                expected := state->'entries'->NEW.memory_id::text;
                IF expected IS NULL THEN RAISE EXCEPTION 'projection missing log authority'; END IF;
                FOREACH field IN ARRAY ARRAY['status','superseded_by','source_event_id'] LOOP
                    IF to_jsonb(NEW)->field IS DISTINCT FROM expected->field THEN RAISE EXCEPTION 'projection differs from log replay: %',field; END IF;
                END LOOP;
                FOREACH field IN ARRAY ARRAY['valid_from','valid_to','invalidated_at'] LOOP
                    IF (to_jsonb(NEW)->>field)::timestamptz IS DISTINCT FROM (expected->>field)::timestamptz
                        THEN RAISE EXCEPTION 'projection timeline differs from log replay: %',field; END IF;
                END LOOP;
                IF NEW.write_status NOT IN ('complete','failed') THEN RAISE EXCEPTION 'invalid projection completion'; END IF;
            ELSIF TG_TABLE_NAME='memory_salience' THEN
                expected := state->'salience'->NEW.memory_id::text;
                IF expected IS NULL THEN RAISE EXCEPTION 'projection missing log authority'; END IF;
                FOREACH field IN ARRAY ARRAY['access_count','salience','decay_rate'] LOOP
                    IF to_jsonb(NEW)->field IS DISTINCT FROM expected->field THEN RAISE EXCEPTION 'salience differs from log replay: %',field; END IF;
                END LOOP;
                IF NEW.last_access_at IS DISTINCT FROM (expected->>'last_access_at')::timestamptz
                   OR NEW.reinforced_at IS DISTINCT FROM (expected->>'reinforced_at')::timestamptz THEN RAISE EXCEPTION 'salience differs from log replay'; END IF;
            ELSIF TG_TABLE_NAME IN ('memory_links','memory_summary_nodes') THEN
                key := CASE TG_TABLE_NAME WHEN 'memory_links' THEN 'links' ELSE 'summary' END;
                IF NEW.revision_id<>authority_id OR NEW.data IS DISTINCT FROM state->key->NEW.node_key
                    THEN RAISE EXCEPTION 'projection differs from immutable log replay'; END IF;
            ELSIF TG_TABLE_NAME='scope_bindings' THEN
                expected := state->'bindings'->NEW.binding_id::text;
                FOREACH field IN ARRAY ARRAY['binding_id','knowledge_scope_id','binding_kind','binding_value','priority','status'] LOOP
                    IF to_jsonb(NEW)->field IS DISTINCT FROM expected->field THEN RAISE EXCEPTION 'binding differs from immutable log replay'; END IF;
                END LOOP;
            ELSIF TG_TABLE_NAME='memory_projection_meta' THEN
                key := CASE NEW.projection_type WHEN 'relation' THEN 'entries' WHEN 'file' THEN 'files' ELSE NEW.projection_type END;
                expected := CASE WHEN key IN ('manifest','pending') THEN state ELSE state->key END;
                IF NEW.source_event_id<>authority_id OR expected IS NULL OR NEW.payload->'state' IS DISTINCT FROM expected
                    THEN RAISE EXCEPTION 'manifest differs from immutable log replay'; END IF;
            END IF;
            RETURN NEW;
        END; $$;
    """)
    for table in ("memory_entries", "memory_salience", "memory_links", "memory_summary_nodes", "memory_projection_meta", "scope_bindings"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_log_parity ON {table}")
        op.execute(f"CREATE TRIGGER {table}_log_parity BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION verify_memory_log_projection()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM memory_events")).scalar_one():
        raise RuntimeError("cannot remove database authority with retained events")
    for table in ("memory_entries", "memory_salience", "memory_links", "memory_summary_nodes", "memory_projection_meta", "scope_bindings"):
        op.execute(f"DROP TRIGGER {table}_log_parity ON {table}")
    op.execute("DROP FUNCTION verify_memory_log_projection()")
    op.execute("DROP FUNCTION memory_log_state(bigint,bigint)")
    op.execute("DROP FUNCTION memory_sorted_json(jsonb)")
    op.execute("DROP FUNCTION memory_isoformat(timestamptz)")
