from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from rag_mcp.models import Base


class MemorySession(Base):
    __tablename__ = "sessions"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_scope_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
