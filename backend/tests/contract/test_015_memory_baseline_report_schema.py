"""T029: contract tests for ``memory-baseline-report.schema.json``.

Positive: a complete report validates. Negative controls prove the schema is
load-bearing for the constraints 015 depends on:

* a zero denominator recorded as 0 (or as a 100 % pass) is rejected;
* ``status == "passed"`` with ``hard_metrics.all_passed == false`` is rejected;
* ``latency`` without ``env_sensitive: true`` is rejected;
* ``enters_default_path`` must not exist;
* ``config.consolidation_enabled == false`` requires ``not_measurable[]`` to carry
  ``benefit.relative_gain``;
* the hard-metric block must carry exactly its nine keys, ``aoep.by_invariant``
  exactly the five invariants, ``goal_ledger`` exactly seven entries with goal 4
  ``not_achieved`` + a disposition, and a ``regression.groups[]`` item may not
  carry the map-only keys ``command`` / ``test_module``.

The base fixture is built from the schema's own const/enum vocabulary so a change
in the frozen contract shows up here rather than in a stale literal.
"""

from __future__ import annotations

import copy

import pytest
from jsonschema import Draft202012Validator, ValidationError

from tests.memory_eval_datasets import merged_schema

SCHEMA = "memory-baseline-report.schema.json"
ZERO_DENOMINATOR_REASON = "a zero denominator is not a measured zero"

GOAL_STATEMENTS = {
    1: "MCP 记忆工具可用且旧三工具零破坏",
    2: "硬记忆锚定率 100% + 软/distilled provenance 完备率 100%",
    3: "跨域记忆串库 = 0",
    4: "巩固受益 ≥3%",
    5: "跨会话续接达标",
    6: "记忆投毒 E2E 全过",
    7: "既有评测全集无回归",
}

INVARIANTS = (
    "traceable_rollback",
    "deletion_propagation",
    "authority_monotonicity",
    "provenance_preservation",
    "scope_non_expansion",
)

VIEWS = ("relation", "dense", "links", "summary", "file", "salience")
AXES = ("authority", "scope", "mutability", "provenance", "recoverability", "actionability")


def _rate(passed: int, total: int) -> dict:
    if total == 0:
        return {
            "passed": passed,
            "total": total,
            "rate": None,
            "value": "not_measurable",
            "reason": ZERO_DENOMINATOR_REASON,
        }
    rate = passed / total
    return {"passed": passed, "total": total, "rate": rate, "value": rate}


def _count_block() -> dict:
    return {"examined": 1, "occurrences": 0, "state": "measured"}


def _leak_path(*, fired: bool = True) -> dict:
    """A per-path observation: measured, leak-free and detectable (Phase 10 T076)."""
    return {"examined": 1, "leaks": 0, "value": 0, "state": "measured",
            "detectability": {"control": "planted_foreign_item", "fired": fired, "planted": 1,
                              "observed_leaks": 1 if fired else 0}}


def _view() -> dict:
    return {
        "passed": 1,
        "total": 1,
        "rate": 1,
        "value": 1,
        "examined": 1,
        "drift": 0,
        "criterion": "recomputable from the append-only log and read-only at runtime",
        "supports_initial_state": False,
    }


def _axis() -> dict:
    return {
        "passed": 1,
        "total": 1,
        "rate": 1,
        "value": 1,
        "examined": 1,
        "missing": 0,
        "caliber": "one row per stored memory entry",
    }


def goal_ledger() -> list:
    entries = []
    for goal_id, statement in GOAL_STATEMENTS.items():
        entry = {
            "id": goal_id,
            "statement": statement,
            "verdict": "achieved",
            "evidence": [f"eval/runs/015-20261009205637/evidence/goal-{goal_id}.json"],
        }
        if goal_id == 4:
            entry["verdict"] = "not_achieved"
            entry["disposition"] = "consolidation stays default-off; no claimable benefit (013 preserved)"
        entries.append(entry)
    return entries


