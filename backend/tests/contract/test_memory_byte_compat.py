def test_legacy_tool_names_remain_registered():
    from rag_mcp.mcp.memory_tools import tool_names

    names = set(tool_names("writer"))
    assert {"search_knowledge", "get_evidence", "list_knowledge_domains"}.issubset(names)

