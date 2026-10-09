"""014 T012: the attachment item contract and its separation from evidence.

Covers FR-003/FR-010/FR-012 and Constitution IV:

* positive and negative examples for ``related_memories`` entries,
* **bidirectional** non-mixing with ``evidence[]`` (each schema rejects the other),
* the locating-semantics boundary — an attachment must be rejected when it carries
  ``source_position`` / ``source_version`` / ``relevance_score``,
* provenance completeness: ``soft``/``distilled`` need the five-element
  ``inference_meta``, ``hard`` needs ``confidence: null``, and
  ``valid_to``/``superseded_by`` are pinned to ``null``,
* no drift from the 012 ``memory-entry`` vocabulary nor from the runtime
  ``public_entry`` shape.
"""

from __future__ import annotations

import pytest

from rag_mcp.services.memory_reader import public_entry
from tests.contract import schema_registry_014 as reg

ATTACHMENT = "memory-attachment.schema.json"


def _assert_rejected(instance: dict, *, reason: str):
    errors = list(reg.validator(ATTACHMENT).iter_errors(instance))
    assert errors, f"expected the attachment schema to reject {reason}"
    return errors


@pytest.mark.parametrize("provenance", ["hard", "soft", "distilled"])
def test_valid_attachment_examples(provenance):
    assert reg.is_valid(ATTACHMENT, reg.sample_attachment(provenance=provenance))


def test_missing_required_key_is_rejected():
    for key in ("memory_id", "knowledge_scope_id", "kind", "provenance", "confidence",
                "content_excerpt", "truncated", "content_length", "evidence_refs",
                "inference_meta", "valid_from", "valid_to", "observed_at", "session_id",
                "agent_id", "status", "superseded_by", "injection_flags", "attach_reason", "match"):
        instance = reg.sample_attachment()
        instance.pop(key)
        _assert_rejected(instance, reason=f"a missing {key}")


def test_missing_provenance_makes_the_whole_item_invalid():
    instance = reg.sample_attachment()
    instance.pop("provenance")
    _assert_rejected(instance, reason="a missing provenance")


def test_excerpt_longer_than_200_is_rejected():
    _assert_rejected(reg.sample_attachment(content_excerpt="x" * 201), reason="a 201-char excerpt")
    assert reg.is_valid(ATTACHMENT, reg.sample_attachment(content_excerpt="x" * 200))


def test_non_active_status_is_rejected():
    for status in ("quarantined", "superseded", "retired", "archived"):
        _assert_rejected(reg.sample_attachment(status=status), reason=f"status={status}")


def test_attachment_must_not_carry_evidence_locating_fields():
    for field, value in (("source_position", "doc.md#L1"), ("source_version", 1), ("relevance_score", 0.9)):
        _assert_rejected(reg.sample_attachment(**{field: value}),
                         reason=f"the evidence locating field {field}")


def test_memory_id_must_be_a_positive_integer():
    _assert_rejected(reg.sample_attachment(memory_id=0), reason="memory_id=0")
    _assert_rejected(reg.sample_attachment(memory_id="1"), reason="a string memory_id")


@pytest.mark.parametrize("provenance", ["soft", "distilled"])
def test_soft_and_distilled_require_the_five_element_inference_meta(provenance):
    _assert_rejected(reg.sample_attachment(provenance=provenance, inference_meta=None),
                     reason=f"{provenance} with a null inference_meta")
    for key in ("source", "confidence", "model_version", "time", "supporting_evidence"):
        meta = {"source": "s", "confidence": 0.5, "model_version": "none",
                "time": "2026-10-09T00:00:00+00:00", "supporting_evidence": []}
        meta.pop(key)
        _assert_rejected(reg.sample_attachment(provenance=provenance, inference_meta=meta),
                         reason=f"{provenance} whose inference_meta lacks {key}")


def test_hard_confidence_must_be_null():
    _assert_rejected(reg.sample_attachment(provenance="hard", confidence=0.8),
                     reason="a hard item with a non-null confidence")
    assert reg.is_valid(ATTACHMENT, reg.sample_attachment(provenance="hard", confidence=None))


def test_valid_to_and_superseded_by_are_pinned_to_null():
    _assert_rejected(reg.sample_attachment(valid_to="2026-10-09T00:00:00+00:00"),
                     reason="a non-null valid_to")
    _assert_rejected(reg.sample_attachment(superseded_by=2), reason="a non-null superseded_by")


def test_attach_reason_is_a_closed_readable_enum():
    for reason in ("session_recent", "context_match", "session_and_context"):
        assert reg.is_valid(ATTACHMENT, reg.sample_attachment(attach_reason=reason))
    _assert_rejected(reg.sample_attachment(attach_reason="because"), reason="an unknown attach_reason")


def test_bidirectional_non_mixing_between_evidence_and_attachments():
    reg.assert_bidirectional_non_mixing()


def test_evidence_schema_still_rejects_attachment_only_fields():
    validator = reg.validator("mcp-search-output.schema.json", pointer=reg.EVIDENCE_ITEM_POINTER)
    errors = list(validator.iter_errors(reg.sample_attachment()))
    codes = {error.validator for error in errors}
    assert "required" in codes or "additionalProperties" in codes


def test_attachment_vocabulary_does_not_drift_from_012_memory_entry():
    reg.assert_attachment_vocabulary_matches_012()


