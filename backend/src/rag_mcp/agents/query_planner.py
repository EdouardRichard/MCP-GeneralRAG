"""Query planner agent for multi-hop query decomposition (T019/T021, US1).

Decomposes complex/multi-hop queries into traceable sub-problems:
  - sub_problem_id starts from 1, monotonic (FR-032)
  - signals subset of {dense, sparse, graph} (FR-001)
  - relation_directions respect 004 bidirectional default (FR-033)
  - Invalid direction selections fall back to 004 deterministic default
  - schema_valid=true when output passes validation (FR-003)
  - Single-intent query produces 1 sub-problem (no extra overhead)

009 (T007/T009-T012): the planner is domain-neutralized. The system prompt and
the relation-direction vocabulary are derived per-request from the
domain_planner_config injected by the entry orchestration (research R1/R2/R7);
NODE_SCHEMA is built dynamically from the relation vocabulary (research R2).
When no domain_planner_config is wired (direct construction), the planner
preserves the 1.0 se-project behaviour as the backward-compatible default.

Constitution VI: the query planner is an Agent whose output is an INPUT
to the deterministic controller, not an exclusive jump authority.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator

from rag_mcp.agents.base import AgentBase
from rag_mcp.config.domain_profiles import (
    SE_PLANNER_PROMPT,
    SE_PROJECT_GRAPH_RELATIONS,
    render_neutral_planner_prompt,
)

logger = logging.getLogger(__name__)

VALID_SIGNALS = {"dense", "sparse", "graph"}

# 1.0 se-project relation vocabulary — the backward-compatible default when no
# domain_planner_config is wired. Derived from the se-project profile
# declaration, not hardcoded here (Constitution XI / SC-005).
_DEFAULT_RELATION_VOCAB = list(SE_PROJECT_GRAPH_RELATIONS)


def _build_node_schema(relation_vocab: list[str]) -> dict[str, Any]:
    """Build the planner NODE_SCHEMA dynamically from the relation vocab (R2).

    Non-empty vocab -> signals enum includes 'graph' and the schema carries
    relation_directions (items.enum = vocab) + graph_hop. Empty vocab -> both
    relation_directions and graph_hop are OMITTED and signals is [dense, sparse]
    (clarification Q4, FR-008).
    """
    signals_enum = ["dense", "sparse"]
    if relation_vocab:
        signals_enum.append("graph")

    sub_problem_props: dict[str, Any] = {
        "sub_problem_id": {"type": "integer", "minimum": 1},
        "query": {"type": "string", "minLength": 1},
        "signals": {
            "type": "array",
            "items": {"type": "string", "enum": signals_enum},
            "minItems": 1,
        },
    }
    if relation_vocab:
        sub_problem_props["relation_directions"] = {
            "type": "array",
            "items": {"type": "string", "enum": list(relation_vocab)},
        }
        sub_problem_props["graph_hop"] = {"type": "integer", "minimum": 1, "maximum": 3}

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "sub_problems": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": sub_problem_props,
                    "required": ["sub_problem_id", "query", "signals"],
                    "additionalProperties": False,
                },
            },
            "schema_valid": {"type": "boolean"},
        },
        "required": ["sub_problems", "schema_valid"],
        "additionalProperties": False,
    }


@lru_cache(maxsize=None)
def _cached_validator(vocab_key: frozenset[str]) -> Draft202012Validator:
    """Per-request validator cached by the vocab key (research R2).

    Enum order does not affect validation, so a canonical (sorted) order is
    used here; the two builtin vocab shapes (4 values / empty) hit a 100%
    cache rate.
    """
    return Draft202012Validator(_build_node_schema(sorted(vocab_key)))


# Module-level default NODE_SCHEMA: the se-project shape (backward-compatible
# for direct importers such as test_query_planner_hop.py). The runtime schema
# is derived per-request from the domain_planner_config vocabulary (R2).
NODE_SCHEMA: dict[str, Any] = _build_node_schema(list(_DEFAULT_RELATION_VOCAB))


class QueryPlannerAgent(AgentBase):
    """Query planner agent that decomposes queries into sub-problems (FR-001).

    Uses an LLM to decompose multi-hop queries. Falls back to a single
    sub-problem (the original query) when the LLM fails or returns invalid
    output (SC-011).
    """

    ROLE = "query_planner"
    NODE_SCHEMA = NODE_SCHEMA

    # Backward-compatible 1.0 se-project system prompt (the equivalence gate,
    # FR-002/SC-001 text layer). Kept as an alias for legacy importers; the
    # runtime prompt is resolved per-request in execute().
    DECOMPOSE_SYSTEM_PROMPT = SE_PLANNER_PROMPT

    def __init__(self, model_and_version: str = "", llm_client=None) -> None:
        super().__init__(model_and_version=model_and_version)
        self._sub_problem_counter = 0
        self._llm_client = llm_client
        self._relation_vocab = list(_DEFAULT_RELATION_VOCAB)
        self._system_prompt = SE_PLANNER_PROMPT

    # ------------------------------------------------------------------
    # Per-request domain config resolution (009, T007, research R1/R2)
    # ------------------------------------------------------------------

    def _resolve_config(
        self, context: dict[str, Any],
    ) -> tuple[list[str], list[str], str | None]:
        """Resolve (distinct_domain_keys, relation_vocab, prompt_override).

        When domain_planner_config is absent/None (direct construction), the
        1.0 se-project default is preserved. Otherwise the config's fields are
        honoured; a non-single override is normalised to None (FR-003).
        """
        cfg = context.get("domain_planner_config")
        if not isinstance(cfg, dict) or not cfg:
            return ["se-project"], list(_DEFAULT_RELATION_VOCAB), SE_PLANNER_PROMPT

        distinct_keys = list(cfg.get("distinct_domain_keys") or [])
        vocab = list(cfg.get("relation_vocab") or [])
        prompt_override = cfg.get("prompt_override")
        if len(distinct_keys) != 1 or not prompt_override:
            prompt_override = None
        return distinct_keys, vocab, prompt_override

    def _resolve_system_prompt(
        self,
        distinct_keys: list[str],
        vocab: list[str],
        prompt_override: str | None,
    ) -> str:
        """Resolve the system prompt (research R1 / FR-003).

        Single profile with a query_planner_system_prompt override -> the
        override (the complete system prompt). Heterogeneous / no override ->
        the domain-neutral base template with the relation-vocab slot filled.
        """
        if len(distinct_keys) == 1 and prompt_override:
            return prompt_override
        return render_neutral_planner_prompt(vocab)

    def _prepare(self, context: dict[str, Any]) -> None:
        """Derive per-request vocab/prompt/validator state (T007/T009)."""
        distinct_keys, vocab, prompt_override = self._resolve_config(context)
        self._relation_vocab = list(vocab)
        self._system_prompt = self._resolve_system_prompt(
            distinct_keys, vocab, prompt_override,
        )
        self._validator = _cached_validator(frozenset(self._relation_vocab))

    def get_default_directions(self) -> list[str]:
        """Return the 004 deterministic bidirectional default (FR-033).

        Derived from the current request's relation vocabulary; falls back to
        the 1.0 se-project default when no request has been prepared yet.
        """
        return list(self._relation_vocab)

    def _next_sub_problem_id(self) -> int:
        """Return the next sub_problem_id (starts from 1, monotonic, FR-032)."""
        self._sub_problem_counter += 1
        return self._sub_problem_counter

    def _llm_decompose(self, query: str, context: dict[str, Any]) -> list[dict[str, Any]] | None:
        """Call the LLM to decompose the query (overridable for testing).

        Makes a REAL LLM call through the wired client when one is configured
        (T019 LLM integration). Returns a list of sub-problem dicts, or None
        on any failure — the caller then degrades deterministically (SC-011).
        Each dict has: query (str), signals (list[str]), relation_directions (list[str]|None).
        """
        if self._llm_client is None:
            # No client wired: deterministic fallback (keeps unit tests offline)
            return None
        try:
            payload = self._llm_client.chat_json(
                self._system_prompt,
                {"query": query, "task_context": context.get("task_context")},
            )
        except Exception as exc:
            logger.warning("query_planner LLM call raised: %s", exc)
            return None
        if not isinstance(payload, dict):
            return None
        sub_problems = payload.get("sub_problems")
        if not isinstance(sub_problems, list) or not sub_problems:
            return None
        return sub_problems

    def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Decompose the query into sub-problems (FR-001/FR-032/FR-033)."""
        self._prepare(context)

        query = context.get("query", "")
        if not query:
            return {"sub_problems": [], "schema_valid": True}

        raw_sub_problems = self._llm_decompose(query, context)

        if not raw_sub_problems:
            # LLM unavailable: use fallback (single sub-problem)
            return self._build_fallback_output(query)

        # Reset counter for fresh decomposition
        self._sub_problem_counter = 0
        sub_problems = []
        for sp in raw_sub_problems:
            sub_id = self._next_sub_problem_id()
            sp_query = sp.get("query", query)
            signals = self._validate_signals(sp.get("signals", ["dense"]))
            directions = self._validate_directions(sp.get("relation_directions"), signals)
            sub_problem = {
                "sub_problem_id": sub_id,
                "query": sp_query,
                "signals": signals,
            }
            if directions:
                sub_problem["relation_directions"] = directions
            if "graph" in signals:
                # Planner hop cap within the 004 guardrail band; invalid or
                # missing values fall back to the 004 default hop 2 (FR-033)
                sub_problem["graph_hop"] = self._validate_hop(sp.get("graph_hop"))
            sub_problems.append(sub_problem)

        return {"sub_problems": sub_problems, "schema_valid": True}

    def fallback(self, context: dict[str, Any]) -> dict[str, Any]:
        """Deterministic fallback: single sub-problem with the original query (SC-011)."""
        self._prepare(context)
        query = context.get("query", "")
        return self._build_fallback_output(query)

    def _build_fallback_output(self, query: str) -> dict[str, Any]:
        """Build a valid single-sub-problem output (deterministic, SC-011).

        009 (T012): when the current domain declares no relation vocabulary,
        relation_directions/graph_hop are omitted (fallback matches the
        dynamic schema, FR-008).
        """
        self._sub_problem_counter = 0
        sub_id = self._next_sub_problem_id()
        sub_problem: dict[str, Any] = {
            "sub_problem_id": sub_id,
            "query": query,
            "signals": ["dense"],
        }
        if self._relation_vocab:
            sub_problem["relation_directions"] = list(self._relation_vocab)
        return {
            "sub_problems": [sub_problem],
            "schema_valid": True,
        }

    def _validate_signals(self, signals: list[str]) -> list[str]:
        """Validate signals against the current domain's capability (FR-006/FR-008).

        'graph' is only allowed when the current domain declares a non-empty
        relation vocabulary (a no-graph domain cannot plan graph traversal).
        """
        allowed = {"dense", "sparse"}
        if self._relation_vocab:
            allowed.add("graph")
        valid = [s for s in signals if s in allowed]
        if not valid:
            valid = ["dense"]  # default fallback
        return valid

    def _validate_hop(self, value: Any) -> int:
        """Validate the planner graph hop cap (FR-033, T067).

        The 004 guardrail band is 1..3 (hop_default 2 / hop_max 3). Invalid
        or missing values fall back to the 004 deterministic default 2.
        """
        try:
            hop = int(value)
        except (TypeError, ValueError):
            return 2
        if hop < 1 or hop > 3:
            return 2
        return hop

    def _validate_directions(
        self,
        directions: list[str] | None,
        signals: list[str],
    ) -> list[str]:
        """Validate relation_directions and fall back to the domain default (FR-033).

        - If signals do not include graph, directions are optional (may be empty).
        - If directions are missing or empty and graph signal is present,
          use the current domain's default vocabulary.
        - If any direction is invalid, fall back to the full domain vocabulary.
        - A no-graph domain has no default vocabulary and produces no directions.
        """
        has_graph = "graph" in signals
        vocab = self._relation_vocab

        if not vocab:
            return []  # no-graph domain: no directions are plannable

        if not directions:
            if has_graph:
                return list(vocab)
            return []  # non-graph signals: no directions needed

        # Check if all directions are valid
        all_valid = all(d in vocab for d in directions)
        if not all_valid:
            # Any invalid -> fall back to full default (FR-033)
            return list(vocab)

        return list(directions)
