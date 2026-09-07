"""Source-level guard: graph_edge writes only via write_edges (010, T059).

FR-009 / SC-006 / research R5: PostgresGraphStore.write_edges is the single
vocabulary-validation chokepoint for graph_edge (allowed_relation_types +
reserved-word blacklist). This guard scans the production source tree so any
future direct write - a raw INSERT INTO graph_edge, an ORM GraphEdge(...)
construction, or a SQLAlchemy insert(GraphEdge) bulk statement outside the
store - fails CI instead of silently bypassing the domain-vocabulary check.

Production scope only: test fixtures legitimately construct GraphEdge /
INSERT INTO graph_edge and are not scanned (they are not the runtime write
path). Precedent for source-level guards:
test_graph_expansion_vocab.test_no_bidirectional_default_constant.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _REPO_ROOT / "backend" / "src" / "rag_mcp"

# The ORM model module owns the GraphEdge class definition and __repr__.
_ORM_MODEL_MODULE = "graph/models.py"
# The store module owns the only runtime INSERT INTO graph_edge (write_edges).
_STORE_MODULE = "graph/store/postgres_graph_store.py"


def _production_py_files() -> list[Path]:
    files = sorted(_SRC_ROOT.rglob("*.py"))
    assert files, f"production source tree not found at {_SRC_ROOT}"
    return files


def _normalized(content: str) -> str:
    """Collapse whitespace so multi-line SQL cannot evade the guard."""
    return re.sub(r"\s+", " ", content)


def test_raw_graph_edge_insert_only_in_store():
    offenders: list[str] = []
    for f in _production_py_files():
        rel = f.relative_to(_SRC_ROOT).as_posix()
        content = _normalized(f.read_text(encoding="utf-8"))
        if "INSERT INTO graph_edge" in content and rel != _STORE_MODULE:
            offenders.append(rel)
    assert not offenders, (
        "Raw INSERT INTO graph_edge found outside the store chokepoint: "
        f"{offenders}. All runtime graph_edge writes must flow through "
        "PostgresGraphStore.write_edges so the domain-vocabulary check "
        "(allowed_relation_types) is enforced (FR-009/SC-006, research R5)."
    )


def test_orm_graph_edge_construction_only_in_models():
    offenders: list[str] = []
    pattern = re.compile(r"GraphEdge\s*\(")
    for f in _production_py_files():
        rel = f.relative_to(_SRC_ROOT).as_posix()
        content = f.read_text(encoding="utf-8")
        if pattern.search(content) and rel != _ORM_MODEL_MODULE:
            offenders.append(rel)
    assert not offenders, (
        f"ORM GraphEdge construction found outside {_ORM_MODEL_MODULE}: "
        f"{offenders}. Constructing GraphEdge directly (and session.add-ing "
        "it) bypasses PostgresGraphStore.write_edges vocabulary validation "
        "(FR-009/SC-006, research R5)."
    )


def test_no_sqlalchemy_bulk_insert_of_graph_edge():
    offenders: list[str] = []
    pattern = re.compile(r"insert\s*\(\s*GraphEdge")
    for f in _production_py_files():
        rel = f.relative_to(_SRC_ROOT).as_posix()
        content = f.read_text(encoding="utf-8")
        if pattern.search(content):
            offenders.append(rel)
    assert not offenders, (
        f"SQLAlchemy insert(GraphEdge) bulk-write found: {offenders}. "
        "graph_edge writes must flow through PostgresGraphStore.write_edges."
    )
