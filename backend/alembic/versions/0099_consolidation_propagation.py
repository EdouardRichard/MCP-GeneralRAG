"""Guard deterministic_propagation effects and the propagation continuation seal.

Deployed predecessors 0095-0098 are frozen; this successor adds only the
trusted support-maintenance surface: the publication fence learns a narrow
maintenance allowance keyed to the exact live eligibility identity, the effect
guard gains the historical-lineage branch for propagation events, and the new
control grant `consolidation_propagation` gets the same trusted-source guard
style as the window seal (without any policy gate). memory_log_state keeps
byte-exact parity: propagation_seals only appears once a seal exists.
"""
from alembic import op
import sqlalchemy as sa

revision = '0099_consolidation_propagation'
down_revision = '0098_consolidation_integrity'
branch_labels = None
depends_on = None

PROPAGATION_ADJUDICATION = '{"decision":"seal_propagation","effect":"control_only","rule_version":"013.propagation.1"}'


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
    replace_function('assert_consolidation_fence(bigint)', ((
        """               OR scope_status IS DISTINCT FROM 'active' OR policy->'consolidation_enabled' IS DISTINCT FROM 'true'::jsonb
               OR policy->'consolidation' IS NULL OR policy->'consolidation'='null'::jsonb THEN""",
        """               OR scope_status IS DISTINCT FROM 'active'
               OR (nullif(current_setting('rag_memory.consolidation_maintenance',true),'')
                       IS DISTINCT FROM eligibility.eligibility_id::text
                   AND (policy->'consolidation_enabled' IS DISTINCT FROM 'true'::jsonb
                        OR policy->'consolidation' IS NULL OR policy->'consolidation'='null'::jsonb)) THEN""",
    ),))
    replace_function('guard_consolidation_effect()', ((
        """            FOR ref IN SELECT * FROM jsonb_array_elements(NEW.payload->'source_refs') LOOP
                source := memory_log_state(NEW.knowledge_scope_id,root_id-1)->'entries'->(ref->>'memory_id');
                IF source IS NULL OR source->>'status'<>'active' OR source->>'kind'<>'episodic'
                   OR source->'source_event_id' IS DISTINCT FROM ref->'source_event_id'
                   OR COALESCE(source->'state_event_id',source->'source_event_id') IS DISTINCT FROM ref->'state_event_id'
                   OR source->'content_hash' IS DISTINCT FROM ref->'content_hash'
                   OR (source->>'expires_at')::timestamptz<=clock_timestamp() THEN
                    RAISE EXCEPTION 'invalid consolidation source version';
                END IF;
            END LOOP;""",
        """            IF NEW.payload->>'execution_context'='deterministic_propagation' THEN
                IF NEW.payload->>'operation'<>'invalidate' OR NEW.payload->>'action'<>'invalidate_contradiction'
                   OR NEW.payload->>'window_id' IS NOT NULL OR NEW.payload->'propagation' IS NULL
                   OR NEW.payload->'propagation'='null'::jsonb
                   OR jsonb_array_length(NEW.payload->'source_outcomes')<>0
                   OR NEW.payload->>'confidence_origin'<>'deterministic_rule'
                   OR jsonb_array_length(NEW.payload->'approved_effect'->'links')<>0
                   OR NEW.payload->'approved_effect' ? 'context' OR NEW.payload->'approved_effect' ? 'candidate' THEN
                    RAISE EXCEPTION 'invalid consolidation propagation effect';
                END IF;
                FOR ref IN SELECT * FROM jsonb_array_elements(NEW.payload->'source_refs') LOOP
                    source := memory_log_state(NEW.knowledge_scope_id,root_id-1)->'entries'->(ref->>'memory_id');
                    IF source IS NULL
                       OR source->'source_event_id' IS DISTINCT FROM ref->'source_event_id'
                       OR COALESCE(source->'state_event_id',source->'source_event_id') IS DISTINCT FROM ref->'state_event_id'
                       OR source->'content_hash' IS DISTINCT FROM ref->'content_hash' THEN
                        RAISE EXCEPTION 'invalid consolidation historical lineage';
                    END IF;
                END LOOP;
            ELSE
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
            END IF;""",
    ),))
    replace_function('memory_log_state(bigint,bigint)', (
        ("""unresolved_windows jsonb := '[]'; results jsonb := '{}';""",
         """unresolved_windows jsonb := '[]'; results jsonb := '{}';
            propagations jsonb := '{}';"""),
        ("""                        unresolved_windows := restored->'consolidation_state'->'unresolved_windows';""",
         """                        unresolved_windows := restored->'consolidation_state'->'unresolved_windows';
                        propagations := COALESCE(restored->'consolidation_state'->'propagation_seals','{}'::jsonb);"""),
        ("""                        unresolved_windows := unresolved_windows || jsonb_build_array(event.event_id);
                    END IF;
                    IF event.payload ? 'binding_id' THEN""",
         """                        unresolved_windows := unresolved_windows || jsonb_build_array(event.event_id);
                    END IF;
                    IF event.payload->>'grant_type'='consolidation_propagation' THEN
                        IF event.actor<>'management' OR event.authority->>'source' IS DISTINCT FROM 'consolidation_control'
                           OR event.payload->'control_adjudication' IS DISTINCT FROM
                              '""" + PROPAGATION_ADJUDICATION + """'::jsonb THEN
                            RAISE EXCEPTION 'trusted consolidation control required';
                        END IF;
                        propagations := jsonb_set(propagations,ARRAY[event.event_id::text],event.payload ||
                            jsonb_build_object('seal_id',event.event_id,'knowledge_scope_id',scope_id));
                    END IF;
                    IF event.payload ? 'binding_id' THEN"""),
        ("""                    IF windows ? (event.payload->>'window_id') THEN""",
         """                    IF event.payload->>'window_id' IS NOT NULL
                       AND windows ? (event.payload->>'window_id') THEN"""),
        ("""                'consolidation_state',jsonb_build_object('window_seals',windows,'potential_results',results,
                    'potential_source_outcomes',outcomes,'potential_checkpoint',checkpoint,'unresolved_windows',unresolved_windows));""",
         """                'consolidation_state',jsonb_build_object('window_seals',windows,'potential_results',results,
                    'potential_source_outcomes',outcomes,'potential_checkpoint',checkpoint,'unresolved_windows',unresolved_windows)
                    || CASE WHEN propagations='{}'::jsonb THEN '{}'::jsonb
                            ELSE jsonb_build_object('propagation_seals',propagations) END);"""),
    ))
    op.execute("""
        CREATE FUNCTION guard_consolidation_propagation_event() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE token jsonb; eligibility consolidation_eligibilities%ROWTYPE;
        BEGIN
            IF NEW.event_type<>'grant' OR NEW.payload->>'grant_type' IS DISTINCT FROM 'consolidation_propagation'
               THEN RETURN NEW; END IF;
            IF current_user<>'rag_memory_reducer' OR NEW.actor<>'management'
               OR NEW.authority->>'source' IS DISTINCT FROM 'consolidation_control'
               OR NEW.payload->>'payload_version' IS DISTINCT FROM '2'::jsonb
               OR NEW.payload->'control_adjudication' IS DISTINCT FROM
                  '@ADJ@'::jsonb THEN
                RAISE EXCEPTION 'trusted consolidation control required';
            END IF;
            IF jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'
               OR NOT NEW.payload ?& ARRAY['payload_version','grant_type','trigger','visited_memory_ids','depth',
                   'frontier_memory_ids','continuation_key','vocabulary_version','control_adjudication',
                   'eligibility_token']
               OR (SELECT count(*) FROM jsonb_object_keys(NEW.payload))<>10
               OR COALESCE(NEW.payload->>'continuation_key','') !~ '^[0-9a-f]{64}$'
               OR COALESCE(NEW.payload->>'vocabulary_version','') !~ '^[0-9a-f]{64}$'
               OR jsonb_typeof(NEW.payload->'trigger') IS DISTINCT FROM 'object'
               OR jsonb_typeof(NEW.payload->'trigger'->'proof') IS DISTINCT FROM 'object'
               OR NEW.payload->'trigger'->'proof'='{}'::jsonb
               OR (NEW.payload->'trigger'->>'event_id' IS NULL
                   AND NEW.payload->'trigger'->>'evidence_id' IS NULL)
               OR (NEW.payload->>'depth')::int NOT BETWEEN 0 AND 32
               OR jsonb_typeof(NEW.payload->'visited_memory_ids') IS DISTINCT FROM 'array'
               OR jsonb_array_length(NEW.payload->'visited_memory_ids') NOT BETWEEN 1 AND 128
               OR jsonb_typeof(NEW.payload->'frontier_memory_ids') IS DISTINCT FROM 'array'
               OR jsonb_array_length(NEW.payload->'frontier_memory_ids')>5000 THEN
                RAISE EXCEPTION 'invalid consolidation propagation seal';
            END IF;
            token := NEW.payload->'eligibility_token';
            IF jsonb_typeof(token) IS DISTINCT FROM 'object'
               OR NOT token ?& ARRAY['eligibility_id','scope_id','run_id','holder_instance_id',
                   'writer_lease_id','eligibility_version']
               OR (SELECT count(*) FROM jsonb_object_keys(token))<>6 THEN
                RAISE EXCEPTION 'invalid consolidation window token';
            END IF;
            SELECT * INTO eligibility FROM consolidation_eligibilities
                WHERE eligibility_id=(token->>'eligibility_id')::uuid FOR UPDATE;
            IF NOT FOUND OR eligibility.state<>'active' OR eligibility.expires_at<=clock_timestamp()
               OR eligibility.knowledge_scope_id<>NEW.knowledge_scope_id
               OR (token->>'scope_id')::bigint IS DISTINCT FROM NEW.knowledge_scope_id
               OR eligibility.run_id IS DISTINCT FROM (token->>'run_id')::uuid
               OR eligibility.holder_instance_id IS DISTINCT FROM (token->>'holder_instance_id')::uuid
               OR eligibility.writer_lease_id IS DISTINCT FROM (token->>'writer_lease_id')::bigint
               OR eligibility.eligibility_version IS DISTINCT FROM (token->>'eligibility_version')::bigint
               OR current_setting('rag_memory.consolidation_token',true) IS DISTINCT FROM token->>'eligibility_id'
               THEN RAISE EXCEPTION 'ELIGIBILITY_LOST'; END IF;
            IF NOT lock_consolidation_writer_lease(eligibility.writer_lease_id,eligibility.holder_instance_id)
               THEN RAISE EXCEPTION 'WRITER_LEASE_LOST'; END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER memory_events_propagation_control BEFORE INSERT ON memory_events
            FOR EACH ROW EXECUTE FUNCTION guard_consolidation_propagation_event();
    """.replace('@ADJ@', PROPAGATION_ADJUDICATION))


def downgrade():
    raise RuntimeError('cannot downgrade consolidation authority; use compatible forward deployment')
