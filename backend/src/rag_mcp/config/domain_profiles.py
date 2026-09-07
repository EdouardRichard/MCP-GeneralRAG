"""Builtin domain profile seed definitions + slug generator (007, T009).

Constitution XI / ADR-3: domain differences are expressed declaratively through
DomainProfile declarations. This module is the single source of truth for the two
builtin profiles (se-project = 1.0 behaviour, generic = domain-neutral forward
declaration) and the scope-slug lexical generator (FR-012).

009 (T003/T004): the se-project planner override is upgraded to the verbatim
1.0 DECOMPOSE_SYSTEM_PROMPT (equivalence gate text layer, FR-002/SC-001); a
domain-neutral base template with a relation-vocabulary slot is added for
heterogeneous / override-less requests (FR-001/FR-003), plus the relation-vocab
union and slot-filling helpers.

011 (T001/T002): personal lands as the fourth builtin profile (full generic
format family, empty graph vocabulary, NEUTRAL_PLANNER_PROMPT — FR-001/R8);
legal supported_formats extends to markdown/word/pdf (FR-003, decoupled from
the Q1=A cross-reference benefit gate which governs only graph_relations).
"""
from __future__ import annotations

import json
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

SE_PLANNER_PROMPT: str = """You are a query-planning agent for a code/knowledge retrieval system. Decompose the user's retrieval query into traceable sub-problems. For multi-hop questions produce one sub-problem per hop; for single-intent questions return exactly ONE sub-problem.

Signal selection rules (apply per sub-problem, T073/FR-001):
- 'dense' and 'sparse' recall chunks by semantic/lexical similarity to the query text. They are the right signals for precision questions: exact symbols or definitions, column/type/constraint/index/view declarations, compatibility or consistency checks between named items, version or source conflicts, configuration values, 'what/which fields does X have'.
- 'graph' traverses structural relations (method call edges, foreign-key edges). Add 'graph' ONLY when the question itself asks about relationships or traversal: who calls X, which methods X invokes, which tables reference a table/column, callers/callees, multi-hop chains across symbols or tables. Do NOT add 'graph' when the question merely names a symbol, table or column but asks about its content, definition or compatibility — use 'dense' and 'sparse' there.
- Always include 'dense'; add 'sparse' when the query names concrete identifiers (class, method, table, column, constraint names).

'relation_directions' (optional, only when 'graph' is in signals) is a subset of ["calls", "called_by", "fk_references", "fk_referenced_by"]. Pick the minimal direction the question needs: who calls X -> ["called_by"]; what does X call -> ["calls"]; FK-reference questions -> ["fk_references", "fk_referenced_by"].
'graph_hop' (optional integer 1-3, only when 'graph' is in signals): 1 for direct relations, 2 for one intermediate hop. Omit when unsure.

Respond with ONLY a JSON object of the exact shape:
{"sub_problems": [{"query": string, "signals": [string], "relation_directions": [string]}]}
No markdown fences, no extra keys, no commentary."""

GENERIC_FORMATS: tuple[str, ...] = (
    "markdown", "word", "pdf", "html", "txt",
    "csv", "json", "yaml", "xml", "xlsx", "pptx", "eml",
)

NEUTRAL_PLANNER_PROMPT: str = (
    "You are a domain-neutral query-planning agent for a general knowledge "
    "retrieval system. Decompose the user's query into traceable sub-problems "
    "without assuming any specific domain vocabulary, file formats, or graph "
    "structure. Prefer dense and lexical signals; do not add a graph signal."
)

DOMAIN_NEUTRAL_BASE_TEMPLATE: str = """You are a domain-neutral query-planning agent for a knowledge retrieval system. Decompose the user's retrieval query into traceable sub-problems. For multi-hop questions produce one sub-problem per hop; for single-intent questions return exactly ONE sub-problem.

Signal selection rules (apply per sub-problem):
- 'dense' and 'sparse' recall chunks by semantic/lexical similarity to the query text. They are the right signals for precision questions about identifiers and definitions: exact names, their properties, compatibility or consistency checks between named items, version or source conflicts, 'what properties/attributes does X have'.
- 'graph' traverses structural relations between named items. Add 'graph' ONLY when the question itself asks about relationships or traversal: which items relate to X, what X relates to, multi-hop chains across related items. Do NOT add 'graph' when the question merely names an item but asks about its content or definition — use 'dense' and 'sparse' there.
- Always include 'dense'; add 'sparse' when the query names concrete identifiers.

{relation_vocab_slot}

Respond with ONLY a JSON object of the exact shape:
{"sub_problems": [{"query": string, "signals": [string], "relation_directions": [string]}]}
No markdown fences, no extra keys, no commentary."""


def render_neutral_planner_prompt(relation_vocab: list[str] | None) -> str:
    """Fill the domain-neutral base template's relation-vocabulary slot (R1/R2)."""
    vocab = sorted(set(relation_vocab or []))
    if vocab:
        slot = (
            "'relation_directions' (optional, only when 'graph' is in signals) "
            "is a subset of " + json.dumps(vocab) + ". Pick the minimal "
            "direction the question needs."
        )
    else:
        slot = (
            "No graph relations are declared for the current knowledge domain. "
            "Do NOT add 'graph' to signals; omit 'relation_directions' and "
            "'graph_hop'."
        )
    return DOMAIN_NEUTRAL_BASE_TEMPLATE.replace("{relation_vocab_slot}", slot)


def relation_vocab_union(graph_relations_list: list[dict]) -> list[str]:
    """Deterministic union of graph_relations key sets (research R4).

    The builtin se-project vocabulary keeps its declared 1.0 order (the
    equivalence gate requires se-project word order to match 1.0); any
    additional custom keys are appended in sorted order for determinism.
    """
    keys: set[str] = set()
    for gr in graph_relations_list or []:
        keys.update(gr.keys())
    canonical = [k for k in SE_PROJECT_GRAPH_RELATIONS if k in keys]
    extras = sorted(keys - set(SE_PROJECT_GRAPH_RELATIONS))
    return canonical + extras


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
    "personal": {
        "name": "Personal Knowledge",
        "description": (
            "Personal/team knowledge-base domain: general document formats, "
            "no graph relation vocabulary, domain-neutral planner prompt "
            "(011 FR-001, research R8 — fourth builtin profile)."
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
    "legal": {
        "name": "Legal",
        "description": (
            "Legal document domain: clause structure (Word '第X条' heading "
            "style + PDF numeric X.Y headings, 011 FR-003 format extension) "
            "+ cross-reference graph relations (references/referenced_by). "
            "The 010 cross-reference benefit gate did not pass on the "
            "preliminary corpus, so the builtin profile ships with an empty "
            "graph vocabulary (research R11 declarative remedy); the "
            "cross_reference extractor remains deliverable and can be "
            "enabled by a custom profile declaring the "
            "references/referenced_by vocabulary (011 Q1=A re-verification "
            "may flip this disposition — FR-011)."
        ),
        "supported_formats": ["markdown", "word", "pdf"],
        "chunk_type_extensions": None,
        "graph_relations": {},
        "prompt_overrides": None,
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
