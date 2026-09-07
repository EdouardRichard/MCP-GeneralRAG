"""011 domain-corpora ingestion integration tests (T007, VS-02).

Asserts the two evaluation domains' corpora are ingested, chunked, retrievable
and locatable through the existing 007-010 pipeline, plus the domain-profile
format gate (out-of-family formats rejected, VS-02).

Scope layout follows the system's one-file-per-scope version model (001/008
precedent): each corpus file lives in its own public scope (slug per file).
Fixtures are produced by eval/ingest_domain_corpora.py (T006, idempotent by
fixed slug); this module self-heals by invoking the runner when a scope is
missing (quickstart VS-02 note).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

_REPO_ROOT = Path(__file__).resolve().parents[3]
for p in (_REPO_ROOT / "eval", str(_REPO_ROOT)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rag_mcp.models.chunk import Chunk
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope

from ingest_domain_corpora import (  # noqa: E402
    SCOPE_SPECS,
    CorpusFormatError,
    ingest_domain_corpora,
    validate_formats_against_family,
)

_ALL_SLUGS = tuple(s["slug"] for s in SCOPE_SPECS)
_SLUG_BY_DOMAIN = {
    "personal": [s["slug"] for s in SCOPE_SPECS if s["domain_key"] == "personal"],
    "generic": [s["slug"] for s in SCOPE_SPECS if s["domain_key"] == "generic"],
    "legal": [s["slug"] for s in SCOPE_SPECS if s["domain_key"] == "legal"],
}


async def _scope_ids(session: AsyncSession) -> dict[str, tuple[int, str]]:
    rows = (await session.execute(
        sa_select(KnowledgeScope.scope_id, KnowledgeScope.slug, KnowledgeScope.domain_key)
        .where(KnowledgeScope.slug.in_(_ALL_SLUGS))
    )).all()
    return {r.slug: (int(r.scope_id), r.domain_key) for r in rows}


@pytest_asyncio.fixture(scope="function")
async def ingested_scopes():
    """Ensure the 16 per-file 011 scopes exist with published corpora.

    Idempotent: when every slug is present the runner is skipped entirely.
    Uses its own engine/session (a module-scoped async fixture cannot reuse
    the function-scoped engine/event_loop fixtures from conftest).
    """
    from rag_mcp.config import get_settings
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    own_engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(own_engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            found = await _scope_ids(session)

        missing = [s for s in _ALL_SLUGS if s not in found]
        if missing:
            rc = await ingest_domain_corpora(["personal", "generic", "legal"])
            assert rc == 0, "ingest_domain_corpora failed rc=" + str(rc)

        async with factory() as session:
            found = await _scope_ids(session)
        assert set(_ALL_SLUGS) <= set(found), "scopes still missing after ingest"
        return found
    finally:
        await own_engine.dispose()


async def _chunks(session: AsyncSession, scope_id: int) -> list[Chunk]:
    return list((await session.execute(
        sa_select(Chunk).where(Chunk.knowledge_scope_id == scope_id)
        .order_by(Chunk.chunk_id)
    )).scalars().all())


class TestScopesIngested:
    async def test_personal_four_formats_published(self, db_session, ingested_scopes):
        """VS-02/FR-002: personal domain spans 4 scopes covering the 4 formats."""
        for slug in _SLUG_BY_DOMAIN["personal"]:
            scope_id, domain_key = ingested_scopes[slug]
            assert domain_key == "personal"
            chunks = await _chunks(db_session, scope_id)
            assert chunks, f"no chunks in {slug}"

        # The four formats are covered across the personal scopes.
        files = {s["file"]: s["slug"] for s in SCOPE_SPECS
                 if s["domain_key"] == "personal"}
        assert any(f.endswith(".md") for f in files)
        assert any(f.endswith(".txt") for f in files)
        assert any(f.endswith(".csv") for f in files)
        assert any(f.endswith(".html") for f in files)

    async def test_generic_five_files_published(self, db_session, ingested_scopes):
        """FR-002: generic domain spans >=2 scopes (5 files)."""
        assert len(_SLUG_BY_DOMAIN["generic"]) == 5
        for slug in _SLUG_BY_DOMAIN["generic"]:
            scope_id, domain_key = ingested_scopes[slug]
            assert domain_key == "generic"
            chunks = await _chunks(db_session, scope_id)
            assert chunks, f"no chunks in {slug}"

    async def test_legal_word_pdf_markdown_published(self, db_session, ingested_scopes):
        """VS-02/FR-004: legal domain carries word/pdf + markdown cross-ref corpus."""
        formats_by_slug = {}
        for s in SCOPE_SPECS:
            if s["domain_key"] == "legal":
                formats_by_slug[s["slug"]] = s["file"].rsplit(".", 1)[-1]
        assert "docx" in formats_by_slug.values()
        assert "pdf" in formats_by_slug.values()
        assert "md" in formats_by_slug.values()
        for slug in _SLUG_BY_DOMAIN["legal"]:
            scope_id, domain_key = ingested_scopes[slug]
            assert domain_key == "legal"
            chunks = await _chunks(db_session, scope_id)
            assert chunks, f"no chunks in {slug}"


class TestLocatorPrefixes:
    async def test_csv_sheet_prefix(self, db_session, ingested_scopes):
        """csv chunks locate via sheet:<basename> (008 locator table)."""
        for slug in ("personal-eval-expenses", "generic-eval-reading-tracker"):
            scope_id, _ = ingested_scopes[slug]
            chunks = await _chunks(db_session, scope_id)
            csv_chunks = [c for c in chunks if c.position_path.startswith("sheet:")]
            assert csv_chunks, f"no sheet: chunks in {slug}"
            for c in csv_chunks:
                assert c.position_path.startswith("sheet:"), c.position_path

    async def test_markdown_html_heading_paths(self, db_session, ingested_scopes):
        """markdown/html chunks locate via '# heading' paths (converter IR)."""
        slugs = ("personal-eval-rag-notes", "personal-eval-bookmarks",
                 "generic-eval-meeting-notes")
        for slug in slugs:
            scope_id, _ = ingested_scopes[slug]
            chunks = await _chunks(db_session, scope_id)
            heading_chunks = [
                c for c in chunks
                if c.position_path.startswith("#") and c.position_path != ""
            ]
            assert heading_chunks, f"no heading-path chunks in {slug}"
            deep = [c for c in heading_chunks if " > " in c.position_path]
            assert deep, f"only document-level headings in {slug}"

    async def test_txt_document_level_paragraphs(self, db_session, ingested_scopes):
        """txt chunks are paragraphs at the document-level '# <basename>' locator."""
        for slug in ("personal-eval-weekly-plan", "generic-eval-brainstorm"):
            scope_id, _ = ingested_scopes[slug]
            chunks = await _chunks(db_session, scope_id)
            assert chunks, f"no chunks in {slug}"
            for c in chunks:
                assert c.position_path.startswith("# "), c.position_path
                assert c.chunk_type == "paragraph"

    async def test_word_clause_heading_paths(self, db_session, ingested_scopes):
        """Word corpus chunks locate via '第X条' heading paths (clause structure)."""
        for slug in ("legal-eval-dpa", "legal-eval-svc-contract"):
            scope_id, _ = ingested_scopes[slug]
            chunks = await _chunks(db_session, scope_id)
            assert chunks, f"no chunks in {slug}"
            clause_headings = [
                c for c in chunks
                if "第" in c.position_path and "条" in c.position_path
            ]
            assert clause_headings, f"no '第X条' heading chunks in {slug}"
            assert all(c.position_path.startswith("#") for c in chunks)

    async def test_pdf_numeric_section_paths(self, db_session, ingested_scopes):
        """PDF corpus chunks locate via 'page:N §<numeric>' paths (FR-004/US1 AC2)."""
        for slug in ("legal-eval-data-security", "legal-eval-pip"):
            scope_id, _ = ingested_scopes[slug]
            chunks = await _chunks(db_session, scope_id)
            assert chunks, f"no chunks in {slug}"
            numeric_headings = [
                c for c in chunks
                if re.match(r"^page:\d+ §[\d.]+", c.position_path)
            ]
            assert numeric_headings, f"no numeric-section headings in {slug}"
            assert all(c.position_path.startswith("page:") for c in chunks)


class TestRetrievalLocatable:
    async def test_dense_retrieval_scoped_and_locatable(self, db_session, ingested_scopes):
        """VS-02: retrieval returns evidence from the requested scope only,
        every item locatable (position_path non-empty, scope id matches)."""
        from rag_mcp.config import get_settings
        from rag_mcp.indexing.qdrant_client import QdrantStore
        from rag_mcp.services.ingestion_service import _derive_index_version
        from run_eval import _EvalEmbeddingProvider

        scope_id, _ = ingested_scopes["personal-eval-rag-notes"]
        settings = get_settings()
        provider = _EvalEmbeddingProvider(settings.embedding_model)
        qdrant = QdrantStore(url=settings.qdrant_url)
        index_version = _derive_index_version(settings.embedding_model)
        collection = f"chunks_hybrid_{index_version}"

        query_vector = await provider.embed_query("嵌入模型选型 bge-m3 中文检索")
        hits = qdrant.search_dense_named(
            collection, query_vector, scope_ids=[scope_id], limit=5,
        )
        assert hits, "dense retrieval returned no evidence for personal scope"
        hit_ids = [int(h["id"]) for h in hits]

        from rag_mcp.models.chunk import Chunk as ChunkModel
        rows = (await db_session.execute(
            sa_select(ChunkModel).where(ChunkModel.chunk_id.in_(hit_ids))
        )).scalars().all()
        by_id = {c.chunk_id: c for c in rows}
        for h in hits:
            c = by_id.get(int(h["id"]))
            assert c is not None, f"chunk {h['id']} not found in DB"
            assert c.knowledge_scope_id == scope_id, (
                "cross-scope evidence leaked into a single-scope query"
            )
            assert c.position_path, f"evidence without locatable position: {c.chunk_id}"


class TestDomainFormatGate:
    async def test_personal_family_rejects_java(self, db_session, tmp_path):
        """VS-02: the domain-profile format gate rejects out-of-family formats
        (java is a se-project format, not in the personal/generic family)."""
        row = (await db_session.execute(
            sa_select(DomainProfile.supported_formats).where(
                DomainProfile.domain_key == "personal"
            )
        )).scalar_one()
        assert "markdown" in row and "csv" in row
        assert "java" not in row, "personal family must not include se-project formats"

        java_file = tmp_path / "Sample.java"
        java_file.write_text("package demo;\npublic class Sample {}\n", encoding="utf-8")
        with pytest.raises(CorpusFormatError, match="outside the domain family"):
            validate_formats_against_family([java_file], list(row))

    async def test_legal_family_rejects_java_and_html(self, db_session, tmp_path):
        """Legal family is markdown/word/pdf only (FR-003); html is out of family."""
        row = (await db_session.execute(
            sa_select(DomainProfile.supported_formats).where(
                DomainProfile.domain_key == "legal"
            )
        )).scalar_one()
        assert list(row) == ["markdown", "word", "pdf"]

        java_file = tmp_path / "Sample.java"
        java_file.write_text("package demo;\npublic class Sample {}\n", encoding="utf-8")
        with pytest.raises(CorpusFormatError):
            validate_formats_against_family([java_file], list(row))

    async def test_legal_family_accepts_own_corpora(self, db_session):
        """The gate passes for the actual legal corpora (md/docx/pdf)."""
        row = (await db_session.execute(
            sa_select(DomainProfile.supported_formats).where(
                DomainProfile.domain_key == "legal"
            )
        )).scalar_one()
        legal_dir = _REPO_ROOT / "eval" / "corpora" / "legal"
        files = sorted(
            p for p in legal_dir.iterdir()
            if p.suffix.lower() in (".md", ".docx", ".pdf")
        )
        assert len(files) >= 7
        formats = validate_formats_against_family(files, list(row))
        assert set(formats) == {"markdown", "word", "pdf"}


class TestScopeReplayability:
    async def test_fixed_slug_scopes_reusable(self, db_session, ingested_scopes):
        """SC-010: each per-file scope is addressable by a fixed slug; re-running
        the ingestion runner reuses (never duplicates) the scope."""
        scopes = (await db_session.execute(
            sa_select(KnowledgeScope.slug, KnowledgeScope.scope_id)
            .where(KnowledgeScope.slug.in_(_ALL_SLUGS))
        )).all()
        by_slug: dict[str, list[int]] = {}
        for r in scopes:
            by_slug.setdefault(r.slug, []).append(int(r.scope_id))
        assert len(by_slug) == len(_ALL_SLUGS)
        for slug in _ALL_SLUGS:
            ids = by_slug.get(slug, [])
            assert len(ids) == 1, (
                f"slug {slug!r} resolved to {len(ids)} scopes — replay created "
                f"duplicates: {ids}"
            )
