"""Memory management lives exclusively on the writer management application."""
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, cast, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from rag_mcp.config import get_settings
from rag_mcp.db import get_session
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
from rag_mcp.models.memory_management_audit import MemoryManagementAudit
from rag_mcp.models.runtime import WriterLease
from rag_mcp.models.scope_binding import ScopeBinding
from rag_mcp.services.memory_reader import public_entry
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.services.scope_resolver import MemoryScopeResolver
from rag_mcp.services.memory_policy import MemoryPolicy

router = APIRouter(prefix="/api/memories", tags=["memories"])
_embedding_provider = None


def management_action(action, *, actor):
    return {"authorized": actor == "management", "action": action}


async def require_writer(request: Request, session: AsyncSession = Depends(get_session)):
    lease = getattr(request.app.state, "writer_lease", None)
    if get_settings().instance_mode != "writer" or lease is None:
        raise HTTPException(503, detail={"code": "MEMORY_WRITE_UNAVAILABLE"})
    active = await session.scalar(select(WriterLease.lease_id).where(
        WriterLease.lease_id == lease.lease_id, WriterLease.holder_instance_id == lease.holder_instance_id,
        WriterLease.state == "active", WriterLease.expires_at > func.now()).with_for_update(read=True))
    if active is None:
        raise HTTPException(503, detail={"code": "MEMORY_WRITE_UNAVAILABLE"})


def _service(session):
    global _embedding_provider
    if _embedding_provider is None:
        from rag_mcp.providers.factory import assemble_or_fail
        _embedding_provider = assemble_or_fail(get_settings()).embedding
    return MemoryService(session, embedding_provider=_embedding_provider)


def _http_error(exception):
    from rag_mcp.mcp.serialization import memory_error
    body = memory_error(exception).structuredContent["error"]
    return HTTPException(403 if isinstance(exception, PermissionError) else 400, detail=body)


class ScopeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=4000)


class MemoryCommand(ScopeCommand):
    memory_id: int = Field(gt=0)


class RebuildCommand(ScopeCommand):
    since_event_id: int | None = Field(default=None, gt=0)


class PolicyCommand(ScopeCommand):
    policy: MemoryPolicy


class RollbackCommand(ScopeCommand):
    event_point: int | None = None
    time_point: datetime | None = None


class BindingCommand(ScopeCommand):
    binding_id: int | None = None
    binding_kind: Literal["workdir_prefix", "git_remote", "dir_name"]
    binding_value: str = Field(min_length=1, max_length=1024)
    priority: int = 0
    status: Literal["active", "disabled"] = "active"


@router.get("/scopes")
async def list_memory_scopes(session: AsyncSession = Depends(get_session)):
    scopes = (await session.execute(select(KnowledgeScope).where(KnowledgeScope.status == "active")
                                   .order_by(KnowledgeScope.name, KnowledgeScope.scope_id))).scalars().all()
    return {"items": [{"scope_id": str(scope.scope_id), "name": scope.name, "slug": scope.slug,
                       "domain_key": scope.domain_key} for scope in scopes]}


@router.get("")
async def browse_memories(scope_ref: str = Query(min_length=1), limit: int = Query(default=50, ge=1, le=100),
                          offset: int = Query(default=0, ge=0), session: AsyncSession = Depends(get_session)):
    try:
        sid = await MemoryScopeResolver(session).resolve(scope_ref)
    except ValueError as exception:
        raise _http_error(exception) from None
    entries = func.jsonb_each(MemoryProjectionMeta.payload["state"]["entries"]).table_valued("key", "value").lateral()
    data = cast(entries.c.value, JSONB)
    conditions = (MemoryProjectionMeta.knowledge_scope_id == sid, MemoryProjectionMeta.projection_type == "manifest",
                  MemoryProjectionMeta.status == "complete", MemoryProjectionMeta.payload["verification_version"].as_integer() == 1)
    rows = (await session.execute(select(data).select_from(MemoryProjectionMeta).join(entries, true()).where(*conditions)
        .order_by(data["observed_at"].as_string().desc(), cast(data["memory_id"].as_string(), BigInteger).desc())
        .offset(offset).limit(limit))).scalars().all()
    total = await session.scalar(select(func.count()).select_from(MemoryProjectionMeta).join(entries, true()).where(*conditions))
    memories = []
    for row in rows:
        item = public_entry(row)
        for key in ("memory_id", "knowledge_scope_id", "superseded_by"):
            if item.get(key) is not None:
                item[key] = str(item[key])
        item.update(injection_flags=row.get("injection_flags", []), projection_status="complete")
        memories.append(item)
    return {"memories": memories, "total": total, "scope_id": str(sid)}


