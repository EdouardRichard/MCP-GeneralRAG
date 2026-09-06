"""GraphExtractor plugin interface + graph relation registry (010, T001/T002).

Formalizes the 004 duck-typing extractor contract into a GraphExtractor ABC
(format / relation_pairs / chunk_scope declarations + extract(source, chunks,
scope) -> list[edge]) and a deterministic graph relation registry that
discovers extractors by (format x domain graph-relations vocabulary)
intersection (graph-extractor-registry.md §1/§3, research R1-R3/R8-R9).

The registry supersedes the 008 FormatHandlerRegistry.graph_extractor single
value hook (R2): a format may host multiple extractors distinguished by the
requesting domain's vocabulary. Build failures raise at startup (008 §5).
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Mapping

RELATION_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class GraphExtractor(ABC):
    """Deterministic hard-relation extractor plugin interface (FR-001).

    Subclasses declare the source format they consume, the reciprocal relation
    pairs they produce, and the chunk scope they resolve against:
      * chunk_scope = "source": only the current knowledge source's chunks
        (java/ddl — behavior unchanged from 004).
      * chunk_scope = "scope":  the full scope chunk index (cross_reference,
        cross-file relative links). Each chunk dict carries an extra
        'filename' key injected by orchestration.
    """

    format: str
    relation_pairs: Mapping[str, str]
    chunk_scope: str = "source"

    @abstractmethod
    def extract(self, source: str, chunks: list[dict[str, Any]], scope: Any) -> list[dict[str, Any]]:
        """Deterministically extract hard-relation edges.

        MUST be deterministic and free of LLM/network calls; MAY raise on
        internal failure (orchestration degrades); indeterminable relations
        MUST NOT be produced (Constitution III).
        """
        raise NotImplementedError


class GraphExtractorRegistry:
    """Deterministic registry: format x domain-vocabulary discovery (FR-002).

    Read-only process singleton; build failures (invalid declarations) raise
    at startup (008 §5 / Constitution VI).
    """

    _instance: "GraphExtractorRegistry | None" = None

    def __init__(self, extractor_classes: list[type[GraphExtractor]]) -> None:
        self._extractor_classes = list(extractor_classes)
        self._by_format: dict[str, list[type[GraphExtractor]]] = {}
        self._validate()
        for cls in self._extractor_classes:
            self._by_format.setdefault(cls.format, []).append(cls)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(cls) -> "GraphExtractorRegistry":
        """Build the registry from the builtin extractor set (declaration order)."""
        from rag_mcp.graph.extractors.cross_reference import CrossReferenceExtractor
        from rag_mcp.graph.extractors.ddl_fk import DdlFkExtractor
        from rag_mcp.graph.extractors.java_call_graph import JavaCallGraphExtractor

        return cls([
            JavaCallGraphExtractor,
            DdlFkExtractor,
            CrossReferenceExtractor,
        ])

    @classmethod
    def instance(cls) -> "GraphExtractorRegistry":
        """Return the process-wide singleton (built on first use)."""
        if cls._instance is None:
            cls._instance = cls.build()
        return cls._instance

    # ------------------------------------------------------------------
    # Registration validation (build failure = startup failure)
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        aggregate: dict[str, str] = {}
        seen_formats: set[str] = set()
        for cls in self._extractor_classes:
            if not isinstance(cls.format, str) or not cls.format:
                raise ValueError(
                    f"GraphExtractor {cls.__name__} must declare a non-empty format"
                )
            pairs = dict(cls.relation_pairs or {})
            if not pairs:
                raise ValueError(
                    f"GraphExtractor {cls.__name__} must declare at least one relation pair"
                )
            for key, value in pairs.items():
                if not RELATION_TYPE_PATTERN.match(key):
                    raise ValueError(
                        f"GraphExtractor {cls.__name__} relation key {key!r} "
                        f"does not match wide pattern"
                    )
                if not RELATION_TYPE_PATTERN.match(value):
                    raise ValueError(
                        f"GraphExtractor {cls.__name__} relation value {value!r} "
                        f"does not match wide pattern"
                    )
                # A single-entry declaration {"calls": "called_by"} is the
                # canonical reciprocal pair (the inverse is implied). The check
                # only rejects a NON-inverse declaration: when the inverse value
                # is itself declared as a key, it MUST round-trip back to key.
                if pairs.get(value, key) != key:
                    raise ValueError(
                        f"GraphExtractor {cls.__name__} relation pair "
                        f"{key!r} <-> {value!r} is not mutually inverse "
                        f"(single-sided or non-inverse declarations are rejected)"
                    )
                if key in aggregate and aggregate[key] != value:
                    raise ValueError(
                        f"relation key {key!r} conflicts across extractors "
                        f"({aggregate[key]!r} vs {value!r})"
                    )
                aggregate[key] = value
                if value in aggregate and aggregate[value] != key:
                    raise ValueError(
                        f"relation key {value!r} conflicts across extractors "
                        f"({aggregate[value]!r} vs {key!r})"
                    )
                aggregate[value] = key
            seen_formats.add(cls.format)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(
        self,
        format: str,
        graph_relations: Mapping[str, Any] | None,
    ) -> list[GraphExtractor]:
        """Return extractors whose relation_pairs keys intersect the domain vocab.

        Deterministic (declaration order); empty vocab or no intersection
        returns [] (normal skip, not an error). Returns fresh instances.
        """
        vocab = set((graph_relations or {}).keys())
        result: list[GraphExtractor] = []
        for cls in self._by_format.get(format, []):
            if set(cls.relation_pairs.keys()) & vocab:
                result.append(cls())
        return result

    def inverse_relation_map(self) -> dict[str, str]:
        """Aggregate the reciprocal mapping of every registered pair (R9)."""
        mapping: dict[str, str] = {}
        for cls in self._extractor_classes:
            for key, value in cls.relation_pairs.items():
                mapping[key] = value
                mapping[value] = key
        return mapping
