"""widen_graph_edge_relation_type

Revision ID: 0074
Revises: 0073
Create Date: 2026-09-06 00:00:00.000000

010 Graph Relation Registry: widen graph_edge.relation_type from the closed
5-value enum (calls/called_by/fk_references/fk_referenced_by/other_hard) to a
wide-mode pattern + application-layer domain-vocabulary validation (FR-008/
FR-010, data-model §2.1, research R4). other_hard is retired: any pre-existing
other_hard row aborts the migration (no silent discard/remap, Constitution III).

Existing calls/called_by/fk_references/fk_referenced_by values remain valid
under the wide pattern (zero data rewrite, Clarification Q3).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0074"
down_revision: Union[str, Sequence[str], None] = "0073"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WIDE_PATTERN = "^[a-z][a-z0-9_]{0,62}$"
_LEGACY_ENUM = (
    "calls", "called_by", "fk_references", "fk_referenced_by", "other_hard",
)


def upgrade() -> None:
    # Pre-assertion (R4): other_hard must be retired cleanly. A non-zero count
    # means data needs an explicit backfill strategy — abort loudly.
    bind = op.get_bind()
    other_hard_count = bind.execute(
        sa.text("SELECT count(*) FROM graph_edge WHERE relation_type = 'other_hard'")
    ).scalar()
    if other_hard_count:
        raise RuntimeError(
            f"graph_edge contains {other_hard_count} 'other_hard' row(s); "
            "other_hard is retired in 010 — resolve the legacy rows before "
            "upgrading (no silent discard/remap, Constitution III)"
        )

    op.execute(
        "ALTER TABLE graph_edge DROP CONSTRAINT IF EXISTS chk_graph_edge_relation_type"
    )
    op.execute(
        "ALTER TABLE graph_edge ADD CONSTRAINT chk_graph_edge_relation_type "
        "CHECK (relation_type ~ '" + _WIDE_PATTERN + "')"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE graph_edge DROP CONSTRAINT IF EXISTS chk_graph_edge_relation_type"
    )
    op.execute(
        "ALTER TABLE graph_edge ADD CONSTRAINT chk_graph_edge_relation_type "
        "CHECK (relation_type IN ('" + "','".join(_LEGACY_ENUM) + "'))"
    )
