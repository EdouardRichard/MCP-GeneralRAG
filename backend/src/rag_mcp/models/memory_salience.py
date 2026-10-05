from typing import Any
from sqlalchemy import BigInteger, Float, ForeignKey
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from rag_mcp.models import Base


class MemorySalience(Base):
    __tablename__ = "memory_salience"
    memory_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("memory_entries.memory_id"), primary_key=True)
    salience: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    access_count: Mapped[int] = mapped_column(nullable=False, default=0)
    decay_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.05)
    last_access_at: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True))
    reinforced_at: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True))
