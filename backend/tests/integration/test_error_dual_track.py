"""Integration test for dual-track error codes (007, T027).

FR-010/SC-010: project_scope-only requests keep legacy codes; requests
involving domain_scope emit the new codes (MISSING_KNOWLEDGE_SCOPE /
AMBIGUOUS_DOMAIN_REF).
"""
from __future__ import annotations

import pytest

from rag_mcp.mcp.search_knowledge import search_knowledge_core


@pytest.mark.asyncio
async def test_entry_both_empty_legacy_code():
    r = await search_knowledge_core(
        query="x", project_scope=[], domain_scope=[], top_k=5, task_context=None,
        session_factory=None, qdrant_store=None, embedding_provider=None,
    )
    assert r["error"]["code"] == "MISSING_PROJECT_SCOPE"


@pytest.mark.asyncio
async def test_entry_domain_scope_present_passes_validation(db_session):
    # domain_scope non-empty passes entry validation; resolver then rejects the
    # unresolvable slug with the new code (needs a real session factory).
    import asyncio
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def sf():
        yield db_session

    r = await search_knowledge_core(
        query="x", project_scope=[], domain_scope=["no-such-slug-zzz"], top_k=5, task_context=None,
        session_factory=sf, qdrant_store=None, embedding_provider=None,
    )
    assert r["error"]["code"] == "MISSING_KNOWLEDGE_SCOPE"
