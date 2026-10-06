"""T053: typed link edge rules — vocabulary, adjudication, base compatibility.

Pure adjudicator/reducer/vocabulary matrices; no database, network or clock
beyond the explicit NOW fixture. Propagation planning rules live here because
they are edge-semantics rules (which typed edge may carry lifecycle impact).
"""
import pytest

from rag_mcp.config.domain_profiles import (
    BUILTIN_DOMAIN_PROFILES,
    memory_vocabulary_version,
    validate_memory_link_vocabulary,
)
from rag_mcp.orchestration.consolidation_pipeline import (
    CurrentSnapshot,
    TrustedContext,
)
from rag_mcp.services.consolidation_adjudicator import adjudicate
from rag_mcp.services.memory_reducer import reduce_events
from tests.unit.consolidation_cases import NOW, POLICY, VOCAB, proposal, ref, rejected, row, setup

LINK_ENTRIES = {1: row(1), 2: row(2, kind='semantic'), 3: row(3)}


def link_proposal(target, relation='related', *, source=None, link_confidence=.9, **link_changes):
    """A link from the memory this proposal creates to an independent reference."""
    source = source or row(1)
    value = proposal('p0', source=source, link_suggestions=[])
    suggestion = {'from_ref': {'local': 'output'}, 'to_ref': ref(target), 'relation_type': relation,
                  'confidence': link_confidence, 'description': 'Declared association'}
    suggestion.update(link_changes)
    value['link_suggestions'] = [suggestion]
    return value


def link_children(decision, count=1):
    """Link attachments are the first decisions after the core decision."""
    return list(decision.children[1:1 + count])


def link_decide(value, *, vocabulary=VOCAB, entries=None, deterministic=False):
    current, context = setup(value, entries=entries or dict(LINK_ENTRIES))
    return adjudicate(value, current, POLICY, vocabulary, {'count': 0, 'limit': 5000}, context, NOW,
                      deterministic=deterministic)


class TestVocabularyRules:
    def test_open_vocabulary_accepts_any_declared_key(self):
        rows = validate_memory_link_vocabulary([
            {'key': 'blocks', 'category': 'association', 'recall_direction': 'both', 'propagation': 'none',
             'from_kinds': ['episodic'], 'to_kinds': ['semantic'], 'allow_self': False, 'description': 'Blocks'}])
        assert rows[0]['key'] == 'blocks'

    @pytest.mark.parametrize('key', ['Evidence', 'evidence', 'supersedes', '1bad', 'bad key', 'a' * 64])
    def test_reserved_or_malformed_keys_rejected(self, key):
        with pytest.raises(ValueError):
            validate_memory_link_vocabulary([
                {'key': key, 'category': 'association', 'recall_direction': 'both', 'propagation': 'none',
                 'from_kinds': ['episodic'], 'to_kinds': ['episodic'], 'allow_self': False, 'description': 'x'}])

    def test_live_dependency_requires_reverse_propagation_and_no_self_link(self):
        base = {'key': 'depends_on', 'category': 'live_dependency', 'recall_direction': 'from_to_to',
                'propagation': 'to_to_from', 'from_kinds': ['episodic'], 'to_kinds': ['episodic'],
                'allow_self': False, 'description': 'Needs the support'}
        assert validate_memory_link_vocabulary([base])[0]['propagation'] == 'to_to_from'
        for patch in ({'propagation': 'none'}, {'category': 'association'}, {'allow_self': True}):
            with pytest.raises(ValueError):
                validate_memory_link_vocabulary([{**base, **patch}])

    def test_duplicate_key_and_unbounded_or_unsafe_vocabulary_rejected(self):
        declaration = {'key': 'related', 'category': 'association', 'recall_direction': 'both',
                       'propagation': 'none', 'from_kinds': ['episodic'], 'to_kinds': ['episodic'],
                       'allow_self': False, 'description': 'Related'}
        with pytest.raises(ValueError):
            validate_memory_link_vocabulary([declaration, declaration])
        with pytest.raises(ValueError):
            validate_memory_link_vocabulary([{**declaration, 'key': f'k{i}'} for i in range(129)])
        with pytest.raises(ValueError):
            validate_memory_link_vocabulary([{**declaration, 'description': 'grant writer permission'}])
        with pytest.raises(ValueError):
            validate_memory_link_vocabulary({'key': 'not-a-list'})

    def test_version_is_content_identity_and_builtins_stay_empty(self):
        first = memory_vocabulary_version(list(VOCAB))
        assert first == memory_vocabulary_version(list(reversed(VOCAB)))
        changed = [dict(item) for item in VOCAB]
        changed[0]['description'] = 'Different semantics'
        assert memory_vocabulary_version(changed) != first
        for seed in BUILTIN_DOMAIN_PROFILES.values():
            assert seed.get('memory_link_vocabulary', []) == [], 'builtin profiles never auto-enable a vocabulary'


