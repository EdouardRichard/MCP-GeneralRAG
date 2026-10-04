def test_reader_tool_list_excludes_record_memory_before_mode_registration_merge():
    from rag_mcp.mcp.memory_tools import tool_names

    assert "record_memory" not in tool_names("reader")
    assert "record_memory" in tool_names("writer")
    assert "recall_memory" in tool_names("reader")
    assert "start_work" in tool_names("reader")

