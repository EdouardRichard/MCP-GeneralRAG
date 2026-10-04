import pytest


def test_memory_event_has_wide_event_check_and_required_scope_fields():
    from rag_mcp.models.memory_event import MemoryEvent

    from sqlalchemy import CheckConstraint
    checks = " ".join(str(c.sqltext) for c in MemoryEvent.__table__.constraints if isinstance(c, CheckConstraint))
    assert "event_type" in checks
    for field in ("knowledge_scope_id", "payload", "authority", "scope_meta", "provenance_meta", "occurred_at"):
        assert MemoryEvent.__table__.c[field].nullable is False


def test_event_store_is_append_only_api():
    from rag_mcp.services.memory_event_store import MemoryEventStore

    assert hasattr(MemoryEventStore, "append")
    assert not hasattr(MemoryEventStore, "update")
    assert not hasattr(MemoryEventStore, "delete")
