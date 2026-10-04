from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from rag_mcp.models import Base


class MemoryEntry(Base):
    __tablename__ = "memory_entries"
    __table_args__ = (Index("ix_memory_entries_scope_status", "knowledge_scope_id", "status"),)
    memory_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    inference_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    supersedes_memory_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    superseded_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    injection_flags: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    valid_from: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    valid_to: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