@router.get("/bindings")
async def browse_bindings(scope_ref: str = Query(min_length=1), session: AsyncSession = Depends(get_session)):
    try:
        sid = await MemoryScopeResolver(session).resolve(scope_ref)
        rows = (await session.execute(select(ScopeBinding).where(ScopeBinding.knowledge_scope_id == sid))).scalars().all()
        return {"items": [{"binding_id": str(row.binding_id), "knowledge_scope_id": str(sid),
            "binding_kind": row.binding_kind, "binding_value": row.binding_value,
            "priority": row.priority, "status": row.status} for row in rows]}
    except ValueError as exception:
        raise _http_error(exception) from None


@router.get("/policy")
async def browse_policy(scope_ref: str = Query(min_length=1), session: AsyncSession = Depends(get_session)):
    try:
        sid = await MemoryScopeResolver(session).resolve(scope_ref)
        scope = await session.get(KnowledgeScope, sid)
        profile = await session.get(DomainProfile, scope.domain_key)
        return {"scope_id": str(sid), "domain_key": scope.domain_key, "policy": profile.memory_policy}
    except ValueError as exception:
        raise _http_error(exception) from None


@router.post("/policy", dependencies=[Depends(require_writer)])
async def update_policy(data: PolicyCommand, session: AsyncSession = Depends(get_session)):
    try:
        return await _service(session).govern("policy", actor="management", scope_id=data.scope_id,
            reason=data.reason, policy=data.policy.model_dump(exclude_unset=True))
    except (ValueError, PermissionError) as exception:
        raise _http_error(exception) from None


async def _command(action, data, session):
    try:
        return await _service(session).govern(action, actor="management", **data.model_dump())
    except (ValueError, PermissionError) as exception:
        raise _http_error(exception) from None


@router.post("/retire", dependencies=[Depends(require_writer)])
async def retire_memory(data: MemoryCommand, session: AsyncSession = Depends(get_session)):
    return await _command("retire", data, session)


@router.post("/purge", dependencies=[Depends(require_writer)])
async def purge_memory(data: MemoryCommand, session: AsyncSession = Depends(get_session)):
    return await _command("purge", data, session)


@router.post("/usage", dependencies=[Depends(require_writer)])
async def record_usage(data: MemoryCommand, session: AsyncSession = Depends(get_session)):
    return await _command("access", data, session)


@router.post("/rollback", dependencies=[Depends(require_writer)])
async def rollback_memory(data: RollbackCommand, session: AsyncSession = Depends(get_session)):
    return await _command("rollback", data, session)


@router.post("/bindings", dependencies=[Depends(require_writer)])
async def grant_binding(data: BindingCommand, session: AsyncSession = Depends(get_session)):
    return await _command("binding", data, session)


@router.post("/rebuild", dependencies=[Depends(require_writer)])
async def rebuild_memory(data: RebuildCommand, session: AsyncSession = Depends(get_session)):
    try:
        request_id = str(uuid4())
        return {"scope_id": data.scope_id, "request_id": request_id, "projections": await _service(session).rebuild(
            data.scope_id, actor="management", reason=data.reason, since_event_id=data.since_event_id,
            request_id=request_id)}
    except (ValueError, PermissionError) as exception:
        raise _http_error(exception) from None


@router.get("/rebuild/audit")
async def rebuild_audit(request_id: str = Query(min_length=1, max_length=128),
                       scope_id: int | None = Query(default=None, gt=0),
                       session: AsyncSession = Depends(get_session)):
    audit = await session.get(MemoryManagementAudit, request_id)
    if audit is None or (scope_id is not None and audit.knowledge_scope_id != scope_id):
        raise HTTPException(404, detail={"code": "MEMORY_AUDIT_NOT_FOUND"})
    return {"request_id": audit.request_id, "operation": audit.operation, "actor": audit.actor,
            "scope_id": audit.knowledge_scope_id, "reason": audit.reason,
            "source_event_id": audit.source_event_id, "since_event_id": audit.since_event_id,
            "result": audit.result, "created_at": audit.created_at.isoformat()}
