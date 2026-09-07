"""Unit test for builtin domain profile seed content (007, T003; 011 T003).

FR-004: se-project declares the 8 native 1.0 formats + the 4 graph relation
vocabulary; generic declares an empty graph vocabulary + a domain-neutral prompt.

011 FR-001/FR-003 (VS-01): personal lands as the fourth builtin profile (full
generic format family, empty graph vocabulary, NEUTRAL_PLANNER_PROMPT,
dense/hybrid only); legal supported_formats extends to markdown/word/pdf
(decoupled from the Q1=A benefit gate); se-project/generic seeds stay
field-for-field unchanged (007 equivalence no-regression).
"""
from __future__ import annotations

from rag_mcp.config.domain_profiles import (
    BUILTIN_DOMAIN_PROFILES,
    GENERIC_FORMATS,
    NEUTRAL_PLANNER_PROMPT,
    is_builtin,
    slugify,
)


def test_se_project_has_8_native_formats():
    formats = BUILTIN_DOMAIN_PROFILES["se-project"]["supported_formats"]
    assert sorted(formats) == sorted([
        "markdown", "java", "openapi", "ddl", "go", "python", "word", "pdf",
    ])


def test_se_project_has_4_graph_relations():
    graph = BUILTIN_DOMAIN_PROFILES["se-project"]["graph_relations"]
    assert set(graph.keys()) == {"calls", "called_by", "fk_references", "fk_referenced_by"}
    for directions in graph.values():
        assert "out" in directions and "in" in directions


def test_generic_has_empty_graph_relations():
    assert BUILTIN_DOMAIN_PROFILES["generic"]["graph_relations"] == {}


def test_generic_prompt_is_domain_neutral():
    prompt = BUILTIN_DOMAIN_PROFILES["generic"]["prompt_overrides"]["query_planner_system_prompt"]
    assert "domain-neutral" in prompt


def test_se_project_prompt_is_se_specific():
    prompt = BUILTIN_DOMAIN_PROFILES["se-project"]["prompt_overrides"]["query_planner_system_prompt"]
    assert "code/knowledge" in prompt


def test_is_builtin():
    assert is_builtin("se-project")
    assert is_builtin("generic")
    assert is_builtin("legal")
    assert not is_builtin("custom")


def test_legal_formats_extended_word_pdf():
    """011 FR-003: legal supported_formats extends to markdown/word/pdf to
    carry the Word contract ("第X条" heading style) and PDF regulation
    (numeric X.Y heading) corpora. The format extension is decoupled from
    the Q1=A cross-reference benefit gate and always lands."""
    formats = BUILTIN_DOMAIN_PROFILES["legal"]["supported_formats"]
    assert formats == ["markdown", "word", "pdf"]


def test_legal_chunk_type_extensions_stays_none():
    """011 R13: the legal:article clause chunk_type is NOT landed; clause
    structure is carried by generic heading/section chunks (Word heading
    paths / PDF page:N §numeric-numbered locators)."""
    assert BUILTIN_DOMAIN_PROFILES["legal"]["chunk_type_extensions"] is None


def test_legal_has_empty_vocab_r11_remedy():
    """The 010 preliminary cross-reference benefit gate did not pass (SC-002),
    so the builtin legal profile ships with an empty vocabulary (R11 declarative
    remedy); cross_reference remains deliverable via a custom profile."""
    assert BUILTIN_DOMAIN_PROFILES["legal"]["graph_relations"] == {}


def test_legal_is_builtin_without_graph_capability():
    """R11 declarative remedy: empty vocabulary means NO graph capability
    declaration (has_graph False, no graph_enhanced mode, generic-style
    dense/hybrid modes) — the graph path does not enter the legal default
    retrieval (FR-030/SC-002, 010 T060)."""
    legal = BUILTIN_DOMAIN_PROFILES["legal"]
    assert legal["is_builtin"] is True
    assert legal["default_capabilities"]["has_graph"] is False
    assert "graph_enhanced" not in legal["default_capabilities"]["retrieval_modes"]
    assert legal["default_capabilities"]["retrieval_modes"] == ["dense", "hybrid"]


def test_personal_is_builtin_fourth_builtin():
    """011 FR-001/R8: personal lands as the fourth builtin profile
    (declarative config, read-only protected, domain-neutral)."""
    assert is_builtin("personal")
    personal = BUILTIN_DOMAIN_PROFILES["personal"]
    assert personal["is_builtin"] is True


def test_personal_has_generic_format_family():
    """011 FR-001: personal declares the full generic format family — the
    profile capability face is self-consistent ("a personal knowledge base
    may hold any generic document"); the eval corpora only use 4 of them."""
    personal = BUILTIN_DOMAIN_PROFILES["personal"]
    assert personal["supported_formats"] == list(GENERIC_FORMATS)


def test_personal_has_empty_graph_vocabulary():
    """011 FR-001: personal has no graph relation vocabulary and no graph
    capability (dense/hybrid retrieval only, has_graph False)."""
    personal = BUILTIN_DOMAIN_PROFILES["personal"]
    assert personal["graph_relations"] == {}
    assert personal["default_capabilities"] == {
        "retrieval_modes": ["dense", "hybrid"],
        "has_graph": False,
    }
    assert personal["chunk_type_extensions"] is None


def test_personal_prompt_is_domain_neutral():
    """011 FR-001: personal uses the same NEUTRAL_PLANNER_PROMPT as generic
    (domain-neutral planner, no graph signal guidance)."""
    personal = BUILTIN_DOMAIN_PROFILES["personal"]
    assert personal["prompt_overrides"] == {
        "query_planner_system_prompt": NEUTRAL_PLANNER_PROMPT
    }


def test_se_project_seed_field_frozen():
    """011 VS-01: the se-project builtin seed is field-for-field unchanged
    by the 011 personal/legal seed changes (007 equivalence no-regression)."""
    se = BUILTIN_DOMAIN_PROFILES["se-project"]
    assert se["name"] == "Software Engineering"
    assert se["supported_formats"] == [
        "markdown", "java", "openapi", "ddl", "go", "python", "word", "pdf",
    ]
    assert se["chunk_type_extensions"] is None
    assert se["graph_relations"] == {
        "calls": ["out", "in"],
        "called_by": ["out", "in"],
        "fk_references": ["out", "in"],
        "fk_referenced_by": ["out", "in"],
    }
    assert se["prompt_overrides"] is not None
    assert "query_planner_system_prompt" in se["prompt_overrides"]
    assert se["default_capabilities"] == {
        "retrieval_modes": ["dense", "hybrid", "graph_enhanced", "agentic"],
        "has_graph": True,
    }
    assert se["is_builtin"] is True


def test_generic_seed_field_frozen():
    """011 VS-01: the generic builtin seed is field-for-field unchanged by
    the 011 personal/legal seed changes (007 equivalence no-regression)."""
    gen = BUILTIN_DOMAIN_PROFILES["generic"]
    assert gen["name"] == "General Knowledge"
    assert gen["supported_formats"] == list(GENERIC_FORMATS)
    assert gen["chunk_type_extensions"] is None
    assert gen["graph_relations"] == {}
    assert gen["prompt_overrides"] == {
        "query_planner_system_prompt": NEUTRAL_PLANNER_PROMPT
    }
    assert gen["default_capabilities"] == {
        "retrieval_modes": ["dense", "hybrid"],
        "has_graph": False,
    }
    assert gen["is_builtin"] is True


def test_slugify_lexical():
    assert slugify("Hello World") == "hello-world"
    assert slugify("  Foo__Bar  ") == "foo-bar"
    assert slugify("法规库") == ""
    assert slugify("") == ""
