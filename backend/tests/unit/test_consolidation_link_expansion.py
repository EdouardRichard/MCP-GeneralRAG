"""T055/T063: candidate link expansion planner and recall enhancement behavior."""
import pytest

from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.services.memory_service import MemoryService
from tests.integration.consolidation_commit_fixtures import commit, prepared
from tests.integration.consolidation_fixtures import StableEmbedding, create_scope, recorded_episode
from tests.unit.consolidation_gate import build_report, install_registry


def declared(direction='both', category='association'):
    return {direction and 'related': {'key': 'related', 'recall_direction': direction, 'category': category,
                                      'propagation': 'none'}}


def edge(source, target, relation='related', scope=1):
    return {'from_id': source, 'to_id': target, 'relation_type': relation, 'knowledge_scope_id': scope}


class TestExpansionPlanner:
    def plan(self, selected, links, eligible, vocabulary=None, **budgets):
        from rag_mcp.services.memory_reader import plan_link_expansion

        rows = {mid: {'memory_id': mid, 'knowledge_scope_id': 1} for mid in eligible}
        return plan_link_expansion(selected, links, vocabulary or declared(), rows,
                                   **{'max_hops': 1, 'max_nodes': 8, 'limit': 50, **budgets})

    def test_direction_semantics(self):
        links = [edge(1, 2)]
        assert self.plan([1], links, [1, 2], declared('from_to_to')) == [2]
        assert self.plan([2], links, [1, 2], declared('from_to_to')) == []
        assert self.plan([2], links, [1, 2], declared('to_to_from')) == [1]
        assert self.plan([1], links, [1, 2], declared('to_to_from')) == []
        assert self.plan([2], links, [1, 2], declared('both')) == [1]
        assert self.plan([1], links, [1, 2], declared('none')) == []

    def test_undeclared_base_and_cross_scope_edges_never_expand(self):
        links = [edge(1, 2, relation='undeclared'), edge(1, 3, scope=9),
                 {'from_id': 1, 'to_id': '501', 'relation': 'evidence', 'knowledge_scope_id': 1},
                 edge(1, 4)]
        assert self.plan([1], links, [1, 2, 3, 4]) == [4]

    def test_ineligible_endpoints_cycles_and_budgets(self):
        chain = [edge(1, 2), edge(2, 3), edge(3, 4), edge(4, 2)]
        assert self.plan([1], chain, [1, 2, 3, 4], max_hops=1) == [2]
        # `related` is declared `both`, so the closing edge 4-2 makes 4 a
        # second-hop neighbour of 2 as well; the cycle itself adds nothing more.
        assert self.plan([1], chain, [1, 2, 3, 4], max_hops=2) == [2, 3, 4]
        assert self.plan([1], chain, [1, 2, 3, 4], max_hops=4) == [2, 3, 4]
        assert self.plan([1], chain, [1, 2, 3, 4], max_hops=2, max_nodes=1) == [2]
        assert self.plan([1], chain, [1, 3, 4]) == []  # 2 is not eligible; traversal stops there
        assert self.plan([1], [edge(1, 2)], [1, 2], limit=1) == []

    def test_deterministic_order_independent_of_link_ordering(self):
        links = [edge(1, 3), edge(1, 2), edge(1, 4)]
        first = self.plan([1], links, [1, 2, 3, 4])
        assert first == self.plan([1], list(reversed(links)), [1, 2, 3, 4]) == [2, 3, 4]


@pytest.mark.asyncio
async def test_legacy_calls_stay_byte_compatible_without_flags(db_session, memory_writer_owner):
    scope = await create_scope(db_session)
    service = MemoryService(db_session, embedding_provider=StableEmbedding())
    first = (await recorded_episode(service, scope, 'Legacy alpha'))['memory_id']
    second = (await recorded_episode(service, scope, 'Legacy beta'))['memory_id']
    omitted = await service.recall(scope_ref=[str(scope)], memory_ids=[first, second])
    explicit = await service.recall(scope_ref=[str(scope)], memory_ids=[first, second],
                                    include_linked=False, include_context=False)
    assert 'enhancement' not in omitted and 'enhancement' not in explicit
    assert [{key: value for key, value in omitted.items() if key != 'request_id'}] == [
        {key: value for key, value in explicit.items() if key != 'request_id'}]
    assert all('context' not in memory for memory in omitted['memories'])


@pytest.mark.asyncio
async def test_include_context_is_presentation_only_after_final_selection(db_session, memory_writer_owner):
    fixture = await prepared(db_session, memory_writer_owner, count=1)
    service, _runtime, token = fixture[0], fixture[1], fixture[2]
    result = await commit(fixture)
    assert result.status == 'completed'
    output = result.output_memory_ids[0]
    plain = await service.recall(scope_ref=[str(token.scope_id)], memory_ids=[output])
    enhanced = await service.recall(scope_ref=[str(token.scope_id)], memory_ids=[output], include_context=True)
    assert 'enhancement' not in plain
    assert enhanced['enhancement']['context_status'] == 'available'
    assert enhanced['enhancement']['link_expansion_status'] == 'disabled'
    memory = enhanced['memories'][0]
    assert memory['context']['digest'] == 'Navigation summary 0'
    assert memory['context']['keywords'] and memory['context']['version'] and memory['context']['source']
    # Candidates, order and content fields are identical to the legacy call.
    assert [row['memory_id'] for row in enhanced['memories']] == [row['memory_id'] for row in plain['memories']]
    assert enhanced['counts']['candidates'] == plain['counts']['candidates']
    assert all(memory[key] == plain['memories'][0][key] for key in
               ('content_excerpt', 'truncated', 'content_length', 'match'))
    unavailable = await service.recall(scope_ref=[str(token.scope_id)],
                                       memory_ids=[token_window_source(fixture)], include_context=True)
    assert unavailable['enhancement']['context_status'] == 'unavailable'


