from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from rag_mcp.models import Base


class MemoryLink(Base):
    __tablename__ = "memory_links"
    __table_args__ = (Index("ix_memory_links_scope_revision", "knowledge_scope_id", "revision_id"),)
    row_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("knowledge_scopes.scope_id"), nullable=False)
    revision_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    node_key: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)


class MemorySummaryNode(Base):
    __tablename__ = "memory_summary_nodes"
    __table_args__ = (Index("ix_memory_summary_nodes_scope_revision", "knowledge_scope_id", "revision_id"),)
    row_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("knowledge_scopes.scope_id"), nullable=False)
    revision_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    node_key: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[list] = mapped_column(JSONB, nullable=False)
