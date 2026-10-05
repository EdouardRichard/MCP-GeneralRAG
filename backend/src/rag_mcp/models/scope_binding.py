from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from rag_mcp.models import Base


class ScopeBinding(Base):
    __tablename__ = "scope_bindings"
    __table_args__ = (UniqueConstraint("binding_kind", "binding_value", name="uq_scope_binding_value"),)
    binding_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    binding_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    binding_value: Mapped[str] = mapped_column(String(1024), nullable=False)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("knowledge_scopes.scope_id"), nullable=False)
    priority: Mapped[int] = mapped_column(nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
