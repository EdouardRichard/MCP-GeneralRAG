from typing import Any
from sqlalchemy import Boolean, Float, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from rag_mcp.models import Base


class MemoryRecallRun(Base):
    __tablename__ = "memory_recall_runs"
    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    channel: Mapped[str | None] = mapped_column(String(32))
    session_id: Mapped[str | None] = mapped_column(String(64))
    returned_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    returned_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    package_fingerprint: Mapped[str | None] = mapped_column(String(64))
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    failed_paths: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    created_at: Mapped[Any] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
    expires_at: Mapped[Any] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW() + INTERVAL '7 days'"))
