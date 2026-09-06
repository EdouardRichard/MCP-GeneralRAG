"""Unit test for FormatHandlerRegistry behaviour equivalence (T001, US1).

Asserts the registry reproduces the 1.0 dispatch behaviour for the 8 frozen
native formats (markdown/java/openapi/ddl/go/python/word/pdf) item-for-item:
format detection, binary declaration, graph-extractor presence, and parser
output equivalence. Written FIRST (TDD) — expected to FAIL before the
registry implementation lands.

SC-002: zero migration for the existing 8 formats.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_mcp.parsers.registry import (
    FormatHandlerRegistry,
    LocatorPrefix,
    RegistryFormatError,
)

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "samples"


@pytest.fixture(scope="module")
def registry():
    return FormatHandlerRegistry.build()


# ---------------------------------------------------------------------------
# Format detection equivalence (extensions -> canonical format)
# ---------------------------------------------------------------------------

DETECT_CASES = {
    "doc.md": "markdown",
    "notes.markdown": "markdown",
    "Service.java": "java",
    "schema.sql": "ddl",
    "service.go": "go",
    "module.py": "python",
    "design.docx": "word",
    "paper.pdf": "pdf",
}


class TestDetectFormat:
    @pytest.mark.parametrize("filename,expected", sorted(DETECT_CASES.items()))
    def test_extension_maps_to_format(self, registry, filename, expected):
        assert registry.detect_format(filename, None) == expected

    def test_openapi_sniff_hits_openapi(self, registry):
        content = (FIXTURES / "openapi.json").read_bytes()
        assert registry.detect_format("openapi.json", content) == "openapi"

    def test_openapi_sniff_yaml_hits_openapi(self, registry):
        content = (FIXTURES / "openapi.yaml").read_bytes()
        assert registry.detect_format("openapi.yaml", content) == "openapi"

    def test_unknown_extension_raises(self, registry):
        with pytest.raises(RegistryFormatError):
            registry.detect_format("file.xyz", None)

    def test_go_mismatch_raises(self, registry):
        content = (FIXTURES / "mismatched.go").read_bytes()
        with pytest.raises(RegistryFormatError):
            registry.detect_format("mismatched.go", content)


# ---------------------------------------------------------------------------
# Binary declaration equivalence (only word/pdf are binary)
# ---------------------------------------------------------------------------

class TestIsBinary:
    @pytest.mark.parametrize("fmt", ["word", "pdf"])
    def test_binary_formats(self, registry, fmt):
        assert registry.is_binary(fmt) is True

    @pytest.mark.parametrize(
        "fmt", ["markdown", "java", "openapi", "ddl", "go", "python"]
    )
    def test_text_formats(self, registry, fmt):
        assert registry.is_binary(fmt) is False

    def test_unknown_format_raises(self, registry):
        with pytest.raises(RegistryFormatError):
            registry.is_binary("nope")


# ---------------------------------------------------------------------------
# Graph-extractor dispatch equivalence (only java/ddl have hooks)
# ---------------------------------------------------------------------------

class TestGraphExtractor:
    def test_java_has_extractor(self, registry):
        extractor = registry.graph_extractor("java")
        assert extractor is not None
        assert callable(extractor)

    def test_ddl_has_extractor(self, registry):
        extractor = registry.graph_extractor("ddl")
        assert extractor is not None
        assert callable(extractor)

    @pytest.mark.parametrize(
        "fmt", ["markdown", "openapi", "go", "python", "word", "pdf"]
    )
    def test_other_formats_have_no_extractor(self, registry, fmt):
        assert registry.graph_extractor(fmt) is None


# ---------------------------------------------------------------------------
# parse_content equivalence with the frozen parsers
# ---------------------------------------------------------------------------

class TestParseContentEquivalence:
    def test_markdown_equivalence(self, registry):
        from rag_mcp.parsers.markdown_parser import MarkdownParser

        text = "# Title\n\nParagraph one.\n\n## Sub\n\nMore text here.\n"
        assert registry.parse_content(text, "markdown", "doc.md") == (
            MarkdownParser().parse(text)
        )

    def test_java_equivalence(self, registry):
        from rag_mcp.parsers.java_parser import JavaParser

        text = (
            "package com.example;\n"
            "public class Foo {\n"
            "    public void bar() { System.out.println(1); }\n"
            "}\n"
        )
        assert registry.parse_content(text, "java", "Foo.java") == (
            JavaParser().parse(text, filename="Foo.java")
        )

    def test_openapi_equivalence(self, registry):
        from rag_mcp.parsers.openapi_parser import OpenAPIParser

        text = (FIXTURES / "openapi.json").read_text()
        assert registry.parse_content(text, "openapi", "openapi.json") == (
            OpenAPIParser().parse(text, filename="openapi.json")
        )

    def test_ddl_equivalence(self, registry):
        from rag_mcp.parsers.ddl_parser import DDLParser

        text = (FIXTURES / "schema.sql").read_text()
        assert registry.parse_content(text, "ddl", "schema.sql") == (
            DDLParser().parse(text, filename="schema.sql")
        )

    def test_go_equivalence(self, registry):
        from rag_mcp.parsers.go_parser import GoParser

        text = (FIXTURES / "service.go").read_text()
        assert registry.parse_content(text, "go", "service.go") == (
            GoParser().parse(text, filename="service.go")
        )

    def test_python_equivalence(self, registry):
        from rag_mcp.parsers.python_parser import PythonParser

        text = (FIXTURES / "module.py").read_text()
        assert registry.parse_content(text, "python", "module.py") == (
            PythonParser().parse(text, filename="module.py")
        )

    def test_word_equivalence(self, registry):
        from rag_mcp.parsers.text_extractor import extract_text
        from rag_mcp.parsers.word_parser import WordParser

        raw = (FIXTURES / "design.docx").read_bytes()
        text = extract_text(raw, "word")
        assert registry.parse_content(text, "word", "design.docx") == (
            WordParser().parse(text, filename="design.docx")
        )

    def test_pdf_equivalence(self, registry):
        from rag_mcp.parsers.text_extractor import extract_text
        from rag_mcp.parsers.pdf_parser import PDFParser

        raw = (FIXTURES / "paper.pdf").read_bytes()
        text = extract_text(raw, "pdf")
        assert registry.parse_content(text, "pdf", "paper.pdf") == (
            PDFParser().parse(text, filename="paper.pdf")
        )


# ---------------------------------------------------------------------------
# Registry invariants (17 entries after Phase 4; 8 in Phase 1)
# ---------------------------------------------------------------------------

class TestRegistryInvariants:
    def test_native_tier_has_parser_factory(self, registry):
        for handler in registry.handlers():
            if handler.tier == "native":
                assert handler.parser_factory is not None
                assert handler.converter_spec is None

    def test_no_duplicate_extensions(self, registry):
        seen: set[str] = set()
        for handler in registry.handlers():
            for ext in handler.extensions:
                assert ext not in seen, f"duplicate extension {ext}"
                seen.add(ext)

    def test_error_message_lists_acceptable_formats(self, registry):
        with pytest.raises(RegistryFormatError) as exc_info:
            registry.detect_format("nope.xyz", None)
        msg = str(exc_info.value)
        # the error message must carry the acceptable-format list (single source of truth)
        assert "markdown" in msg and "pdf" in msg
