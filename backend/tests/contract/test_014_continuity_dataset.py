"""T051/T052: 014 continuity evaluation-dataset contract test (US5).

Frozen-set discipline inherited from 011 (FR-005/FR-007) and
``contracts/continuity-evaluation-contract.md`` §2 / ``data-model.md`` §7.6:

* the dataset is a frozen **object** (not a bare array) carrying
  ``dataset_version`` / ``frozen{...}`` / ``snapshot_hash`` / ``source`` /
  ``k=5`` / ``queries[]``;
* >= 15 queries, the four continuity categories each >= 1, ``zh`` >= 2 written as
  real Chinese text, unique ``query_id``, non-empty ``required_items`` whose
  ``locator`` is a cross-environment stable anchor (scope slug + structural
  anchor) with an **optional** ``memory_id`` that is never the only anchor;
* every query carries a ``forbidden_items`` key and a rule-decidable
  ``criterion`` (the control path has no LLM judge anywhere);
* every query carries an honest ``_meta`` review record.

**T053 review recorded.**  The allowed ``review_status`` value set is exactly
``{"reviewed", "pending_review"}``.  The 2026-10-09 review was authorized by the
dataset owner and executed by the implementation agent on the owner's behalf;
every query records that provenance in ``review_notes``.  A query claiming
``reviewed`` while ``review_notes`` or ``grounded_source`` is empty is a
fabrication and still fails here; the dataset sha256 pin moved to the reviewed
revision in the same change.

The dataset sha256 is pinned below because the pre-existing
``test_domain_eval_dataset_schema.py`` pins only the three 011 datasets and does
not scan new files (contract §2, "保护缺口").
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _path in (ROOT / "eval", ROOT / "backend" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from memory_continuity_support import (  # noqa: E402
    CATEGORIES,
    FROZEN_FIELDS,
    K,
    LANGUAGES,
    MIN_QUERIES,
    REVIEW_STATUSES,
    DatasetInvalid,
    load_dataset,
    locator_parts,
    validate_dataset,
)

DATASET_PATH = ROOT / "eval" / "memory_continuity_eval_dataset.json"
# Frozen at T052 (2026-10-09), re-frozen by the authorized T053 review, and
# re-frozen again by the T058 anchor-slug correction (scope slug must be the
# frozen authority's real slug).  Any further rewrite of _meta must update this
# pin in the same change; no other edit may pass this test.
DATASET_SHA256 = "8a5fb42d74bdf37d794dde15804a3d97316ff5d14c8ab122350df8dede79ffc4"
CORPUS_PATH = ROOT / "eval" / "corpora" / "generic" / "team_meeting_notes.md"
CONSOLIDATION_DATASET = ROOT / "eval" / "consolidation_eval_dataset.json"
INGEST_SPECS = ROOT / "eval" / "ingest_domain_corpora.py"
#: The 013 freeze declaration is the real source of the frozen scope's slug.
FREEZE_SPECS = ROOT / "eval" / "freeze_consolidation_dataset.py"

CJK = re.compile(r"[\u4e00-\u9fff]")
PATH_TOKEN = re.compile(r"eval/[^\s'\"(),;]+?\.(?:md|json|py|txt)")
NEW_FIELDS = ("related_memories", "memory_notice", "counts", "working_set")


@pytest.fixture(scope="module")
def dataset() -> dict:
    return load_dataset(DATASET_PATH)


def _copy(dataset: dict) -> dict:
    return json.loads(json.dumps(dataset))


# ---------------------------------------------------------------------------
# Frozen object shape
# ---------------------------------------------------------------------------

def test_dataset_is_a_frozen_object_with_every_required_key(dataset):
    assert isinstance(dataset, dict), "the 014 dataset is a frozen object, not a bare array"
    for key in ("dataset_version", "frozen", "snapshot_hash", "source", "k", "queries"):
        assert key in dataset, f"dataset missing {key}"
    assert re.match(r"^014\.eval\.\d+$", dataset["dataset_version"])
    assert dataset["k"] == K == 5
    assert re.match(r"^[a-f0-9]{64}$", dataset["snapshot_hash"])
    validate_dataset(dataset)


def test_frozen_identity_map_is_complete_and_declares_no_model(dataset):
    frozen = dataset["frozen"]
    assert set(frozen) == set(FROZEN_FIELDS), "frozen identity map must carry exactly the ten frozen keys"
    assert frozen["model"] == "none", "014 has no LLM in the control path"
    for field in FROZEN_FIELDS:
        assert isinstance(frozen[field], str) and frozen[field].strip(), f"frozen.{field} must be frozen text"


def test_source_declares_the_real_snapshot_material(dataset):
    source = dataset["source"]
    assert isinstance(source, dict)
    assert source["scope_id"] == dataset["scope_id"]
    assert source["scope_slug"] and source["corpus"]
    assert source["human_review"].startswith("pending")
    for reference in source["grounding"]:
        assert (ROOT / reference).exists(), f"declared grounding material is absent: {reference}"


# ---------------------------------------------------------------------------
# Coverage: >= 15 queries, four categories, Chinese
# ---------------------------------------------------------------------------

def test_minimum_fifteen_queries(dataset):
    assert len(dataset["queries"]) >= MIN_QUERIES >= 15


def test_every_category_is_covered(dataset):
    counts = {category: 0 for category in CATEGORIES}
    for query in dataset["queries"]:
        assert query["category"] in CATEGORIES, f"query {query.get('query_id')} category invalid"
        counts[query["category"]] += 1
    for category, count in counts.items():
        assert count >= 1, f"category {category} is not covered"


def test_at_least_two_chinese_queries_with_real_chinese_text(dataset):
    chinese = [query for query in dataset["queries"] if query["language"] == "zh"]
    assert len(chinese) >= 2
    for query in chinese:
        assert CJK.search(query["question"]), f"zh query {query['query_id']} carries no Chinese text"
    for query in dataset["queries"]:
        assert query["language"] in LANGUAGES
    for query in dataset["queries"]:
        if query["language"] == "en":
            assert not CJK.search(query["question"]), "an en query must be written in English"


def test_query_ids_are_unique_and_scope_bound(dataset):
    identifiers = [query["query_id"] for query in dataset["queries"]]
    assert len(set(identifiers)) == len(identifiers)
    assert all(identifier and isinstance(identifier, str) for identifier in identifiers)
    for query in dataset["queries"]:
        assert query["scope_id"] == dataset["scope_id"]
        assert query["question"].strip()
        assert query["criterion"].strip()


# ---------------------------------------------------------------------------
# Anchors: stable locator, never a memory_id-only anchor
# ---------------------------------------------------------------------------

def test_required_items_are_non_empty_and_carry_a_stable_locator(dataset):
    slug = dataset["source"]["scope_slug"]
    for query in dataset["queries"]:
        items = query["required_items"]
        assert isinstance(items, list) and items, f"query {query['query_id']} required_items must be non-empty"
        for item in items:
            locator = item["locator"]
            assert isinstance(locator, str) and locator, "every required item carries a locator"
            parsed = locator_parts(locator)
            assert parsed["slug"] == slug, "the locator must anchor inside the frozen scope slug"
            assert parsed["heading"], "the locator must carry a structural anchor (heading path)"
            assert isinstance(item["require_citation"], bool)
            if "memory_id" in item and item["memory_id"] is not None:
                assert re.match(r"^[0-9]+$", str(item["memory_id"]))
                # The memory_id is a same-snapshot consistency check *only*: the
                # stable locator above is always the anchor.
                assert locator != str(item["memory_id"])


def test_forbidden_items_key_exists_and_criterion_is_rule_decidable(dataset):
    for query in dataset["queries"]:
        assert "forbidden_items" in query, f"query {query['query_id']} must carry the forbidden_items key"
        assert isinstance(query["forbidden_items"], list)
        for item in query["forbidden_items"]:
            assert item["locator"] and item["reason"] and item["kind"] in (
                "out_of_scope", "superseded_item", "banned_claim")
        assert any(token in query["criterion"] for token in ("must", "并", "且", "不得")), (
            f"query {query['query_id']} criterion is not an explicit, decidable completion rule")


# ---------------------------------------------------------------------------
# Honest review record (T053, executed under the dataset owner's authorization)
# ---------------------------------------------------------------------------

def test_allowed_review_status_set_is_exactly_reviewed_or_pending(dataset):
    assert REVIEW_STATUSES == {"reviewed", "pending_review"}
    for query in dataset["queries"]:
        meta = query["_meta"]
        assert meta["review_status"] in REVIEW_STATUSES
        assert meta["review_notes"].strip(), f"query {query['query_id']} has no review record"
        assert meta["grounded_source"].strip(), f"query {query['query_id']} has no grounded source"


def test_dataset_carries_the_authorized_review_record(dataset):
    """T053: the review happened under the owner's authorization; every query records it."""
    statuses = {query["_meta"]["review_status"] for query in dataset["queries"]}
    assert statuses == {"reviewed"}, (
        "the authorized T053 review must be recorded on every query; a parked or mixed state "
        "means the review is incomplete and requires the reviewer's own edit plus the pin update")
    for query in dataset["queries"]:
        notes = query["_meta"]["review_notes"]
        assert "T053" in notes and "2026-10-09" in notes, f"query {query['query_id']} lacks a review record"
        assert "authorized" in notes.lower(), "the review record must disclose its provenance"
        assert not notes.lower().startswith("ai-drafted, pending")


