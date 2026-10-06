from typing import Any

from sqlalchemy import BigInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from rag_mcp.models import Base


class MemoryManagementAudit(Base):
    __tablename__ = "memory_management_audits"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    since_event_id: Mapped[int | None] = mapped_column(BigInteger)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[Any] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                              server_default=text("NOW()"))
