"""T057: 014 continuity comparison-report contract test (US5).

Pins the report shape of ``eval/run_memory_comparison.py``
(``contracts/continuity-evaluation-contract.md`` §5) and the gate semantics of
T056:

* every top-level key of the frozen report contract exists, ``schema_version``
  is ``014.1``, and every query row carries **both** arms' hits/misses/forbidden
  items, latency and cost, with a difference explanation; a failed path is never
  omitted;
* the baseline arm is driven without ``session_id``/``memory_context``, holds no
  shared session or delivered set, and its response is asserted to carry **zero
  new fields** (``related_memories``/``memory_notice``/``counts``/``working_set``);
* quality is ``relative_gain >= 3%`` **or** the pre-frozen explicit criterion;
  ``without_memory == 0`` is ``BASELINE_ZERO_NOT_COMPUTABLE`` and is never
  replaced by a tiny/infinite substitute; the three gates plus
  ``reproducibility == 'passed'`` are required for ``default_enable_eligible``;
* the report is evidence only: it never flips a configuration switch, and the
  CLI refuses an existing ``--output`` with exit code 2 (0 pass / 1 fail /
  2 incomplete evidence).

Pure tests: no database, store, MCP endpoint or provider is required.  The
record/replay run itself (T058) needs the closed PostgreSQL/Qdrant/MCP services
and is therefore not executed here.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _path in (ROOT / "eval", ROOT / "backend" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from memory_continuity_support import (  # noqa: E402
    ARMS,
    FULL_INTEGRITY_KEYS,
    K,
    REPORT_KEYS,
    ROUNDS,
    ZERO_BASELINE_CODE,
    ZERO_SAFETY_KEYS,
    ArmObservation,
    CachedToolFailure,
    CacheIncomplete,
    ComparisonFailed,
    ToolCallCache,
    allocate_identities,
    assert_baseline_zero_new_fields,
    assert_independent,
    baseline_parameters,
    arm_parameters,
    arm_policy,
    completion_rate,
    entry_path,
    explicit_criterion_check,
    load_dataset,
    redundancy,
    relative_gain,
    replay_response_audit,
    task_complete,
    validate_comparison_report,
    zero_new_fields,
)

from run_memory_comparison import (  # noqa: E402
    EXIT_FAILED,
    EXIT_INCOMPLETE,
    EXIT_OK,
    build_parser,
    build_report,
    default_enable_eligible,
    exit_code_for,
    main,
    quality_gate,
    regression_gate,
    safety_gate,
)

DATASET_PATH = ROOT / "eval" / "memory_continuity_eval_dataset.json"
DATASET_SHA256 = "8a5fb42d74bdf37d794dde15804a3d97316ff5d14c8ab122350df8dede79ffc4"
GREEN_LEGACY_NEW_FIELDS = ("related_memories", "memory_notice", "counts", "working_set")


@pytest.fixture(scope="module")
def dataset() -> dict:
    return load_dataset(DATASET_PATH)


def _ids_with_all_categories(dataset: dict, count: int) -> list:
    """A deterministic query-id selection that covers the four categories."""
    by_category: dict[str, list] = {}
    for query in dataset["queries"]:
        by_category.setdefault(query["category"], []).append(query["query_id"])
    chosen = [by_category[category][0] for category in sorted(by_category)]
    for query in dataset["queries"]:
        if len(chosen) >= count:
            break
        if query["query_id"] not in chosen:
            chosen.append(query["query_id"])
    return chosen[:count]


def observations(dataset: dict, *, complete_without=(), complete_with=(), duplicate_delivery=False):
    """Record and replay rows for both arms over the frozen query set."""
    rows = {}
    for query in dataset["queries"]:
        required = [item["locator"] for item in query["required_items"]]
        for arm in ARMS:
            complete = query["query_id"] in (complete_with if arm == "with_memory" else complete_without)
            delivered = list(required) if complete else []
            if duplicate_delivery and arm == "with_memory" and complete and delivered:
                delivered = delivered + [delivered[0]]
            observation = ArmObservation(
                query_id=query["query_id"], arm=arm, round="record",
                hits=tuple(required) if complete else (),
                cited=tuple(required) if complete else (),
                delivered=tuple(delivered), latency_ms=12.5, cost_usd=0.0)
            rows[("record", arm, query["query_id"])] = observation
            rows[("replay", arm, query["query_id"])] = ArmObservation(
                query_id=query["query_id"], arm=arm, round="replay",
                hits=observation.hits, cited=observation.cited, delivered=observation.delivered,
                latency_ms=13.0, cost_usd=0.0)
    return rows


def cache_block(*, replay_real_network_calls=0, evidence_complete=True, response_match_rate=1.0):
    return {"path": "cache", "manifest_hash": "a" * 64, "expected_keys": 4,
            "recorded_success": 4, "recorded_failure": 0, "replayed_success": 4,
            "replayed_failure": 0, "missing": 0, "corrupt": 0, "version_mismatch": 0,
            "record_real_network_calls": 4, "replay_real_network_calls": replay_real_network_calls,
            "response_match_rate": response_match_rate, "evidence_complete": evidence_complete}


def clean_hard_metrics():
    return {**dict.fromkeys(ZERO_SAFETY_KEYS, 0), **dict.fromkeys(FULL_INTEGRITY_KEYS, 1.0)}


def regression_evidence():
    return {"legacy_contract": "eval/011_regression_summary.json", "delivered_ttl_seconds": 3600}


def reproducibility_evidence(*, drift=0.0, match=1.0, replay_calls=0, complete=True):
    return {"max_non_latency_relative_drift": drift, "response_match_rate": match,
            "record_real_network_calls": 4, "replay_real_network_calls": replay_calls,
            "evidence_complete": complete}


def report_for(dataset, *, complete_without, complete_with, **overrides):
    rows = observations(dataset, complete_without=complete_without, complete_with=complete_with,
                        duplicate_delivery=True)
    payload = {
        "faces": {"dataset": {"path": str(DATASET_PATH), "sha256": DATASET_SHA256},
                  "snapshot": {"path": "capsule", "sha256": dataset["snapshot_hash"]}},
        "reproducibility_evidence": reproducibility_evidence(),
        "hard_metrics": clean_hard_metrics(),
        "cache": cache_block(),
        "regression_evidence": regression_evidence(),
        "evidence_paths": [str(DATASET_PATH)],
        "environment": {"host": "contract-test", "database": "isolated 2x2", "qdrant": "isolated 2x2"},
    }
    payload.update(overrides)
    if "observations" in payload:
        rows = payload.pop("observations")
    return build_report(dataset=dataset, observations=rows, **payload)


# ---------------------------------------------------------------------------
# Report schema
# ---------------------------------------------------------------------------

def test_report_top_level_schema_matches_the_frozen_contract(dataset):
    report = report_for(dataset, complete_without=_ids_with_all_categories(dataset, 8),
                        complete_with=_ids_with_all_categories(dataset, 11))
    assert set(report) == set(REPORT_KEYS)
    for key in ("schema_version", "report_type", "generated_at", "commit", "status", "environment",
                "dataset_version", "snapshot_hash", "k", "queries", "aggregates", "relative_gain",
                "zero_baseline", "criteria", "redundancy", "reproducibility", "hard_metrics",
                "gates", "default_enable_eligible", "evidence_paths", "failed_paths"):
        assert key in report, f"the frozen report contract requires {key}"
    assert report["schema_version"] == "014.1"
    assert report["report_type"] == "014_memory_continuity_comparison"
    assert report["k"] == K == 5
    assert report["dataset_version"] == dataset["dataset_version"]
    assert report["snapshot_hash"] == dataset["snapshot_hash"]
    assert set(report["aggregates"]) == set(ARMS)
    assert set(report["gates"]) == {"quality", "safety", "regression"}
    assert report["status"] in ("passed", "failed", "incomplete")
    assert [row["query_id"] for row in report["queries"]] == [
        query["query_id"] for query in dataset["queries"]]


def test_aggregates_and_gates_are_recomputable_from_the_query_rows(dataset):
    complete_without = _ids_with_all_categories(dataset, 8)
    complete_with = _ids_with_all_categories(dataset, 11)
    report = report_for(dataset, complete_without=complete_without, complete_with=complete_with)
    for arm, expected in (("without_memory", complete_without), ("with_memory", complete_with)):
        aggregate = report["aggregates"][arm]
        assert aggregate["completed"] == len(expected)
        assert aggregate["queries"] == len(dataset["queries"])
        assert aggregate["completion_rate"] == pytest.approx(completion_rate(
            [row[arm]["task_complete"] for row in report["queries"]]))
    recomputed = relative_gain(
        report["aggregates"]["without_memory"]["completion_rate"],
        report["aggregates"]["with_memory"]["completion_rate"])
    assert report["relative_gain"]["value"] == pytest.approx(recomputed["value"])
    assert report["relative_gain"]["formula"] == "(with_memory - without_memory) / without_memory"
    assert report["relative_gain"]["threshold"] == 0.03
    # Redundancy is a deterministic auxiliary observation, never a gate.
    assert report["redundancy"]["value"] == pytest.approx(redundancy(
        [locator for row in report["queries"] for locator in row["with_memory"]["delivered"]])["value"])
    assert report["redundancy"]["formula"] == "1 - distinct_items / total_items"
    assert "auxiliary" in report["redundancy"]["scope"]


def test_every_query_row_carries_both_arms_hits_misses_forbidden_items_and_difference(dataset):
    complete_without = _ids_with_all_categories(dataset, 8)
    complete_with = _ids_with_all_categories(dataset, 11)
    report = report_for(dataset, complete_without=complete_without, complete_with=complete_with)
    for row, query in zip(report["queries"], dataset["queries"]):
        assert row["category"] == query["category"] and row["language"] == query["language"]
        assert row["criterion"] == query["criterion"]
        assert isinstance(row["difference"], str) and row["difference"]
        for arm in ARMS:
            block = row[arm]
            for key in ("task_complete", "hit", "missing", "uncited", "forbidden", "delivered",
                        "latency_ms", "cost_usd"):
                assert key in block, f"query {row['query_id']} {arm} is missing {key}"
            assert isinstance(block["task_complete"], bool)
            assert block["latency_ms"] is not None or block["latency_ms"] is None
        expected = query["query_id"] in complete_with
        assert row["with_memory"]["task_complete"] is expected
        assert row["without_memory"]["task_complete"] is (query["query_id"] in complete_without)
        if expected:
            assert row["with_memory"]["missing"] == [] and row["with_memory"]["uncited"] == []
        else:
            assert row["with_memory"]["missing"], "an incomplete query must name its missing items"


def test_a_missing_citation_and_a_forbidden_hit_are_reported_not_hidden(dataset):
    query = dataset["queries"][0]
    required = [item["locator"] for item in query["required_items"]]
    uncited = ArmObservation(query_id=query["query_id"], arm="with_memory", round="record",
                             hits=tuple(required), cited=(), delivered=tuple(required))
    verdict = task_complete(query, uncited)
    assert verdict["task_complete"] is False
    assert sorted(verdict["uncited"]) == sorted(required)
    forbidden_locator = query["forbidden_items"][0]["locator"] if query["forbidden_items"] else "x"
    violated = ArmObservation(query_id=query["query_id"], arm="with_memory", round="record",
                              hits=tuple(required), cited=tuple(required), delivered=tuple(required),
                              forbidden_hits=(forbidden_locator,))
    verdict = task_complete(query, violated)
    assert verdict["task_complete"] is False and verdict["forbidden"] == [forbidden_locator]


def test_an_arm_failure_stays_a_failed_path_and_never_completes(dataset):
    rows = observations(dataset, complete_without=[], complete_with=[])
    broken = dataset["queries"][0]["query_id"]
    for arm in ARMS:
        rows[("record", arm, broken)] = ArmObservation(
            query_id=broken, arm=arm, round="record", error="RuntimeError: transport refused")
    report = report_for(dataset, complete_without=[], complete_with=[], observations=rows)
    assert any(path.endswith(broken) for path in report["failed_paths"])
    row = next(item for item in report["queries"] if item["query_id"] == broken)
    assert row["with_memory"]["task_complete"] is False
    assert row["with_memory"]["error"] == "RuntimeError: transport refused"
    assert report["status"] == "incomplete"
    assert report["default_enable_eligible"] is False


def test_unmeasured_latency_and_cost_stay_null_instead_of_zero(dataset):
    rows = observations(dataset, complete_without=[], complete_with=[])
    query_id = dataset["queries"][0]["query_id"]
    rows[("record", "with_memory", query_id)] = ArmObservation(
        query_id=query_id, arm="with_memory", round="record", hits=(), cited=(), delivered=(),
        latency_ms=None, cost_usd=None)
    report = report_for(dataset, complete_without=[], complete_with=[], observations=rows)
    row = next(item for item in report["queries"] if item["query_id"] == query_id)
    assert row["with_memory"]["latency_ms"] is None and row["with_memory"]["cost_usd"] is None


# ---------------------------------------------------------------------------
# Baseline arm: no memory parameters and zero new fields
# ---------------------------------------------------------------------------

def test_baseline_arm_disables_the_parameters_and_shares_no_session(dataset):
    assert baseline_parameters() == {"session_id": None, "memory_context": None}
    assert "session_id" not in {key for key, value in baseline_parameters().items() if value is not None}
    baseline = arm_policy("without_memory")
    enabled = arm_policy("with_memory")
    assert baseline == {"memory_attachment_enabled": False, "working_set_enabled": False}
    assert enabled == {"memory_attachment_enabled": True, "working_set_enabled": True}
    # The two arms never share a session or a delivered set.
    first = arm_parameters("with_memory", session_id="session-a", memory_context="ctx-a")
    second = arm_parameters("with_memory", session_id="session-b", memory_context="ctx-b")
    assert first["session_id"] != second["session_id"]
    assert arm_parameters("without_memory")["session_id"] is None
    assert "memory_context" not in arm_parameters("without_memory") or \
        arm_parameters("without_memory")["memory_context"] is None


def test_baseline_response_must_carry_zero_new_fields():
    legacy = {"completion_status": "complete", "evidence": [{"source_id": "1"}], "gaps": [],
              "request_id": "r"}
    assert zero_new_fields(legacy) == []
    assert_baseline_zero_new_fields(legacy)
    for field in GREEN_LEGACY_NEW_FIELDS:
        polluted = dict(legacy, **{field: []})
        assert zero_new_fields(polluted) == [field]
        with pytest.raises(ComparisonFailed, match=field):
            assert_baseline_zero_new_fields(polluted)


def test_a_polluted_baseline_is_a_measured_report_failure(dataset):
    """A baseline carrying 014-only fields fails the report, it is not an excuse."""
    rows = observations(dataset, complete_without=[], complete_with=[])
    query_id = dataset["queries"][0]["query_id"]
    rows[("record", "without_memory", query_id)] = ArmObservation(
        query_id=query_id, arm="without_memory", round="record",
        baseline_new_fields=("related_memories",),
        error="BASELINE_NEW_FIELDS:related_memories")
    report = report_for(dataset, complete_without=[], complete_with=[], observations=rows)
    assert report["status"] == "failed"
    assert report["default_enable_eligible"] is False
    assert report["environment"]["baseline_new_fields"] == [
        {"query_id": query_id, "fields": ["related_memories"]}]
    row = next(item for item in report["queries"] if item["query_id"] == query_id)
    assert "related_memories" in row["without_memory"]["error"]


# ---------------------------------------------------------------------------
# T056 gate semantics
# ---------------------------------------------------------------------------

def test_quality_gate_passes_on_three_percent_relative_gain(dataset):
    complete_without = _ids_with_all_categories(dataset, 8)
    complete_with = _ids_with_all_categories(dataset, 11)
    report = report_for(dataset, complete_without=complete_without, complete_with=complete_with)
    gain = report["relative_gain"]
    assert gain["value"] == pytest.approx((11 - 8) / 8)
    checks = report["gates"]["quality"]["checks"]
    assert checks["relative_gain_threshold_met"] is True and checks["quality_met"] is True
    assert report["gates"]["quality"]["status"] == "passed"
    assert report["status"] == "passed" and report["default_enable_eligible"] is True
    assert report["zero_baseline"] == {"is_zero": False, "code": None,
                                       "without_memory_completion_rate": pytest.approx(8 / len(dataset["queries"]))}


def test_quality_gate_fails_when_neither_threshold_nor_criterion_is_met(dataset):
    same = _ids_with_all_categories(dataset, 8)
    report = report_for(dataset, complete_without=same, complete_with=same)
    checks = report["gates"]["quality"]["checks"]
    assert report["relative_gain"]["value"] == pytest.approx(0.0)
    assert checks["relative_gain_threshold_met"] is False
    assert checks["explicit_criterion_met"] is False
    assert checks["quality_met"] is False
    assert report["status"] == "failed" and exit_code_for(report["status"]) == EXIT_FAILED
    assert "RELATIVE_GAIN_BELOW_THRESHOLD" in report["criteria"]["reasons"]


def test_quality_gate_falls_back_to_the_prefrozen_explicit_criterion(dataset):
    thirteen = _ids_with_all_categories(dataset, 13)
    report = report_for(dataset, complete_without=thirteen, complete_with=thirteen)
    checks = report["gates"]["quality"]["checks"]
    assert report["relative_gain"]["value"] == pytest.approx(0.0)
    assert checks["relative_gain_threshold_met"] is False
    assert checks["explicit_criterion_met"] is True and checks["quality_met"] is True
    assert report["criteria"]["explicit_criterion"] == dataset["explicit_criterion"]
    assert report["criteria"]["explicit_criterion_source"].startswith("dataset.explicit_criterion")
    assert report["gates"]["quality"]["status"] == "passed"


def test_a_zero_baseline_is_not_computable_and_never_substituted(dataset):
    report = report_for(dataset, complete_without=[],
                        complete_with=_ids_with_all_categories(dataset, 14))
    assert report["relative_gain"]["value"] is None, "a zero baseline gets no tiny/infinite substitute"
    assert report["zero_baseline"]["is_zero"] is True
    assert report["zero_baseline"]["code"] == ZERO_BASELINE_CODE
    checks = report["gates"]["quality"]["checks"]
    assert checks["relative_gain_threshold_met"] is False
    assert checks["explicit_criterion_met"] is True and checks["quality_met"] is True
    # The pre-frozen criterion is the substitute, and the code is still recorded.
    assert checks["baseline_zero"] is True
    unresolved = report_for(dataset, complete_without=[],
                            complete_with=_ids_with_all_categories(dataset, 4))
    assert unresolved["gates"]["quality"]["checks"]["quality_met"] is False
    assert ZERO_BASELINE_CODE in unresolved["criteria"]["reasons"]
    assert unresolved["status"] == "failed"


def test_gate_helpers_are_pure_and_agree_with_the_report(dataset):
    without, with_ = 0.5, 0.6
    gain = relative_gain(without, with_)
    rows = [{"category": category, "task_complete": True} for category in
            ("resume_after_break", "recall_last_decision", "lesson_effective", "preference_applied")]
    explicit = explicit_criterion_check(rows, dataset["explicit_criterion"])
    checks, reasons = quality_gate(gain=gain, explicit=explicit)
    assert checks["quality_met"] is True and reasons == []
    hard = clean_hard_metrics()
    safety, safety_reasons = safety_gate(hard)
    assert safety["all_required_observed"] is True and safety["violations"] == 0 and safety_reasons == []
    regression, regression_reasons = regression_gate(
        reproducibility={"status": "passed", "max_non_latency_relative_drift": 0.0},
        cache=cache_block(), regression_evidence=regression_evidence())
    assert regression["regression_met"] is True and regression_reasons == []
    assert default_enable_eligible(
        quality=checks, safety=safety, regression=regression,
        reproducibility={"status": "passed"}) is True


# ---------------------------------------------------------------------------
# Three gates + reproducibility => default_enable_eligible
# ---------------------------------------------------------------------------

def test_default_enable_eligible_requires_all_three_gates_and_reproducibility(dataset):
    complete_without = _ids_with_all_categories(dataset, 8)
    complete_with = _ids_with_all_categories(dataset, 11)
    green = report_for(dataset, complete_without=complete_without, complete_with=complete_with)
    assert green["status"] == "passed" and green["default_enable_eligible"] is True
    assert green["reproducibility"]["status"] == "passed"
    assert exit_code_for(green["status"]) == EXIT_OK
    # A quality failure blocks eligibility.
    weak = report_for(dataset, complete_without=_ids_with_all_categories(dataset, 8),
                      complete_with=_ids_with_all_categories(dataset, 8))
    assert weak["default_enable_eligible"] is False and weak["status"] == "failed"
    # A zero-tolerance safety violation blocks eligibility with exit 1.
    violated = clean_hard_metrics()
    violated["cross_domain_leaks"] = 1
    broken = report_for(dataset, complete_without=complete_without, complete_with=complete_with,
                        hard_metrics=violated)
    assert broken["gates"]["safety"]["checks"]["cross_domain_leaks"] is False
    assert broken["gates"]["safety"]["status"] == "failed"
    assert broken["default_enable_eligible"] is False and broken["status"] == "failed"
    # An unobserved counter stays null and is not a fabricated zero; evidence is incomplete.
    unobserved = clean_hard_metrics()
    unobserved["memory_provenance_complete_rate"] = None
    partial = report_for(dataset, complete_without=complete_without, complete_with=complete_with,
                         hard_metrics=unobserved)
    assert partial["hard_metrics"]["memory_provenance_complete_rate"] is None
    assert partial["gates"]["safety"]["checks"]["all_required_observed"] is False
    assert partial["default_enable_eligible"] is False and partial["status"] == "incomplete"
    assert exit_code_for(partial["status"]) == EXIT_INCOMPLETE
    # An incomplete replay (cache evidence) blocks eligibility with exit 2.
    incomplete = report_for(dataset, complete_without=complete_without, complete_with=complete_with,
                            reproducibility_evidence=reproducibility_evidence(complete=False),
                            cache=cache_block(evidence_complete=False))
    assert incomplete["reproducibility"]["status"] == "incomplete"
    assert incomplete["default_enable_eligible"] is False and incomplete["status"] == "incomplete"
    # A measured replay drift beyond the 1% tolerance is a failure, not an excuse.
    drifted = report_for(dataset, complete_without=complete_without, complete_with=complete_with,
                         reproducibility_evidence=reproducibility_evidence(drift=0.5))
    assert drifted["reproducibility"]["status"] == "failed"
    assert drifted["status"] == "failed" and exit_code_for(drifted["status"]) == EXIT_FAILED
    # A real model call during replay fails the regression gate.
    network = report_for(dataset, complete_without=complete_without, complete_with=complete_with,
                         reproducibility_evidence=reproducibility_evidence(replay_calls=1),
                         cache=cache_block(replay_real_network_calls=1))
    assert network["gates"]["regression"]["checks"]["replay_zero_network"] is False
    assert network["default_enable_eligible"] is False
    # The approved change (7-day window -> delivered_ttl_seconds=3600) must be recorded.
    unrecorded = report_for(dataset, complete_without=complete_without, complete_with=complete_with,
                            regression_evidence={})
    assert unrecorded["gates"]["regression"]["checks"]["approved_window_change_recorded"] is False
    assert unrecorded["default_enable_eligible"] is False


def test_report_is_evidence_only_and_never_flips_a_switch(dataset):
    complete_without = _ids_with_all_categories(dataset, 8)
    complete_with = _ids_with_all_categories(dataset, 11)
    green = report_for(dataset, complete_without=complete_without, complete_with=complete_with)
    assert green["default_enable_eligible"] is True
    assert green["default_configuration"] == {
        "memory_aware_retrieval_enabled": False, "memory_consumption_projection_enabled": False,
        "switches_changed": False,
        "reason": "evidence-only report: both 014 deployment switches stay false and no domain policy was published"}
    for key in ("memory_aware_retrieval_enabled", "memory_consumption_projection_enabled"):
        assert key not in green or green[key] is False


# ---------------------------------------------------------------------------
# Replay cache: recorded outcomes only, zero real calls
# ---------------------------------------------------------------------------

def test_record_replay_cache_consumes_recorded_outcomes_with_zero_real_calls(tmp_path):
    calls = []

    def tool(key):
        calls.append(key)
        return {"memories": [{"memory_id": "1"}]}

    cache_dir = tmp_path / "cache"
    manifest_path = tmp_path / "cache-manifest.json"
    cache = ToolCallCache(cache_dir, mode="record")
    assert cache.invoke("k1", lambda: tool("k1")) == {"memories": [{"memory_id": "1"}]}

    def failing():
        raise RuntimeError("transport refused")

    with pytest.raises(RuntimeError, match="transport refused"):
        cache.invoke("k2", failing)
    assert cache.real_calls == 2
    manifest = cache.seal(manifest_path, dataset_hash="d" * 64, snapshot_hash="s" * 64)
    assert manifest["manifest_version"] == "014.cache.1"
    assert manifest["expected_keys"] == 2 and manifest["recorded_success"] == 1
    assert manifest["recorded_failure"] == 1 and manifest["model_version"] == "none"

    def never():
        raise AssertionError("replay must not call the tool boundary")

    replay = ToolCallCache(cache_dir, mode="replay")
    assert replay.invoke("k1", never) == {"memories": [{"memory_id": "1"}]}
    with pytest.raises(CachedToolFailure, match="transport refused"):
        replay.invoke("k2", never)
    assert replay.real_calls == 0, "the replay round must make zero real calls"
    assert calls == ["k1"]
    audit = replay.audit(["k1", "k2"])
    assert audit["evidence_complete"] is True and audit["replayed_success"] == 1
    assert audit["replayed_failure"] == 1 and audit["missing"] == 0
    with pytest.raises(CacheIncomplete, match="missing"):
        replay.invoke("absent", never)
    # A version mismatch is an incomplete record, never a silent re-run.
    entry_path(cache_dir, "k1").write_text(json.dumps(
        {"parser": "continuity-v0", "reason": None, "output": {}}), encoding="utf-8")
    broken = ToolCallCache(cache_dir, mode="replay").audit(["k1", "k2"])
    assert broken["version_mismatch"] == 1 and broken["evidence_complete"] is False
    assert entry_path(cache_dir, "k1").exists()
    # The sealed manifest is never overwritten with different bytes.  The
    # tampered entry above is restored first: sealing a corrupt cache is a
    # different refusal and must not mask the overwrite rule under test.
    entry_path(cache_dir, "k1").write_text(json.dumps(
        {"parser": "continuity-v1", "reason": None, "output": {"memories": []}}), encoding="utf-8")
    with pytest.raises(ComparisonFailed, match="refus"):
        ToolCallCache(cache_dir, mode="record").seal(manifest_path, dataset_hash="x" * 64,
                                                     snapshot_hash="y" * 64)


def test_replay_response_audit_compares_normalized_arm_outcomes(dataset):
    rows = observations(dataset, complete_without=[], complete_with=[])
    record_rows = {key: value for key, value in rows.items() if key[0] == "record"}
    replay_rows = {key: value for key, value in rows.items() if key[0] == "replay"}
    query_ids = [query["query_id"] for query in dataset["queries"]]
    audit = replay_response_audit(record_rows, replay_rows, query_ids)
    assert audit["match_rate"] == 1.0 and audit["mismatched"] == []
    drifted = dict(replay_rows)
    key = ("replay", "with_memory", query_ids[0])
    drifted[key] = ArmObservation(query_id=query_ids[0], arm="with_memory", round="replay",
                                  hits=("x",), cited=("x",), delivered=("x",))
    audit = replay_response_audit(record_rows, drifted, query_ids)
    assert audit["match_rate"] < 1.0 and audit["mismatched"]
    assert replay_response_audit({}, {}, query_ids)["match_rate"] is None


# ---------------------------------------------------------------------------
# CLI: unique output, refusal, exit codes
# ---------------------------------------------------------------------------

def test_cli_declares_the_frozen_flags_and_exit_codes():
    parser = build_parser()
    options = {action.dest for action in parser._actions}
    assert {"dataset", "mode", "cache_manifest", "output", "run_id"} <= options
    mode = next(action for action in parser._actions if action.dest == "mode")
    assert set(mode.choices) == {"record", "replay"}
    assert (EXIT_OK, EXIT_FAILED, EXIT_INCOMPLETE) == (0, 1, 2)
    assert exit_code_for("passed") == EXIT_OK
    assert exit_code_for("failed") == EXIT_FAILED
    assert exit_code_for("incomplete") == EXIT_INCOMPLETE
    with pytest.raises(SystemExit):
        parser.parse_args(["--dataset", "d", "--mode", "bogus", "--cache-manifest", "m",
                           "--output", "o"])


def test_cli_refuses_an_existing_output_and_missing_evidence_with_exit_2(tmp_path, capsys):
    output = tmp_path / "memory-report.json"
    output.write_text('{"owned": "elsewhere"}', encoding="utf-8")
    argv = ["--dataset", str(DATASET_PATH), "--mode", "record",
            "--cache-manifest", str(tmp_path / "manifest.json"), "--output", str(output),
            "--run-id", "t057test"]
    assert main(argv) == EXIT_INCOMPLETE
    assert json.loads(capsys.readouterr().out)["status"] == "incomplete"
    assert output.read_text(encoding="utf-8") == '{"owned": "elsewhere"}', (
        "an existing --output is never overwritten")
    # A unique output with no snapshot/capsule evidence is incomplete evidence (2),
    # and the honest placeholder report claims no gate result.
    fresh = tmp_path / "fresh-report.json"
    assert main(["--dataset", str(DATASET_PATH), "--mode", "record",
                 "--cache-manifest", str(tmp_path / "manifest2.json"), "--output", str(fresh),
                 "--run-id", "t057test2"]) == EXIT_INCOMPLETE
    capsys.readouterr()
    placeholder = json.loads(fresh.read_text(encoding="utf-8"))
    assert placeholder["status"] == "incomplete"
    assert "default_enable_eligible" not in placeholder
    # An absent dataset is incomplete evidence, not a crash.
    missing = tmp_path / "absent.json"
    assert main(["--dataset", str(missing), "--mode", "replay",
                 "--cache-manifest", str(tmp_path / "manifest3.json"),
                 "--output", str(tmp_path / "out3.json")]) == EXIT_INCOMPLETE


def test_the_frozen_dataset_still_hashes_to_its_pin():
    digest = hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest()
    assert digest == DATASET_SHA256


# ---------------------------------------------------------------------------
# T054: four independent restorations, one per (round, arm)
# ---------------------------------------------------------------------------

def test_two_arms_two_rounds_allocate_four_independent_restorations(tmp_path):
    run = allocate_identities("t057x", base=tmp_path / "runs", qdrant_port_base=18900)
    expected = {(round_name, arm) for round_name in ROUNDS for arm in ARMS}
    assert {(item.round, item.arm) for item in run.identities} == expected
    proof = assert_independent(run)
    assert proof["identities"] == 4 and proof["distinct_databases"] == 4
    assert proof["distinct_data_roots"] == 4 and proof["distinct_qdrant_stores"] == 4
    assert proof["arms"] == sorted(ARMS) and proof["rounds"] == sorted(ROUNDS)
    assert len({item.database for item in run.identities}) == 4
    with pytest.raises(ComparisonFailed, match="run_id"):
        allocate_identities("not a token", base=tmp_path / "runs")


def test_a_passed_report_requires_complete_real_evidence(dataset):
    green = report_for(dataset, complete_without=_ids_with_all_categories(dataset, 8),
                       complete_with=_ids_with_all_categories(dataset, 11))
    decision = validate_comparison_report(green, evidence={"cache": "sealed"})
    assert decision["status"] == "passed" and decision["default_enable_eligible"] is True
    assert decision["snapshot_hash"] == dataset["snapshot_hash"]
    with pytest.raises(ComparisonFailed, match="evidence"):
        validate_comparison_report(green)
    unsealed = json.loads(json.dumps(green))
    unsealed["cache"]["evidence_complete"] = False
    with pytest.raises(ComparisonFailed, match="cache evidence"):
        validate_comparison_report(unsealed, evidence={"cache": "sealed"})
    unreproduced = json.loads(json.dumps(green))
    unreproduced["reproducibility"]["status"] = "incomplete"
    with pytest.raises(ComparisonFailed, match="reproducibility"):
        validate_comparison_report(unreproduced, evidence={"cache": "sealed"})


# --- T087: the tracked target-host smoke record --------------------------------


def test_target_host_smoke_record_is_complete_and_never_fakes_a_pass():
    """T087/FR-037/SC-014: per-host availability, compatibility and probe evidence."""
    record = json.loads((ROOT / "eval" / "target-host-smoke-014.json").read_text(encoding="utf-8"))
    assert record["report_type"] == "target-host-smoke"
    hosts = record["hosts"]
    assert set(hosts) == {"dsh", "chatgpt_app", "claude_code"}
    required = {"must_pass", "status", "checked_at", "availability", "compatibility",
                "probe_commands", "raw_observation", "reason"}
    for name, host in hosts.items():
        assert required <= set(host), (name, sorted(required - set(host)))
    for name in ("chatgpt_app", "claude_code"):
        assert hosts[name]["status"] != "passed", "an unexecuted host is never a pass"
    dsh = hosts["dsh"]
    assert dsh["must_pass"] is True
    if dsh["status"] == "passed":
        assert dsh["work_package_continuation_observed"]
        assert dsh["projection_direct_read_observed"]
    else:
        assert dsh["reason"]


def test_tracked_projection_direct_read_record_is_honest():
    """T087/T065: the canonical direct-read evidence is on a tracked path."""
    record = json.loads((ROOT / "eval" / "projection-direct-read-014.json").read_text(encoding="utf-8"))
    layers = record["layers"]
    assert set(layers) >= {"filesystem", "dsh_host_observation", "protocol"}
    assert layers["filesystem"]["observed"] is True
    host_layer = layers["dsh_host_observation"]
    if host_layer["status"] == "passed":
        assert host_layer["observed"] is True
        assert record["conclusion"] == "passed"
    else:
        assert record["conclusion"] == "failed"


def test_tracked_hard_metrics_never_reports_an_unmeasured_zero():
    """T098: a zero denominator is reported as not_measurable, never as 0."""
    record = json.loads((ROOT / "eval" / "hard-metrics-014.json").read_text(encoding="utf-8"))
    leakage = record["metrics"]["cross_domain_leakage"]
    if not leakage.get("examined"):
        assert leakage.get("state") == "not_measurable", leakage
        assert leakage.get("value") is None, leakage
    quarantined = record["metrics"]["quarantined_exclusion"]
    if quarantined.get("quarantined_status_observed") != "quarantined":
        assert quarantined.get("state") == "not_measurable", quarantined


# --- T058 runner wiring: payload schema + per-identity binding -----------------


def test_tool_payload_addresses_the_scope_through_the_tool_schema():
    """T058: ``search_knowledge`` takes ``domain_scope``; ``start_work`` a string scope_ref."""
    from run_memory_comparison import WORK_TOOL, tool_payload

    memory_policy = {"memory_attachment_enabled": True, "working_set_enabled": True}
    baseline_policy = {"memory_attachment_enabled": False, "working_set_enabled": False}
    search = tool_payload("search_knowledge", {"question": "q"},
                          parameters={"session_id": "s", "memory_context": "c"},
                          policy=memory_policy, scope_ref="slug-x", top_k=5)
    assert search == {"query": "q", "domain_scope": ["slug-x"], "top_k": 5,
                      "session_id": "s", "memory_context": "c"}
    assert "scope_ref" not in search
    baseline = tool_payload("search_knowledge", {"question": "q"},
                            parameters={"session_id": None, "memory_context": None},
                            policy=baseline_policy, scope_ref="slug-x")
    assert "session_id" not in baseline and "memory_context" not in baseline
    work = tool_payload(WORK_TOOL, {"question": "q"},
                        parameters={"session_id": "s", "memory_context": None},
                        policy=memory_policy, scope_ref="slug-x")
    assert work == {"scope_ref": "slug-x", "include_working_set": True, "session_id": "s"}


def test_identity_environment_binds_and_restores_every_key(monkeypatch):
    """T058: each arm is pointed at its own restored store and the env is restored."""
    import os
    from types import SimpleNamespace

    from run_memory_comparison import _IDENTITY_ENV_KEYS, identity_environment

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/rag_mcp")
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql+psycopg2://u:p@h:5432/rag_mcp")
    identity = SimpleNamespace(database="memory_consolidation_013_014_run_0",
                               qdrant_url="http://127.0.0.1:18900",
                               data_root="C:/t014c/run/00/root", label="record/with_memory")
    before = {key: os.environ.get(key) for key in _IDENTITY_ENV_KEYS}
    with identity_environment(identity, memory_enabled=True):
        assert os.environ["DATABASE_URL"].endswith("/memory_consolidation_013_014_run_0")
        assert os.environ["DATABASE_URL_SYNC"].endswith("/memory_consolidation_013_014_run_0")
        assert os.environ["QDRANT_URL"] == "http://127.0.0.1:18900"
        assert os.environ["DATA_ROOT"] == "C:/t014c/run/00/root"
        assert os.environ["MEMORY_AWARE_RETRIEVAL_ENABLED"] == "true"
        assert os.environ["AGENTIC_RETRIEVAL_ENABLED"] == "false"
    assert {key: os.environ.get(key) for key in _IDENTITY_ENV_KEYS} == before


def test_runner_uses_the_shared_implementations_with_identity_services():
    """T058: the runner must not import tool names that do not exist, and must bind."""
    source = (ROOT / "eval" / "run_memory_comparison.py").read_text(encoding="utf-8")
    assert "from rag_mcp.mcp.search_knowledge import search_knowledge_core" in source
    assert "from rag_mcp.mcp.search_knowledge import search_knowledge\n" not in source
    assert "from rag_mcp.mcp.start_work import start_work\n" not in source
    assert "def identity_environment(" in source
    assert "invoke_async" in source
    assert "async def call_tool(" in source


def test_forbidden_claims_are_not_hit_by_a_shared_heading(dataset):
    """T058: the forbidden claim locators share the evidence heading, so a heading
    match is not a forbidden hit; only a real memory_id/scope can be one."""
    from run_memory_comparison import observe_response

    query = dataset["queries"][0]
    assert any(item["kind"] == "banned_claim" for item in query["forbidden_items"])
    response = {
        "completion_status": "complete", "request_id": "r",
        "evidence": [{"evidence_id": "e-1", "source_id": "1", "source_version": "1",
                      "source_position": "2026-09-01 Weekly Sync > action items"}],
    }
    observation = observe_response(query, response, arm="without_memory", round_name="record")
    assert observation.forbidden_hits == ()
    assert observation.hits, "the required heading must still resolve from evidence"


def test_memory_arm_payload_survives_without_a_snapshot_session():
    """T104: a scope whose entries carry no session still attaches via memory_context.

    A synthetic UUID would filter every restored memory out (all frozen entries
    have a NULL session), silently measuring an empty attachment layer.
    """
    from run_memory_comparison import tool_payload

    payload = tool_payload("search_knowledge", {"question": "q"},
                           parameters={"session_id": None, "memory_context": "resume the task"},
                           policy={"memory_attachment_enabled": True, "working_set_enabled": True},
                           scope_ref="c013-eval-meeting-notes")
    assert payload["memory_context"] == "resume the task"
    assert payload["domain_scope"] == ["c013-eval-meeting-notes"]
    assert "session_id" not in payload


def test_evidence_locatability_uses_the_real_evidence_face_fields():
    """T102: the locating triple on the MCP face is evidence_id/version/position."""
    from types import SimpleNamespace

    from run_memory_comparison import evidence_locatable, observe_hard_metrics

    assert evidence_locatable({"evidence_id": "1", "source_version": 1, "source_position": "p"})
    assert evidence_locatable({"source_id": "1", "source_version": 1, "source_position": "p"})
    assert not evidence_locatable({"evidence_id": "1", "source_position": "p"})
    assert not evidence_locatable({"evidence_id": "1", "source_version": 1})
    assert not evidence_locatable(None)
    response = {
        "completion_status": "complete",
        "evidence": [{"evidence_id": "1", "source_version": 1, "source_position": "p"},
                     {"evidence_id": "2", "source_version": 1, "source_position": ""}],
    }
    metrics = observe_hard_metrics({"k": SimpleNamespace(raw=response)})
    assert metrics["mcp_schema_validity_rate"] == 1.0
    assert metrics["evidence_source_locatable_rate"] == 0.5


def test_cross_domain_leaks_are_measured_from_item_scopes():
    """T102: search items expose knowledge_scope_id, so leaks are witnessable."""
    from types import SimpleNamespace

    from run_memory_comparison import observe_hard_metrics

    response = {"completion_status": "complete",
                "evidence": [{"evidence_id": "1", "source_version": 1, "source_position": "p",
                              "knowledge_scope_id": 7}],
                "related_memories": [{"memory_id": 1, "provenance": "soft",
                                      "knowledge_scope_id": 8, "status": "active"}]}
    metrics = observe_hard_metrics({"k": SimpleNamespace(raw=response)}, requested_scope_id=7)
    assert metrics["cross_domain_leaks"] == 1
    clean = observe_hard_metrics(
        {"k": SimpleNamespace(raw={**response, "related_memories": []})}, requested_scope_id=7)
    assert clean["cross_domain_leaks"] == 0


def test_gate_report_archiver_archives_and_refuses_overwrite(tmp_path):
    """T059: the gate report is an archive of the validated reports, never a rewrite."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "archive_memory_gate_report", ROOT / "eval" / "archive_memory_gate_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    record = tmp_path / "memory-record.json"
    replay = tmp_path / "memory-replay.json"
    record.write_text(json.dumps({"status": "incomplete"}), encoding="utf-8")
    replay.write_text(json.dumps({
        "status": "failed", "default_enable_eligible": False,
        "gates": {"quality": {"status": "passed"}, "safety": {"status": "failed"},
                  "regression": {"status": "incomplete"}},
        "relative_gain": {"value": 0.0, "zero_baseline": False},
        "default_configuration": {"switches_changed": False},
    }), encoding="utf-8")
    output = tmp_path / "memory-gate-report.json"
    arguments = ["--record", str(record), "--replay", str(replay), "--output", str(output)]
    assert module.main(arguments) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["default_enable_eligible"] is False
    assert payload["gates"]["quality"]["status"] == "passed"
    assert "default_enable_eligible=False" in payload["conclusion"]
    assert payload["archive"]["replay"]["sha256"]
    assert module.main(arguments) == 2, "an existing gate report is never overwritten"
