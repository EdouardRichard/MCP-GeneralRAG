"""Read completed, versioned PG views; vector payloads never decide lifecycle."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from time import monotonic
from types import SimpleNamespace
from uuid import UUID, uuid4

from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import case, func, select, text

from rag_mcp.fusion.rrf import weighted_memory_rrf
from rag_mcp.indexing.qdrant_client import QdrantStore
from rag_mcp.indexing.memory_vectors import revision_filter
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
from rag_mcp.models.memory_recall_run import MemoryRecallRun
from rag_mcp.services.scope_resolver import MemoryScopeResolver
from rag_mcp.services.salience_service import SalienceService


READ_GUIDANCE = "Verify anchors."
WEIGHTS = {"dense": 1., "recency": .5, "kind": .3, "salience": .2}


def timestamp(value):
    if value is None:
        return None
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("MEMORY_PROVENANCE_INVALID: timezone required")
    return result


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def text_characters(value):
    if isinstance(value, dict):
        return sum(text_characters(item) for item in value.values())
    if isinstance(value, list):
        return sum(text_characters(item) for item in value)
    return len(value) if isinstance(value, str) else 0


def serialized_characters(value):
    """Count the exact deterministic JSON body, including its envelope fields."""
    candidate = dict(value)
    counts = dict(candidate.get("counts") or {})
    candidate["counts"] = {**counts, "characters": 0}
    for _ in range(4):
        length = len(canonical(candidate))
        if candidate["counts"]["characters"] == length:
            break
        candidate["counts"]["characters"] = length
    return candidate["counts"]["characters"]


def memory_visible(row, *, point, now, include_superseded=False):
    allowed = {"active", "superseded"} if include_superseded else {"active"}
    if row["status"] not in allowed or point is None and row.get("retention_stage") == "archived":
        return False
    reference = point or now
    # An explicit chain read can show closed superseded entries; as_of never
    # relaxes the valid interval, regardless of the include flags.
    if point is not None or row["status"] == "active":
        start, end = timestamp(row.get("valid_from")), timestamp(row.get("valid_to"))
        if start is not None and reference < start or end is not None and reference >= end:
            return False
    expires = timestamp(row.get("expires_at"))
    return expires is None or reference < expires


def public_entry(row, *, match=None):
    content = row["content_text"]
    keys = ("memory_id", "knowledge_scope_id", "kind", "provenance", "title", "confidence", "evidence_refs", "retention_stage",
            "valid_from", "valid_to", "observed_at", "session_id", "agent_id", "status", "superseded_by", "inference_meta")
    return {**{key: row.get(key) for key in keys}, "content_excerpt": content[:300],
            "truncated": len(content) > 300, "content_length": len(content), "match": match}


def stable_package_visible(row):
    # A cacheable body cannot reveal and later remove a finite-lifetime fact
    # without changing data. Such facts remain available through live recall.
    if row["status"] != "active" or row.get("retention_stage") == "archived":
        return False
    if row.get("valid_to") is not None or row.get("expires_at") is not None:
        return False
    start, observed = timestamp(row.get("valid_from")), timestamp(row.get("observed_at"))
    return start is None or observed is not None and start <= observed


class MemoryReader:
    def __init__(self, session, projections):
        self.session, self.projections = session, projections

    async def _views(self, scope_ids, *, memory_ids=None):
        # All scopes use one statement snapshot. Pending manifests cannot be consumed.
        await self.session.execute(text("SET LOCAL ROLE rag_memory_reader"))
        payload = MemoryProjectionMeta.payload
        entries = payload["state"]["entries"]
        if memory_ids is not None:
            entries = func.jsonb_build_object(*(part for mid in dict.fromkeys(memory_ids)
                                               for part in (str(mid), entries[str(mid)])))
        records = (await self.session.execute(select(
            MemoryProjectionMeta.knowledge_scope_id, MemoryProjectionMeta.source_event_id,
            MemoryProjectionMeta.projection_type, MemoryProjectionMeta.status,
            case((MemoryProjectionMeta.projection_type == "manifest", entries)).label("entries"),
            case((MemoryProjectionMeta.projection_type == "manifest", payload["state"]["salience"])).label("salience"),
            payload["failed_paths"].label("failed_paths"), payload["collection"].as_string().label("collection"),
            payload["dense_revision"].label("dense_revision"), payload["verification_version"].label("verification_version")
        ).where(
            MemoryProjectionMeta.knowledge_scope_id.in_(scope_ids),
            MemoryProjectionMeta.projection_type.in_(["manifest", "pending"])))).all()
        manifests = [row for row in records if row.projection_type == "manifest" and row.status == "complete" and row.verification_version == 1]
        completed = {row.knowledge_scope_id: row.source_event_id for row in manifests}
        failed = sorted({path for row in records if row.projection_type == "pending" and
                         row.source_event_id > completed.get(row.knowledge_scope_id, 0)
                         for path in row.failed_paths or []})
        if any(row.projection_type == "manifest" and row.verification_version != 1 for row in records):
            failed = sorted(set(failed + ["projection_verification_required"]))
        rows, salience = {}, {}
        for manifest in manifests:
            for identifier, row in (manifest.entries or {}).items():
                if row is None:
                    continue
                if row["knowledge_scope_id"] != manifest.knowledge_scope_id:
                    raise ValueError("MEMORY_EVIDENCE_SCOPE_MISMATCH")
                rows[int(identifier)] = row
            salience.update({int(key): value for key, value in (manifest.salience or {}).items()})
        descriptors = [SimpleNamespace(knowledge_scope_id=row.knowledge_scope_id,
                                      payload={"collection": row.collection, "dense_revision": row.dense_revision}) for row in manifests]
        return rows, salience, descriptors, failed

    async def _dense(self, manifests, query, limit, kind, session_id):
        vector = await self.projections.embedding.embed_query(query)
        if self.projections.qdrant is None:
            self.projections.qdrant = await asyncio.to_thread(QdrantStore)
        async def search(manifest):
            conditions = revision_filter(manifest.knowledge_scope_id, manifest.payload.get("dense_revision")).must
            for key, value in (("kind", kind), ("session_id", session_id)):
                if value is not None:
                    conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))
            result = await asyncio.to_thread(self.projections.qdrant._client.query_points,
                collection_name=manifest.payload["collection"], query=vector,
                query_filter=Filter(must=conditions), limit=max(40, limit * 4), with_payload=["memory_id"])
            return [(int(point.payload["memory_id"]), float(point.score)) for point in result.points]
        results = await asyncio.gather(*(search(manifest) for manifest in manifests), return_exceptions=True)
        scores, failures, failed_scopes = {}, [], []
        for manifest, result in zip(manifests, results, strict=True):
            if isinstance(result, BaseException):
                failures.append("dense_unavailable")
                failed_scopes.append(manifest.knowledge_scope_id)
            else:
                scores.update(result)
        return scores, sorted(set(failures)), failed_scopes

    async def recall(self, *, scope_ref, query=None, memory_ids=None, kind=None, session_id=None,
                     agent_id=None, time_window=None, as_of=None, include_superseded=False,
                     include_delivered=False, limit=10):
        started = monotonic()
        if query is not None and memory_ids is not None:
            raise ValueError("MEMORY_IDS_QUERY_CONFLICT")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("MEMORY_PROVENANCE_INVALID: limit")
        if query is not None and (not isinstance(query, str) or not query.strip() or len(query) > 2000):
            raise ValueError("MEMORY_PROVENANCE_INVALID: query")
        if memory_ids is not None and (not isinstance(memory_ids, list) or any(not isinstance(mid, int) or isinstance(mid, bool) for mid in memory_ids)):
            raise ValueError("MEMORY_PROVENANCE_INVALID: memory_ids")
        if kind is not None and kind not in {"episodic", "semantic", "procedural"}:
            raise ValueError("MEMORY_KIND_INVALID")
        if session_id is not None:
            session_id = str(UUID(session_id))
        point = timestamp(as_of)
        if time_window is not None and (not isinstance(time_window, dict) or not time_window or not set(time_window) <= {"start", "end"}):
            raise ValueError("MEMORY_PROVENANCE_INVALID: time_window")
        lower, upper = (timestamp((time_window or {}).get(key)) for key in ("start", "end"))
        if lower and upper and lower > upper:
            raise ValueError("MEMORY_PROVENANCE_INVALID: time_window")
        scope_ids = []
        mode = "by_id" if memory_ids is not None else "semantic" if query and not any((kind, session_id, agent_id, time_window)) else "hybrid" if query else "filtered" if any((kind, session_id, agent_id, time_window)) else "timeline"
        request_id = str(uuid4())
        failed_paths = []
        try:
            # Reserve time for cancellation, transaction cleanup and the audit.
            async with asyncio.timeout_at(started + 2.75):
                scope_ids = await MemoryScopeResolver(self.session).resolve_many(scope_ref)
                rows, salience, manifests, failed_paths = await self._views(scope_ids, memory_ids=memory_ids)
                now = datetime.now(timezone.utc)
                eligible = {}
                inactive = 0
                for mid, row in rows.items():
                    if not memory_visible(row, point=point, now=now, include_superseded=include_superseded):
                        inactive += 1
                        continue
                    if any(value is not None and row.get(key) != value for key, value in (("kind", kind), ("session_id", session_id), ("agent_id", agent_id))):
                        continue
                    observed = timestamp(row["observed_at"])
                    if lower and observed < lower or upper and observed > upper:
                        continue
                    eligible[mid] = row
                delivered = set()
                if session_id and not include_delivered:
                    deliveries = (await self.session.execute(select(MemoryRecallRun.returned_ids).where(
                        MemoryRecallRun.session_id == session_id, MemoryRecallRun.expires_at > now))).scalars().all()
                    delivered = {mid for ids in deliveries for mid in ids}
                dropped = len(set(eligible) & delivered)
                eligible = {mid: row for mid, row in eligible.items() if mid not in delivered}
                ordered = sorted(eligible, key=lambda mid: (eligible[mid]["observed_at"], mid), reverse=True)
                matches = {}
                candidate_count = len(rows)
                if memory_ids is not None:
                    ordered = [mid for mid in dict.fromkeys(memory_ids) if mid in eligible]
                    candidate_count = len(set(memory_ids))
                elif query:
                    try:
                        scores, dense_failures, failed_scopes = await asyncio.wait_for(self._dense(manifests, query, limit, kind, session_id),
                            timeout=max(.001, 2.5 - (monotonic() - started)))
                    except (TimeoutError, OSError):
                        scores, dense_failures, failed_scopes = {}, ["dense_unavailable"], scope_ids
                    failed_paths = sorted(set(failed_paths + dense_failures))
                    eligible = {mid: row for mid, row in eligible.items()
                                if mid in scores or row["knowledge_scope_id"] in failed_scopes}
                    candidate_count = len(scores)
                    dense = sorted((mid for mid in scores if mid in eligible), key=lambda mid: (-scores[mid], mid))
                    recency = [mid for mid in ordered if mid in eligible]
                    kinds = sorted(eligible, key=lambda mid: ({"procedural": 0, "semantic": 1, "episodic": 2}[eligible[mid]["kind"]], mid))
                    policies = {}
                    for sid in scope_ids:
                        scope = await self.session.get(KnowledgeScope, sid)
                        profile = await self.session.get(DomainProfile, scope.domain_key)
                        policies[sid] = profile.memory_policy or {}
                    signals = {}
                    for mid in eligible:
                        state = salience.get(mid, {})
                        beta = policies[eligible[mid]["knowledge_scope_id"]].get("decay_rate", .05)
                        last = timestamp(state.get("last_access_at"))
                        if beta > 0 and last is not None:
                            signal = SalienceService().rank_signal(state.get("salience", 0.),
                                decay_rate=beta, age_days=(now - last).total_seconds() / 86400)
                            if signal > 0:
                                signals[mid] = signal
                    paths = {"dense": dense, "recency": recency, "kind": kinds}
                    if signals:
                        paths["salience"] = sorted(signals, key=lambda mid: (-signals[mid], mid))
                    # Use each candidate's resolved domain policy, never trust/confidence.
                    fused = {}
                    for sid in scope_ids:
                        weights = {**WEIGHTS, **policies[sid].get("rrf_weights", {})}
                        for item in weighted_memory_rrf(paths, weights):
                            mid = item["memory_id"]
                            if eligible[mid]["knowledge_scope_id"] == sid:
                                fused[mid] = item["score"]
                    ordered = sorted(fused, key=lambda mid: (-fused[mid], mid))
                    matches = {mid: {"dense_similarity": scores.get(mid), "recency_rank": recency.index(mid) + 1,
                        "kind_rank": kinds.index(mid) + 1, "salience": signals.get(mid), "fused_score": fused[mid]} for mid in ordered}
                memories, characters, trimmed = [], 0, 0
                for mid in ordered[:limit]:
                    item = public_entry(eligible[mid], match=matches.get(mid))
                    length = text_characters(item)
                    if characters + length > 6000:
                        trimmed += 1
                        continue
                    characters += length
                    memories.append(item)
                completion = "partial" if failed_paths or trimmed else "complete" if memories else "no_evidence"
                result = {"completion_status": completion, "memories": memories,
                    "counts": {"mode": mode, "returned": len(memories), "candidates": candidate_count,
                               "truncated_by_budget": trimmed, "dropped_delivered": dropped,
                               "filtered_inactive": inactive, "characters": characters}, "request_id": request_id}
                if failed_paths or trimmed:
                    result["memory_notice"] = {"failed_paths": failed_paths, "untrusted": True}
                if not memories:
                    result["gaps"] = [{"description": "No eligible memory matched the explicit request.",
                                       "suggested_action": "Verify filters or explicitly request include_delivered."}]
                result["counts"]["characters"] = 0
                while serialized_characters(result) > 6000 and memories:
                    memories.pop()
                    trimmed += 1
                    result["completion_status"] = "partial"
                    result["counts"].update(returned=len(memories), truncated_by_budget=trimmed)
                    result["memory_notice"] = {"failed_paths": failed_paths, "untrusted": True}
                    if not memories:
                        result["gaps"] = [{"description": "No eligible memory matched the explicit request.",
                                           "suggested_action": "Verify filters or explicitly request include_delivered."}]
                result["counts"]["characters"] = serialized_characters(result)
        except TimeoutError:
            failed_paths = ["recall_timeout"]
            result = {"completion_status": "failed", "memories": [], "counts": {"mode": mode, "returned": 0},
                      "error": {"code": "MEMORY_TIMEOUT"}, "memory_notice": {"failed_paths": failed_paths}, "request_id": request_id}
        try:
            async with asyncio.timeout_at(started + 2.98):
                if result["completion_status"] == "failed":
                    await self.session.rollback()
                    await self.session.execute(text("SET LOCAL ROLE rag_memory_reader"))
                self.session.add(MemoryRecallRun(request_id=request_id, tool="recall_memory", mode=mode,
                    scope_ids=scope_ids, session_id=session_id, returned_ids=[row["memory_id"] for row in result["memories"]],
                    returned_count=len(result["memories"]), degraded=bool(failed_paths), failed_paths=failed_paths,
                    latency_ms=(monotonic() - started) * 1000))
                await self.session.commit()
        except TimeoutError:
            failed_paths = sorted(set(failed_paths + ["recall_timeout", "audit_unavailable"]))
            result = {"completion_status": "failed", "memories": [], "counts": {"mode": mode, "returned": 0},
                      "error": {"code": "MEMORY_TIMEOUT"}, "memory_notice": {"failed_paths": failed_paths}, "request_id": request_id}
            try:
                async with asyncio.timeout_at(started + 3):
                    await self.session.rollback()
            except TimeoutError:
                pass
        return result

    async def consolidation_candidates(self, *, scope_ref):
        """Deterministic candidate window only; proposal/adjudication belongs to 013."""
        scope_ids = await MemoryScopeResolver(self.session).resolve_many(scope_ref)
        rows, _, _, failed_paths = await self._views(scope_ids)
        if failed_paths:
            raise ValueError("MEMORY_WRITE_UNAVAILABLE: incomplete consolidation window")
        enabled = set()
        for sid in scope_ids:
            scope = await self.session.get(KnowledgeScope, sid)
            profile = await self.session.get(DomainProfile, scope.domain_key)
            if (profile.memory_policy or {}).get("consolidation_enabled", False):
                enabled.add(sid)
        now = datetime.now(timezone.utc)
        candidates = [row for row in rows.values() if row["knowledge_scope_id"] in enabled
                      and memory_visible(row, point=None, now=now)]
        return sorted(candidates, key=lambda row: (row["observed_at"], row["memory_id"]), reverse=True)

    async def start_work(self, *, scope_ref, session_id=None, task_hint=None, agent_id=None, include="both", budget="standard"):
        if include != "both" or budget not in {"standard", "compact", "minimal"}:
            raise ValueError("MEMORY_PROVENANCE_INVALID: package options")
        if session_id is not None:
            UUID(session_id)
        async with asyncio.timeout(2):
            sid = await MemoryScopeResolver(self.session).resolve(scope_ref)
            scope = await self.session.get(KnowledgeScope, sid)
            profile = await self.session.get(DomainProfile, scope.domain_key)
            rows, _, _, failed_paths = await self._views([sid])
            active = [row for row in rows.values() if stable_package_visible(row)]
            active.sort(key=lambda row: (row["observed_at"], row["memory_id"]), reverse=True)
            digest_rows = [row for row in active if row["kind"] in {"semantic", "procedural"}]
            work_rows = [row for row in active if row["kind"] == "episodic" and
                         (session_id is None or row.get("session_id") == session_id) and
                         (agent_id is None or row.get("agent_id") == agent_id)]
            maximum = {"standard": 2000, "compact": 800, "minimal": 300}[budget]
            policy_budget = (profile.memory_policy or {}).get("start_work_budgets", {}).get(
                "full" if budget == "standard" else budget, maximum)
            if isinstance(policy_budget, bool) or not isinstance(policy_budget, int) or policy_budget < 250:
                raise ValueError("MEMORY_PROVENANCE_INVALID: start_work_budgets")
            total = min(maximum, policy_budget)
            description = (profile.description or "")[:max(0, total - len(READ_GUIDANCE)) // 4]
            scope_data = {"knowledge_scope_id": sid, "slug": scope.slug}
            brief = {"domain_key": scope.domain_key, "description": description,
                     "policy_fingerprint": hashlib.sha256(canonical(profile.memory_policy or {}).encode()).hexdigest()}
            overhead = 64 + text_characters(failed_paths)
            base_size = overhead + len(READ_GUIDANCE) + text_characters(scope_data) + text_characters(brief)
            if base_size > total:
                brief["description"] = ""
                scope_data = {"knowledge_scope_id": sid}
                base_size = overhead + len(READ_GUIDANCE) + text_characters(scope_data) + text_characters(brief)
            if base_size > total:
                brief.pop("domain_key")
                base_size = overhead + len(READ_GUIDANCE) + text_characters(brief)
            remaining = total - base_size
            digest, working_set, used = [], [], base_size
            for candidates, target in ((digest_rows, digest), (work_rows, working_set)):
                for row in candidates:
                    if remaining <= 0:
                        break
                    item = {"memory_id": row["memory_id"], "kind": row["kind"], "provenance": row["provenance"],
                            "evidence_refs": row.get("evidence_refs", []), "inference_meta": row.get("inference_meta")}
                    metadata_size = text_characters(item)
                    if metadata_size >= remaining:
                        continue
                    excerpt = row["content_text"][:min(300, remaining - metadata_size)]
                    target.append({**item, "content_excerpt": excerpt, "truncated": len(excerpt) < len(row["content_text"])})
                    remaining -= metadata_size + len(excerpt)
                    used += metadata_size + len(excerpt)
            body = {"scope": scope_data,
                "domain_brief": brief,
                "digest": {"memories": digest}, "working_set": {"memories": working_set}, "read_guidance": READ_GUIDANCE,
                "counts": {"returned": len(digest) + len(working_set), "characters": used,
                           "failed_paths": failed_paths,
                           "truncated_by_budget": len(digest_rows) + len(work_rows) - len(digest) - len(working_set)}}
            body["package_fingerprint"] = "0" * 64
            body["counts"]["characters"] = 0
            def package_size():
                return serialized_characters(body)
            while package_size() > total and (digest or working_set):
                target = working_set if working_set else digest
                target.pop()
                body["counts"]["returned"] = len(digest) + len(working_set)
                body["counts"]["truncated_by_budget"] += 1
            # Failure labels are useful diagnostics, but they are optional
            # package metadata. Trim them before dropping the required counts
            # envelope when a domain policy selects the 250-character floor.
            while package_size() > total and body["counts"].get("failed_paths"):
                body["counts"]["failed_paths"].pop()
            if package_size() > total:
                body["scope"] = {}
                body["domain_brief"] = {}
            if package_size() > total:
                body["counts"].pop("failed_paths", None)
                body["counts"].pop("truncated_by_budget", None)
                body["counts"].pop("returned", None)
            if package_size() > total:
                raise ValueError("MEMORY_PROVENANCE_INVALID: start_work budget cannot fit required envelope")
            body["counts"]["characters"] = serialized_characters(body)
            body["package_fingerprint"] = hashlib.sha256(canonical({key: value for key, value in body.items()
                                                                   if key != "package_fingerprint"}).encode()).hexdigest()
            await self.session.commit()
            return {**body, "request_id": str(uuid4())}
