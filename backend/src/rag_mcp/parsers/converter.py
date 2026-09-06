"""Pluggable converter interface + markitdown adapter (008, FR-009).

Defines the Converter protocol, the markitdown-backed MarkitdownConverter,
the YAML -> JSON-equivalent YamlAdapter (markitdown has no native YAML
converter, research §2.5), and a NoopConverter placeholder for future
pandoc/tika-equivalent replacements.

Converters are lazy: they import markitdown only on first convert so a
missing optional dependency fails at detection/upload time with a
"converter unavailable" message (FR-003/FR-015), never at registry build
time (so a missing converter does not fail startup — that is reserved for
frozen native parser import failures).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Protocol


class ConverterError(ValueError):
    """Raised when conversion fails or produces empty output (FR-015)."""


class ConverterUnavailableError(ConverterError):
    """Raised when a converter's optional dependency is not installed."""


class Converter(Protocol):
    """Contract for a pluggable format converter (contracts/format-handler-registry.md §2).

    convert(raw_bytes, format, filename) -> str returns the Markdown IR.
    Failure or empty output MUST raise (never return an empty string or
    fabricate content).
    """

    def convert(self, raw_bytes: bytes, format: str, filename: str) -> str: ...

    def available(self) -> bool: ...


class MarkitdownConverter:
    """Wraps markitdown's MarkItDown.convert for arbitrary formats (FR-009).

    Args:
        extras: informational tuple of markitdown extras this converter
            relies on (e.g. ("xlsx", "pptx")). Used only for diagnostics;
            the actual dependency is imported lazily.
    """

    def __init__(self, extras: tuple[str, ...] = ()) -> None:
        self._extras = extras

    def available(self) -> bool:
        try:
            import markitdown  # noqa: F401

            return True
        except ImportError:
            return False

    def convert(self, raw_bytes: bytes, format: str, filename: str) -> str:
        """Convert raw bytes to Markdown IR (FR-009).

        Uses the filename extension as a routing hint (StreamInfo) so formats
        that magika misdetects still reach the correct markitdown converter.
        Binary extras (xlsx/pptx) are ZIP archives; a non-ZIP payload is
        rejected here as corrupted/unparseable instead of letting markitdown
        silently degrade to plain text and losing the reason (T054, FR-015).
        """
        if self._extras and not raw_bytes.startswith(b"PK"):
            raise ConverterError(
                f"corrupted/unparseable {format} file ({filename}): not a valid archive"
            )
        try:
            from markitdown import MarkItDown
            from markitdown._stream_info import StreamInfo
        except ImportError as exc:
            raise ConverterUnavailableError(
                f"converter unavailable: {format}"
            ) from exc

        ext = Path(filename).suffix.lower()
        stream_info = StreamInfo(extension=ext, filename=filename)
        md = MarkItDown()
        try:
            result = md.convert(io.BytesIO(raw_bytes), stream_info=stream_info)
        except Exception as exc:  # noqa: BLE001 - surface the real cause
            raise ConverterError(
                f"conversion failed for {format} ({filename}): {type(exc).__name__}: {exc}"
            ) from exc

        text = getattr(result, "text_content", None) if result is not None else None
        if not text or not text.strip():
            raise ConverterError(
                f"conversion produced empty output for {format} ({filename}) (FR-015)"
            )
        return text


class NoopConverter:
    """Placeholder converter for future pandoc/tika-equivalent replacements."""

    def available(self) -> bool:
        return False

    def convert(self, raw_bytes: bytes, format: str, filename: str) -> str:
        raise ConverterUnavailableError(f"converter unavailable: {format}")


class YamlAdapter:
    """YAML -> dict -> JSON-equivalent Markdown IR (research §2.5).

    markitdown has no native YAML converter, so YAML shares the JSON
    conversion path: parse with pyyaml, then serialize as indented JSON so the
    json/yaml key-path slicer (path:/key) applies unchanged.
    """

    def available(self) -> bool:
        try:
            import yaml  # noqa: F401

            return True
        except ImportError:
            return False

    def convert(self, raw_bytes: bytes, format: str, filename: str) -> str:
        try:
            import yaml
        except ImportError as exc:
            raise ConverterUnavailableError(
                f"converter unavailable: {format} (pyyaml missing)"
            ) from exc
        import json

        text = raw_bytes.decode("utf-8", errors="replace")
        try:
            data = yaml.safe_load(text)
        except Exception as exc:
            raise ConverterError(
                f"yaml parse failed for {filename}: {type(exc).__name__}: {exc}"
            ) from exc
        if data is None:
            raise ConverterError(f"yaml produced no data for {filename} (FR-015)")
        return json.dumps(data, indent=2, ensure_ascii=False)
