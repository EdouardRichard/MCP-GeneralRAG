"""Require transaction-bound six-view verification for completion publication."""
from alembic import op
import sqlalchemy as sa

revision = "0092_memory_verified_publication"
down_revision = "0091_memory_governance_axes"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='rag_memory_publisher') THEN
                CREATE ROLE rag_memory_publisher NOLOGIN;
            END IF;
        END $$;
        GRANT rag_memory_publisher TO CURRENT_USER;
        GRANT USAGE ON SCHEMA public TO rag_memory_publisher;
        CREATE TABLE memory_projection_receipts (
            knowledge_scope_id bigint NOT NULL,
            source_event_id bigint NOT NULL,
            transaction_id bigint NOT NULL,
            state_fingerprint text NOT NULL,
            fingerprints jsonb NOT NULL,
            collection text NOT NULL,
            root text NOT NULL,
            dense_revision bigint NOT NULL,
            report jsonb NOT NULL,
            PRIMARY KEY (knowledge_scope_id, source_event_id, transaction_id)
        );
        REVOKE ALL ON memory_projection_receipts FROM PUBLIC,rag_memory_reader,rag_memory_reducer;
        GRANT INSERT ON memory_projection_receipts TO rag_memory_publisher;

        CREATE FUNCTION guard_memory_verification_receipt() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE projection text;
        BEGIN
            IF current_user <> 'rag_memory_publisher' OR NEW.transaction_id <> txid_current()
               OR NEW.dense_revision <> NEW.source_event_id THEN
                RAISE EXCEPTION 'publication verification requires trusted publisher';
            END IF;
            FOREACH projection IN ARRAY ARRAY['relation','dense','links','summary','file','salience'] LOOP
                IF NEW.report->projection->'matches_replay' IS DISTINCT FROM 'true'::jsonb
                   OR NEW.fingerprints->>projection IS NULL THEN
                    RAISE EXCEPTION 'publication requires six verified projections';
                END IF;
            END LOOP;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER memory_receipt_insert BEFORE INSERT ON memory_projection_receipts
            FOR EACH ROW EXECUTE FUNCTION guard_memory_verification_receipt();
        CREATE TRIGGER memory_receipt_immutable BEFORE UPDATE OR DELETE ON memory_projection_receipts
            FOR EACH ROW EXECUTE FUNCTION reject_memory_projection_delete();
        CREATE TRIGGER memory_receipt_no_truncate BEFORE TRUNCATE ON memory_projection_receipts
            FOR EACH STATEMENT EXECUTE FUNCTION reject_memory_projection_delete();

        CREATE FUNCTION verify_memory_publication() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        DECLARE receipt memory_projection_receipts%ROWTYPE; event_id bigint; expected_id text;
        BEGIN
            IF TG_TABLE_NAME='memory_entries' THEN
                IF NEW.write_status<>'complete' THEN RETURN NEW; END IF;
            ELSE
                IF NEW.status<>'complete' THEN RETURN NEW; END IF;
            END IF;
            event_id := nullif(current_setting('rag_memory.reducer_event',true),'')::bigint;
            SELECT * INTO receipt FROM memory_projection_receipts
                WHERE knowledge_scope_id=NEW.knowledge_scope_id AND source_event_id=event_id
                  AND transaction_id=txid_current();
            IF NOT FOUND THEN RAISE EXCEPTION 'completion publication requires current verification receipt'; END IF;
            IF TG_TABLE_NAME='memory_projection_meta' THEN
                expected_id := CASE WHEN NEW.projection_type='manifest' THEN 'current:'||NEW.knowledge_scope_id
                    ELSE NEW.knowledge_scope_id||':'||event_id||':'||NEW.projection_type END;
                IF NEW.projection_id<>expected_id OR NEW.source_event_id<>event_id
                   OR NEW.payload->>'collection' IS DISTINCT FROM receipt.collection
                   OR NEW.payload->>'root' IS DISTINCT FROM receipt.root
                   OR (NEW.payload->>'dense_revision')::bigint IS DISTINCT FROM receipt.dense_revision
                   OR NEW.fingerprint IS DISTINCT FROM (CASE WHEN NEW.projection_type='manifest'
                       THEN receipt.state_fingerprint ELSE receipt.fingerprints->>NEW.projection_type END) THEN
                    RAISE EXCEPTION 'publication descriptor differs from verified projections';
                END IF;
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER memory_entries_publication BEFORE INSERT OR UPDATE ON memory_entries
            FOR EACH ROW EXECUTE FUNCTION verify_memory_publication();
        CREATE TRIGGER memory_meta_publication BEFORE INSERT OR UPDATE ON memory_projection_meta
            FOR EACH ROW EXECUTE FUNCTION verify_memory_publication();
    """)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM memory_events")).scalar_one():
        raise RuntimeError("cannot weaken publication guards with retained authority")
    op.execute("DROP TRIGGER memory_entries_publication ON memory_entries")
    op.execute("DROP TRIGGER memory_meta_publication ON memory_projection_meta")
    op.execute("DROP FUNCTION verify_memory_publication()")
    op.execute("DROP TABLE memory_projection_receipts")
    op.execute("DROP FUNCTION guard_memory_verification_receipt()")
