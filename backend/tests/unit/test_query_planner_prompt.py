"""Prompt-equivalence and domain-neutral audit tests (009, T001/T002).

FR-001/FR-002/SC-003: the se-project planner override (SE_PLANNER_PROMPT) must be
the verbatim 1.0 DECOMPOSE_SYSTEM_PROMPT (the equivalence gate text layer), and
the domain-neutral base template must carry zero SE examples and zero relation
vocabulary (the domain-neutrality audit).

TDD Red: T001 fails while SE_PLANNER_PROMPT is the abbreviated 007 seed; T002
fails until the domain-neutral base template exists.
"""

from __future__ import annotations

from rag_mcp.config.domain_profiles import SE_PLANNER_PROMPT

GOLDEN_1_0_PROMPT = """You are a query-planning agent for a code/knowledge retrieval system. Decompose the user's retrieval query into traceable sub-problems. For multi-hop questions produce one sub-problem per hop; for single-intent questions return exactly ONE sub-problem.

Signal selection rules (apply per sub-problem, T073/FR-001):
- 'dense' and 'sparse' recall chunks by semantic/lexical similarity to the query text. They are the right signals for precision questions: exact symbols or definitions, column/type/constraint/index/view declarations, compatibility or consistency checks between named items, version or source conflicts, configuration values, 'what/which fields does X have'.
- 'graph' traverses structural relations (method call edges, foreign-key edges). Add 'graph' ONLY when the question itself asks about relationships or traversal: who calls X, which methods X invokes, which tables reference a table/column, callers/callees, multi-hop chains across symbols or tables. Do NOT add 'graph' when the question merely names a symbol, table or column but asks about its content, definition or compatibility — use 'dense' and 'sparse' there.
- Always include 'dense'; add 'sparse' when the query names concrete identifiers (class, method, table, column, constraint names).

'relation_directions' (optional, only when 'graph' is in signals) is a subset of ["calls", "called_by", "fk_references", "fk_referenced_by"]. Pick the minimal direction the question needs: who calls X -> ["called_by"]; what does X call -> ["calls"]; FK-reference questions -> ["fk_references", "fk_referenced_by"].
'graph_hop' (optional integer 1-3, only when 'graph' is in signals): 1 for direct relations, 2 for one intermediate hop. Omit when unsure.

Respond with ONLY a JSON object of the exact shape:
{"sub_problems": [{"query": string, "signals": [string], "relation_directions": [string]}]}
No markdown fences, no extra keys, no commentary."""


class TestSeProjectPromptEquivalence:
    """T001 / SC-001 text layer: SE_PLANNER_PROMPT == 1.0 DECOMPOSE_SYSTEM_PROMPT."""

    def test_se_planner_prompt_matches_1_0_verbatim(self):
        assert SE_PLANNER_PROMPT.splitlines() == GOLDEN_1_0_PROMPT.splitlines(), (
            "SE_PLANNER_PROMPT must be the verbatim 1.0 DECOMPOSE_SYSTEM_PROMPT "
            "(sentence-for-sentence equivalence gate)"
        )


class TestDomainNeutralBaseTemplateAudit:
    """T002 / SC-003: the base template is free of SE examples + relation vocab."""

    def _template(self) -> str:
        from rag_mcp.config.domain_profiles import DOMAIN_NEUTRAL_BASE_TEMPLATE

        return DOMAIN_NEUTRAL_BASE_TEMPLATE

    def test_base_template_has_no_se_examples(self):
        text = self._template().lower()
        for term in ("method call", "method", "foreign-key", "class", "table", "column", "constraint", "index", "view", "symbols", "fields", "declared", "configuration"):
            assert term not in text, f"SE example leaked into base template: {term!r}"

    def test_base_template_has_no_relation_vocab(self):
        text = self._template().lower()
        for term in ("calls", "called_by", "fk_references", "fk_referenced_by"):
            assert term not in text, f"relation vocab leaked into base template: {term!r}"

SE_VOCAB = ["calls", "called_by", "fk_references", "fk_referenced_by"]


def _make_planner():
    from rag_mcp.agents.query_planner import QueryPlannerAgent

    planner = QueryPlannerAgent(model_and_version="test-v1")
    planner._llm_decompose = lambda q, ctx: None  # fallback path; _prepare still runs
    return planner


