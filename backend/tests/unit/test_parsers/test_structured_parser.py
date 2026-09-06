"""JSON/YAML/XML slicer unit tests (T030, US2)."""
from __future__ import annotations

from pathlib import Path

import pytest

from rag_mcp.parsers.registry import FormatHandlerRegistry, RegistryFormatError
from rag_mcp.parsers.slicers import json_yaml_slicer, xml_slicer

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "samples"


def _registry():
    return FormatHandlerRegistry.build()


def _slice_json_yaml(name, fmt):
    raw = (FIXTURES / name).read_bytes()
    ir = _registry().to_text(raw, fmt, name)
    return _registry().parse_content(ir, fmt, name)


class TestJsonYamlKeyPath:
    def test_json_top_level_key_path(self):
        chunks = _slice_json_yaml("config.json", "json")
        paths = {c["position_path"] for c in chunks}
        assert "path:/service" in paths
        assert "path:/users" in paths

    def test_yaml_top_level_key_path(self):
        chunks = _slice_json_yaml("config.yaml", "yaml")
        paths = {c["position_path"] for c in chunks}
        assert "path:/service" in paths
        assert "path:/users" in paths

    def test_chunks_are_l1(self):
        for name, fmt in [("config.json", "json"), ("config.yaml", "yaml")]:
            chunks = _slice_json_yaml(name, fmt)
            assert chunks
            for c in chunks:
                assert c["chunk_type"] in {"section", "heading", "paragraph", "list", "table"}

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            json_yaml_slicer("{not json", "json", "bad.json")


class TestXmlElementPath:
    def test_xml_element_path(self):
        raw = (FIXTURES / "catalog.xml").read_bytes()
        ir = _registry().to_text(raw, "xml", "catalog.xml")
        chunks = xml_slicer(ir, "xml", "catalog.xml")
        paths = {c["position_path"] for c in chunks}
        assert "path:/item" in paths


class TestOpenApiSniffingOrder:
    def test_openapi_sniff_hits_openapi(self):
        content = (FIXTURES / "openapi.json").read_bytes()
        assert _registry().detect_format("openapi.json", content) == "openapi"

    def test_json_falls_back_to_generic_json(self):
        content = (FIXTURES / "config.json").read_bytes()
        assert _registry().detect_format("config.json", content) == "json"

    def test_yaml_falls_back_to_generic_yaml(self):
        content = (FIXTURES / "config.yaml").read_bytes()
        assert _registry().detect_format("config.yaml", content) == "yaml"

