"""Pure approval and event planning over explicitly supplied trusted facts.

No function in this module acquires authority, reads a store, or commits effects.
The caller must re-collect these facts under the writer fence before committing.
"""
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import date, datetime
from hashlib import sha256

from rag_mcp.orchestration.consolidation_pipeline import (
    Decision,
    SourceVersion,
    TrustedContext,
    freeze,
    thaw,
)
from rag_mcp.services.memory_validators import detect_submission, redact_submission

RULE_VERSION = '013.adjudication.2'
CREATES = frozenset(('extract_fact', 'distill_procedure'))
VERSION_FIELDS = ('memory_id', 'source_event_id', 'state_event_id', 'content_hash')
_COMMAND_SEAL = object()
_COMMAND_ISSUER_SEAL = object()


def stable_key(value):
    def serializable(item):
        if isinstance(item, (datetime, date)):
            return item.isoformat()
        if is_dataclass(item):
            return serializable(asdict(item))
        if isinstance(item, Mapping):
            return {str(k): serializable(v) for k, v in item.items()}
        if isinstance(item, (tuple, list)):
            return [serializable(v) for v in item]
        if isinstance(item, (set, frozenset)):
            return sorted(serializable(v) for v in item)
        return item

    return sha256(json.dumps(serializable(thaw(freeze(value))), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def memory_ref(row):
    return {key: row.get(key, row.get('source_event_id') if key == 'state_event_id' else None)
            for key in VERSION_FIELDS}


class Rejection(Exception):
    pass


def reject(reason, *, key=None):
    return Decision(key or stable_key({'reason': reason}), 'reject', (reason,), rule_version=RULE_VERSION)


def _rejection_value(value, references=None):
    """Typed audit encoding keeps invalid numbers distinct from JSON values."""
    endpoints = set(_endpoint_paths(value)) if isinstance(value, Mapping) else set()

    def encode(item, path=()):
        if isinstance(item, Mapping):
            if path in endpoints and set(item) == {'proposal_ref'}:
                label = item['proposal_ref']
                if isinstance(label, str):
                    return ['proposal_ref', (references or {}).get(label, 'unresolved')]
            pairs = [[key if isinstance(key, str) else encode(key), encode(child, (*path, key))]
                     for key, child in item.items() if key not in {'proposal_id', 'run_id', 'request_id'}]
            pairs.sort(key=lambda pair: (0, pair[0]) if isinstance(pair[0], str) else (1, stable_key(pair[0])))
            return ['object', pairs]
        if isinstance(item, (tuple, list)):
            return ['array', [encode(child, (*path, index)) for index, child in enumerate(item)]]
        if isinstance(item, (bytes, bytearray, memoryview)):
            return [type(item).__name__, item.hex()]
        if isinstance(item, (set, frozenset)):
            return [type(item).__name__, sorted((encode(child) for child in item), key=stable_key)]
        if isinstance(item, float) and not math.isfinite(item):
            return ['nonfinite', str(item)]
        return ['scalar', item]

    return encode(value)


def _rejection_facts(proposal, current):
    identifiers = set()

    def collect(value):
        if isinstance(value, Mapping):
            identifier = value.get('memory_id')
            if isinstance(identifier, (int, str)):
                identifiers.add(identifier)
            for item in value.values():
                collect(item)
        elif isinstance(value, (tuple, list)):
            for item in value:
                collect(item)

    collect(proposal)
    return {'scope': current.scope_id, 'versions': [
        {'reference': identifier, 'current': memory_ref(current.entries[identifier])
         if identifier in current.entries else None}
        for identifier in sorted(identifiers, key=str)]}


def _bind_rejections(decision, proposal, current, *, references=None, component=()):
    children = tuple(_bind_rejections(child, proposal, current, references=references,
                                     component=(*component, index))
                     for index, child in enumerate(decision.children))
    if decision.decision != 'reject':
        return replace(decision, children=children)
    key = stable_key({'proposal': _rejection_value(proposal, references),
                      'current': _rejection_facts(proposal, current), 'component': component,
                      'reasons': decision.reason_codes, 'rule': RULE_VERSION})
    return replace(decision, decision_id=key, children=children)


def _rejection_references(proposals):
    # Describe graph nodes by semantic content, then include reachable adjacency.
    # Local labels are used only to traverse, never placed in the audit identity.
    by_id = {p['proposal_id']: p for p in proposals}
    content = {label: stable_key(_rejection_value(p)) for label, p in by_id.items()}
    references = {}
    for label in by_id:
        seen, pending, graph = set(), [label], []
        while pending:
            item = pending.pop()
            if item in seen or item not in by_id:
                continue
            seen.add(item)
            graph.append(_rejection_value(by_id[item], content))
            pending.extend(_references(by_id[item]))
        references[label] = stable_key({'root': content[label], 'graph': sorted(graph, key=stable_key)})
    return references


def _bind_rejected_members(decisions, proposals, current, *, references=None):
    bound = [_bind_rejections(d, p, current, references=references) if d.decision == 'reject' else d
             for d, p in zip(decisions, proposals)]
    counts, occurrences = {}, {}
    for decision in bound:
        if decision.decision == 'reject':
            counts[decision.decision_id] = counts.get(decision.decision_id, 0) + 1
    for index, (decision, proposal) in enumerate(zip(bound, proposals)):
        key = decision.decision_id
        if counts.get(key, 0) > 1:
            occurrence = occurrences.get(key, 0)
            occurrences[key] = occurrence + 1
            bound[index] = _bind_rejections(decision, proposal, current, references=references,
                                            component=('occurrence', occurrence))
    return tuple(bound)


def accept(effects, *, versions=(), outcomes=(), proof=None, support_versions=()):
    proof = proof or {'origin': 'deterministic_rule', 'rule_id': 'effect_guard'}
    if support_versions:
        facts = {stable_key(fact): fact for fact in (*proof.get('support_versions', ()), *support_versions)}
        proof = {**proof, 'support_versions': tuple(facts[key] for key in sorted(facts))}
    key = stable_key({'effects': effects, 'versions': [memory_ref(vars(v)) for v in versions],
                      'rule': RULE_VERSION, 'proof': proof})
    return Decision(key, 'accept', ('APPROVED',), tuple(effects), tuple(versions), tuple(outcomes),
                    proof, RULE_VERSION)


@dataclass(frozen=True)
class AdjudicationContext(TrustedContext):
    window: object = None
    inferences: Mapping = field(default_factory=dict)
    support_facts: Mapping = field(default_factory=dict)
    support_versions: Mapping = field(default_factory=dict)
    provisional: Mapping = field(default_factory=dict)

    def __post_init__(self):
        super().__post_init__()
        for key in ('inferences', 'support_facts', 'support_versions', 'provisional'):
            object.__setattr__(self, key, freeze(getattr(self, key)))


@dataclass(frozen=True)
class _GovernedCommand:
    target: Mapping
    operation: str
    event_id: int
    replacement_id: int | None
    _seal: object = field(repr=False, compare=False)
    effect_value: Mapping | None = None


def _governed_command(event, *, target, validation=None, _issuer=None):
    """Internal adapter for an ALREADY authorized existing governed command.

    This is a trusted-code capability issuer, like the support-hook seal. It is
    never called by proposal adjudication and must not be exposed to model/API
    payloads. Existing writer/management authorization remains the caller's job.
    Bind the existing event's actor, authority, object, version and exact effect.
    """
    payload = event.get('payload', {})
    if _issuer is not _COMMAND_ISSUER_SEAL:
        raise PermissionError('TRUSTED_CONTEXT_REQUIRED')
    scope = target.get('knowledge_scope_id')
    if (event.get('knowledge_scope_id') != scope or event.get('scope_meta', {}).get('knowledge_scope_id') != scope
        or not event.get('event_id') or not event.get('request_id')):
        raise PermissionError('TRUSTED_CONTEXT_REQUIRED')
    if (event.get('event_type') == 'retract' and event.get('actor') == 'management'
        and event.get('authority', {}).get('source') == 'management'
        and event.get('aggregate_id') == target.get('memory_id')
        and isinstance(payload.get('reason'), str) and payload['reason'].strip()):
        operation, replacement_id = 'invalidate', None
    elif (event.get('event_type') == 'revise' and event.get('actor') == 'memory_tool'
          and event.get('authority', {}).get('source') == 'validated_evidence'
          and payload.get('supersedes_memory_id') == target.get('memory_id')
          and payload.get('provenance') == 'hard' and payload.get('confidence') is None
          and validation and validation.get('validated') is True and validation.get('provenance') == 'hard'
          and payload.get('evidence_refs') and set(payload['evidence_refs']) == {
              a.get('evidence_id') for a in validation.get('attributions', ())}
          and all(a.get('position') and a.get('content_hash') and a.get('version_id') and a.get('source_id')
                  for a in validation['attributions'])):
        operation, replacement_id = 'replace', event['aggregate_id']
    else:
        raise PermissionError('TRUSTED_CONTEXT_REQUIRED')
    return _GovernedCommand(freeze({**memory_ref(target), 'scope': scope}), operation,
                            event['event_id'], replacement_id, _COMMAND_SEAL)


def guard_effect(effect, target, *, command=None):
    """Common hard guard; association/annotation cannot confer state authority."""
    if target.get('provenance') != 'hard':
        return accept((effect,))
    bound = {**memory_ref(target), 'scope': target.get('knowledge_scope_id')}
    authorized = (isinstance(command, _GovernedCommand) and command._seal is _COMMAND_SEAL
                  and command.target == bound and command.operation == effect.get('operation')
                  and effect.get('aggregate_id') == target.get('memory_id')
                  and command.replacement_id == effect.get('replacement_id')
                  and command.effect_value == effect.get('value'))
    if authorized:
        return accept((effect,), proof={'origin': 'governed_command', 'event_id': command.event_id})
    return reject('HARD_MEMORY_PROTECTED')


def adjudicate_lifecycle(intent, current, *, now):
    """Existing governed retention transition, with current due-time revalidation."""
    from rag_mcp.orchestration.consolidation_pipeline import _TTL_SEAL, TTLIntent

    if not isinstance(intent, TTLIntent) or intent._seal is not _TTL_SEAL:
        return reject('TRUSTED_CONTEXT_REQUIRED')
    if now.tzinfo is None:
        raise ValueError('timezone-aware clock required')
    row = current.entries.get(intent.target_ref.get('memory_id'))
    if row is None or memory_ref(row) != intent.target_ref:
        return reject('TARGET_VERSION_CHANGED')
    if current.scope_id != intent.scope_id or row.get('knowledge_scope_id') != current.scope_id:
        return reject('SCOPE_MISMATCH')
    if (row.get('status') != 'active' or row.get('write_status', 'complete') != 'complete'
        or not row.get('expires_at') or _date(row['expires_at']) > now):
        return reject('TTL_NOT_DUE')
    if intent.retention_stage != {'active': 'compressed', 'compressed': 'archived', 'archived': 'tombstone'}.get(
        row.get('retention_stage')):
        return reject('TTL_TRANSITION_INVALID')
    effect = {'operation': 'lifecycle', 'aggregate_id': row['memory_id'],
              'value': {'retention_stage': intent.retention_stage}}
    command = _GovernedCommand(freeze({**memory_ref(row), 'scope': current.scope_id}), 'lifecycle',
                              row['state_event_id'], None, _COMMAND_SEAL, freeze(effect['value']))
    guarded = guard_effect(effect, row, command=command)
    if guarded.decision == 'reject':
        return guarded
    return accept((effect,), versions=(SourceVersion(**memory_ref(row), observed_at=_date(row['observed_at'])),),
                  proof={'origin': 'deterministic_rule', 'rule_id': 'governed_natural_ttl',
                         'expires_at': row['expires_at']})


def _confidence(value, minimum):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise Rejection('CONFIDENCE_INVALID')
    if value < minimum:
        raise Rejection('CONFIDENCE_BELOW_THRESHOLD')


def _date(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('timezone-aware timestamp required')
    return result


def _current(row, scope, now):
    if row.get('knowledge_scope_id') != scope:
        raise Rejection('SCOPE_MISMATCH')
    if row.get('status') != 'active' or row.get('write_status', 'complete') != 'complete':
        raise Rejection('SOURCE_NOT_ELIGIBLE')
    try:
        if (any(row.get(key) and _date(row[key]) <= now for key in ('expires_at', 'valid_to'))
            or row.get('valid_from') and _date(row['valid_from']) > now):
            raise Rejection('SOURCE_NOT_ELIGIBLE')
    except (ValueError, TypeError):
        raise Rejection('SOURCE_NOT_ELIGIBLE') from None


def _chain(row, current, limit):
    visited = set()
    while row:
        identifier = row.get('memory_id')
        if identifier in visited or len(visited) >= limit or row.get('knowledge_scope_id') != current.scope_id:
            raise Rejection('SUPERSEDE_CHAIN_INVALID')
        visited.add(identifier)
        parent = row.get('supersedes_memory_id')
        if parent is None:
            return
        row = current.entries.get(parent)
        if row is None:
            raise Rejection('SUPERSEDE_CHAIN_INVALID')


def _resolve(reference, current, context, now, config, versions, *, source=False, output=None, check_support=True,
             support_versions=None):
    if reference.get('local') == 'output':
        if output is None:
            raise Rejection('OUTPUT_NOT_APPROVED')
        if check_support:
            _required_support(output, current, context, now, config, versions, support_versions)
        return output
    if 'output_key' in reference:
        result = context.provisional.get(reference['output_key'])
        if source or result is None:
            raise Rejection('OUTPUT_NOT_APPROVED')
        _current(result, current.scope_id, now)
        if check_support:
            _required_support(result, current, context, now, config, versions, support_versions)
        return result
    if 'proposal_ref' in reference:
        raise Rejection('OUTPUT_NOT_APPROVED')
    window = context.window
    allowed = () if window is None else window.input_episode_refs + (() if source else window.reference_refs)
    selected = next((v for v in allowed if v.memory_id == reference.get('memory_id')), None)
    if selected is None:
        raise Rejection('SOURCE_NOT_ELIGIBLE' if source else 'TARGET_NOT_ALLOWED')
    row = current.entries.get(reference.get('memory_id'))
    if row is None:
        raise Rejection('SOURCE_NOT_ELIGIBLE')
    if row.get('knowledge_scope_id') != current.scope_id or window.scope_id != current.scope_id:
        raise Rejection('SCOPE_MISMATCH')
    actual = memory_ref(row)
    if (actual != dict(reference) or actual != memory_ref(vars(selected))
        or max(actual['source_event_id'], actual['state_event_id']) > current.high_water_mark):
        raise Rejection('TARGET_VERSION_CHANGED')
    _current(row, current.scope_id, now)
    if source and row.get('kind') != 'episodic':
        raise Rejection('SOURCE_NOT_ELIGIBLE')
    if source and row.get('provenance') == 'hard':
        _hard_attribution(row, current, context, support_versions)
    _chain(row, current, config.max_chain_depth)
    if check_support:
        _required_support(row, current, context, now, config, versions, support_versions)
    if selected not in versions:
        versions.append(selected)
    return row


def _support(identifier, current, context, support_versions=None):
    fact = context.support_facts.get(identifier)
    if not fact or fact.get('status') != 'published' or fact.get('source_status') != 'published':
        raise Rejection('EVIDENCE_UNAVAILABLE')
    if any(fact.get(key) != current.scope_id for key in ('knowledge_scope_id', 'source_scope_id', 'version_scope_id')):
        raise Rejection('SCOPE_MISMATCH')
    if (fact.get('attributed') is not True or not fact.get('position') or not fact.get('content_hash')
        or not fact.get('source_id') or not fact.get('version_id') or not fact.get('version', 0) >= 1):
        raise Rejection('ATTRIBUTION_FAILED')
    if fact != context.support_versions.get(identifier):
        raise Rejection('TARGET_VERSION_CHANGED')
    captured = {'evidence_id': identifier, **fact}
    if support_versions is not None and captured not in support_versions:
        support_versions.append(captured)
    return captured


def _captured_support(row):
    """Translate permanent descriptors only through their captured attribution."""
    for required in row.get('required_support', ()):
        if 'support_kind' not in required:
            yield required
            continue
        attribution = next((fact for fact in row.get('adjudication', {}).get('evidence_attributions', ())
                            if fact.get('evidence_id') == required.get('support_id')), None)
        if (required.get('support_kind') != 'evidence' or attribution is None
            or str(attribution.get('version_id')) != required.get('version')
            or attribution.get('content_hash') != required.get('content_hash')):
            raise Rejection('DEPENDENCY_SUPPORT_INVALID')
        yield attribution


def _required_support(row, current, context, now, config, versions, support_versions=None):
    nodes, active, heights = set(), set(), {}

    def node(kind, identifier, depth):
        if depth > config.max_chain_depth:
            raise Rejection('DEPENDENCY_SUPPORT_INVALID')
        nodes.add((kind, stable_key(identifier)))
        if len(nodes) > 128:
            raise Rejection('DEPENDENCY_SUPPORT_INVALID')

    def visit(memory, depth):
        identifier = stable_key(memory['memory_id'])
        node('memory', memory['memory_id'], depth)
        if identifier in active:
            raise Rejection('DEPENDENCY_SUPPORT_INVALID')
        if identifier in heights:
            if depth + heights[identifier] - 1 > config.max_chain_depth:
                raise Rejection('DEPENDENCY_SUPPORT_INVALID')
            return heights[identifier]
        active.add(identifier)
        height = 1
        # Root attribution/protection belongs to its source or action gate.
        if depth > 1 and memory.get('provenance') == 'hard':
            for fact in _hard_attribution(memory, current, context, support_versions):
                node('evidence', fact['evidence_id'], depth + 1)
                height = 2
        for required in _captured_support(memory):
            if 'evidence_id' in required:
                fact = _support(required['evidence_id'], current, context, support_versions)
                if (fact['version_id'] != required.get('version_id')
                    or any(required[key] != fact.get(key) for key in (
                        'source_id', 'version', 'position', 'content_hash') if key in required)):
                    raise Rejection('DEPENDENCY_SUPPORT_INVALID')
                node('evidence', fact['evidence_id'], depth + 1)
                height = max(height, 2)
            elif 'memory_id' in required:
                support = current.entries.get(required['memory_id'])
                if (not support or memory_ref(support) != {k: required.get(k) for k in VERSION_FIELDS}
                    or max(support['source_event_id'], support['state_event_id']) > current.high_water_mark):
                    raise Rejection('DEPENDENCY_SUPPORT_INVALID')
                _current(support, current.scope_id, now)
                version = SourceVersion(**memory_ref(support), observed_at=_date(support['observed_at']))
                if version not in versions:
                    versions.append(version)
                height = max(height, 1 + visit(support, depth + 1))
            else:
                raise Rejection('DEPENDENCY_SUPPORT_INVALID')
        active.remove(identifier)
        heights[identifier] = height
        return height

    try:
        visit(row, 1)
    except (Rejection, KeyError, TypeError, ValueError):
        raise Rejection('DEPENDENCY_SUPPORT_INVALID') from None


def equivalent(left, right):
    """Exact metadata and CRLF/LF representation equality; raw hashes stay intact."""
    keys = ('knowledge_scope_id', 'kind', 'provenance', 'evidence_refs', 'submission_meta', 'required_support', 'title', 'tags',
            'valid_from', 'valid_to', 'expires_at', 'supersedes_memory_id', 'confidence', 'inference_meta',
            'authority', 'provenance_meta')
    return (all(left.get(key) == right.get(key) for key in keys)
            and left.get('content_text', '').replace('\r\n', '\n') == right.get('content_text', '').replace('\r\n', '\n')
            and all(r.get('content_hash') == sha256(r.get('content_text', '').encode()).hexdigest()
                    for r in (left, right)))


def _hard_attribution(row, current, context, support_versions=None):
    metadata = row.get('provenance_meta', {})
    attributions = metadata.get('attributions', ())
    if (row.get('confidence') is not None or not row.get('evidence_refs')
        or metadata.get('validated') is not True
        or {a.get('evidence_id') for a in attributions} != set(row['evidence_refs'])):
        raise Rejection('ATTRIBUTION_FAILED')
    facts = []
    for attribution in attributions:
        fact = _support(attribution['evidence_id'], current, context, support_versions)
        if any(attribution.get(key) != fact.get(key) for key in (
            'source_id', 'version_id', 'version', 'position', 'content_hash')):
            raise Rejection('ATTRIBUTION_FAILED')
        facts.append(fact)
    return tuple(facts)


def _correction(target, correcting, current, context, support_versions=None):
    if correcting is not None:
        if (correcting.get('supersedes_memory_id') == target['memory_id']
            and correcting.get('provenance') == 'hard' and correcting.get('confidence') is None
            and correcting.get('authority', {}).get('source') == 'validated_evidence'
            and correcting.get('provenance_meta', {}).get('validated') is True
            and correcting.get('evidence_refs')):
            _hard_attribution(correcting, current, context, support_versions)
            return {'rule_id': 'authoritative_correction', 'replacement_id': correcting['memory_id']}
    else:
        for required in _captured_support(target):
            fact = context.support_facts.get(required.get('evidence_id'))
            if (fact and fact.get('status') == 'withdrawn'
                and fact.get('knowledge_scope_id') == current.scope_id
                and fact.get('source_scope_id') == current.scope_id and fact.get('version_scope_id') == current.scope_id
                and fact.get('version_id') == required.get('version_id')
                and context.support_versions.get(required.get('evidence_id')) == fact):
                if support_versions is not None:
                    support_versions.append({'evidence_id': required['evidence_id'], **fact})
                return {'rule_id': 'support_withdrawal', 'support': required, 'replacement_id': None}
    raise Rejection('CONTRADICTION_NOT_PROVEN')


def _safe(value):
    clean = redact_submission(thaw(value))
    if clean != thaw(value) or detect_submission({'content': json.dumps(clean, ensure_ascii=False)}).status != 'active':
        raise Rejection('GENERATED_CONTENT_UNSAFE')


def _source_versions(p, current, context, now, config):
    refs = p.get('source_refs', ())
    if not refs or len(refs) > config.max_sources_per_proposal:
        raise Rejection('SOURCE_NOT_ELIGIBLE')
    versions, support_versions = [], []
    for reference in refs:
        _resolve(reference, current, context, now, config, versions, source=True, support_versions=support_versions)
    return versions, support_versions


def _core(p, current, policy, quota, context, now):
    config = policy.consolidation
    if not policy.consolidation_enabled or config is None:
        raise Rejection('POLICY_CHANGED')
    if any(k in p for k in ('origin', 'proof', 'rule_id', 'provenance', 'permission', 'authority', 'approved_effects')):
        raise Rejection('AUTHORITY_FIELDS_FORBIDDEN')
    _confidence(p.get('confidence'), config.min_confidence)
    versions, support_versions = _source_versions(p, current, context, now, config)
    _safe({k: p.get(k) for k in ('content', 'title', 'justification',
                               'equivalence_basis', 'contradiction_basis')})
    refs = p.get('source_refs', ())
    action = p.get('action')
    proof = {'origin': 'llm_self', 'confidence': p['confidence'], 'threshold': config.min_confidence,
             'scope_id': current.scope_id, 'rule_id': action}
    if action in CREATES:
        info = context.inferences.get(p.get('proposal_id'), {})
        meta = info.get('inference_meta', {})
        if not {'source', 'confidence', 'model_version', 'time', 'supporting_evidence'} <= meta.keys():
            raise Rejection('INFERENCE_META_INCOMPLETE')
        if any(not isinstance(meta[k], str) or not meta[k].strip() for k in ('source', 'model_version', 'time')):
            raise Rejection('INFERENCE_META_INCOMPLETE')
        try:
            _date(meta['time'])
        except (ValueError, TypeError):
            raise Rejection('INFERENCE_META_INCOMPLETE') from None
        if meta['confidence'] != p['confidence'] or isinstance(meta['confidence'], bool):
            raise Rejection('CONFIDENCE_INVALID')
        expected_lineage = [{k: r[k] for k in ('memory_id', 'source_event_id', 'content_hash')} for r in refs]
        if (thaw(info.get('source_lineage')) != expected_lineage
            or list(meta['supporting_evidence']) != [f"memory:{r['memory_id']}" for r in refs]):
            raise Rejection('SOURCE_CHAIN_INCOMPLETE')
        if 'fact_anchors' not in info or set(info['fact_anchors']) != set(p.get('evidence_refs', ())):
            raise Rejection('DEPENDENCY_SUPPORT_INVALID')
        support = tuple(_support(identifier, current, context, support_versions) for identifier in sorted(info['fact_anchors']))
        if quota.get('count') is None or quota.get('limit') is None or quota['count'] >= quota['limit']:
            raise Rejection('QUOTA_EXCEEDED')
        kind = 'semantic' if action == 'extract_fact' else 'procedural'
        if (p.get('kind') != kind or not isinstance(p.get('content'), str) or not p['content'].strip()
            or len(p['content']) > 4000):
            raise Rejection('GENERATED_CONTENT_UNSAFE')
        value = {'kind': kind, 'provenance': 'distilled', 'confidence': p['confidence'],
                 'content_text': p['content'], 'content_hash': sha256(p['content'].encode()).hexdigest(),
                 'title': p.get('title'), 'inference_meta': {**meta, 'origin': 'llm_self'},
                 'source_lineage': expected_lineage, 'evidence_refs': sorted(info['fact_anchors']),
                 'required_support': support, 'knowledge_scope_id': current.scope_id}
        output_key = stable_key({'scope': current.scope_id, 'action': action, 'sources': refs, 'value': value,
                                 'rule': RULE_VERSION})
        effects = ({'operation': 'create', 'aggregate_id': {'output_key': output_key}, 'value': value},)
    elif action == 'merge_duplicate':
        keeper = _resolve(p['survivor_ref'], current, context, now, config, versions, support_versions=support_versions)
        duplicates = [_resolve(r, current, context, now, config, versions, support_versions=support_versions)
                      for r in p['duplicate_refs']]
        if not duplicates or any(r['memory_id'] == keeper['memory_id'] for r in duplicates):
            raise Rejection('EQUIVALENCE_NOT_PROVEN')
        effects = []
        for duplicate in duplicates:
            effect = {'operation': 'merge', 'aggregate_id': duplicate['memory_id'],
                      'value': {'keeper_id': keeper['memory_id'], 'merge_lineage': refs}}
            if guard_effect(effect, duplicate).decision == 'reject':
                raise Rejection('HARD_MEMORY_PROTECTED')
            if not equivalent(keeper, duplicate):
                raise Rejection('EQUIVALENCE_NOT_PROVEN')
            effects.append(effect)
        proof.update(origin='deterministic_rule', confidence=1., rule_id='exact_equivalence')
    elif action == 'invalidate_contradiction':
        target = _resolve(p['target_ref'], current, context, now, config, versions, check_support=False,
                          support_versions=support_versions)
        effect = {'operation': 'invalidate', 'aggregate_id': target['memory_id']}
        if guard_effect(effect, target).decision == 'reject':
            raise Rejection('HARD_MEMORY_PROTECTED')
        correcting = _resolve(p['correcting_ref'], current, context, now, config, versions,
                              support_versions=support_versions) if p.get('correcting_ref') else None
        correction = _correction(target, correcting, current, context, support_versions)
        proof.update(origin='deterministic_rule', confidence=1., **correction)
        effects = ({**effect, 'value': {'replacement_id': correction['replacement_id']}},)
    else:
        raise Rejection('ACTION_NOT_ALLOWED')
    completed_refs = refs
    if action == 'merge_duplicate':
        completed_refs = [r for r in refs if r['memory_id'] != keeper['memory_id']
                          and equivalent(current.entries[r['memory_id']], keeper)]
    elif action == 'invalidate_contradiction':
        completed_refs = [r for r in refs if r['memory_id'] == target['memory_id']]
    outcomes = tuple({'source_version': r, 'outcome': 'consumed_on_complete'} for r in completed_refs)
    return accept(effects, versions=versions, outcomes=outcomes, proof=proof, support_versions=support_versions)


def _endpoint_ref(row):
    return {'output_key': row['output_key']} if row.get('output_key') else memory_ref(row)


def _attachments(p, core, current, policy, vocabulary, context, now):
    config = policy.consolidation
    created = next((e for e in core.approved_effects if e['operation'] == 'create'), None)
    output = ({**created['value'], 'memory_id': created['aggregate_id'],
               'output_key': created['aggregate_id']['output_key']} if created else None)
    for index, link in enumerate(p.get('link_suggestions', ())):
        try:
            if config is None or not policy.consolidation_enabled:
                raise Rejection('POLICY_CHANGED')
            if index >= config.max_links_per_proposal:
                raise Rejection('LINK_BUDGET_EXCEEDED')
            if set(link) != {'from_ref', 'to_ref', 'relation_type', 'confidence', 'description'}:
                raise Rejection('AUTHORITY_FIELDS_FORBIDDEN')
            versions, support_versions = _source_versions(p, current, context, now, config)
            left = _resolve(link['from_ref'], current, context, now, config, versions, output=output,
                            support_versions=support_versions)
            right = _resolve(link['to_ref'], current, context, now, config, versions, output=output,
                             support_versions=support_versions)
            relation = next((r for r in vocabulary if r['key'] == link['relation_type']), None)
            if relation is None:
                raise Rejection('LINK_TYPE_NOT_ALLOWED')
            if left.get('kind') not in relation.get('from_kinds', ()) or right.get('kind') not in relation.get('to_kinds', ()):
                raise Rejection('LINK_KIND_NOT_ALLOWED')
            if left['memory_id'] == right['memory_id'] or relation.get('recall_direction') not in ('both', 'from_to_to', 'to_to_from'):
                raise Rejection('LINK_DIRECTION_INVALID')
            _confidence(link.get('confidence'), config.min_confidence)
            if (relation['category'] == 'live_dependency'
                and not any(r.get('memory_id') == right['memory_id'] for r in left.get('required_support', ()))):
                raise Rejection('DEPENDENCY_SUPPORT_INVALID')
            _safe(link['description'])
            value = {**link, 'from_ref': _endpoint_ref(left), 'to_ref': _endpoint_ref(right),
                     'origin': 'llm_proposed', 'category': relation['category'],
                     'propagation': relation['propagation']}
            yield accept(({'operation': 'derive', 'aggregate_id': left['memory_id'], 'value': {'links': [value]}},),
                         versions=versions, support_versions=support_versions,
                         proof={'origin': 'llm_self', 'confidence': link['confidence'], 'rule_id': 'link'})
        except Rejection as error:
            yield reject(str(error))
    if 'context' in p:
        try:
            value = p['context']
            if output is None:
                raise Rejection('OUTPUT_NOT_APPROVED')
            if set(value) != {'context_digest', 'keywords'}:
                raise Rejection('CONTEXT_FIELDS_INVALID')
            if (not isinstance(value['context_digest'], str) or not value['context_digest']
                or len(value['context_digest']) > config.max_context_chars or len(value['keywords']) > config.max_keywords
                or any(not isinstance(k, str) or not k or len(k) > 64 for k in value['keywords'])):
                raise Rejection('CONTEXT_BUDGET_EXCEEDED')
            _safe(value)
            yield accept(({'operation': 'derive', 'aggregate_id': output['memory_id'], 'value': {'context': value}},),
                         proof={'origin': 'llm_self', 'rule_id': 'context'})
        except Rejection as error:
            yield reject(str(error))
    if output is not None:
        if (output['kind'] == 'semantic' and output['evidence_refs']
            and output['confidence'] >= config.candidate_min_confidence):
            yield accept(({'operation': 'derive', 'aggregate_id': output['memory_id'],
                           'value': {'promotion_candidate': True}},),
                         proof={'origin': 'deterministic_rule', 'rule_id': 'candidate_eligibility'})
        else:
            yield reject('CANDIDATE_NOT_ELIGIBLE')


def adjudicate(proposal, current, policy, vocabulary, quota, context, now):
    """Adjudicate core and attachments independently; expose approved values only."""
    if now.tzinfo is None:
        raise ValueError('timezone-aware clock required')
    if not isinstance(context, AdjudicationContext):
        return _bind_rejections(reject('TRUSTED_CONTEXT_REQUIRED'), proposal, current)
    if context.execution_context != 'distiller_window':
        return _bind_rejections(_maintenance(proposal, current, context, now), proposal, current)
    try:
        core = _core(proposal, current, policy, quota, context, now)
    except Rejection as error:
        core = reject(str(error))
    children = (core, *_attachments(proposal, core, current, policy, vocabulary, context, now))
    effects = tuple(e for child in children for e in child.approved_effects)
    if not effects:
        return _bind_rejections(replace(core, children=children), proposal, current)
    versions = tuple(dict.fromkeys(v for child in children for v in child.expected_versions))
    support_versions = tuple(fact for child in children for fact in child.proof.get('support_versions', ()))
    decision = accept(effects, versions=versions, outcomes=core.source_outcomes, proof=core.proof,
                      support_versions=support_versions)
    return _bind_rejections(replace(decision, children=children), proposal, current)


def _maintenance(proposal, current, context, now):
    if not context.trusted_support_hook:
        return reject('TRUSTED_CONTEXT_REQUIRED')
    if (proposal.get('action') != 'invalidate_contradiction' or proposal.get('source_refs')
        or proposal.get('correcting_ref') is not None
        or any(k in proposal for k in ('link_suggestions', 'context', 'candidate', 'promotion_candidate'))):
        return reject('MAINTENANCE_EFFECT_FORBIDDEN')
    trigger = context.propagation_trigger
    reference = proposal.get('target_ref', {})
    if trigger.get('target_ref') != reference:
        return reject('CONTRADICTION_NOT_PROVEN')
    row = current.entries.get(reference.get('memory_id'))
    if row is None or memory_ref(row) != reference:
        return reject('TARGET_VERSION_CHANGED')
    try:
        _current(row, current.scope_id, now)
        proof = _correction(row, None, current, context)
        if (proof['support'].get('evidence_id') != trigger.get('evidence_id')
            or proof['support'].get('version_id') != trigger.get('version_id')):
            raise Rejection('CONTRADICTION_NOT_PROVEN')
        effect = {'operation': 'invalidate', 'aggregate_id': row['memory_id'],
                  'value': {'replacement_id': None}}
        if guard_effect(effect, row).decision == 'reject':
            raise Rejection('HARD_MEMORY_PROTECTED')
        return accept((effect,), versions=(SourceVersion(**memory_ref(row), observed_at=_date(row['observed_at'])),),
                      proof={**proof, 'origin': 'deterministic_rule', 'confidence': 1.,
                             'historical_source_refs': context.historical_source_refs})
    except Rejection as error:
        return reject(str(error))


@dataclass(frozen=True)
class AtomicGroup:
    group_key: str
    decision_ids: tuple
    event_plan: tuple
    source_outcomes: tuple

    def __post_init__(self):
        for name in ('decision_ids', 'event_plan', 'source_outcomes'):
            object.__setattr__(self, name, freeze(getattr(self, name)))


@dataclass(frozen=True)
class BatchDecision:
    decisions: tuple
    groups: tuple


def _endpoint_paths(proposal):
    """Only contract-defined targets and link endpoints can reference batch outputs."""
    action = proposal.get('action')
    if action == 'merge_duplicate':
        yield ('survivor_ref',)
        duplicates = proposal.get('duplicate_refs', ())
        if isinstance(duplicates, (tuple, list)):
            for index in range(len(duplicates)):
                yield ('duplicate_refs', index)
    elif action == 'invalidate_contradiction':
        yield ('target_ref',)
        yield ('correcting_ref',)
    links = proposal.get('link_suggestions', ())
    if isinstance(links, (tuple, list)):
        for index in range(len(links)):
            yield ('link_suggestions', index, 'from_ref')
            yield ('link_suggestions', index, 'to_ref')


def _references(proposal):
    for path in _endpoint_paths(proposal):
        value = proposal
        for key in path:
            value = value[key]
        if isinstance(value, Mapping) and set(value) == {'proposal_ref'} and isinstance(value['proposal_ref'], str):
            yield value['proposal_ref']


def _resolve_outputs(proposal, outputs):
    resolved = thaw(proposal)
    for path in _endpoint_paths(proposal):
        parent = resolved
        for key in path[:-1]:
            parent = parent[key]
        value = parent[path[-1]]
        if isinstance(value, Mapping) and set(value) == {'proposal_ref'}:
            parent[path[-1]] = {'output_key': outputs[value['proposal_ref']]}
    return resolved


def _proposal_order(value):
    try:
        return stable_key(value)
    except (TypeError, ValueError):
        # Malformed numeric claims still reach the ordinary confidence decision.
        return stable_key({'action': value.get('action'), 'sources': value.get('source_refs')})


def lower_events(decisions):
    """Exact commit contract: one create/lifecycle effect per aggregate event;
    one derive per aggregate per proposal, coalescing its approved attachments.
    Created-memory annotations use a subsequent derive, never hidden create data.
    Input decisions are in stable topological order. No writer may recount them.
    """
    events = []
    for decision in decisions:
        derives = {}
        for effect in decision.approved_effects:
            if effect['operation'] != 'derive':
                event = thaw(effect)
                event['proposal_key'] = decision.decision_id
                events.append(event)
                continue
            key = stable_key(effect['aggregate_id'])
            aggregate = derives.setdefault(key, {'operation': 'derive', 'aggregate_id': effect['aggregate_id'],
                                                 'proposal_key': decision.decision_id, 'value': {}})
            for name, value in effect['value'].items():
                if name == 'links':
                    aggregate['value'].setdefault(name, []).extend(value)
                else:
                    aggregate['value'][name] = value
        events.extend(derives[k] for k in sorted(derives))
    count = len(events)
    return freeze([{**event, 'effect_index': index, 'effect_count': count} for index, event in enumerate(events)])


def _model_structure_valid(proposal):
    """Reject malformed containers before they can disrupt trusted batch work."""
    def sequence(value):
        return isinstance(value, (tuple, list))

    def reference(value, *, source=False, local=False):
        if not isinstance(value, Mapping):
            return False
        if not source and set(value) == {'proposal_ref'}:
            return isinstance(value['proposal_ref'], str) and re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value['proposal_ref']) is not None
        if local and set(value) == {'local'}:
            return value['local'] == 'output'
        return (set(VERSION_FIELDS) == value.keys()
                and all(isinstance(value[key], int) and not isinstance(value[key], bool)
                        for key in VERSION_FIELDS[:3]) and isinstance(value['content_hash'], str))

    if not sequence(proposal.get('source_refs')) or not all(reference(ref, source=True) for ref in proposal['source_refs']):
        return False
    if not sequence(proposal.get('evidence_refs')) or not all(isinstance(ref, str) for ref in proposal['evidence_refs']):
        return False
    action = proposal.get('action')
    if not isinstance(action, str):
        return False
    common = {'proposal_id', 'action', 'source_refs', 'confidence', 'justification', 'evidence_refs',
              'link_suggestions', 'context', 'run_id', 'request_id'}
    fields = {'extract_fact': {'kind', 'content', 'title'}, 'distill_procedure': {'kind', 'content', 'title'},
              'merge_duplicate': {'survivor_ref', 'duplicate_refs', 'equivalence_basis'},
              'invalidate_contradiction': {'target_ref', 'correcting_ref', 'contradiction_basis'}}
    if not proposal.keys() <= common | fields.get(action, {'kind', 'content', 'title'}):
        return False
    if any(not isinstance(proposal[key], str) for key in (
        'title', 'justification', 'equivalence_basis', 'contradiction_basis', 'run_id', 'request_id') if key in proposal):
        return False
    if isinstance(proposal.get('confidence'), (Mapping, tuple, list)):
        return False
    if action in CREATES and not all(isinstance(proposal.get(key), str) for key in ('kind', 'content')):
        return False
    if action == 'merge_duplicate' and (
        not reference(proposal.get('survivor_ref')) or not sequence(proposal.get('duplicate_refs'))
        or not all(reference(ref) for ref in proposal['duplicate_refs'])):
        return False
    if action == 'invalidate_contradiction' and (
        not reference(proposal.get('target_ref')) or 'correcting_ref' not in proposal
        or proposal['correcting_ref'] is not None and not reference(proposal['correcting_ref'])):
        return False
    links = proposal.get('link_suggestions', ())
    if not sequence(links) or any(not isinstance(link, Mapping)
        or {'from_ref', 'to_ref', 'relation_type', 'confidence', 'description'} != link.keys()
        or not reference(link['from_ref'], local=True) or not reference(link['to_ref'], local=True)
        or not isinstance(link['relation_type'], str) or not isinstance(link['description'], str)
        or isinstance(link['confidence'], (Mapping, tuple, list)) for link in links):
        return False
    if 'context' in proposal:
        context = proposal['context']
        if (not isinstance(context, Mapping) or set(context) != {'context_digest', 'keywords'}
            or not isinstance(context.get('context_digest'), str) or not sequence(context.get('keywords'))
            or not all(isinstance(keyword, str) for keyword in context['keywords'])):
            return False
    return True


def adjudicate_batch(batch, current, policy, vocabulary, quota, context, now):
    models, rules = tuple(batch.proposals), tuple(batch.deterministic_proposals)
    model_fault = None
    if any(not isinstance(p, Mapping) for p in models):
        model_fault = 'PROPOSAL_INVALID'
    elif any(not isinstance(p.get('proposal_id'), str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', p['proposal_id'])
             for p in models):
        model_fault = 'PROPOSAL_ID_INVALID'
    else:
        model_ids = [p['proposal_id'] for p in models]
        if len(set(model_ids)) != len(model_ids) or set(model_ids) & {p['proposal_id'] for p in rules}:
            model_fault = 'PROPOSAL_ID_DUPLICATE'
        if model_fault is None and any(not _model_structure_valid(p) for p in models):
            model_fault = 'PROPOSAL_INVALID'
    if model_fault:
        trusted = adjudicate_batch(replace(batch, proposals=()), current, policy, vocabulary, quota, context, now)
        return BatchDecision(trusted.decisions + _bind_rejected_members(
            tuple(reject(model_fault) for _ in models), models, current), trusted.groups)
    proposals = tuple(batch.deterministic_proposals) + tuple(batch.proposals)
    labels = [p['proposal_id'] for p in proposals]
    if len(set(labels)) != len(labels):
        return BatchDecision(_bind_rejected_members(tuple(reject('PROPOSAL_ID_DUPLICATE') for _ in proposals),
                                                    proposals, current), ())
    by_id = dict(zip(labels, proposals))
    dependencies = {label: set(_references(p)) for label, p in by_id.items()}
    rule_ids = {p['proposal_id'] for p in rules}
    model_ids = {p['proposal_id'] for p in models}
    decisions, outputs, provisional, order = {}, {}, {}, []
    for label, deps in dependencies.items():
        if label in deps:
            decisions[label] = reject('PROPOSAL_REF_SELF')
        elif deps - (rule_ids if label in rule_ids else model_ids):
            decisions[label] = reject('PROPOSAL_REF_UNKNOWN')
    pending = set(labels) - decisions.keys()
    while pending:
        ready = [label for label in pending if not (dependencies[label] & pending)]
        if not ready:
            for label in pending:
                decisions[label] = reject('PROPOSAL_REF_CYCLE')
            break
        # Labels are only a final tie-breaker for identical semantic proposals.
        ready.sort(key=lambda label: (_proposal_order({k: v for k, v in _resolve_outputs(
            by_id[label], {d: outputs.get(d, 'rejected') for d in dependencies[label]}).items()
            if k != 'proposal_id'}), label))
        for label in ready:
            pending.remove(label)
            order.append(label)
            if any(dep not in outputs for dep in dependencies[label]):
                decisions[label] = reject('OUTPUT_NOT_APPROVED')
                continue
            resolved = _resolve_outputs(by_id[label], outputs)
            decision = adjudicate(resolved, current, policy, vocabulary, quota,
                                  replace(context, provisional=provisional), now)
            decisions[label] = decision
            creation = next((e for e in decision.approved_effects if e['operation'] == 'create'), None)
            if creation:
                key = creation['aggregate_id']['output_key']
                if key in provisional:
                    decisions[label] = reject('OUTPUT_DUPLICATE', key=stable_key({'duplicate': key}))
                    continue
                outputs[label] = key
                provisional[key] = {**creation['value'], 'memory_id': creation['aggregate_id'], 'output_key': key,
                                    'status': 'active', 'write_status': 'complete'}
    # Connectivity is computed from the original batch, including rejected work.
    neighbors = {label: set(dependencies[label]) & by_id.keys() for label in labels}
    sources = {label: {stable_key(r) for r in p.get('source_refs', ())} for label, p in by_id.items()}
    for left in labels:
        for right in labels:
            if left != right and (sources[left] & sources[right] or left in neighbors[right]):
                neighbors[left].add(right)
                neighbors[right].add(left)
    components, unseen = [], set(labels)
    while unseen:
        root = min(unseen)
        group, frontier = set(), {root}
        while frontier:
            item = frontier.pop()
            if item not in group:
                group.add(item)
                frontier.update(neighbors[item] - group)
        unseen -= group
        components.append(group)
    components.sort(key=lambda group: sorted(decisions[label].decision_id for label in group))
    reserved, groups = 0, []
    for component in components:
        members = [label for label in order if label in component and decisions[label].decision == 'accept']
        if not members:
            continue
        planned = lower_events([decisions[label] for label in members])
        creates = sum(e['operation'] == 'create' for e in planned)
        reason = None
        mutations = {}
        for event in planned:
            if event['operation'] != 'derive':
                mutations.setdefault(stable_key(event['aggregate_id']), []).append(event['operation'])
        if any(len(operations) > 1 for operations in mutations.values()):
            reason = 'EFFECT_CONFLICT'
        if len(planned) > min(128, policy.consolidation.max_events_per_group):
            reason = 'GROUP_BUDGET_EXCEEDED'
        elif quota['count'] + reserved + creates > quota['limit']:
            reason = 'QUOTA_EXCEEDED'
        if reason:
            for label in component:
                decisions[label] = reject(reason, key=decisions[label].decision_id)
            continue
        reserved += creates
        ids = tuple(decisions[label].decision_id for label in members)
        outcomes = tuple(o for label in members for o in decisions[label].source_outcomes)
        groups.append(AtomicGroup(stable_key({'scope': current.scope_id,
                                              'versions': [decisions[label].expected_versions for label in members],
                                              'plan': planned, 'rule': RULE_VERSION}),
                                  ids, planned, outcomes))
    references = _rejection_references(proposals)
    return BatchDecision(_bind_rejected_members(tuple(decisions[label] for label in labels), proposals,
                                                current, references=references), tuple(groups))
