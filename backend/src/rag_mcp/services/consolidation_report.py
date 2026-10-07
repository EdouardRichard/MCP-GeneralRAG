"""Same-scope writer read model for consolidation runs (013 T085).

Reports are derived only from the append-only observation trail plus the
retained eligibility history. They never invent a status: accepted is never
shown as committed, unknown usage stays null, and a purged audit trail is only
reported as expired when a same-scope long-term run identity proves the run
existed — otherwise the run does not exist as far as the management surface is
concerned.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from rag_mcp.models.consolidation_run import ConsolidationEligibility, ConsolidationRunObservation

NOT_FOUND = 'CONSOLIDATION_RUN_NOT_FOUND'
EXPIRED = 'CONSOLIDATION_RUN_EXPIRED'


class ConsolidationRunMissing(LookupError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _identifier(value):
    return None if value is None else str(value)


def _counts(observation):
    proposals = list(observation.proposals or ())
    adjudications = list(observation.adjudications or ())

    def published(state):
        return sum(1 for item in adjudications if item.get('publication') == state)

    return {'proposed': len(proposals),
            'accepted': sum(1 for item in adjudications if item.get('decision') == 'accept'),
            'rejected': sum(1 for item in adjudications if item.get('decision') == 'reject'),
            'committed': published('committed'),
            'pending': published('pending'),
            'failed': published('failed'),
            'unprocessed': max(0, len(proposals) - len(adjudications))}


def _observation_body(observation, *, history=False):
    trigger = observation.propagation_trigger or None
    body = {
        'run_id': str(observation.run_id),
        'scope_id': str(observation.knowledge_scope_id),
        'request_id': observation.request_id,
        'trigger': observation.trigger,
        'execution_context': observation.execution_context,
        'status': observation.status,
        'observation_seq': observation.observation_seq,
        'window': observation.window,
        'input_event_ids': [_identifier(item) for item in observation.input_event_ids or ()],
        'reference_versions': list(observation.reference_versions or ()),
        'proposals': list(observation.proposals or ()),
        'adjudications': list(observation.adjudications or ()),
        'output_memory_ids': [_identifier(item) for item in observation.output_memory_ids or ()],
        'output_event_ids': [_identifier(item) for item in observation.output_event_ids or ()],
        'pending_result_keys': list(observation.pending_result_keys or ()),
        'provider_usage': observation.provider_usage,
        'degradation_reasons': list(observation.degradation_reasons or ()),
        'versions': observation.versions,
        'counts': _counts(observation),
        'eligibility_state': observation.eligibility_state,
        'created_at': observation.created_at.isoformat(),
        'ttl_expires_at': observation.ttl_expires_at.isoformat(),
    }
    if trigger is not None:
        body['historical_source_refs'] = list(observation.historical_source_refs or ())
        body['propagation_trigger'] = trigger
        body['proof'] = trigger.get('proof')
    return body


async def _eligibilities(session, *, run_id, scope_id):
    return (await session.execute(select(ConsolidationEligibility).where(
        ConsolidationEligibility.run_id == run_id,
        ConsolidationEligibility.knowledge_scope_id == scope_id)
        .order_by(ConsolidationEligibility.eligibility_version))).scalars().all()


async def _eligibility_history(session, *, run_id, scope_id):
    rows = await _eligibilities(session, run_id=run_id, scope_id=scope_id)
    latest = rows[-1] if rows else None
    return [{'eligibility_id': str(row.eligibility_id),
             'eligibility_version': row.eligibility_version,
             'state': row.state,
             'acquired_at': row.acquired_at.isoformat(),
             'renewed_at': row.renewed_at.isoformat(),
             'expires_at': row.expires_at.isoformat(),
             'released_at': row.released_at.isoformat() if row.released_at else None,
             'is_current': latest is not None and row.eligibility_id == latest.eligibility_id}
            for row in rows]


async def get_run_report(session, *, run_id, scope_id, include_history=False):
    try:
        identifier = UUID(str(run_id))
    except (TypeError, ValueError):
        raise ConsolidationRunMissing(NOT_FOUND) from None
    observations = (await session.execute(select(ConsolidationRunObservation).where(
        ConsolidationRunObservation.run_id == identifier,
        ConsolidationRunObservation.knowledge_scope_id == scope_id)
        .order_by(ConsolidationRunObservation.observation_seq))).scalars().all()
    history = await _eligibility_history(session, run_id=identifier, scope_id=scope_id)
    if not observations:
        # Long-term same-scope identity proof only; an unadmitted attempt never
        # acquires existence proof and a foreign scope never leaks metadata.
        raise ConsolidationRunMissing(EXPIRED if history else NOT_FOUND)
    latest = observations[-1]
    body = _observation_body(latest, history=include_history)
    body['schema_version'] = 1
    body['eligibility_history'] = history
    body['current_generation'] = history[-1] if history else None
    body['history'] = [_observation_body(item, history=True) for item in observations] if include_history else []
    return body


async def list_run_reports(session, *, scope_id, limit=20, offset=0):
    statement = (select(ConsolidationRunObservation)
                 .where(ConsolidationRunObservation.knowledge_scope_id == scope_id)
                 .distinct(ConsolidationRunObservation.run_id)
                 .order_by(ConsolidationRunObservation.run_id,
                           ConsolidationRunObservation.observation_seq.desc()))
    latest = (await session.execute(statement)).scalars().all()
    total = await session.scalar(select(func.count(func.distinct(ConsolidationRunObservation.run_id))).where(
        ConsolidationRunObservation.knowledge_scope_id == scope_id))
    ordered = sorted(latest, key=lambda item: (item.created_at, str(item.run_id)), reverse=True)
    history = await _eligibility_history_map(session, scope_id=scope_id)
    items = []
    for observation in ordered[offset:offset + limit]:
        body = _observation_body(observation)
        body['schema_version'] = 1
        body['current_generation'] = (history.get(observation.run_id) or [None])[-1]
        items.append(body)
    return {'schema_version': 1, 'scope_id': str(scope_id), 'items': items, 'total': total or 0}


async def _eligibility_history_map(session, *, scope_id):
    rows = (await session.execute(select(ConsolidationEligibility).where(
        ConsolidationEligibility.knowledge_scope_id == scope_id)
        .order_by(ConsolidationEligibility.eligibility_version))).scalars().all()
    grouped: dict[UUID, list] = {}
    for row in rows:
        grouped.setdefault(row.run_id, []).append({
            'eligibility_id': str(row.eligibility_id), 'eligibility_version': row.eligibility_version,
            'state': row.state, 'acquired_at': row.acquired_at.isoformat(),
            'renewed_at': row.renewed_at.isoformat(), 'expires_at': row.expires_at.isoformat(),
            'released_at': row.released_at.isoformat() if row.released_at else None,
            'is_current': False})
    for entries in grouped.values():
        entries[-1]['is_current'] = True
    return grouped
