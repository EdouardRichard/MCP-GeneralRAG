"""Persist successful management rebuild audit records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0094_memory_management_audit"
down_revision = "0093_memory_access_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memory_management_audits",
        sa.Column("request_id", sa.String(length=128), primary_key=True),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("knowledge_scope_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.BigInteger(), nullable=False),
        sa.Column("since_event_id", sa.BigInteger(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("idx_memory_management_audits_scope_created", "memory_management_audits",
                   ["knowledge_scope_id", "created_at"])


def downgrade():
    op.drop_index("idx_memory_management_audits_scope_created", table_name="memory_management_audits")
    op.drop_table("memory_management_audits")
