"""Dependency-free packing helpers shared by the memory read/write paths.

This module is intentionally **stdlib-only**: it must be importable from pure
functions, contracts and tests without pulling in SQLAlchemy, Qdrant, Pydantic or
any provider. It exists so that:

* ``rag_mcp.services.memory_reader`` keeps exposing ``timestamp`` / ``canonical``
  / ``text_characters`` / ``serialized_characters`` (existing imports such as
  ``from rag_mcp.services.memory_reader import serialized_characters`` and
  ``from rag_mcp.services.memory_reader import timestamp`` must keep working), and
* ``rag_mcp.orchestration.working_set`` can use the very same character accounting
  without importing the reader (and therefore without touching Qdrant or the DB).

Behaviour is byte-for-byte the pre-existing implementation (014 T006 is a pure
extraction, not a redefinition).
"""

from __future__ import annotations

import json
from datetime import datetime

__all__ = ["timestamp", "canonical", "text_characters", "serialized_characters"]


def timestamp(value):
    """Parse an ISO-8601 value; naive timestamps are rejected."""
    if value is None:
        return None
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("MEMORY_PROVENANCE_INVALID: timezone required")
    return result


def canonical(value):
    """Deterministic JSON text: unicode preserved, keys sorted, no spaces."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def text_characters(value):
    """Count the characters of every string leaf in a nested structure."""
    if isinstance(value, dict):
        return sum(text_characters(item) for item in value.values())
    if isinstance(value, list):
        return sum(text_characters(item) for item in value)
    return len(value) if isinstance(value, str) else 0


def serialized_characters(value):
    """Count the exact deterministic JSON body, including its envelope fields."""
    candidate = dict(value)
    counts = dict(candidate.get("counts") or {})
    candidate["counts"] = {**counts, "characters": 0}
    for _ in range(4):
        length = len(canonical(candidate))
        if candidate["counts"]["characters"] == length:
            break
        candidate["counts"]["characters"] = length
    return candidate["counts"]["characters"]
