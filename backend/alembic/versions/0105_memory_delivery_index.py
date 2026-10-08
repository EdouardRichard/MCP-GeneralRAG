"""Supporting index for the 014 session-level delivered-memory set (T028).

014 replaces 012's 7-day ``expires_at`` dedup window with the short policy TTL
``delivered_ttl_seconds`` (default 3600 seconds). Dedup now filters on
``session_id = :sid AND created_at > :cutoff`` on every recall/attachment/package
request of a session, which the existing indexes do not support: ``memory_recall_runs``
has only its ``request_id`` primary key.

This migration adds exactly one non-unique index. It does not add, drop or alter a
column, does not backfill, and does not change any default; ``expires_at`` remains
the runtime audit retention and is simply no longer consulted for delivery dedup.
That window change is an approved change and is evidenced in the 014 regression
report (spec SC-015).
"""
from sqlalchemy import text

from alembic import op

revision = '0105_memory_delivery_index'
down_revision = '0104_runtime_activity_signals'
branch_labels = None
depends_on = None

INDEX_NAME = 'ix_memory_recall_runs_session_created'


def upgrade():
    op.create_index(
        INDEX_NAME,
        'memory_recall_runs',
        ['session_id', 'created_at'],
        unique=False,
        postgresql_where=text('session_id IS NOT NULL'),
    )


def downgrade():
    # Idempotent on purpose: an operator (or an out-of-order history) may reach
    # this point without the index ever having been created, and dropping an index
    # that does not exist must not abort the rest of a downgrade chain.
    op.execute(f'DROP INDEX IF EXISTS {INDEX_NAME}')
