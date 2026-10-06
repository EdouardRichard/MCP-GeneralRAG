from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


_REDUCER_SEAL = object()
PROJECTION_NAMES = ("entries", "dense", "links", "summary", "files", "salience")
GOVERNANCE_AXES = ("authority", "scope_meta", "mutability", "provenance_meta", "recoverability", "actionability")


def _governance_axes(event, payload):
    # Legacy fixtures lack event metadata; defaults describe their log context,
    # never claim evidence validation or permission to act.
    defaults = {
        "authority": {"source": "event_log", "event_id": event["event_id"]},
        "scope_meta": {"knowledge_scope_id": event["knowledge_scope_id"]},
        "mutability": {"correction": "supersede"},
        "provenance_meta": {"provenance": payload.get("provenance"),
                            "evidence_refs": payload.get("evidence_refs", []),
                            "inference_meta": payload.get("inference_meta")},
        "recoverability": {"source": "event_log"},
        "actionability": None,
    }
    return {axis: deepcopy(event.get(axis, defaults[axis])) for axis in GOVERNANCE_AXES}


@dataclass(frozen=True)
class ReducerState(Mapping):
    """Immutable reducer output. Copies returned to callers cannot alter it."""
    _serialized: str
    _seal: object

    def __getitem__(self, key):
        value = json.loads(self._serialized)[key]
        if key in {"entries", "dense", "salience"}:
            return {int(identifier): row for identifier, row in value.items()}
        return value

    def __iter__(self):
        return iter(json.loads(self._serialized))

    def __len__(self):
        return len(json.loads(self._serialized))

    def export(self):
        return {name: self[name] for name in self}


def require_reducer_state(state):
    if not isinstance(state, ReducerState) or state._seal is not _REDUCER_SEAL:
        raise TypeError("projection writes require sealed reducer output")
    return state


def _scoped_target(entries, memory_id, scope):
    target = entries.get(memory_id)
    if target is None:
        raise ValueError("MEMORY_SUPERSEDE_TARGET_INVALID")
    if target["knowledge_scope_id"] != scope:
        raise ValueError("MEMORY_EVIDENCE_SCOPE_MISMATCH")
    return target


def validate_window_control(event):
    payload = event.get('payload') or {}
    if (event.get('actor') != 'management' or event.get('authority', {}).get('source') != 'consolidation_control'
        or payload.get('control_adjudication') != {'decision': 'seal_window', 'effect': 'control_only', 'rule_version': '013.window.1'}):
        raise PermissionError('trusted consolidation control required')
    keys = {'payload_version', 'grant_type', 'start', 'end', 'frozen_at', 'high_water_mark', 'source_refs',
            'reference_refs', 'support_refs', 'original_window_id', 'captured_policy', 'captured_vocabulary',
            'policy_hash', 'vocabulary_hash', 'control_adjudication', 'eligibility_token'}
    if set(payload) != keys or payload['payload_version'] != 2 or not payload['source_refs']:
        raise ValueError('invalid consolidation window seal')
    token = payload['eligibility_token']
    if set(token) != {'eligibility_id', 'scope_id', 'run_id', 'holder_instance_id', 'writer_lease_id', 'eligibility_version'}:
        raise ValueError('invalid consolidation window token')
    for key in ('eligibility_id', 'run_id', 'holder_instance_id'):
        UUID(token[key])
    if token['scope_id'] != event['knowledge_scope_id']:
        raise ValueError('SCOPE_MISMATCH')
    for key in ('writer_lease_id', 'eligibility_version'):
        if isinstance(token[key], bool) or not isinstance(token[key], int) or token[key] <= 0:
            raise ValueError('invalid consolidation window token')
    start, end, frozen = (datetime.fromisoformat(payload[key]) for key in ('start', 'end', 'frozen_at'))
    if any(value.tzinfo is None for value in (start, end, frozen)) or start > end or end != frozen:
        raise ValueError('invalid consolidation window timeline')
    high_water = payload['high_water_mark']
    if isinstance(high_water, bool) or not isinstance(high_water, int) or not 0 < high_water < event['event_id']:
        raise ValueError('invalid consolidation window high water')
    from rag_mcp.services.memory_policy import MemoryPolicy
    policy = MemoryPolicy.model_validate(payload['captured_policy'])
    if not policy.consolidation_enabled or policy.consolidation is None:
        raise ValueError('invalid consolidation window policy')
    return payload


