"""Repair the deployed 012 foundation without rewriting migration history."""
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0081_memory_authority"
down_revision = "0080_memory_foundation"
branch_labels = None
depends_on = None

POLICY = {
    "episodic_ttl_days": 180, "semantic_procedural_ttl_days": None,
    "per_scope_memory_quota": 5000, "decay_rate": .05,
    "rrf_weights": {"dense": 1., "recency": .5, "kind": .3, "salience": .2},
    "start_work_budgets": {"full": 2000, "compact": 800, "minimal": 300},
    "consolidation_enabled": False, "attach_min_score": 0.,
}

ENTRY_COLUMNS = [
    sa.Column("content_hash", sa.String(64)), sa.Column("submission_meta", JSONB()),
    sa.Column("confidence", sa.Float()), sa.Column("tags", JSONB(), nullable=False, server_default="[]"),
    sa.Column("supersedes_memory_id", sa.BigInteger()), sa.Column("superseded_by", sa.BigInteger()),
    sa.Column("valid_from", sa.TIMESTAMP(timezone=True)), sa.Column("valid_to", sa.TIMESTAMP(timezone=True)),
    sa.Column("observed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    sa.Column("invalidated_at", sa.TIMESTAMP(timezone=True)), sa.Column("session_id", sa.String(64)),
    sa.Column("agent_id", sa.String(255)), sa.Column("task_context", JSONB()),
    sa.Column("injection_flags", JSONB()), sa.Column("expires_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("promote_candidate_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    sa.Column("source_event_id", sa.BigInteger()),
]


def upgrade():
    for column in ENTRY_COLUMNS:
        op.add_column("memory_entries", column)
    op.alter_column("memory_entries", "content_hash", nullable=False)
    op.create_unique_constraint("uq_memory_entries_scope_hash", "memory_entries", ["knowledge_scope_id", "content_hash"])
    for table in ("memory_events", "memory_entries", "scope_bindings"):
        op.create_foreign_key(f"fk_{table}_scope", table, "knowledge_scopes", ["knowledge_scope_id"], ["scope_id"])
    for column in ("supersedes_memory_id", "superseded_by"):
        op.create_foreign_key(f"fk_memory_entries_{column}", "memory_entries", "memory_entries", [column], ["memory_id"])
    op.create_foreign_key("fk_memory_entries_event", "memory_entries", "memory_events", ["source_event_id"], ["event_id"])
    op.create_check_constraint("ck_memory_content_length", "memory_entries", "char_length(content_text) BETWEEN 1 AND 4000")
    op.create_check_constraint("ck_memory_confidence", "memory_entries", "confidence IS NULL OR confidence BETWEEN 0 AND 1")
    for field in ("kind", "provenance", "status"):
        op.create_check_constraint(f"ck_memory_{field}_wide", "memory_entries", f"{field} ~ '^[a-z][a-z0-9_]*$'")
    op.create_index("ix_memory_entries_scope_status", "memory_entries", ["knowledge_scope_id", "status"])
    op.create_index("ix_memory_entries_scope_kind_status", "memory_entries", ["knowledge_scope_id", "kind", "status"])
    op.create_index("ix_memory_entries_session", "memory_entries", ["session_id"])
    op.create_index("ix_memory_events_scope_type_time", "memory_events", ["knowledge_scope_id", "event_type", "occurred_at"])
    op.create_unique_constraint("uq_scope_binding_value", "scope_bindings", ["binding_kind", "binding_value"])
    for column in (
        sa.Column("last_access_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("reinforced_at", sa.TIMESTAMP(timezone=True)),
    ):
        op.add_column("memory_salience", column)
    op.create_foreign_key("fk_memory_salience_entry", "memory_salience", "memory_entries", ["memory_id"], ["memory_id"])
    for name in ("started_at", "last_active_at", "expires_at"):
        op.add_column("sessions", sa.Column(name, sa.TIMESTAMP(timezone=True)))
    op.create_foreign_key("fk_memory_session_scope", "sessions", "knowledge_scopes", ["primary_scope_id"], ["scope_id"])
    for column in (
        sa.Column("channel", sa.String(32)), sa.Column("session_id", sa.String(64)),
        sa.Column("returned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("package_fingerprint", sa.String(64)),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("failed_paths", JSONB(), nullable=False, server_default="[]"),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW() + INTERVAL '7 days'")),
    ):
        op.add_column("memory_recall_runs", column)
    for column in (
        sa.Column("knowledge_scope_id", sa.BigInteger()),
        sa.Column("source_event_id", sa.BigInteger()),
        sa.Column("fingerprint", sa.String(64)), sa.Column("payload", JSONB()),
        sa.Column("projection_version", sa.String(64), nullable=False, server_default="012-v1"),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    ):
        op.add_column("memory_projection_meta", column)
    op.execute(sa.text("UPDATE domain_profiles SET memory_policy=CAST(:policy AS jsonb) "
                       "WHERE domain_key IN ('se-project','generic','personal','legal') AND memory_policy IS NULL")
               .bindparams(policy=json.dumps(POLICY)))
    op.execute("""
        CREATE FUNCTION reject_memory_event_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'memory_events is append-only and immutable';
        END; $$;
        CREATE TRIGGER memory_events_immutable BEFORE UPDATE OR DELETE ON memory_events
        FOR EACH ROW EXECUTE FUNCTION reject_memory_event_mutation();
        CREATE TRIGGER memory_events_no_truncate BEFORE TRUNCATE ON memory_events
        FOR EACH STATEMENT EXECUTE FUNCTION reject_memory_event_mutation();
    """)


def downgrade():
    # A downgrade would erase trajectory metadata. Reject it once events exist.
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM memory_events")).scalar_one()
    if count:
        raise RuntimeError("cannot downgrade memory authority with retained events")
    op.execute("DROP TRIGGER memory_events_no_truncate ON memory_events")
    op.execute("DROP TRIGGER memory_events_immutable ON memory_events")
    op.execute("DROP FUNCTION reject_memory_event_mutation()")
    for table, names in {
        "memory_projection_meta": ["knowledge_scope_id", "source_event_id", "fingerprint", "payload", "projection_version", "updated_at"],
        "memory_recall_runs": ["channel", "session_id", "returned_count", "package_fingerprint", "degraded", "failed_paths", "latency_ms", "created_at", "expires_at"],
        "sessions": ["started_at", "last_active_at", "expires_at"],
        "memory_salience": ["last_access_at", "reinforced_at"],
    }.items():
        for name in names:
            op.drop_column(table, name)
    op.drop_constraint("fk_memory_session_scope", "sessions", type_="foreignkey")
    op.drop_constraint("fk_memory_salience_entry", "memory_salience", type_="foreignkey")
    op.drop_constraint("uq_scope_binding_value", "scope_bindings", type_="unique")
    for table in ("memory_events", "memory_entries", "scope_bindings"):
        op.drop_constraint(f"fk_{table}_scope", table, type_="foreignkey")
    for name in ("supersedes_memory_id", "superseded_by"):
        op.drop_constraint(f"fk_memory_entries_{name}", "memory_entries", type_="foreignkey")
    op.drop_constraint("fk_memory_entries_event", "memory_entries", type_="foreignkey")
    op.drop_constraint("uq_memory_entries_scope_hash", "memory_entries", type_="unique")
    for name in ("ck_memory_content_length", "ck_memory_confidence", "ck_memory_kind_wide", "ck_memory_provenance_wide", "ck_memory_status_wide"):
        op.drop_constraint(name, "memory_entries", type_="check")
    for name in ("ix_memory_entries_scope_status", "ix_memory_entries_scope_kind_status", "ix_memory_entries_session"):
        op.drop_index(name, table_name="memory_entries")
    op.drop_index("ix_memory_events_scope_type_time", table_name="memory_events")
    for column in reversed(ENTRY_COLUMNS):
        op.drop_column("memory_entries", column.name)
