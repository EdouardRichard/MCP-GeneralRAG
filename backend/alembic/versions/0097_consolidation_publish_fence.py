"""Fence v2 verification receipts and retain rollback group history."""
import importlib.util as _importlib_util
from pathlib import Path as _pathlib_Path

from alembic import op
import sqlalchemy as sa

_downgrade_guard_spec = _importlib_util.spec_from_file_location(
    '_consolidation_downgrade', _pathlib_Path(__file__).resolve().parents[1] / '_consolidation_downgrade.py')
_downgrade_guard = _importlib_util.module_from_spec(_downgrade_guard_spec)
_downgrade_guard_spec.loader.exec_module(_downgrade_guard)
assert_no_consolidation_authority = _downgrade_guard.assert_no_consolidation_authority

revision = '0097_consolidation_publish_fence'
down_revision = '0096_consolidation_authority'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    definition = connection.execute(sa.text("SELECT pg_get_functiondef('memory_log_state(bigint,bigint)'::regprocedure)")).scalar_one()
    before = "results := results || restored->'consolidation_state'->'potential_results';"
    if definition.count(before) != 1:
        raise RuntimeError('unexpected 0096 reducer version')
    connection.execute(sa.text(definition.replace(before, "results := results || (restored->'consolidation_state'->'potential_results');")))
    op.execute("""
        CREATE FUNCTION verify_consolidation_publication() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
        DECLARE eligibility consolidation_eligibilities%ROWTYPE; token jsonb; completed bigint; policy jsonb; scope_status text;
        BEGIN
            SELECT source_event_id INTO completed FROM memory_projection_meta
                WHERE projection_id='current:'||NEW.knowledge_scope_id AND status='complete';
            IF NOT EXISTS(SELECT 1 FROM memory_events WHERE knowledge_scope_id=NEW.knowledge_scope_id
                AND event_id>COALESCE(completed,0) AND event_id<=NEW.source_event_id
                AND event_type='consolidate' AND payload->>'payload_version'='2') THEN RETURN NEW; END IF;
            token := nullif(current_setting('rag_memory.consolidation_fence',true),'')::jsonb;
            SELECT * INTO eligibility FROM consolidation_eligibilities
                WHERE eligibility_id=nullif(current_setting('rag_memory.consolidation_token',true),'')::uuid FOR UPDATE;
            SELECT p.memory_policy,s.status INTO policy,scope_status FROM knowledge_scopes s
                JOIN domain_profiles p ON s.domain_key=p.domain_key WHERE s.scope_id=NEW.knowledge_scope_id FOR SHARE OF s,p;
            IF eligibility.eligibility_id IS NULL OR eligibility.state<>'active' OR eligibility.expires_at<=clock_timestamp()
               OR eligibility.knowledge_scope_id<>NEW.knowledge_scope_id
               OR token IS DISTINCT FROM jsonb_build_object('eligibility_id',eligibility.eligibility_id::text,
                  'scope_id',eligibility.knowledge_scope_id,'run_id',eligibility.run_id::text,
                  'holder_instance_id',eligibility.holder_instance_id::text,'writer_lease_id',eligibility.writer_lease_id,
                  'eligibility_version',eligibility.eligibility_version)
               OR NOT lock_consolidation_writer_lease(eligibility.writer_lease_id,eligibility.holder_instance_id)
               OR nullif(current_setting('rag_memory.consolidation_started_at',true),'') IS NULL
               OR clock_timestamp()-nullif(current_setting('rag_memory.consolidation_started_at',true),'')::timestamptz>=interval '30 seconds'
               OR scope_status IS DISTINCT FROM 'active' OR policy->'consolidation_enabled' IS DISTINCT FROM 'true'::jsonb
               OR policy->'consolidation' IS NULL OR policy->'consolidation'='null'::jsonb THEN
                RAISE EXCEPTION 'CONSOLIDATION_PUBLICATION_FENCE_LOST';
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER memory_consolidation_publication BEFORE INSERT ON memory_projection_receipts
            FOR EACH ROW EXECUTE FUNCTION verify_consolidation_publication();
    """)


def downgrade():
    assert_no_consolidation_authority('0097_consolidation_publish_fence')
    connection = op.get_bind()
    definition = connection.execute(sa.text(
        "SELECT pg_get_functiondef('memory_log_state(bigint,bigint)'::regprocedure)")).scalar_one()
    before = "results := results || restored->'consolidation_state'->'potential_results';"
    after = "results := results || (restored->'consolidation_state'->'potential_results');"
    if definition.count(after) != 1:
        raise RuntimeError('unexpected successor reducer version; refusing partial downgrade')
    connection.execute(sa.text(definition.replace(after, before)))
    op.execute('DROP TRIGGER memory_consolidation_publication ON memory_projection_receipts')
    op.execute('DROP FUNCTION verify_consolidation_publication()')