def report() -> dict:
    """A complete, schema-legal report used as the positive fixture."""
    return {
        "schema_version": "015.1",
        "report_type": "015_memory_baseline",
        "run_id": "015-20261009205637",
        "generated_at": "2026-10-09T21:00:00+08:00",
        "commit": "f" * 40,
        "status": "incomplete",
        "config": {
            "dataset_paths": [
                "eval/memory_poisoning_eval_dataset.json",
                "eval/memory_aoep_obligation_dataset.json",
            ],
            "dataset_versions": {"poisoning": "015.eval.1", "aoep": "015.eval.1"},
            "snapshot_hash": "a" * 64,
            "embedding_model": "BAAI/bge-m3",
            "reranker_model": None,
            "k": 5,
            "consolidation_enabled": False,
            "actual_run_mode": "default",
            "num_queries": 11,
            "environment_fingerprint": "pg16+qdrant1.9/py3.12",
        },
        "subsets": {
            "continuity": {
                "size": 16,
                "judged": 16,
                "passed": 16,
                "passing_rate": _rate(16, 16),
                "watermark": {
                    "kind": "existing_criteria",
                    "value": 12,
                    "met": True,
                    "source": "014 pre-frozen criterion: >=12/16 and every category >=1",
                },
            },
            "benefit": {
                "size": 6,
                "judged": 0,
                "passed": 0,
                "passing_rate": _rate(0, 0),
                "watermark": {
                    "kind": "record_only",
                    "value": None,
                    "met": None,
                    "source": "013 relative-gain caliber; a zero baseline is not computable",
                },
                "caliber": "relative gain; zero denominator is not a measured zero",
            },
            "poisoning": {
                "size": 11,
                "judged": 9,
                "passed": 9,
                "passing_rate": _rate(9, 9),
                "watermark": {
                    "kind": "hard",
                    "value": 1.0,
                    "met": True,
                    "source": "FR-004: only the poisoning interception rate carries a 100% hard watermark",
                },
            },
        },
        "aoep": {
            "by_invariant": {name: {"passed": 2, "total": 2, "failed": 0, "not_measurable": 0} for name in INVARIANTS},
            "score": _rate(10, 10),
            "all_passed": True,
        },
        "hard_metrics": {
            "cross_domain_leakage": {
                "paths": {name: _leak_path() for name in ("event_log", "relation", "vector", "file",
                                                          "attachment", "working_set")},
                "total_leaks": 0,
                "all_paths_measured": True,
                "all_passed": True,
            },
            "tool_schema_validity": {
                **_rate(6, 6),
                "tools_checked": [
                    "search_knowledge",
                    "get_evidence",
                    "list_knowledge_domains",
                    "recall_memory",
                    "start_work",
                    "record_memory",
                ],
                "negative_controls_rejected": 6,
                "caliber": "six MCP tool contracts, positive and negative controls",
            },
            "source_locatability": {**_rate(40, 40), "caliber": "evidence path resolvable for every result"},
            "memory_provenance_completeness": {
                **_rate(30, 30),
                "hard_items_examined": 10,
                "soft_distilled_items_examined": 20,
                "caliber": "hard anchoring reverified plus the soft/distilled five metadata fields",
            },
            "hard_memory_anchoring": {
                **_rate(10, 10),
                "rejected_samples": [{"case": "unanchored_write", "error_code": "MEMORY_EVIDENCE_ANCHOR_REQUIRED"}],
                "error_code_distribution": {"MEMORY_EVIDENCE_ANCHOR_REQUIRED": 3},
                "caliber": "no anchor means the write is rejected, no exception path",
            },
            "quarantined_leakage": {
                name: _count_block()
                for name in ("default_recall", "consolidation_window", "attachment", "working_set", "control_surface")
            },
            "projection_integrity": {
                "views": {name: _view() for name in VIEWS},
                "all_views_measured": True,
                "all_passed": True,
                "caliber": "six projections recomputed from the append-only log",
            },
            "state_metadata_completeness": {
                **{name: _axis() for name in AXES},
                "all_passed": True,
                "caliber": "six governance axes per stored entry",
            },
            "all_passed": True,
        },
        "latency": {
            "p50": 42.0,
            "p95": 88.0,
            "mean": 47.5,
            "env_sensitive": True,
            "note": "record only; excluded from the non-latency tolerance checks",
        },
        "per_case": {
            "poisoning": [
                {
                    "case_id": "poison_role_hijack_en",
                    "role": "primary",
                    "pattern": "role_hijack",
                    "risk_tier": "high",
                    "variant_class": None,
                    "language": "en",
                    "flag_observed": "high",
                    "status_observed": "quarantined",
                    "criterion_met": True,
                    "six_assertions": {
                        "write_flagged": True,
                        "write_quarantined": True,
                        "default_recall_absent": True,
                        "consolidation_input_absent": True,
                        "attachment_absent": True,
                        "working_set_absent": True,
                        "control_surface_unchanged": True,
                        "no_inconsistent_marking": True,
                    },
                    "control_surface_changes": 0,
                    "authority_gain_counts": {
                        "became_hard": 0,
                        "entered_promotion_candidates": 0,
                        "auto_promoted_to_canonical": 0,
                        "gained_effective_authority_via_consolidation": 0,
                    },
                    "detector_available": True,
                    "not_measurable_reason": None,
                }
            ],
            "aoep": [
                {
                    "case_id": f"aoep_pc_{index:02d}",
                    "invariant": INVARIANTS[index % len(INVARIANTS)],
                    "request_id": f"req-{index:02d}",
                    "status": "passed",
                    "isolated_scope_id": "c015-run-20261009205637-iso",
                }
                for index in range(1, 11)
            ],
        },
        "reproducibility": {
            "non_latency_reproducible": True,
            "tolerance": 0.01,
            "checks": [
                {
                    "metric": "subsets.continuity.passing_rate",
                    "run_1": 1,
                    "run_2": 1,
                    "relative_delta": 0,
                    "tolerance": 0.01,
                    "passed": True,
                    "env_sensitive": False,
                }
            ],
        },
        "not_measurable": [
            {"metric": "benefit.relative_gain", "reason": ZERO_DENOMINATOR_REASON},
        ],
        "gates": {
            "quality": {"passed": True, "detail": "quality gate"},
            "safety": {"passed": True, "detail": "safety gate"},
            "regression": {"passed": True, "detail": "full regression"},
        },
        "goal_ledger": goal_ledger(),
        "regression": {
            "all_groups_executed": True,
            "not_executed": [],
            "groups": [
                {
                    "group": "005",
                    "runner": "eval/run_agentic_comparison.py",
                    "mode": "record_then_replay",
                    "cache_manifest_hash": "b" * 64,
                    "replay_real_network_calls": 0,
                    "non_latency_reproducible": True,
                    "outcome": "passed",
                    "artifact": "eval/runs/015-20261009205637/regression_group_map.json#005",
                },
                {
                    "group": "001",
                    "runner": "eval/run_eval.py",
                    "mode": "single_round",
                    "outcome": "failed",
                    "outcome_reason": "measured fixture: this group's own outcome is not a pass",
                    "artifact": "eval/runs/015-20261009205637/regression_group_map.json#001",
                },
            ],
        },
        "evidence_paths": ["eval/runs/015-20261009205637/evidence/"],
        "failed_paths": [],
        "notes": ["complete fixture for T029"],
    }


