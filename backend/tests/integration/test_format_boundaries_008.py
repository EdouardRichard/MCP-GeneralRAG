"""008 boundary-semantics tests (T040, US2).

fail-fast behaviour: oversized uploads, corrupted binaries, empty datasets,
extension/content mismatch, and converter unavailability must all be rejected
without producing empty chunks (FR-015, research §5).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from rag_mcp.parsers.converter import (
    ConverterError,
    ConverterUnavailableError,
    MarkitdownConverter,
    NoopConverter,
)
from rag_mcp.parsers.registry import FormatHandlerRegistry, RegistryFormatError
from rag_mcp.utils.snowflake import generate_id
from rag_mcp.parsers.slicers import csv_slicer

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = PROJECT_ROOT / "backend" / "tests" / "fixtures" / "samples"


class TestOversizeUpload:
    @pytest.mark.asyncio
    async def test_oversize_file_rejected(self, test_client, monkeypatch):
        monkeypatch.setenv("MAX_UPLOAD_SIZE_BYTES", "16")
        alias = f"oversize-{generate_id()}"
        resp = await test_client.post("/api/projects", json={"name": "Oversize", "alias": alias})
        assert resp.status_code == 201
        scope_id = resp.json()["knowledge_scope_id"]
        resp = await test_client.post(
            f"/api/knowledge-sources?scope_id={scope_id}",
            files={"file": ("big.txt", io.BytesIO(b"x" * 100), "text/plain")},
        )
        assert resp.status_code == 413


class TestCorruptedBinary:
    def test_corrupted_xlsx_produces_no_chunks(self):
        # markitdown degrades a non-zip input to plain text; the xlsx slicer
        # then yields no '## Sheet' blocks -> "no chunk then fail" (FR-015).
        registry = FormatHandlerRegistry.build()
        ir = registry.to_text(b"not a real xlsx", "xlsx", "corrupt.xlsx")
        chunks = registry.parse_content(ir, "xlsx", "corrupt.xlsx")
        assert chunks == []



class TestEmptyCsv:
    def test_empty_csv_returns_no_chunks(self):
        assert csv_slicer("", "csv", "empty.csv") == []
        assert csv_slicer("name,amount", "csv", "empty.csv") == []


class TestExtensionContentMismatch:
    def test_go_without_package_rejected(self):
        registry = FormatHandlerRegistry.build()
        with pytest.raises(RegistryFormatError):
            registry.detect_format("mismatched.go", b"package main" * 0 + b"func x() {}")


class TestConverterUnavailable:
    def test_noop_converter_raises_unavailable(self):
        with pytest.raises(ConverterUnavailableError):
            NoopConverter().convert(b"x", "doc", "x.doc")

    def test_unavailable_converter_detected_at_registry(self):
        from rag_mcp.parsers.registry import ConverterSpec, FormatHandler, LocatorPrefix

        handler = FormatHandler(
            format="doc",
            extensions=(".doc",),
            tier="converter",
            binary=True,
            converter_spec=ConverterSpec(converter=NoopConverter(), chunk_slicer=lambda *a: []),
            graph_extractor=None,
            locator_prefix=LocatorPrefix.HEADING,
        )
        registry = FormatHandlerRegistry.build()
        with pytest.raises(RegistryFormatError):
            registry._check_converter_available(handler)
