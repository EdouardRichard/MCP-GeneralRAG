"""Unit test for java/ddl plugin-interface migration equivalence (010, T010).

Validates that the ABC-ized JavaCallGraphExtractor / DdlFkExtractor declare
their plugin contract (format / relation_pairs / chunk_scope) and produce
edges that are byte-for-byte equivalent to the pre-migration (004) output:
same relation_type, direction pairing, dedup keys, and parse_evidence locator
(FR-005, SC-001 first half).

This test MUST FAIL before the extractors are migrated to the ABC (TDD).
"""
from __future__ import annotations

from rag_mcp.graph.extractors.base import GraphExtractor
from rag_mcp.graph.extractors.ddl_fk import DdlFkExtractor
from rag_mcp.graph.extractors.java_call_graph import JavaCallGraphExtractor
from rag_mcp.graph.store.base import GraphScope


_JAVA_SOURCE = """package com.example;

public class Calculator {
    public int compute(int x) {
        return square(add(x, 1));
    }
    public int add(int a, int b) {
        return a + b;
    }
    public int square(int x) {
        return x * x;
    }
}
"""


def _java_chunks():
    return [
        {"chunk_id": 1001, "symbol_path": "com.example.Calculator",
         "symbol_type": "class", "content_text": _JAVA_SOURCE,
         "start_line": 3, "end_line": 14},
        {"chunk_id": 1002, "symbol_path": "com.example.Calculator#compute",
         "symbol_type": "method", "content_text": "compute body",
         "start_line": 4, "end_line": 6},
        {"chunk_id": 1003, "symbol_path": "com.example.Calculator#add",
         "symbol_type": "method", "content_text": "add body",
         "start_line": 7, "end_line": 9},
        {"chunk_id": 1004, "symbol_path": "com.example.Calculator#square",
         "symbol_type": "method", "content_text": "square body",
         "start_line": 10, "end_line": 12},
    ]


_DDL = """CREATE TABLE users (
    id INT PRIMARY KEY,
    email VARCHAR(255)
);

CREATE TABLE orders (
    id INT PRIMARY KEY,
    user_id INT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


def _ddl_chunks():
    return [
        {"chunk_id": 5001, "symbol_path": "table:users",
         "symbol_type": "table", "content_text": "CREATE TABLE users (...)",
         "start_line": 1, "end_line": 4},
        {"chunk_id": 5002, "symbol_path": "table:users.column:id",
         "symbol_type": "column", "content_text": "id INT PRIMARY KEY",
         "start_line": 2, "end_line": 2},
        {"chunk_id": 5003, "symbol_path": "table:users.column:email",
         "symbol_type": "column", "content_text": "email VARCHAR(255)",
         "start_line": 3, "end_line": 3},
        {"chunk_id": 5004, "symbol_path": "table:orders",
         "symbol_type": "table", "content_text": "CREATE TABLE orders (...)",
         "start_line": 6, "end_line": 11},
        {"chunk_id": 5005, "symbol_path": "table:orders.column:id",
         "symbol_type": "column", "content_text": "id INT PRIMARY KEY",
         "start_line": 7, "end_line": 7},
        {"chunk_id": 5006, "symbol_path": "table:orders.column:user_id",
         "symbol_type": "column", "content_text": "user_id INT",
         "start_line": 8, "end_line": 8},
    ]


def _edge_key(edge):
    return (
        edge["source_chunk_id"], edge["target_chunk_id"], edge["relation_type"],
        edge["direction"],
    )


class TestJavaMigration:
    def test_java_declares_plugin_contract(self):
        assert issubclass(JavaCallGraphExtractor, GraphExtractor)
        assert JavaCallGraphExtractor.format == "java"
        assert JavaCallGraphExtractor.relation_pairs == {"calls": "called_by"}
        assert JavaCallGraphExtractor.chunk_scope == "source"

    def test_java_edges_equivalent_to_004(self):
        extractor = JavaCallGraphExtractor()
        edges = extractor.extract(_JAVA_SOURCE, _java_chunks(), GraphScope(100, 1))
        keys = {_edge_key(e) for e in edges}
        # compute calls add and square; the reciprocal called_by edges.
        assert (1002, 1003, "calls", "out") in keys
        assert (1002, 1004, "calls", "out") in keys
        assert (1003, 1002, "called_by", "out") in keys
        assert (1004, 1002, "called_by", "out") in keys
        assert len(edges) == 4

    def test_java_parse_evidence_locator(self):
        extractor = JavaCallGraphExtractor()
        edges = extractor.extract(_JAVA_SOURCE, _java_chunks(), GraphScope(100, 1))
        for e in edges:
            pe = e["parse_evidence"]
            assert pe["source_format"] == "java"
            assert pe["extractor"] == "java_call_graph"
            assert pe["locator"].startswith("method:")
            assert ":line:" in pe["locator"]


class TestDdlMigration:
    def test_ddl_declares_plugin_contract(self):
        assert issubclass(DdlFkExtractor, GraphExtractor)
        assert DdlFkExtractor.format == "ddl"
        assert DdlFkExtractor.relation_pairs == {
            "fk_references": "fk_referenced_by"}
        assert DdlFkExtractor.chunk_scope == "source"

    def test_ddl_edges_equivalent_to_004(self):
        extractor = DdlFkExtractor()
        edges = extractor.extract(_DDL, _ddl_chunks(), GraphScope(100, 1))
        keys = {_edge_key(e) for e in edges}
        assert (5004, 5001, "fk_references", "out") in keys
        assert (5001, 5004, "fk_referenced_by", "out") in keys
        assert len(edges) == 2

    def test_ddl_parse_evidence_locator(self):
        extractor = DdlFkExtractor()
        edges = extractor.extract(_DDL, _ddl_chunks(), GraphScope(100, 1))
        fk_ref = next(e for e in edges if e["relation_type"] == "fk_references")
        assert fk_ref["parse_evidence"]["locator"] == "table:orders.fk:users"
        for e in edges:
            assert e["parse_evidence"]["extractor"] == "ddl_fk"