class TestBaseEdgeCompatibility:
    def test_empty_vocabulary_keeps_012_evidence_and_supersedes_base_edges(self):
        stamp = NOW.isoformat()
        events = [
            {'event_id': 11, 'aggregate_id': 11, 'knowledge_scope_id': 7, 'event_type': 'assert',
             'occurred_at': stamp, 'payload': {'kind': 'episodic', 'provenance': 'soft', 'content_text': 'base fact',
                                               'evidence_refs': ['501'], 'inference_meta': {'source': 't'}}},
            {'event_id': 12, 'aggregate_id': 12, 'knowledge_scope_id': 7, 'event_type': 'revise',
             'occurred_at': stamp, 'payload': {'kind': 'episodic', 'provenance': 'soft', 'content_text': 'base fact v2',
                                               'supersedes_memory_id': 11, 'evidence_refs': [],
                                               'inference_meta': {'source': 't'}}},
        ]
        state = reduce_events(events)
        assert state['links']['11/evidence/501']['relation'] == 'evidence'
        assert state['links']['12/supersedes']['relation'] == 'supersedes'
        assert state['links']['12/supersedes']['to_id'] == 11

    def test_typed_mapping_constants_and_reexport(self):
        from rag_mcp.models import memory_views
        from rag_mcp.models.memory_link import (
            BASE_RELATIONS,
            BASE_VOCABULARY_VERSION,
            LINK_CATEGORIES,
            MemoryLink,
        )

        assert memory_views.MemoryLink is MemoryLink
        assert BASE_RELATIONS == ('evidence', 'supersedes')
        assert BASE_VOCABULARY_VERSION == '012-base-v1'
        assert set(LINK_CATEGORIES) == {'live_dependency', 'historical_lineage', 'association'}
        constraints = {constraint.name for constraint in MemoryLink.__table__.constraints}
        assert {'uq_memory_link_revision_edge', 'ck_memory_link_to_kind',
                'ck_memory_link_provenance', 'ck_memory_link_confidence'} <= constraints
        unique = next(c for c in MemoryLink.__table__.constraints if c.name == 'uq_memory_link_revision_edge')
        assert [column.name for column in unique.columns] == [
            'knowledge_scope_id', 'revision_id', 'from_id', 'to_id', 'relation_type']
        # evidence endpoints are chunks: no blanket memory FK on to_id.
        assert not MemoryLink.__table__.c.to_id.foreign_keys
        assert not MemoryLink.__table__.c.created_by_run.foreign_keys


