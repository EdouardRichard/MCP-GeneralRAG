"""Close statement-level deletion and unlogged promotion metadata bypasses."""
from alembic import op
import sqlalchemy as sa

revision = "0090_memory_bypass_guards"
down_revision = "0089_memory_retention"
branch_labels = None
depends_on = None

PROJECTION_TABLES = ("memory_entries", "memory_salience", "memory_links", "memory_summary_nodes", "memory_projection_meta", "scope_bindings")
OLD = "OR NEW.expires_at IS DISTINCT FROM (source_record.payload->>'expires_at')::timestamptz THEN"
NEW = """OR NEW.expires_at IS DISTINCT FROM (source_record.payload->>'expires_at')::timestamptz
               OR NEW.promote_candidate_at IS DISTINCT FROM (source_record.payload->>'promote_candidate_at')::timestamptz THEN"""


def replace_source_guard(before, after):
    connection = op.get_bind()
    definition = connection.execute(sa.text("SELECT pg_get_functiondef('verify_memory_source_fields()'::regprocedure)")).scalar_one()
    if definition.count(before) != 1:
        raise RuntimeError("unexpected source guard version; refusing partial migration")
    connection.execute(sa.text(definition.replace(before, after)))


def upgrade():
    for table in PROJECTION_TABLES:
        op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION reject_memory_projection_delete()")
    replace_source_guard(OLD, NEW)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM memory_events")).scalar_one():
        raise RuntimeError("cannot weaken projection guards with retained authority events")
    replace_source_guard(NEW, OLD)
    for table in PROJECTION_TABLES:
        op.execute(f"DROP TRIGGER {table}_no_truncate ON {table}")
