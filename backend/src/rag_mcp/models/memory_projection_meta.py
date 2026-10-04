from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from rag_mcp.models import Base


class MemoryProjectionMeta(Base):
    __tablename__ = "memory_projection_meta"
    projection_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    projection_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
