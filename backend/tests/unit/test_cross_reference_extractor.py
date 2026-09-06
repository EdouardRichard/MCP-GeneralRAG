"""Unit test for the cross-reference extractor (010, T034/T035, VS-03/VS-04).

Validates the three reference forms (internal anchor / relative link / clause
reference) each produce paired references/referenced_by hard edges, the hybrid
anchoring (line-number source + heading target), locator encoding, heading
normalization (Chinese/English), clause-number prefix matching, document-order
disambiguation, and the four false-positive exclusions (narrative / range /
relative / target-not-in-corpus).

This test MUST FAIL before cross_reference.py is implemented (TDD).
"""
from __future__ import annotations

from rag_mcp.graph.extractors.cross_reference import CrossReferenceExtractor
from rag_mcp.graph.store.base import GraphScope


def _chunk(cid, heading, start, end, filename="law.md", is_current=True):
    return {
        "chunk_id": cid,
        "heading": heading,
        "start_line": start,
        "end_line": end,
        "filename": filename,
        "is_current": is_current,
    }


def _extract(source, chunks):
    return CrossReferenceExtractor().extract(source, chunks, GraphScope(100, 1))


def _pairs(edges):
    return {(e["source_chunk_id"], e["target_chunk_id"], e["relation_type"]) for e in edges}


class TestInternalAnchor:
    def test_internal_anchor_produces_paired_edges(self):
        source = "# Law\n\n## General Provisions\n\nSee [Penalties](#penalties).\n\n## Penalties\n\nFines apply.\n"
        chunks = [
            _chunk(1, "General Provisions", 3, 5),
            _chunk(2, "Penalties", 7, 9),
        ]
        edges = _extract(source, chunks)
        assert (1, 2, "references") in _pairs(edges)
        assert (2, 1, "referenced_by") in _pairs(edges)

    def test_internal_anchor_locator(self):
        source = "# Law\n\n## Penalties\n\nSee [Penalties](#penalties).\n"
        # self-reference (source chunk == target chunk) -> no edge
        chunks = [_chunk(1, "Penalties", 1, 3)]
        edges = _extract(source, chunks)
        assert edges == []


class TestRelativeLink:
    def test_cross_file_relative_link_no_anchor(self):
        source = "# Law\n\n## 总则\n\n见 [细则](./rules.md)。\n"
        chunks = [
            _chunk(1, "总则", 3, 5, filename="law.md", is_current=True),
            _chunk(10, "第一条", 1, 3, filename="rules.md", is_current=False),
        ]
        edges = _extract(source, chunks)
        assert (1, 10, "references") in _pairs(edges)
        assert (10, 1, "referenced_by") in _pairs(edges)

    def test_cross_file_relative_link_locator(self):
        source = "# Law\n\n## 总则\n\n见 [细则](./rules.md)。\n"
        chunks = [
            _chunk(1, "总则", 3, 5, filename="law.md", is_current=True),
            _chunk(10, "第一条", 1, 3, filename="rules.md", is_current=False),
        ]
        edges = _extract(source, chunks)
        ref = next(e for e in edges if e["relation_type"] == "references")
        assert ref["parse_evidence"]["locator"] == (
            "xref:relative:file=rules.md:anchor=-:text=细则:line=5"
        )


class TestClauseReference:
    def test_chinese_clause_reference(self):
        source = "# Law\n\n## 第一条 总则\n\n本法依据第二条制定。\n\n## 第二条 适用范围\n\n本文规定适用。\n"
        chunks = [
            _chunk(1, "第一条 总则", 3, 5),
            _chunk(2, "第二条 适用范围", 7, 9),
        ]
        edges = _extract(source, chunks)
        assert (1, 2, "references") in _pairs(edges)
        assert (2, 1, "referenced_by") in _pairs(edges)

    def test_point_number_clause_reference(self):
        source = "# Doc\n\n## 4.1 General\n\n参见 4.2 的规定。\n\n## 4.2 Scope\n\nScope defined.\n"
        chunks = [
            _chunk(1, "4.1 General", 3, 5),
            _chunk(2, "4.2 Scope", 7, 9),
        ]
        edges = _extract(source, chunks)
        assert (1, 2, "references") in _pairs(edges)

    def test_clause_locator(self):
        source = "# Law\n\n## 第一条 总则\n\n本法依据第二条制定。\n\n## 第二条 适用范围\n\n本文规定适用。\n"
        chunks = [
            _chunk(1, "第一条 总则", 3, 5),
            _chunk(2, "第二条 适用范围", 7, 9),
        ]
        edges = _extract(source, chunks)
        ref = next(e for e in edges if e["relation_type"] == "references")
        loc = ref["parse_evidence"]["locator"]
        assert loc.startswith("xref:clause:ref=第二条:marker=依据:line=5")


