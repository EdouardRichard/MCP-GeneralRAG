from __future__ import annotations

import hashlib
import json


def reduce_events(events):
    entries = {}
    salience = {}
    for event in sorted(events, key=lambda item: item["event_id"]):
        eid = event["aggregate_id"]
        payload = dict(event.get("payload") or {})
        if event["event_type"] == "assert":
            entries[eid] = {**payload, "memory_id": eid, "knowledge_scope_id": event["knowledge_scope_id"], "status": "active"}
            salience.setdefault(eid, {"salience": 0.0, "access_count": 0})
        elif event["event_type"] == "revise" and eid in entries:
            entries[eid].update(payload)
            entries[eid]["status"] = "active"
        elif event["event_type"] in {"retract", "rollback"} and eid in entries:
            entries[eid]["status"] = "retired"
        elif event["event_type"] == "access":
            state = salience.setdefault(eid, {"salience": 0.0, "access_count": 0})
            state["access_count"] += 1
            state["salience"] += 1.0
    return {"entries": entries, "salience": salience}


def projection_fingerprint(state):
    normalized = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()
