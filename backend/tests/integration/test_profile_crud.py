"""Integration test: domain profile CRUD + builtin read-only (007, T035).

FR-005/SC-008: builtin profiles reject update/delete (field-level); custom
profiles support create/update/delete; deletion of a referenced profile is
rejected.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from rag_mcp.services.domain_profile_service import DomainProfileService
from rag_mcp.utils.snowflake import generate_id


def _key():
    return "legal-" + str(generate_id())[-8:]


@pytest.mark.asyncio
async def test_builtin_readonly(db_session):
    svc = DomainProfileService(db_session)
    with pytest.raises(ValueError):
        await svc.update_profile("se-project", {"name": "hacked"})
    with pytest.raises(ValueError):
        await svc.delete_profile("se-project")
    with pytest.raises(ValueError):
        await svc.update_profile("generic", {"name": "hacked"})


@pytest.mark.asyncio
async def test_custom_profile_crud(db_session):
    svc = DomainProfileService(db_session)
    key = _key()
    p = await svc.create_profile({
        "domain_key": key, "name": "Legal", "supported_formats": ["markdown"],
        "graph_relations": {}, "default_capabilities": {},
    })
    await db_session.commit()
    assert p.is_builtin is False
    await svc.update_profile(key, {"name": "Legal Renamed"})
    await db_session.commit()
    profiles = await svc.list_profiles()
    assert any(p.domain_key == key for p in profiles)
    assert await svc.delete_profile(key) is True
    await db_session.commit()


@pytest.mark.asyncio
async def test_delete_referenced_profile_rejected(db_session):
    svc = DomainProfileService(db_session)
    key = _key()
    await svc.create_profile({"domain_key": key, "name": "Ref", "supported_formats": ["markdown"],
        "graph_relations": {}, "default_capabilities": {}})
    # create a scope referencing it
    sid = generate_id()
    await db_session.execute(text(
        "INSERT INTO knowledge_scopes (scope_id, scope_type, name, slug, domain_key, status) "
        "VALUES (:sid, 'public', :name, :slug, :dk, 'active')"
    ), {"sid": sid, "name": "RefScope", "slug": "scope-" + str(sid), "dk": key})
    await db_session.commit()
    with pytest.raises(ValueError):
        await svc.delete_profile(key)
