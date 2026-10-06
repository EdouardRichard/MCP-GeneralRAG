"""Shared knowledge-source registration steps for upload and human promotion (T069).

Owns only: validated/sanitized content + scope + filename + format -> raw object
+ uploaded KnowledgeSource + exactly one pending initial ProcessingRun. It never
ingests, publishes, adjudicates, or performs an HTTP self-call, and it preserves
the existing raw-path convention and validation/error behaviour of upload.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from rag_mcp.config import get_settings
from rag_mcp.models.knowledge_source import KnowledgeSource
from rag_mcp.models.processing_run import ProcessingRun
from rag_mcp.parsers.registry import RegistryFormatError, upload_size_limit_message
from rag_mcp.utils.hashing import hash_bytes
from rag_mcp.utils.snowflake import generate_id


class RegistrationError(Exception):
    """Registration refusal carrying the HTTP status the upload route returns."""

    def __init__(self, status_code: int, detail: str):
        self.status_code, self.detail = status_code, detail
        super().__init__(detail)


@dataclass(frozen=True)
class Registration:
    source: KnowledgeSource
    initial_run: ProcessingRun
    raw_path: Path
    content_hash: str


def detect_format(filename: str, content: bytes | None = None) -> str:
    """Detect file format via the FormatHandler registry (008, FR-001/FR-003)."""
    from rag_mcp.parsers.registry import FormatHandlerRegistry

    return FormatHandlerRegistry.instance().detect_format(filename, content)


def raw_path_for(scope_id: int, source_id: int, filename: str) -> Path:
    """The frozen raw-object convention ``{data_root}/{scope}/{source}/{filename}``."""
    return Path(get_settings().data_root) / str(scope_id) / str(source_id) / filename


async def register_uploaded_source(session: AsyncSession, *, scope_id, content: bytes, filename: str,
                                   format: str | None = None, now: datetime | None = None) -> Registration:
    """Register the raw file and exactly one pending initial run in this transaction."""
    if not isinstance(scope_id, int) or isinstance(scope_id, bool) or scope_id <= 0:
        raise RegistrationError(422, "MISSING_KNOWLEDGE_SCOPE")
    if len(content) == 0:
        raise RegistrationError(400, "Empty file uploaded")
    max_size = get_settings().max_upload_size_bytes
    if len(content) > max_size:
        raise RegistrationError(413, upload_size_limit_message(max_size))
    if format is None:
        try:
            format = detect_format(filename, content)
        except RegistryFormatError as error:
            raise RegistrationError(400, str(error)) from None
    content_hash = hash_bytes(content)
    identifier = generate_id()
    path = raw_path_for(scope_id, identifier, filename or "unknown")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    timestamp = now or datetime.now(UTC)
    source = KnowledgeSource(source_id=identifier, knowledge_scope_id=scope_id, filename=filename or "unknown",
                             content_hash=content_hash, format=format, size_bytes=len(content),
                             status="uploaded", created_at=timestamp, updated_at=timestamp)
    initial_run = ProcessingRun(run_id=generate_id(), source_id=identifier, run_type="initial",
                                status="pending", stages=[])
    session.add_all([source, initial_run])
    await session.flush()
    return Registration(source=source, initial_run=initial_run, raw_path=path, content_hash=content_hash)
