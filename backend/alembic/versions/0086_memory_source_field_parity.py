"""A scoped reducer event cannot authorize forged immutable relation fields."""
from alembic import op
import sqlalchemy as sa

revision = "0086_memory_source_parity"
down_revision = "0085_memory_delivery"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION verify_memory_source_fields() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE source_record memory_events%ROWTYPE; field_name text;
        BEGIN
            SELECT * INTO source_record FROM memory_events
              WHERE event_id=NEW.source_event_id AND aggregate_id=NEW.memory_id
                AND knowledge_scope_id=NEW.knowledge_scope_id
                AND event_type IN ('assert','revise','consolidate');
            IF source_record.event_id IS NULL THEN
                RAISE EXCEPTION 'relation facts require an immutable source event';
            END IF;
            FOREACH field_name IN ARRAY ARRAY['kind','provenance','title','content_text','content_hash',
                'submission_meta','confidence','tags','evidence_refs','inference_meta','injection_flags',
                'session_id','agent_id','task_context','supersedes_memory_id'] LOOP
                IF COALESCE(source_record.payload->field_name, 'null'::jsonb)
                   IS DISTINCT FROM COALESCE(to_jsonb(NEW)->field_name, 'null'::jsonb) THEN
                    RAISE EXCEPTION 'relation facts must match immutable source fields: %', field_name;
                END IF;
            END LOOP;
            IF NEW.observed_at IS DISTINCT FROM source_record.occurred_at
               OR NEW.created_at IS DISTINCT FROM (source_record.payload->>'created_at')::timestamptz
               OR NEW.updated_at IS DISTINCT FROM (source_record.payload->>'updated_at')::timestamptz
               OR NEW.expires_at IS DISTINCT FROM (source_record.payload->>'expires_at')::timestamptz THEN
                RAISE EXCEPTION 'relation timestamps must match immutable source fields';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER memory_entries_source_parity BEFORE INSERT OR UPDATE ON memory_entries
            FOR EACH ROW EXECUTE FUNCTION verify_memory_source_fields();
    """)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM memory_events")).scalar_one():
        raise RuntimeError("cannot remove source parity with retained events")
    op.execute("DROP TRIGGER memory_entries_source_parity ON memory_entries")
    op.execute("DROP FUNCTION verify_memory_source_fields()")
