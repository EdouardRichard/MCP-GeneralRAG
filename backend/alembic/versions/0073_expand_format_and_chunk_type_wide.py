"""expand_format_and_chunk_type_wide

Revision ID: 0073
Revises: 0072
Create Date: 2026-09-06 00:00:00.000000

008 Universal Ingestion Channel: widen the three enum CHECK constraints to a
wide-mode pattern + application-layer validation (FR-018/FR-019).

  * knowledge_sources.format:      String(16) -> String(32), enum -> pattern
  * chunks.chunk_type:             String(16) -> String(32), 18-value enum ->
                                   L1 (section/heading/paragraph/list/table) +
                                   L2 namespace + legacy 18 values
  * retrieval_runs.format:         String(8)  -> String(32), enum -> pattern

Backward compatible: existing 'markdown'/'java'/... formats and the 18 legacy
chunk_type values remain valid under the wide pattern (zero data migration).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0073"
down_revision: Union[str, Sequence[str], None] = "0072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_CHUNK_TYPES = (
    "section", "symbol", "endpoint", "schema", "table", "column",
    "constraint", "index", "view", "procedure", "function", "method",
    "type", "interface", "class", "heading", "paragraph", "list",
)

_LEGACY_FORMATS = (
    "markdown", "java", "openapi", "ddl", "go", "python", "word", "pdf",
)


def upgrade() -> None:
    # knowledge_sources.format: String(16) -> String(32), enum -> wide pattern
    op.execute("ALTER TABLE knowledge_sources ALTER COLUMN format TYPE VARCHAR(32)")
    op.execute(
        "ALTER TABLE knowledge_sources "
        "DROP CONSTRAINT IF EXISTS knowledge_sources_format_check"
    )
    op.execute(
        "ALTER TABLE knowledge_sources "
        "ADD CONSTRAINT knowledge_sources_format_check "
        "CHECK (format ~ '^[a-z][a-z0-9_]{0,31}$')"
    )

    # chunks.chunk_type: String(16) -> String(32), 18-value enum -> wide pattern
    op.execute("ALTER TABLE chunks ALTER COLUMN chunk_type TYPE VARCHAR(32)")
    op.execute(
        "ALTER TABLE chunks "
        "DROP CONSTRAINT IF EXISTS chunks_chunk_type_check"
    )
    op.execute(
        "ALTER TABLE chunks "
        "ADD CONSTRAINT chunks_chunk_type_check "
        "CHECK (chunk_type ~ '^[a-z][a-z0-9_]{0,31}$' "
        "OR chunk_type ~ '^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$')"
    )

    # retrieval_runs.format: String(8) -> String(32), enum -> wide pattern
    op.execute("ALTER TABLE retrieval_runs ALTER COLUMN format TYPE VARCHAR(32)")
    op.execute(
        "ALTER TABLE retrieval_runs "
        "DROP CONSTRAINT IF EXISTS chk_retrieval_run_format"
    )
    op.execute(
        "ALTER TABLE retrieval_runs "
        "ADD CONSTRAINT chk_retrieval_run_format "
        "CHECK (format IS NULL OR format ~ '^[a-z][a-z0-9_]{0,31}$')"
    )


def downgrade() -> None:
    # knowledge_sources.format: revert to the 8-value enum (String(16))
    op.execute(
        "ALTER TABLE knowledge_sources "
        "DROP CONSTRAINT IF EXISTS knowledge_sources_format_check"
    )
    op.execute(
        "ALTER TABLE knowledge_sources "
        "ADD CONSTRAINT knowledge_sources_format_check "
        "CHECK (format IN ('" + "','".join(_LEGACY_FORMATS) + "'))"
    )
    op.execute("ALTER TABLE knowledge_sources ALTER COLUMN format TYPE VARCHAR(16)")

    # chunks.chunk_type: revert to the 18-value enum (String(16))
    op.execute(
        "ALTER TABLE chunks "
        "DROP CONSTRAINT IF EXISTS chunks_chunk_type_check"
    )
    op.execute(
        "ALTER TABLE chunks "
        "ADD CONSTRAINT chunks_chunk_type_check "
        "CHECK (chunk_type IN ('" + "','".join(_LEGACY_CHUNK_TYPES) + "'))"
    )
    op.execute("ALTER TABLE chunks ALTER COLUMN chunk_type TYPE VARCHAR(16)")

    # retrieval_runs.format: revert to the 8-value enum (String(8))
    op.execute(
        "ALTER TABLE retrieval_runs "
        "DROP CONSTRAINT IF EXISTS chk_retrieval_run_format"
    )
    op.execute(
        "ALTER TABLE retrieval_runs "
        "ADD CONSTRAINT chk_retrieval_run_format "
        "CHECK (format IS NULL OR format IN ('" + "','".join(_LEGACY_FORMATS) + "'))"
    )
    op.execute("ALTER TABLE retrieval_runs ALTER COLUMN format TYPE VARCHAR(8)")
