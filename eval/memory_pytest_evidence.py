"""Optional pytest observer for real memory calls; it never writes storage."""
import json
from pathlib import Path
from time import perf_counter

import pytest


def scope_ids(parameters, result=None):
    values = []
    for key in ("scope_id", "scope_ref"):
        value = parameters.get(key)
        values.extend(value if isinstance(value, list) else [value])
    values.extend(row.get("knowledge_scope_id") for row in (result or {}).get("memories", []))
    return sorted({int(value) for value in values if str(value).isdecimal() and int(value) > 0})


def observe_result(operation, parameters, result, *, elapsed):
    fingerprints = {}
    for key, name in (("package_fingerprint", "package"), ("before_fingerprint", "before"), ("after_fingerprint", "after")):
        if result.get(key):
            fingerprints[name] = result[key]
    paths = {"operation": operation, "elapsed_seconds": elapsed}
    for key in ("counts", "provenance_validation", "injection_flags", "impact"):
        if key in result:
            paths[key] = result[key]
    if operation == "record" and result.get("provenance_validation"):
        validation = result["provenance_validation"]
        provenance = validation.get("provenance")
        checks = {"provenance": validation.get("validated") is True}
        attributions = validation.get("attributions", [])
        if provenance == "hard":
            references = set(parameters.get("evidence_refs") or [])
            checks["hard_attribution"] = bool(references) and references == {
                row.get("evidence_id") for row in attributions} and all(
                    all(row.get(key) for key in ("source_id", "version_id", "version", "position", "content_hash"))
                    for row in attributions)
        if provenance in {"soft", "distilled"}:
            required = {"source", "confidence", "model_version", "time", "supporting_evidence"}
            checks["soft_metadata"] = required <= (parameters.get("inference_meta") or {}).keys() and checks["provenance"]
        if provenance == "distilled":
            checks["distilled_source_chain"] = bool(attributions) and all(
                row.get("source_chain", {}).get("validated") is True for row in attributions)
        paths["write_checks"] = checks
    if "memories" in result:
        paths["memory_ids"] = [row["memory_id"] for row in result["memories"]]
        paths["excerpt_lengths"] = [len(row.get("content_excerpt", "")) for row in result["memories"]]
    if result.get("read_guidance"):
        paths["read_guidance"] = result["read_guidance"]
    return {"scenario": operation, "scope_ids": scope_ids(parameters, result),
            "request_ids": [result["request_id"]] if result.get("request_id") else [],
            "status": result.get("completion_status", result.get("status", "returned")),
            "failed_paths": result.get("failed_paths", result.get("memory_notice", {}).get("failed_paths",
                            result.get("counts", {}).get("failed_paths", []))), "fingerprints": fingerprints, "paths": paths}


def pytest_addoption(parser):
    parser.addoption("--memory-evidence", type=Path, help="Exclusive output path for actual memory invocation observations")


def pytest_configure(config):
    target = config.getoption("--memory-evidence")
    if target and target.exists():
        raise pytest.UsageError("memory evidence output exists; refusing overwrite")
    config._memory_observations = []


@pytest.fixture(autouse=True)
def observe_memory_calls(request, monkeypatch):
    if not request.config.getoption("--memory-evidence"):
        yield
        return
    from rag_mcp.services.memory_service import MemoryService
    from rag_mcp.services.memory_projection_store import MemoryProjectionStore
    from rag_mcp.services.memory_event_store import MemoryEventStore
    from rag_mcp.services.memory_reducer import projection_fingerprint

    record = {"nodeid": request.node.nodeid, "outcome": "not_run", "measurements": []}
    request.node._memory_observation = record
    request.config._memory_observations.append(record)

    def instrument(name):
        original = getattr(MemoryService, name)
        async def observed(self, *args, **kwargs):
            parameters = dict(args[0]) if args and isinstance(args[0], dict) else dict(kwargs)
            if name == "govern" and args:
                parameters["action"] = args[0]
            start = perf_counter()
            try:
                result = await original(self, *args, **kwargs)
            except Exception as error:
                record["measurements"].append({"scenario": name + ":rejected", "scope_ids": scope_ids(parameters),
                    "request_ids": [], "status": "rejected", "failed_paths": [str(error)], "fingerprints": {},
                    "paths": {"operation": name, "elapsed_seconds": perf_counter() - start, "error_type": type(error).__name__}})
                raise
            record["measurements"].append(observe_result(name, parameters, result, elapsed=perf_counter() - start))
            return result
        monkeypatch.setattr(MemoryService, name, observed)
    for name in ("record", "recall", "start_work", "govern"):
        instrument(name)

    original_inspect = MemoryProjectionStore.inspect
    async def inspected(self, state, sid):
        result = await original_inspect(self, state, sid)
        record["measurements"].append({"scenario": "six_projection_integrity", "scope_ids": [sid],
            "request_ids": [], "status": "passed" if all(row["matches_replay"] for row in result.values()) else "failed",
            "failed_paths": [name for name, row in result.items() if not row["matches_replay"]],
            "fingerprints": {name: row["fingerprint"] for name, row in result.items()}, "paths": result})
        return result
    monkeypatch.setattr(MemoryProjectionStore, "inspect", inspected)

    original_replay = MemoryEventStore.replay
    async def replayed(self, sid, **kwargs):
        events = await original_replay(self, sid, **kwargs)
        record["measurements"].append({"scenario": "event_log", "scope_ids": [sid],
            "request_ids": sorted({event["request_id"] for event in events}), "status": "observed", "failed_paths": [],
            "fingerprints": {"event_log": projection_fingerprint(events)},
            "paths": {"event_log": {"count": len(events), "foreign_scope_count": sum(event["knowledge_scope_id"] != sid for event in events)}}})
        return events
    monkeypatch.setattr(MemoryEventStore, "replay", replayed)
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    record = getattr(item, "_memory_observation", None)
    if record is not None and (report.when == "call" or report.failed):
        record["outcome"] = report.outcome


def pytest_sessionfinish(session, exitstatus):
    target = session.config.getoption("--memory-evidence")
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as stream:
            json.dump({"exitstatus": int(exitstatus), "tests": session.config._memory_observations}, stream, ensure_ascii=False, indent=2)
