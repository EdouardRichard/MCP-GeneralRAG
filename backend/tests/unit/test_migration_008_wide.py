"""Migration 0073 wide-mode tests (T021, US3).

Two layers verified separately (FR-018/FR-019/FR-021, quickstart S4):
  (a) DB wide-mode CHECK: the pattern allows xlsx format + legal:article
      chunk_type, rejects illegal values, and keeps the 18 legacy values valid.
  (b) Application-layer vocabulary: L2 namespace values are valid only when
      the scope's domain profile declares the namespace.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from rag_mcp.parsers.chunk_type_vocab import (
    L1_CHUNK_TYPES,
    LEGACY_CHUNK_TYPES,
    is_valid_chunk_type,
)

from tests.unit.test_migrations_helper import get_check_constraints, get_columns


async def _pattern_matches(session, pattern: str, value: str) -> bool:
    result = await session.execute(
        text("SELECT :v ~ :p"), {"v": value, "p": pattern}
    )
    return bool(result.scalar())


# ---------------------------------------------------------------------------
# (a) DB-level: widened columns + wide-mode CHECK
# ---------------------------------------------------------------------------

class TestDbWideColumns:
    @pytest.mark.asyncio
    async def test_format_columns_widened_to_32(self, db_session):
        ks = await get_columns(db_session, "knowledge_sources")
        assert ks["format"]["char_max_length"] == 32
        chunks = await get_columns(db_session, "chunks")
        assert chunks["chunk_type"]["char_max_length"] == 32
        rr = await get_columns(db_session, "retrieval_runs")
        assert rr["format"]["char_max_length"] == 32


class TestDbWidePattern:
    @pytest.mark.asyncio
    async def test_format_pattern_allows_new_formats(self, db_session):
        assert await _pattern_matches(db_session, "^[a-z][a-z0-9_]{0,31}$", "xlsx")
        assert await _pattern_matches(db_session, "^[a-z][a-z0-9_]{0,31}$", "pptx")
        assert await _pattern_matches(db_session, "^[a-z][a-z0-9_]{0,31}$", "eml")

    @pytest.mark.asyncio
    async def test_format_pattern_rejects_illegal(self, db_session):
        assert not await _pattern_matches(db_session, "^[a-z][a-z0-9_]{0,31}$", "Bad Format")
        assert not await _pattern_matches(db_session, "^[a-z][a-z0-9_]{0,31}$", "UPPER")

    @pytest.mark.asyncio
    async def test_chunk_type_pattern_allows_l2(self, db_session):
        assert await _pattern_matches(
            db_session,
            "^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$",
            "legal:article",
        )

    @pytest.mark.asyncio
    async def test_chunk_type_pattern_allows_legacy(self, db_session):
        for value in LEGACY_CHUNK_TYPES:
            assert await _pattern_matches(db_session, "^[a-z][a-z0-9_]{0,31}$", value), value

    @pytest.mark.asyncio
    async def test_chunk_type_pattern_rejects_illegal(self, db_session):
        assert not await _pattern_matches(db_session, "^[a-z][a-z0-9_]{0,31}$", "Bad Type!")

    @pytest.mark.asyncio
    async def test_knowledge_sources_check_is_wide(self, db_session):
        checks = " ".join(await get_check_constraints(db_session, "knowledge_sources"))
        assert "~" in checks
        assert "markdown" not in checks  # the enum is gone


class TestMigrationDowngrade:
    def test_downgrade_is_defined(self):
        import importlib.util
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[3]
            / "backend" / "alembic" / "versions"
            / "0073_expand_format_and_chunk_type_wide.py"
        )
        spec = importlib.util.spec_from_file_location(
            "migration_0073", str(path)
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod.downgrade)
        assert callable(mod.upgrade)
        assert mod.revision == "0073"
        assert mod.down_revision == "0072"


# ---------------------------------------------------------------------------
# (b) Application-layer vocabulary (FR-019/FR-020/FR-021)
# ---------------------------------------------------------------------------

class TestL1AndLegacyAlwaysValid:
    def test_l1_closed_set_valid_without_extensions(self):
        for value in L1_CHUNK_TYPES:
            assert is_valid_chunk_type(value, None), value

    def test_legacy_values_valid_without_extensions(self):
        for value in LEGACY_CHUNK_TYPES:
            assert is_valid_chunk_type(value, None), value


class TestL2RequiresDomainDeclaration:
    def test_l2_rejected_without_declaration(self):
        assert not is_valid_chunk_type("legal:article", None)
        assert not is_valid_chunk_type("legal:article", {})

    def test_l2_accepted_with_wildcard_declaration(self):
        assert is_valid_chunk_type("legal:article", {"legal": "*"})

    def test_l2_accepted_with_explicit_value_declaration(self):
        assert is_valid_chunk_type("legal:article", {"legal": ["article", "clause"]})

    def test_l2_rejected_with_other_namespace(self):
        assert not is_valid_chunk_type("legal:article", {"finance": "*"})

    def test_invalid_chunk_type_rejected(self):
        assert not is_valid_chunk_type("Not Valid!", None)
        assert not is_valid_chunk_type("UPPERCASE", None)
