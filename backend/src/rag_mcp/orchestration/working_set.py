"""Deterministic working-set assembler (014 T034/T037/T038).

Pure functions only: **no IO, no clock, no model, no network**. The same captured
rows and the same explicit ``snapshot_at`` always produce byte-identical output, so
``start_work`` can promise SC-009's "same input, same bytes" without depending on
when the request happened to run.

Three derived buckets plus an append-only decision trail:

* ``open_items``  — episodic memories that are still open (未决事项)
* ``recent_activity`` — episodic memories of the *resolved* session; empty (with
  visible counts, and without an error or a widened scope) when no session resolves
* ``procedural``  — applicable procedural experience (similarity and frequency are
  deliberately never consulted)

Data model: [data-model.md §7.4](../../../../specs/014-memory-aware-retrieval/data-model.md).
Ambiguity rulings A1–A7: [research.md §6](../../../../specs/014-memory-aware-retrieval/research.md).

A6 interpretation (recorded because the source phrasing is ambiguous): a row whose
``observed_at`` is missing, naive or unparsable **must not raise** and must not
contribute to the data-derived ``snapshot_at``; it participates and sorts last by
``memory_id``. A row whose ``valid_from`` cannot be compared against its
``observed_at`` is excluded, because the fifth predicate condition cannot be
verified and the safe direction is to omit the item.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = [
    "DEFAULT_BUCKET_LIMITS",
    "BUCKET_ORDER",
    "CROP_ORDER",
    "EXCERPT_CHARACTERS",
    "working_set_visible",
    "snapshot_of",
    "resolve_recent_session",
    "assemble_working_set",
]

#: Policy defaults (data-model §3). ``start_work`` passes the resolved domain
#: policy's values; these are the fallbacks for a policy that omits them.
DEFAULT_BUCKET_LIMITS = {"open_items": 3, "recent_activity": 3, "procedural": 2}

#: Bucket precedence for cross-bucket dedup (first occurrence wins).
BUCKET_ORDER = ("open_items", "recent_activity", "procedural")

#: Drop order under character pressure (procedural first; ``read_guidance`` and the
#: digest are never part of this function's budget).
CROP_ORDER = ("procedural", "recent_activity", "open_items")

EXCERPT_CHARACTERS = 300

_EPISODIC = "episodic"
_PROCEDURAL = "procedural"

_EPOCH = datetime(1, 1, 1, tzinfo=UTC)


def _aware(value):
    """Parse an ISO-8601 timestamp; ``None`` when missing, naive or unparsable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    try:
        from rag_mcp.orchestration.packing import timestamp

        return timestamp(value)
    except (ValueError, TypeError, AttributeError):
        return None


def working_set_visible(row, *, snapshot_at) -> bool:
    """The single shared visibility predicate (data-model §7.4).

    ``status == active`` AND ``retention_stage == active`` AND ``valid_to`` is
    null AND (no ``expires_at`` or it is still in the future **relative to
    ``snapshot_at``**) AND (no ``valid_from``/``observed_at`` or
    ``valid_from <= observed_at``).

    T089 mirrors the attachment-layer predicate: a write that never completed
    (``write_status``) and a ``hard`` row without any attribution anchor are
    excluded as well (FR-007/FR-003). The full live anchor re-verification is an
    IO concern owned by the attach path; this pure predicate enforces the
    verifiable part.
    """
    if not isinstance(row, dict):
        return False
    if row.get("status") != "active":
        return False
    if row.get("retention_stage") != "active":
        return False
    if row.get("valid_to") is not None:
        return False
    if row.get("write_status") not in (None, "complete"):
        return False
    if row.get("provenance") == "hard" and not row.get("evidence_refs"):
        return False

    expires = row.get("expires_at")
    if expires is not None:
        expiry = _aware(expires)
        if expiry is None or snapshot_at is None or expiry <= snapshot_at:
            return False

    valid_from = row.get("valid_from")
    observed = row.get("observed_at")
    if valid_from is not None and observed is not None:
        start, moment = _aware(valid_from), _aware(observed)
        if start is None or moment is None or start > moment:
            return False
    return True


def snapshot_of(rows) -> datetime | None:
    """The data-derived ``snapshot_at``: ``max(observed_at)`` over usable rows.

    Never the wall clock — that is what keeps the assembled bytes stable across
    time. Returns ``None`` when no usable ``observed_at`` exists.
    """
    observed = [_aware(row.get("observed_at")) for row in (rows.values() if isinstance(rows, dict) else rows)]
    usable = [moment for moment in observed if moment is not None]
    return max(usable) if usable else None


def _sort_key(row):
    """Bucket ordering: ``(observed_at, memory_id)`` descending, unusable last."""
    moment = _aware(row.get("observed_at")) or _EPOCH
    return (-moment.timestamp(), -int(row.get("memory_id") or 0))


def _rows(rows):
    return [row for row in (rows.values() if isinstance(rows, dict) else rows) if isinstance(row, dict)]


