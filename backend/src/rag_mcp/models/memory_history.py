from typing import Any

from sqlalchemy import BigInteger, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from rag_mcp.models import Base


class MemorySnapshot(Base):
    __tablename__ = "memory_snapshots"
    snapshot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("knowledge_scopes.scope_id"), nullable=False, index=True)
    covered_through_event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("memory_events.event_id"), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[Any] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))


class MemoryArchive(Base):
    __tablename__ = "memory_archives"
    archive_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("knowledge_scopes.scope_id"), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[Any] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))


class MemoryArchivedEvent(Base):
    __tablename__ = "memory_archived_events"
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("memory_events.event_id"), primary_key=True)
    archive_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("memory_archives.archive_id"), nullable=False, index=True)