def test_the_validator_forbids_a_fabricated_review_claim(dataset):
    """A reviewed claim without a review record or grounded source is fabrication."""
    fabricated = _copy(dataset)
    fabricated["queries"][0]["_meta"]["review_status"] = "reviewed"
    fabricated["queries"][0]["_meta"]["review_notes"] = "   "
    with pytest.raises(DatasetInvalid, match="fabricat|review record"):
        validate_dataset(fabricated)
    ungrounded = _copy(dataset)
    ungrounded["queries"][0]["_meta"]["review_status"] = "reviewed"
    ungrounded["queries"][0]["_meta"]["grounded_source"] = ""
    with pytest.raises(DatasetInvalid, match="fabricat|grounded"):
        validate_dataset(ungrounded)
    invented = _copy(dataset)
    invented["queries"][0]["_meta"]["review_status"] = "approved_by_ai"
    with pytest.raises(DatasetInvalid, match="review_status"):
        validate_dataset(invented)


# ---------------------------------------------------------------------------
# The validator refuses every broken shape (the dataset is the artefact)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mutation,message", [
    ("version", "dataset_version"),
    ("k", "k=5"),
    ("frozen_key", "frozen"),
    ("few_queries", "at least"),
    ("category", "category"),
    ("duplicate_id", "unique"),
    ("no_required", "required_items"),
    ("no_locator", "locator"),
    ("locator_only_memory_id", "locator"),
    ("no_forbidden_key", "forbidden_items"),
    ("no_criterion", "criterion"),
])
def test_validator_refuses_a_broken_dataset(dataset, mutation, message):
    broken = _copy(dataset)
    queries = broken["queries"]
    if mutation == "version":
        broken["dataset_version"] = "013.eval.1"
    elif mutation == "k":
        broken["k"] = 3
    elif mutation == "frozen_key":
        broken["frozen"].pop("budget")
    elif mutation == "few_queries":
        broken["queries"] = queries[: MIN_QUERIES - 3]
    elif mutation == "category":
        for query in queries:
            query["category"] = "resume_after_break"
    elif mutation == "duplicate_id":
        queries[1]["query_id"] = queries[0]["query_id"]
    elif mutation == "no_required":
        queries[0]["required_items"] = []
    elif mutation == "no_locator":
        queries[0]["required_items"][0].pop("locator")
    elif mutation == "locator_only_memory_id":
        queries[0]["required_items"][0]["locator"] = str(
            queries[0]["required_items"][0].get("memory_id") or "366085012090519552")
    elif mutation == "no_forbidden_key":
        queries[0].pop("forbidden_items")
    elif mutation == "no_criterion":
        queries[0]["criterion"] = "  "
    with pytest.raises(DatasetInvalid, match=message):
        validate_dataset(broken)


