from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from rag_mcp.models import Base


class MemoryEvent(Base):
    __tablename__ = "memory_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('assert','revise','retract','consolidate','access','grant','rollback')", name="ck_memory_event_type"),
        Index("ix_memory_events_scope_aggregate_time", "knowledge_scope_id", "aggregate_id", "occurred_at"),
        Index("ix_memory_events_scope_event", "knowledge_scope_id", "event_id"),
    )
    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    authority: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scope_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    mutability: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recoverability: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actionability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[Any] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    valid_from: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    valid_to: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[Any] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
