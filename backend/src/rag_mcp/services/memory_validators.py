"""Validation at the memory boundary; caller claims never establish authority."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from rag_mcp.agents.injection_detector import InjectionDetector
from rag_mcp.models.chunk import Chunk
from rag_mcp.models.knowledge_source import KnowledgeSource
from rag_mcp.models.knowledge_version import KnowledgeVersion
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.parsers.credential_redactor import redact_credentials


def canonical_distilled(value, *, policy, now):
    from datetime import timedelta

    from rag_mcp.orchestration.consolidation_pipeline import thaw

    value = thaw(value)
    meta = {key: item for key, item in value['inference_meta'].items() if key != 'origin'}
    meta['confidence_origin'] = 'llm_self'
    metadata = {key: value.get(key) for key in ('kind', 'provenance', 'confidence', 'title')}
    metadata.update(inference_meta=meta, session_id=None, agent_id=None, task_context=None,
                    supersedes_memory_id=None, tags=[], evidence_refs=value['evidence_refs'])
    checked = detect_submission({'content': value['content_text']})
    if checked.status != 'active' or checked.content != value['content_text']:
        raise ValueError('GENERATED_CONTENT_UNSAFE')
    ttl = derive_ttl(value['kind'], policy.model_dump())
    return {**metadata, 'content_text': value['content_text'], 'content_hash': value['content_hash'],
        'submission_meta': metadata, 'status': 'active', 'injection_flags': checked.injection_flags,
        'provenance_validation': {'provenance': 'distilled', 'validated': True,
                                  'attributions': value['source_lineage']},
        'created_at': now.isoformat(), 'updated_at': now.isoformat(), 'valid_from': now.isoformat(),
        'decay_rate': policy.decay_rate,
        'expires_at': (now + timedelta(days=ttl)).isoformat() if ttl is not None else None}


def validate_consolidation_payload(event):
    from pathlib import Path

    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource

    root = Path(__file__).resolve().parents[4] / 'specs/013-memory-consolidation-loop/contracts'
    schemas = [json.loads((root / name).read_text(encoding='utf-8')) for name in
               ('consolidate-event.schema.json', 'distiller-output.schema.json')]
    registry = Registry().with_resources((schema['$id'], Resource.from_contents(schema)) for schema in schemas)
    payload = event['payload']
    json.dumps(payload, allow_nan=False)
    Draft202012Validator(schemas[0], registry=registry, format_checker=FormatChecker()).validate(payload)
    if (event['aggregate_id'] != payload['approved_effect']['memory_id']
        or event.get('actor') != 'consolidation_service'
        or event.get('authority', {}).get('source') != 'consolidation_adjudicator'
        or event.get('scope_meta') != {'knowledge_scope_id': event['knowledge_scope_id']}):
        raise ValueError('CONSOLIDATION_AUTHORITY_INVALID')
    if any(outcome['required_group_key'] != payload['group_key'] for outcome in payload['source_outcomes']):
        raise ValueError('CONSOLIDATION_GROUP_INVALID')
    if payload['source_lineage'] != payload['source_refs']:
        raise ValueError('SOURCE_CHAIN_INCOMPLETE')
    if payload['execution_context'] == 'deterministic_propagation':
        # Trusted support-maintenance waves: historical lineage, null window,
        # captured propagation material, invalidate-only and no consumption.
        propagation = payload.get('propagation') or {}
        if (payload['operation'] != 'invalidate' or payload['action'] != 'invalidate_contradiction'
            or payload['window_id'] is not None or not propagation
            or payload['source_outcomes'] or payload['confidence_origin'] != 'deterministic_rule'
            or payload['approved_effect'].get('links') or 'context' in payload['approved_effect']
            or 'candidate' in payload['approved_effect']
            or set(propagation.get('trigger') or {}) != {'kind', 'event_id', 'evidence_id', 'version',
                                                         'observed_at', 'proof'}
            or not propagation['trigger']['proof']
            or (propagation['trigger']['event_id'] is None
                and propagation['trigger']['evidence_id'] is None)):
            raise ValueError('CONSOLIDATION_AUTHORITY_INVALID')
    if payload['operation'] == 'create':
        if (payload['confidence'] != payload['inference_meta']['confidence']
            or payload['inference_meta']['confidence_origin'] != payload['confidence_origin']
            or payload['content_hash'] != hashlib.sha256(payload['content_text'].encode()).hexdigest()
            or payload['inference_meta']['supporting_evidence'] != [f"memory:{r['memory_id']}" for r in payload['source_refs']]):
            raise ValueError('SOURCE_CHAIN_INCOMPLETE')
        for key, value in payload['submission_meta'].items():
            if payload.get(key) != value:
                raise ValueError('CONSOLIDATION_METADATA_INVALID')
    return payload


@dataclass(frozen=True)
class SanitizedMemory:
    content: str
    injection_flags: dict
    status: str


def _confidence(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("MEMORY_PROVENANCE_INVALID")


def validate_memory(payload):
    if payload.get("kind") not in {"episodic", "semantic", "procedural"}:
        raise ValueError("MEMORY_KIND_INVALID")
    scope = payload.get("scope_id")
    if isinstance(scope, bool) or not isinstance(scope, int) or scope <= 0:
        raise ValueError("MISSING_KNOWLEDGE_SCOPE")
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip() or len(content) > 4000:
        raise ValueError("MEMORY_PROVENANCE_INVALID")
    if payload.get("confidence") is not None:
        _confidence(payload["confidence"])
    for field, maximum in (("title", 512), ("agent_id", 255)):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > maximum):
            raise ValueError("MEMORY_PROVENANCE_INVALID")
    tags = payload.get("tags")
    if tags is not None and (not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags)):
        raise ValueError("MEMORY_PROVENANCE_INVALID")
    if payload.get("task_context") is not None and not isinstance(payload["task_context"], dict):
        raise ValueError("MEMORY_PROVENANCE_INVALID")
    if payload.get("session_id") is not None:
        try:
            UUID(payload["session_id"])
        except (ValueError, TypeError, AttributeError):
            raise ValueError("MEMORY_PROVENANCE_INVALID") from None
    provenance = payload.get("provenance")
    if provenance == "hard":
        if payload.get("confidence") is not None:
            raise ValueError("MEMORY_PROVENANCE_INVALID")
        refs = payload.get("evidence_refs")
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref.isdecimal() for ref in refs):
            raise ValueError("MEMORY_EVIDENCE_ANCHOR_REQUIRED")
    elif provenance in {"soft", "distilled"}:
        meta = payload.get("inference_meta")
        required = {"source", "confidence", "model_version", "time", "supporting_evidence"}
        if not isinstance(meta, dict) or not required <= meta.keys():
            raise ValueError("MEMORY_INFERENCE_META_INCOMPLETE")
        if any(not isinstance(meta[key], str) or not meta[key].strip() for key in ("source", "model_version", "time")):
            raise ValueError("MEMORY_INFERENCE_META_INCOMPLETE")
        _confidence(meta["confidence"])
        if not isinstance(meta["supporting_evidence"], list) or any(not isinstance(ref, str) or not ref for ref in meta["supporting_evidence"]):
            raise ValueError("MEMORY_INFERENCE_META_INCOMPLETE")
        try:
            timestamp = datetime.fromisoformat(meta["time"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("timezone required")
        except ValueError:
            raise ValueError("MEMORY_INFERENCE_META_INCOMPLETE") from None
        if provenance == "distilled" and not meta["supporting_evidence"]:
            raise ValueError("MEMORY_PROVENANCE_INVALID")
    else:
        raise ValueError("MEMORY_PROVENANCE_INVALID")
    return payload


class MemoryProvenanceValidator:
    def __init__(self, session):
        self.session = session

    async def validate(self, payload, *, _chain=()):
        validate_memory(payload)
        attributions = []
        if payload["provenance"] == "hard":
            for reference in payload["evidence_refs"]:
                row = (await self.session.execute(
                    select(Chunk, KnowledgeVersion, KnowledgeSource)
                    .join(KnowledgeVersion, Chunk.version_id == KnowledgeVersion.version_id)
                    .join(KnowledgeSource, Chunk.source_id == KnowledgeSource.source_id)
                    .where(Chunk.chunk_id == int(reference))
                    .with_for_update(read=True)
                )).first()
                if not row:
                    raise ValueError("MEMORY_EVIDENCE_ANCHOR_REQUIRED")
                chunk, version, source = row
                if any(scope != payload["scope_id"] for scope in (
                    chunk.knowledge_scope_id, version.knowledge_scope_id, source.knowledge_scope_id
                )):
                    raise ValueError("MEMORY_EVIDENCE_SCOPE_MISMATCH")
                if version.status != "published" or source.status != "published" or not chunk.content_text.strip() or not chunk.position_path or version.version_number < 1:
                    raise ValueError("MEMORY_EVIDENCE_ANCHOR_REQUIRED")
                attributions.append({"evidence_id": reference, "source_id": source.source_id,
                    "version_id": version.version_id, "version": version.version_number,
                    "position": chunk.position_path,
                    "content_hash": hashlib.sha256(chunk.content_text.encode()).hexdigest()})
        elif payload["provenance"] == "distilled":
            for reference in payload["inference_meta"]["supporting_evidence"]:
                identifier = reference.removeprefix("memory:")
                if not identifier.isdecimal():
                    raise ValueError("MEMORY_PROVENANCE_INVALID")
                source = await self.session.get(MemoryEntry, int(identifier))
                if source is None or source.knowledge_scope_id != payload["scope_id"] or source.status != "active" or source.write_status != "complete":
                    raise ValueError("MEMORY_PROVENANCE_INVALID")
                if source.memory_id in _chain or len(_chain) >= 32 or source.expires_at and source.expires_at <= datetime.now(UTC):
                    raise ValueError("MEMORY_PROVENANCE_INVALID")
                source_payload = {"scope_id": source.knowledge_scope_id, "kind": source.kind,
                    "content": source.content_text, "provenance": source.provenance,
                    "confidence": source.confidence, "evidence_refs": source.evidence_refs, "inference_meta": source.inference_meta}
                try:
                    verified = await self.validate(source_payload, _chain=(*_chain, source.memory_id))
                except ValueError:
                    raise ValueError("MEMORY_PROVENANCE_INVALID") from None
                attributions.append({"memory_id": source.memory_id, "provenance": source.provenance,
                                     "evidence_refs": source.evidence_refs, "inference_meta": source.inference_meta,
                                     "source_chain": verified})
        return {"provenance": payload["provenance"], "validated": True, "attributions": attributions}


_SHORT_CREDENTIAL = re.compile(
    r'''(?i)(\b(password|passwd|pwd|token|api[_-]?key|client_secret|secret)\s*[:=]\s*)(["']?)([^\s"'<>]+)(["']?)'''
)


def _credential_type(field):
    field = field.lower()
    return "password" if field in {"password", "passwd", "pwd"} else "api-key" if field in {"api_key", "api-key"} else "secret" if "secret" in field else "token"


def _redact_tree(value):
    from collections.abc import Mapping
    if isinstance(value, str):
        return _SHORT_CREDENTIAL.sub(lambda match: f"{match[1]}{match[3]}<{_credential_type(match[2])}>{match[5]}", redact_credentials(value))
    if isinstance(value, (list, tuple)):
        return [_redact_tree(item) for item in value]
    if isinstance(value, Mapping):
        return {key: f"<{_credential_type(key)}>" if isinstance(key, str) and key.lower() in {"password", "passwd", "pwd", "token", "api_key", "api-key", "client_secret", "secret"}
                and item is not None else _redact_tree(item) for key, item in value.items()}
    return value


def sanitize_memory(content):
    redacted = _redact_tree(content)
    try:
        report = InjectionDetector().detect(redacted, strict=True)
        if report.risk_level not in {"none", "low", "high"}:
            raise ValueError("invalid detector result")
    except Exception:
        raise ValueError("MEMORY_WRITE_UNAVAILABLE") from None
    flags = {"suspicious": report.suspicious, "risk_level": report.risk_level,
             "matched_patterns": report.matched_patterns}
    return SanitizedMemory(redacted, flags, "quarantined" if report.risk_level == "high" else "active")


def redact_submission(payload):
    return _redact_tree(payload)


def sanitize_consolidation_audit(payload, *, scope_id):
    """Keep same-scope diagnostics, withholding raw failures and unsafe text."""
    from collections.abc import Mapping

    def scoped(value):
        if isinstance(value, Mapping):
            if any(str(value[key]) != str(scope_id) for key in ('scope_id', 'knowledge_scope_id') if key in value):
                return {'reason_code': 'SCOPE_MISMATCH'}
            return {key: '<failure body withheld>' if key in ('failure_body', 'response_body', 'raw_error')
                    else scoped(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [scoped(item) for item in value]
        if isinstance(value, str):
            try:
                if detect_submission({'content': value}).status != 'active':
                    return '<unsafe text withheld>'
            except ValueError:
                return '<unverified text withheld>'
        return value

    return scoped(redact_submission(payload))


def detect_submission(clean):
    # Scan every text leaf, including nested context, reasons, keywords and links.
    # Existing callers also pass arbitrary frozen DTO mappings and tuples.
    checked = sanitize_memory(json.dumps(_redact_tree(clean), ensure_ascii=False, allow_nan=False))
    authority = re.search(
        r'\b(?:switch|change)\s+(?:the\s+)?scope\s+to\b|'
        r'\bgrant\s+(?:writer|admin|hard)\s+(?:permission|authority)\b|'
        r'\b(?:write|create)\s+hard\s+memor|'
        r'\benable\s+(?:consolidation\s+)?policy\b|'
        r'\bpromote\s+memor\w*\s+automatically\b',
        json.dumps(_redact_tree(clean), ensure_ascii=False), re.IGNORECASE)
    if authority:
        return SanitizedMemory(clean.get('content', ''),
                               {'suspicious': True, 'risk_level': 'high',
                                'matched_patterns': ['memory_authority_override']}, 'quarantined')
    return SanitizedMemory(clean.get("content", ""), checked.injection_flags, checked.status)


def sanitize_submission(payload):
    clean = redact_submission(payload)
    return clean, detect_submission(clean)


def validate_supersede(payload):
    target = payload.get("target") or {}
    if target.get("scope_id") != payload.get("scope_id") or target.get("status") != "active":
        raise ValueError("MEMORY_SUPERSEDE_TARGET_INVALID")
    if target.get("provenance") == "hard" and payload.get("provenance") != "hard":
        raise ValueError("MEMORY_SUPERSEDE_TARGET_INVALID")


def check_quota(current, quota):
    if current >= quota:
        raise ValueError("MEMORY_QUOTA_EXCEEDED")


def derive_ttl(kind, policy):
    return policy.get("episodic_ttl_days", 180) if kind == "episodic" else policy.get("semantic_procedural_ttl_days")
