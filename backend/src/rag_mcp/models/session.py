from typing import Any
from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from rag_mcp.models import Base


class MemorySession(Base):
    __tablename__ = "sessions"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_scope_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("knowledge_scopes.scope_id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    started_at: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True))
    last_active_at: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True))
    expires_at: Mapped[Any | None] = mapped_column(TIMESTAMP(timezone=True))