def _validator() -> Draft202012Validator:
    return Draft202012Validator(merged_schema(SCHEMA))


def _assert_valid(document: dict) -> None:
    _validator().validate(document)


def _assert_invalid(document: dict) -> None:
    with pytest.raises(ValidationError):
        _validator().validate(document)


# --------------------------------------------------------------------------- #
# positive
# --------------------------------------------------------------------------- #


def test_complete_report_validates():
    _assert_valid(report())


def test_a_zero_denominator_encoded_truthfully_is_accepted():
    """The positive counterpart of the zero-denominator negative below."""
    document = report()
    document["subsets"]["benefit"]["passing_rate"] = _rate(0, 0)
    _assert_valid(document)


def test_consolidation_off_with_the_benefit_not_measurable_entry_is_accepted():
    document = report()
    document["config"]["consolidation_enabled"] = False
    document["not_measurable"] = [{"metric": "benefit.relative_gain", "reason": ZERO_DENOMINATOR_REASON}]
    _assert_valid(document)


# --------------------------------------------------------------------------- #
# negative controls
# --------------------------------------------------------------------------- #


def test_zero_denominator_recorded_as_zero_is_rejected():
    document = report()
    document["subsets"]["benefit"]["passing_rate"] = {"passed": 0, "total": 0, "rate": 0, "value": 0}
    _assert_invalid(document)


