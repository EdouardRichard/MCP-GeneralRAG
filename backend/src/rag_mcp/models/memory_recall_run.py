from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from rag_mcp.models import Base


class MemoryRecallRun(Base):
    __tablename__ = "memory_recall_runs"
    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
