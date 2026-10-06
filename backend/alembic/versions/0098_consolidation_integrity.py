"""Guard ordinary hash identity and v2 canonical/final publication authority."""
from alembic import op

revision = '0098_consolidation_integrity'
down_revision = '0097_consolidation_publish_fence'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION assert_consolidation_fence(scope_id bigint) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        DECLARE eligibility consolidation_eligibilities%ROWTYPE; token jsonb; policy jsonb; scope_status text;
        BEGIN
            token := nullif(current_setting('rag_memory.consolidation_fence',true),'')::jsonb;
            SELECT * INTO eligibility FROM consolidation_eligibilities
                WHERE eligibility_id=nullif(current_setting('rag_memory.consolidation_token',true),'')::uuid FOR UPDATE;
            SELECT p.memory_policy,s.status INTO policy,scope_status FROM knowledge_scopes s
                JOIN domain_profiles p ON s.domain_key=p.domain_key WHERE s.scope_id=$1 FOR SHARE OF s,p;
            IF eligibility.eligibility_id IS NULL OR eligibility.state<>'active' OR eligibility.expires_at<=clock_timestamp()
               OR eligibility.knowledge_scope_id<>scope_id
               OR token IS DISTINCT FROM jsonb_build_object('eligibility_id',eligibility.eligibility_id::text,
                  'scope_id',eligibility.knowledge_scope_id,'run_id',eligibility.run_id::text,
                  'holder_instance_id',eligibility.holder_instance_id::text,'writer_lease_id',eligibility.writer_lease_id,
                  'eligibility_version',eligibility.eligibility_version)
               OR NOT lock_consolidation_writer_lease(eligibility.writer_lease_id,eligibility.holder_instance_id)
               OR nullif(current_setting('rag_memory.consolidation_started_at',true),'') IS NULL
               OR clock_timestamp()-nullif(current_setting('rag_memory.consolidation_started_at',true),'')::timestamptz>=interval '30 seconds'
               OR scope_status IS DISTINCT FROM 'active' OR policy->'consolidation_enabled' IS DISTINCT FROM 'true'::jsonb
               OR policy->'consolidation' IS NULL OR policy->'consolidation'='null'::jsonb THEN
                RAISE EXCEPTION 'CONSOLIDATION_PUBLICATION_FENCE_LOST';
            END IF;
        END; $$;

        CREATE OR REPLACE FUNCTION verify_consolidation_publication() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        DECLARE completed bigint; through_id bigint;
        BEGIN
            IF TG_TABLE_NAME='memory_entries' THEN
                IF NEW.write_status<>'complete' THEN RETURN NEW; END IF;
                through_id := nullif(current_setting('rag_memory.reducer_event',true),'')::bigint;
            ELSE
                IF TG_TABLE_NAME='memory_projection_meta' THEN
                    IF NEW.status<>'complete' THEN RETURN NEW; END IF;
                END IF;
                through_id := NEW.source_event_id;
            END IF;
            SELECT source_event_id INTO completed FROM memory_projection_meta
                WHERE projection_id='current:'||NEW.knowledge_scope_id AND status='complete';
            IF EXISTS(SELECT 1 FROM memory_events WHERE knowledge_scope_id=NEW.knowledge_scope_id
                AND event_id>COALESCE(completed,0) AND event_id<=through_id
                AND event_type='consolidate' AND payload->>'payload_version'='2') THEN
                PERFORM assert_consolidation_fence(NEW.knowledge_scope_id);
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER memory_entries_consolidation_fence BEFORE INSERT OR UPDATE ON memory_entries
            FOR EACH ROW EXECUTE FUNCTION verify_consolidation_publication();
        CREATE TRIGGER memory_meta_consolidation_fence BEFORE INSERT OR UPDATE ON memory_projection_meta
            FOR EACH ROW EXECUTE FUNCTION verify_consolidation_publication();

        CREATE FUNCTION guard_memory_creation_hash() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        BEGIN
            IF NEW.event_type NOT IN ('assert','revise','consolidate') THEN RETURN NEW; END IF;
            PERFORM pg_advisory_xact_lock(NEW.knowledge_scope_id);
            IF NEW.event_type='consolidate' AND NEW.payload->>'payload_version'='2' THEN
                PERFORM assert_consolidation_fence(NEW.knowledge_scope_id);
                RETURN NEW;
            END IF;
            IF EXISTS(SELECT 1 FROM memory_events WHERE knowledge_scope_id=NEW.knowledge_scope_id
                AND event_type IN ('assert','revise','consolidate')
                AND payload->>'content_hash'=NEW.payload->>'content_hash') THEN
                RAISE EXCEPTION 'MEMORY_CONTENT_HASH_CONFLICT';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER memory_creation_hash BEFORE INSERT ON memory_events
            FOR EACH ROW EXECUTE FUNCTION guard_memory_creation_hash();
        ALTER TABLE memory_entries DROP CONSTRAINT uq_memory_entries_scope_hash;
        CREATE INDEX ix_memory_entries_scope_hash ON memory_entries(knowledge_scope_id,content_hash);

        CREATE FUNCTION verify_consolidation_canonical() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE pair record; evidence jsonb;
        BEGIN
            IF NEW.event_type<>'consolidate' OR NEW.payload->>'payload_version' IS DISTINCT FROM '2' THEN RETURN NEW; END IF;
            IF NEW.payload->>'operation'='create' THEN
                SELECT jsonb_agg('memory:'||(ref->>'memory_id')) INTO evidence
                    FROM jsonb_array_elements(NEW.payload->'source_refs') ref;
                IF NEW.payload->'confidence' IS DISTINCT FROM NEW.payload->'inference_meta'->'confidence'
                   OR NEW.payload->'confidence_origin' IS DISTINCT FROM NEW.payload->'inference_meta'->'confidence_origin'
                   OR NEW.payload->>'content_hash' IS DISTINCT FROM encode(sha256(convert_to(NEW.payload->>'content_text','UTF8')),'hex')
                   OR NEW.payload->'inference_meta'->'supporting_evidence' IS DISTINCT FROM evidence
                   OR NEW.payload->>'provenance' IS DISTINCT FROM 'distilled'
                   OR NEW.payload->>'kind' NOT IN ('semantic','procedural')
                   OR NEW.payload->'provenance_validation'->'attributions' IS DISTINCT FROM (
                       SELECT jsonb_agg(ref-'state_event_id') FROM jsonb_array_elements(NEW.payload->'source_lineage') ref)
                   OR NEW.payload->'provenance_validation'->'validated' IS DISTINCT FROM 'true'::jsonb THEN
                    RAISE EXCEPTION 'invalid consolidation canonical body or provenance';
                END IF;
                FOR pair IN SELECT * FROM jsonb_each(NEW.payload->'submission_meta') LOOP
                    IF NEW.payload->pair.key IS DISTINCT FROM pair.value THEN
                        RAISE EXCEPTION 'invalid consolidation canonical metadata';
                    END IF;
                END LOOP;
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER memory_consolidation_canonical BEFORE INSERT ON memory_events
            FOR EACH ROW EXECUTE FUNCTION verify_consolidation_canonical();
    """)


def downgrade():
    raise RuntimeError('cannot downgrade immutable memory identity guards')
