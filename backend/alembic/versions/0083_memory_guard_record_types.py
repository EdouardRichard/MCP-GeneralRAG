"""Avoid resolving relation-only fields on link and summary trigger records."""
from alembic import op

revision = "0083_memory_guard_types"
down_revision = "0082_memory_boundary"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION guard_memory_projection() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE event_scope bigint; event_kind text; candidate_id bigint;
        BEGIN
            candidate_id := NULLIF(current_setting('rag_memory.reducer_event', true), '')::bigint;
            SELECT knowledge_scope_id, event_type INTO event_scope,event_kind
              FROM memory_events WHERE event_id=candidate_id;
            IF event_scope IS NULL THEN
                RAISE EXCEPTION 'projection writes require a scoped reducer event';
            END IF;
            IF TG_TABLE_NAME = 'memory_salience' THEN
                IF NOT EXISTS (SELECT 1 FROM memory_entries WHERE memory_id=NEW.memory_id
                               AND knowledge_scope_id=event_scope) THEN
                    RAISE EXCEPTION 'salience reducer scope mismatch';
                END IF;
            ELSE
                IF NEW.knowledge_scope_id IS DISTINCT FROM event_scope THEN
                    RAISE EXCEPTION 'projection reducer scope mismatch';
                END IF;
            END IF;
            IF TG_TABLE_NAME = 'scope_bindings' THEN
                IF event_kind NOT IN ('grant','rollback') THEN
                    RAISE EXCEPTION 'binding projection requires a management grant reducer';
                END IF;
            END IF;
            IF TG_TABLE_NAME = 'memory_entries' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM memory_events e WHERE e.aggregate_id=NEW.memory_id
                    AND e.knowledge_scope_id=event_scope AND e.event_type IN ('assert','revise','consolidate')
                    AND e.payload->>'content_text'=NEW.content_text
                    AND e.payload->>'provenance'=NEW.provenance
                    AND e.payload->'evidence_refs'=NEW.evidence_refs
                ) THEN
                    RAISE EXCEPTION 'relation facts must match immutable reducer source events';
                END IF;
            END IF;
            RETURN NEW;
        END; $$;
    """)


def downgrade():
    # Both adjacent versions enforce the same boundary; preserve the corrected
    # trigger when changing the Alembic marker rather than reinstalling a bug.
    pass
