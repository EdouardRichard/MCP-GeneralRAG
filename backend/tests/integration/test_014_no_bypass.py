"""T041/T046 — no-bypass inventory for the consumption layer (US6).

The whole file runs without PostgreSQL or Qdrant: static (AST) inventory plus
file-system assertions. The consumption layer must have no write entrance that
skips the reducer-state gate, no event append, no public write API, and no
dependency on the 012 revision store.
"""

from __future__ import annotations

import ast
import os
import re
import stat
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "rag_mcp"
CONSUMPTION_MODULE = SRC / "runtime" / "memory_projection.py"
PROJECTION_STORE = SRC / "services" / "memory_projection_store.py"

#: Filesystem publication calls; every call site must live inside a private
#: helper, a ``ConsumptionGuard`` method, or one of the guarded entry points below.
WRITE_CALLS = {"write_bytes", "write_text", "unlink", "rmtree", "chmod"}
#: The only public write entrance points (each takes reducer state/scope, never
#: an arbitrary path and never an arbitrary body). ``_worker`` may be reached
#: only through ``mark_memory_projection_dirty``.
GUARDED_ENTRY_POINTS = {"apply_tree", "apply_tree_state", "rebuild", "remove_scope", "_worker",
                        "write_file", "write_tree", "lock_file", "upsert_metadata", "reconcile"}
#: Total inventory of functions that may touch published bytes. Any new name
#: here is a deliberate contract change, so the list is asserted exhaustively.
PUBLICATION_FUNCTIONS = {
    "write_file", "write_tree", "lock_file", "_publish", "_resolve_scope_dir",
    "remove_scope", "_clear_readonly", "_make_dirs",
}


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_source(path))


def _call_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Attribute):
        return function.attr
    if isinstance(function, ast.Name):
        return function.id
    return ""


def _ancestors(tree: ast.Module):
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _enclosing_function(parents, node):
    current = parents.get(id(node))
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = parents.get(id(current))
    return None


def test_consumption_module_never_calls_the_projection_store_upsert():
    tree = _tree(CONSUMPTION_MODULE)
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and _call_name(node) == "_upsert"]
    assert calls == [], "the consumption layer must never reach MemoryProjectionStore._upsert"


def test_consumption_module_appends_no_authority_events():
    tree = _tree(CONSUMPTION_MODULE)
    source = _source(CONSUMPTION_MODULE)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == "append":
            target = node.func.value
            name = getattr(target, "id", getattr(target, "attr", ""))
            assert name not in {"events", "session", "self"}, "the consumption layer must never append authority events"
    assert "MemoryEventStore" not in source, "no second authority-log entrance may exist"
    assert "MemoryEvent(" not in source


def test_consumption_module_does_not_import_or_touch_the_revision_store():
    source = _source(CONSUMPTION_MODULE)
    assert "memory_projection_store" not in source
    assert "MemoryProjectionStore" not in source
    assert "_materialize_" not in source
    assert "memory_projection_meta" not in source


def test_consumption_module_has_no_unguarded_public_write_api():
    tree = _tree(CONSUMPTION_MODULE)
    parents = _ancestors(tree)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) not in WRITE_CALLS:
            continue
        function = _enclosing_function(parents, node)
        if function is None:  # module-level write: always a bypass
            offenders.append((node.lineno, "<module>", _call_name(node)))
            continue
        if function.name.startswith("_") or function.name in GUARDED_ENTRY_POINTS:
            continue
        offenders.append((node.lineno, function.name, _call_name(node)))
    assert offenders == [], f"unguarded write call sites: {offenders}"