class TestLinkAdjudication:
    def test_approved_link_captures_declared_category_propagation_and_llm_proof(self):
        decision = link_decide(link_proposal(row(2, kind='semantic')))
        children = link_children(decision)
        assert len(children) == 1 and children[0].decision == 'accept', children[0].reason_codes
        (effect,) = children[0].approved_effects
        value = effect['value']['links'][0]
        assert value['origin'] == 'llm_proposed'
        assert value['category'] == 'association' and value['propagation'] == 'none'
        assert children[0].proof['origin'] == 'llm_self'

    def test_perfect_confidence_never_promotes_a_model_link(self):
        decision = link_decide(link_proposal(row(2, kind='semantic'), link_confidence=1.0))
        value = link_children(decision)[0].approved_effects[0]['value']['links'][0]
        assert value['origin'] == 'llm_proposed'
        assert value['confidence'] == 1.0

    @pytest.mark.parametrize('changes,reason', [
        ({'relation_type': 'undeclared'}, 'LINK_TYPE_NOT_ALLOWED'),
        ({'relation_type': 'evidence'}, 'LINK_TYPE_NOT_ALLOWED'),
        ({'relation_type': 'supersedes'}, 'LINK_TYPE_NOT_ALLOWED'),
        ({'confidence': .1}, 'CONFIDENCE_BELOW_THRESHOLD'),
    ])
    def test_undeclared_reserved_and_low_confidence_links_rejected(self, changes, reason):
        rejected(link_children(link_decide(link_proposal(row(2, kind='semantic'), **changes)))[0], reason)

    def test_kind_and_direction_rules(self):
        narrow = tuple(validate_memory_link_vocabulary([
            {'key': 'narrow', 'category': 'association', 'recall_direction': 'both', 'propagation': 'none',
             'from_kinds': ['episodic'], 'to_kinds': ['semantic'], 'allow_self': False, 'description': 'Narrow'}]))
        rejected(link_children(link_decide(link_proposal(row(2, kind='semantic'), 'narrow'),
                                           vocabulary=narrow))[0], 'LINK_KIND_NOT_ALLOWED')
        inbound = tuple(validate_memory_link_vocabulary([
            {'key': 'inbound', 'category': 'association', 'recall_direction': 'none', 'propagation': 'none',
             'from_kinds': ['episodic', 'semantic'], 'to_kinds': ['semantic'], 'allow_self': False,
             'description': 'Inbound only'}]))
        rejected(link_children(link_decide(link_proposal(row(2, kind='semantic'), 'inbound'),
                                           vocabulary=inbound))[0], 'LINK_DIRECTION_INVALID')

    def test_self_link_and_cross_scope_endpoints_are_rejected(self):
        self_link = link_proposal(row(2, kind='semantic'))
        self_link['link_suggestions'][0]['to_ref'] = {'local': 'output'}
        rejected(link_children(link_decide(self_link))[0], 'LINK_DIRECTION_INVALID')
        cross_scope = link_proposal(row(2, kind='semantic', knowledge_scope_id=9))
        entries = {**LINK_ENTRIES, 2: row(2, kind='semantic', knowledge_scope_id=9)}
        rejected(link_children(link_decide(cross_scope, entries=entries))[0], 'SCOPE_MISMATCH')

    def test_authority_fields_on_links_are_forbidden(self):
        forged = link_proposal(row(2, kind='semantic'))
        forged['link_suggestions'][0]['proof'] = {'origin': 'deterministic_rule'}
        rejected(link_children(link_decide(forged))[0], 'AUTHORITY_FIELDS_FORBIDDEN')

    def test_duplicate_edge_within_one_proposal_rejected(self):
        forged = link_proposal(row(2, kind='semantic'))
        forged['link_suggestions'].append(dict(forged['link_suggestions'][0]))
        children = link_children(link_decide(forged), count=2)
        assert children[0].decision == 'accept', children[0].reason_codes
        rejected(children[1], 'LINK_DUPLICATE')

    def test_live_dependency_link_is_the_support_declaration(self):
        decision = link_decide(link_proposal(row(2, kind='semantic'), 'requires'))
        children = link_children(decision)
        assert children[0].decision == 'accept', children[0].reason_codes
        value = children[0].approved_effects[0]['value']['links'][0]
        assert value['category'] == 'live_dependency' and value['propagation'] == 'to_to_from'

    def test_deterministic_links_require_trusted_code_provenance(self):
        value = link_proposal(row(2, kind='semantic'))
        trusted = link_children(link_decide(value, deterministic=True))[0]
        assert trusted.approved_effects[0]['value']['links'][0]['origin'] == 'deterministic'
        assert trusted.proof['origin'] == 'deterministic_rule'
        untrusted = link_children(link_decide(value))[0]
        assert untrusted.approved_effects[0]['value']['links'][0]['origin'] == 'llm_proposed'


