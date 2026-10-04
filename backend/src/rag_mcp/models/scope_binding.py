from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from rag_mcp.models import Base


class ScopeBinding(Base):
    __tablename__ = "scope_bindings"
    binding_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    binding_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    binding_value: Mapped[str] = mapped_column(String(1024), nullable=False)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    priority: Mapped[int] = mapped_column(nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
