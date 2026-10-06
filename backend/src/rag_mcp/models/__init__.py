"""SQLAlchemy ORM models for RAG MCP Server.

All models inherit from the shared ``Base`` declarative base defined here.
Import individual models from their respective modules or re-export from
this package for convenience.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# Re-export models for convenient ``from rag_mcp.models import KnowledgeScope``
from rag_mcp.models.knowledge_scope import KnowledgeScope  # noqa: E402, F401
from rag_mcp.models.project import Project  # noqa: E402, F401
from rag_mcp.models.knowledge_source import KnowledgeSource  # noqa: E402, F401
from rag_mcp.models.knowledge_version import KnowledgeVersion  # noqa: E402, F401
from rag_mcp.models.chunk import Chunk  # noqa: E402, F401
from rag_mcp.models.processing_run import ProcessingRun  # noqa: E402, F401
from rag_mcp.models.retrieval_run import RetrievalRun  # noqa: E402, F401
from rag_mcp.models.domain_profile import DomainProfile  # noqa: E402, F401
from rag_mcp.models.memory_event import MemoryEvent  # noqa: E402, F401
from rag_mcp.models.memory_projection import MemoryEntry  # noqa: E402, F401
from rag_mcp.models.scope_binding import ScopeBinding  # noqa: E402, F401
from rag_mcp.models.session import MemorySession  # noqa: E402, F401
from rag_mcp.models.memory_salience import MemorySalience  # noqa: E402, F401
from rag_mcp.models.memory_recall_run import MemoryRecallRun  # noqa: E402, F401
from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta  # noqa: E402, F401
from rag_mcp.models.memory_views import MemoryLink, MemorySummaryNode  # noqa: E402, F401
from rag_mcp.models.memory_history import MemorySnapshot, MemoryArchive, MemoryArchivedEvent  # noqa: E402, F401
from rag_mcp.models.memory_management_audit import MemoryManagementAudit  # noqa: E402, F401
from rag_mcp.models.consolidation_run import ConsolidationEligibility, ConsolidationRunObservation  # noqa: E402, F401
from rag_mcp.models.runtime import (  # noqa: E402, F401
    InstanceRegistry,
    WriterLease,
    RuntimeMaintenanceLog,
)
from rag_mcp.graph.models import GraphEdge, SoftRelation, GraphExpansionPath  # noqa: E402, F401
from rag_mcp.orchestration.models import (  # noqa: E402, F401
    EvidenceLedgerEntry,
    AgentJudgment,
    ContextSelectionList,
    AgenticRetrievalRun,
)

__all__ = [
    "Base",
    "KnowledgeScope",
    "Project",
    "KnowledgeSource",
    "KnowledgeVersion",
    "Chunk",
    "ProcessingRun",
    "RetrievalRun",
    "DomainProfile",
    "MemoryEvent", "MemoryEntry", "ScopeBinding", "MemorySession", "MemorySalience", "MemoryRecallRun", "MemoryProjectionMeta", "MemoryManagementAudit",
    "InstanceRegistry",
    "WriterLease",
    "RuntimeMaintenanceLog",
    "GraphEdge",
    "SoftRelation",
    "GraphExpansionPath",
    "EvidenceLedgerEntry",
    "AgentJudgment",
    "ContextSelectionList",
    "AgenticRetrievalRun",
]
