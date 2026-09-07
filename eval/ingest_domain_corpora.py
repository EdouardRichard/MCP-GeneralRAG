#!/usr/bin/env python3
"""Domain corpora ingestion runner (011, T006, FR-002/FR-004/SC-010).

Idempotently creates ONE public scope per corpus file across the three 011
evaluation domains (public+personal, public+generic, public+legal), validates
every corpus file against its domain-profile format family (application-layer
gate layered on the registry check), and ingests the corpus through the
existing pipeline — FormatHandler registry dispatch, converter/native slicing,
credential redaction, embedding, version publish.

Scope layout rationale (one file per scope): the system's knowledge-version
model publishes one live snapshot per scope — ingesting a second source into
the same scope supersedes (and purges) the first source's chunks. The 001/008
eval corpora therefore use one scope per corpus file (e.g. "008-json-2",
"008-yaml-3"). 011 follows that precedent; a domain's corpus spans several
scopes, each carrying one file's chunks, and dataset entries reference the
scope slug(s) holding the expected evidence (FR-002 "跨 >=2 个 scope").

Idempotency: by fixed slug scope reuse + by-filename source dedup, so the
corpora stay replayable (SC-010). Failures are fail-loud (US1 AC5).

Usage:
    python eval/ingest_domain_corpora.py                     # all three domains
    python eval/ingest_domain_corpora.py --scope personal    # one domain
    python eval/ingest_domain_corpora.py --dry-run           # validate only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_SRC = _REPO_ROOT / "backend" / "src"
for p in (_BACKEND_SRC, str(_REPO_ROOT / "eval"), str(_REPO_ROOT / "backend")):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from sqlalchemy import select as sa_select  # noqa: E402
from sqlalchemy import text as sa_text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rag_mcp.config import get_settings  # noqa: E402
from rag_mcp.indexing.qdrant_client import QdrantStore  # noqa: E402
from rag_mcp.models.domain_profile import DomainProfile  # noqa: E402
from rag_mcp.models.knowledge_source import KnowledgeSource  # noqa: E402
from rag_mcp.parsers.registry import FormatHandlerRegistry  # noqa: E402
from rag_mcp.utils.hashing import hash_bytes  # noqa: E402
from rag_mcp.utils.snowflake import generate_id  # noqa: E402
from run_eval import _EvalEmbeddingProvider  # noqa: E402

logger = logging.getLogger(__name__)

GENERIC_CORPUS_DIR = _REPO_ROOT / "eval" / "corpora" / "generic"
LEGAL_CORPUS_DIR = _REPO_ROOT / "eval" / "corpora" / "legal"

# ---------------------------------------------------------------------------
# Per-file scope specs (one public scope per corpus file — 001/008 precedent)
# ---------------------------------------------------------------------------

SCOPE_SPECS: list[dict] = [
    # --- personal domain (public + personal profile) -----------------------
    {"domain_key": "personal", "slug": "personal-eval-rag-notes",
     "dir": GENERIC_CORPUS_DIR, "file": "个人学习笔记-RAG系统.md"},
    {"domain_key": "personal", "slug": "personal-eval-weekly-plan",
     "dir": GENERIC_CORPUS_DIR, "file": "个人周计划.txt"},
    {"domain_key": "personal", "slug": "personal-eval-expenses",
     "dir": GENERIC_CORPUS_DIR, "file": "个人开支记录.csv"},
    {"domain_key": "personal", "slug": "personal-eval-bookmarks",
     "dir": GENERIC_CORPUS_DIR, "file": "学习资源收藏.html"},
    # --- team/generic domain (public + generic profile) --------------------
    {"domain_key": "generic", "slug": "generic-eval-meeting-notes",
     "dir": GENERIC_CORPUS_DIR, "file": "team_meeting_notes.md"},
    {"domain_key": "generic", "slug": "generic-eval-conventions",
     "dir": GENERIC_CORPUS_DIR, "file": "团队知识库-检索规范.md"},
    {"domain_key": "generic", "slug": "generic-eval-brainstorm",
     "dir": GENERIC_CORPUS_DIR, "file": "brainstorm_ideas.txt"},
    {"domain_key": "generic", "slug": "generic-eval-reading-tracker",
     "dir": GENERIC_CORPUS_DIR, "file": "reading_tracker.csv"},
    {"domain_key": "generic", "slug": "generic-eval-bookmarks",
     "dir": GENERIC_CORPUS_DIR, "file": "bookmark_archive.html"},
    # --- legal domain (public + legal profile) -----------------------------
    {"domain_key": "legal", "slug": "legal-eval-dpa",
     "dir": LEGAL_CORPUS_DIR, "file": "数据处理协议模板.docx"},
    {"domain_key": "legal", "slug": "legal-eval-svc-contract",
     "dir": LEGAL_CORPUS_DIR, "file": "标准服务合同模板.docx"},
    {"domain_key": "legal", "slug": "legal-eval-data-security",
     "dir": LEGAL_CORPUS_DIR, "file": "数据安全管理办法.pdf"},
    {"domain_key": "legal", "slug": "legal-eval-pip",
     "dir": LEGAL_CORPUS_DIR, "file": "个人信息保护规范.pdf"},
    {"domain_key": "legal", "slug": "legal-eval-regulation",
     "dir": LEGAL_CORPUS_DIR, "file": "数据治理条例.md"},
    {"domain_key": "legal", "slug": "legal-eval-rules",
     "dir": LEGAL_CORPUS_DIR, "file": "实施细则.md"},
    {"domain_key": "legal", "slug": "legal-eval-references",
     "dir": LEGAL_CORPUS_DIR, "file": "引用性文件.md"},
]

DOMAINS = ("personal", "generic", "legal")


class CorpusFormatError(RuntimeError):
    """Raised when a corpus file's format is outside the scope's domain family."""


def validate_formats_against_family(
    files: list[Path], supported_formats: list[str]
) -> list[str]:
    """Application-layer domain-profile format gate (VS-02).

    Detects each file's format via the FormatHandler registry and raises
    CorpusFormatError when it falls outside the scope's domain family.
    Returns the detected formats (in file order) on success.
    """
    registry = FormatHandlerRegistry.instance()
    formats: list[str] = []
    for path in files:
        raw = path.read_bytes()
        fmt = registry.detect_format(path.name, raw)
        if fmt not in supported_formats:
            raise CorpusFormatError(
                f"format {fmt!r} ({path.name}) is outside the domain "
                f"family {supported_formats} (domain-profile format gate, VS-02)"
            )
        formats.append(fmt)
    return formats


async def sync_builtin_domain_profiles(session_factory) -> int:
    """Ensure DB builtin profile rows match the in-process seed (007 sync).

    The 011 personal row (and the legal supported_formats extension) reach
    the database through this startup-sync mechanism — no DDL migration.
    """
    from rag_mcp.services.domain_profile_service import DomainProfileService

    async with session_factory() as session:
        svc = DomainProfileService(session)
        repairs = await svc.sync_builtin_profiles()
        await session.commit()
    if repairs:
        logger.info("domain_profiles sync: %d row(s) inserted/repaired", repairs)
    return repairs


async def ensure_scope(session_factory, slug: str, domain_key: str) -> int:
    """Idempotent scope creation by fixed slug (SC-010 replayability)."""
    async with session_factory() as session:
        row = (await session.execute(
            sa_text(
                "SELECT scope_id FROM knowledge_scopes "
                "WHERE slug = :slug AND status = 'active' "
                "ORDER BY scope_id LIMIT 1"
            ),
            {"slug": slug},
        )).first()
        if row is not None:
            return int(row[0])
        scope_id = generate_id()
        await session.execute(sa_text(
            "INSERT INTO knowledge_scopes (scope_id, scope_type, name, slug, "
            "status, domain_key) VALUES (:sid, 'public', :name, :slug, "
            "'active', :dk)"
        ), {"sid": scope_id, "name": slug, "slug": slug, "dk": domain_key})
        await session.commit()
        logger.info("created scope %s (slug=%s, domain_key=%s)", scope_id, slug, domain_key)
        return scope_id


async def resolve_supported_formats(session_factory, domain_key: str) -> list[str]:
    """Read the domain profile's supported_formats from the DB row."""
    async with session_factory() as session:
        row = (await session.execute(
            sa_select(DomainProfile.supported_formats).where(
                DomainProfile.domain_key == domain_key
            )
        )).scalar_one_or_none()
    if row is None:
        raise RuntimeError(
            f"domain profile {domain_key!r} missing after sync — aborting"
        )
    return list(row)