class TestAnchoringAndNormalization:
    def test_line_number_source_anchoring(self):
        source = "# Law\n\n## 第一条 总则\n\n前言。\n\n依据第二条。\n\n## 第二条 适用范围\n\n内容。\n"
        chunks = [
            _chunk(1, "第一条 总则", 3, 7),
            _chunk(2, "第二条 适用范围", 9, 11),
        ]
        edges = _extract(source, chunks)
        ref = next(e for e in edges if e["relation_type"] == "references")
        assert ref["source_chunk_id"] == 1
        assert ref["target_chunk_id"] == 2

    def test_heading_normalization_whitespace_and_case(self):
        source = "# Law\n\n## 总则\n\nSee [rules](#data-protection-rules).\n\n## Data Protection Rules\n\n内容。\n"
        chunks = [
            _chunk(1, "总则", 3, 5),
            _chunk(2, "Data Protection Rules", 7, 9),
        ]
        edges = _extract(source, chunks)
        assert (1, 2, "references") in _pairs(edges)

    def test_duplicate_heading_document_order_first(self):
        source = "# Law\n\n## 总则\n\n见 [第一条](#第一条)。\n"
        chunks = [
            _chunk(1, "总则", 3, 5, filename="a.md", is_current=True),
            _chunk(10, "第一条", 1, 2, filename="a.md", is_current=True),
            _chunk(20, "第一条", 1, 2, filename="b.md", is_current=False),
        ]
        edges = _extract(source, chunks)
        # document-order first: chunk 10 (a.md) wins over chunk 20 (b.md)
        ref = next(e for e in edges if e["relation_type"] == "references")
        assert ref["target_chunk_id"] == 10


class TestFalsePositives:
    def test_narrative_mention_no_trigger_word(self):
        source = "# Law\n\n## 第一条 总则\n\n本法第一条确立了基本制度。\n"
        chunks = [_chunk(1, "第一条 总则", 3, 5)]
        assert _extract(source, chunks) == []

    def test_range_reference_no_edge(self):
        source = "# Law\n\n## 第一条 总则\n\n参见第一条至第三条。\n"
        chunks = [
            _chunk(1, "第一条 总则", 3, 5),
            _chunk(2, "第三条 附则", 7, 9),
        ]
        assert _extract(source, chunks) == []

    def test_relative_reference_no_edge(self):
        source = "# Law\n\n## 第一条 总则\n\n前条已有规定，本条补充。\n"
        chunks = [_chunk(1, "第一条 总则", 3, 5)]
        assert _extract(source, chunks) == []

    def test_target_not_in_corpus_no_edge(self):
        source = "# Law\n\n## 第一条 总则\n\n依据第九十九条制定。\n"
        chunks = [_chunk(1, "第一条 总则", 3, 5)]
        assert _extract(source, chunks) == []

    def test_external_link_no_edge(self):
        source = "# Law\n\n## 总则\n\n见 [外部](https://example.com)。\n"
        chunks = [_chunk(1, "总则", 3, 5)]
        assert _extract(source, chunks) == []


class TestPairedSymmetry:
    def test_every_reference_has_referenced_by(self):
        source = "# Law\n\n## 第一条 总则\n\n本法依据第二条制定。\n\n## 第二条 适用范围\n\n内容。\n"
        chunks = [
            _chunk(1, "第一条 总则", 3, 5),
            _chunk(2, "第二条 适用范围", 7, 9),
        ]
        edges = _extract(source, chunks)
        refs = [e for e in edges if e["relation_type"] == "references"]
        rby = [e for e in edges if e["relation_type"] == "referenced_by"]
        assert len(refs) == len(rby) >= 1
        for r in refs:
            mirror = (r["target_chunk_id"], r["source_chunk_id"], "referenced_by")
            assert mirror in _pairs(edges)
