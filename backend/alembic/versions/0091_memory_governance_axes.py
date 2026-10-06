"""Preserve source-event governance axes in all six derived memory views."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0091_memory_governance_axes"
down_revision = "0090_memory_bypass_guards"
branch_labels = None
depends_on = None

AXES = ("authority", "scope_meta", "mutability", "provenance_meta", "recoverability", "actionability")
SQL_AXES = "jsonb_build_object(" + ",".join(f"'{axis}',event.{axis}" for axis in AXES) + ")"
REPLAY_FRAGMENTS = (
    ("row_data := event.payload || jsonb_build_object('memory_id'",
     "row_data := event.payload || " + SQL_AXES + " || jsonb_build_object('memory_id'"),
    ("salience := jsonb_set(salience,ARRAY[mid],jsonb_build_object('memory_id'",
     "salience := jsonb_set(salience,ARRAY[mid]," + SQL_AXES + " || jsonb_build_object('memory_id'"),
)
GUARD_FRAGMENTS = tuple(
    (before, before[:-1] + "," + ",".join(f"'{axis}'" for axis in AXES) + "]")
    for before in ("ARRAY['status','superseded_by','source_event_id','retention_stage']",
                   "ARRAY['access_count','salience','decay_rate']")
)


def replace_fragments(function, fragments, *, reverse=False):
    connection = op.get_bind()
    definition = connection.execute(sa.text("SELECT pg_get_functiondef(CAST(:function AS regprocedure))"),
                                    {"function": function}).scalar_one()
    for before, after in fragments:
        if reverse:
            before, after = after, before
        if definition.count(before) != 1:
            raise RuntimeError("unexpected database governance reducer version; refusing partial migration")
        definition = definition.replace(before, after)
    connection.execute(sa.text(definition))


def upgrade():
    for table in ("memory_entries", "memory_salience"):
        for axis in AXES:
            op.add_column(table, sa.Column(axis, sa.String(32) if axis == "actionability" else JSONB(), nullable=True))
    replace_fragments("memory_log_state(bigint,bigint)", REPLAY_FRAGMENTS)

    # Backfill only source metadata under transactional DDL locks. Existing
    # completion states can lag retained failed events, so replay guards cannot
    # authorize this metadata-only migration on their original dynamics.
    for table in ("memory_entries", "memory_salience"):
        for suffix in ("reducer_guard", "log_parity"):
            op.execute(f"ALTER TABLE {table} DISABLE TRIGGER {table}_{suffix}")
    assignments = ",".join(f"{axis}=event.{axis}" for axis in AXES)
    op.execute(f"UPDATE memory_entries AS entry SET {assignments} FROM memory_events AS event "
               "WHERE event.event_id=entry.source_event_id AND event.aggregate_id=entry.memory_id "
               "AND event.knowledge_scope_id=entry.knowledge_scope_id "
               "AND event.event_type IN ('assert','revise','consolidate')")
    assignments = ",".join(f"{axis}=entry.{axis}" for axis in AXES)
    op.execute(f"UPDATE memory_salience AS salience SET {assignments} FROM memory_entries AS entry "
               "WHERE entry.memory_id=salience.memory_id")
    for table in ("memory_entries", "memory_salience"):
        for axis in AXES[:-1]:
            op.alter_column(table, axis, nullable=False)
        for suffix in ("reducer_guard", "log_parity"):
            op.execute(f"ALTER TABLE {table} ENABLE TRIGGER {table}_{suffix}")
    replace_fragments("verify_memory_log_projection()", GUARD_FRAGMENTS)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM memory_events")).scalar_one():
        raise RuntimeError("cannot discard governance metadata with retained authority events")
    replace_fragments("verify_memory_log_projection()", GUARD_FRAGMENTS, reverse=True)
    replace_fragments("memory_log_state(bigint,bigint)", REPLAY_FRAGMENTS, reverse=True)
    for table in ("memory_entries", "memory_salience"):
        for axis in reversed(AXES):
            op.drop_column(table, axis)
