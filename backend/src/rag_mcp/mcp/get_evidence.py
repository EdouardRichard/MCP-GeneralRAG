"""MCP tool definition for get_evidence.

Registers the evidence expansion tool with the MCP server. Accepts an
evidence_id (from search_knowledge results) and explicit knowledge scopes
(project_scope and/or domain_scope, at least one non-empty; 007 T031),
delegates to EvidenceService, and returns full chunk content with parent
context.

Conforms to mcp-get-evidence.schema.json input/output structure.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from rag_mcp.services.evidence_service import EvidenceService

logger = logging.getLogger(__name__)


def register_get_evidence_tool(
    mcp_server: FastMCP,
    session_factory: Any,
) -> None:
    """Register the get_evidence tool on the MCP server.

    Args:
        mcp_server: The FastMCP server instance.
        session_factory: Callable that returns an AsyncSession.
    """

    @mcp_server.tool(
        name="get_evidence",
        description=(
            "Retrieve the full content of a specific evidence item by its ID. "
            "Use this after search_knowledge to expand an evidence excerpt into "
            "its complete text, including parent context when available. "
            "Requires an explicit knowledge scope: at least one of project_scope "
            "or domain_scope must be non-empty — the requested scopes must "
            "include the knowledge domain that owns this evidence."
        ),
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_evidence(
        evidence_id: str,
        project_scope: list[str] | None = None,
        domain_scope: list[str] | None = None,
    ) -> dict[str, Any]:
        """Retrieve full evidence content by evidence_id.

        Args:
            evidence_id: The evidence ID string from search_knowledge results.
            project_scope: List of project references (stable ID, alias, or repo
                path). Legacy compatible scope form; without domain_scope, at
                least one entry is required.
            domain_scope: List of knowledge-domain references (numeric
                knowledge_scope_id, scope slug, or type:name). New scope form;
                without project_scope, at least one entry is required. The
                resolved scopes must include the domain owning this evidence.

        Returns:
            Structured response with full_content, parent_context (if available),
            source metadata, and status indicating availability.
        """
        # Validate inputs
        if not evidence_id or not evidence_id.strip():
            return {
                "evidence_id": evidence_id or "",
                "status": "unavailable",
                "error": {
                    "code": "INVALID_EVIDENCE_ID",
                    "message": "Evidence ID must not be empty.",
                },
            }

        project_scope = project_scope or []
        domain_scope = domain_scope or []
        if not any((r or "").strip() for r in project_scope) and not any((r or "").strip() for r in domain_scope):
            code = "MISSING_KNOWLEDGE_SCOPE" if any((r or "").strip() for r in domain_scope) else "MISSING_PROJECT_SCOPE"
            return {
                "evidence_id": evidence_id,
                "status": "unavailable",
                "error": {
                    "code": code,
                    "message": "At least one project_scope or domain_scope entry is required.",
                },
            }

        try:
            async with session_factory() as session:
                service = EvidenceService(session=session)
                result = await service.get_evidence(
                    evidence_id=evidence_id.strip(),
                    project_scopes=project_scope,
                    domain_scopes=domain_scope,
                )
                await session.commit()
                return result

        except Exception as exc:
            logger.error("get_evidence tool failed: %s", exc, exc_info=True)
            return {
                "evidence_id": evidence_id,
                "status": "unavailable",
                "error": {
                    "code": "SYSTEM_ERROR",
                    "message": f"Internal error: {type(exc).__name__}",
                },
            }
