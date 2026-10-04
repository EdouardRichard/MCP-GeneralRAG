def test_memory_rrf_supports_four_weighted_paths_and_deterministic_tie_break():
    from rag_mcp.fusion.rrf import weighted_memory_rrf

    result = weighted_memory_rrf({"dense": ["b", "a"], "recency": ["a"], "kind": [], "salience": []}, weights={"dense": 1.0, "recency": 0.2, "kind": 0.1, "salience": 0.2})
    assert [item["memory_id"] for item in result] == ["a", "b"]

