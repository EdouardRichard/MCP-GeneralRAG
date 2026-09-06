"""008 locator-prefix contract tests (T037, US4).

Asserts the 9 new formats' source_position (position_path) conforms to the
locator-prefix table in contracts/locator-prefixes.md (sheet:/path:/msg:/#
heading path; txt is document-level with an empty section path).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rag_mcp.parsers.registry import FormatHandlerRegistry

FIXTURES = Path(__file__).resolve().parents[3] / "backend" / "tests" / "fixtures" / "samples"

_PATTERNS = {
    "html": r"^#.*$",
    "csv": r"^sheet:[A-Za-z0-9_\-]+$",
    "json": r"^path:/.*$",
    "yaml": r"^path:/.*$",
    "xml": r"^path:/.*$",
    "xlsx": r"^sheet:.+$",
    "pptx": r"^#.*$",
    "eml": r"^msg:.+$",
}

_FIXTURES = {
    "html": "report.html",
    "csv": "report.csv",
    "json": "config.json",
    "yaml": "config.yaml",
    "xml": "catalog.xml",
    "xlsx": "book.xlsx",
    "pptx": "deck.pptx",
    "eml": "msg.eml",
}


@pytest.fixture(scope="module")
def registry():
    return FormatHandlerRegistry.build()


def _chunks(registry, fmt):
    name = _FIXTURES[fmt]
    raw = (FIXTURES / name).read_bytes()
    ir = registry.to_text(raw, fmt, name)
    return registry.parse_content(ir, fmt, name)


class TestLocatorPrefixes:
    @pytest.mark.parametrize("fmt", sorted(_PATTERNS))
    def test_converter_locator_matches_pattern(self, registry, fmt):
        chunks = _chunks(registry, fmt)
        assert chunks, f"{fmt} produced no chunks"
        for c in chunks:
            assert re.fullmatch(_PATTERNS[fmt], c["position_path"]), (
                f"{fmt} position_path {c['position_path']!r} does not match {_PATTERNS[fmt]!r}"
            )


class TestTxtDocumentLevelLocator:
    def test_txt_document_level_fallback_locator(self, registry):
        raw = (FIXTURES / "notes.txt").read_bytes()
        ir = registry.to_text(raw, "txt", "notes.txt")
        chunks = registry.parse_content(ir, "txt", "notes.txt")
        assert chunks
        for c in chunks:
            assert c["position_path"] == "# notes"
            assert c["start_line"] >= 1
            assert c["end_line"] >= c["start_line"]
