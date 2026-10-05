import asyncio
import importlib.util
import json
import os
from pathlib import Path
from time import perf_counter

import pytest
from qdrant_client.models import FieldCondition, MatchValue

from rag_mcp.indexing.memory_vectors import revision_filter, revision_point_id
from rag_mcp.services.memory_service import MemoryService
from tests.integration.test_012_live_reader import scope_and_payload


@pytest.mark.asyncio
async def test_actual_status_two_arms_and_budget_diagnostics(db_session):
    sid, payload = await scope_and_payload(db_session)
    service = MemoryService(db_session)
    memory = await service.record(payload)
    manifest = await service.projections.current(sid)
    client = service.projections.qdrant._client
    await asyncio.to_thread(client.set_payload, collection_name=manifest.payload["collection"],
        points=[revision_point_id(sid, manifest.source_event_id, memory["memory_id"])], payload={"status": "retired"})
    vector = await service.projections.embedding.embed_query("explicit scope for each memory request")
    stale_filter = revision_filter(sid, manifest.source_event_id)
    stale_filter.must.append(FieldCondition(key="status", match=MatchValue(value="active")))
    unsafe = await asyncio.to_thread(client.query_points, collection_name=manifest.payload["collection"],
                                     query=vector, query_filter=stale_filter, limit=40)
    started = perf_counter()
    safe = await service.recall(scope_ref=[str(sid)], query="explicit scope for each memory request")
    semantic_latency = perf_counter() - started
    assert not unsafe.points
    assert [row["memory_id"] for row in safe["memories"]] == [memory["memory_id"]]
    assert semantic_latency < 3
    assert all(row["matches_replay"] for row in (await service.rebuild(sid, actor="management")).values())
    reads = []
    for parameters in ({"memory_ids": [memory["memory_id"]]}, {}, {"kind": "procedural"},
                       {"query": "explicit scope for each memory request"}):
        started = perf_counter()
        result = await service.recall(scope_ref=[str(sid)], **parameters)
        elapsed = perf_counter() - started
        assert elapsed < 3 and result["counts"]["characters"] <= 6000
        assert all(len(row["content_excerpt"]) <= 300 for row in result["memories"])
        reads.append({"mode": result["counts"]["mode"], "elapsed_seconds": elapsed,
                      "counts": result["counts"], "request_id": result["request_id"]})
    packages = []
    for budget, maximum in (("standard", 2000), ("compact", 800), ("minimal", 300)):
        started = perf_counter()
        first = await service.start_work(scope_ref=str(sid), budget=budget)
        elapsed = perf_counter() - started
        second = await service.start_work(scope_ref=str(sid), budget=budget)
        request_ids = [first.pop("request_id"), second.pop("request_id")]
        assert first == second and first["counts"]["characters"] <= maximum
        assert elapsed < 2 and first["read_guidance"]
        packages.append({"budget": budget, "maximum": maximum, "elapsed_seconds": elapsed,
                         "characters": first["counts"]["characters"], "request_ids": request_ids,
                         "fingerprint": first["package_fingerprint"], "byte_stable": True,
                         "read_guidance": first["read_guidance"]})
    root = Path(__file__).parents[3]
    spec = importlib.util.spec_from_file_location("memory_read_diagnostics", root / "eval/memory_read_diagnostics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = {"status": "passed", "scope_id": sid,
        "status_staleness": {"status_pushdown": {"returned": len(unsafe.points), "false_negatives": 1},
                             "pg_post_filter": {"returned": len(safe["memories"]), "false_negatives": 0,
                                                "elapsed_seconds": semantic_latency, "request_id": safe["request_id"]}},
        "recall": reads, "packages": packages, "decay_comparison": module.decay_comparison(),
        "feedback_experiment": "Deterministic 120-day feedback experiment with production salience and RRF; no benefit claim."}
    target = os.getenv("MEMORY_DIAGNOSTICS_OUTPUT")
    if target:
        with Path(target).open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
