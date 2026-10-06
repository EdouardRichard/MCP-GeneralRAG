

def test_approved_context_does_not_change_embedding_body_or_identity():
    from rag_mcp.services.memory_validators import canonical_distilled
    from tests.unit.consolidation_cases import NOW, POLICY, decide, proposal
    p = proposal()
    decision = decide(p)
    value = canonical_distilled(decision.approved_effects[0]['value'], policy=POLICY, now=NOW)
    assert value['content_text'] == p['content']
    assert value['confidence'] == value['inference_meta']['confidence'] == .8
    assert value['inference_meta']['confidence_origin'] == 'llm_self'
    assert value['submission_meta']['inference_meta'] == value['inference_meta']
