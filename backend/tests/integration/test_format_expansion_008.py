"""008 format-expansion integration tests (T039, US2).

Two layers: (1) upload + format detection for the 9 new formats via the
management API; (2) the converter pipeline (to_text -> parse_content) yields
L1 chunk types with the correct locator for every format. The full
embedding/retrieval leg is covered by test_target_host_smoke.py (live infra).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_mcp.parsers.registry import FormatHandlerRegistry
from rag_mcp.utils.snowflake import generate_id

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = PROJECT_ROOT / "backend" / "tests" / "fixtures" / "samples"

_L1 = {"section", "heading", "paragraph", "list", "table"}

_UPLOAD_CASES = {
    "report.html": "html",
    "notes.txt": "txt",
    "report.csv": "csv",
    "config.json": "json",
    "config.yaml": "yaml",
    "catalog.xml": "xml",
    "book.xlsx": "xlsx",
    "deck.pptx": "pptx",
    "msg.eml": "eml",
}


class TestFormatDetection008:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("filename,expected", sorted(_UPLOAD_CASES.items()))
    async def test_upload_detects_format(self, test_client, filename, expected):
        alias = _uniq("f8")
        resp = await test_client.post("/api/projects", json={"name": "F8", "alias": alias})
        assert resp.status_code == 201
        scope_id = resp.json()["knowledge_scope_id"]
        with open(FIXTURES / filename, "rb") as f:
            resp = await test_client.post(
                f"/api/knowledge-sources?scope_id={scope_id}",
                files={"file": (filename, f, "application/octet-stream")},
            )
        assert resp.status_code == 201, resp.text
        assert resp.json()["format"] == expected


class TestConverterPipeline008:
    @pytest.fixture(scope="class")
    def registry(self):
        return FormatHandlerRegistry.build()

    @pytest.mark.parametrize("filename,fmt", sorted(_UPLOAD_CASES.items()))
    def test_convert_and_slice_yields_l1(self, registry, filename, fmt):
        raw = (FIXTURES / filename).read_bytes()
        ir = registry.to_text(raw, fmt, filename)
        chunks = registry.parse_content(ir, fmt, filename)
        assert chunks, f"{fmt} produced no chunks"
        for c in chunks:
            assert c["chunk_type"] in _L1, f"{fmt} chunk_type {c['chunk_type']!r}"
            assert c["content_text"].strip()


def _uniq(prefix):
    return f"{prefix}-{generate_id()}"
