"""PPTX slicer unit tests (T034, US2)."""
from __future__ import annotations

from pathlib import Path

from rag_mcp.parsers.registry import FormatHandlerRegistry
from rag_mcp.parsers.slicers import markdown_structure_slicer

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "samples"


def _ir():
    raw = (FIXTURES / "deck.pptx").read_bytes()
    return FormatHandlerRegistry.build().to_text(raw, "pptx", "deck.pptx")


class TestPptxSlicing:
    def test_slide_title_locator(self):
        chunks = markdown_structure_slicer(_ir(), "pptx", "deck.pptx")
        paths = [c["position_path"] for c in chunks]
        assert any(p.startswith("# Slide 1") for p in paths)

    def test_heading_and_paragraph_output(self):
        chunks = markdown_structure_slicer(_ir(), "pptx", "deck.pptx")
        types = {c["chunk_type"] for c in chunks}
        assert "heading" in types

