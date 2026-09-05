"""Integration test: scope slug allocation + immutability (007, T036).

FR-012/SC-011: explicit slug is stored; duplicate slug creation is rejected by
the global unique constraint; slug is create-only (no update path).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.schemas.project import ProjectCreate
from rag_mcp.services.project_service import ProjectService
from rag_mcp.utils.snowflake import generate_id


@pytest.mark.asyncio
async def test_explicit_slug_stored(db_session):
    svc = ProjectService(db_session)
    slug = "my-domain-" + str(generate_id())[-6:]
    proj = await svc.create_project(ProjectCreate(name="Slug Project", slug=slug))
    await db_session.commit()
    scope = (await db_session.execute(
        select(KnowledgeScope).where(KnowledgeScope.scope_id == proj.knowledge_scope_id)
    )).scalar_one()
    assert scope.slug == slug
    assert scope.domain_key == "se-project"


@pytest.mark.asyncio
async def test_duplicate_slug_rejected(db_session):
    svc = ProjectService(db_session)
    slug = "dup-slug-" + str(generate_id())[-6:]
    await svc.create_project(ProjectCreate(name="First", slug=slug))
    await db_session.commit()
    # second scope with same slug violates the unique constraint
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        await svc.create_project(ProjectCreate(name="Second", slug=slug))
        await db_session.commit()
