"""Dynamic relation-vocabulary unit tests (009, T013/T014).

FR-006/FR-008/SC-004: relation_directions vocabulary and NODE_SCHEMA are derived
dynamically from the domain profile graph_relations keys (research R2/R4). A
no-graph domain (empty vocab) omits relation_directions/graph_hop, drops 'graph'
from signals, and cannot plan graph traversal (clarification Q4).
"""

from __future__ import annotations

from jsonschema import Draft202012Validator

from rag_mcp.agents.query_planner import QueryPlannerAgent, _build_node_schema
from rag_mcp.config.domain_profiles import relation_vocab_union

SE_VOCAB = ["calls", "called_by", "fk_references", "fk_referenced_by"]


def _make_planner(llm_response):
    planner = QueryPlannerAgent(model_and_version="test-v1")
    planner._llm_decompose = lambda q, ctx: llm_response
    return planner


def _sub_problem_props(schema: dict) -> dict:
    return schema["properties"]["sub_problems"]["items"]["properties"]


class TestBuildNodeSchema:
    """T013: _build_node_schema reflects the relation vocabulary."""

    def test_se_project_schema_has_four_value_enum_and_graph(self):
        schema = _build_node_schema(SE_VOCAB)
        props = _sub_problem_props(schema)
        assert "relation_directions" in props
        assert set(props["relation_directions"]["items"]["enum"]) == set(SE_VOCAB)
        assert "graph_hop" in props
        assert props["graph_hop"]["minimum"] == 1
        assert props["graph_hop"]["maximum"] == 3
        assert props["signals"]["items"]["enum"] == ["dense", "sparse", "graph"]

    def test_generic_schema_omits_directions_and_graph(self):
        schema = _build_node_schema([])
        props = _sub_problem_props(schema)
        assert "relation_directions" not in props
        assert "graph_hop" not in props
        assert props["signals"]["items"]["enum"] == ["dense", "sparse"]

    def test_heterogeneous_union_schema(self):
        vocab = relation_vocab_union([{"calls": ["out"]}, {"fk_references": ["in"]}, {}])
        schema = _build_node_schema(vocab)
        props = _sub_problem_props(schema)
        assert set(props["relation_directions"]["items"]["enum"]) == set(vocab)


class TestRelationVocabUnion:
    """T013 / R4: relation vocab is the deterministic union of graph_relations keys."""

    def test_se_project_union_is_1_0_order(self):
        assert relation_vocab_union([dict.fromkeys(SE_VOCAB)]) == SE_VOCAB

    def test_generic_union_is_empty(self):
        assert relation_vocab_union([{}]) == []

    def test_heterogeneous_union(self):
        vocab = relation_vocab_union([{"calls": ["out", "in"]}, {}])
        assert vocab == ["calls"]

    def test_custom_union_sorted(self):
        vocab = relation_vocab_union([{"zzz": ["out"], "aaa": ["in"]}])
        assert vocab == ["aaa", "zzz"]


class TestEmptyVocabBehaviour:
    """T014 / FR-008: a no-graph domain cannot plan graph traversal."""

    def _ctx(self, vocab):
        return {
            "query": "q",
            "domain_planner_config": {
                "distinct_domain_keys": ["generic"] if not vocab else ["se-project"],
                "relation_vocab": vocab,
                "prompt_override": None,
            },
        }

    def test_empty_vocab_default_directions_is_empty(self):
        planner = _make_planner(None)
        planner._prepare(self._ctx([]))
        assert planner.get_default_directions() == []

    def test_empty_vocab_drops_graph_signal(self):
        planner = _make_planner([
            {"query": "q", "signals": ["graph"], "relation_directions": ["calls"]},
        ])
        out = planner.execute(self._ctx([]))
        sp = out["sub_problems"][0]
        assert "graph" not in sp["signals"]
        assert "relation_directions" not in sp
        assert "graph_hop" not in sp

    def test_empty_vocab_fallback_omits_directions_and_is_schema_valid(self):
        planner = _make_planner(None)
        out = planner.execute(self._ctx([]))
        sp = out["sub_problems"][0]
        assert "relation_directions" not in sp
        assert "graph_hop" not in sp
        result = planner.validate_output(out)
        assert result.schema_valid is True

    def test_empty_vocab_schema_rejects_graph_fields(self):
        # The dynamic schema for a no-graph domain rejects graph signal/fields.
        validator = Draft202012Validator(_build_node_schema([]))
        errors = list(validator.iter_errors({
            "sub_problems": [{
                "sub_problem_id": 1,
                "query": "q",
                "signals": ["graph"],
            }],
            "schema_valid": True,
        }))
        assert errors, "graph signal must be rejected for a no-graph domain"


class TestSeProjectVocabBehaviour:
    """T013 / FR-006: se-project keeps the 1.0 four-value vocabulary."""

    def _ctx(self):
        return {
            "query": "q",
            "domain_planner_config": {
                "distinct_domain_keys": ["se-project"],
                "relation_vocab": SE_VOCAB,
                "prompt_override": None,
            },
        }

    def test_se_project_default_directions_are_four_values(self):
        planner = _make_planner(None)
        planner._prepare(self._ctx())
        assert planner.get_default_directions() == SE_VOCAB

    def test_se_project_graph_signal_kept(self):
        planner = _make_planner([
            {"query": "q", "signals": ["graph"], "relation_directions": ["calls"]},
        ])
        out = planner.execute(self._ctx())
        sp = out["sub_problems"][0]
        assert "graph" in sp["signals"]
        assert sp["relation_directions"] == ["calls"]
