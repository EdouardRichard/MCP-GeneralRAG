from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Float, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from rag_mcp.models import Base


class MemoryEntry(Base):
    __tablename__ = "memory_entries"
    __table_args__ = (
        Index("ix_memory_entries_scope_status", "knowledge_scope_id", "status"),
        Index("ix_memory_entries_scope_kind_status", "knowledge_scope_id", "kind", "status"),
        Index("ix_memory_entries_session", "session_id"),
        UniqueConstraint("knowledge_scope_id", "content_hash", name="uq_memory_entries_scope_hash"),
        CheckConstraint("char_length(content_text) BETWEEN 1 AND 4000", name="ck_memory_content_length"),
        CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1", name="ck_memory_confidence"),
        *(CheckConstraint(f"{field} ~ '^[a-z][a-z0-9_]*$'", name=f"ck_memory_{field}_wide")
          for field in ("kind", "provenance", "status")),
    )
    memory_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("knowledge_scopes.scope_id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    authority: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scope_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    mutability: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recoverability: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actionability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    submission_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Float)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    inference_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    supersedes_memory_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("memory_entries.memory_id", deferrable=True, initially="DEFERRED"), nullable=True)
    superseded_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("memory_entries.memory_id", deferrable=True, initially="DEFERRED"), nullable=True)
    injection_flags: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    valid_from: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    valid_to: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    observed_at: Mapped[Any] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
    invalidated_at: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True))
    session_id: Mapped[str | None] = mapped_column(String(64))
    agent_id: Mapped[str | None] = mapped_column(String(255))
    task_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expires_at: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True))
    promote_candidate_at: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[Any] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[Any] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
    source_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("memory_events.event_id"))
    write_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    retention_stage: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    state_event_id: Mapped[int | None] = mapped_column(BigInteger)
    context_digest: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    context_version: Mapped[str | None] = mapped_column(String(128))
    context_source_event_id: Mapped[int | None] = mapped_column(BigInteger)
    promotion_pointer: Mapped[dict | None] = mapped_column(JSONB)
    candidate_version: Mapped[str | None] = mapped_column(String(64))
    candidate_basis: Mapped[dict | None] = mapped_column(JSONB)