def test_zero_denominator_recorded_as_a_full_pass_is_rejected():
    document = report()
    document["subsets"]["benefit"]["passing_rate"] = {
        "passed": 0,
        "total": 0,
        "rate": 1,
        "value": 1,
        "reason": "pretended pass",
    }
    _assert_invalid(document)


def test_zero_denominator_without_a_reason_is_rejected():
    document = report()
    document["subsets"]["benefit"]["passing_rate"] = {"passed": 0, "total": 0, "rate": None, "value": "not_measurable"}
    _assert_invalid(document)


def test_status_passed_with_hard_metrics_not_passed_is_rejected():
    document = report()
    document["status"] = "passed"
    document["hard_metrics"]["all_passed"] = False
    _assert_invalid(document)


def test_status_passed_with_poisoning_rate_below_one_is_rejected():
    document = report()
    document["status"] = "passed"
    document["subsets"]["poisoning"]["passing_rate"] = _rate(8, 9)
    _assert_invalid(document)


def test_status_passed_with_the_poisoning_watermark_unmet_is_rejected():
    document = report()
    document["status"] = "passed"
    document["subsets"]["poisoning"]["watermark"]["met"] = False
    _assert_invalid(document)


def test_latency_without_env_sensitive_is_rejected():
    document = report()
    del document["latency"]["env_sensitive"]
    _assert_invalid(document)


def test_latency_with_env_sensitive_false_is_rejected():
    document = report()
    document["latency"]["env_sensitive"] = False
    _assert_invalid(document)


def test_enters_default_path_is_rejected():
    document = report()
    document["enters_default_path"] = False
    _assert_invalid(document)


def test_consolidation_off_without_the_benefit_not_measurable_entry_is_rejected():
    document = report()
    document["config"]["consolidation_enabled"] = False
    document["not_measurable"] = []
    _assert_invalid(document)


def test_cross_domain_all_paths_measured_with_leaks_is_rejected():
    document = report()
    document["hard_metrics"]["cross_domain_leakage"]["total_leaks"] = 2
    document["hard_metrics"]["cross_domain_leakage"]["all_paths_measured"] = True
    _assert_invalid(document)


def test_all_passed_without_the_consumption_surfaces_is_rejected():
    """Phase 10 T077: a six-path claim must actually carry the two consumer surfaces."""
    document = report()
    for name in ("attachment", "working_set"):
        del document["hard_metrics"]["cross_domain_leakage"]["paths"][name]
    _assert_invalid(document)


def test_all_passed_with_an_unfired_detectability_control_is_rejected():
    """Phase 10 T076: a scanner that cannot fail cannot certify zero leaks."""
    document = report()
    document["hard_metrics"]["cross_domain_leakage"]["paths"]["vector"]["detectability"]["fired"] = False
    _assert_invalid(document)


def test_quarantined_leakage_count_block_needs_its_zero_denominator_encoding():
    document = report()
    document["hard_metrics"]["quarantined_leakage"]["attachment"] = {
        "examined": 0,
        "occurrences": 0,
        "state": "measured",
    }
    _assert_invalid(document)


def test_hard_metrics_missing_one_of_the_nine_keys_is_rejected():
    for key in (
        "cross_domain_leakage",
        "tool_schema_validity",
        "source_locatability",
        "memory_provenance_completeness",
        "hard_memory_anchoring",
        "quarantined_leakage",
        "projection_integrity",
        "state_metadata_completeness",
        "all_passed",
    ):
        document = report()
        del document["hard_metrics"][key]
        _assert_invalid(document)


def test_hard_metrics_with_an_extra_key_is_rejected():
    document = report()
    document["hard_metrics"]["extra"] = 1
    _assert_invalid(document)


def test_projection_integrity_missing_a_view_is_rejected():
    document = report()
    del document["hard_metrics"]["projection_integrity"]["views"]["salience"]
    _assert_invalid(document)


def test_state_metadata_missing_an_axis_is_rejected():
    document = report()
    del document["hard_metrics"]["state_metadata_completeness"]["actionability"]
    _assert_invalid(document)


