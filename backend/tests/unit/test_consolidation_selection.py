from datetime import datetime, timedelta, timezone

import pytest

from rag_mcp.services.memory_reducer import reduce_events
from rag_mcp.services.memory_policy import MemoryPolicy


NOW = datetime(2026, 10, 6, 6, tzinfo=timezone.utc)


def event(identifier, *, kind='episodic', offset=-10, status='active', expires_at=None):
    return {'event_id': identifier, 'aggregate_id': identifier, 'knowledge_scope_id': 1,
            'event_type': 'assert', 'occurred_at': (NOW + timedelta(seconds=offset)).isoformat(),
            'payload': {'kind': kind, 'provenance': 'soft', 'status': status, 'content_text': f'Memory {identifier}',
                        'content_hash': str(identifier).zfill(64), 'expires_at': expires_at, 'evidence_refs': []}}


def select(events, **options):
    from rag_mcp.orchestration.consolidation_pipeline import select_window, CurrentSnapshot
    high_water = options.pop('high_water', max(e['event_id'] for e in events))
    snapshot = CurrentSnapshot.from_verified_state(reduce_events(events), scope_id=1,
                                                    high_water_mark=high_water, verified_complete=True)
    return select_window(snapshot, policy=MemoryPolicy.model_validate({'consolidation': options.pop('policy', {})}),
                         now=NOW, start=options.pop('start', NOW - timedelta(seconds=10)), **options)


def test_half_open_window_high_water_and_stable_event_sort():
    window = select([event(4, offset=0), event(3, offset=-1), event(2), event(1)], high_water=3)
    assert [r.memory_id for r in window.input_episode_refs] == [1, 2, 3]
    assert window.start == NOW - timedelta(seconds=10)
    assert window.end == NOW
    assert window.high_water_mark == 3


@pytest.mark.parametrize('state', ['quarantined', 'retired', 'superseded'])
def test_nonactive_states_are_excluded_from_sources_and_references(state):
    events = [event(1), event(2, kind='semantic')]
    if state == 'quarantined':
        events[0]['payload']['status'] = state
        events[1]['payload']['status'] = state
    else:
        for identifier in (1, 2):
            if state == 'retired':
                events.append({'event_id': 10 + identifier, 'aggregate_id': identifier, 'knowledge_scope_id': 1,
                               'event_type': 'retract', 'payload': {}, 'occurred_at': NOW.isoformat()})
            else:
                newer = event(10 + identifier, kind=events[identifier - 1]['payload']['kind'], offset=0)
                newer['event_type'] = 'revise'
                newer['payload']['supersedes_memory_id'] = identifier
                events.append(newer)
    window = select(events)
    assert all(r.memory_id not in (1, 2) for r in window.input_episode_refs + window.reference_refs)


def test_expired_consumed_and_incomplete_versions_cannot_supply_sources_or_references():
    from rag_mcp.orchestration.consolidation_pipeline import SourceVersion
    events = [event(1, expires_at=NOW.isoformat()), event(2), event(3), event(4, kind='semantic', expires_at=NOW.isoformat()),
              event(5, kind='procedural', offset=-999)]
    window = select(events, consumed_versions=((2, 2, 2),), incomplete_memory_ids=(3,))
    assert window.input_episode_refs == ()
    assert [r.memory_id for r in window.reference_refs] == [5]
    assert isinstance(window.reference_refs[0], SourceVersion)


def test_budget_truncation_preserves_original_window_and_never_mixes_references():
    window = select([event(2), event(1), event(3, kind='semantic', offset=-100)], policy={'batch_size': 1})
    assert [r.memory_id for r in window.input_episode_refs] == [1]
    assert [r.memory_id for r in window.reference_refs] == [3]
    assert window.end == NOW
    assert window.truncated is True


def test_unverified_snapshot_and_mutable_nested_inputs_are_rejected_or_frozen():
    from rag_mcp.orchestration.consolidation_pipeline import CurrentSnapshot
    with pytest.raises(ValueError, match='verified complete'):
        CurrentSnapshot.from_verified_state(reduce_events([event(1)]), scope_id=1, high_water_mark=1, verified_complete=False)
    window = select([event(1)])
    with pytest.raises(TypeError):
        window.episodes[1]['content_text'] = 'changed'


