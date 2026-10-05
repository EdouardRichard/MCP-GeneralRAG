"""Persist bounded runtime delivery IDs without modifying memory facts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0085_memory_delivery"
down_revision = "0084_memory_supersede_fk"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("memory_recall_runs", sa.Column("returned_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade():
    op.drop_column("memory_recall_runs", "returned_ids")