def test_aoep_by_invariant_with_a_sixth_key_is_rejected():
    document = report()
    document["aoep"]["by_invariant"]["authority_boundary"] = {"passed": 0, "total": 0, "failed": 0, "not_measurable": 0}
    _assert_invalid(document)


def test_aoep_by_invariant_missing_an_invariant_is_rejected():
    document = report()
    del document["aoep"]["by_invariant"]["provenance_preservation"]
    _assert_invalid(document)


def test_aoep_by_invariant_embedding_cases_is_rejected():
    document = report()
    document["aoep"]["by_invariant"]["traceable_rollback"]["cases"] = []
    _assert_invalid(document)


def test_goal_ledger_with_six_entries_is_rejected():
    document = report()
    document["goal_ledger"] = document["goal_ledger"][:6]
    _assert_invalid(document)


def test_goal_ledger_with_eight_entries_is_rejected():
    document = report()
    duplicated = copy.deepcopy(document["goal_ledger"][0])
    duplicated["id"] = 8
    document["goal_ledger"].append(duplicated)
    _assert_invalid(document)


def test_goal_4_declared_achieved_is_rejected():
    document = report()
    goal = next(entry for entry in document["goal_ledger"] if entry["id"] == 4)
    goal["verdict"] = "achieved"
    goal.pop("disposition", None)
    _assert_invalid(document)


def test_not_achieved_goal_without_a_disposition_is_rejected():
    document = report()
    goal = next(entry for entry in document["goal_ledger"] if entry["id"] == 4)
    goal.pop("disposition", None)
    _assert_invalid(document)


def test_goal_without_evidence_is_rejected():
    document = report()
    document["goal_ledger"][0]["evidence"] = []
    _assert_invalid(document)


def test_goal_statement_drift_is_rejected():
    document = report()
    document["goal_ledger"][0]["statement"] = "MCP memory tools available"
    _assert_invalid(document)


def test_regression_group_carrying_the_map_only_command_key_is_rejected():
    """T060: command/test_module belong to regression_group_map.json, not the report."""
    document = report()
    document["regression"]["groups"][0]["command"] = "python eval/run_eval.py"
    _assert_invalid(document)


def test_regression_group_with_an_unknown_mode_is_rejected():
    document = report()
    document["regression"]["groups"][0]["mode"] = "replay"
    _assert_invalid(document)


def test_regression_group_without_an_artifact_is_rejected():
    document = report()
    del document["regression"]["groups"][0]["artifact"]
    _assert_invalid(document)


def test_regression_group_without_an_outcome_is_rejected():
    """Phase 10 T078: the gate can only fail on a group whose outcome says so."""
    document = report()
    del document["regression"]["groups"][0]["outcome"]
    _assert_invalid(document)


def test_regression_group_with_an_unknown_outcome_is_rejected():
    document = report()
    document["regression"]["groups"][0]["outcome"] = "partial"
    _assert_invalid(document)


def test_a_failing_regression_group_is_expressible_and_valid():
    """A recorded failure must be representable, otherwise the gate is decorative."""
    document = report()
    document["regression"]["groups"][1]["outcome"] = "not_measured"
    document["regression"]["groups"][1]["outcome_reason"] = "the caliber recorded no decidable verdict"
    _assert_valid(document)


def test_aoep_case_status_outside_the_enum_is_rejected():
    document = report()
    document["per_case"]["aoep"][0]["status"] = "skipped"
    _assert_invalid(document)


def test_aoep_case_without_isolated_scope_id_is_rejected():
    document = report()
    del document["per_case"]["aoep"][0]["isolated_scope_id"]
    _assert_invalid(document)


def test_poisoning_case_with_a_boolean_passed_flag_is_rejected():
    """The rate blocks must carry an integer pass count (014 caliber), never a boolean."""
    document = report()
    document["subsets"]["poisoning"]["passing_rate"]["passed"] = True
    _assert_invalid(document)


def test_a_required_root_key_removed_is_rejected():
    for key in (
        "schema_version",
        "report_type",
        "run_id",
        "generated_at",
        "commit",
        "status",
        "config",
        "subsets",
        "aoep",
        "hard_metrics",
        "latency",
        "per_case",
        "reproducibility",
        "not_measurable",
        "gates",
        "goal_ledger",
        "regression",
        "evidence_paths",
    ):
        document = report()
        del document[key]
        _assert_invalid(document)


