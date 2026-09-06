"""CSV slicer unit tests (T026, US2)."""
from __future__ import annotations

from pathlib import Path

from rag_mcp.parsers.slicers import csv_slicer

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "samples"


def _ir(name="report.csv"):
    from rag_mcp.parsers.converter import MarkitdownConverter
    raw = (FIXTURES / name).read_bytes()
    return MarkitdownConverter().convert(raw, "csv", name)


class TestCsvWindowSlicing:
    def test_produces_table_chunk_with_sheet_locator(self):
        chunks = csv_slicer(_ir(), "csv", "report.csv")
        assert chunks
        assert chunks[0]["chunk_type"] == "table"
        assert chunks[0]["position_path"] == "sheet:report"

    def test_header_preserved(self):
        chunks = csv_slicer(_ir(), "csv", "report.csv")
        assert "name" in chunks[0]["content_text"]
        assert "amount" in chunks[0]["content_text"]

    def test_over_50_rows_splits_into_windows(self):
        header = "name,amount"
        rows = [header] + [f"r{i},{i}" for i in range(120)]
        ir = "\n".join(rows)
        chunks = csv_slicer(ir, "csv", "big.csv")
        assert len(chunks) >= 3  # header + 120 rows -> 3 windows of 50

    def test_empty_dataset_returns_no_chunks(self):
        assert csv_slicer("", "csv", "empty.csv") == []
        assert csv_slicer("name,amount", "csv", "empty.csv") == []

