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

import importlib.util as _importlib_util
from pathlib import Path as _pathlib_Path

_downgrade_guard_spec = _importlib_util.spec_from_file_location(
    '_consolidation_downgrade', _pathlib_Path(__file__).resolve().parents[1] / '_consolidation_downgrade.py')
_downgrade_guard = _importlib_util.module_from_spec(_downgrade_guard_spec)
_downgrade_guard_spec.loader.exec_module(_downgrade_guard)
assert_no_consolidation_authority = _downgrade_guard.assert_no_consolidation_authority

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
    assert_no_consolidation_authority('0100_consolidation_propagation_guard_fix')
    connection = op.get_bind()
    definition = connection.execute(sa.text(
        "SELECT pg_get_functiondef('guard_consolidation_propagation_event()'::regprocedure)")).scalar_one()
    if definition.count(FRAGMENT[0]) == 1:
        # The predecessor was already repaired in place, so upgrade() was a no-op
        # and the reverse must be one too.
        return
    if definition.count(FRAGMENT[1]) != 1:
        raise RuntimeError('unexpected propagation guard definition; refusing partial downgrade')
    connection.execute(sa.text(definition.replace(FRAGMENT[1], FRAGMENT[0])))
