"""Replay immutable policy rates captured by access events."""
from alembic import op
import sqlalchemy as sa


revision = "0093_memory_access_policy"
down_revision = "0092_memory_verified_publication"
branch_labels = None
depends_on = None

ACCESS_BEFORE = "access_state := salience->mid;"
ACCESS_AFTER = """access_state := salience->mid;
                    access_state := access_state || jsonb_build_object('decay_rate',
                        COALESCE(event.payload->'decay_rate',access_state->'decay_rate'));"""


def _replace_access_policy(*, reverse=False):
    connection = op.get_bind()
    definition = connection.execute(sa.text(
        "SELECT pg_get_functiondef('memory_log_state(bigint,bigint)'::regprocedure)"
    )).scalar_one()
    before, after = (ACCESS_AFTER, ACCESS_BEFORE) if reverse else (ACCESS_BEFORE, ACCESS_AFTER)
    if definition.count(before) != 1 or (not reverse and ACCESS_AFTER in definition):
        raise RuntimeError("unexpected database access reducer version; refusing partial migration")
    connection.execute(sa.text(definition.replace(before, after)))


def upgrade():
    _replace_access_policy()


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM memory_events")).scalar_one():
        raise RuntimeError("cannot discard captured access policy with retained authority events")
    _replace_access_policy(reverse=True)
