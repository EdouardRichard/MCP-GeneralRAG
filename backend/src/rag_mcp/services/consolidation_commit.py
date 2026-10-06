"""Trusted lowering and fenced publication of pure consolidation approvals."""
import json
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from rag_mcp.models.chunk import Chunk
from rag_mcp.models.knowledge_source import KnowledgeSource
from rag_mcp.models.knowledge_version import KnowledgeVersion
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.orchestration.consolidation_pipeline import CommitOutcome, CurrentSnapshot, ProposalBatch, thaw
from rag_mcp.services.consolidation_adjudicator import AdjudicationContext, adjudicate_batch, stable_key
from rag_mcp.services.consolidation_runtime import ConsolidationRuntimeError
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_projection_store import ProjectionFailure
from rag_mcp.services.memory_reducer import reduce_events
from rag_mcp.services.memory_validators import canonical_distilled
from rag_mcp.utils.snowflake import generate_id


async def locked_approval(runtime, token, batch, context):
    policy, _profile = await runtime._validate_policy(token.scope_id, context)
    await runtime.session.execute(select(MemoryEntry).where(MemoryEntry.knowledge_scope_id == token.scope_id)
                                  .order_by(MemoryEntry.memory_id).with_for_update(read=True))
    current = await runtime.read_snapshot(token.scope_id)
    history = await MemoryEventStore(runtime.session).replay(token.scope_id)
    later = [e for e in history if e['event_id'] > current.high_water_mark and not (
        e['event_type'] == 'consolidate' and e['payload'].get('payload_version') == 2)]
    if later:
        baseline = [e for e in history if e['event_id'] <= current.high_water_mark]
        state = reduce_events([*baseline, *later])
        current = CurrentSnapshot(token.scope_id, max(e['event_id'] for e in history), state['entries'],
            state['consolidation_state'], current.vocabulary,
            sum(r['status'] == 'active' for r in state['entries'].values()))
    identifiers = set(context.support_versions)
    for proposal in (*batch.deterministic_proposals, *batch.proposals):
        identifiers.update(proposal.get('evidence_refs', ()))
    for entry in current.entries.values():
        identifiers.update(entry.get('evidence_refs', ()))
    facts = await read_evidence(runtime.session, identifiers, locked=True)
    now = await runtime._clock()
    checked_context = replace(context, support_facts=facts)
    checked = adjudicate_batch(batch, current, policy, current.vocabulary,
        {'count': current.quota_count, 'limit': policy.per_scope_memory_quota}, checked_context, now)
    return checked, current, policy, checked_context, now


async def read_evidence(session, identifiers, *, locked=False):
    facts = {}
    for identifier in sorted(identifiers, key=str):
        statement = select(Chunk, KnowledgeVersion, KnowledgeSource)
        statement = (statement
            .join(KnowledgeVersion, Chunk.version_id == KnowledgeVersion.version_id)
            .join(KnowledgeSource, Chunk.source_id == KnowledgeSource.source_id)
            .where(Chunk.chunk_id == int(identifier)).execution_options(populate_existing=True))
        if locked:
            statement = statement.with_for_update(read=True)
        row = (await session.execute(statement)).first()
        if row:
            chunk, version, source = row
            facts[identifier] = {'knowledge_scope_id': chunk.knowledge_scope_id,
                'source_scope_id': source.knowledge_scope_id, 'version_scope_id': version.knowledge_scope_id,
                'status': version.status, 'source_status': source.status, 'version_id': version.version_id,
                'source_id': source.source_id, 'version': version.version_number, 'position': chunk.position_path,
                'content_hash': sha256(chunk.content_text.encode()).hexdigest(),
                'attributed': bool(chunk.content_text.strip() and chunk.position_path)}
    return facts


def _references(value, allocated):
    if isinstance(value, dict):
        if set(value) == {'output_key'}:
            return allocated[value['output_key']]
        if 'memory_id' in value:
            return value['memory_id']
    return value


