"""Shared destructive-downgrade guard for the 013 consolidation authority.

`specs/013-memory-consolidation-loop/tasks.md` T007 forbids a *destructive*
downgrade only **while 013 authority is retained**.  An empty database (or one
that never admitted a v2 consolidation event, an eligibility/run row, or a
promotion pointer) must still roll back cleanly, which is what the 012
empty-database roundtrip exercises.

Every 0096-0103 ``downgrade()`` therefore calls
:func:`assert_no_consolidation_authority` *before* it removes the objects that
migration created: the probes below only query tables/columns that still exist
at that point in the reverse chain.

Location note: this helper deliberately lives next to ``versions/`` instead of
inside it.  Alembic 1.19.1 loads *every* ``*.py`` file under
``alembic/versions`` as a revision script and aborts with ``Could not determine
revision id from filename ...`` for any module that does not declare
``revision``/``down_revision`` (verified locally), so a shared helper cannot be
placed in that directory.  Each migration loads it by absolute path, which keeps
the import independent of the current working directory.
"""
import sqlalchemy as sa

from alembic import op


def _table_exists(name):
    return op.get_bind().execute(
        sa.text('SELECT to_regclass(:name)'), {'name': name}).scalar() is not None


def _column_exists(table, column):
    return bool(op.get_bind().execute(sa.text(
        'SELECT count(*) FROM pg_attribute WHERE attrelid=to_regclass(:table)'
        ' AND attname=:column AND NOT attisdropped'),
        {'table': table, 'column': column}).scalar())


def _count(statement):
    return op.get_bind().execute(sa.text(statement)).scalar() or 0


def retained_consolidation_authority():
    """Return the 013 authority still present in the database (empty when none)."""
    retained = []
    if _table_exists('memory_events'):
        if _count("SELECT count(*) FROM memory_events WHERE payload->>'payload_version'='2'"):
            retained.append('v2 consolidation events')
        if _count("SELECT count(*) FROM memory_events WHERE payload->>'grant_type'"
                  " IN ('promotion_requested','promotion_observed')"):
            retained.append('promotion control grants')
    for table, label in (('consolidation_eligibilities', 'consolidation eligibilities'),
                         ('consolidation_runs', 'consolidation runs')):
        if _table_exists(table) and _count('SELECT count(*) FROM ' + table):
            retained.append(label)
    if _table_exists('memory_entries') and _column_exists('memory_entries', 'promotion_pointer'):
        fields = ['promotion_pointer IS NOT NULL']
        if _column_exists('memory_entries', 'candidate_version'):
            fields.append('candidate_version IS NOT NULL')
        if _count('SELECT count(*) FROM memory_entries WHERE ' + ' OR '.join(fields)):
            retained.append('promotion pointers or candidate data')
    return retained


def assert_no_consolidation_authority(stage):
    """Refuse a destructive downgrade while any 013 authority row survives."""
    retained = retained_consolidation_authority()
    if retained:
        raise RuntimeError(
            f'cannot downgrade consolidation authority at {stage}: database still retains '
            f'{", ".join(retained)}; use compatible forward deployment')
