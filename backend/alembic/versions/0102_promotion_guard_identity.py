"""Fix the promotion guard identity check for observation grants (013 T071).

0101 is applied and frozen. Its `guard_promotion_event()` required the pointer's
`task_id`/`request_event_id` to equal the *current* event id, which is correct
only for the first `promotion_requested` grant; a later `promotion_observed`
grant keeps the original stable task identity and appends its own event id to
`authority_event_ids`. This successor replaces only that check.
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

revision = '0102_promotion_guard_identity'
down_revision = '0101_promotion_pointer'
branch_labels = None
depends_on = None

BEFORE = """               OR pointer->>'task_id' IS DISTINCT FROM NEW.event_id::text
               OR (pointer->>'request_event_id')::bigint IS DISTINCT FROM NEW.event_id
               OR (pointer->>'memory_id')::bigint IS DISTINCT FROM NEW.aggregate_id"""
AFTER = """               OR pointer->>'task_id' IS DISTINCT FROM (pointer->>'request_event_id')
               OR (NEW.payload->>'grant_type'='promotion_requested'
                   AND pointer->>'task_id' IS DISTINCT FROM NEW.event_id::text)
               OR (pointer->>'memory_id')::bigint IS DISTINCT FROM NEW.aggregate_id"""


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
    assert_no_consolidation_authority('0102_promotion_guard_identity')
    replace_function('guard_promotion_event()', ((AFTER, BEFORE),))
