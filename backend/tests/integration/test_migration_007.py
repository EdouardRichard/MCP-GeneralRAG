"""Integration test for the 007 migrations (T002).

FR-002/FR-004: after migration, domain_profiles holds the two builtin rows
(se-project/generic, is_builtin=true), and every knowledge_scope gained a
domain_key='se-project' plus a globally-unique slug.
"""
from __future__ import annotations

from sqlalchemy import text

import pytest


@pytest.mark.asyncio
async def test_domain_profiles_has_two_builtin_rows(db_session):
    rows = (await db_session.execute(
        text("SELECT domain_key, is_builtin FROM domain_profiles ORDER BY domain_key")
    )).fetchall()
    keys = {r[0] for r in rows}
    assert keys == {"se-project", "generic"}
    assert all(r[1] for r in rows)


@pytest.mark.asyncio
async def test_se_project_profile_content(db_session):
    row = (await db_session.execute(
        text("SELECT supported_formats, graph_relations FROM domain_profiles WHERE domain_key = 'se-project'")
    )).fetchone()
    assert row is not None
    assert sorted(row[0]) == sorted([
        "markdown", "java", "openapi", "ddl", "go", "python", "word", "pdf",
    ])
    assert set(row[1].keys()) == {"calls", "called_by", "fk_references", "fk_referenced_by"}


@pytest.mark.asyncio
async def test_generic_profile_empty_graph(db_session):
    row = (await db_session.execute(
        text("SELECT graph_relations FROM domain_profiles WHERE domain_key = 'generic'")
    )).fetchone()
    assert row is not None
    assert row[0] == {}


@pytest.mark.asyncio
async def test_knowledge_scopes_backfilled(db_session):
    total = (await db_session.execute(text("SELECT count(*) FROM knowledge_scopes"))).scalar_one()
    wrong_domain = (await db_session.execute(
        text("SELECT count(*) FROM knowledge_scopes WHERE domain_key != 'se-project' OR domain_key IS NULL")
    )).scalar_one()
    assert wrong_domain == 0
    assert total >= 0


@pytest.mark.asyncio
async def test_knowledge_scopes_slug_unique(db_session):
    dupes = (await db_session.execute(
        text("SELECT count(*) FROM (SELECT slug FROM knowledge_scopes GROUP BY slug HAVING count(*) > 1) t")
    )).scalar_one()
    assert dupes == 0
    empty = (await db_session.execute(
        text("SELECT count(*) FROM knowledge_scopes WHERE slug IS NULL OR slug = ''")
    )).scalar_one()
    assert empty == 0
