"""Unit test for builtin domain profile seed content (007, T003).

FR-004: se-project declares the 8 native 1.0 formats + the 4 graph relation
vocabulary; generic declares an empty graph vocabulary + a domain-neutral prompt.
"""
from __future__ import annotations

from rag_mcp.config.domain_profiles import (
    BUILTIN_DOMAIN_PROFILES,
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


def test_legal_has_markdown_format():
    formats = BUILTIN_DOMAIN_PROFILES["legal"]["supported_formats"]
    assert formats == ["markdown"]


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


def test_slugify_lexical():
    assert slugify("Hello World") == "hello-world"
    assert slugify("  Foo__Bar  ") == "foo-bar"
    assert slugify("法规库") == ""
    assert slugify("") == ""
