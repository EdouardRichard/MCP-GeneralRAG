"""TXT parser unit tests (T024, US2)."""
from __future__ import annotations

from pathlib import Path

from rag_mcp.parsers.txt_parser import TxtParser

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "samples"


def _parse(name="notes.txt"):
    text = (FIXTURES / name).read_text()
    return TxtParser().parse(text, name)


class TestTxtBlankLineSegmentation:
    def test_paragraphs_produce_paragraph_chunks(self):
        chunks = _parse()
        assert chunks, "notes.txt must produce chunks"
        assert all(c["chunk_type"] == "paragraph" for c in chunks)
        assert len(chunks) >= 3

    def test_document_level_locator(self):
        chunks = _parse()
        for c in chunks:
            assert c["position_path"] == ""
            assert c["start_line"] >= 1
            assert c["end_line"] >= c["start_line"]

    def test_empty_content_returns_no_chunks(self):
        assert TxtParser().parse("", "empty.txt") == []
        assert TxtParser().parse("   \n\n  ", "empty.txt") == []


class TestTxtLongParagraphSplit:
    def test_overlong_paragraph_is_split(self):
        words = "word " * 400
        text = "A long paragraph: " + words
        chunks = TxtParser().parse(text, "long.txt")
        assert chunks
        assert all(c["chunk_type"] == "paragraph" for c in chunks)
        assert all(c["token_count"] <= 1100 for c in chunks)

