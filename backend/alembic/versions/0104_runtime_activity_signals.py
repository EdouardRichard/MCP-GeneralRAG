"""Bounded cross-process request-activity signals for automatic admission (013 T082/T084).

0095-0103 are applied and frozen. Automatic idle/volume consolidation must not
run while real foreground work is in flight, and the management process cannot
observe the MCP process's request activity in memory. This successor adds one
operational row per process that publishes its own in-memory activity snapshot
(foreground count, last foreground time, ingestion/rebuild liveness, unpicked
volume hints); the writer maintenance tick reads fresh peer rows and
conservatively skips automatic admission when an observation is stale.

This table is runtime/audit state only: it never enters the knowledge base, the
event log or the vector store, and it holds no memory authority.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '0104_runtime_activity_signals'
down_revision = '0103_promotion_guard_skip'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'runtime_activity_signals',
        sa.Column('instance_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('process_role', sa.String(12), nullable=False),
        sa.Column('instance_mode', sa.String(8), nullable=False),
        sa.Column('foreground_active', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('last_foreground_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('ingestion_active', sa.Boolean(), nullable=False, server_default=sa.text('FALSE')),
        sa.Column('rebuild_active', sa.Boolean(), nullable=False, server_default=sa.text('FALSE')),
        sa.Column('volume_hint_scope_ids', postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column('volume_hint_published_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('published_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('state', sa.String(16), nullable=False, server_default=sa.text("'active'")),
        sa.Column('released_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("process_role IN ('management','mcp')",
                           name='ck_runtime_activity_process_role'),
        sa.CheckConstraint("instance_mode IN ('writer','reader')",
                           name='ck_runtime_activity_instance_mode'),
        sa.CheckConstraint('foreground_active>=0', name='ck_runtime_activity_foreground_active'),
        sa.CheckConstraint("state IN ('active','released')", name='ck_runtime_activity_state'),
    )
    op.create_index('ix_runtime_activity_active', 'runtime_activity_signals', ['state', 'published_at'])


def downgrade():
    op.drop_index('ix_runtime_activity_active', table_name='runtime_activity_signals')
    op.drop_table('runtime_activity_signals')
