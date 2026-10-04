"""012 memory foundation tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0080_memory_foundation"
down_revision = "0074"
branch_labels = None
depends_on = None


def upgrade():
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.add_column("domain_profiles", sa.Column("memory_policy", jsonb, nullable=True))
    op.create_table("memory_events",
        sa.Column("event_id", sa.BigInteger(), primary_key=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("aggregate_id", sa.BigInteger(), nullable=False),
        sa.Column("knowledge_scope_id", sa.BigInteger(), nullable=False),
        sa.Column("payload", jsonb, nullable=False), sa.Column("authority", jsonb, nullable=False),
        sa.Column("scope_meta", jsonb, nullable=False), sa.Column("mutability", jsonb, nullable=False),
        sa.Column("provenance_meta", jsonb, nullable=False), sa.Column("recoverability", jsonb, nullable=False),
        sa.Column("actionability", sa.String(32)), sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False), sa.Column("session_id", sa.String(64)),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("valid_from", sa.TIMESTAMP(timezone=True)), sa.Column("valid_to", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint("event_type IN ('assert','revise','retract','consolidate','access','grant','rollback')", name="ck_memory_event_type"),
    )
    for name, cols in (("memory_entries", [sa.Column("memory_id", sa.BigInteger(), primary_key=True), sa.Column("knowledge_scope_id", sa.BigInteger(), nullable=False), sa.Column("kind", sa.String(32), nullable=False), sa.Column("provenance", sa.String(32), nullable=False), sa.Column("title", sa.String(512)), sa.Column("content_text", sa.Text(), nullable=False), sa.Column("evidence_refs", jsonb, nullable=False), sa.Column("inference_meta", jsonb), sa.Column("status", sa.String(32), nullable=False)]), ("scope_bindings", [sa.Column("binding_id", sa.BigInteger(), primary_key=True), sa.Column("binding_kind", sa.String(32), nullable=False), sa.Column("binding_value", sa.String(1024), nullable=False), sa.Column("knowledge_scope_id", sa.BigInteger(), nullable=False), sa.Column("priority", sa.Integer(), nullable=False), sa.Column("status", sa.String(16), nullable=False)]), ("sessions", [sa.Column("session_id", sa.String(64), primary_key=True), sa.Column("agent_id", sa.String(255), nullable=False), sa.Column("primary_scope_id", sa.BigInteger()), sa.Column("status", sa.String(32), nullable=False)]), ("memory_salience", [sa.Column("memory_id", sa.BigInteger(), primary_key=True), sa.Column("salience", sa.Float(), nullable=False), sa.Column("access_count", sa.Integer(), nullable=False), sa.Column("decay_rate", sa.Float(), nullable=False)]), ("memory_recall_runs", [sa.Column("request_id", sa.String(128), primary_key=True), sa.Column("tool", sa.String(64), nullable=False), sa.Column("mode", sa.String(32), nullable=False), sa.Column("scope_ids", jsonb, nullable=False)]), ("memory_projection_meta", [sa.Column("projection_id", sa.String(128), primary_key=True), sa.Column("projection_type", sa.String(32), nullable=False), sa.Column("status", sa.String(16), nullable=False)])):
        op.create_table(name, *cols)
    op.create_index("ix_memory_events_scope_aggregate_time", "memory_events", ["knowledge_scope_id", "aggregate_id", "occurred_at"])
    op.create_index("ix_memory_events_scope_event", "memory_events", ["knowledge_scope_id", "event_id"])


def downgrade():
    op.drop_column("domain_profiles", "memory_policy")
    for name in ("memory_projection_meta", "memory_recall_runs", "memory_salience", "sessions", "scope_bindings", "memory_entries"):
        op.drop_table(name)
    op.drop_index("ix_memory_events_scope_event", table_name="memory_events")
    op.drop_index("ix_memory_events_scope_aggregate_time", table_name="memory_events")
    op.drop_table("memory_events")
