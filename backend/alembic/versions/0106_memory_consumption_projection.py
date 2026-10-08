"""Consumption-layer projection metadata (014 T043).

014 adds two migrations: ``0105_memory_delivery_index`` (the delivered-set lookup
index) and this one. This successor therefore chains onto 0105 to keep a single
linear head, and adds one operational registry row per knowledge scope for the
read-only **consumption layer** (``MEMORY_CONSUMPTION_ROOT/<scope_slug>/<kind>/<memory_id>.md``
+ ``DIGEST.md``/``INDEX.md``), which coexists with — and never replaces — the 012
revision tree under ``DATA_ROOT/memory_projection/<numeric scope id>/...``.

The table is projection *metadata*, not a seventh business projection, so it is
deliberately **not** ``memory_projection_meta``: that table's ``versions()``
contract requires exactly the six ``VIEW_KEYS`` (012 FR-005/FR-007), and adding a
type there would break the existing rebuild verification. No column of the
revision tree is touched, and no backfill happens: an empty table simply means
"nothing reconciled yet".

``downgrade`` drops only this table's index and the table itself.

Note: the revision identifier is short (``0106_memory_consumption``, 23 chars)
because ``alembic_version.version_num`` is ``VARCHAR(32)``; the module filename
keeps the full descriptive name from the task list.
"""

import sqlalchemy as sa

from alembic import op

revision = '0106_memory_consumption'
down_revision = '0105_memory_delivery_index'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'memory_consumption_projection',
        sa.Column('knowledge_scope_id', sa.BigInteger(), sa.ForeignKey('knowledge_scopes.scope_id'),
                  primary_key=True),
        sa.Column('scope_slug', sa.String(255), nullable=False),
        sa.Column('source_event_id', sa.BigInteger(), nullable=False),
        sa.Column('tree_fingerprint', sa.String(64), nullable=False),
        sa.Column('file_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('status', sa.String(16), nullable=False, server_default=sa.text("'staging'")),
        sa.Column('guard_state', sa.String(16), nullable=False, server_default=sa.text("'writable'")),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('refreshed_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint("status ~ '^[a-z][a-z0-9_]*$'", name='ck_memory_consumption_status'),
        sa.CheckConstraint("guard_state ~ '^[a-z][a-z0-9_]*$'", name='ck_memory_consumption_guard_state'),
        sa.CheckConstraint("tree_fingerprint ~ '^[0-9a-f]{64}$'", name='ck_memory_consumption_fingerprint'),
        sa.CheckConstraint('file_count >= 0', name='ck_memory_consumption_file_count'),
        sa.CheckConstraint('source_event_id > 0', name='ck_memory_consumption_source_event'),
    )
    op.create_index('ix_memory_consumption_status', 'memory_consumption_projection', ['status'])


def downgrade():
    op.drop_index('ix_memory_consumption_status', table_name='memory_consumption_projection')
    op.drop_table('memory_consumption_projection')
