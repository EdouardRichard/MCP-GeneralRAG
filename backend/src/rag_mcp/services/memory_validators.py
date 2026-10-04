from __future__ import annotations

import re
from dataclasses import dataclass


class SanitizedMemory:
    def __init__(self, content, injection_flags, status):
        self.content, self.injection_flags, self.status = content, injection_flags, status


def validate_memory(payload):
    if payload.get("kind") not in {"episodic", "semantic", "procedural"}:
        raise ValueError("MEMORY_KIND_INVALID")
    if not payload.get("scope_id"):
        raise ValueError("MISSING_KNOWLEDGE_SCOPE")
    provenance = payload.get("provenance")
    if provenance == "hard":
        refs = payload.get("evidence_refs") or []
        if not refs:
            raise ValueError("MEMORY_PROVENANCE_INVALID")
        for ref in refs:
            if isinstance(ref, str) or not ref.get("published") or ref.get("scope_id") != payload["scope_id"] or not all(ref.get(k) is not None for k in ("source_id", "version", "position")):
                raise ValueError("MEMORY_EVIDENCE_INVALID")
    elif provenance in {"soft", "distilled"}:
        required = {"source", "confidence", "model_version", "time", "supporting_evidence"}
        if not required.issubset((payload.get("inference_meta") or {}).keys()):
            raise ValueError("MEMORY_INFERENCE_META_INCOMPLETE")
        if provenance == "distilled" and not payload.get("source_memory_ids"):
            raise ValueError("MEMORY_SOURCE_CHAIN_INVALID")
    else:
        raise ValueError("MEMORY_PROVENANCE_INVALID")
    return payload


def sanitize_memory(content):
    redacted = re.sub(r"(?i)(password|token|api[_-]?key)\s*=\s*[^\s]+", r"\1=[REDACTED]", content)
    flags = ["prompt_injection"] if re.search(r"(?i)ignore previous instructions|system prompt", content) else []
    return SanitizedMemory(redacted, flags, "quarantined" if flags else "active")


def validate_supersede(payload):
    target = payload.get("target") or {}
    if target.get("scope_id") != payload.get("scope_id") or target.get("status") != "active":
        raise ValueError("MEMORY_SUPERSEDE_INVALID")


def check_quota(current, quota):
    if current >= quota:
        raise ValueError("MEMORY_QUOTA_EXCEEDED")


def derive_ttl(kind, policy):
    return (policy.get("ttl_days") or {}).get(kind)
