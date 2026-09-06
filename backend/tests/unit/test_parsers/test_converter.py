"""Conversion-layer contract tests (T013, US2).

Locks markitdown 0.1.7 behaviour for the 8 converter-tier formats: for each
format a "given input -> expected Markdown IR structure" assertion pins the
converted output so a dependency upgrade that changes the IR shape fails here
(FR-036 / SC-009).

Fixtures live under backend/tests/fixtures/samples/.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_mcp.parsers.converter import (
    ConverterError,
    ConverterUnavailableError,
    MarkitdownConverter,
    NoopConverter,
    YamlAdapter,
)

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "samples"


@pytest.fixture(scope="module")
def converter() -> MarkitdownConverter:
    return MarkitdownConverter()


def _convert(converter, name, fmt):
    raw = (FIXTURES / name).read_bytes()
    return converter.convert(raw, fmt, name)


class TestMarkitdownVersionLock:
    def test_version_is_locked(self):
        import importlib.metadata as m

        assert m.version("markitdown") == "0.1.7"


class TestHtmlConversion:
    def test_html_produces_heading_and_table(self, converter):
        out = _convert(converter, "report.html", "html")
        assert "# Quarterly Report" in out
        assert "## Sales Breakdown" in out
        assert "| Product | Qty |" in out
        assert "* East" in out


class TestCsvConversion:
    def test_csv_produces_pipe_table(self, converter):
        out = _convert(converter, "report.csv", "csv")
        assert "| name | amount |" in out
        assert "| alpha | 10 |" in out


class TestJsonConversion:
    def test_json_preserves_structure(self, converter):
        out = _convert(converter, "config.json", "json")
        assert '"service"' in out
        assert '"host": "api.internal"' in out


class TestXmlConversion:
    def test_xml_preserves_elements(self, converter):
        out = _convert(converter, "catalog.xml", "xml")
        assert "<root>" in out
        assert "<name>Widget</name>" in out


class TestXlsxConversion:
    def test_xlsx_produces_sheet_tables(self, converter):
        out = _convert(converter, "book.xlsx", "xlsx")
        assert "Sheet1" in out
        assert "| Product | Qty | Price |" in out
        assert "## Sheet2" in out


class TestPptxConversion:
    def test_pptx_produces_slide_titles(self, converter):
        out = _convert(converter, "deck.pptx", "pptx")
        assert "# Slide 1" in out
        assert "# Slide 2" in out
        assert "Introduction bullet one" in out


class TestEmlConversion:
    def test_eml_preserves_headers_and_body(self, converter):
        out = _convert(converter, "msg.eml", "eml")
        assert "Subject: Re: Contract Review" in out
        assert "From: alice@example.com" in out
        assert "Please review the attached contract" in out


class TestYamlAdapter:
    def test_yaml_produces_json_equivalent(self):
        out = YamlAdapter().convert(
            (FIXTURES / "config.yaml").read_bytes(), "yaml", "config.yaml"
        )
        assert '"service"' in out
        assert '"host": "api.internal"' in out


class TestConverterFailureSemantics:
    def test_empty_input_raises(self, converter):
        with pytest.raises(ConverterError):
            converter.convert(b"", "html", "empty.html")

    def test_noop_converter_raises_unavailable(self):
        with pytest.raises(ConverterUnavailableError):
            NoopConverter().convert(b"x", "doc", "x.doc")

    def test_markitdown_available(self, converter):
        assert converter.available() is True
