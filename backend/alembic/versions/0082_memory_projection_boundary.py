"""Reducer-only projection writes and separate write-completion state."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0082_memory_boundary"
down_revision = "0081_memory_authority"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("memory_entries", sa.Column("write_status", sa.String(16), nullable=False, server_default="pending"))
    for name in ("memory_links", "memory_summary_nodes"):
        op.create_table(name,
            sa.Column("row_id", sa.String(512), primary_key=True),
            sa.Column("knowledge_scope_id", sa.BigInteger(), sa.ForeignKey("knowledge_scopes.scope_id"), nullable=False),
            sa.Column("revision_id", sa.BigInteger(), nullable=False),
            sa.Column("node_key", sa.String(255), nullable=False),
            sa.Column("data", JSONB(), nullable=False),
        )
        op.create_index(f"ix_{name}_scope_revision", name, ["knowledge_scope_id", "revision_id"])
    op.execute("""
        CREATE FUNCTION guard_memory_projection() RETURNS trigger LANGUAGE plpgsql AS $$
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
            IF TG_TABLE_NAME = 'scope_bindings' AND event_kind NOT IN ('grant','rollback') THEN
                RAISE EXCEPTION 'binding projection requires a management grant reducer';
            END IF;
            IF TG_TABLE_NAME = 'memory_entries' AND NOT EXISTS (
                SELECT 1 FROM memory_events e WHERE e.aggregate_id=NEW.memory_id
                AND e.knowledge_scope_id=event_scope AND e.event_type IN ('assert','revise','consolidate')
                AND e.payload->>'content_text'=NEW.content_text
                AND e.payload->>'provenance'=NEW.provenance
                AND e.payload->'evidence_refs'=NEW.evidence_refs
            ) THEN
                RAISE EXCEPTION 'relation facts must match immutable reducer source events';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE FUNCTION reject_memory_projection_delete() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'projection deletion requires event-derived replacement, not direct deletion';
        END; $$;
    """)
    for table in ("memory_entries", "memory_salience", "memory_links", "memory_summary_nodes", "memory_projection_meta", "scope_bindings"):
        op.execute(f"CREATE TRIGGER {table}_reducer_guard BEFORE INSERT OR UPDATE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION guard_memory_projection()")
        op.execute(f"CREATE TRIGGER {table}_delete_guard BEFORE DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION reject_memory_projection_delete()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM memory_events")).scalar_one():
        raise RuntimeError("cannot downgrade projection boundaries with retained events")
    for table in ("memory_entries", "memory_salience", "memory_links", "memory_summary_nodes", "memory_projection_meta", "scope_bindings"):
        op.execute(f"DROP TRIGGER {table}_delete_guard ON {table}")
        op.execute(f"DROP TRIGGER {table}_reducer_guard ON {table}")
    op.execute("DROP FUNCTION guard_memory_projection()")
    op.execute("DROP FUNCTION reject_memory_projection_delete()")
    op.drop_table("memory_links")
    op.drop_table("memory_summary_nodes")
    op.drop_column("memory_entries", "write_status")