def _concrete_plan(value, allocated):
    if isinstance(value, dict):
        if set(value) == {'output_key'}:
            return allocated[value['output_key']]
        return {key: _concrete_plan(item, allocated) for key, item in value.items()}
    if isinstance(value, list):
        return [_concrete_plan(item, allocated) for item in value]
    return value


def _proposal_references(value, outputs, owner, *, restore=False):
    if isinstance(value, dict):
        if restore and 'memory_id' in value:
            label = next((label for label, ref in outputs.items() if ref == value), None)
            if label:
                return {'local': 'output'} if label == owner else {'proposal_ref': label}
        if not restore:
            if set(value) == {'local'}:
                return outputs[owner]
            if set(value) == {'proposal_ref'}:
                return outputs[value['proposal_ref']]
        return {key: _proposal_references(item, outputs, owner, restore=restore) for key, item in value.items()}
    if isinstance(value, list):
        return [_proposal_references(item, outputs, owner, restore=restore) for item in value]
    return value


def lower_group(group, decisions, batch, context, policy, current, token, now):
    proposals = tuple(batch.deterministic_proposals) + tuple(batch.proposals)
    by_key = {decision.decision_id: (decision, proposal)
              for decision, proposal in zip(decisions.decisions, proposals, strict=True)}
    event_ids = [generate_id() for _ in group.event_plan]
    allocated = {e['aggregate_id']['output_key']: identifier for e, identifier in zip(group.event_plan, event_ids, strict=True)
                 if e['operation'] == 'create'}
    outputs = {by_key[e['proposal_key']][1]['proposal_id']: {
        'memory_id': allocated[e['aggregate_id']['output_key']], 'source_event_id': identifier,
        'state_event_id': identifier, 'content_hash': e['value']['content_hash']}
        for e, identifier in zip(group.event_plan, event_ids, strict=True) if e['operation'] == 'create'}
    approved_outputs = {key: next(ref for ref in outputs.values() if ref['memory_id'] == mid)
                        for key, mid in allocated.items()}

    def approved_reference(value):
        if isinstance(value, dict) and set(value) == {'output_key'}:
            return approved_outputs[value['output_key']]
        return value

    group_id = str(uuid4())
    replay_proposals = []
    for key in group.decision_ids:
        decision, proposal = by_key[key]
        clean = thaw(proposal)
        effects = thaw(decision.approved_effects)
        approved_links = [link for effect in effects for link in effect.get('value', {}).get('links', [])]
        if 'link_suggestions' in clean:
            clean['link_suggestions'] = [link for link in clean['link_suggestions'] if any(
                all(_proposal_references(link[key], outputs, clean['proposal_id']) == approved_reference(approved[key])
                    for key in ('from_ref', 'to_ref', 'relation_type', 'description', 'confidence'))
                for approved in approved_links)]
        if not any('context' in effect.get('value', {}) for effect in effects):
            clean.pop('context', None)
        if decision.children and decision.children[0].decision == 'reject':
            for field in ('content', 'title', 'justification', 'equivalence_basis', 'contradiction_basis'):
                if field in clean:
                    clean[field] = ''
        replay_proposals.append(_proposal_references(clean, outputs, clean['proposal_id']))
    recovery = {'proposals': replay_proposals, 'inferences': {p['proposal_id']: thaw(context.inferences[p['proposal_id']])
                for p in replay_proposals if p['proposal_id'] in outputs and p['proposal_id'] in context.inferences},
                'created_outputs': outputs, 'allocations': allocated,
                'support_versions': thaw(context.support_versions), 'event_plan': _concrete_plan(thaw(group.event_plan), allocated)}
    fields = []
    for planned, event_id in zip(group.event_plan, event_ids, strict=True):
        planned = thaw(planned)
        decision, proposal = by_key[planned['proposal_key']]
        operation, value = planned['operation'], planned.get('value', {})
        aggregate_id = _references(planned['aggregate_id'], allocated)
        propagation_context = context.execution_context == 'deterministic_propagation'
        # A propagation wave recovers its permanent historical lineage instead of
        # distiller-window inputs; the window is null and no source is consumed.
        refs = thaw(context.historical_source_refs) if propagation_context else thaw(proposal['source_refs'])
        effect = {'memory_id': aggregate_id, 'links': []}
        for link in value.get('links', []):
            effect['links'].append({'from_id': _references(link['from_ref'], allocated),
                'to_id': _references(link['to_ref'], allocated), 'relation_type': link['relation_type'],
                'provenance': link.get('origin', 'llm_proposed'), 'confidence': link['confidence'],
                'created_by_run': str(token.run_id),
                'vocabulary_version': stable_key(current.vocabulary), 'category': link['category'],
                'propagation': link['propagation'], 'description': link['description'], 'source_refs': refs})
        model = context.inferences.get(proposal['proposal_id'], {}).get('inference_meta', {}).get('model_version', 'deterministic')
        if 'context' in value:
            effect['context'] = {**value['context'], 'keywords': list(dict.fromkeys(value['context']['keywords'])),
                'context_version': stable_key({'event': event_id, 'value': value['context']}), 'source_refs': refs,
                'model_version': model, 'prompt_version': '013.distiller.1', 'schema_version': '013.1'}
        attributions = [{key: fact[key] for key in ('evidence_id', 'source_id', 'version_id', 'version', 'position', 'content_hash')}
                        for fact in decision.proof.get('support_versions', ()) if fact.get('evidence_id')]
        if value.get('promotion_candidate'):
            effect['candidate'] = {'promote_candidate_at': now.isoformat(), 'candidate_version': stable_key(
                {'memory_id': aggregate_id, 'event_id': event_id, 'attributions': attributions}),
                'evidence_attributions': attributions}
        if operation in ('merge', 'invalidate'):
            replacement = _references(value.get('replacement_id'), allocated)
            effect['lifecycle'] = {'status': 'superseded' if replacement else 'retired',
                'valid_to': now.isoformat(), 'replacement_id': replacement,
                'keeper_id': _references(value.get('keeper_id'), allocated), 'trigger_event_id': None}
        effect_proof = decision.proof
        if 'confidence' not in effect_proof:
            effect_proof = next(child.proof for child in decision.children
                                if child.decision == 'accept' and 'confidence' in child.proof)
        origin = effect_proof['origin']
        outcomes = []
        if operation != 'derive':
            outcomes = [{'source_event_id': o['source_version']['source_event_id'], 'outcome': o['outcome'],
                         'required_group_key': group.group_key} for o in decision.source_outcomes]
        if propagation_context:
            material = thaw(proposal.get('propagation_material') or {})
            propagation = {'trigger': material['trigger'],
                'visited_memory_ids': list(material['visited_memory_ids']), 'depth': int(material['depth']),
                'frontier_memory_ids': list(material['frontier_memory_ids']),
                'continuation_key': material['continuation_key'],
                'vocabulary_version': material['vocabulary_version']}
            versions = {'model': model, 'prompt': None, 'schema': '013.1', 'rule': decision.rule_version,
                        'policy': stable_key(policy.model_dump()), 'vocabulary': stable_key(current.vocabulary)}
        else:
            propagation, versions = None, {'model': model, 'prompt': '013.distiller.1', 'schema': '013.1',
                                           'rule': decision.rule_version,
                                           'policy': stable_key(policy.model_dump()),
                                           'vocabulary': stable_key(current.vocabulary)}
        payload = {'payload_version': 2, 'operation': operation, 'action': proposal['action'],
            'proposal_key': planned['proposal_key'], 'group_key': group.group_key, 'group_id': group_id,
            'effect_index': planned['effect_index'], 'effect_count': planned['effect_count'],
            'created_by_run': str(token.run_id),
            'execution_context': 'deterministic_propagation' if propagation_context else 'distiller_window',
            'window_id': None if propagation_context else context.window.window_id, 'propagation': propagation,
            'source_refs': refs,
            'source_lineage': refs, 'target_refs': [{k: getattr(v, k) for k in
                ('memory_id', 'source_event_id', 'state_event_id', 'content_hash')} for v in decision.expected_versions
                if v.memory_id not in {r['memory_id'] for r in refs}], 'source_outcomes': outcomes,
            'required_support': [{'support_kind': 'evidence', 'support_id': a['evidence_id'],
                'version': str(a['version_id']), 'content_hash': a['content_hash'], 'revocation_semantics': 'must_remain_active'}
                for a in attributions], 'confidence': effect_proof['confidence'], 'confidence_origin': origin,
            'versions': versions,
            'captured_policy': policy.model_dump(), 'captured_vocabulary': thaw(current.vocabulary),
            'adjudication': {'decision_id': decision.decision_id, 'decision': 'accept', 'rule_version': decision.rule_version,
                'reason_codes': list(decision.reason_codes),
                'min_confidence': policy.consolidation.min_confidence if policy.consolidation else 0.,
                'proofs': [_concrete_plan(thaw(decision.proof), allocated), {'recovery': recovery}], 'evidence_attributions': attributions},
            'approved_effect': effect, 'evidence_refs': list(proposal.get('evidence_refs', ()))}
        if operation == 'create':
            payload.update(canonical_distilled(value, policy=policy, now=now))
        fields.append({'event_id': event_id, 'aggregate_id': aggregate_id, 'event_type': 'consolidate',
            'knowledge_scope_id': token.scope_id, 'payload': payload, 'actor': 'consolidation_service',
            'request_id': str(uuid4()), 'occurred_at': now, 'valid_from': now,
            'authority': {'source': 'consolidation_adjudicator'},
            'scope_meta': {'knowledge_scope_id': token.scope_id}, 'mutability': {'correction': 'append_event'},
            'provenance_meta': {'provenance': 'distilled' if operation == 'create' else 'consolidation',
                                'source_lineage': refs, 'validated': True,
                                'evidence_attributions': attributions},
            'recoverability': {'source': 'event_log', 'group_key': group.group_key}, 'actionability': 'evidence'})
    return fields


