"""Immutable revision addressing within one model-versioned dense index."""
from uuid import NAMESPACE_URL, uuid5
from qdrant_client.models import FieldCondition, Filter, MatchValue


def revision_point_id(scope_id, revision_id, memory_id):
    return str(uuid5(NAMESPACE_URL, f"rag-memory/012-v2/{scope_id}/{revision_id}/{memory_id}"))


def revision_filter(scope_id, revision_id):
    conditions = [FieldCondition(key="knowledge_scope_id", match=MatchValue(value=str(scope_id)))]
    if revision_id is not None:
        conditions.append(FieldCondition(key="projection_revision", match=MatchValue(value=str(revision_id))))
    return Filter(must=conditions)
