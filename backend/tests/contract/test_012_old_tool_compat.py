def test_old_tools_are_unchanged_and_present():
    from rag_mcp.mcp.memory_tools import LEGACY_TOOLS, tool_names
    assert tuple(LEGACY_TOOLS) == ("search_knowledge", "get_evidence", "list_knowledge_domains")
    assert set(LEGACY_TOOLS).issubset(tool_names("reader"))

