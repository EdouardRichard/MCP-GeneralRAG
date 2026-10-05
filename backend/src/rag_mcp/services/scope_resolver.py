"""Memory addressing reuses the established domain reference resolver."""
from sqlalchemy import select

from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.scope_binding import ScopeBinding
from rag_mcp.services.retrieval_service import RetrievalService
from rag_mcp.services.scope_binding_service import ScopeBindingError, ScopeBindingService


class MemoryScopeResolver:
    def __init__(self, session):
        self.session = session

    async def resolve(self, reference):
        if not isinstance(reference, str) or not reference.strip():
            raise ScopeBindingError("MISSING_KNOWLEDGE_SCOPE")
        reference = reference.strip()
        if reference.startswith("path:"):
            rows = (await self.session.execute(select(ScopeBinding).where(ScopeBinding.status == "active"))).scalars().all()
            bindings = [{column.name: getattr(row, column.name) for column in ScopeBinding.__table__.columns} for row in rows]
            resolved = ScopeBindingService(bindings).resolve(reference).scope_id
        else:
            service = RetrievalService(self.session, None, None)
            resolved = await service._resolve_domain_scope_entry(reference)
            if isinstance(resolved, list):
                raise ScopeBindingError("AMBIGUOUS_DOMAIN_REF", resolved)
        if not resolved:
            raise ScopeBindingError("MISSING_KNOWLEDGE_SCOPE")
        scope = await self.session.get(KnowledgeScope, resolved)
        if not scope or scope.status != "active":
            raise ScopeBindingError("MISSING_KNOWLEDGE_SCOPE")
        return resolved

    async def resolve_many(self, references):
        if not isinstance(references, list) or not references:
            raise ScopeBindingError("MISSING_KNOWLEDGE_SCOPE")
        return sorted({await self.resolve(reference) for reference in references})
