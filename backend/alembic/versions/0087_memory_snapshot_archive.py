"""Immutable replay checkpoints and archive indexes; original events remain."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0087_memory_history"
down_revision = "0086_memory_source_parity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("memory_snapshots",
        sa.Column("snapshot_id", sa.BigInteger(), primary_key=True),
        sa.Column("knowledge_scope_id", sa.BigInteger(), sa.ForeignKey("knowledge_scopes.scope_id"), nullable=False),
        sa.Column("covered_through_event_id", sa.BigInteger(), sa.ForeignKey("memory_events.event_id"), nullable=False),
        sa.Column("payload", JSONB(), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")))
    op.create_table("memory_archives",
        sa.Column("archive_id", sa.BigInteger(), primary_key=True),
        sa.Column("knowledge_scope_id", sa.BigInteger(), sa.ForeignKey("knowledge_scopes.scope_id"), nullable=False),
        sa.Column("path", sa.String(2048), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")))
    op.create_table("memory_archived_events",
        sa.Column("event_id", sa.BigInteger(), sa.ForeignKey("memory_events.event_id"), primary_key=True),
        sa.Column("archive_id", sa.BigInteger(), sa.ForeignKey("memory_archives.archive_id"), nullable=False))
    for table in ("memory_snapshots", "memory_archives"):
        op.create_index(f"ix_{table}_knowledge_scope_id", table, ["knowledge_scope_id"])
    op.create_index("ix_memory_archived_events_archive_id", "memory_archived_events", ["archive_id"])
    for table in ("memory_snapshots", "memory_archives", "memory_archived_events"):
        op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_memory_event_mutation()")
        op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION reject_memory_event_mutation()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM memory_snapshots")).scalar_one():
        raise RuntimeError("cannot remove retained replay checkpoints")
    for table in ("memory_archived_events", "memory_archives", "memory_snapshots"):
        op.drop_table(table)
