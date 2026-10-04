"""DomainProfile ORM model (007, T005).

The domain profile registry (domain_profiles) is the "declare once, consume
four places" configuration hub (ADR-3, FR-003). It holds declarative domain
configuration (formats, chunk-type vocabularies, graph relation vocabularies,
prompt overrides, default capabilities) and MUST NOT contain knowledge content
(FR-006). Builtin rows are read-only (is_builtin, FR-005).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from rag_mcp.models import Base


class DomainProfile(Base):
    __tablename__ = "domain_profiles"

    domain_key: Mapped[str] = mapped_column(
        String(64), primary_key=True, comment="stable profile key",
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="display name")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    supported_formats: Mapped[list] = mapped_column(
        JSONB, nullable=False, comment="declared accepted format set",
    )
    chunk_type_extensions: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="namespaced chunk-type extension vocabulary",
    )
    graph_relations: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="relation vocabulary with directions",
    )
    prompt_overrides: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="planner prompt injection fragments",
    )
    default_capabilities: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="default capability declaration",
    )
    memory_policy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), comment="builtin (read-only) flag",
    )
    created_at: Mapped[Any] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"),
    )
    updated_at: Mapped[Any] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DomainProfile(domain_key={self.domain_key!r}, builtin={self.is_builtin})>"
