from typing import Any
from sqlalchemy import BigInteger, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from rag_mcp.models import Base


class MemoryProjectionMeta(Base):
    __tablename__ = "memory_projection_meta"
    projection_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    projection_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    knowledge_scope_id: Mapped[int | None] = mapped_column(BigInteger)
    source_event_id: Mapped[int | None] = mapped_column(BigInteger)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False, server_default="012-v1")
    updated_at: Mapped[Any] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
