"""Repair the propagation control guard's payload_version comparison (T060).

`0099_consolidation_propagation` compares `payload->>'payload_version'` (text)
against `'2'::jsonb` in `guard_consolidation_propagation_event()`, so every
`grant_type='consolidation_propagation'` insert raises
`UndefinedFunctionError: operator does not exist: text = jsonb`. 0099 is already
applied in the isolated deployment, so this successor replaces only that one
predicate and leaves every other deployed definition untouched.
"""
from alembic import op
import sqlalchemy as sa

revision = '0100_propagation_guard_text_fix'
down_revision = '0099_consolidation_propagation'
branch_labels = None
depends_on = None

FRAGMENT = ("NEW.payload->>'payload_version' IS DISTINCT FROM '2'::jsonb",
            "NEW.payload->>'payload_version' IS DISTINCT FROM '2'")


def upgrade():
    connection = op.get_bind()
    definition = connection.execute(sa.text(
        "SELECT pg_get_functiondef('guard_consolidation_propagation_event()'::regprocedure)")).scalar_one()
    if definition.count(FRAGMENT[0]) == 1:
        connection.execute(sa.text(definition.replace(*FRAGMENT)))
    elif definition.count(FRAGMENT[1]) >= 1 and definition.count(FRAGMENT[0]) == 0:
        # The predecessor was already repaired in place; this successor is a
        # no-op so a fresh upgrade path stays valid either way.
        return
    else:
        raise RuntimeError('unexpected propagation guard definition; refusing partial repair')


def downgrade():
    raise RuntimeError('cannot downgrade consolidation authority; use compatible forward deployment')
