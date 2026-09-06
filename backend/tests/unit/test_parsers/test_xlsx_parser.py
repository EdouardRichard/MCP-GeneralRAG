"""XLSX slicer unit tests (T032, US2)."""
from __future__ import annotations

from pathlib import Path

from rag_mcp.parsers.registry import FormatHandlerRegistry
from rag_mcp.parsers.slicers import xlsx_slicer

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "samples"


def _ir():
    raw = (FIXTURES / "book.xlsx").read_bytes()
    return FormatHandlerRegistry.build().to_text(raw, "xlsx", "book.xlsx")


class TestXlsxSlicing:
    def test_multi_sheet_slicing(self):
        chunks = xlsx_slicer(_ir(), "xlsx", "book.xlsx")
        assert len(chunks) >= 2

    def test_sheet_locator(self):
        chunks = xlsx_slicer(_ir(), "xlsx", "book.xlsx")
        paths = {c["position_path"] for c in chunks}
        assert "sheet:Sheet1" in paths
        assert "sheet:Sheet2" in paths

    def test_table_chunk(self):
        chunks = xlsx_slicer(_ir(), "xlsx", "book.xlsx")
        assert all(c["chunk_type"] == "table" for c in chunks)

