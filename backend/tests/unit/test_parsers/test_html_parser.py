"""HTML slicer unit tests (T028, US2)."""
from __future__ import annotations

from pathlib import Path

from rag_mcp.parsers.slicers import markdown_structure_slicer

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "samples"


def _ir():
    from rag_mcp.parsers.converter import MarkitdownConverter
    raw = (FIXTURES / "report.html").read_bytes()
    return MarkitdownConverter().convert(raw, "html", "report.html")


class TestHtmlSlicing:
    def test_produces_heading_paragraph_list_table(self):
        chunks = markdown_structure_slicer(_ir(), "html", "report.html")
        types = {c["chunk_type"] for c in chunks}
        assert "heading" in types
        assert "paragraph" in types
        assert "list" in types
        assert "table" in types

    def test_heading_path_locator(self):
        chunks = markdown_structure_slicer(_ir(), "html", "report.html")
        paths = [c["position_path"] for c in chunks]
        assert any(p.startswith("# Quarterly Report") for p in paths)

