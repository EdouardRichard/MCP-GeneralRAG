"""FormatHandler registry: single source of truth for format dispatch (008, FR-001).

Converges the four scattered dispatch points (format detection, parse
dispatch, binary declaration, graph-extractor dispatch) onto one
deterministic, read-only in-memory registry. Each FormatHandler entry
declares a format's complete ingestion capability (FR-002).

The registry is built once at application/service startup; a build failure
(duplicate format, duplicate extension, or an import error for a frozen
native parser) MUST raise and thereby fail startup — there is no silent
fallback to the legacy if/elif chains (FR-001, Constitution VI).

Errors are produced by the registry itself so every entry point speaks the
same message including the acceptable-format list (FR-007).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal


class LocatorPrefix(str, Enum):
    """Evidence locator prefixes (contracts/locator-prefixes.md)."""

    SHEET = "sheet"
    PATH = "path"
    MSG = "msg"
    HEADING = "heading"   # '#' title path
    PAGE = "page"
    SYMBOL = "symbol"


@dataclass(frozen=True)
class ConverterSpec:
    """Specification for a converter-tier format (contracts/format-handler-registry.md §2).

    Attributes:
        converter: a Converter instance (MarkitdownConverter/YamlAdapter/...).
        chunk_slicer: callable (markdown_ir, fmt, filename) -> list[dict]
            that slices the converted Markdown IR into chunk dicts.
    """

    converter: Any | None = None
    chunk_slicer: Callable[..., Any] | None = None


@dataclass(frozen=True)
class FormatHandler:
    """Immutable declaration of a single format's ingestion capability (FR-002).

    Invariants (contracts/format-handler-registry.md §1):
        * native tier: parser_factory non-None, converter_spec None.
        * converter tier: converter_spec non-None, parser_factory None.
    """

    format: str
    extensions: tuple[str, ...]
    tier: Literal["native", "converter"]
    binary: bool
    parser_factory: Callable[..., Any] | None = None
    converter_spec: ConverterSpec | None = None
    graph_extractor: Callable[..., Any] | None = None
    text_extractor: Callable[..., Any] | None = None
    locator_prefix: LocatorPrefix = LocatorPrefix.HEADING


class RegistryFormatError(ValueError):
    """Raised for unsupported formats, unknown extensions, or converter unavailability."""


def upload_size_limit_message(max_size: int) -> str:
    """Single-source-of-truth upload size-ceiling message (T057, FR-015)."""
    return f"File exceeds the maximum upload size of {max_size} bytes"


def _unsupported_message(accepted: list[str]) -> str:
    """Compose the single-source-of-truth supported-format suffix (FR-007)."""
    return "Supported formats: " + ", ".join(accepted)


class FormatHandlerRegistry:
    """Read-only singleton registry of format handlers (Constitution VI)."""

    _instance: "FormatHandlerRegistry | None" = None

    def __init__(self, handlers: list[FormatHandler]) -> None:
        self._handlers = handlers
        self._by_format: dict[str, FormatHandler] = {}
        self._by_ext: dict[str, FormatHandler] = {}
        for handler in handlers:
            self._by_format[handler.format] = handler
            for ext in handler.extensions:
                self._by_ext[ext] = handler
        self._accepted = sorted(h.format for h in handlers)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(cls) -> "FormatHandlerRegistry":
        """Build the registry from the frozen native + converter format set.

        Raises RegistryFormatError on duplicate format/extension or when a
        frozen native parser cannot be imported (startup failure, no fallback).
        """
        # Eager import of the frozen native parsers (FR-008): a missing
        # dependency here is a startup failure, not a silent if/elif fallback.
        from rag_mcp.parsers.ddl_parser import DDLParser
        from rag_mcp.parsers.go_parser import GoParser
        from rag_mcp.parsers.java_parser import JavaParser
        from rag_mcp.parsers.markdown_parser import MarkdownParser
        from rag_mcp.parsers.openapi_parser import OpenAPIParser
        from rag_mcp.parsers.pdf_parser import PDFParser
        from rag_mcp.parsers.python_parser import PythonParser
        from rag_mcp.parsers.word_parser import WordParser
        from rag_mcp.parsers.converter import MarkitdownConverter, YamlAdapter
        from rag_mcp.parsers import slicers
        from rag_mcp.parsers.txt_parser import TxtParser

        handlers: list[FormatHandler] = [
            FormatHandler(
                format="markdown",
                extensions=(".md", ".markdown"),
                tier="native",
                binary=False,
                parser_factory=lambda content, filename: MarkdownParser().parse(content),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.HEADING,
            ),
            FormatHandler(
                format="java",
                extensions=(".java",),
                tier="native",
                binary=False,
                parser_factory=lambda content, filename: JavaParser().parse(content, filename=filename),
                graph_extractor=_java_graph_extractor,
                locator_prefix=LocatorPrefix.SYMBOL,
            ),
            FormatHandler(
                format="openapi",
                extensions=(),
                tier="native",
                binary=False,
                parser_factory=lambda content, filename: OpenAPIParser().parse(content, filename=filename),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.SYMBOL,
            ),
            FormatHandler(
                format="ddl",
                extensions=(".sql",),
                tier="native",
                binary=False,
                parser_factory=lambda content, filename: DDLParser().parse(content, filename=filename),
                graph_extractor=_ddl_graph_extractor,
                locator_prefix=LocatorPrefix.SYMBOL,
            ),
            FormatHandler(
                format="go",
                extensions=(".go",),
                tier="native",
                binary=False,
                parser_factory=lambda content, filename: GoParser().parse(content, filename=filename),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.SYMBOL,
            ),
            FormatHandler(
                format="python",
                extensions=(".py",),
                tier="native",
                binary=False,
                parser_factory=lambda content, filename: PythonParser().parse(content, filename=filename),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.SYMBOL,
            ),
            FormatHandler(
                format="word",
                extensions=(".docx",),
                tier="native",
                binary=True,
                parser_factory=lambda content, filename: WordParser().parse(content, filename=filename),
                graph_extractor=None,
                text_extractor=_word_text_extractor,
                locator_prefix=LocatorPrefix.HEADING,
            ),
            FormatHandler(
                format="pdf",
                extensions=(".pdf",),
                tier="native",
                binary=True,
                parser_factory=lambda content, filename: PDFParser().parse(content, filename=filename),
                graph_extractor=None,
                text_extractor=_pdf_text_extractor,
                locator_prefix=LocatorPrefix.PAGE,
            ),
            FormatHandler(
                format="txt",
                extensions=(".txt",),
                tier="native",
                binary=False,
                parser_factory=lambda content, filename: TxtParser().parse(content, filename=filename),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.HEADING,
            ),
            FormatHandler(
                format="csv",
                extensions=(".csv",),
                tier="converter",
                binary=False,
                converter_spec=ConverterSpec(
                    converter=MarkitdownConverter(),
                    chunk_slicer=slicers.csv_slicer,
                ),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.SHEET,
            ),
            FormatHandler(
                format="html",
                extensions=(".html", ".htm"),
                tier="converter",
                binary=False,
                converter_spec=ConverterSpec(
                    converter=MarkitdownConverter(),
                    chunk_slicer=slicers.markdown_structure_slicer,
                ),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.HEADING,
            ),
            FormatHandler(
                format="json",
                extensions=(".json",),
                tier="converter",
                binary=False,
                converter_spec=ConverterSpec(
                    converter=MarkitdownConverter(),
                    chunk_slicer=slicers.json_yaml_slicer,
                ),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.PATH,
            ),
            FormatHandler(
                format="yaml",
                extensions=(".yaml", ".yml"),
                tier="converter",
                binary=False,
                converter_spec=ConverterSpec(
                    converter=YamlAdapter(),
                    chunk_slicer=slicers.json_yaml_slicer,
                ),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.PATH,
            ),
            FormatHandler(
                format="xml",
                extensions=(".xml",),
                tier="converter",
                binary=False,
                converter_spec=ConverterSpec(
                    converter=MarkitdownConverter(),
                    chunk_slicer=slicers.xml_slicer,
                ),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.PATH,
            ),
            FormatHandler(
                format="xlsx",
                extensions=(".xlsx",),
                tier="converter",
                binary=True,
                converter_spec=ConverterSpec(
                    converter=MarkitdownConverter(extras=("xlsx",)),
                    chunk_slicer=slicers.xlsx_slicer,
                ),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.SHEET,
            ),
            FormatHandler(
                format="pptx",
                extensions=(".pptx",),
                tier="converter",
                binary=True,
                converter_spec=ConverterSpec(
                    converter=MarkitdownConverter(extras=("pptx",)),
                    chunk_slicer=slicers.markdown_structure_slicer,
                ),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.HEADING,
            ),
            FormatHandler(
                format="eml",
                extensions=(".eml",),
                tier="converter",
                binary=False,
                converter_spec=ConverterSpec(
                    converter=MarkitdownConverter(),
                    chunk_slicer=slicers.eml_slicer,
                ),
                graph_extractor=None,
                locator_prefix=LocatorPrefix.MSG,
            ),
        ]

        registry = cls(handlers)
        registry._validate_no_duplicates()
        return registry

    def _validate_no_duplicates(self) -> None:
        """Fail on duplicate format or extension (single source of truth)."""
        formats: set[str] = set()
        extensions: set[str] = set()
        for handler in self._handlers:
            if handler.format in formats:
                raise RegistryFormatError(f"duplicate format registration: {handler.format}")
            formats.add(handler.format)
            for ext in handler.extensions:
                if ext in extensions:
                    raise RegistryFormatError(f"duplicate extension registration: {ext}")
                extensions.add(ext)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "FormatHandlerRegistry":
        """Return the process-wide singleton (built on first use)."""
        if cls._instance is None:
            cls._instance = cls.build()
        return cls._instance

    def handlers(self) -> list[FormatHandler]:
        return list(self._handlers)

    def _by_format_or_raise(self, fmt: str) -> FormatHandler:
        handler = self._by_format.get(fmt)
        if handler is None:
            raise RegistryFormatError(
                f"Unsupported format {fmt!r}. " + _unsupported_message(self._accepted)
            )
        return handler

    def _check_converter_available(self, handler: FormatHandler) -> None:
        """Reject a converter-tier format when its converter dependency is missing (T016)."""
        if handler.tier == "converter" and handler.converter_spec is not None:
            converter = handler.converter_spec.converter
            if converter is not None and not converter.available():
                raise RegistryFormatError(f"converter unavailable: {handler.format}")

    # ------------------------------------------------------------------
    # Dispatch APIs (contracts/format-handler-registry.md §3)
    # ------------------------------------------------------------------

    def detect_format(self, filename: str, content: bytes | None = None) -> str:
        """Resolve a canonical format from a filename (and optional content).

        .json/.yaml/.yml sniff OpenAPI/Swagger first (FR-003); when the
        content is not OpenAPI the call falls back to the generic json/yaml
        converter entry when registered, otherwise raises.
        """
        ext = Path(filename).suffix.lower()

        if ext in (".json", ".yaml", ".yml"):
            if content is not None and _sniff_openapi(content, ext):
                return "openapi"
            generic = self._by_ext.get(ext)
            if generic is not None:
                self._check_converter_available(generic)
                return generic.format
            raise RegistryFormatError(
                f"Unsupported format: {filename}. " + _unsupported_message(self._accepted)
            )

        handler = self._by_ext.get(ext)
        if handler is None:
            raise RegistryFormatError(
                f"Unsupported format: {filename}. " + _unsupported_message(self._accepted)
            )

        # Extension/content mismatch guard for .go (spec edge case).
        if handler.format == "go" and content is not None:
            _check_go_package(content, filename)
        self._check_converter_available(handler)
        return handler.format

    def parse_content(self, content: Any, fmt: str, filename: str) -> list[dict[str, Any]]:
        """Parse (already redacted) content into chunk dicts.

        native -> parser_factory(content, filename);
        converter -> converter_spec.chunk_slicer(markdown_ir, fmt, filename).
        """
        handler = self._by_format_or_raise(fmt)
        if handler.tier == "native":
            assert handler.parser_factory is not None
            return handler.parser_factory(content, filename)
        assert handler.converter_spec is not None
        assert handler.converter_spec.chunk_slicer is not None
        return handler.converter_spec.chunk_slicer(content, fmt, filename)

    def to_text(self, raw_bytes: bytes, fmt: str, filename: str) -> str:
        """Convert raw bytes to text (the zhuan-wenben step, before redaction).

        converter tier -> converter.convert (Markdown IR);
        native binary -> extract_text; native text -> UTF-8 decode.
        """
        handler = self._by_format_or_raise(fmt)
        if handler.tier == "converter":
            assert handler.converter_spec is not None
            assert handler.converter_spec.converter is not None
            return handler.converter_spec.converter.convert(raw_bytes, fmt, filename)
        if handler.binary:
            assert handler.text_extractor is not None
            return handler.text_extractor(raw_bytes)
        return raw_bytes.decode("utf-8", errors="replace")

    def is_binary(self, fmt: str) -> bool:
        return self._by_format_or_raise(fmt).binary

    def is_converter(self, fmt: str) -> bool:
        return self._by_format_or_raise(fmt).tier == "converter"

    def graph_extractor(self, fmt: str) -> Callable[..., Any] | None:
        """Return the format's graph-extractor factory, or None when no hook."""
        return self._by_format_or_raise(fmt).graph_extractor


