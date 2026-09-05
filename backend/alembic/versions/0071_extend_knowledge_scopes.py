"""extend_knowledge_scopes

Revision ID: 0071
Revises: 0070
Create Date: 2026-09-06 00:00:00.000000

007: extends knowledge_scopes with the semantic axis domain_key (FK default
se-project) and the globally-unique slug (FR-001/FR-012). Backfills every
existing scope with domain_key='se-project' and a unique slug generated from
its name (slugify + collision suffix; data-model §3.3).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0071'
down_revision: Union[str, Sequence[str], None] = '0070'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # domain_key: semantic axis (FK default se-project, FR-001/FR-002).
    op.add_column(
        'knowledge_scopes',
        sa.Column('domain_key', sa.String(64), sa.ForeignKey('domain_profiles.domain_key'),
                  nullable=False, server_default=sa.text("'se-project'"),
                  comment='semantic axis: domain profile key'),
    )

    # slug: added nullable first, backfilled, then made NOT NULL + UNIQUE.
    op.add_column(
        'knowledge_scopes',
        sa.Column('slug', sa.String(255), nullable=True,
                  comment='globally-unique name-addressing slug'),
    )

    from rag_mcp.config.domain_profiles import generate_unique_slug

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT scope_id, name FROM knowledge_scopes ORDER BY scope_id")).fetchall()
    used: set[str] = set()
    for scope_id, name in rows:
        slug = generate_unique_slug(name or "", scope_id, used)
        used.add(slug)
        conn.execute(
            sa.text("UPDATE knowledge_scopes SET slug = :slug WHERE scope_id = :sid"),
            {"slug": slug, "sid": scope_id},
        )

    op.alter_column('knowledge_scopes', 'slug', nullable=False)
    op.create_unique_constraint('uq_knowledge_scopes_slug', 'knowledge_scopes', ['slug'])


def downgrade() -> None:
    op.drop_constraint('uq_knowledge_scopes_slug', 'knowledge_scopes', type_='unique')
    op.drop_column('knowledge_scopes', 'slug')
    op.drop_column('knowledge_scopes', 'domain_key')
