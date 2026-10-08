"""Validated declarative settings for the memory management surface."""
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class ConsolidationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    volume_threshold: int = Field(default=100, ge=1, le=5000)
    batch_size: int = Field(default=32, ge=1, le=64)
    reference_limit: int = Field(default=64, ge=0, le=128)
    max_sources_per_proposal: int = Field(default=16, ge=1, le=32)
    max_chain_depth: int = Field(default=32, ge=1, le=32)
    max_proposals: int = Field(default=64, ge=1, le=128)
    max_events_per_group: int = Field(default=128, ge=1, le=128)
    min_confidence: float = Field(default=.80, ge=0, le=1, allow_inf_nan=False)
    candidate_min_confidence: float = Field(default=.95, ge=0, le=1, allow_inf_nan=False)
    max_links_per_proposal: int = Field(default=8, ge=0, le=16)
    max_context_chars: int = Field(default=512, ge=0, le=1024)
    max_keywords: int = Field(default=8, ge=0, le=16)
    max_input_chars: int = Field(default=32000, ge=4000, le=64000)
    llm_timeout_seconds: int = Field(default=30, ge=1, le=60)
    max_llm_calls: int = Field(default=1, ge=0, le=2)
    run_timeout_seconds: int = Field(default=300, ge=30, le=600)
    idle_seconds: int = Field(default=60, ge=1, le=600)
    expansion_max_hops: int = Field(default=1, ge=1, le=2)
    expansion_max_nodes: int = Field(default=8, ge=1, le=16)

    @model_validator(mode="after")
    def ordered_thresholds(self):
        if self.candidate_min_confidence < self.min_confidence:
            raise ValueError("candidate_min_confidence must be >= min_confidence")
        return self


class WorkBudgets(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    full: int = Field(default=2000, ge=250, le=2000)
    compact: int = Field(default=800, ge=250, le=800)
    minimal: int = Field(default=300, ge=250, le=300)


class FusionWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dense: float = Field(default=1., ge=0, allow_inf_nan=False)
    recency: float = Field(default=.5, ge=0, allow_inf_nan=False)
    kind: float = Field(default=.3, ge=0, allow_inf_nan=False)
    salience: float = Field(default=.2, ge=0, allow_inf_nan=False)


class MemoryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    episodic_ttl_days: int = Field(default=180, gt=0)
    semantic_procedural_ttl_days: int | None = Field(default=None, gt=0)
    per_scope_memory_quota: int = Field(default=5000, gt=0)
    decay_rate: float = Field(default=.05, ge=0, allow_inf_nan=False)
    rrf_weights: FusionWeights = Field(default_factory=FusionWeights)
    start_work_budgets: WorkBudgets = Field(default_factory=WorkBudgets)
    consolidation_enabled: StrictBool = False
    consolidation: ConsolidationPolicy | None = None
    link_expansion_enabled: StrictBool = False
    attach_min_score: float = Field(default=0., ge=0, le=1, allow_inf_nan=False)
    # --- 014 (data-model §3): additive optional keys for memory-aware retrieval.
    # Every new key has a default, so an existing profile without it keeps the
    # current behaviour inactive. `attach_min_score` above is deliberately NOT
    # re-defaulted: changing it would move the domain `policy_hash` that 013's
    # gate registrations were bound to.
    attach_conservative_min_score: float = Field(default=.50, ge=0, le=1, allow_inf_nan=False)
    attach_top_k: int = Field(default=3, ge=1, le=5)
    attach_max_chars: int = Field(default=800, ge=200, le=800)
    attach_excerpt_chars: int = Field(default=200, ge=1, le=200)
    attach_timeout_ms: int = Field(default=800, ge=1, le=800)
    delivered_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    working_set_max_open_items: int = Field(default=3, ge=1, le=5)
    working_set_max_recent_activity: int = Field(default=3, ge=1, le=5)
    working_set_max_procedural: int = Field(default=2, ge=1, le=5)

    @model_validator(mode="after")
    def explicit_consolidation(self):
        if self.consolidation_enabled and self.consolidation is None:
            raise ValueError("enabled consolidation requires explicit configuration")
        return self

    @model_validator(mode="after")
    def ordered_attach_thresholds(self):
        # Fail closed rather than silently clamping: a conservative threshold below
        # the permissive one would make the "no memory_context"档 less strict than
        # the documented "宁缺勿滥" behaviour.
        if self.attach_conservative_min_score < self.attach_min_score:
            raise ValueError("attach_conservative_min_score must be >= attach_min_score")
        return self