async def _publish(service, runtime, token, fence, fields=None, *, context=None):
    scope = token.scope_id
    store = MemoryEventStore(service.session)
    await service.session.execute(text("SELECT set_config('rag_memory.consolidation_token',:token,true)"),
                                  {'token': str(token.eligibility_id)})
    await service.session.execute(text("SELECT set_config('rag_memory.consolidation_fence',:fence,true),"
        "set_config('rag_memory.consolidation_started_at',:started,true)"),
        {'fence': json.dumps(token.to_dict()), 'started': fence.started_at.isoformat()})
    if context is not None and context.execution_context == 'deterministic_propagation':
        # Maintenance waves commit under a disabled ordinary policy; the SQL
        # fence accepts only this exact eligibility identity as the allowance.
        await service.session.execute(text("SELECT set_config('rag_memory.consolidation_maintenance',:maintenance,true)"),
                                      {'maintenance': str(token.eligibility_id)})
    try:
        async with service.session.begin_nested():
            if fields:
                await store.append_many(MemoryEvent(**value) for value in fields)
            history = await store.replay(scope)
            state = reduce_events(history)
            fence._publication_event_id = history[-1]['event_id']
            service._ensure_vector_store()
            await service.projections.materialize(state, scope, history[-1]['event_id'],
                                                  final_fence=fence.validate_before_publish)
    except ProjectionFailure as failure:
        if failure.path not in ('dense', 'files'):
            raise
        if fields:
            await store.append_many(MemoryEvent(**value) for value in fields)
        history = await store.replay(scope)
        state = reduce_events(history)
        await service.projections.retain_failure(state, scope, history[-1]['event_id'], failure.path)
        return False
    finally:
        fence._publication_event_id = None
    return True