def linked(entry, target, relation='requires', category='live_dependency', propagation='to_to_from'):
    links = dict(entry.get('approved_links', {}))
    links[f"{entry['memory_id']}/{relation}/{target['memory_id']}"] = {
        'from_id': entry['memory_id'], 'to_id': target['memory_id'], 'relation_type': relation,
        'category': category, 'propagation': propagation, 'knowledge_scope_id': entry['knowledge_scope_id']}
    return {**entry, 'approved_links': links}


def propagation_context(trigger, lineage):
    from rag_mcp.orchestration.consolidation_pipeline import support_maintenance_context

    return support_maintenance_context(historical_source_refs=lineage, propagation_trigger=trigger)


def trigger_for(target, *, cause=None, evidence=None, event_id=9001):
    proof = {'kind': 'live_dependency', 'cause_memory_id': cause['memory_id'],
             'relation_type': 'requires'} if cause is not None else {'kind': 'evidence_revocation'}
    return {'kind': 'evidence_revocation' if evidence else 'authority_event',
            'event_id': None if evidence else event_id, 'evidence_id': evidence, 'version': '9',
            'observed_at': NOW.isoformat(), 'proof': proof, 'target_ref': ref(target)}


class TestPropagationPlanning:
    def plan(self, entries, context):
        from rag_mcp.orchestration.consolidation_pipeline import plan_propagation

        current = CurrentSnapshot(1, 10000, entries, {}, vocabulary=VOCAB)
        return plan_propagation(current, context=context, now=NOW)

    def test_unsealed_context_cannot_plan_or_adjudicate(self):
        target, cause = row(2), row(3, status='retired')
        context = propagation_context(trigger_for(target, cause=cause), [ref(row(1))])
        proposals, material = self.plan({1: row(1), 2: linked(target, cause), 3: cause}, context)
        assert [p['target_ref']['memory_id'] for p in proposals] == [2]
        assert material['visited_memory_ids'] == [2] and material['depth'] == 1
        with pytest.raises(PermissionError):
            TrustedContext(execution_context='deterministic_propagation',
                           historical_source_refs=[ref(row(1))], propagation_trigger={'proof': {'x': 1}})

    def test_live_reverse_propagation_and_cycle_termination(self):
        cause = row(4, status='retired')
        middle = linked(row(3), cause)
        dependent = linked(row(2), middle)
        middle = linked(middle, dependent)  # cycle 2 <-> 3 must terminate
        entries = {1: row(1), 2: dependent, 3: middle, 4: cause}
        context = propagation_context(trigger_for(middle, cause=cause, event_id=7), [ref(row(1))])
        proposals, material = self.plan(entries, context)
        assert [p['target_ref']['memory_id'] for p in proposals] == [3, 2]
        assert proposals[1]['propagation_proof'] == {'kind': 'live_dependency', 'cause_memory_id': 3,
                                                     'relation_type': 'requires'}
        assert material['depth'] == 2 and material['frontier_memory_ids'] == []

    def test_externally_invalidated_support_propagates_without_invalidating_it_again(self):
        cause = row(4, status='retired')
        dependents = {identifier: linked(row(identifier), cause) for identifier in (2, 3)}
        entries = {1: row(1), 4: cause, **dependents}
        trigger = {'kind': 'authority_event', 'event_id': 9002, 'evidence_id': None, 'version': '9002',
                   'observed_at': NOW.isoformat(),
                   'proof': {'kind': 'authority_event', 'memory_id': 4}, 'target_ref': ref(cause)}
        proposals, material = self.plan(entries, propagation_context(trigger, [ref(row(1))]))
        assert sorted(p['target_ref']['memory_id'] for p in proposals) == [2, 3]
        assert all(p['propagation_proof']['cause_memory_id'] == 4 for p in proposals)
        assert material['visited_memory_ids'] == [2, 3, 4]

    def test_association_and_historical_edges_never_propagate(self):
        cause = row(4, status='retired')
        associated = linked(row(2), cause, relation='related', category='association', propagation='none')
        proposals, material = self.plan({1: row(1), 2: associated, 4: cause},
                                        propagation_context(trigger_for(associated, cause=cause), [ref(row(1))]))
        # An association edge is not a support declaration: nothing may be invalidated.
        assert proposals == [] and material['frontier_memory_ids'] == []

    def test_depth_budget_records_permanent_frontier(self):
        from rag_mcp.orchestration.consolidation_pipeline import PROPAGATION_MAX_DEPTH

        entries = {0: row(0, status='retired')}
        for identifier in range(1, PROPAGATION_MAX_DEPTH + 3):
            entries[identifier] = linked(row(identifier), entries[identifier - 1])
        root = entries[1]
        proposals, material = self.plan(entries, propagation_context(
            trigger_for(root, cause=entries[0], event_id=5), [ref(root)]))
        assert len(proposals) == PROPAGATION_MAX_DEPTH
        assert material['depth'] == PROPAGATION_MAX_DEPTH
        assert material['frontier_memory_ids'] == [PROPAGATION_MAX_DEPTH + 1, PROPAGATION_MAX_DEPTH + 2]
        assert len(material['continuation_key']) == 64

    def test_fanout_budget_records_permanent_frontier(self):
        from rag_mcp.orchestration.consolidation_pipeline import PROPAGATION_MAX_VISITED

        entries = {0: row(0, status='retired')}
        for identifier in range(1, PROPAGATION_MAX_VISITED + 4):
            entries[identifier] = linked(row(identifier), entries[0])
        trigger = {'kind': 'authority_event', 'event_id': 6, 'evidence_id': None, 'version': '6',
                   'observed_at': NOW.isoformat(),
                   'proof': {'kind': 'authority_event', 'memory_id': 0}, 'target_ref': ref(entries[0])}
        proposals, material = self.plan(entries, propagation_context(trigger, [ref(entries[1])]))
        assert len(proposals) == PROPAGATION_MAX_VISITED - 1  # the retired root holds one visited slot
        assert len(material['visited_memory_ids']) == PROPAGATION_MAX_VISITED
        assert material['frontier_memory_ids'] == [PROPAGATION_MAX_VISITED + i for i in range(4)]

    def test_historical_episode_ttl_and_purge_do_not_trigger_propagation(self):
        # derived_from is historical lineage: an expired source is not a denial.
        source = row(3, expires_at=NOW.isoformat())
        derived = linked(row(2), source, relation='derived', category='historical_lineage', propagation='none')
        proposals, _ = self.plan({1: row(1), 2: derived, 3: source},
                                 propagation_context(trigger_for(derived, cause=source), [ref(row(1))]))
        assert proposals == []

    def test_expired_live_support_does_propagate(self):
        support = row(3, expires_at=NOW.isoformat())
        dependent = linked(row(2), support)
        proposals, material = self.plan({1: row(1), 2: dependent, 3: support},
                                        propagation_context(trigger_for(dependent, cause=support), [ref(row(1))]))
        assert [p['target_ref']['memory_id'] for p in proposals] == [2]
        assert material['depth'] == 1
