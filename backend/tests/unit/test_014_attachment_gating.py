"""014 attachment-layer tests (T008 error registry, extended by T013/T022).

This file is the 014 home for the attachment layer: the error-code freeze
(T008), the signal/threshold/budget/degradation matrix (T013) and the notice
contract (T022).
"""

from __future__ import annotations

import pytest

from rag_mcp.errors import (
    ATTACHMENT_DEGRADATION_REASONS,
    ERROR_CODES,
    LEGACY_ERROR_CODES,
    MEMORY_ERROR_CODES,
    attachment_degradation_reason,
)

# Frozen registry as measured at the 014 baseline. 014 is add-only: a removal or
# a rename here is a client-visible break, so it must never be "fixed" by editing
# this literal.
FROZEN_LEGACY_ERROR_CODES = frozenset({
    "SYSTEM_ERROR", "MISSING_PROJECT_SCOPE", "AMBIGUOUS_PROJECT_REF",
    "INVALID_PROJECT_REF", "INDEX_UNAVAILABLE", "MISSING_KNOWLEDGE_SCOPE",
    "AMBIGUOUS_DOMAIN_REF", "INVALID_INPUT", "INVALID_EVIDENCE_ID",
})
FROZEN_MEMORY_ERROR_CODES = frozenset({
    "MISSING_KNOWLEDGE_SCOPE", "AMBIGUOUS_DOMAIN_REF",
    "MEMORY_EVIDENCE_ANCHOR_REQUIRED", "MEMORY_EVIDENCE_SCOPE_MISMATCH",
    "MEMORY_INFERENCE_META_INCOMPLETE", "MEMORY_PROVENANCE_INVALID",
    "MEMORY_KIND_INVALID", "MEMORY_SUPERSEDE_TARGET_INVALID",
    "MEMORY_QUOTA_EXCEEDED", "MEMORY_WRITE_UNAVAILABLE",
    "MEMORY_IDS_QUERY_CONFLICT", "MEMORY_ROLLBACK_FORBIDDEN",
    "MEMORY_TIMEOUT", "MEMORY_CONTENT_CONFLICT", "SYSTEM_ERROR",
})


def test_legacy_error_codes_unchanged():
    assert LEGACY_ERROR_CODES == FROZEN_LEGACY_ERROR_CODES


def test_memory_error_codes_unchanged():
    assert MEMORY_ERROR_CODES == FROZEN_MEMORY_ERROR_CODES


def test_combined_error_code_set_unchanged():
    assert ERROR_CODES == FROZEN_LEGACY_ERROR_CODES | FROZEN_MEMORY_ERROR_CODES
    # 014 adds no error code: degradation is reported as a reason, not a new code.
    assert ERROR_CODES == LEGACY_ERROR_CODES | MEMORY_ERROR_CODES


def test_degradation_reasons_are_a_separate_vocabulary():
    assert ATTACHMENT_DEGRADATION_REASONS, "the degradation vocabulary must not be empty"
    # A reason is never an error code and vice versa: the two vocabularies must
    # not be conflated in the response.
    assert not (ATTACHMENT_DEGRADATION_REASONS & ERROR_CODES)
    assert all(reason.islower() for reason in ATTACHMENT_DEGRADATION_REASONS)
    assert all(reason.replace("_", "").isalnum() for reason in ATTACHMENT_DEGRADATION_REASONS)


@pytest.mark.parametrize(
    "exception,reason",
    [
        (TimeoutError(), "attachment_timeout"),
        (ConnectionError("qdrant down"), "memory_unavailable"),
        (ValueError("MEMORY_PROVENANCE_INVALID: x"), "memory_unavailable"),
    ],
)
def test_degradation_reason_mapping_is_stable(exception, reason):
    assert attachment_degradation_reason(exception) == reason
    assert reason in ATTACHMENT_DEGRADATION_REASONS