def test_attachment_property_set_matches_the_runtime_public_entry_shape():
    """The vocabulary is anchored to the *runtime* entry shape, not only the 012 doc."""
    row = {
        "memory_id": 1, "knowledge_scope_id": 1, "kind": "episodic", "provenance": "soft",
        "title": "t", "confidence": 0.8, "evidence_refs": [], "retention_stage": "active",
        "valid_from": None, "valid_to": None, "observed_at": "2026-10-09T00:00:00+00:00",
        "session_id": None, "agent_id": None, "status": "active", "superseded_by": None,
        "inference_meta": {"source": "s", "confidence": 0.8, "model_version": "none",
                           "time": "2026-10-09T00:00:00+00:00", "supporting_evidence": []},
        "content_text": "hello world",
    }
    runtime_keys = set(public_entry(row))
    declared = set(reg.load(ATTACHMENT)["properties"])
    # The attachment adds the two 014-only presentation keys and drops the
    # memory-internal retention_stage; nothing else may differ.
    assert declared - {"injection_flags", "attach_reason"} == runtime_keys - {"retention_stage"}
    assert "retention_stage" not in declared, "retention_stage must not leak to the host"


def test_no_shared_field_is_typed_as_the_other_layer():
    """A memory field must never adopt an evidence type and vice versa."""
    declared = reg.load(ATTACHMENT)["properties"]
    assert declared["knowledge_scope_id"]["type"] == "integer"
    evidence = reg.load("mcp-search-output.schema.json")["properties"]["evidence"]["items"]["properties"]
    assert evidence["knowledge_scope_id"]["type"] == "string"
    assert "match" in declared and "match" not in evidence


# --- implementation-level assertions (land green only with T020) --------------


def _row(**overrides) -> dict:
    row = {
        "memory_id": 7,
        "knowledge_scope_id": 1,
        "kind": "episodic",
        "provenance": "soft",
        "confidence": 0.8,
        "title": "a title",
        "content_text": "remembered excerpt",
        "evidence_refs": [],
        "inference_meta": {"source": "s", "confidence": 0.8, "model_version": "none",
                           "time": "2026-10-09T00:00:00+00:00", "supporting_evidence": []},
        "valid_from": None, "valid_to": None, "observed_at": "2026-10-09T00:00:00+00:00",
        "session_id": None, "agent_id": None, "status": "active",
        "retention_stage": "active", "superseded_by": None,
        "write_status": "complete", "expires_at": None, "injection_flags": {},
    }
    row.update(overrides)
    return row


_MATCH = {"dense_similarity": 0.7, "recency_rank": 1, "kind_rank": 1, "salience": None, "fused_score": 0.01}


@pytest.mark.parametrize("provenance", ["hard", "soft", "distilled"])
def test_assembled_attachment_item_validates_against_the_contract(provenance):
    from rag_mcp.services.memory_service import attachment_item

    row = _row(
        provenance=provenance,
        confidence=None if provenance == "hard" else 0.8,
        evidence_refs=["ev-1"] if provenance == "hard" else [],
        inference_meta=None if provenance == "hard" else {
            "source": "s", "confidence": 0.8, "model_version": "none",
            "time": "2026-10-09T00:00:00+00:00", "supporting_evidence": [],
        },
    )
    item = attachment_item(row, match=_MATCH, attach_reason="context_match", excerpt_chars=200)
    errors = list(reg.validator(ATTACHMENT).iter_errors(item))
    assert not errors, [error.message for error in errors]
    # locating semantics stay separated
    for field in ("source_position", "source_version", "relevance_score"):
        assert field not in item


def test_assembled_item_pins_the_nullable_and_status_fields():
    from rag_mcp.services.memory_service import attachment_item

    item = attachment_item(_row(), match=None, attach_reason="session_recent", excerpt_chars=200)
    assert item["valid_to"] is None
    assert item["superseded_by"] is None
    assert item["status"] == "active"
    assert "confidence" in item, "the confidence key is always present"
    assert "inference_meta" in item
    assert "session_id" in item and "agent_id" in item
    assert item["injection_flags"] == {}
    assert list(item) == [
        "memory_id", "knowledge_scope_id", "kind", "provenance", "confidence", "title",
        "content_excerpt", "truncated", "content_length", "evidence_refs", "inference_meta",
        "valid_from", "valid_to", "observed_at", "session_id", "agent_id", "status",
        "superseded_by", "injection_flags", "attach_reason", "match",
    ], "attachment key order is frozen to the contract declaration order"


def test_excerpt_is_cropped_to_the_contract_limit_and_marks_truncation():
    from rag_mcp.services.memory_service import attachment_item

    item = attachment_item(_row(content_text="x" * 250), match=None,
                           attach_reason="context_match", excerpt_chars=200)
    assert len(item["content_excerpt"]) == 200
    assert item["truncated"] is True
    assert item["content_length"] == 250


def test_attachment_match_rejects_nested_evidence_locating_fields():
    """T088/FR-003: ``match`` is closed, so a nested locating field cannot validate."""
    from rag_mcp.services.memory_service import attachment_item

    validator = reg.validator(ATTACHMENT)
    item = attachment_item(_row(content_text="body"), match={"dense_similarity": 0.9},
                           attach_reason="context_match", excerpt_chars=200)
    assert not list(validator.iter_errors(item))
    item["match"]["relevance_score"] = 0.5
    assert list(validator.iter_errors(item)), "a nested relevance_score must be rejected"

