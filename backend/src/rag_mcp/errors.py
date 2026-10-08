"""Public error codes, preserving the historical retrieval contracts."""

LEGACY_ERROR_CODES = frozenset({
    "SYSTEM_ERROR", "MISSING_PROJECT_SCOPE", "AMBIGUOUS_PROJECT_REF",
    "INVALID_PROJECT_REF", "INDEX_UNAVAILABLE", "MISSING_KNOWLEDGE_SCOPE",
    "AMBIGUOUS_DOMAIN_REF", "INVALID_INPUT", "INVALID_EVIDENCE_ID",
})

MEMORY_ERROR_CODES = frozenset({
    "MISSING_KNOWLEDGE_SCOPE", "AMBIGUOUS_DOMAIN_REF",
    "MEMORY_EVIDENCE_ANCHOR_REQUIRED", "MEMORY_EVIDENCE_SCOPE_MISMATCH",
    "MEMORY_INFERENCE_META_INCOMPLETE", "MEMORY_PROVENANCE_INVALID",
    "MEMORY_KIND_INVALID", "MEMORY_SUPERSEDE_TARGET_INVALID",
    "MEMORY_QUOTA_EXCEEDED", "MEMORY_WRITE_UNAVAILABLE",
    "MEMORY_IDS_QUERY_CONFLICT", "MEMORY_ROLLBACK_FORBIDDEN",
    "MEMORY_TIMEOUT", "MEMORY_CONTENT_CONFLICT", "SYSTEM_ERROR",
})

ERROR_CODES = LEGACY_ERROR_CODES | MEMORY_ERROR_CODES


# --- 014: attachment-layer degradation reasons --------------------------------
# Additive vocabulary only. These are NOT error codes: they ride in
# ``memory_notice.failed_paths`` / ``counts`` and never replace or rename an
# entry of ERROR_CODES. The existing code sets above MUST stay unchanged, which
# tests/unit/test_014_attachment_gating.py freezes explicitly.
ATTACHMENT_DEGRADATION_REASONS = frozenset({
    "attachment_timeout",
    "memory_unavailable",
    "below_min_score",
    "budget_exhausted",
    "state_filtered",
    "detection_degraded",
})


def attachment_degradation_reason(exception: BaseException) -> str:
    """Map an attachment-layer failure to its stable degradation reason.

    The attachment layer degrades independently: whatever happens here is
    reported as a reason on the memory side and never changes the primary
    retrieval status (FR-004/SC-003).
    """
    if isinstance(exception, TimeoutError):
        return "attachment_timeout"
    if isinstance(exception, OSError):
        return "memory_unavailable"
    return "memory_unavailable"


class MemoryContentConflictError(ValueError):
    """Raised only after a matching entry is found in the requested scope."""

    def __init__(self, memory_id: int):
        self.memory_id = memory_id
        super().__init__(f"MEMORY_CONTENT_CONFLICT:{memory_id}")
