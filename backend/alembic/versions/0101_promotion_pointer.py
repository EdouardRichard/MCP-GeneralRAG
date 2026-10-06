"""Add permanent promotion request/observation pointers (013 T071).

Deployed predecessors 0095-0100 are frozen. This successor adds the explicit
human promotion surface: `memory_log_state` learns the two management grants
that carry the projected pointer snapshot, a trusted-source trigger validates
the pointer identity and the current candidate marker, and a partial unique
index makes `(scope, memory, candidate_version)` the stable task identity so a
duplicate or concurrent request can never create a second knowledge source or
initial attempt.
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

revision = '0101_promotion_pointer'
down_revision = '0100_propagation_guard_text_fix'
branch_labels = None
depends_on = None

POINTER_FIELDS = """ARRAY['task_id','request_event_id','memory_id','candidate_version','scope_id','actor','reason',
                    'request_id','source_id','initial_processing_run_id','content_hash','filename','format',
                    'requested_at','evidence_attributions','status','published_version_id','result',
                    'attempt_run_ids','authority_event_ids','attempts']"""

PROJECTION_BRANCH = """
                    IF event.payload->>'grant_type' IN ('promotion_requested','promotion_observed') THEN
                        IF event.actor<>'management' OR event.authority->>'source' IS DISTINCT FROM 'management' THEN
                            RAISE EXCEPTION 'trusted promotion control required';
                        END IF;
                        row_data := entries->mid;
                        IF row_data IS NULL THEN RAISE EXCEPTION 'missing promotion target'; END IF;
                        IF event.payload->>'grant_type'='promotion_requested' THEN
                            IF row_data->'promotion_pointer' IS NOT NULL
                               AND row_data->'promotion_pointer'->>'candidate_version'=event.payload->>'candidate_version' THEN
                                RAISE EXCEPTION 'duplicate promotion request';
                            END IF;
                        ELSIF row_data->'promotion_pointer' IS NULL
                           OR row_data->'promotion_pointer'->>'task_id' IS DISTINCT FROM event.payload->'pointer'->>'task_id'
                           OR row_data->'promotion_pointer'->>'source_id' IS DISTINCT FROM event.payload->'pointer'->>'source_id'
                           OR row_data->'promotion_pointer'->>'candidate_version' IS DISTINCT FROM event.payload->'pointer'->>'candidate_version'
                           OR row_data->'promotion_pointer'->>'initial_processing_run_id' IS DISTINCT FROM event.payload->'pointer'->>'initial_processing_run_id'
                           OR jsonb_array_length(event.payload->'pointer'->'authority_event_ids')
                              <> jsonb_array_length(row_data->'promotion_pointer'->'authority_event_ids')+1
                           OR (event.payload->'pointer'->'authority_event_ids'->0)
                              IS DISTINCT FROM (row_data->'promotion_pointer'->'authority_event_ids'->0)
                           OR (event.payload->'pointer'->'authority_event_ids'->-2)
                              IS DISTINCT FROM (row_data->'promotion_pointer'->'authority_event_ids'->-1) THEN
                            RAISE EXCEPTION 'promotion observation does not extend the existing task';
                        END IF;
                        row_data := row_data || jsonb_build_object('promotion_pointer',event.payload->'pointer');
                        entries := jsonb_set(entries,ARRAY[mid],row_data);
                    END IF;
