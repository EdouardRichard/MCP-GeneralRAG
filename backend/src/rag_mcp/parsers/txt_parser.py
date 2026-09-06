"""TXT lightweight native parser (008, FR-010/FR-011/FR-012).

Splits plain text on blank lines into paragraph chunks (chunk_type=paragraph)
with a document-level locator (empty section_path; position is carried by
filename + start/end line). Over-long paragraphs are re-split at natural
boundaries (sentences/newlines) toward the 512-1024 token target.
"""

from __future__ import annotations

import re
from typing import Any

_TARGET_MAX = 1024


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _split_long_paragraph(text: str) -> list[str]:
    """Re-split an over-long paragraph at sentence boundaries."""
    if _estimate_tokens(text) <= _TARGET_MAX:
        return [text]
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    parts: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if current and _estimate_tokens(" ".join(current + [sentence])) > _TARGET_MAX:
            parts.append(" ".join(current))
            current = [sentence]
        else:
            current.append(sentence)
    if current:
        parts.append(" ".join(current))
    return parts or [text]


class TxtParser:
    """Blank-line paragraph parser for plain-text (.txt) files."""

    def parse(self, content: str, filename: str = "") -> list[dict[str, Any]]:
        if not content or not content.strip():
            return []
        lines = content.split("\n")
        chunks: list[dict[str, Any]] = []
        current: list[str] = []
        current_start: int | None = None

        def flush() -> None:
            nonlocal current, current_start
            if current:
                para = "\n".join(current).strip()
                if para:
                    for sub in _split_long_paragraph(para):
                        chunks.append({
                            "content_text": sub,
                            "position_path": "",
                            "parent_position_path": "",
                            "chunk_type": "paragraph",
                            "start_line": current_start or 1,
                            "end_line": (current_start or 1) + len(current) - 1,
                            "token_count": _estimate_tokens(sub),
                        })
            current = []
            current_start = None

        for i, raw in enumerate(lines):
            line = raw.rstrip("\n")
            if not line.strip():
                flush()
                continue
            if current_start is None:
                current_start = i + 1
            current.append(line)
        flush()
        return chunks
