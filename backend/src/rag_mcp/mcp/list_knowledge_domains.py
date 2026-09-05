"""MCP tool definition for list_knowledge_domains (007, T033).

Read-only tool that returns ACTIVE knowledge-domain metadata only (FR-014/
FR-015/FR-022). Capabilities are derived from domain_profiles declarations —
never from knowledge content (SC-006).
"""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from sqlalchemy import select

from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope


async def list_knowledge_domains_core(session_factory: Any) -> dict[str, Any]:
    """Return active-domain metadata (no knowledge content)."""
    async with session_factory() as session:
        result = await session.execute(
            select(KnowledgeScope)
            .where(KnowledgeScope.status == "active")
            .order_by(KnowledgeScope.scope_id)
        )
        scopes = list(result.scalars().all())

        profiles: dict[str, DomainProfile] = {}
        keys = {s.domain_key for s in scopes}
        if keys:
            presult = await session.execute(
                select(DomainProfile).where(DomainProfile.domain_key.in_(keys))
            )
            for p in presult.scalars().all():
                profiles[p.domain_key] = p

        domains: list[dict[str, Any]] = []
        for s in scopes:
            p = profiles.get(s.domain_key)
            supported_formats = list(p.supported_formats) if p is not None else []
            has_graph = bool(p.graph_relations) if p is not None else False
            domains.append({
                "id": str(s.scope_id),
                "slug": s.slug,
                "name": s.name,
                "scope_type": s.scope_type,
                "domain_key": s.domain_key,
                "capabilities": {
                    "supported_formats": supported_formats,
                    "has_graph": has_graph,
                },
            })
        return {"domains": domains}


def register_list_knowledge_domains_tool(
    mcp_server: FastMCP,
    session_factory: Any,
) -> None:
    """Register the list_knowledge_domains read-only tool."""

    @mcp_server.tool(
        name="list_knowledge_domains",
        description=(
            "List available active knowledge domains (metadata only). "
            "Returns each domain's id, slug, name, scope_type, domain_key and a "
            "capability summary (supported formats and whether graph retrieval is "
            "available). This tool never returns knowledge content (chunks, "
            "evidence, or source excerpts)."
        ),
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def list_knowledge_domains() -> dict[str, Any]:
        return await list_knowledge_domains_core(session_factory)