def token_window_source(fixture):
    return fixture[4].window.input_episode_refs[0].memory_id


@pytest.mark.asyncio
async def test_link_expansion_three_gate_combinations(db_session, memory_writer_owner, tmp_path, monkeypatch):
    fixture = await prepared(db_session, memory_writer_owner, links=True)
    service, token = fixture[0], fixture[2]
    result = await commit(fixture)
    assert result.status == 'completed'
    output = result.output_memory_ids[0]
    reference = fixture[4].window.reference_refs[0].memory_id
    direct = await service.recall(scope_ref=[str(token.scope_id)], memory_ids=[output])
    assert [row['memory_id'] for row in direct['memories']] == [output]

    # Gate 1/2: client opted in but the domain never allowed expansion.
    refused = await service.recall(scope_ref=[str(token.scope_id)], memory_ids=[output], include_linked=True)
    assert refused['enhancement']['link_expansion_status'] == 'disabled'
    assert [row['memory_id'] for row in refused['memories']] == [output]

    # Gate 3: domain allows but no proof is installed.
    profile = await db_session.get(DomainProfile, (await db_session.get(KnowledgeScope, token.scope_id)).domain_key)
    policy = dict(profile.memory_policy)
    policy['link_expansion_enabled'] = True
    profile.memory_policy = policy
    await db_session.commit()
    monkeypatch.delenv('CONSOLIDATION_GATE_REGISTRY_PATH', raising=False)
    unproven = await service.recall(scope_ref=[str(token.scope_id)], memory_ids=[output], include_linked=True)
    assert unproven['enhancement']['link_expansion_status'] == 'not_available'
    assert 'GATE_NOT_CONFIGURED' in unproven['enhancement']['degradation_reasons']
    assert [row['memory_id'] for row in unproven['memories']] == [output]

    # All three gates: current binding + fixed report bytes + candidate_expansion.
    from rag_mcp.services.consolidation_gate import gather_current_binding
    bound = await gather_current_binding(db_session, token.scope_id)
    registry = install_registry(tmp_path, bound, build_report(bound))
    monkeypatch.setenv('CONSOLIDATION_GATE_REGISTRY_PATH', str(registry))
    applied = await service.recall(scope_ref=[str(token.scope_id)], memory_ids=[output], include_linked=True)
    assert applied['enhancement']['link_expansion_status'] == 'applied'
    assert applied['enhancement']['linked_count'] == 1
    assert [row['memory_id'] for row in applied['memories']] == [output, reference]
    # A stale binding (policy change) immediately revokes authorization.
    policy['decay_rate'] = .07
    profile.memory_policy = policy
    await db_session.commit()
    stale = await service.recall(scope_ref=[str(token.scope_id)], memory_ids=[output], include_linked=True)
    assert stale['enhancement']['link_expansion_status'] == 'not_available'
    assert 'GATE_BINDING_STALE' in stale['enhancement']['degradation_reasons']
    assert [row['memory_id'] for row in stale['memories']] == [output]


@pytest.mark.asyncio
async def test_expansion_filters_nodes_whose_necessary_support_is_no_longer_live(monkeypatch):
    """T061 tail: withdrawn necessary support must not be resurrected by expansion.

    Only the proposed expansion nodes are revalidated, through their captured
    ``must_remain_active`` descriptors; unreadable support fails closed for the
    enhancement while leaving direct results untouched.
    """
    from rag_mcp.services import consolidation_commit
    from rag_mcp.services.memory_reader import MemoryReader

    support = {'support_kind': 'evidence', 'support_id': 9, 'version': '5',
               'content_hash': 'a' * 64, 'revocation_semantics': 'must_remain_active'}
    node = {'memory_id': 2, 'knowledge_scope_id': 1, 'required_support': [support]}
    reader = MemoryReader(session=None, projections=None)
    calls = []

    async def facts(session, identifiers, locked=False):
        calls.append(sorted(identifiers))
        return {'9': {'status': 'published', 'source_status': 'published', 'version_id': 5,
                      'content_hash': 'a' * 64}}

    monkeypatch.setattr(consolidation_commit, 'read_evidence', facts)
    assert await reader._live_support_nodes([2], {2: node}) == ([2], False)
    assert calls == [['9']], 'only the captured support ids are read'

    for replacement in (
        {'status': 'withdrawn', 'source_status': 'published', 'version_id': 5, 'content_hash': 'a' * 64},
        {'status': 'published', 'source_status': 'failed', 'version_id': 5, 'content_hash': 'a' * 64},
        {'status': 'published', 'source_status': 'published', 'version_id': 6, 'content_hash': 'a' * 64},
        {'status': 'published', 'source_status': 'published', 'version_id': 5, 'content_hash': 'b' * 64},
        None,
    ):
        async def stale(session, identifiers, locked=False, replacement=replacement):
            return {} if replacement is None else {'9': replacement}

        monkeypatch.setattr(consolidation_commit, 'read_evidence', stale)
        assert await reader._live_support_nodes([2], {2: node}) == ([], True)

    async def unreadable(session, identifiers, locked=False):
        raise RuntimeError('reader role cannot read evidence')

    monkeypatch.setattr(consolidation_commit, 'read_evidence', unreadable)
    assert await reader._live_support_nodes([2], {2: node}) == ([], True)
    # A node without necessary support never triggers an evidence read at all.
    assert await reader._live_support_nodes([3], {3: {'memory_id': 3, 'knowledge_scope_id': 1}}) == ([3], False)
