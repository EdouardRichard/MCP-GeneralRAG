"""Positive trusted-fact fixtures shared by the Phase 2 behavior matrices."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from rag_mcp.config.domain_profiles import validate_memory_link_vocabulary
from rag_mcp.orchestration.consolidation_pipeline import (
    CurrentSnapshot,
    SourceVersion,
    WindowSnapshot,
)
from rag_mcp.services.consolidation_adjudicator import AdjudicationContext, adjudicate
from rag_mcp.services.memory_policy import MemoryPolicy

NOW = datetime(2026, 10, 6, tzinfo=UTC)
POLICY = MemoryPolicy(consolidation_enabled=True, consolidation={})
VOCAB = tuple(validate_memory_link_vocabulary([
    {'key': 'related', 'category': 'association', 'recall_direction': 'both', 'propagation': 'none',
     'from_kinds': ['episodic', 'semantic', 'procedural'], 'to_kinds': ['episodic', 'semantic', 'procedural'],
     'allow_self': False, 'description': 'Related memories'},
    {'key': 'requires', 'category': 'live_dependency', 'recall_direction': 'from_to_to',
     'propagation': 'to_to_from', 'from_kinds': ['episodic', 'semantic', 'procedural'],
     'to_kinds': ['episodic', 'semantic', 'procedural'], 'allow_self': False, 'description': 'Required support'},
]))


def row(identifier, **changes):
    value = {'memory_id': identifier, 'knowledge_scope_id': 1, 'kind': 'episodic',
             'provenance': 'soft', 'confidence': .4, 'status': 'active', 'write_status': 'complete',
             'content_text': 'same fact', 'content_hash': sha256(b'same fact').hexdigest(),
             'source_event_id': identifier, 'state_event_id': identifier,
             'observed_at': (NOW - timedelta(days=1)).isoformat(), 'expires_at': None,
             'valid_from': (NOW - timedelta(days=1)).isoformat(), 'valid_to': None,
             'supersedes_memory_id': None, 'evidence_refs': [], 'required_support': [],
             'submission_meta': {'kind': 'episodic', 'tags': []}, 'retention_stage': 'active'}
    value.update(changes)
    return value


def ref(entry):
    return {key: entry[key] for key in ('memory_id', 'source_event_id', 'state_event_id', 'content_hash')}


def version(entry):
    return SourceVersion(**ref(entry), observed_at=datetime.fromisoformat(entry['observed_at']))


def proposal(identifier='p0', source=None, **changes):
    source = source or row(1)
    value = {'proposal_id': identifier, 'action': 'extract_fact', 'source_refs': [ref(source)],
             'confidence': .8, 'justification': 'observed fact', 'evidence_refs': [],
             'kind': 'semantic', 'content': 'a conclusion'}
    value.update(changes)
    if value['action'] in ('merge_duplicate', 'invalidate_contradiction'):
        value.pop('kind', None)
        value.pop('content', None)
    return value


def facts(p):
    return {'inference_meta': {'source': 'distiller', 'confidence': p['confidence'], 'model_version': 'test-model',
                              'time': NOW.isoformat(),
                              'supporting_evidence': [f"memory:{r['memory_id']}" for r in p['source_refs']]},
            'source_lineage': [{k: r[k] for k in ('memory_id', 'source_event_id', 'content_hash')}
                               for r in p['source_refs']], 'fact_anchors': list(p['evidence_refs'])}


def setup(*proposals, entries=None, sources=None, targets=None, quota_count=0, support=None):
    entries = entries if entries is not None else {i: row(i) for i in (1, 2, 3)}
    current = CurrentSnapshot(1, 10000, entries, {}, quota_count=quota_count)
    source_ids = sources if sources is not None else [i for i, r in entries.items() if r['kind'] == 'episodic']
    target_ids = targets if targets is not None else list(entries)
    window = WindowSnapshot(1, NOW - timedelta(days=2), NOW, NOW, 10000,
                            tuple(version(entries[i]) for i in source_ids),
                            tuple(version(entries[i]) for i in target_ids if i not in source_ids))
    support = support or {}
    context = AdjudicationContext(window=window, inferences={p['proposal_id']: facts(p) for p in proposals},
                                  support_facts=support,
                                  support_versions=support)
    return current, context


def decide(p, current=None, context=None, *, policy=POLICY, quota=None, vocabulary=VOCAB):
    if current is None:
        current, context = setup(p)
    return adjudicate(p, current, policy, vocabulary,
                      quota if quota is not None else {'count': current.quota_count, 'limit': 5000}, context, NOW)


def rejected(decision, reason):
    assert decision.decision == 'reject'
    assert reason in decision.reason_codes
    assert decision.approved_effects == ()
    assert decision.source_outcomes == ()


def support_fact(**changes):
    value = {'knowledge_scope_id': 1, 'source_scope_id': 1, 'version_scope_id': 1,
             'status': 'published', 'source_status': 'published', 'version_id': 9, 'source_id': 8,
             'version': 1, 'position': 'section/1', 'content_hash': 'a' * 64, 'attributed': True}
    value.update(changes)
    return value


def changed(current, identifier, **changes):
    return replace(current, entries={**current.entries, identifier: {**current.entries[identifier], **changes}})
