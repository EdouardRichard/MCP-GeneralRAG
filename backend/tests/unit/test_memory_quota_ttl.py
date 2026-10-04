import pytest


def test_quota_fails_loudly_and_ttl_is_derived():
    from rag_mcp.services.memory_validators import check_quota, derive_ttl

    with pytest.raises(ValueError, match="MEMORY_QUOTA_EXCEEDED"):
        check_quota(5000, 5000)
    assert derive_ttl("episodic", {"ttl_days": {"episodic": 180}}) == 180