"""

GUARD_FUNCTION = """
        CREATE FUNCTION guard_promotion_event() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE pointer jsonb; keys text[]; entry jsonb;
        BEGIN
            IF NEW.event_type<>'grant'
               OR NEW.payload->>'grant_type' NOT IN ('promotion_requested','promotion_observed') THEN
                RETURN NEW;
            END IF;
            IF current_user<>'rag_memory_reducer' OR NEW.actor<>'management'
               OR NEW.authority->>'source' IS DISTINCT FROM 'management'
               OR NEW.scope_meta<>jsonb_build_object('knowledge_scope_id',NEW.knowledge_scope_id) THEN
                RAISE EXCEPTION 'trusted promotion control required';
            END IF;
            keys := CASE NEW.payload->>'grant_type' WHEN 'promotion_requested'
                THEN ARRAY['payload_version','grant_type','memory_id','candidate_version','source_id','request_id','reason','pointer']
                ELSE ARRAY['payload_version','grant_type','memory_id','source_id','request_id','pointer'] END;
            IF jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'
               OR NOT NEW.payload ?& keys
               OR (SELECT count(*) FROM jsonb_object_keys(NEW.payload))<>array_length(keys,1)
               OR NEW.payload->>'payload_version' IS DISTINCT FROM '2' THEN
                RAISE EXCEPTION 'invalid promotion grant';
            END IF;
            pointer := NEW.payload->'pointer';
            IF jsonb_typeof(pointer) IS DISTINCT FROM 'object'
               OR NOT pointer ?& @POINTER_FIELDS@
               OR (SELECT count(*) FROM jsonb_object_keys(pointer))<>21
               OR pointer->>'task_id' IS DISTINCT FROM NEW.event_id::text
               OR (pointer->>'request_event_id')::bigint IS DISTINCT FROM NEW.event_id
               OR (pointer->>'memory_id')::bigint IS DISTINCT FROM NEW.aggregate_id
               OR (pointer->>'scope_id')::bigint IS DISTINCT FROM NEW.knowledge_scope_id
               OR (pointer->>'source_id')::bigint IS DISTINCT FROM (NEW.payload->>'source_id')::bigint
               OR pointer->>'actor'<>'management'
               OR pointer->>'request_id' IS DISTINCT FROM NEW.payload->>'request_id'
               OR COALESCE(pointer->>'candidate_version','') !~ '^[0-9a-f]{64}$'
               OR pointer->>'status' NOT IN ('accepted','uploaded','processing','failed','published')
               OR (pointer->>'status'='published')
                  <> (pointer->'published_version_id' IS NOT NULL AND pointer->'published_version_id'<>'null'::jsonb)
               OR jsonb_typeof(pointer->'attempt_run_ids') IS DISTINCT FROM 'array'
               OR jsonb_array_length(pointer->'attempt_run_ids')<1
               OR jsonb_typeof(pointer->'authority_event_ids') IS DISTINCT FROM 'array'
               OR (pointer->'authority_event_ids'->-1)::bigint IS DISTINCT FROM NEW.event_id
               OR jsonb_typeof(pointer->'attempts') IS DISTINCT FROM 'array'
               OR jsonb_array_length(pointer->'attempts')<>jsonb_array_length(pointer->'attempt_run_ids')
               OR jsonb_typeof(pointer->'evidence_attributions') IS DISTINCT FROM 'array'
               OR (NEW.payload->>'grant_type'='promotion_requested'
                   AND (pointer->>'candidate_version' IS DISTINCT FROM NEW.payload->>'candidate_version'
                        OR pointer->>'reason' IS DISTINCT FROM NEW.payload->>'reason')) THEN
                RAISE EXCEPTION 'invalid promotion pointer';
            END IF;
            entry := memory_log_state(NEW.knowledge_scope_id,NEW.event_id-1)->'entries'->(NEW.aggregate_id::text);
            IF entry IS NULL THEN RAISE EXCEPTION 'missing promotion target'; END IF;
            IF NEW.payload->>'grant_type'='promotion_requested' THEN
                IF entry->>'status'<>'active' OR entry->>'kind'<>'semantic'
                   OR entry->>'candidate_version' IS DISTINCT FROM pointer->>'candidate_version' THEN
                    RAISE EXCEPTION 'MEMORY_CANDIDATE_VERSION_CHANGED';
                END IF;
            END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER memory_events_promotion_control BEFORE INSERT ON memory_events
            FOR EACH ROW EXECUTE FUNCTION guard_promotion_event();
"""


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
    replace_function('memory_log_state(bigint,bigint)', ((
        """                        propagations := jsonb_set(propagations,ARRAY[event.event_id::text],event.payload ||
                            jsonb_build_object('seal_id',event.event_id,'knowledge_scope_id',scope_id));
                    END IF;
                    IF event.payload ? 'binding_id' THEN""",
        """                        propagations := jsonb_set(propagations,ARRAY[event.event_id::text],event.payload ||
                            jsonb_build_object('seal_id',event.event_id,'knowledge_scope_id',scope_id));
                    END IF;
