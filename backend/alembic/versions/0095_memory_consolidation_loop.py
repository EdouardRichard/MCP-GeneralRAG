"""Add consolidation control records and typed projection columns."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0095_memory_consolidation_loop'
down_revision = '0094_memory_management_audit'
branch_labels = None
depends_on = None

CONTEXT_CHECK = """(trigger IN ('idle','manual','volume') AND execution_context='distiller_window') OR
    (trigger='support_maintenance' AND execution_context='deterministic_propagation'
    AND \"window\" IS NULL AND input_event_ids='[]'::jsonb
    AND jsonb_typeof(historical_source_refs)='array' AND jsonb_array_length(historical_source_refs)>0
    AND jsonb_typeof(propagation_trigger)='object' AND propagation_trigger ? 'proof'
    AND jsonb_typeof(propagation_trigger->'proof')='object' AND propagation_trigger->'proof'<>'{}'::jsonb
    AND (propagation_trigger->>'event_id' IS NOT NULL OR propagation_trigger->>'evidence_id' IS NOT NULL))"""
USAGE_DEFAULT = """'{"embedding_calls": 0,"rerank_calls": 0,"llm_calls": 0,"llm_prompt_chars": 0,
    "llm_completion_chars": 0,"cache_hits": 0,"source": "unavailable",
    "input_tokens": null,"output_tokens": null,"cost_usd": null}'::jsonb"""

