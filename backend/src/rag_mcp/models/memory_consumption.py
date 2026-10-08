"""Consumption-layer metadata (014 T043, migration 0106).

One row per knowledge scope carrying the last-good fingerprint, status and
repair basis of the read-only file consumption layer. This is *not* a memory
source of truth: the append-only ``memory_events`` log remains the only
authority, and the row is never consulted for a fact or a status judgement
(FR-029/SC-012).

Deliberately a separate table — never ``memory_projection_meta``, whose
``versions()`` contract forces exactly the six business ``VIEW_KEYS`` (012
FR-005); adding a seventh type there would break the existing rebuild checks.
"""

from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from rag_mcp.models import Base


class MemoryConsumptionProjection(Base):
    """Last-good registry for ``<MEMORY_CONSUMPTION_ROOT>/<scope_slug>/...``."""

    __tablename__ = "memory_consumption_projection"

    knowledge_scope_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("knowledge_scopes.scope_id"), primary_key=True
    )
    #: Directly the resolved ``knowledge_scopes.slug`` (single canonical source);
    #: width aligned with ``ScopeSlug`` (<=255).
    scope_slug: Mapped[str] = mapped_column(String(255), nullable=False)
    #: End of the verified log prefix this render was based on.
    source_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: ``sha256(canonical({relative path -> sha256(bytes)}))`` — bytes only.
    tree_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Rendered memory files (DIGEST.md/INDEX.md excluded).
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'staging'"))
    #: Expected OS form of the published files (defence in depth only).
    guard_state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'writable'"))
    last_error: Mapped[str | None] = mapped_column(Text)
    refreshed_at: Mapped[Any] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[Any] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        CheckConstraint("status ~ '^[a-z][a-z0-9_]*$'", name="ck_memory_consumption_status"),
        CheckConstraint("guard_state ~ '^[a-z][a-z0-9_]*$'", name="ck_memory_consumption_guard_state"),
        CheckConstraint("tree_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_memory_consumption_fingerprint"),
        CheckConstraint("file_count >= 0", name="ck_memory_consumption_file_count"),
        CheckConstraint("source_event_id > 0", name="ck_memory_consumption_source_event"),
        Index("ix_memory_consumption_status", "status"),
    )
