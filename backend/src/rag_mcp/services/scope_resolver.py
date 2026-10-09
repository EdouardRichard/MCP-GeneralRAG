"""Memory addressing reuses the established domain reference resolver."""
from sqlalchemy import select

from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.scope_binding import ScopeBinding
from rag_mcp.services.retrieval_service import RetrievalService
from rag_mcp.services.scope_binding_service import ScopeBindingError, ScopeBindingService

# FR-061/FR-018: a rejected scope reference must tell the caller which domains
# exist, otherwise "rejected" is indistinguishable from "your domain is unknown
# and there is no way to find out". Bounded so the error stays small.
MAX_SCOPE_CANDIDATES = 10


async def scope_candidates(session, limit=MAX_SCOPE_CANDIDATES):
    """The active domains a caller could have meant, ordered deterministically."""
    rows = (
        await session.execute(
            select(KnowledgeScope)
            .where(KnowledgeScope.status == "active")
            .order_by(KnowledgeScope.scope_id)
            .limit(limit)
        )
    ).scalars().all()
    return [RetrievalService._domain_candidate(scope) for scope in rows]


async def missing_scope_error(session):
    """MISSING_KNOWLEDGE_SCOPE carrying the candidate domains (FR-061/FR-018).

    Only AMBIGUOUS_DOMAIN_REF used to carry candidates; a missing or empty
    reference was rejected with an empty candidate list, which made the rejection
    unactionable. Every write and read surface that rejects for a missing scope
    raises through here so the candidates travel with the error.

    A falsy session means there is no domain store to enumerate (the 012 contract
    pins the blank-reference rejection as a pre-database validation), so the error
    is raised without candidates instead of failing on a missing session.
    """
    if session is None:
        return ScopeBindingError("MISSING_KNOWLEDGE_SCOPE")
    return ScopeBindingError("MISSING_KNOWLEDGE_SCOPE", await scope_candidates(session))


class MemoryScopeResolver:
    def __init__(self, session):
        self.session = session

    async def _missing_scope_error(self):
        return await missing_scope_error(self.session)

    async def resolve(self, reference):
        if not isinstance(reference, str) or not reference.strip():
            raise await self._missing_scope_error()
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
            raise await self._missing_scope_error()
        scope = await self.session.get(KnowledgeScope, resolved)
        if not scope or scope.status != "active":
            raise await self._missing_scope_error()
        return resolved

    async def resolve_many(self, references):
        if not isinstance(references, list) or not references:
            raise await self._missing_scope_error()
        return sorted({await self.resolve(reference) for reference in references})
