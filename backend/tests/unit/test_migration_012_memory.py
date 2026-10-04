import pytest


def test_memory_foundation_tables_are_declared():
    from rag_mcp.models import Base

    expected = {
        "memory_events", "memory_entries", "scope_bindings", "sessions",
        "memory_salience", "memory_recall_runs", "memory_projection_meta",
    }
    # Importing the package must register every 012 table for Alembic.
    from rag_mcp.models import MemoryEvent, MemoryEntry, ScopeBinding, MemorySession, MemorySalience, MemoryRecallRun
    assert expected.issubset(set(Base.metadata.tables))


def test_memory_event_indexes_and_scope_constraint_exist():
    from rag_mcp.models.memory_event import MemoryEvent

    assert {"knowledge_scope_id", "aggregate_id", "occurred_at"}.issubset(set(MemoryEvent.__table__.c.keys()))
    assert any("knowledge_scope_id" in ix.columns.keys() for ix in MemoryEvent.__table__.indexes)
