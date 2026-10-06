"""Make the promotion guard ignore every non-promotion grant (013 T071).

0101/0102 are applied and frozen. Their `guard_promotion_event()` opened with
``payload->>'grant_type' NOT IN ('promotion_requested','promotion_observed')``,
which is NULL (never TRUE) when a grant has no `grant_type` at all, so ordinary
management grants (retention lifecycle, policy, bindings) fell through into the
promotion shape checks and were rejected. This successor makes the early return
explicit for that case.
"""
import importlib.util as _importlib_util
from pathlib import Path as _pathlib_Path

import sqlalchemy as sa

from alembic import op

_downgrade_guard_spec = _importlib_util.spec_from_file_location(
    '_consolidation_downgrade', _pathlib_Path(__file__).resolve().parents[1] / '_consolidation_downgrade.py')
_downgrade_guard = _importlib_util.module_from_spec(_downgrade_guard_spec)
_downgrade_guard_spec.loader.exec_module(_downgrade_guard)
assert_no_consolidation_authority = _downgrade_guard.assert_no_consolidation_authority

revision = '0103_promotion_guard_skip'
down_revision = '0102_promotion_guard_identity'
branch_labels = None
depends_on = None

BEFORE = """            IF NEW.event_type<>'grant'
               OR NEW.payload->>'grant_type' NOT IN ('promotion_requested','promotion_observed') THEN
                RETURN NEW;
            END IF;"""
AFTER = """            IF NEW.event_type<>'grant'
               OR COALESCE(NEW.payload->>'grant_type','') NOT IN ('promotion_requested','promotion_observed') THEN
                RETURN NEW;
            END IF;"""


def replace_function(signature, fragments):
    connection = op.get_bind()
    definition = connection.execute(sa.text('SELECT pg_get_functiondef(CAST(:signature AS regprocedure))'),
                                    {'signature': signature}).scalar_one()
    for before, after in fragments:
        if definition.count(before) != 1:
            raise RuntimeError(f'unexpected predecessor function {signature}: {before!r}')
        definition = definition.replace(before, after)
    connection.execute(sa.text(definition))


def upgrade():
    replace_function('guard_promotion_event()', ((BEFORE, AFTER),))


def downgrade():
    assert_no_consolidation_authority('0103_promotion_guard_skip')
    replace_function('guard_promotion_event()', ((AFTER, BEFORE),))
