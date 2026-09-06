"""Two-level chunk_type vocabulary (008, FR-020/FR-021/FR-022).

L1 is the universal closed set produced by the conversion layer / generic
slicers (section/heading/paragraph/list/table). L2 is a namespaced extension
only valid when the active scope's domain profile declares the namespace via
chunk_type_extensions. The 18 legacy values from 003 remain valid unchanged
(zero migration).

Application-layer validation (FR-019) replaces the former DB enum CHECK: the
DB now only enforces the wide-mode pattern; the registry + this vocabulary are
the semantic gate.
"""

from __future__ import annotations

import re

L1_CHUNK_TYPES: frozenset[str] = frozenset(
    {"section", "heading", "paragraph", "list", "table"}
)

# 003 legacy values — valid, zero migration (FR-021).
LEGACY_CHUNK_TYPES: frozenset[str] = frozenset(
    {
        "section", "symbol", "endpoint", "schema", "table", "column",
        "constraint", "index", "view", "procedure", "function", "method",
        "type", "interface", "class", "heading", "paragraph", "list",
    }
)

L2_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")


def is_l1(chunk_type: str) -> bool:
    return chunk_type in L1_CHUNK_TYPES


def is_legacy(chunk_type: str) -> bool:
    return chunk_type in LEGACY_CHUNK_TYPES


def is_l2_namespace(chunk_type: str) -> bool:
    """True when chunk_type has the L2 namespace form (e.g. legal:article)."""
    return bool(L2_NAMESPACE_RE.match(chunk_type))


def namespace_of(chunk_type: str) -> str:
    """Return the namespace prefix of an L2 chunk type (or '' when not L2)."""
    return chunk_type.partition(":")[0]


def is_valid_chunk_type(chunk_type: str, chunk_type_extensions=None) -> bool:
    """Judge a chunk_type against L1, legacy values, and domain L2 extensions.

    L2 values (e.g. legal:article) are valid only when the active scope's
    domain profile explicitly declares the namespace via
    chunk_type_extensions (a dict mapping namespace -> "*" or a list of values).
    This feature presets no domain extension values (Constitution XI).
    """
    if is_l1(chunk_type) or is_legacy(chunk_type):
        return True
    if not is_l2_namespace(chunk_type):
        return False
    if not chunk_type_extensions:
        return False
    namespace, _, value = chunk_type.partition(":")
    allowed = chunk_type_extensions.get(namespace) if isinstance(chunk_type_extensions, dict) else None
    if allowed is None:
        return False
    if allowed == "*" or allowed == ["*"] or allowed == ("*",):
        return True
    if isinstance(allowed, (list, tuple, set, frozenset)):
        return value in allowed
    return False


def validate_chunk_type(chunk_type: str, chunk_type_extensions=None) -> None:
    """Raise ValueError when chunk_type is not valid (application-layer gate, FR-019)."""
    if not is_valid_chunk_type(chunk_type, chunk_type_extensions):
        raise ValueError(
            f"invalid chunk_type {chunk_type!r}: not in L1 closed set, legacy "
            f"values, or a declared domain namespace extension"
        )
