"""EML slicer unit tests (T036, US2)."""
from __future__ import annotations

from pathlib import Path

from rag_mcp.parsers.registry import FormatHandlerRegistry
from rag_mcp.parsers.slicers import eml_slicer

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "samples"


def _ir():
    raw = (FIXTURES / "msg.eml").read_bytes()
    return FormatHandlerRegistry.build().to_text(raw, "eml", "msg.eml")


class TestEmlSlicing:
    def test_msg_subject_locator(self):
        chunks = eml_slicer(_ir(), "eml", "msg.eml")
        assert chunks
        assert chunks[0]["position_path"] == "msg:Re: Contract Review"

    def test_header_names_and_body_preserved(self):
        chunks = eml_slicer(_ir(), "eml", "msg.eml")
        text = chunks[0]["content_text"]
        assert "From: alice@example.com" in text
        assert "To: bob@example.com" in text
        assert "Subject: Re: Contract Review" in text
        assert "Please review the attached contract" in text

    def test_empty_returns_no_chunks(self):
        assert eml_slicer("", "eml", "empty.eml") == []