class TestPromptResolution:
    """T008 / FR-003: three-state prompt resolution + no-override fallback."""

    def test_single_se_project_uses_override(self):
        planner = _make_planner()
        planner.execute({"query": "q", "domain_planner_config": {
            "distinct_domain_keys": ["se-project"],
            "relation_vocab": SE_VOCAB,
            "prompt_override": SE_PLANNER_PROMPT,
        }})
        assert planner._system_prompt == SE_PLANNER_PROMPT
        assert planner._relation_vocab == SE_VOCAB

    def test_single_generic_uses_override(self):
        from rag_mcp.config.domain_profiles import NEUTRAL_PLANNER_PROMPT

        planner = _make_planner()
        planner.execute({"query": "q", "domain_planner_config": {
            "distinct_domain_keys": ["generic"],
            "relation_vocab": [],
            "prompt_override": NEUTRAL_PLANNER_PROMPT,
        }})
        assert planner._system_prompt == NEUTRAL_PLANNER_PROMPT
        assert planner._relation_vocab == []

    def test_heterogeneous_falls_back_to_neutral_template(self):
        from rag_mcp.config.domain_profiles import render_neutral_planner_prompt

        planner = _make_planner()
        planner.execute({"query": "q", "domain_planner_config": {
            "distinct_domain_keys": ["se-project", "generic"],
            "relation_vocab": SE_VOCAB,
            # A single-domain override is present but MUST be ignored (FR-003).
            "prompt_override": SE_PLANNER_PROMPT,
        }})
        assert planner._system_prompt == render_neutral_planner_prompt(SE_VOCAB)
        assert planner._system_prompt != SE_PLANNER_PROMPT
        assert planner._relation_vocab == SE_VOCAB

    def test_no_override_uses_neutral_template(self):
        from rag_mcp.config.domain_profiles import render_neutral_planner_prompt

        planner = _make_planner()
        vocab = ["foo", "bar"]
        planner.execute({"query": "q", "domain_planner_config": {
            "distinct_domain_keys": ["custom"],
            "relation_vocab": vocab,
            "prompt_override": None,
        }})
        assert planner._system_prompt == render_neutral_planner_prompt(vocab)
        assert planner._relation_vocab == vocab

    def test_config_less_defaults_to_se_project(self):
        """No domain_planner_config -> 1.0 se-project default (backward compat)."""
        planner = _make_planner()
        planner.execute({"query": "q"})
        assert planner._system_prompt == SE_PLANNER_PROMPT
        assert planner._relation_vocab == SE_VOCAB
class TestSeProjectDatasetStructuralEquivalence:
    """T015 structural layer at dataset scope (SC-001(2)/R5(2)).

    Every entry of the agentic comparison corpus (base eval_dataset.json +
    the 005 agentic batch, i.e. the combined set run by
    run_agentic_comparison.py) resolves through the se-project domain profile
    to the verbatim 1.0 planner prompt + 4-value relation vocabulary,
    byte-identical to the 1.0 config-less default — so the structured planner
    output (signals/relation_directions) is equivalent for the whole dataset,
    not just the 3-item offline proxy.
    """

    def _combined_dataset(self):
        import json
        from pathlib import Path

        repo = Path(__file__).resolve().parents[3]
        with open(repo / "eval" / "eval_dataset.json", encoding="utf-8") as f:
            base = json.load(f)
        with open(repo / "eval" / "agentic_eval_dataset.json", encoding="utf-8") as f:
            agentic = json.load(f)
        return [*base, *agentic]

    def test_combined_dataset_is_non_empty(self):
        assert len(self._combined_dataset()) > 0

    def test_all_items_byte_equivalent_to_1_0_default(self):
        from rag_mcp.config.domain_profiles import SE_PLANNER_PROMPT

        cfg = {
            "distinct_domain_keys": ["se-project"],
            "relation_vocab": SE_VOCAB,
            "prompt_override": SE_PLANNER_PROMPT,
        }
        for entry in self._combined_dataset():
            query = entry.get("query", "")
            se = _make_planner()
            se_out = se.execute({"query": query, "domain_planner_config": dict(cfg)})
            legacy = _make_planner()
            legacy_out = legacy.execute({"query": query})
            assert se._system_prompt == legacy._system_prompt == SE_PLANNER_PROMPT
            assert se._relation_vocab == legacy._relation_vocab == SE_VOCAB
            assert se_out == legacy_out, f"structural drift for {query!r}"

