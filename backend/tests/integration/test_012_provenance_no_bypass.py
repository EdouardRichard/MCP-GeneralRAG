def test_all_memory_write_entrance_points_use_validator():
    from pathlib import Path

    root = Path(__file__).parents[2] / "src" / "rag_mcp"
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py") if "memory" in path.name)
    assert "validate_memory" in text
    assert "MemoryEventStore" in text


import pytest
from sqlalchemy import select, func
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
async def test_provenance_rejection_precedes_injection_and_cannot_append(db_session, monkeypatch):
    from rag_mcp.agents.injection_detector import InjectionDetector
    sid, payload = await scope_and_payload(db_session)
    observed = []
    original = InjectionDetector.detect
    def detected(self, *args, **kwargs):
        observed.append(True)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(InjectionDetector, "detect", detected)
    with pytest.raises(ValueError, match="MEMORY_EVIDENCE_ANCHOR_REQUIRED"):
        await MemoryService(db_session).record({**payload, "provenance": "hard", "evidence_refs": []})
    assert observed == [], "the nine-step pipeline runs injection before provenance rejection"
    assert await db_session.scalar(select(func.count()).select_from(MemoryEvent).where(MemoryEvent.knowledge_scope_id == sid)) == 0


def test_memory_mutation_entrance_inventory_has_no_non_event_projection_writers():
    import ast
    from pathlib import Path
    root = Path(__file__).parents[2] / "src/rag_mcp"
    writers = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_upsert":
                writers.append(path.relative_to(root).as_posix())
    assert writers and set(writers) == {"services/memory_projection_store.py"}
    source = (root / "services/memory_projection_store.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in {"_materialize_relation", "_materialize_dense", "_materialize_links", "_materialize_summary", "_materialize_files", "_materialize_salience"}:
            assert isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Await)
            assert node.body[0].value.value.func.attr == "_authorize", node.name
    assert "self._states" not in source
