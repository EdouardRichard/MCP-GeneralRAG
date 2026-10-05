"""Memory management lives exclusively on the writer management application."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_mcp.config import get_settings
from rag_mcp.db import get_session
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.models.runtime import WriterLease
from rag_mcp.models.scope_binding import ScopeBinding
from rag_mcp.services.memory_reader import public_entry
from rag_mcp.services.memory_service import MemoryService
from rag_mcp.services.scope_resolver import MemoryScopeResolver

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
    rows = (await session.execute(select(MemoryEntry).where(MemoryEntry.knowledge_scope_id == sid)
        .order_by(MemoryEntry.observed_at.desc(), MemoryEntry.memory_id.desc()).offset(offset).limit(limit))).scalars().all()
    total = await session.scalar(select(func.count()).select_from(MemoryEntry).where(MemoryEntry.knowledge_scope_id == sid))
    memories = []
    for row in rows:
        data = {column.name: (getattr(row, column.name).isoformat() if isinstance(getattr(row, column.name), datetime)
                             else getattr(row, column.name)) for column in MemoryEntry.__table__.columns}
        item = public_entry(data)
        for key in ("memory_id", "knowledge_scope_id", "superseded_by"):
            if item.get(key) is not None:
                item[key] = str(item[key])
        item.update(injection_flags=row.injection_flags, projection_status=row.write_status)
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
async def rebuild_memory(data: ScopeCommand, session: AsyncSession = Depends(get_session)):
    try:
        return {"scope_id": data.scope_id, "projections": await _service(session).rebuild(data.scope_id, actor="management")}
    except (ValueError, PermissionError) as exception:
        raise _http_error(exception) from None
