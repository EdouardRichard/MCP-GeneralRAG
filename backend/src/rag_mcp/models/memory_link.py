"""Typed memory link projection mapping (013 T011/T056).

`memory_links` keeps the 012 view columns (row_id/scope/revision/node_key/data)
and adds typed columns filled from the immutable `data` authority by the
`verify_typed_memory_link` parity trigger: base 012 edges (evidence/supersedes)
are always deterministic with the 012-base-v1 vocabulary; advanced edges carry
the declaring vocabulary version, semantic category and propagation mode
captured at approval time. Evidence endpoints are chunks, so `to_id` takes no
blanket memory FK; `created_by_run` is a permanent scalar that must not FK the
TTL'd audit tables.
"""
from uuid import UUID as PythonUUID

from sqlalchemy import BigInteger, CheckConstraint, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from rag_mcp.models import Base

BASE_RELATIONS = ('evidence', 'supersedes')
BASE_VOCABULARY_VERSION = '012-base-v1'
LINK_CATEGORIES = ('live_dependency', 'historical_lineage', 'association')
PROPAGATION_MODES = ('to_to_from', 'none')
LINK_PROVENANCE = ('deterministic', 'llm_proposed')


class MemoryLink(Base):
    __tablename__ = 'memory_links'
    __table_args__ = (
        Index('ix_memory_links_scope_revision', 'knowledge_scope_id', 'revision_id'),
        UniqueConstraint('knowledge_scope_id', 'revision_id', 'from_id', 'to_id', 'relation_type', name='uq_memory_link_revision_edge'),
        CheckConstraint("to_kind IN ('memory','evidence')", name='ck_memory_link_to_kind'),
        CheckConstraint("provenance IN ('deterministic','llm_proposed')", name='ck_memory_link_provenance'),
        CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1", name='ck_memory_link_confidence'),
    )
    row_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('knowledge_scopes.scope_id'), nullable=False)
    revision_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    node_key: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    from_id: Mapped[str] = mapped_column(String(128), nullable=False)
    to_id: Mapped[str] = mapped_column(String(128), nullable=False)
    to_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_by_run: Mapped[PythonUUID | None] = mapped_column(UUID(as_uuid=True))
    source_event_id: Mapped[int | None] = mapped_column(BigInteger)
    vocabulary_version: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_category: Mapped[str] = mapped_column(String(32), nullable=False)
    propagation: Mapped[str] = mapped_column(String(16), nullable=False)
