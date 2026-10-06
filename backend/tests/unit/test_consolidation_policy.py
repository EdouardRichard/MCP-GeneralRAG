import pytest
from pydantic import ValidationError

from rag_mcp.services.memory_policy import MemoryPolicy


RANGES = {
    'volume_threshold': (1, 5000), 'batch_size': (1, 64), 'reference_limit': (0, 128),
    'max_sources_per_proposal': (1, 32), 'max_chain_depth': (1, 32), 'max_proposals': (1, 128),
    'max_events_per_group': (1, 128), 'max_links_per_proposal': (0, 16),
    'max_context_chars': (0, 1024), 'max_keywords': (0, 16), 'max_input_chars': (4000, 64000),
    'llm_timeout_seconds': (1, 60), 'max_llm_calls': (0, 2), 'run_timeout_seconds': (30, 600),
    'idle_seconds': (1, 600), 'expansion_max_hops': (1, 2), 'expansion_max_nodes': (1, 16),
}


def test_old_policy_stays_disabled_and_enabled_requires_explicit_configuration():
    policy = MemoryPolicy.model_validate({})
    assert policy.consolidation_enabled is False
    assert policy.link_expansion_enabled is False
    assert policy.consolidation is None
    with pytest.raises(ValidationError):
        MemoryPolicy.model_validate({'consolidation_enabled': True})
    assert MemoryPolicy.model_validate({'consolidation_enabled': True, 'consolidation': {}}).consolidation.batch_size == 32


@pytest.mark.parametrize('key,bounds', RANGES.items())
def test_integer_budgets_accept_only_strict_in_range_values(key, bounds):
    low, high = bounds
    for value in (low, high):
        assert getattr(MemoryPolicy.model_validate({'consolidation': {key: value}}).consolidation, key) == value
    for value in (low - 1, high + 1, True, False, 1.0, '1'):
        with pytest.raises(ValidationError):
            MemoryPolicy.model_validate({'consolidation': {key: value}})


@pytest.mark.parametrize('key', ['min_confidence', 'candidate_min_confidence'])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), -.1, 1.1, True, '0.9'])
def test_confidence_rejects_nonfinite_out_of_range_and_coerced_values(key, value):
    with pytest.raises(ValidationError):
        MemoryPolicy.model_validate({'consolidation': {key: value}})


def test_candidate_threshold_must_not_be_lower_than_consolidation_threshold():
    with pytest.raises(ValidationError):
        MemoryPolicy.model_validate({'consolidation': {'min_confidence': .9, 'candidate_min_confidence': .8}})
    assert MemoryPolicy.model_validate({'consolidation': {'min_confidence': .9, 'candidate_min_confidence': .9}})


def test_memory_vocabulary_is_independent_versioned_and_builtin_governed():
    from rag_mcp.config.domain_profiles import validate_memory_link_vocabulary, memory_vocabulary_version
    from rag_mcp.services.domain_profile_service import assert_not_builtin

    link = {'key': 'depends_on', 'from_kinds': ['semantic'], 'to_kinds': ['procedural'],
            'category': 'live_dependency', 'propagation': 'to_to_from', 'recall_direction': 'from_to_to',
            'allow_self': False, 'description': 'Required support'}
    assert validate_memory_link_vocabulary([link]) == [link]
    assert memory_vocabulary_version([link]) == memory_vocabulary_version([dict(reversed(list(link.items())))])
    for change in ({'key': 'evidence'}, {'key': 'supersedes'}, {'key': 'Has Space'},
                   {'propagation': 'none'}, {'allow_self': True}, {'from_kinds': []},
                   {'category': 'association', 'propagation': 'to_to_from'}, {'permission': 'writer'}):
        with pytest.raises(ValueError):
            validate_memory_link_vocabulary([{**link, **change}])
    with pytest.raises(ValueError):
        validate_memory_link_vocabulary([link, link])
    assert validate_memory_link_vocabulary([]) == []
    with pytest.raises(ValueError, match='read-only'):
        assert_not_builtin('generic')


def test_builtin_sync_repairs_memory_vocabulary_drift():
    from types import SimpleNamespace
    from rag_mcp.config.domain_profiles import BUILTIN_DOMAIN_PROFILES
    from rag_mcp.services.domain_profile_service import DomainProfileService
    seed = BUILTIN_DOMAIN_PROFILES['generic']
    row = SimpleNamespace(**{**seed, 'is_builtin': True, 'memory_link_vocabulary': [{'key': 'forged'}]})
    assert DomainProfileService._matches(row, seed) is False
    DomainProfileService._apply(row, seed)
    assert row.memory_link_vocabulary == []
