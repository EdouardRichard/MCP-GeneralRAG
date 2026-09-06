"""Document cross-reference hard-relation extractor (010, T028-T032).

Deterministically extracts references/referenced_by hard edges from Markdown
documents: internal anchor links [text](#anchor), relative links
[text](path.md#anchor), and Chinese/point-number clause references
(依据第X条 / 参见X.Y). Hybrid anchoring (research R10): the source endpoint is
resolved by line-number interval, the target endpoint by section_path last-segment
heading match. Rules follow contracts/cross-reference-extraction.md.

Precision-first (Constitution III/IV): only determinable references produce
edges; a trigger-word + resolvable-target double confirmation suppresses
narrative false positives (research R7.3).
"""
from __future__ import annotations

import re
from typing import Any

from rag_mcp.graph.extractors.base import GraphExtractor

logger = __import__("logging").getLogger(__name__)

# Trigger verbs that MUST precede a clause reference (R7.2 white-list).
_TRIGGER_WORDS = ("依据", "根据", "依照", "按照", "参照", "参见", "见", "转致", "援引")
_TRIGGER_RE = re.compile("(" + "|".join(_TRIGGER_WORDS) + ")")

_CN_NUM = "一二三四五六七八九十百零两"
# Chinese clause number: 第X条.
_CN_CLAUSE_RE = re.compile("第[" + _CN_NUM + "]+条")
# Point-number clause: 4.2 / 4.2.1 (numbered documents).
_DOT_CLAUSE_RE = re.compile(r"\d+(?:\.\d+)+")
# Range reference: 第X条至第Y条 / 第X条-第Y条 (explicitly excluded, no edge).
_RANGE_RE = re.compile(r"第[" + _CN_NUM + r"]+条\s*(?:至|到|-|—)\s*第[" + _CN_NUM + r"]+条")

# Markdown link: [text](url) — with optional leading ! (image) captured.
_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")

_EXT_LINK_PREFIXES = ("http://", "https://", "mailto:", "ftp://")
_FENCE = chr(96) * 3  # markdown fenced code block marker


def _normalize_heading(text: str) -> str:
    """Normalize a heading/anchor for comparison (contract §2.2).

    ASCII lowercase; whitespace -> -; strip markdown markers (# * _ and
    backtick) and common punctuation; CJK characters are preserved.
    """
    text = text.strip()
    text = text.lstrip("#").strip()
    text = text.replace(chr(96), "")  # backtick
    text = re.sub(r"[*_]", "", text)
    text = text.lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w\u4e00-\u9fff-]", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def _percent_encode(value: str) -> str:
    """Percent-encode : and = inside a locator field (contract §4)."""
    return value.replace("%", "%25").replace(":", "%3A").replace("=", "%3D")


def _locator(kind: str, **fields: str) -> str:
    order = {
        "internal": ("anchor", "text", "line"),
        "relative": ("file", "anchor", "text", "line"),
        "clause": ("ref", "marker", "line"),
    }.get(kind, tuple(fields.keys()))
    parts = [kind]
    for key in order:
        if key in fields:
            parts.append(key + "=" + _percent_encode(str(fields[key])))
    return "xref:" + ":".join(parts)


