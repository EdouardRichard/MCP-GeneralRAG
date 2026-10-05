"""Validate both supersede pointers at the transaction boundary."""
from alembic import op

revision = "0084_memory_supersede_fk"
down_revision = "0083_memory_guard_types"
branch_labels = None
depends_on = None


def upgrade():
    for column in ("supersedes_memory_id", "superseded_by"):
        op.execute(f"ALTER TABLE memory_entries ALTER CONSTRAINT fk_memory_entries_{column} DEFERRABLE INITIALLY DEFERRED")


def downgrade():
    for column in ("supersedes_memory_id", "superseded_by"):
        op.execute(f"ALTER TABLE memory_entries ALTER CONSTRAINT fk_memory_entries_{column} NOT DEFERRABLE INITIALLY IMMEDIATE")
