"""Builtin domain profile seed definitions + slug generator (007, T009).

Constitution XI / ADR-3: domain differences are expressed declaratively through
DomainProfile declarations. This module is the single source of truth for the two
builtin profiles (se-project = 1.0 behaviour, generic = domain-neutral forward
declaration) and the scope-slug lexical generator (FR-012).
"""
from __future__ import annotations

import re

SE_PROJECT_FORMATS: tuple[str, ...] = (
    "markdown", "java", "openapi", "ddl", "go", "python", "word", "pdf",
)

SE_PROJECT_GRAPH_RELATIONS: dict[str, list[str]] = {
    "calls": ["out", "in"],
    "called_by": ["out", "in"],
    "fk_references": ["out", "in"],
    "fk_referenced_by": ["out", "in"],
}

SE_PLANNER_PROMPT: str = (
    "You are a query-planning agent for a code/knowledge retrieval system. "
    "Decompose the user's retrieval query into traceable sub-problems. "
    "For multi-hop questions produce one sub-problem per hop; for "
    "single-intent questions return exactly ONE sub-problem. "
    "Signal selection rules: use 'dense' and 'sparse' for precision questions "
    "about exact symbols or definitions, columns/types/constraints, versions or "
    "configuration; add 'graph' only when the question asks about relationships "
    "or traversal (who calls X, callers/callees, foreign-key references, "
    "multi-hop chains)."
)

GENERIC_FORMATS: tuple[str, ...] = (
    "markdown", "word", "pdf", "html", "txt",
)

NEUTRAL_PLANNER_PROMPT: str = (
    "You are a domain-neutral query-planning agent for a general knowledge "
    "retrieval system. Decompose the user's query into traceable sub-problems "
    "without assuming any specific domain vocabulary, file formats, or graph "
    "structure. Prefer dense and lexical signals; do not add a graph signal."
)

BUILTIN_DOMAIN_PROFILES: dict[str, dict] = {
    "se-project": {
        "name": "Software Engineering",
        "description": (
            "1.0 software-engineering domain: code/knowledge retrieval with "
            "call-graph and foreign-key relation vocabulary."
        ),
        "supported_formats": list(SE_PROJECT_FORMATS),
        "chunk_type_extensions": None,
        "graph_relations": SE_PROJECT_GRAPH_RELATIONS,
        "prompt_overrides": {"query_planner_system_prompt": SE_PLANNER_PROMPT},
        "default_capabilities": {
            "retrieval_modes": ["dense", "hybrid", "graph_enhanced", "agentic"],
            "has_graph": True,
        },
        "is_builtin": True,
    },
    "generic": {
        "name": "General Knowledge",
        "description": (
            "Domain-neutral general-document domain: no graph relation "
            "vocabulary, no domain-specific prompt assumptions."
        ),
        "supported_formats": list(GENERIC_FORMATS),
        "chunk_type_extensions": None,
        "graph_relations": {},
        "prompt_overrides": {"query_planner_system_prompt": NEUTRAL_PLANNER_PROMPT},
        "default_capabilities": {
            "retrieval_modes": ["dense", "hybrid"],
            "has_graph": False,
        },
        "is_builtin": True,
    },
}

BUILTIN_DOMAIN_KEYS: frozenset[str] = frozenset(BUILTIN_DOMAIN_PROFILES.keys())

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Slugify a display name into a scope-slug token (lexical FR-012)."""
    if not name:
        return ""
    s = name.lower().strip()
    s = _SLUG_RE.sub("-", s)
    s = s.strip("-")
    if len(s) > 255:
        s = s[:255].rstrip("-")
    return s


def generate_unique_slug(name: str, scope_id: int, existing: set[str]) -> str:
    """Generate a globally-unique slug for a scope (fallback + numeric suffix)."""
    base = slugify(name) or ("scope-" + str(scope_id))
    if base not in existing:
        return base
    i = 2
    while (base + "-" + str(i)) in existing:
        i += 1
    return base + "-" + str(i)


def is_builtin(domain_key: str) -> bool:
    """True when domain_key names a builtin (read-only) profile."""
    return domain_key in BUILTIN_DOMAIN_KEYS
