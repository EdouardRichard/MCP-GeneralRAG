from rag_mcp.services.memory_reducer import reduce_events


def test_aoep_invariants_authority_scope_deletion_provenance_rollback():
    state = reduce_events([{ "event_id": 1, "event_type": "assert", "aggregate_id": 1, "knowledge_scope_id": 1, "payload": {"provenance": "hard", "evidence_refs": ["e"]}}, {"event_id": 2, "event_type": "retract", "aggregate_id": 1, "knowledge_scope_id": 1, "payload": {}}])
    entry = state["entries"][1]
    assert entry["status"] == "retired"
    assert entry["knowledge_scope_id"] == 1
    assert entry["evidence_refs"] == ["e"]

