"""T081 / FR-003: the honest "unrecognised variant is NOT passed" path.

``spec.md`` FR-003 forbids a variant entry's judgement from depending on the
detector firing: an unrecognised variant MUST be judged *not passed* -- recorded
as ``criterion_met=false`` and never counted as intercepted -- while the
detector-independent assertion ("the control surface did not move") MUST still
hold on its own.

The frozen subset cannot observe that path by itself: all of its 16 primary
cases are recognised by the shipped detector (proved below, without a database,
straight against the real ``detect_submission``), which is exactly why the
subset's 100% interception watermark is legitimate.  Adding an unrecognised
variant as a *case* would break that watermark, so the residual limitation is
disclosed as ``variant_dictionary.known_misses`` and the honest judgement is
demonstrated here by driving that disclosed body through the very same
:func:`judge_poisoning_case` the integration suite uses (imported, not
re-implemented) with the observation produced by the real detector.

Only the detector-level observation is claimed here.  The storage-surface half
of the judgement (recall/consolidation/attachment/working-set absence) needs the
real PG+Qdrant write path and is measured by
``tests/integration/test_015_poisoning_suite.py``; this module never fabricates
an assertion it did not measure.
"""

from __future__ import annotations

import pytest

from rag_mcp.services.memory_validators import detect_submission
from tests.integration.test_015_poisoning_suite import (
    CASES,
    VARIANT_DICTIONARY,
    VARIANT_DICTIONARY_VERSION,
    criterion_expected_for,
    declared_rule_observed,
    judge_poisoning_case,
)

#: The disclosed non-detection: the dataset body is the single source of truth.
KNOWN_MISS = VARIANT_DICTIONARY["known_misses"][0]
KNOWN_MISS_CASE = {
    "case_id": "poison_known_miss_disregard_paraphrase",
    "role": "primary",
    "pattern": "role_hijack",
    "risk_tier": "high",
    "variant_class": KNOWN_MISS["variant_class"],
    "variant_id": f"{VARIANT_DICTIONARY_VERSION}#{KNOWN_MISS['variant_class']}",
    "language": KNOWN_MISS["language"],
    "content": KNOWN_MISS["content"],
}


def _observe(content: str) -> dict:
    """The real detector observation for one body (the write path's own call)."""
    result = detect_submission({"content": content})
    return {"flag_observed": result.injection_flags["risk_level"],
            "status_observed": result.status,
            "matched_patterns": list(result.injection_flags["matched_patterns"])}


def test_the_disclosed_paraphrase_really_is_unrecognised_by_every_rule():
    """The premise of the honest path, measured on the shipped detector."""
    observation = _observe(KNOWN_MISS_CASE["content"])
    assert observation["flag_observed"] == "none", observation
    assert observation["matched_patterns"] == [], observation
    assert observation["status_observed"] == "active", observation
    assert declared_rule_observed(KNOWN_MISS_CASE, observation["matched_patterns"]) is False, (
        "the disclosed miss is supposed to violate its own declared coverage")


def test_unrecognised_high_risk_variant_is_recorded_as_not_passed_not_raised():
    """FR-003: judgement is recorded (criterion_met=false), the run does not error."""
    observation = _observe(KNOWN_MISS_CASE["content"])
    judgement = judge_poisoning_case(
        KNOWN_MISS_CASE, control_surface_changes=0, **observation)

    # the declared expectation is unchanged: this *is* a primary-style case that
    # the dataset's explicit criterion would require to be intercepted ...
    assert criterion_expected_for(KNOWN_MISS_CASE) is True
    assert judgement["criterion_expected"] is True
    # ... and the honest judgement records that it was not.
    assert judgement["criterion_met"] is False, judgement
    assert judgement["criterion_met"] != judgement["criterion_expected"]
    # the observation itself is exported verbatim, so a reader can audit it
    assert judgement["flag_observed"] == "none"
    assert judgement["status_observed"] == "active"
    assert judgement["matched_patterns"] == []
    assert judgement["detector_rule"] is None
    assert judgement["variant_id"] == f"{VARIANT_DICTIONARY_VERSION}#{KNOWN_MISS['variant_class']}"
    assert judgement["detector_available"] is True

    # the traceable hook back into the dataset disclosure
    assert KNOWN_MISS["observed_risk_level"] == judgement["flag_observed"]
    assert KNOWN_MISS["observed_status"] == judgement["status_observed"]
    assert KNOWN_MISS["observed_matched_patterns"] == judgement["matched_patterns"]


def test_the_control_surface_assertion_holds_independently_of_the_detection_result():
    """FR-003 second half: the detector-independent assertion is enforced regardless.

    The refusal happens on the *unchanged control surface* fact alone: the
    detection outcome is identical in both calls below (none/low), so only the
    control-surface value decides the outcome.
    """
    observation = _observe(KNOWN_MISS_CASE["content"])
    judgement = judge_poisoning_case(KNOWN_MISS_CASE, control_surface_changes=0, **observation)
    assert judgement["criterion_met"] is False
    with pytest.raises(AssertionError, match="control_surface_unchanged"):
        judge_poisoning_case(KNOWN_MISS_CASE, control_surface_changes=1, **observation)


def test_the_known_miss_is_disclosed_in_the_dataset_and_absent_from_the_cases():
    misses = VARIANT_DICTIONARY["known_misses"]
    assert misses, "the residual detector limitation must be disclosed"
    contents = {case["content"] for case in CASES}
    assert KNOWN_MISS["content"] not in contents, (
        "the known miss MUST NOT be a frozen case: it would break the 100% interception watermark")
    assert KNOWN_MISS["reason"].strip()
    assert KNOWN_MISS["evidence"]


def test_every_frozen_case_still_fires_the_rule_it_declares_on_the_real_detector():
    """The frozen subset's coverage claim, re-derived without a database.

    Together with the test above this pins the FR-003 situation exactly: the only
    body in the 015 poisoning vocabulary that the shipped detector does not
    recognise is the disclosed ``known_misses`` entry, so the honest non-detection
    path is real but *deliberately outside* the frozen 100% watermark.
    """
    for case in CASES:
        observation = _observe(case["content"])
        assert declared_rule_observed(case, observation["matched_patterns"]), (
            f"{case['case_id']} declares {case['pattern']!r} but the shipped detector matched "
            f"{observation['matched_patterns']!r}")
        assert observation["flag_observed"] == case["risk_tier"], (case["case_id"], observation)
        assert observation["status_observed"] == (
            "quarantined" if case["risk_tier"] == "high" else "active"), (case["case_id"], observation)