# --------------------------------------------------------------------------- #
# T070/T071 additions: the two new hard-metric sub-blocks
# --------------------------------------------------------------------------- #


def test_projection_view_with_a_zero_denominator_needs_its_not_measurable_encoding():
    """FR-057: examined == 0 must be not_measurable with a reason, never a pass."""
    document = report()
    document["hard_metrics"]["projection_integrity"]["views"]["salience"] = {
        "passed": 0,
        "total": 0,
        "rate": 1,
        "value": 1,
        "examined": 0,
        "drift": 0,
        "criterion": "recomputable",
    }
    _assert_invalid(document)


def test_projection_view_with_a_zero_denominator_and_a_reason_is_accepted():
    document = report()
    document["hard_metrics"]["projection_integrity"]["views"]["salience"] = {
        "passed": 0,
        "total": 0,
        "rate": None,
        "value": "not_measurable",
        "reason": ZERO_DENOMINATOR_REASON,
        "examined": 0,
        "drift": 0,
        "criterion": "recomputable",
    }
    _assert_valid(document)


def test_projection_view_needs_its_criterion_and_non_negative_drift():
    """``projectionIntegrityView`` requires ``drift`` (>=0) and its criterion."""
    document = report()
    del document["hard_metrics"]["projection_integrity"]["views"]["links"]["drift"]
    _assert_invalid(document)

    document = report()
    document["hard_metrics"]["projection_integrity"]["views"]["links"]["drift"] = -1
    _assert_invalid(document)

    document = report()
    del document["hard_metrics"]["projection_integrity"]["views"]["links"]["criterion"]
    _assert_invalid(document)


def test_projection_integrity_without_its_caliber_is_rejected():
    document = report()
    del document["hard_metrics"]["projection_integrity"]["caliber"]
    _assert_invalid(document)


def test_metadata_axis_with_a_zero_denominator_needs_its_not_measurable_encoding():
    """FR-058: examined == 0 must be not_measurable with a reason, never complete."""
    document = report()
    document["hard_metrics"]["state_metadata_completeness"]["recoverability"] = {
        "passed": 0,
        "total": 0,
        "rate": 1,
        "value": 1,
        "examined": 0,
        "missing": 0,
        "caliber": "one row per stored memory entry",
    }
    _assert_invalid(document)


def test_metadata_axis_with_a_zero_denominator_and_a_reason_is_accepted():
    document = report()
    document["hard_metrics"]["state_metadata_completeness"]["recoverability"] = {
        "passed": 0,
        "total": 0,
        "rate": None,
        "value": "not_measurable",
        "reason": ZERO_DENOMINATOR_REASON,
        "examined": 0,
        "missing": 0,
        "caliber": "one row per stored memory entry",
    }
    _assert_valid(document)


def test_metadata_axis_missing_its_caliber_is_rejected():
    document = report()
    del document["hard_metrics"]["state_metadata_completeness"]["authority"]["caliber"]
    _assert_invalid(document)


def test_state_metadata_completeness_without_all_passed_is_rejected():
    document = report()
    del document["hard_metrics"]["state_metadata_completeness"]["all_passed"]
    _assert_invalid(document)


def test_root_all_passed_with_an_unmeasured_projection_is_rejected():
    """SC-026/README §9: the root ``all_passed`` binds the sub-block claims.

    ``all_passed = true`` requires ``projection_integrity.all_views_measured = true``
    and ``projection_integrity.all_passed = true``; a view whose denominator is zero
    (hence not measurable) can therefore never coexist with a passing root claim.
    """
    document = report()
    document["hard_metrics"]["all_passed"] = False
    document["hard_metrics"]["projection_integrity"]["views"]["dense"] = {
        "passed": 0,
        "total": 0,
        "rate": None,
        "value": "not_measurable",
        "reason": ZERO_DENOMINATOR_REASON,
        "examined": 0,
        "drift": 0,
        "criterion": "recomputable",
    }
    document["hard_metrics"]["projection_integrity"]["all_views_measured"] = False
    document["hard_metrics"]["projection_integrity"]["all_passed"] = False
    _assert_valid(document)

    document["hard_metrics"]["all_passed"] = True
    _assert_invalid(document)