""" + PROJECTION_BRANCH + """                    IF event.payload ? 'binding_id' THEN""",
    ),))
    op.execute("""
        CREATE UNIQUE INDEX uq_promotion_request ON memory_events
            (knowledge_scope_id,aggregate_id,(payload->>'candidate_version'))
            WHERE event_type='grant' AND payload->>'grant_type'='promotion_requested';
""")
    op.execute(GUARD_FUNCTION.replace('@POINTER_FIELDS@', POINTER_FIELDS))


# --- reverse fragments generated from upgrade() (do not edit by hand) ---
REVERSE_FRAGMENTS = {
    'memory_log_state(bigint,bigint)': (
        ("""                        propagations := jsonb_set(propagations,ARRAY[event.event_id::text],event.payload ||
                            jsonb_build_object('seal_id',event.event_id,'knowledge_scope_id',scope_id));
                    END IF;

                    IF event.payload->>'grant_type' IN ('promotion_requested','promotion_observed') THEN
                        IF event.actor<>'management' OR event.authority->>'source' IS DISTINCT FROM 'management' THEN
                            RAISE EXCEPTION 'trusted promotion control required';
                        END IF;
                        row_data := entries->mid;
                        IF row_data IS NULL THEN RAISE EXCEPTION 'missing promotion target'; END IF;
                        IF event.payload->>'grant_type'='promotion_requested' THEN
                            IF row_data->'promotion_pointer' IS NOT NULL
                               AND row_data->'promotion_pointer'->>'candidate_version'=event.payload->>'candidate_version' THEN
                                RAISE EXCEPTION 'duplicate promotion request';
                            END IF;
                        ELSIF row_data->'promotion_pointer' IS NULL
                           OR row_data->'promotion_pointer'->>'task_id' IS DISTINCT FROM event.payload->'pointer'->>'task_id'
                           OR row_data->'promotion_pointer'->>'source_id' IS DISTINCT FROM event.payload->'pointer'->>'source_id'
                           OR row_data->'promotion_pointer'->>'candidate_version' IS DISTINCT FROM event.payload->'pointer'->>'candidate_version'
                           OR row_data->'promotion_pointer'->>'initial_processing_run_id' IS DISTINCT FROM event.payload->'pointer'->>'initial_processing_run_id'
                           OR jsonb_array_length(event.payload->'pointer'->'authority_event_ids')
                              <> jsonb_array_length(row_data->'promotion_pointer'->'authority_event_ids')+1
                           OR (event.payload->'pointer'->'authority_event_ids'->0)
                              IS DISTINCT FROM (row_data->'promotion_pointer'->'authority_event_ids'->0)
                           OR (event.payload->'pointer'->'authority_event_ids'->-2)
                              IS DISTINCT FROM (row_data->'promotion_pointer'->'authority_event_ids'->-1) THEN
                            RAISE EXCEPTION 'promotion observation does not extend the existing task';
                        END IF;
                        row_data := row_data || jsonb_build_object('promotion_pointer',event.payload->'pointer');
                        entries := jsonb_set(entries,ARRAY[mid],row_data);
                    END IF;
                    IF event.payload ? 'binding_id' THEN""",
         """                        propagations := jsonb_set(propagations,ARRAY[event.event_id::text],event.payload ||
                            jsonb_build_object('seal_id',event.event_id,'knowledge_scope_id',scope_id));
                    END IF;
                    IF event.payload ? 'binding_id' THEN"""),
    ),
}
# --- end reverse fragments ---


def downgrade():
    assert_no_consolidation_authority('0101_promotion_pointer')
    for signature, fragments in REVERSE_FRAGMENTS.items():
        replace_function(signature, tuple(reversed(fragments)))
    op.execute('DROP TRIGGER memory_events_promotion_control ON memory_events')
    op.execute('DROP FUNCTION guard_promotion_event()')
    op.execute('DROP INDEX uq_promotion_request')