def resolve_recent_session(rows, *, explicit_session_id=None, snapshot_at=None):
    """Resolve the session the working set continues from.

    An explicit ``session_id`` always wins. Otherwise the session of the *visible*
    episodic row with the greatest ``observed_at`` is used, with the
    lexicographically largest ``session_id`` as the tie-break. No candidate means
    ``None``: the caller reports counts and an empty ``recent_activity`` instead of
    erroring or widening the scope (T038).
    """
    if explicit_session_id is not None:
        return explicit_session_id
    moment = snapshot_at if snapshot_at is not None else snapshot_of(rows)
    candidates = [
        row for row in _rows(rows)
        if row.get("kind") == _EPISODIC and row.get("session_id")
        and working_set_visible(row, snapshot_at=moment)
    ]
    if not candidates:
        return None
    best = max(
        candidates,
        key=lambda row: (
            (_aware(row.get("observed_at")) or _EPOCH).timestamp(),
            str(row.get("session_id")),
        ),
    )
    return str(best.get("session_id"))


def _item(row) -> dict:
    """The working-set item shape; it never repeats the scope (FR-021)."""
    content = row.get("content_text")
    if content is None:
        content = row.get("content_excerpt") or ""
    excerpt = content[:EXCERPT_CHARACTERS]
    length = len(content) if row.get("content_text") is not None else int(row.get("content_length") or len(content))
    return {
        "memory_id": int(row["memory_id"]),
        "kind": row.get("kind"),
        "provenance": row.get("provenance"),
        "confidence": row.get("confidence"),
        "evidence_refs": list(row.get("evidence_refs") or []),
        "inference_meta": row.get("inference_meta"),
        "content_excerpt": excerpt,
        "truncated": length > len(excerpt),
        "observed_at": row.get("observed_at"),
    }


def assemble_working_set(*, rows, explicit_session_id=None, snapshot_at=None,
                         remaining_characters: int = 0, limits=None) -> dict:
    """Assemble the three derived buckets plus the decision trail.

    Args:
        rows: the scope's captured entries (``memory_id`` -> row).
        explicit_session_id: the caller's session, if any.
        snapshot_at: the reference instant; ``None`` derives it from the data.
        remaining_characters: the budget left after the digest and read guidance.
        limits: per-bucket caps; defaults to :data:`DEFAULT_BUCKET_LIMITS`.

    Returns:
        ``{"open_items", "recent_activity", "procedural", "decisions",
        "truncated", "session_resolved"}``.
    """
    caps = {**DEFAULT_BUCKET_LIMITS, **(limits or {})}
    moment = snapshot_at if snapshot_at is not None else snapshot_of(rows)
    session = resolve_recent_session(rows, explicit_session_id=explicit_session_id, snapshot_at=moment)

    visible = [row for row in _rows(rows) if working_set_visible(row, snapshot_at=moment)]
    visible.sort(key=_sort_key)

    # Independent candidate lists: an in-session episodic memory is a candidate for
    # both open_items and recent_activity, and the bucket order below decides where
    # it actually lands (data-model §7.4).
    candidates: dict[str, list[dict]] = {name: [] for name in BUCKET_ORDER}
    for row in visible:
        if row.get("kind") == _EPISODIC:
            candidates["open_items"].append(row)
            if session is not None and row.get("session_id") == session:
                candidates["recent_activity"].append(row)
        elif row.get("kind") == _PROCEDURAL:
            candidates["procedural"].append(row)

    buckets: dict[str, list[dict]] = {name: [] for name in BUCKET_ORDER}
    decisions: list[dict] = []
    seen: set[int] = set()
    truncated = False

    for name in BUCKET_ORDER:
        for row in candidates[name]:
            memory_id = int(row["memory_id"])
            if memory_id in seen:
                decisions.append({"memory_id": memory_id, "decision": "deduped"})
                continue
            if len(buckets[name]) >= int(caps[name]):
                decisions.append({"memory_id": memory_id, "decision": "truncated"})
                truncated = True
                continue
            seen.add(memory_id)
            buckets[name].append(_item(row))
            decisions.append({"memory_id": memory_id, "decision": "selected"})

    # Character budget: drop from the tail of each bucket in CROP_ORDER.
    budget = max(0, int(remaining_characters or 0))
    while _characters(buckets) > budget:
        dropped = False
        for name in CROP_ORDER:
            if buckets[name]:
                removed = buckets[name].pop()
                decisions.append({"memory_id": removed["memory_id"], "decision": "truncated"})
                truncated = True
                dropped = True
                break
        if not dropped:
            break

    return {
        "open_items": buckets["open_items"],
        "recent_activity": buckets["recent_activity"],
        "procedural": buckets["procedural"],
        "decisions": decisions,
        "truncated": truncated,
        "session_resolved": session,
    }


def _characters(buckets) -> int:
    from rag_mcp.orchestration.packing import text_characters

    return sum(text_characters(item) for items in buckets.values() for item in items)