def test_every_write_entrance_is_a_guard_method_or_private_helper():
    tree = _tree(CONSUMPTION_MODULE)
    parents = _ancestors(tree)
    entry_functions = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in WRITE_CALLS:
            function = _enclosing_function(parents, node)
            if function is not None:
                entry_functions.add(function.name)
    assert entry_functions, "the inventory must observe the real write sites"
    assert entry_functions == PUBLICATION_FUNCTIONS, sorted(entry_functions ^ PUBLICATION_FUNCTIONS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ConsumptionGuard":
            guard_methods = {child.name for child in node.body if isinstance(child, ast.FunctionDef)}
            assert {"write_file", "write_tree"} <= guard_methods


def test_public_module_surface_is_the_documented_contract():
    import rag_mcp.runtime.memory_projection as module

    for name in ("mark_memory_projection_dirty", "worker_task", "reconcile"):
        assert callable(getattr(module, name, None)), f"{name} is part of the fixed contract"
    assert not hasattr(module, "write_memory_file"), "no public arbitrary-path writer may exist"
    assert not hasattr(module, "write_tree")


def test_revision_store_is_still_the_only_authority_log_writer():
    """The 012 no-bypass inventory keeps holding after 014 lands."""
    writers = []
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = _tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_upsert":
                writers.append(path.relative_to(SRC).as_posix())
    assert writers and set(writers) == {"services/memory_projection_store.py"}


def test_projection_store_still_guards_every_materializer_with_authorize():
    tree = _tree(PROJECTION_STORE)
    materializers = {"_materialize_relation", "_materialize_dense", "_materialize_links", "_materialize_summary",
                     "_materialize_files", "_materialize_salience"}
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in materializers:
            first = node.body[0]
            assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Await)
            assert first.value.value.func.attr == "_authorize", node.name


def test_no_new_chmod_or_stat_calls_in_the_revision_store():
    """014 must not add directory/file lock semantics to the frozen 012 store."""
    source = _source(PROJECTION_STORE)
    assert "chmod" not in source
    assert "stat.S_I" not in source


def test_consumption_module_is_import_side_effect_free():
    """Importing the layer must not construct a consumer, task or directory."""
    source = _source(CONSUMPTION_MODULE)
    assert "get_settings()" not in source.split("def _enabled", 1)[0]
    import rag_mcp.runtime.memory_projection as module

    assert module._DIRTY_SCOPES == set()
    assert module._WORKER_TASKS == {}


def test_readonly_guard_uses_the_asymmetric_platform_form():
    source = _source(CONSUMPTION_MODULE)
    assert "stat.S_IREAD" in source, "Windows files use S_IREAD"
    assert "0o444" in source and "0o755" in source
    assert not re.search(r"chmod\(\s*directory\s*,\s*0o555", source), "directories must stay 0755"


@pytest.mark.asyncio
async def test_mark_dirty_is_a_silent_noop_without_the_switch(monkeypatch, tmp_path):
    import rag_mcp.runtime.memory_projection as module
    from rag_mcp.services.memory_reducer import reduce_events

    module.set_consumer(module.MemoryProjectionConsumer(root=tmp_path / "consumption"))
    monkeypatch.setattr(module, "_enabled", lambda: False)
    try:
        module.mark_memory_projection_dirty(7)  # must not raise, must not schedule
        module.mark_memory_projection_dirty("7")
        module.mark_memory_projection_dirty(-1)
        assert module.worker_task(7) is None
        assert module._DIRTY_SCOPES == set()
        assert not (tmp_path / "consumption").exists()
    finally:
        module.set_consumer(None)


def test_consumption_root_default_is_a_sibling_of_data_root(monkeypatch, tmp_path):
    from rag_mcp.config import Settings

    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data" / "uploads"))
    monkeypatch.delenv("MEMORY_CONSUMPTION_ROOT", raising=False)
    settings = Settings()
    root = Path(settings.memory_consumption_root).resolve()
    assert root == (tmp_path / "data" / "memory_projection").resolve()
    assert not root.is_relative_to(Path(settings.data_root).resolve())


def test_consumption_root_cannot_overlap_data_root(monkeypatch, tmp_path):
    from rag_mcp.config import Settings

    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data" / "uploads"))
    monkeypatch.setenv("MEMORY_CONSUMPTION_ROOT", str(tmp_path / "data" / "uploads" / "consumption"))
    with pytest.raises(ValueError):
        Settings()
