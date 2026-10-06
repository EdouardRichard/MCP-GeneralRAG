from typing import Any
from sqlalchemy import BigInteger, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from rag_mcp.models import Base


class MemorySalience(Base):
    __tablename__ = "memory_salience"
    memory_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("memory_entries.memory_id"), primary_key=True)
    authority: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scope_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    mutability: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recoverability: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actionability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    salience: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    access_count: Mapped[int] = mapped_column(nullable=False, default=0)
    decay_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.05)
    last_access_at: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True))
    reinforced_at: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True))