# ---------------------------------------------------------------------------
# Grounding is real, never invented
# ---------------------------------------------------------------------------

def test_dataset_sha256_is_pinned(dataset):
    digest = hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest()
    assert digest == DATASET_SHA256, (
        "the frozen 014 dataset changed; T053's human review is the only sanctioned rewrite "
        "and it must update this pin")


def test_snapshot_hash_and_scope_come_from_the_real_frozen_authority(dataset):
    frozen_013 = json.loads(CONSOLIDATION_DATASET.read_text(encoding="utf-8"))
    assert dataset["snapshot_hash"] == frozen_013["snapshot_hash"] == frozen_013["frozen"]["snapshot"]
    assert dataset["scope_id"] == frozen_013["scope_id"]
    assert dataset["source"]["corpus"] == frozen_013["source"]["corpus"]


def test_scope_slug_is_a_real_declared_scope(dataset):
    """The anchor slug must be the slug the frozen authority really carries.

    T058 proved (against the restored sealed capsule) that scope
    366084747748704256 is ``c013-eval-meeting-notes``; the 011 ingest label is a
    different scope and must never be used as this dataset's anchor.
    """
    freeze_specs = FREEZE_SPECS.read_text(encoding="utf-8")
    assert f"--scope-slug {dataset['source']['scope_slug']}" in freeze_specs
    specs = INGEST_SPECS.read_text(encoding="utf-8")
    assert f'"file": "{Path(dataset["source"]["corpus"]).name}"' in specs


