def test_incomplete_snapshot_fails_loudly():
    from rag_mcp.runtime.projection_rebuild import ProjectionRebuilder

    try:
        ProjectionRebuilder().restore(snapshot={"status": "corrupt"}, delta=[])
    except ValueError as exc:
        assert "SNAPSHOT_INVALID" in str(exc)
    else:
        raise AssertionError("corrupt snapshot must fail")

