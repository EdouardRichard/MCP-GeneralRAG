"""Chunk slicers for converter-tier formats (008, FR-010/FR-011).

Each slicer converts a Markdown IR (already credential-redacted) into chunk
dicts carrying L1 chunk types and the evidence locator (position_path).
All slicers share the chunk-dict contract of data-model.md §3 and produce no
chunks for empty/meaningless input (FR-015 "no chunk then fail").
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _chunk(
    content_text: str,
    position_path: str,
    chunk_type: str,
    start_line: int,
    end_line: int,
    parent_position_path: str = "",
) -> dict[str, Any]:
    return {
        "content_text": content_text,
        "position_path": position_path,
        "parent_position_path": parent_position_path,
        "chunk_type": chunk_type,
        "start_line": start_line,
        "end_line": end_line,
        "token_count": _estimate_tokens(content_text),
    }


# ---------------------------------------------------------------------------
# Markdown structure slicer (html / pptx) — heading/paragraph/list/table blocks
# ---------------------------------------------------------------------------

def markdown_structure_slicer(markdown_ir: str, fmt: str, filename: str) -> list[dict[str, Any]]:
    """Slice Markdown IR into L1 blocks with '#' heading-path locators."""
    lines = markdown_ir.split("\n")
    chunks: list[dict[str, Any]] = []
    heading_stack: list[str] = []
    block_type: str | None = None
    buffer: list[str] = []
    start: int | None = None

    def flush() -> None:
        nonlocal block_type, buffer, start
        if buffer:
            text = "\n".join(buffer).strip()
            if text:
                path = " > ".join(heading_stack)
                chunks.append(_chunk(
                    text, path, block_type or "paragraph",
                    start or 1, (start or 1) + len(buffer) - 1,
                ))
        buffer = []
        start = None
        block_type = None

    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--"):
            if not stripped:
                flush()
            continue

        if stripped.startswith("#"):
            flush()
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
            while heading_stack and heading_stack[-1].startswith("#" * level):
                heading_stack.pop()
            heading_stack.append("#" * level + " " + title)
            block_type = "heading"
            buffer = [stripped]
            start = i + 1
        elif stripped.startswith("|"):
            if block_type != "table":
                flush()
            block_type = "table"
            buffer.append(line)
            start = start if start is not None else i + 1
        elif stripped.startswith(("-", "*", "+")) or re.match(r"^\d+[.)]\s", stripped):
            if block_type != "list":
                flush()
            block_type = "list"
            buffer.append(line)
            start = start if start is not None else i + 1
        else:
            if block_type not in (None, "paragraph"):
                flush()
            block_type = "paragraph"
            buffer.append(line)
            start = start if start is not None else i + 1
    flush()
    return chunks


# ---------------------------------------------------------------------------
# CSV row-window slicer
# ---------------------------------------------------------------------------

def csv_slicer(markdown_ir: str, fmt: str, filename: str) -> list[dict[str, Any]]:
    """Slice a CSV pipe-table IR into 50-row table chunks (sheet:<basename>)."""
    rows = [
        line for line in markdown_ir.split("\n")
        if line.strip() and not line.strip().startswith("---")
    ]
    rows = [r for r in rows if not re.match(r"^\s*\|?\s*:?-+", r)]
    if not rows:
        return []
    basename = Path(filename).stem
    chunks: list[dict[str, Any]] = []
    header = rows[0]
    data = rows[1:]
    window = 50
    for i in range(0, len(data), window):
        block = [header] + data[i:i + window]
        start_line = i + 2
        end_line = start_line + len(block) - 1
        chunks.append(_chunk(
            "\n".join(block), f"sheet:{basename}", "table", start_line, end_line,
        ))
    return chunks


# ---------------------------------------------------------------------------
# JSON / YAML key-path slicer
# ---------------------------------------------------------------------------

def json_yaml_slicer(markdown_ir: str, fmt: str, filename: str) -> list[dict[str, Any]]:
    """Slice JSON(-equivalent) IR by top-level key path (path:/key)."""
    text = markdown_ir.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except Exception as exc:
        raise ValueError(f"invalid JSON for {filename}: {exc}") from exc
    if not isinstance(data, dict):
        data = {"root": data}
    chunks: list[dict[str, Any]] = []
    for key, value in data.items():
        serialized = json.dumps({key: value}, indent=2, ensure_ascii=False)
        chunks.append(_chunk(
            serialized, f"path:/{key}", "paragraph", 1, serialized.count(chr(10)) + 1,
        ))
    return chunks


# ---------------------------------------------------------------------------
# XML element-path slicer
# ---------------------------------------------------------------------------

def xml_slicer(markdown_ir: str, fmt: str, filename: str) -> list[dict[str, Any]]:
    """Slice XML IR by top-level element path (path:/elem)."""
    text = markdown_ir.strip()
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except Exception as exc:
        raise ValueError(f"invalid XML for {filename}: {exc}") from exc
    chunks: list[dict[str, Any]] = []
    for child in root:
        block = ET.tostring(child, encoding="unicode")
        tag = child.tag.split("}")[-1]
        chunks.append(_chunk(block, f"path:/{tag}", "paragraph", 1, block.count(chr(10)) + 1))
    if not chunks:
        chunks.append(_chunk(text, "path:/" + root.tag.split("}")[-1], "paragraph", 1, text.count(chr(10)) + 1))
    return chunks


# ---------------------------------------------------------------------------
# XLSX sheet slicer
# ---------------------------------------------------------------------------

def xlsx_slicer(markdown_ir: str, fmt: str, filename: str) -> list[dict[str, Any]]:
    """Slice XLSX IR ('## SheetN' + pipe tables) into per-sheet table chunks."""
    chunks: list[dict[str, Any]] = []
    current_sheet: str | None = None
    current_lines: list[str] = []
    current_start: int | None = None

    def flush() -> None:
        nonlocal current_sheet, current_lines, current_start
        if current_sheet is not None and current_lines:
            text = "\n".join(current_lines).strip()
            if text:
                chunks.append(_chunk(
                    text, f"sheet:{current_sheet}", "table",
                    current_start or 1, (current_start or 1) + len(current_lines) - 1,
                ))
        current_lines = []
        current_start = None

    for i, raw in enumerate(markdown_ir.split("\n")):
        line = raw.rstrip("\n")
        stripped = line.strip()
        if stripped.startswith("##"):
            flush()
            current_sheet = stripped.lstrip("#").strip()
            current_start = i + 1
        elif stripped:
            current_lines.append(line)
            current_start = current_start if current_start is not None else i + 1
        else:
            flush()
    flush()
    return chunks


# ---------------------------------------------------------------------------
# EML slicer (headers + body, msg:<Subject>)
# ---------------------------------------------------------------------------

_EML_KEEP_HEADERS = ("From", "To", "Subject", "Date")


def eml_slicer(markdown_ir: str, fmt: str, filename: str) -> list[dict[str, Any]]:
    """Slice EML IR into a paragraph chunk keeping header field names + body."""
    lines = markdown_ir.split("\n")
    subject = filename
    headers: list[str] = []
    body_start = 0
    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        if line.strip() == "":
            body_start = i + 1
            break
        if ":" in line:
            name, _, value = line.partition(":")
            if name.strip() in _EML_KEEP_HEADERS:
                headers.append(line)
                if name.strip() == "Subject":
                    subject = value.strip() or subject
    body = "\n".join(lines[body_start:]).strip()
    if not headers and not body:
        return []
    parts = headers + ([body] if body else [])
    text = "\n".join(parts).strip()
    return [_chunk(text, f"msg:{subject}", "paragraph", 1, len(lines))]