def control_event():
    return {'event_id': 2, 'aggregate_id': 2, 'knowledge_scope_id': 1, 'event_type': 'grant',
            'actor': 'management', 'authority': {'source': 'consolidation_control'}, 'occurred_at': NOW.isoformat(),
            'payload': {'payload_version': 2, 'grant_type': 'consolidation_window', 'start': (NOW - timedelta(seconds=10)).isoformat(),
                        'end': NOW.isoformat(), 'frozen_at': NOW.isoformat(), 'high_water_mark': 1,
                        'source_refs': [{'memory_id': 1, 'source_event_id': 1, 'state_event_id': 1,
                                         'content_hash': str(1).zfill(64), 'observed_at': (NOW - timedelta(seconds=10)).isoformat(),
                                         'original_window_id': None}], 'reference_refs': [], 'support_refs': [],
                        'original_window_id': None, 'captured_policy': {'consolidation_enabled': True, 'consolidation': {}},
                        'captured_vocabulary': [], 'policy_hash': 'a' * 64, 'vocabulary_hash': 'b' * 64,
                        'control_adjudication': {'decision': 'seal_window', 'effect': 'control_only', 'rule_version': '013.window.1'},
                        'eligibility_token': {'eligibility_id': '00000000-0000-4000-8000-000000000001',
                            'scope_id': 1, 'run_id': '00000000-0000-4000-8000-000000000002',
                            'holder_instance_id': '00000000-0000-4000-8000-000000000003',
                            'writer_lease_id': 10, 'eligibility_version': 1}}}


def test_control_grant_permanently_seals_window_without_consuming_or_changing_facts():
    before = reduce_events([event(1)])
    after = reduce_events([event(1), control_event()])
    assert after['entries'] == before['entries']
    assert after['links'] == before['links']
    registry = after['consolidation_state']
    assert registry['window_seals']['2']['source_refs'][0]['source_event_id'] == 1
    assert registry['potential_source_outcomes'] == {}
    assert registry['potential_checkpoint'] is None
    assert registry['potential_results'] == {}


@pytest.mark.parametrize('patch', [{'actor': 'memory_tool'}, {'authority': {'source': 'model'}}])
def test_untrusted_control_grant_is_rejected(patch):
    with pytest.raises(PermissionError, match='trusted consolidation control'):
        reduce_events([event(1), {**control_event(), **patch}])


def test_unconsumed_sources_before_checkpoint_remain_eligible():
    from dataclasses import replace
    from rag_mcp.orchestration.consolidation_pipeline import CurrentSnapshot, select_window
    state = reduce_events([event(1), event(2, offset=-1)])
    snapshot = CurrentSnapshot.from_verified_state(state, scope_id=1, high_water_mark=2, verified_complete=True)
    snapshot = replace(snapshot, consolidation_state={**dict(snapshot.consolidation_state),
        'potential_checkpoint': (NOW - timedelta(seconds=5)).isoformat()})
    window = select_window(snapshot, policy=MemoryPolicy.model_validate({'consolidation': {}}), now=NOW)
    assert [ref.memory_id for ref in window.input_episode_refs] == [1, 2]
    assert window.start == NOW - timedelta(seconds=10)


def test_oversized_oldest_episode_does_not_block_fitting_later_input():
    oldest = event(1)
    oldest['payload']['content_text'] = 'x' * 4000
    events = [oldest, event(2, offset=-5), event(3, offset=-1)]
    before = reduce_events(events)
    window = select(events, policy={'max_input_chars': 4000, 'batch_size': 1})
    assert [ref.memory_id for ref in window.input_episode_refs] == [2]
    assert window.truncated
    assert window == select(events, policy={'max_input_chars': 4000, 'batch_size': 1})
    assert before['consolidation_state']['potential_source_outcomes'] == {}
    assert before['entries'][1]['status'] == 'active'


def test_oversized_reference_does_not_block_fitting_later_reference():
    oversized = event(2, kind='semantic')
    oversized['payload']['content_text'] = 'x' * 4000
    window = select([event(1), oversized, event(3, kind='procedural')],
                    policy={'max_input_chars': 4000, 'reference_limit': 1})
    assert [ref.memory_id for ref in window.input_episode_refs] == [1]
    assert [ref.memory_id for ref in window.reference_refs] == [3]
