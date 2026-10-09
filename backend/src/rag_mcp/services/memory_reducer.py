from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

def _make_reducer_seal():
    """T093: keep the attestation token in a closure, not an importable attribute.

    The earlier ``_REDUCER_SEAL = object()`` module attribute made the "sealed"
    claim trivially forgeable (`ReducerState(payload, memory_reducer._REDUCER_SEAL)`).
    The token is now reachable only through the two private callables below.
    """
    token = object()

    def _construct(serialized: str) -> "ReducerState":
        return ReducerState(serialized, token)

    def _verify(state) -> "ReducerState":
        if not isinstance(state, ReducerState) or state._seal is not token:
            raise TypeError("projection writes require sealed reducer output")
        return state

    return _construct, _verify


_construct_reducer_state, _require_reducer_state = _make_reducer_seal()
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
    return _require_reducer_state(state)


def _scoped_target(entries, memory_id, scope):
    target = entries.get(memory_id)
    if target is None:
        raise ValueError("MEMORY_SUPERSEDE_TARGET_INVALID")
    if target["knowledge_scope_id"] != scope:
        raise ValueError("MEMORY_EVIDENCE_SCOPE_MISMATCH")
    return target


def validate_propagation_control(event):
    """Trusted deterministic-propagation continuation seal (T060).

    Carries only the permanent traversal material of a wave that produced no
    lifecycle effect; it never grants create/merge/link/context/candidate or
    source-consumption authority.
    """
    payload = event.get('payload') or {}
    if (event.get('actor') != 'management' or event.get('authority', {}).get('source') != 'consolidation_control'
        or payload.get('control_adjudication') != {'decision': 'seal_propagation', 'effect': 'control_only',
                                                    'rule_version': '013.propagation.1'}):
        raise PermissionError('trusted consolidation control required')
    keys = {'payload_version', 'grant_type', 'trigger', 'visited_memory_ids', 'depth', 'frontier_memory_ids',
            'continuation_key', 'vocabulary_version', 'control_adjudication', 'eligibility_token'}
    if set(payload) != keys or payload['payload_version'] != 2:
        raise ValueError('invalid consolidation propagation seal')
    token = payload['eligibility_token']
    if set(token) != {'eligibility_id', 'scope_id', 'run_id', 'holder_instance_id', 'writer_lease_id',
                      'eligibility_version'}:
        raise ValueError('invalid consolidation propagation token')
    for key in ('eligibility_id', 'run_id', 'holder_instance_id'):
        UUID(token[key])
    if token['scope_id'] != event['knowledge_scope_id']:
        raise ValueError('SCOPE_MISMATCH')
    for key in ('writer_lease_id', 'eligibility_version'):
        if isinstance(token[key], bool) or not isinstance(token[key], int) or token[key] <= 0:
            raise ValueError('invalid consolidation propagation token')
    trigger = payload['trigger']
    if (not isinstance(trigger, dict)
        or set(trigger) != {'kind', 'event_id', 'evidence_id', 'version', 'observed_at', 'proof'}
        or trigger['kind'] not in ('authority_event', 'evidence_revocation', 'support_expiry')
        or not isinstance(trigger['proof'], dict) or not trigger['proof']
        or (trigger['event_id'] is None and trigger['evidence_id'] is None)
        or not isinstance(trigger['version'], str) or not trigger['version']
        or not isinstance(trigger['observed_at'], str)
        or datetime.fromisoformat(trigger['observed_at']).tzinfo is None):
        raise ValueError('invalid consolidation propagation trigger')
    depth = payload['depth']
    if isinstance(depth, bool) or not isinstance(depth, int) or not 0 <= depth <= 32:
        raise ValueError('invalid consolidation propagation depth')
    visited = payload['visited_memory_ids']
    if (not isinstance(visited, list) or not visited or len(visited) > 128 or len(set(visited)) != len(visited)
        or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in visited)):
        raise ValueError('invalid consolidation propagation visited set')
    frontier = payload['frontier_memory_ids']
    if (not isinstance(frontier, list) or len(frontier) > 5000 or len(set(frontier)) != len(frontier)
        or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in frontier)):
        raise ValueError('invalid consolidation propagation frontier')
    for key in ('continuation_key', 'vocabulary_version'):
        value = payload[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('invalid consolidation propagation identity')
    return payload


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
    groups = {}
    for event in history:
        if event['event_type'] == 'consolidate' and event['payload'].get('payload_version') == 2:
            from rag_mcp.services.memory_validators import validate_consolidation_payload
            payload = validate_consolidation_payload(event)
            groups.setdefault(payload['group_key'], []).append(event)
    complete_groups = set()
    for key, members in groups.items():
        first = members[0]['payload']
        indexes = [e['payload']['effect_index'] for e in members]
        if (indexes != list(range(len(members))) or len(members) > first['effect_count']
            or any((e['knowledge_scope_id'], e['payload']['group_id'], e['payload']['effect_count'],
                    e['payload']['window_id'], e['payload']['created_by_run']) != (
                    members[0]['knowledge_scope_id'], first['group_id'], first['effect_count'],
                    first['window_id'], first['created_by_run']) for e in members)):
            raise ValueError('CONSOLIDATION_GROUP_INVALID')
        if len(members) == first['effect_count']:
            complete_groups.add(key)
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
        v2 = kind == 'consolidate' and payload.get('payload_version') == 2
        if v2 and payload['group_key'] not in complete_groups:
            continue
        if v2 and payload['operation'] != 'create':
            target = _scoped_target(entries, eid, scope)
            effect = payload['approved_effect']
            if payload['operation'] in ('merge', 'invalidate'):
                lifecycle = effect['lifecycle']
                target.update(status=lifecycle['status'], valid_to=lifecycle['valid_to'],
                    invalidated_at=timestamp, superseded_by=lifecycle['replacement_id'], retention_stage='tombstone')
            if effect.get('context'):
                context = effect['context']
                target.update(context_digest=context['context_digest'], keywords=context['keywords'],
                    context_version=context['context_version'], context_source_event_id=event['event_id'],
                    context=context)
            if effect.get('candidate'):
                candidate = effect['candidate']
                target.update(promote_candidate_at=candidate['promote_candidate_at'],
                              candidate_version=candidate['candidate_version'], candidate_basis=candidate)
            if effect['links']:
                registry = target.setdefault('approved_links', {})
                for link in effect['links']:
                    registry[f"{link['from_id']}/{link['relation_type']}/{link['to_id']}"] = {
                        **link, 'knowledge_scope_id': scope, 'source_event_id': event['event_id']}
            target['state_event_id'] = event['event_id']
        elif kind in {"assert", "revise", "consolidate"}:
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
            if v2:
                entries[eid]['state_event_id'] = event['event_id']
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
            from datetime import datetime

            from rag_mcp.services.salience_service import SalienceService
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
            if payload.get('payload_version') == 2:
                for row in entries.values():
                    if row['knowledge_scope_id'] == scope:
                        row['state_event_id'] = event['event_id']
                historical = consolidation_state['potential_results']
                consolidation_state = restored['consolidation_state']
                consolidation_state['potential_results'] = {
                    **{key: {**value, 'rolled_back': True} for key, value in historical.items()},
                    **consolidation_state['potential_results']}
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
            elif payload.get('grant_type') == 'consolidation_propagation':
                seal = validate_propagation_control(event)
                # Only materialized on demand so a scope without propagation
                # control keeps the exact 0095 SQL/Python replay parity shape.
                consolidation_state.setdefault('propagation_seals', {})[str(event['event_id'])] = {
                    **deepcopy(seal), 'seal_id': event['event_id'], 'knowledge_scope_id': scope}
            elif payload.get('grant_type') in ('promotion_requested', 'promotion_observed'):
                # The permanent grant carries the projected pointer snapshot; only
                # the trusted management promotion transaction may append it, and
                # an observation must extend the exact task identity it belongs to.
                from rag_mcp.services.memory_validators import validate_promotion_pointer
                validate_promotion_pointer(event)
                target = _scoped_target(entries, eid, scope)
                previous = target.get('promotion_pointer')
                pointer = deepcopy(payload['pointer'])
                if payload['grant_type'] == 'promotion_requested':
                    if previous is not None and previous.get('candidate_version') == pointer['candidate_version']:
                        raise ValueError('duplicate promotion request')
                elif (previous is None or previous.get('task_id') != pointer['task_id']
                      or previous.get('candidate_version') != pointer['candidate_version']
                      or previous.get('source_id') != pointer['source_id']
                      or previous.get('initial_processing_run_id') != pointer['initial_processing_run_id']
                      or pointer['authority_event_ids'][:-1] != list(previous.get('authority_event_ids', ()))):
                    raise ValueError('promotion observation does not extend the existing task')
                target['promotion_pointer'] = pointer
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
        if v2 and payload['effect_index'] == payload['effect_count'] - 1:
            members = groups[payload['group_key']]
            consolidation_state['potential_results'][payload['group_key']] = {
                'group_id': payload['group_id'], 'event_ids': [e['event_id'] for e in members],
                'memory_ids': [e['aggregate_id'] for e in members if e['payload']['operation'] == 'create'],
                'window_id': payload['window_id'], 'rolled_back': False}
            for member in members:
                for outcome in member['payload']['source_outcomes']:
                    ref = next(r for r in member['payload']['source_refs'] if r['source_event_id'] == outcome['source_event_id'])
                    identity = [ref[k] for k in ('memory_id', 'source_event_id', 'state_event_id')]
                    consolidation_state['potential_source_outcomes']['/'.join(map(str, identity))] = {
                        **outcome, 'source_version': identity}
            seal = consolidation_state['window_seals'].get(str(payload['window_id']))
            if seal:
                consolidation_state['potential_checkpoint'] = max(
                    consolidation_state['potential_checkpoint'] or seal['end'], seal['end'])
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
        links.update(deepcopy(row.get('approved_links', {})))
    state = {"entries": entries, "dense": dense, "links": links, "summary": summary,
             "files": files, "salience": salience, "bindings": bindings, 'consolidation_state': consolidation_state}
    return _construct_reducer_state(
        json.dumps(state, sort_keys=True, separators=(",", ":"), default=str))


def projection_fingerprint(state):
    if isinstance(state, ReducerState):
        state = state.export()
    normalized = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()