# ---------------------------------------------------------------------------
# Frozen native graph-extractor factories (lazy: graph deps are heavy)
# ---------------------------------------------------------------------------

def _java_graph_extractor():
    from rag_mcp.graph.extractors.java_call_graph import JavaCallGraphExtractor

    return JavaCallGraphExtractor()


def _ddl_graph_extractor():
    from rag_mcp.graph.extractors.ddl_fk import DdlFkExtractor

    return DdlFkExtractor()


def _word_text_extractor(raw_bytes):
    from rag_mcp.parsers.text_extractor import _extract_word_text

    return _extract_word_text(raw_bytes)


def _pdf_text_extractor(raw_bytes):
    from rag_mcp.parsers.text_extractor import _extract_pdf_text

    return _extract_pdf_text(raw_bytes)


# ---------------------------------------------------------------------------
# Content sniffing helpers (FR-003)
# ---------------------------------------------------------------------------

def _sniff_openapi(content: bytes, ext: str) -> bool:
    """True when content is an OpenAPI 3.x / Swagger 2.0 object."""
    text = content.decode("utf-8", errors="replace")
    try:
        if ext == ".json":
            import json

            data = json.loads(text)
        else:
            import yaml

            data = yaml.safe_load(text)
    except Exception:
        return False
    return isinstance(data, dict) and ("openapi" in data or "swagger" in data)


def _check_go_package(content: bytes, filename: str) -> None:
    """Reject a .go file whose content lacks a Go package declaration."""
    text = content.decode("utf-8", errors="replace")
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]
    if not any(
        line.lower().startswith("package ") or line.lower() == "package"
        for line in lines[:5]
    ):
        raise RegistryFormatError(
            f"File '{filename}' has .go extension but content does not "
            f"contain a Go package declaration. This appears to be a "
            f"format mismatch (extension/content mismatch)."
        )
