from rag_mcp.services.memory_service import format_memory_recall, recall_memories

def recall_memory(rows, **kwargs):
    return format_memory_recall(recall_memories(rows, **kwargs))
