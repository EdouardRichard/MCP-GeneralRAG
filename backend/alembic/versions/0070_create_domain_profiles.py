"""create_domain_profiles

Revision ID: 0070
Revises: 0062
Create Date: 2026-09-06 00:00:00.000000

007 Knowledge Domain Generalization: creates the domain_profiles registry table
(data-model §2) and seeds the two builtin profiles (se-project / generic,
FR-004). Builtin seed content is imported from rag_mcp.config.domain_profiles
(the single source of truth), so the migration and startup sync never drift.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0070'
down_revision: Union[str, Sequence[str], None] = '0062'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'domain_profiles',
        sa.Column('domain_key', sa.String(64), nullable=False, comment='stable profile key'),
        sa.Column('name', sa.String(255), nullable=False, comment='display name'),
        sa.Column('description', sa.Text(), nullable=True, comment='description'),
        sa.Column('supported_formats', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  comment='declared accepted format set'),
        sa.Column('chunk_type_extensions', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment='namespaced chunk-type extension vocabulary'),
        sa.Column('graph_relations', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  comment='relation vocabulary with directions'),
        sa.Column('prompt_overrides', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment='planner prompt injection fragments'),
        sa.Column('default_capabilities', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  comment='default capability declaration'),
        sa.Column('is_builtin', sa.Boolean(), nullable=False, server_default=sa.text('false'),
                  comment='builtin (read-only) flag'),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('domain_key', name='pk_domain_profiles'),
        comment='Domain profile registry (007)',
    )

    # Seed the two builtin profiles (FR-004).
    from rag_mcp.config.domain_profiles import BUILTIN_DOMAIN_PROFILES

    profiles = op.get_bind()
    for key, p in BUILTIN_DOMAIN_PROFILES.items():
        profiles.execute(
            sa.text(
                "INSERT INTO domain_profiles (domain_key, name, description, "
                "supported_formats, chunk_type_extensions, graph_relations, "
                "prompt_overrides, default_capabilities, is_builtin) "
                "VALUES (:dk, :name, :desc, CAST(:formats AS jsonb), "
                "CAST(:cte AS jsonb), CAST(:graph AS jsonb), CAST(:prompt AS jsonb), "
                "CAST(:caps AS jsonb), :builtin)"
            ),
            {
                "dk": key,
                "name": p["name"],
                "desc": p.get("description"),
                "formats": _json(p["supported_formats"]),
                "cte": _json(p.get("chunk_type_extensions")),
                "graph": _json(p["graph_relations"]),
                "prompt": _json(p.get("prompt_overrides")),
                "caps": _json(p["default_capabilities"]),
                "builtin": bool(p["is_builtin"]),
            },
        )


def _json(value):
    import json
    return json.dumps(value)


def downgrade() -> None:
    op.drop_table('domain_profiles')
