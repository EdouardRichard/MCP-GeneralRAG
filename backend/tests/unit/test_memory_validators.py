import pytest


@pytest.mark.parametrize("payload,code", [
    ({"scope_id": 1, "kind": "episodic", "content": "x", "provenance": "hard", "evidence_refs": []}, "MEMORY_EVIDENCE_ANCHOR_REQUIRED"),
    ({"scope_id": 1, "kind": "episodic", "content": "x", "provenance": "soft", "inference_meta": {}}, "MEMORY_INFERENCE_META_INCOMPLETE"),
    ({"scope_id": 1, "kind": "bad", "content": "x", "provenance": "hard", "evidence_refs": ["e"]}, "MEMORY_KIND_INVALID"),
])
def test_memory_validator_rejects_invalid_matrix(payload, code):
    from rag_mcp.services.memory_validators import validate_memory

    with pytest.raises(ValueError, match=code):
        validate_memory(payload)


def test_hard_memory_requires_published_same_scope_attribution():
    from rag_mcp.services.memory_validators import validate_memory

    with pytest.raises(ValueError, match="MEMORY_EVIDENCE_ANCHOR_REQUIRED"):
        validate_memory({"scope_id": 1, "kind": "episodic", "content": "x", "provenance": "hard", "evidence_refs": [{"scope_id": 2, "published": True}]})


@pytest.mark.parametrize("fields", [{"confidence": .8}, {"title": "T" * 513}, {"title": 42},
    {"agent_id": "A" * 256}, {"tags": "not-an-array"}, {"tags": [42]}, {"session_id": "not-a-uuid"},
    {"task_context": "not-an-object"}])
def test_all_write_boundaries_reject_invalid_submission_metadata(fields):
    from rag_mcp.services.memory_validators import validate_memory
    payload = {"scope_id": 1, "kind": "semantic", "content": "Scoped fact", "provenance": "hard", "evidence_refs": ["1"], **fields}
    with pytest.raises(ValueError, match="MEMORY_PROVENANCE_INVALID"):
        validate_memory(payload)

