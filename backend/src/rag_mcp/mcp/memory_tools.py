TOOL_ANNOTATIONS = {
    "record_memory": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "recall_memory": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    "start_work": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
}
LEGACY_TOOLS = ("search_knowledge", "get_evidence", "list_knowledge_domains")

def tool_names(mode="writer"):
    base = list(LEGACY_TOOLS) + ["recall_memory", "start_work"]
    return base + (["record_memory"] if mode == "writer" else [])
