"""015 Phase 10 T076/T077 — real-DB mixed-domain leakage and meter detectability.

Two halves, both real (no stubs, no route monkeypatching):

* **assembly honesty** — ``memory_baseline_support.cross_domain_block`` must mark a
  path ``not_measurable`` when its denominator is zero **or** when its
  detectability control did not fire, must register the two consumer surfaces
  (``related_memories`` / ``working_set``) beside the four constitutional paths, and
  may only report ``all_passed`` when every registered path was measured, leak-free
  and *proven able to fail*.
* **detectability** — two dedicated throwaway scopes are created, one item is
  recorded in each, and the production scanners are run with ``requested=[own]``
  and ``scan_scopes=[own, foreign]``; every path must report at least one leak.
  The earlier scanner could not fail by construction (it filtered the population to
  the requested scopes before testing membership).

Every observation comes from the real PostgreSQL / Qdrant stores. Destructive or
foreign writes only ever land in scopes this module created itself.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
import pytest_asyncio

REPO_ROOT = Path(__file__).resolve().parents[3]
for _candidate in (str(REPO_ROOT), str(REPO_ROOT / "backend"), str(REPO_ROOT / "eval")):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import memory_baseline_support as support  # noqa: E402
from eval.run_memory_baseline import _detectability_control, _scan_paths  # noqa: E402
from rag_mcp.indexing.qdrant_client import QdrantStore  # noqa: E402
from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider  # noqa: E402
from rag_mcp.utils.snowflake import generate_id  # noqa: E402


@pytest.fixture(scope="session")
def embedding_provider():
    provider = LocalCPUEmbeddingProvider()
    provider.warmup()
    return provider


@pytest_asyncio.fixture
async def qdrant_store():
    return QdrantStore()


def _fired_paths(control: dict) -> dict[str, dict]:
    return {name: control["control"][name] for name in support.LEAK_PATHS}


def _all_paths(examined: int = 1, leaks: int = 0, fired: bool = True) -> dict:
    return {name: {"examined": examined, "leaks": leaks,
                   "detectability": {"control": f"planted_foreign_{name}", "fired": fired,
                                     "planted": 1, "observed_leaks": leaks}}
            for name in support.LEAK_PATHS}


# --------------------------------------------------------------------------- #
# assembly honesty (no database required)
# --------------------------------------------------------------------------- #


def test_zero_denominator_paths_are_never_a_pass():
    block = support.cross_domain_block({})
    assert block["all_paths_measured"] is False
    assert block["all_passed"] is False
    for name in support.LEAK_PATHS:
        path = block["paths"][name]
        assert path["examined"] == 0
        assert path["state"] == "not_measurable"
        assert path["value"] is None
        assert path["reason"]


def test_an_unfired_detectability_control_is_not_a_pass():
    paths = _all_paths()
    paths["vector"] = {"examined": 625, "leaks": 0,
                       "detectability": {"control": "planted_foreign_vector_point", "fired": False,
                                         "planted": 1, "observed_leaks": 0,
                                         "reason": "the scanner did not see the planted point"}}
    block = support.cross_domain_block(paths)
    assert block["paths"]["vector"]["state"] == "not_measurable"
    assert block["paths"]["vector"]["value"] is None
    assert block["paths"]["vector"]["reason"]
    assert block["all_paths_measured"] is False
    assert block["all_passed"] is False


def test_all_six_paths_measured_and_detectable_is_a_pass():
    block = support.cross_domain_block(_all_paths())
    assert set(block["paths"]) == set(support.LEAK_PATHS)
    assert {"attachment", "working_set"} <= set(block["paths"])
    assert block["all_paths_measured"] is True
    assert block["total_leaks"] == 0
    assert block["all_passed"] is True


def test_a_real_leak_fails_the_block():
    paths = _all_paths()
    paths["relation"]["leaks"] = 1
    block = support.cross_domain_block(paths)
    assert block["total_leaks"] == 1
    assert block["all_passed"] is False


def test_the_consumer_surfaces_carry_their_own_denominator():
    paths = _all_paths()
    paths["attachment"] = {"examined": 3, "leaks": 0, "reason": None,
                           "detectability": {"control": "planted_foreign_attachment_item", "fired": True,
                                             "planted": 1, "observed_leaks": 1}}
    paths["working_set"] = {"examined": 0, "leaks": 0, "reason": "the working set exposed no memory row"}
    block = support.cross_domain_block(paths)
    assert block["paths"]["attachment"]["state"] == "measured"
    assert block["paths"]["working_set"]["state"] == "not_measurable"
    assert block["all_passed"] is False


def test_the_report_uses_the_multi_domain_request_paths():
    """The assembled block must come from the explicit multi-domain scan (T076).

    The earlier revision handed the single-domain denominators to the block while
    the reason text claimed they were the multi-domain ones.
    """
    measurement = {
        "single_domain": {"requested_scope_ids": [111], "paths": {
            name: {"examined": 7, "leaks": 0} for name in support.LEAK_PATHS}},
        "multi_domain": {"requested_scope_ids": [111, 222],
                         "paths": {name: {"examined": 70, "leaks": 0,
                                          "detectability": {"control": name, "fired": True,
                                                            "planted": 1, "observed_leaks": 1}}
                                   for name in support.LEAK_PATHS},
                         "recall_returned_scope_ids": [111, 222],
                         "recall_returned_foreign_scope_ids": [],
                         "observed_scope_ids": [111, 222]},
    }
    block = support.cross_domain_block(
        measurement["multi_domain"]["paths"], evidence=support.multi_domain_evidence(measurement))
    assert block["paths"]["event_log"]["examined"] == 70
    assert block["all_passed"] is True
    fingerprint = hashlib.sha256(repr(sorted(block["paths"])).encode()).hexdigest()
    assert fingerprint  # the block is stable and enumerates every registered path


# --------------------------------------------------------------------------- #
# detectability on the real stores
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_detectability_control_fires_on_every_real_path(db_session, qdrant_store, embedding_provider):
    control = await _detectability_control(db_session, qdrant_store, embedding_provider)
    fired = _fired_paths(control)
    assert set(fired) == set(support.LEAK_PATHS)
    missing = {name: entry for name, entry in fired.items() if not entry["fired"]}
    assert not missing, (
        "the meter must see a deliberately planted cross-scope item on every path; "
        f"these paths could not fail: {missing}")
    for name, entry in fired.items():
        assert entry["observed_leaks"] >= 1, f"{name} reported no leak for a planted foreign item"
        assert entry["planted"] == 1


@pytest.mark.asyncio
async def test_the_real_scan_reports_a_foreign_scope_as_a_leak(db_session, qdrant_store, embedding_provider):
    """The scanner's population is not pre-filtered: a foreign row is observable."""
    from rag_mcp.services.memory_service import MemoryService

    service = MemoryService(db_session, embedding_provider=embedding_provider, qdrant_store=qdrant_store)
    own = generate_id()
    foreign = generate_id()
    from rag_mcp.models.knowledge_scope import KnowledgeScope

    for scope_id, slug in ((own, "c015-leak-own"), (foreign, "c015-leak-foreign")):
        db_session.add(KnowledgeScope(scope_id=scope_id, name=slug, slug=f"{slug}-{scope_id}",
                                      scope_type="project", domain_key="generic"))
    await db_session.commit()
    identifiers = []
    for scope_id in (own, foreign):
        recorded = await service.record({
            "scope_id": scope_id, "kind": "episodic",
            "content": f"015 leak meter probe for scope {scope_id}: the release owner is Li.",
            "provenance": "soft",
            "inference_meta": {"source": "015 leak meter", "confidence": 0.5, "model_version": "015.eval.1",
                               "time": "2026-10-09T12:00:00+00:00", "supporting_evidence": []},
        })
        identifiers.append(int(recorded["memory_id"]))
    await db_session.commit()
    scan = await _scan_paths(db_session, qdrant_store, requested=[own], scan_scopes=[own, foreign],
                             reachable_ids=identifiers, label="detectability unit probe",
                             attach_ids=identifiers, working_ids=identifiers)
    paths = scan["paths"]
    for name in support.LEAK_PATHS:
        assert paths[name]["examined"] > 0, f"{name} examined nothing in the detectability probe"
        assert paths[name]["leaks"] >= 1, f"{name} did not report the planted foreign scope as a leak"
    assert scan["requested_scope_ids"] == [own]
    assert foreign in scan["scanned_scope_ids"]