def reduce_events(events, *, initial_state=None):
    history = sorted(deepcopy(list(events)), key=lambda item: item["event_id"])
    if len({event["event_id"] for event in history}) != len(history):
        raise ValueError("duplicate authority event")
    if initial_state is not None:
        require_reducer_state(initial_state)
    entries = initial_state["entries"] if initial_state is not None else {}
    salience = initial_state["salience"] if initial_state is not None else {}
    bindings = {int(key): row for key, row in initial_state["bindings"].items()} if initial_state is not None else {}
    consolidation_state = initial_state['consolidation_state'] if initial_state is not None else {
        'window_seals': {}, 'potential_results': {}, 'potential_source_outcomes': {},
        'potential_checkpoint': None, 'unresolved_windows': []}
    for index, event in enumerate(history):
        eid = event["aggregate_id"]
        scope = event["knowledge_scope_id"]
        if not isinstance(scope, int) or isinstance(scope, bool) or scope <= 0:
            raise ValueError("MISSING_KNOWLEDGE_SCOPE")
        payload = dict(event.get("payload") or {})
        kind = event["event_type"]
        timestamp = event.get("occurred_at")
        if hasattr(timestamp, "isoformat"):
            timestamp = timestamp.isoformat()
        if kind in {"assert", "revise", "consolidate"}:
            governance = _governance_axes(event, payload)
            if eid in entries:
                raise ValueError("memory identity is immutable; revision requires supersede")
            if kind == "revise":
                target = _scoped_target(entries, payload.get("supersedes_memory_id"), scope)
                if target["status"] != "active" or (target.get("provenance") == "hard" and payload.get("provenance") != "hard"):
                    raise ValueError("MEMORY_SUPERSEDE_TARGET_INVALID")
                target.update(status="superseded", superseded_by=eid,
                              valid_to=payload.get("valid_from") or timestamp, invalidated_at=timestamp)
            status = payload.get("status", "active")
            if status not in {"active", "quarantined"}:
                raise ValueError("invalid assert status")
            entries[eid] = {**payload, **governance, "memory_id": eid, "knowledge_scope_id": scope,
                            "status": status, "valid_from": payload.get("valid_from") or timestamp,
                            "valid_to": None, "observed_at": timestamp,
                            "superseded_by": None, "invalidated_at": None,
                            "retention_stage": "active",
                            "source_event_id": event["event_id"]}
            salience[eid] = {**governance, "memory_id": eid, "knowledge_scope_id": scope, "salience": 0.,
                             "access_count": 0, "decay_rate": payload.get("decay_rate", .05),
                             "last_access_at": None, "evidence_refs": payload.get("evidence_refs", []),
                             "reinforced_at": None,
                             "provenance": payload.get("provenance"), "inference_meta": payload.get("inference_meta")}
        elif kind == "retract":
            target = _scoped_target(entries, eid, scope)
            target.update(status="retired", retention_stage="tombstone", valid_to=timestamp, invalidated_at=timestamp)
        elif kind == "access":
            _scoped_target(entries, eid, scope)
            state = salience[eid]
            # Captured policy makes replay stable; legacy access retains its prior rate.
            state["decay_rate"] = payload.get("decay_rate", state["decay_rate"])
            state["access_count"] += 1
            from rag_mcp.services.salience_service import SalienceService
            from datetime import datetime
            age = (datetime.fromisoformat(timestamp) - datetime.fromisoformat(state["last_access_at"])).total_seconds() / 86400 if state["last_access_at"] else 0
            state["salience"] = SalienceService(beta=state["decay_rate"]).update(state["salience"], access_count=1, age_days=age)
            state["last_access_at"] = timestamp
            state["reinforced_at"] = timestamp
        elif kind == "rollback":
            if initial_state is not None:
                raise ValueError("rollback requires complete authority history")
            point = payload.get("event_point")
            if not isinstance(point, int) or point >= event["event_id"] or not payload.get("reason"):
                raise ValueError("MEMORY_ROLLBACK_FORBIDDEN")
            if not any(item["event_id"] == point and item["knowledge_scope_id"] == scope for item in history[:index]):
                raise ValueError("MEMORY_ROLLBACK_FORBIDDEN")
            restored = reduce_events(item for item in history[:index] if item["event_id"] <= point)
            unaffected = {mid: row for mid, row in entries.items() if row["knowledge_scope_id"] != scope}
            restored_ids = set(restored["entries"])
            for mid, row in entries.items():
                if row["knowledge_scope_id"] == scope and mid not in restored_ids:
                    # A later identity becomes a tombstone; its immutable history remains.
                    unaffected[mid] = {**row, "status": "retired", "retention_stage": "tombstone", "valid_to": timestamp, "invalidated_at": timestamp}
            unaffected.update({mid: row for mid, row in restored["entries"].items() if row["knowledge_scope_id"] == scope})
            entries = unaffected
            restored_bindings = {key: row for key, row in restored["bindings"].items() if row["knowledge_scope_id"] == scope}
            bindings = {key: ({**row, "status": "disabled"} if row["knowledge_scope_id"] == scope else row) for key, row in bindings.items()}
            bindings.update(restored_bindings)
            # Preserve all access events, including post-point use. New identities
            # removed by rollback retain salience audit but cannot supply facts.
        elif kind == "grant":
            if payload.get('grant_type') == 'consolidation_window':
                seal = validate_window_control(event)
                consolidation_state['window_seals'][str(event['event_id'])] = {
                    **deepcopy(seal), 'window_id': event['event_id'], 'knowledge_scope_id': scope}
                consolidation_state['unresolved_windows'].append(event['event_id'])
            elif "binding_id" in payload:
                bindings[payload["binding_id"]] = {
                    **{key: payload[key] for key in ("binding_id", "binding_kind", "binding_value", "priority", "status")},
                    "knowledge_scope_id": scope}
            elif "retention_stage" in payload:
                target = _scoped_target(entries, eid, scope)
                stage = payload["retention_stage"]
                if target["status"] != "active" or stage != {"active": "compressed", "compressed": "archived", "archived": "tombstone"}.get(target["retention_stage"]):
                    raise ValueError("MEMORY_WRITE_UNAVAILABLE: invalid retention transition")
                target["retention_stage"] = stage
                if stage == "tombstone":
                    target.update(status="retired", valid_to=timestamp, invalidated_at=timestamp)
        else:
            raise ValueError("invalid authority event type")
    dense, links, summary, files = {}, {}, {}, {}
    for mid, row in entries.items():
        if row["status"] in {"retired", "quarantined"}:
            continue
        branch = f"{row['knowledge_scope_id']}/{row.get('kind', 'episodic')}"
        path = f"012-v1/{branch}/{mid}.md"
        if row["retention_stage"] in {"compressed", "archived"}:
            path += ".gz"
        if row["retention_stage"] == "archived":
            path = "archives/" + path
        files[path] = {**row, "path": path, "body": f"# Memory {mid}\n\n" + json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)}
        if row["retention_stage"] == "archived":
            continue
        dense[mid] = deepcopy(row)
        for ref in row.get("evidence_refs", []):
            links[f"{mid}/evidence/{ref}"] = {**row, "from_id": mid, "to_id": ref, "relation": "evidence"}
        if row.get("supersedes_memory_id"):
            links[f"{mid}/supersedes"] = {**row, "from_id": mid, "to_id": row["supersedes_memory_id"], "relation": "supersedes"}
        summary.setdefault(branch, []).append(deepcopy(row))
    state = {"entries": entries, "dense": dense, "links": links, "summary": summary,
             "files": files, "salience": salience, "bindings": bindings, 'consolidation_state': consolidation_state}
    return ReducerState(json.dumps(state, sort_keys=True, separators=(",", ":"), default=str), _REDUCER_SEAL)


def projection_fingerprint(state):
    if isinstance(state, ReducerState):
        state = state.export()
    normalized = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()