def spec_files(spec: dict) -> list[Path]:
    path = Path(spec["dir"]) / spec["file"]
    if not path.exists():
        raise FileNotFoundError(f"corpus file missing: {path}")
    return [path]


async def ingest_domain_corpora(domains: list[str], dry_run: bool = False) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        await sync_builtin_domain_profiles(session_factory)

        embedding = _EvalEmbeddingProvider(settings.embedding_model)
        qdrant = QdrantStore(url=settings.qdrant_url)

        data_root = Path(settings.data_root)
        if not data_root.exists():
            data_root = _REPO_ROOT / "backend" / data_root

        registry = FormatHandlerRegistry.instance()
        specs = [s for s in SCOPE_SPECS if s["domain_key"] in domains]
        # Cache the supported-format family per domain (3 lookups total).
        family_cache: dict[str, list[str]] = {}
        for domain in domains:
            family_cache[domain] = await resolve_supported_formats(
                session_factory, domain
            )

        summary: list[dict] = []
        for spec in specs:
            domain = spec["domain_key"]
            files = spec_files(spec)
            formats = validate_formats_against_family(files, family_cache[domain])
            if dry_run:
                summary.append({
                    "domain_key": domain,
                    "slug": spec["slug"],
                    "file": spec["file"],
                    "format": formats[0],
                    "dry_run": True,
                })
                continue

            scope_id = await ensure_scope(session_factory, spec["slug"], domain)
            path = files[0]
            raw = path.read_bytes()
            fmt = formats[0]

            async with session_factory() as session:
                existing = (await session.execute(
                    sa_select(KnowledgeSource).where(
                        KnowledgeSource.knowledge_scope_id == scope_id,
                        KnowledgeSource.filename == spec["file"],
                    )
                )).scalars().first()

                if existing is not None and existing.status == "published":
                    summary.append({
                        "domain_key": domain, "slug": spec["slug"],
                        "file": spec["file"], "status": "skipped_already_published",
                    })
                    continue

                from rag_mcp.services.ingestion_service import IngestionService

                svc = IngestionService(session, embedding, qdrant)
                if existing is not None:
                    # Retry a failed/uploaded row from an interrupted replay.
                    await svc.reprocess(existing.source_id)
                    await session.commit()
                    summary.append({
                        "domain_key": domain, "slug": spec["slug"],
                        "file": spec["file"], "status": "reprocessed",
                    })
                    continue

                source_id = generate_id()
                save_dir = data_root / str(scope_id) / str(source_id)
                save_dir.mkdir(parents=True, exist_ok=True)
                (save_dir / spec["file"]).write_bytes(raw)
                await session.execute(sa_text(
                    "INSERT INTO knowledge_sources (source_id, "
                    "knowledge_scope_id, filename, content_hash, format, "
                    "size_bytes, status) VALUES (:sid, :ksid, :fn, :ch, "
                    ":fmt, :sz, 'uploaded')"
                ), {
                    "sid": source_id, "ksid": scope_id, "fn": spec["file"],
                    "ch": hash_bytes(raw), "fmt": fmt, "sz": len(raw),
                })
                await session.commit()
                # Ingest WITHOUT graph_ready: the legal graph vocabulary is
                # empty (R11) until the Q1=A benefit gate decides (T015/T016);
                # dense/hybrid evaluation needs no graph capability anyway.
                await svc.ingest(source_id, graph_ready=False)
                await session.commit()
                summary.append({
                    "domain_key": domain, "slug": spec["slug"],
                    "file": spec["file"], "format": fmt, "scope_id": scope_id,
                    "status": "ingested",
                })
                logger.info("ingested %s -> %s (format=%s)", spec["file"], spec["slug"], fmt)

        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    finally:
        await engine.dispose()


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Idempotent 011 domain-corpora ingestion (per-file scopes)."
    )
    p.add_argument(
        "--scope", choices=list(DOMAINS), default=None,
        help="ingest a single domain (default: all three)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="validate formats against the domain family without ingesting",
    )
    return p.parse_args(argv)


async def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    domains = [args.scope] if args.scope else list(DOMAINS)
    return await ingest_domain_corpora(domains, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
