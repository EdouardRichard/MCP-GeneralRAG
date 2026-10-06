"""Mutable eligibility and immutable cumulative observations are separate."""
from datetime import datetime
from uuid import UUID as PythonUUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from rag_mcp.models import Base


CONTEXT_CHECK = """(trigger IN ('idle','manual','volume') AND execution_context='distiller_window') OR
    (trigger='support_maintenance' AND execution_context='deterministic_propagation'
    AND \"window\" IS NULL AND input_event_ids='[]'::jsonb
    AND jsonb_typeof(historical_source_refs)='array' AND jsonb_array_length(historical_source_refs)>0
    AND jsonb_typeof(propagation_trigger)='object' AND propagation_trigger ? 'proof'
    AND jsonb_typeof(propagation_trigger->'proof')='object' AND propagation_trigger->'proof'<>'{}'::jsonb
    AND (propagation_trigger->>'event_id' IS NOT NULL OR propagation_trigger->>'evidence_id' IS NOT NULL))"""
USAGE_DEFAULT = """'{"embedding_calls": 0,"rerank_calls": 0,"llm_calls": 0,"llm_prompt_chars": 0,
    "llm_completion_chars": 0,"cache_hits": 0,"source": "unavailable",
    "input_tokens": null,"output_tokens": null,"cost_usd": null}'::jsonb"""


class ConsolidationEligibility(Base):
    __tablename__ = 'consolidation_eligibilities'
    __table_args__ = (
        CheckConstraint("state IN ('active','released','expired')", name='ck_consolidation_eligibility_state'),
        CheckConstraint('eligibility_version>0', name='ck_consolidation_eligibility_version'),
        Index('uq_consolidation_scope_active', 'knowledge_scope_id', unique=True, postgresql_where=text("state='active'")),
        Index('uq_consolidation_scope_version', 'knowledge_scope_id', 'eligibility_version', unique=True),
        Index('ix_consolidation_active_expiry', 'expires_at', postgresql_where=text("state='active'")),
    )
    eligibility_id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('knowledge_scopes.scope_id'), nullable=False)
    run_id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    holder_instance_id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    writer_lease_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    eligibility_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observation_seq_high_water: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default='0')
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default='active')
    acquired_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    renewed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class ConsolidationRunObservation(Base):
    __tablename__ = 'consolidation_runs'
    __table_args__ = (
        CheckConstraint('observation_seq>0', name='ck_consolidation_observation_seq'),
        CheckConstraint(CONTEXT_CHECK, name='ck_consolidation_execution_context'),
        CheckConstraint("status IN ('admitted','selecting','proposing','adjudicating','committing','succeeded','no_change','degraded','partial','failed','interrupted')",
                        name='ck_consolidation_observation_status'),
        Index('ix_consolidation_runs_scope_seq', 'knowledge_scope_id', 'run_id', 'observation_seq'),
        Index('ix_consolidation_runs_expiry', 'ttl_expires_at'),
    )
    run_id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    observation_seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    knowledge_scope_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('knowledge_scopes.scope_id'), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_context: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128))
    actor: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    window: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    input_event_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    reference_versions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    historical_source_refs: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    propagation_trigger: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    proposals: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    adjudications: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    output_memory_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    output_event_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    pending_result_keys: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    provider_usage: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text(USAGE_DEFAULT))
    degradation_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    versions: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    eligibility_id: Mapped[PythonUUID | None] = mapped_column(UUID(as_uuid=True))
    eligibility_version: Mapped[int | None] = mapped_column(BigInteger)
    holder_instance_id: Mapped[PythonUUID | None] = mapped_column(UUID(as_uuid=True))
    writer_lease_id: Mapped[int | None] = mapped_column(BigInteger)
    eligibility_state: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=text('NOW()'))
    ttl_expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                   server_default=text("NOW()+interval '7 days'"))