async def commit_approved(service, decisions, token, *, runtime, batch, context):
    memories, events, pending, reasons = [], [], [], []
    for requested in decisions.groups:
        try:
            async with runtime.commit_fence(token, context=context) as fence:
                history = await MemoryEventStore(service.session).replay(token.scope_id)
                current = await runtime.read_snapshot(token.scope_id)
                existing = current.consolidation_state['potential_results'].get(requested.group_key)
                if existing and not existing.get('rolled_back'):
                    memories.extend(existing['memory_ids'])
                    events.extend(existing['event_ids'])
                    continue
                if history and history[-1]['event_id'] != current.high_water_mark:
                    pending.extend(dict.fromkeys(e['payload']['group_key'] for e in history
                        if e['event_id'] > current.high_water_mark and e['event_type'] == 'consolidate'
                        and e['payload'].get('payload_version') == 2))
                    reasons.append('CONSOLIDATION_PENDING_RECOVERY_REQUIRED')
                    break
                checked, current, policy, fresh_context, now = await locked_approval(runtime, token, batch, context)
                group = next((g for g in checked.groups if g.group_key == requested.group_key), None)
                if group is None:
                    reasons.extend(code for d in checked.decisions for child in (d, *d.children)
                                   if child.decision == 'reject' for code in child.reason_codes)
                    if not reasons:
                        reasons.append('POLICY_CHANGED')
                    continue
                fields = lower_group(group, checked, batch, fresh_context, policy, current, token, now)
                published = await _publish(service, runtime, token, fence, fields, context=context)
                if published:
                    memories.extend(v['aggregate_id'] for v in fields if v['payload']['operation'] == 'create')
                    events.extend(v['event_id'] for v in fields)
                else:
                    pending.append(group.group_key)
            if pending:
                break
        except ConsolidationRuntimeError as error:
            return CommitOutcome('rejected', tuple(memories), tuple(events), reason_codes=(str(error),))
        except (ProjectionFailure, DBAPIError) as error:
            reason = str(error) if isinstance(error, ProjectionFailure) else 'CONSOLIDATION_RELATIONAL_FAILURE'
            return CommitOutcome('rolled_back', tuple(memories), tuple(events), reason_codes=(reason,),
                                 failed_result_keys=(requested.group_key,))
    if pending:
        return CommitOutcome('pending', tuple(memories), tuple(events), tuple(pending), tuple(reasons))
    return CommitOutcome('completed' if events else 'rejected', tuple(memories), tuple(events), reason_codes=tuple(reasons))