class CrossReferenceExtractor(GraphExtractor):
    """Markdown references/referenced_by cross-reference extractor (010)."""

    format = "markdown"
    relation_pairs = {"references": "referenced_by"}
    chunk_scope = "scope"

    def extract(self, source, chunks, scope):
        if not source or not source.strip():
            return []

        current_chunks = [c for c in chunks if c.get("is_current")]
        by_filename = {}
        for c in chunks:
            by_filename.setdefault(c.get("filename") or "", []).append(c)

        edges = []
        seen = set()

        lines = source.split("\n")
        in_fence = False
        for line_idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith(_FENCE) or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue

            for m in _LINK_RE.finditer(line):
                is_image, text, url = m.group(1), m.group(2), m.group(3)
                if is_image:
                    continue
                if url.startswith(_EXT_LINK_PREFIXES):
                    continue
                if not text.strip():
                    continue
                if _inside_inline_code(line, m.start()):
                    continue
                if url.startswith("#"):
                    self._add_internal(edges, seen, text, url[1:], line_idx, current_chunks, scope)
                else:
                    self._add_relative(edges, seen, text, url, line_idx, current_chunks, by_filename, scope)

            if not _TRIGGER_RE.search(line):
                continue
            if _RANGE_RE.search(line):
                continue
            trigger = _TRIGGER_RE.search(line).group(1)
            for clause in self._iter_clauses(line):
                target = self._resolve_clause(clause, chunks)
                if target is None:
                    continue
                src = _find_source_chunk(line_idx, current_chunks)
                if src is None:
                    continue
                self._emit(edges, seen, src, target, "clause", scope,
                           ref=clause, marker=trigger, line=line_idx)

        return edges

    def _add_internal(self, edges, seen, text, anchor, line_idx, current_chunks, scope):
        target = _resolve_heading(anchor, current_chunks)
        if target is None:
            return
        src = _find_source_chunk(line_idx, current_chunks)
        if src is None:
            return
        self._emit(edges, seen, src, target, "internal", scope,
                   anchor=anchor, text=text, line=line_idx)

    def _add_relative(self, edges, seen, text, url, line_idx, current_chunks, by_filename, scope):
        path, _, anchor = url.partition("#")
        basename = path.rsplit("/", 1)[-1]
        if not basename:
            return
        file_chunks = by_filename.get(basename)
        if file_chunks is None:
            return
        if anchor:
            target = _resolve_heading(anchor, file_chunks)
        else:
            target = _first_heading_chunk(file_chunks)
        if target is None:
            return
        src = _find_source_chunk(line_idx, current_chunks)
        if src is None:
            return
        self._emit(edges, seen, src, target, "relative", scope,
                   file=basename, anchor=anchor or "-", text=text, line=line_idx)

    @staticmethod
    def _iter_clauses(line):
        clauses = []
        for m in _CN_CLAUSE_RE.finditer(line):
            clauses.append(m.group(0))
        for m in _DOT_CLAUSE_RE.finditer(line):
            clauses.append(m.group(0))
        return clauses

    def _resolve_clause(self, clause, chunks):
        normalized = _normalize_heading(clause)
        for c in chunks:
            heading = c.get("heading") or ""
            norm_heading = _normalize_heading(str(heading))
            if norm_heading == normalized or norm_heading.startswith(normalized):
                return c
        return None

    def _emit(self, edges, seen, src, tgt, kind, scope, **locator_fields):
        if src.get("chunk_id") == tgt.get("chunk_id"):
            return
        locator = _locator(kind, **locator_fields)
        pe = {"source_format": "markdown", "extractor": "cross_reference", "locator": locator}
        fwd = self._make_edge(src, tgt, "references", scope, pe)
        rev = self._make_edge(tgt, src, "referenced_by", scope, pe)
        for edge in (fwd, rev):
            key = _edge_key(edge)
            if key not in seen:
                seen.add(key)
                edges.append(edge)

    @staticmethod
    def _make_edge(src, tgt, relation_type, scope, pe):
        return {
            "source_chunk_id": src["chunk_id"],
            "target_chunk_id": tgt["chunk_id"],
            "relation_type": relation_type,
            "direction": "out",
            "is_hard": True,
            "version": 1,
            "knowledge_scope_id": scope.knowledge_scope_id,
            "index_version": scope.index_version,
            "parse_evidence": pe,
        }


def _inside_inline_code(line: str, pos: int) -> bool:
    """True when the match at pos sits inside a backtick inline-code span."""
    backticks = 0
    for i in range(pos):
        if line[i] == chr(96):
            backticks += 1
    return backticks % 2 == 1


def _find_source_chunk(line_num: int, chunks):
    for c in chunks:
        start = c.get("start_line")
        end = c.get("end_line")
        if start is None or end is None:
            continue
        if start <= line_num <= end:
            return c
    return None


def _resolve_heading(anchor: str, chunks):
    norm_anchor = _normalize_heading(anchor)
    for c in chunks:
        heading = c.get("heading") or ""
        if (anchor and str(heading).strip() == anchor.strip()) or (_normalize_heading(str(heading)) == norm_anchor):
            return c
    return None


def _first_heading_chunk(chunks):
    for c in chunks:
        if c.get("heading"):
            return c
    return None


def _edge_key(edge):
    return (
        edge.get("source_chunk_id"),
        edge.get("target_chunk_id"),
        edge.get("relation_type"),
        edge.get("direction"),
    )
