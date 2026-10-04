def test_builtin_memory_policy_defaults_are_identical():
    from rag_mcp.config.domain_profiles import BUILTIN_MEMORY_POLICY

    assert set(BUILTIN_MEMORY_POLICY) == {"se-project", "generic", "personal", "legal"}
    policies = list(BUILTIN_MEMORY_POLICY.values())
    assert all(policy == policies[0] for policy in policies)
    assert policies[0]["quota"] == 5000
    assert policies[0]["decay_rate"] == 0.05

