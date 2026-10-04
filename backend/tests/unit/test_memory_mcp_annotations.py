def test_memory_tool_annotations():
    from rag_mcp.mcp.memory_tools import TOOL_ANNOTATIONS

    assert TOOL_ANNOTATIONS["record_memory"]["readOnlyHint"] is False
    assert TOOL_ANNOTATIONS["recall_memory"]["readOnlyHint"] is True
    assert TOOL_ANNOTATIONS["start_work"]["readOnlyHint"] is True

