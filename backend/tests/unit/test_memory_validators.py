import pytest


@pytest.mark.parametrize("payload,code", [
    ({"scope_id": 1, "kind": "episodic", "content": "x", "provenance": "hard", "evidence_refs": []}, "MEMORY_PROVENANCE_INVALID"),
    ({"scope_id": 1, "kind": "episodic", "content": "x", "provenance": "soft", "inference_meta": {}}, "MEMORY_INFERENCE_META_INCOMPLETE"),
    ({"scope_id": 1, "kind": "bad", "content": "x", "provenance": "hard", "evidence_refs": ["e"]}, "MEMORY_KIND_INVALID"),
])
def test_memory_validator_rejects_invalid_matrix(payload, code):
    from rag_mcp.services.memory_validators import validate_memory

    with pytest.raises(ValueError, match=code):
        validate_memory(payload)


def test_hard_memory_requires_published_same_scope_attribution():
    from rag_mcp.services.memory_validators import validate_memory

    with pytest.raises(ValueError, match="MEMORY_EVIDENCE_INVALID"):
        validate_memory({"scope_id": 1, "kind": "episodic", "content": "x", "provenance": "hard", "evidence_refs": [{"scope_id": 2, "published": True}]})

