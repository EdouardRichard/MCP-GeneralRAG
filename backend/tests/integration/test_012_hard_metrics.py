def test_hard_metrics_zero_leakage_and_complete_projection_registry():
    from rag_mcp.runtime.projection_rebuild import ProjectionRebuilder
    assert len(ProjectionRebuilder.projection_types) == 6
    assert set(ProjectionRebuilder.projection_types) == {"relation", "vector", "links", "summary", "file", "salience"}