async def recover_consolidation(service, token, *, runtime):
    try:
        async with runtime.commit_fence(token) as fence:
            current = await runtime.read_snapshot(token.scope_id)
            history = await MemoryEventStore(service.session).replay(token.scope_id)
            retained = [e for e in history if e['event_id'] > current.high_water_mark and e['event_type'] == 'consolidate'
                        and e['payload'].get('payload_version') == 2]
            keys = tuple(dict.fromkeys(e['payload']['group_key'] for e in retained))
            if not retained:
                return CommitOutcome('rejected', reason_codes=('NO_PENDING_GROUP',))
            for root in (e for e in retained if e['payload']['effect_index'] == 0):
                p = root['payload']
                recovery = p['adjudication']['proofs'][-1]['recovery']
                window = await runtime.retry_window(token.scope_id, p['window_id'])
                context = AdjudicationContext(window=window, inferences=recovery['inferences'],
                    support_versions=recovery['support_versions'])
                batch = ProposalBatch([_proposal_references(proposal, recovery.get('created_outputs', {}),
                    proposal['proposal_id'], restore=True) for proposal in recovery['proposals']])
                checked, *_ = await locked_approval(runtime, token, batch, context)
                if not any(_concrete_plan(thaw(g.event_plan), recovery.get('allocations', {})) == recovery['event_plan']
                           for g in checked.groups):
                    return CommitOutcome('pending', pending_result_keys=keys, reason_codes=('PENDING_REQUIRES_GOVERNANCE',))
            published = await _publish(service, runtime, token, fence)
            if not published:
                return CommitOutcome('pending', pending_result_keys=keys)
            return CommitOutcome('completed', tuple(e['aggregate_id'] for e in retained if e['payload']['operation'] == 'create'),
                                 tuple(e['event_id'] for e in retained))
    except ConsolidationRuntimeError as error:
        return CommitOutcome('pending', reason_codes=(str(error),))
