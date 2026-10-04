def test_all_memory_write_entrance_points_use_validator():
    from pathlib import Path

    root = Path(__file__).parents[2] / "src" / "rag_mcp"
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py") if "memory" in path.name)
    assert "validate_memory" in text
    assert "MemoryEventStore" in text
