"""Install v2 atomic groups and replay after the deployed 0095 schema."""
from alembic import op
import sqlalchemy as sa

revision = '0096_consolidation_authority'
down_revision = '0095_memory_consolidation_loop'
branch_labels = None
depends_on = None


def replace_function(signature, fragments):
    connection = op.get_bind()
    definition = connection.execute(sa.text('SELECT pg_get_functiondef(CAST(:signature AS regprocedure))'),
                                    {'signature': signature}).scalar_one()
    for before, after in fragments:
        if definition.count(before) != 1:
            raise RuntimeError(f'unexpected predecessor function {signature}: {before!r}')
        definition = definition.replace(before, after)
    connection.execute(sa.text(definition))


def upgrade():
    replace_function('memory_log_state(bigint,bigint)', (
        ("unresolved_windows jsonb := '[]';", """unresolved_windows jsonb := '[]'; results jsonb := '{}';
            outcomes jsonb := '{}'; checkpoint text; effect jsonb; item jsonb; member record; identity jsonb;
            group_key text; v2 boolean; context_value jsonb; registry jsonb;"""),
        ("IF event.event_type IN ('assert','revise','consolidate') THEN", """
                v2 := event.event_type='consolidate' AND event.payload->>'payload_version'='2';
                IF v2 THEN
                    group_key := event.payload->>'group_key';
                    IF (SELECT count(*) FROM memory_events WHERE knowledge_scope_id=scope_id AND event_id<=through_id
                        AND event_type='consolidate' AND payload->>'group_key'=group_key) < (event.payload->>'effect_count')::int
                    THEN CONTINUE; END IF;
                END IF;
                IF v2 AND event.payload->>'operation'<>'create' THEN
                    IF NOT entries ? mid THEN RAISE EXCEPTION 'missing consolidation target'; END IF;
                    effect := event.payload->'approved_effect';
                    row_data := entries->mid;
                    IF event.payload->>'operation' IN ('merge','invalidate') THEN
                        row_data := row_data || jsonb_build_object('status',effect->'lifecycle'->'status',
                            'valid_to',effect->'lifecycle'->'valid_to','invalidated_at',stamp,
                            'superseded_by',effect->'lifecycle'->'replacement_id','retention_stage','tombstone');
                    END IF;
                    IF effect ? 'context' THEN
                        context_value := effect->'context';
                        row_data := row_data || jsonb_build_object('context_digest',context_value->'context_digest',
                            'keywords',context_value->'keywords','context_version',context_value->'context_version',
                            'context_source_event_id',event.event_id,'context',context_value);
                    END IF;
                    IF effect ? 'candidate' THEN
                        row_data := row_data || jsonb_build_object('promote_candidate_at',effect->'candidate'->'promote_candidate_at',
                            'candidate_version',effect->'candidate'->'candidate_version','candidate_basis',effect->'candidate');
                    END IF;
                    IF jsonb_array_length(effect->'links')>0 THEN
                        registry := COALESCE(row_data->'approved_links','{}'::jsonb);
                        FOR item IN SELECT * FROM jsonb_array_elements(effect->'links') LOOP
                            registry := jsonb_set(registry,ARRAY[item->>'from_id'||'/'||(item->>'relation_type')||'/'||(item->>'to_id')],
                                item || jsonb_build_object('knowledge_scope_id',scope_id,'source_event_id',event.event_id));
                        END LOOP;
                        row_data := row_data || jsonb_build_object('approved_links',registry);
                    END IF;
                    entries := jsonb_set(entries,ARRAY[mid],row_data || jsonb_build_object('state_event_id',event.event_id));
                ELSIF event.event_type IN ('assert','revise','consolidate') THEN"""),
        ("entries := jsonb_set(entries,ARRAY[mid],row_data);\n                    salience :=", """IF v2 THEN row_data := row_data || jsonb_build_object('state_event_id',event.event_id); END IF;
                    entries := jsonb_set(entries,ARRAY[mid],row_data);
                    salience :="""),
        ("entries := entries || (restored->'entries');", """entries := entries || (restored->'entries');
                    IF event.payload->>'payload_version'='2' THEN
                        FOR pair IN SELECT * FROM jsonb_each(entries) LOOP
                            entries := jsonb_set(entries,ARRAY[pair.key],pair.value || jsonb_build_object('state_event_id',event.event_id));
                        END LOOP;
                        FOR pair IN SELECT * FROM jsonb_each(results) LOOP
                            results := jsonb_set(results,ARRAY[pair.key],pair.value || jsonb_build_object('rolled_back',true));
                        END LOOP;
                        results := results || restored->'consolidation_state'->'potential_results';
                        outcomes := restored->'consolidation_state'->'potential_source_outcomes';
                        checkpoint := restored->'consolidation_state'->>'potential_checkpoint';
                        windows := restored->'consolidation_state'->'window_seals';
                        unresolved_windows := restored->'consolidation_state'->'unresolved_windows';
                    END IF;"""),
        ("            END LOOP;\n            FOR pair IN SELECT * FROM jsonb_each(entries)", """                IF v2 AND (event.payload->>'effect_index')::int=(event.payload->>'effect_count')::int-1 THEN
                    SELECT jsonb_build_object('group_id',event.payload->'group_id',
                        'event_ids',jsonb_agg(event_id ORDER BY event_id),
                        'memory_ids',COALESCE(jsonb_agg(aggregate_id ORDER BY event_id) FILTER (WHERE payload->>'operation'='create'),'[]'::jsonb),
                        'window_id',event.payload->'window_id','rolled_back',false) INTO row_data
                        FROM memory_events WHERE knowledge_scope_id=scope_id AND event_id<=through_id
                          AND event_type='consolidate' AND payload->>'group_key'=group_key;
                    results := jsonb_set(results,ARRAY[group_key],row_data);
                    FOR member IN SELECT * FROM memory_events WHERE knowledge_scope_id=scope_id AND event_id<=through_id
                        AND event_type='consolidate' AND payload->>'group_key'=group_key ORDER BY event_id LOOP
                        FOR item IN SELECT * FROM jsonb_array_elements(member.payload->'source_outcomes') LOOP
                            SELECT r INTO ref FROM jsonb_array_elements(member.payload->'source_refs') r
                                WHERE r->'source_event_id'=item->'source_event_id' LIMIT 1;
                            identity := jsonb_build_array(ref->'memory_id',ref->'source_event_id',ref->'state_event_id');
                            outcomes := jsonb_set(outcomes,ARRAY[(ref->>'memory_id')||'/'||(ref->>'source_event_id')||'/'||(ref->>'state_event_id')],
                                item || jsonb_build_object('source_version',identity));
                        END LOOP;
                    END LOOP;
                    IF windows ? (event.payload->>'window_id') THEN
                        checkpoint := greatest(checkpoint,windows->(event.payload->>'window_id')->>'end');
                    END IF;
                END IF;
            END LOOP;
            FOR pair IN SELECT * FROM jsonb_each(entries)"""),
        ("summary := jsonb_set(summary,ARRAY[branch],COALESCE(summary->branch,'[]'::jsonb) || jsonb_build_array(row_data));",
         """summary := jsonb_set(summary,ARRAY[branch],COALESCE(summary->branch,'[]'::jsonb) || jsonb_build_array(row_data));
                links := links || COALESCE(row_data->'approved_links','{}'::jsonb);"""),
        ("'potential_results','{}'::jsonb,\n                    'potential_source_outcomes','{}'::jsonb,'potential_checkpoint',NULL",
         "'potential_results',results,\n                    'potential_source_outcomes',outcomes,'potential_checkpoint',checkpoint"),
    ))
    replace_function('verify_memory_source_fields()', ((
        "OR NEW.promote_candidate_at IS DISTINCT FROM (source_record.payload->>'promote_candidate_at')::timestamptz",
        "OR NEW.promote_candidate_at IS DISTINCT FROM (memory_log_state(NEW.knowledge_scope_id,nullif(current_setting('rag_memory.reducer_event',true),'')::bigint)->'entries'->NEW.memory_id::text->>'promote_candidate_at')::timestamptz"),))
    op.execute("""
        CREATE UNIQUE INDEX uq_consolidation_member ON memory_events
            (knowledge_scope_id,(payload->>'group_key'),((payload->>'effect_index')::int))
            WHERE event_type='consolidate' AND payload->>'payload_version'='2';
        CREATE UNIQUE INDEX uq_consolidation_root ON memory_events (knowledge_scope_id,(payload->>'group_key'))
            WHERE event_type='consolidate' AND payload->>'payload_version'='2' AND payload->>'effect_index'='0';
        CREATE FUNCTION guard_consolidation_effect() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE eligibility consolidation_eligibilities%ROWTYPE; source jsonb; ref jsonb; root_id bigint;
        BEGIN
            IF NEW.event_type<>'consolidate' OR NEW.payload->>'payload_version' IS DISTINCT FROM '2' THEN RETURN NEW; END IF;
            SELECT * INTO eligibility FROM consolidation_eligibilities WHERE eligibility_id=
                nullif(current_setting('rag_memory.consolidation_token',true),'')::uuid FOR UPDATE;
            IF eligibility.eligibility_id IS NULL OR eligibility.state<>'active' OR eligibility.expires_at<=clock_timestamp()
               OR eligibility.knowledge_scope_id<>NEW.knowledge_scope_id OR eligibility.run_id::text<>NEW.payload->>'created_by_run'
               OR NOT lock_consolidation_writer_lease(eligibility.writer_lease_id,eligibility.holder_instance_id)
               OR NEW.actor<>'consolidation_service' OR NEW.authority->>'source'<>'consolidation_adjudicator'
               OR NEW.scope_meta<>jsonb_build_object('knowledge_scope_id',NEW.knowledge_scope_id)
               OR NEW.aggregate_id IS DISTINCT FROM (NEW.payload->'approved_effect'->>'memory_id')::bigint
               OR NEW.payload->'adjudication'->>'decision' IS DISTINCT FROM 'accept'
               OR NEW.payload->>'operation' NOT IN ('create','merge','invalidate','derive')
               OR (NEW.payload->>'effect_count')::int NOT BETWEEN 1 AND 128
               OR (NEW.payload->>'effect_index')::int NOT BETWEEN 0 AND (NEW.payload->>'effect_count')::int-1
               OR NEW.payload->'source_lineage' IS DISTINCT FROM NEW.payload->'source_refs'
               OR jsonb_array_length(NEW.payload->'source_refs')=0 THEN
                RAISE EXCEPTION 'invalid trusted consolidation authority';
            END IF;
            SELECT min(event_id) INTO root_id FROM memory_events WHERE knowledge_scope_id=NEW.knowledge_scope_id
                AND event_type='consolidate' AND payload->>'group_key'=NEW.payload->>'group_key';
            root_id := COALESCE(root_id,NEW.event_id);
            FOR ref IN SELECT * FROM jsonb_array_elements(NEW.payload->'source_refs') LOOP
                source := memory_log_state(NEW.knowledge_scope_id,root_id-1)->'entries'->(ref->>'memory_id');
                IF source IS NULL OR source->>'status'<>'active' OR source->>'kind'<>'episodic'
                   OR source->'source_event_id' IS DISTINCT FROM ref->'source_event_id'
                   OR COALESCE(source->'state_event_id',source->'source_event_id') IS DISTINCT FROM ref->'state_event_id'
                   OR source->'content_hash' IS DISTINCT FROM ref->'content_hash'
                   OR (source->>'expires_at')::timestamptz<=clock_timestamp() THEN
                    RAISE EXCEPTION 'invalid consolidation source version';
                END IF;
            END LOOP;
            FOR ref IN SELECT * FROM jsonb_array_elements(NEW.payload->'source_outcomes') LOOP
                IF ref->>'required_group_key' IS DISTINCT FROM NEW.payload->>'group_key' THEN
                    RAISE EXCEPTION 'invalid consolidation outcome group';
                END IF;
            END LOOP;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER memory_consolidation_effect BEFORE INSERT ON memory_events
            FOR EACH ROW EXECUTE FUNCTION guard_consolidation_effect();

        CREATE FUNCTION verify_consolidation_group() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE members int; indexes int; roots int; variants int; maximum int;
        BEGIN
            IF NEW.event_type<>'consolidate' OR NEW.payload->>'payload_version' IS DISTINCT FROM '2' THEN RETURN NEW; END IF;
            SELECT count(*),count(DISTINCT payload->>'effect_index'),
                count(*) FILTER (WHERE payload->>'effect_index'='0'),
                count(DISTINCT jsonb_build_array(payload->'group_id',payload->'effect_count',payload->'window_id',payload->'created_by_run')),
                max((payload->>'effect_index')::int)
                INTO members,indexes,roots,variants,maximum FROM memory_events
                WHERE knowledge_scope_id=NEW.knowledge_scope_id AND event_type='consolidate'
                  AND payload->>'group_key'=NEW.payload->>'group_key';
            IF members<>(NEW.payload->>'effect_count')::int OR members<>indexes OR roots<>1 OR variants<>1 OR maximum<>members-1 THEN
                RAISE EXCEPTION 'incomplete consolidation group';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE CONSTRAINT TRIGGER memory_consolidation_group AFTER INSERT ON memory_events
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION verify_consolidation_group();
    """)


def downgrade():
    raise RuntimeError('cannot discard consolidation authority; use compatible forward deployment')