ENTRY_COLUMNS = (
    sa.Column('state_event_id', sa.BigInteger()), sa.Column('context_digest', sa.Text()),
    sa.Column('keywords', pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column('context_version', sa.String(128)), sa.Column('context_source_event_id', sa.BigInteger()),
    sa.Column('promotion_pointer', pg.JSONB()), sa.Column('candidate_version', sa.String(64)),
    sa.Column('candidate_basis', pg.JSONB()),
)
LINK_COLUMNS = (
    sa.Column('from_id', sa.String(128)), sa.Column('to_id', sa.String(128)), sa.Column('to_kind', sa.String(16)),
    sa.Column('relation_type', sa.String(64)), sa.Column('provenance', sa.String(32)), sa.Column('confidence', sa.Float()),
    sa.Column('created_by_run', pg.UUID(as_uuid=True)), sa.Column('source_event_id', sa.BigInteger()),
    sa.Column('vocabulary_version', sa.String(64)), sa.Column('semantic_category', sa.String(32)), sa.Column('propagation', sa.String(16)),
)


def replace_function(signature, fragments, *, reverse=False):
    connection = op.get_bind()
    definition = connection.execute(sa.text('SELECT pg_get_functiondef(CAST(:signature AS regprocedure))'),
                                    {'signature': signature}).scalar_one()
    for before, after in fragments:
        old, new = (after, before) if reverse else (before, after)
        if definition.count(old) != 1:
            raise RuntimeError('unexpected consolidation reducer version; refusing partial migration')
        definition = definition.replace(old, new)
    connection.execute(sa.text(definition))


REPLAY_FRAGMENTS = (
    ("bindings jsonb := '{}';", "bindings jsonb := '{}'; windows jsonb := '{}'; unresolved_windows jsonb := '[]';"),
    ("ELSIF event.event_type='grant' THEN", """ELSIF event.event_type='grant' THEN
                    IF event.payload->>'grant_type'='consolidation_window' THEN
                        IF event.actor<>'management' OR event.authority->>'source' IS DISTINCT FROM 'consolidation_control'
                           OR event.payload->'control_adjudication' IS DISTINCT FROM
                              '{"decision":"seal_window","effect":"control_only","rule_version":"013.window.1"}'::jsonb THEN
                            RAISE EXCEPTION 'trusted consolidation control required';
                        END IF;
                        windows := jsonb_set(windows,ARRAY[event.event_id::text],event.payload ||
                            jsonb_build_object('window_id',event.event_id,'knowledge_scope_id',scope_id));
                        unresolved_windows := unresolved_windows || jsonb_build_array(event.event_id);
                    END IF;"""),
    ("'salience',salience,'bindings',bindings)", """'salience',salience,'bindings',bindings,
                'consolidation_state',jsonb_build_object('window_seals',windows,'potential_results','{}'::jsonb,
                    'potential_source_outcomes','{}'::jsonb,'potential_checkpoint',NULL,'unresolved_windows',unresolved_windows))"""),
)

ENTRY_GUARD_FRAGMENTS = (
    ("FOREACH field IN ARRAY ARRAY['status','superseded_by','source_event_id','retention_stage','authority','scope_meta','mutability','provenance_meta','recoverability','actionability'] LOOP", """NEW.state_event_id := COALESCE(NEW.state_event_id,(expected->>'state_event_id')::bigint,(expected->>'source_event_id')::bigint);
                IF NEW.state_event_id IS DISTINCT FROM COALESCE((expected->>'state_event_id')::bigint,(expected->>'source_event_id')::bigint)
                   OR NEW.keywords IS DISTINCT FROM COALESCE(expected->'keywords','[]'::jsonb) THEN
                    RAISE EXCEPTION 'entry consolidation fields differ from log replay';
                END IF;
                FOREACH field IN ARRAY ARRAY['context_digest','context_version','context_source_event_id','promotion_pointer','candidate_version','candidate_basis'] LOOP
                    IF COALESCE(to_jsonb(NEW)->field,'null'::jsonb) IS DISTINCT FROM COALESCE(expected->field,'null'::jsonb) THEN
                        RAISE EXCEPTION 'entry consolidation fields differ from log replay: %',field;
                    END IF;
                END LOOP;
                FOREACH field IN ARRAY ARRAY['status','superseded_by','source_event_id','retention_stage','authority','scope_meta','mutability','provenance_meta','recoverability','actionability'] LOOP"""),
)


def upgrade():
    op.create_table('consolidation_eligibilities',
        sa.Column('eligibility_id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('knowledge_scope_id', sa.BigInteger(), sa.ForeignKey('knowledge_scopes.scope_id'), nullable=False),
        sa.Column('run_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('holder_instance_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('writer_lease_id', sa.BigInteger(), nullable=False),
        sa.Column('eligibility_version', sa.BigInteger(), nullable=False),
        sa.Column('observation_seq_high_water', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('state', sa.String(16), nullable=False, server_default='active'),
        *[sa.Column(name, pg.TIMESTAMP(timezone=True), nullable=False) for name in ('acquired_at', 'renewed_at', 'expires_at')],
        sa.Column('released_at', pg.TIMESTAMP(timezone=True)),
        sa.CheckConstraint("state IN ('active','released','expired')", name='ck_consolidation_eligibility_state'),
        sa.CheckConstraint('eligibility_version>0', name='ck_consolidation_eligibility_version'))
    op.create_index('uq_consolidation_scope_active', 'consolidation_eligibilities', ['knowledge_scope_id'], unique=True,
                    postgresql_where=sa.text("state='active'"))
    op.create_index('uq_consolidation_scope_version', 'consolidation_eligibilities', ['knowledge_scope_id', 'eligibility_version'], unique=True)
    op.create_index('ix_consolidation_active_expiry', 'consolidation_eligibilities', ['expires_at'], postgresql_where=sa.text("state='active'"))
    op.create_table('consolidation_runs',
        sa.Column('run_id', pg.UUID(as_uuid=True), primary_key=True), sa.Column('observation_seq', sa.BigInteger(), primary_key=True),
        sa.Column('knowledge_scope_id', sa.BigInteger(), sa.ForeignKey('knowledge_scopes.scope_id'), nullable=False),
        sa.Column('trigger', sa.String(32), nullable=False), sa.Column('execution_context', sa.String(32), nullable=False),
        sa.Column('request_id', sa.String(128)), sa.Column('actor', sa.String(128)), sa.Column('status', sa.String(32), nullable=False),
        sa.Column('window', pg.JSONB()), sa.Column('propagation_trigger', pg.JSONB()),
        *[sa.Column(name, pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")) for name in (
            'input_event_ids', 'reference_versions', 'historical_source_refs', 'proposals', 'adjudications',
            'output_memory_ids', 'output_event_ids', 'pending_result_keys', 'degradation_reasons')],
        sa.Column('provider_usage', pg.JSONB(), nullable=False, server_default=sa.text(USAGE_DEFAULT)),
        sa.Column('versions', pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('eligibility_id', pg.UUID(as_uuid=True)), sa.Column('eligibility_version', sa.BigInteger()),
        sa.Column('holder_instance_id', pg.UUID(as_uuid=True)), sa.Column('writer_lease_id', sa.BigInteger()),
        sa.Column('eligibility_state', sa.String(16)),
        sa.Column('created_at', pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('ttl_expires_at', pg.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()+interval '7 days'")),
        sa.CheckConstraint('observation_seq>0', name='ck_consolidation_observation_seq'),
        sa.CheckConstraint(CONTEXT_CHECK, name='ck_consolidation_execution_context'),
        sa.CheckConstraint("status IN ('admitted','selecting','proposing','adjudicating','committing','succeeded','no_change','degraded','partial','failed','interrupted')", name='ck_consolidation_observation_status'))
    op.create_index('ix_consolidation_runs_scope_seq', 'consolidation_runs', ['knowledge_scope_id', 'run_id', 'observation_seq'])
    op.create_index('ix_consolidation_runs_expiry', 'consolidation_runs', ['ttl_expires_at'])
    op.add_column('domain_profiles', sa.Column('memory_link_vocabulary', pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('runtime_maintenance_log', sa.Column('purged_consolidation_runs', sa.Integer(), nullable=False, server_default='0'))
    for column in ENTRY_COLUMNS:
        op.add_column('memory_entries', column.copy())
    for column in LINK_COLUMNS:
        op.add_column('memory_links', column.copy())
    # Only this migration backfills existing sealed rows; application guards remain active afterwards.
    op.execute('ALTER TABLE memory_entries DISABLE TRIGGER USER')
    op.execute('UPDATE memory_entries SET state_event_id=source_event_id')
    op.execute('ALTER TABLE memory_entries ENABLE TRIGGER USER')
    op.execute('ALTER TABLE memory_links DISABLE TRIGGER USER')
    op.execute("""UPDATE memory_links SET from_id=data->>'from_id',to_id=data->>'to_id',
        to_kind=CASE data->>'relation' WHEN 'evidence' THEN 'evidence' ELSE 'memory' END,
        relation_type=data->>'relation',provenance='deterministic',source_event_id=(data->>'source_event_id')::bigint,
        vocabulary_version='012-base-v1',semantic_category='historical_lineage',propagation='none'""")
    op.execute('ALTER TABLE memory_links ENABLE TRIGGER USER')
    for name in ('from_id', 'to_id', 'to_kind', 'relation_type', 'provenance', 'vocabulary_version', 'semantic_category', 'propagation'):
        op.alter_column('memory_links', name, nullable=False)
    op.create_unique_constraint('uq_memory_link_revision_edge', 'memory_links', ['knowledge_scope_id', 'revision_id', 'from_id', 'to_id', 'relation_type'])
    for name, expression in (
        ('ck_memory_link_to_kind', "to_kind IN ('memory','evidence')"),
        ('ck_memory_link_provenance', "provenance IN ('deterministic','llm_proposed')"),
        ('ck_memory_link_confidence', 'confidence IS NULL OR confidence BETWEEN 0 AND 1')):
        op.create_check_constraint(name, 'memory_links', expression)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='rag_consolidation_maintenance') THEN
                CREATE ROLE rag_consolidation_maintenance NOLOGIN;
            END IF;
        END $$;
        GRANT rag_consolidation_maintenance TO CURRENT_USER;
        GRANT USAGE ON SCHEMA public TO rag_consolidation_maintenance;
        GRANT SELECT,DELETE ON consolidation_runs TO rag_consolidation_maintenance;
        GRANT SELECT ON writer_lease TO rag_consolidation_maintenance;
        GRANT SELECT,INSERT ON runtime_maintenance_log TO rag_consolidation_maintenance;
        GRANT SELECT,INSERT ON consolidation_runs TO rag_memory_reducer;
        GRANT SELECT,INSERT,UPDATE ON consolidation_eligibilities TO rag_memory_reducer;

        CREATE FUNCTION guard_consolidation_observation_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' AND current_user='rag_consolidation_maintenance'
               AND OLD.ttl_expires_at<clock_timestamp()
               AND EXISTS (SELECT 1 FROM writer_lease WHERE lease_id=nullif(current_setting('rag_memory.writer_lease',true),'')::bigint
                    AND holder_instance_id=nullif(current_setting('rag_memory.writer_holder',true),'')::uuid
                    AND state='active' AND expires_at>clock_timestamp())
               AND EXISTS (SELECT 1 FROM runtime_maintenance_log WHERE log_id=nullif(current_setting('rag_memory.maintenance_log',true),'')::bigint
                    AND purged_consolidation_runs>0 AND created_at>=transaction_timestamp()) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'consolidation_runs is append-only; only live maintenance may purge expired observations';
        END; $$;
        CREATE TRIGGER consolidation_runs_immutable BEFORE UPDATE OR DELETE ON consolidation_runs
            FOR EACH ROW EXECUTE FUNCTION guard_consolidation_observation_mutation();
        CREATE TRIGGER consolidation_runs_no_truncate BEFORE TRUNCATE ON consolidation_runs
            FOR EACH STATEMENT EXECUTE FUNCTION reject_memory_event_mutation();

        CREATE FUNCTION verify_typed_memory_link() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE expected_relation text; base boolean;
        BEGIN
            expected_relation := COALESCE(NEW.data->>'relation_type',NEW.data->>'relation');
            base := expected_relation IN ('evidence','supersedes');
            NEW.from_id := COALESCE(NEW.from_id,NEW.data->>'from_id');
            NEW.to_id := COALESCE(NEW.to_id,NEW.data->>'to_id');
            NEW.relation_type := COALESCE(NEW.relation_type,expected_relation);
            NEW.to_kind := COALESCE(NEW.to_kind,CASE WHEN expected_relation='evidence' THEN 'evidence' ELSE 'memory' END);
            NEW.provenance := COALESCE(NEW.provenance,CASE WHEN base THEN 'deterministic' ELSE NEW.data->>'provenance' END);
            NEW.source_event_id := COALESCE(NEW.source_event_id,(NEW.data->>'source_event_id')::bigint);
            NEW.vocabulary_version := COALESCE(NEW.vocabulary_version,CASE WHEN base THEN '012-base-v1' ELSE NEW.data->>'vocabulary_version' END);
            NEW.semantic_category := COALESCE(NEW.semantic_category,CASE WHEN base THEN 'historical_lineage' ELSE NEW.data->>'category' END);
            NEW.propagation := COALESCE(NEW.propagation,CASE WHEN base THEN 'none' ELSE NEW.data->>'propagation' END);
            IF NEW.from_id IS DISTINCT FROM NEW.data->>'from_id' OR NEW.to_id IS DISTINCT FROM NEW.data->>'to_id'
               OR NEW.relation_type IS DISTINCT FROM expected_relation
               OR NEW.to_kind IS DISTINCT FROM (CASE WHEN expected_relation='evidence' THEN 'evidence' ELSE 'memory' END)
               OR NEW.source_event_id IS DISTINCT FROM (NEW.data->>'source_event_id')::bigint
               OR (base AND (NEW.provenance<>'deterministic' OR NEW.confidence IS NOT NULL OR NEW.created_by_run IS NOT NULL
                   OR NEW.vocabulary_version<>'012-base-v1' OR NEW.semantic_category<>'historical_lineage' OR NEW.propagation<>'none'))
               OR (NOT base AND (NEW.provenance IS DISTINCT FROM NEW.data->>'provenance'
                   OR NEW.confidence IS DISTINCT FROM (NEW.data->>'confidence')::double precision
                   OR NEW.created_by_run IS DISTINCT FROM (NEW.data->>'created_by_run')::uuid
                   OR NEW.vocabulary_version IS DISTINCT FROM NEW.data->>'vocabulary_version'
                   OR NEW.semantic_category IS DISTINCT FROM NEW.data->>'category' OR NEW.propagation IS DISTINCT FROM NEW.data->>'propagation')) THEN
                RAISE EXCEPTION 'typed link differs from immutable data authority';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER memory_links_typed_parity BEFORE INSERT OR UPDATE ON memory_links
            FOR EACH ROW EXECUTE FUNCTION verify_typed_memory_link();
    """)
    replace_function('memory_log_state(bigint,bigint)', REPLAY_FRAGMENTS)
    replace_function('verify_memory_log_projection()', ENTRY_GUARD_FRAGMENTS)
    op.execute("""
        CREATE FUNCTION lock_consolidation_writer_lease(lease_id_value bigint,holder_value uuid) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        DECLARE lease writer_lease%ROWTYPE;
        BEGIN
            SELECT * INTO lease FROM writer_lease WHERE lease_id=lease_id_value FOR SHARE;
            RETURN FOUND AND lease.state='active' AND lease.holder_instance_id=holder_value
                AND lease.expires_at>clock_timestamp();
        END; $$;
        REVOKE ALL ON FUNCTION lock_consolidation_writer_lease(bigint,uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION lock_consolidation_writer_lease(bigint,uuid) TO rag_memory_reducer;
        CREATE FUNCTION guard_consolidation_window_event() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE token jsonb; eligibility consolidation_eligibilities%ROWTYPE; lease writer_lease%ROWTYPE;
            current_manifest memory_projection_meta%ROWTYPE; prefix jsonb; ref jsonb; row_data jsonb; field text;
            start_at timestamptz; end_at timestamptz; high_water bigint; policy jsonb;
        BEGIN
            IF NEW.payload->>'grant_type' IS DISTINCT FROM 'consolidation_window' THEN RETURN NEW; END IF;
            IF current_user<>'rag_memory_reducer' OR NEW.event_type<>'grant' OR NEW.actor<>'management'
               OR NEW.authority->>'source' IS DISTINCT FROM 'consolidation_control'
               OR NEW.payload->'payload_version' IS DISTINCT FROM '2'::jsonb
               OR NEW.payload->'control_adjudication' IS DISTINCT FROM
                  '{"decision":"seal_window","effect":"control_only","rule_version":"013.window.1"}'::jsonb THEN
                RAISE EXCEPTION 'trusted consolidation control required';
            END IF;
            IF jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'
               OR NOT NEW.payload ?& ARRAY['payload_version','grant_type','start','end','frozen_at','high_water_mark',
                   'source_refs','reference_refs','support_refs','original_window_id','captured_policy','captured_vocabulary',
                   'policy_hash','vocabulary_hash','control_adjudication','eligibility_token']
               OR (SELECT count(*) FROM jsonb_object_keys(NEW.payload))<>16
               OR jsonb_typeof(NEW.payload->'captured_policy') IS DISTINCT FROM 'object'
               OR jsonb_typeof(NEW.payload->'captured_vocabulary') IS DISTINCT FROM 'array'
               OR COALESCE(NEW.payload->>'policy_hash','') !~ '^[0-9a-f]{64}$'
               OR COALESCE(NEW.payload->>'vocabulary_hash','') !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'invalid consolidation window seal';
            END IF;
            token := NEW.payload->'eligibility_token';
            IF jsonb_typeof(token) IS DISTINCT FROM 'object'
               OR NOT token ?& ARRAY['eligibility_id','scope_id','run_id','holder_instance_id','writer_lease_id','eligibility_version']
               OR (SELECT count(*) FROM jsonb_object_keys(token))<>6 THEN
                RAISE EXCEPTION 'invalid consolidation window token';
            END IF;
            SELECT * INTO eligibility FROM consolidation_eligibilities WHERE eligibility_id=(token->>'eligibility_id')::uuid FOR UPDATE;
            IF NOT FOUND OR eligibility.state<>'active' OR eligibility.expires_at<=clock_timestamp()
               OR eligibility.knowledge_scope_id<>NEW.knowledge_scope_id OR (token->>'scope_id')::bigint IS DISTINCT FROM NEW.knowledge_scope_id
               OR eligibility.run_id IS DISTINCT FROM (token->>'run_id')::uuid
               OR eligibility.holder_instance_id IS DISTINCT FROM (token->>'holder_instance_id')::uuid
               OR eligibility.writer_lease_id IS DISTINCT FROM (token->>'writer_lease_id')::bigint
               OR eligibility.eligibility_version IS DISTINCT FROM (token->>'eligibility_version')::bigint
               OR current_setting('rag_memory.consolidation_token',true) IS DISTINCT FROM token->>'eligibility_id' THEN
                RAISE EXCEPTION 'ELIGIBILITY_LOST';
            END IF;
            IF NOT lock_consolidation_writer_lease(eligibility.writer_lease_id,eligibility.holder_instance_id) THEN
                RAISE EXCEPTION 'WRITER_LEASE_LOST';
            END IF;
            SELECT profile.memory_policy INTO policy FROM knowledge_scopes scope JOIN domain_profiles profile USING(domain_key)
                WHERE scope.scope_id=NEW.knowledge_scope_id AND scope.status='active';
            IF policy->>'consolidation_enabled' IS DISTINCT FROM 'true' OR policy->'consolidation' IS NULL
               OR policy->'consolidation'='null'::jsonb THEN RAISE EXCEPTION 'CONSOLIDATION_DISABLED'; END IF;
            high_water := (NEW.payload->>'high_water_mark')::bigint;
            start_at := (NEW.payload->>'start')::timestamptz; end_at := (NEW.payload->>'end')::timestamptz;
            SELECT * INTO current_manifest FROM memory_projection_meta WHERE projection_id='current:'||NEW.knowledge_scope_id;
            IF NOT FOUND OR current_manifest.status<>'complete' OR current_manifest.source_event_id<high_water
               OR high_water IS NULL OR high_water<=0 OR start_at IS NULL OR end_at IS NULL
               OR NEW.payload->>'frozen_at' IS NULL
               OR high_water>=NEW.event_id OR start_at>end_at OR end_at IS DISTINCT FROM (NEW.payload->>'frozen_at')::timestamptz
               OR jsonb_typeof(NEW.payload->'source_refs') IS DISTINCT FROM 'array'
               OR jsonb_array_length(NEW.payload->'source_refs')=0 THEN
                RAISE EXCEPTION 'invalid consolidation window prefix';
            END IF;
            prefix := memory_log_state(NEW.knowledge_scope_id,high_water);
            FOREACH field IN ARRAY ARRAY['source_refs','reference_refs','support_refs'] LOOP
                IF jsonb_typeof(NEW.payload->field) IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'invalid window read set'; END IF;
                FOR ref IN SELECT * FROM jsonb_array_elements(NEW.payload->field) LOOP
                    row_data := prefix->'entries'->(ref->>'memory_id');
                    IF row_data IS NULL OR row_data->>'status'<>'active'
                       OR row_data->>'source_event_id' IS DISTINCT FROM ref->>'source_event_id'
                       OR COALESCE(row_data->>'state_event_id',row_data->>'source_event_id') IS DISTINCT FROM ref->>'state_event_id'
                       OR row_data->>'content_hash' IS DISTINCT FROM ref->>'content_hash'
                       OR (row_data->>'observed_at')::timestamptz IS DISTINCT FROM (ref->>'observed_at')::timestamptz
                       OR (row_data->>'expires_at')::timestamptz<=end_at
                       OR (field='source_refs' AND (row_data->>'kind'<>'episodic'
                           OR (row_data->>'observed_at')::timestamptz<start_at OR (row_data->>'observed_at')::timestamptz>=end_at))
                       OR (field='reference_refs' AND row_data->>'kind' NOT IN ('semantic','procedural')) THEN
                        RAISE EXCEPTION 'SOURCE_NOT_ELIGIBLE';
                    END IF;
                END LOOP;
            END LOOP;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER memory_events_window_control BEFORE INSERT ON memory_events
            FOR EACH ROW EXECUTE FUNCTION guard_consolidation_window_event();
    """)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM memory_events WHERE payload->>'payload_version'='2'")).scalar_one():
        raise RuntimeError('cannot downgrade consolidation with retained v2 authority events')
    op.execute('DROP TRIGGER memory_events_window_control ON memory_events')
    op.execute('DROP FUNCTION guard_consolidation_window_event()')
    op.execute('DROP FUNCTION IF EXISTS lock_consolidation_writer_lease(bigint,uuid)')
    replace_function('verify_memory_log_projection()', ENTRY_GUARD_FRAGMENTS, reverse=True)
    replace_function('memory_log_state(bigint,bigint)', REPLAY_FRAGMENTS, reverse=True)
    op.execute('DROP TRIGGER memory_links_typed_parity ON memory_links')
    op.execute('DROP FUNCTION verify_typed_memory_link()')
    for constraint in ('uq_memory_link_revision_edge', 'ck_memory_link_to_kind', 'ck_memory_link_provenance', 'ck_memory_link_confidence'):
        op.drop_constraint(constraint, 'memory_links')
    for column in LINK_COLUMNS:
        op.drop_column('memory_links', column.name)
    for column in ENTRY_COLUMNS:
        op.drop_column('memory_entries', column.name)
    op.drop_column('domain_profiles', 'memory_link_vocabulary')
    op.drop_column('runtime_maintenance_log', 'purged_consolidation_runs')
    op.drop_table('consolidation_runs')
    op.drop_table('consolidation_eligibilities')
    op.execute('DROP FUNCTION guard_consolidation_observation_mutation()')
