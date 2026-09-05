"""drop_graph_project_id

Revision ID: 0072
Revises: 0071
Create Date: 2026-09-06 00:00:00.000000

007: knowledge_scope_id becomes the sole graph isolation key (FR-018). Drops
the redundant graph_edge.project_id / soft_relation.project_id columns and
rebuilds the three composite indexes that carried project_id (data-model §4.1).
project_id is still derivable via scope -> Project join (Constitution VIII).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0072'
down_revision: Union[str, Sequence[str], None] = '0071'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the project_id-bearing composite indexes before dropping columns.
    op.drop_index('idx_graph_edge_source', table_name='graph_edge')
    op.drop_index('idx_graph_edge_target', table_name='graph_edge')
    op.drop_index('idx_soft_relation_active', table_name='soft_relation')

    op.drop_column('graph_edge', 'project_id')
    op.drop_column('soft_relation', 'project_id')

    # Rebuild the composite indexes keyed only on knowledge_scope_id.
    op.create_index(
        'idx_graph_edge_source', 'graph_edge',
        ['knowledge_scope_id', 'index_version', 'source_chunk_id', 'relation_type', 'direction'],
    )
    op.create_index(
        'idx_graph_edge_target', 'graph_edge',
        ['knowledge_scope_id', 'index_version', 'target_chunk_id', 'relation_type', 'direction'],
    )
    op.create_index(
        'idx_soft_relation_active', 'soft_relation',
        ['knowledge_scope_id', 'index_version', 'lifecycle_state'],
        postgresql_where=sa.text("lifecycle_state = 'active'"),
    )


def downgrade() -> None:
    op.drop_index('idx_graph_edge_source', table_name='graph_edge')
    op.drop_index('idx_graph_edge_target', table_name='graph_edge')
    op.drop_index('idx_soft_relation_active', table_name='soft_relation')

    # project_id is a 1:1 derivation; on rollback we add it back as NOT NULL
    # with a sentinel (the exact value is recoverable via scope->Project join).
    op.add_column('graph_edge', sa.Column('project_id', sa.BigInteger(), nullable=False, server_default=sa.text('0')))
    op.add_column('soft_relation', sa.Column('project_id', sa.BigInteger(), nullable=False, server_default=sa.text('0')))

    op.create_index(
        'idx_graph_edge_source', 'graph_edge',
        ['knowledge_scope_id', 'project_id', 'index_version', 'source_chunk_id', 'relation_type', 'direction'],
    )
    op.create_index(
        'idx_graph_edge_target', 'graph_edge',
        ['knowledge_scope_id', 'project_id', 'index_version', 'target_chunk_id', 'relation_type', 'direction'],
    )
    op.create_index(
        'idx_soft_relation_active', 'soft_relation',
        ['knowledge_scope_id', 'project_id', 'index_version', 'lifecycle_state'],
        postgresql_where=sa.text("lifecycle_state = 'active'"),
    )
