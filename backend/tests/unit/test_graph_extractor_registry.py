"""Unit test for the graph extractor registry (010, T009, VS-01).

Validates the GraphExtractor plugin interface declarations, deterministic
format x domain-vocabulary discovery, registration validation (single-sided
pairs / illegal pattern / cross-extractor conflict), and the inverse relation
map aggregation (graph-extractor-registry.md §1/§3).

This test MUST FAIL before base.py is implemented (TDD).
"""
from __future__ import annotations

import pytest

from rag_mcp.graph.extractors.base import (
    GraphExtractor,
    GraphExtractorRegistry,
)
from rag_mcp.graph.store.base import GraphScope


# ---------------------------------------------------------------------------
# Minimal stand-in extractors for discovery/validation tests (declaration-level)
# ---------------------------------------------------------------------------

class _FakeJava(GraphExtractor):
    format = "java"
    relation_pairs = {"calls": "called_by"}

    def extract(self, source, chunks, scope):
        return []


class _FakeDdl(GraphExtractor):
    format = "ddl"
    relation_pairs = {"fk_references": "fk_referenced_by"}

    def extract(self, source, chunks, scope):
        return []


class _FakeMarkdown(GraphExtractor):
    format = "markdown"
    relation_pairs = {"references": "referenced_by"}
    chunk_scope = "scope"

    def extract(self, source, chunks, scope):
        return []


def _build(*extractors):
    return GraphExtractorRegistry(list(extractors))


SE_VOCAB = {
    "calls": ["out", "in"],
    "called_by": ["out", "in"],
    "fk_references": ["out", "in"],
    "fk_referenced_by": ["out", "in"],
}
LEGAL_VOCAB = {"references": ["out", "in"], "referenced_by": ["out", "in"]}


class TestDiscovery:
    def test_java_format_matches_java_extractor(self):
        reg = _build(_FakeJava, _FakeDdl, _FakeMarkdown)
        found = reg.discover("java", SE_VOCAB)
        assert [type(e) for e in found] == [_FakeJava]

    def test_ddl_format_matches_ddl_extractor(self):
        reg = _build(_FakeJava, _FakeDdl, _FakeMarkdown)
        found = reg.discover("ddl", SE_VOCAB)
        assert [type(e) for e in found] == [_FakeDdl]

    def test_markdown_se_vocab_matches_nothing(self):
        reg = _build(_FakeJava, _FakeDdl, _FakeMarkdown)
        assert reg.discover("markdown", SE_VOCAB) == []

    def test_markdown_legal_vocab_matches_cross_reference(self):
        reg = _build(_FakeJava, _FakeDdl, _FakeMarkdown)
        found = reg.discover("markdown", LEGAL_VOCAB)
        assert [type(e) for e in found] == [_FakeMarkdown]

    def test_empty_vocab_matches_nothing(self):
        reg = _build(_FakeJava, _FakeDdl, _FakeMarkdown)
        assert reg.discover("java", {}) == []
        assert reg.discover("markdown", {}) == []

    def test_discovery_is_deterministic_order(self):
        reg = _build(_FakeJava, _FakeDdl, _FakeMarkdown)
        first = [type(e).__name__ for e in reg.discover("java", SE_VOCAB)]
        second = [type(e).__name__ for e in reg.discover("java", SE_VOCAB)]
        assert first == second

    def test_discover_returns_instances(self):
        reg = _build(_FakeJava, _FakeDdl, _FakeMarkdown)
        found = reg.discover("java", SE_VOCAB)
        assert isinstance(found[0], GraphExtractor)


class _BadPattern(GraphExtractor):
    format = "x"
    relation_pairs = {"Foo-Bar": "foo-bar"}

    def extract(self, source, chunks, scope):
        return []


class _NonInverse(GraphExtractor):
    format = "x"
    relation_pairs = {"foo": "bar", "bar": "baz"}  # bar maps back to baz != foo

    def extract(self, source, chunks, scope):
        return []


class TestRegistrationValidation:
    def test_single_sided_or_non_inverse_pairs_rejected(self):
        with pytest.raises(ValueError):
            _build(_NonInverse)

    def test_illegal_pattern_rejected(self):
        with pytest.raises(ValueError):
            _build(_BadPattern)

    def test_non_inverse_pairs_rejected(self):
        with pytest.raises(ValueError):
            _build(_NonInverse)

    def test_cross_extractor_conflict_rejected(self):
        class A(GraphExtractor):
            format = "a"
            relation_pairs = {"foo": "bar", "bar": "foo"}

            def extract(self, source, chunks, scope):
                return []

        class B(GraphExtractor):
            format = "b"
            relation_pairs = {"foo": "baz", "baz": "foo"}

            def extract(self, source, chunks, scope):
                return []

        with pytest.raises(ValueError):
            _build(A, B)


class TestInverseMap:
    def test_inverse_map_aggregates_three_pairs_six_keys(self):
        reg = _build(_FakeJava, _FakeDdl, _FakeMarkdown)
        mapping = reg.inverse_relation_map()
        assert mapping == {
            "calls": "called_by",
            "called_by": "calls",
            "fk_references": "fk_referenced_by",
            "fk_referenced_by": "fk_references",
            "references": "referenced_by",
            "referenced_by": "references",
        }
