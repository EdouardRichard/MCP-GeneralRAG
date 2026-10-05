"""Validated declarative settings for the memory management surface."""
from pydantic import BaseModel, ConfigDict, Field, StrictBool


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
    attach_min_score: float = Field(default=0., ge=0, le=1, allow_inf_nan=False)