def test_every_locator_heading_exists_in_the_grounded_corpus(dataset):
    corpus = CORPUS_PATH.read_text(encoding="utf-8")
    for query in dataset["queries"]:
        for item in query["required_items"] + query["forbidden_items"]:
            if not item.get("locator"):
                continue
            heading = locator_parts(item["locator"])["heading"]
            assert f"## {heading}" in corpus or f"# {heading}" in corpus, (
                f"locator {item['locator']} anchors a heading absent from the grounded corpus")


def test_every_cited_memory_id_exists_in_the_real_frozen_snapshot(dataset):
    frozen_013 = json.loads(CONSOLIDATION_DATASET.read_text(encoding="utf-8"))
    real_events = set()
    for query in frozen_013["queries"]:
        real_events.update(str(item) for item in query["expected_source_event_ids"])
        for location in query["locators"]:
            if location.get("kind") == "event":
                real_events.add(str(location["event_id"]))
        for unit in query["relevance_units"]:
            real_events.update(str(item) for item in unit["source_event_ids"])
    cited = set()
    for query in dataset["queries"]:
        for item in query["required_items"]:
            if item.get("memory_id"):
                cited.add(str(item["memory_id"]))
    assert cited, "at least one required item must pin a real same-snapshot memory_id"
    assert cited <= real_events, f"dataset cites memory ids absent from the frozen snapshot: {sorted(cited - real_events)}"


def test_every_grounded_source_names_existing_material(dataset):
    for query in dataset["queries"]:
        referenced = PATH_TOKEN.findall(query["_meta"]["grounded_source"])
        assert referenced, f"query {query['query_id']} grounded_source names no real material"
        for reference in referenced:
            assert (ROOT / reference).exists(), f"grounded_source names absent material: {reference}"
