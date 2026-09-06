"""Unit test for startup sync + builtin read-only guard (007, T004).

FR-005/SC-008: builtin rows are reconciled with the in-process seed (drift
repair), and the builtin guard rejects mutation/removal.
"""
from __future__ import annotations

import pytest

from rag_mcp.config.domain_profiles import BUILTIN_DOMAIN_PROFILES
from rag_mcp.services.domain_profile_service import (
    DomainProfileService,
    assert_not_builtin,
)


def test_assert_not_builtin_rejects_builtin():
    with pytest.raises(ValueError):
        assert_not_builtin("se-project")
    with pytest.raises(ValueError):
        assert_not_builtin("generic")
    with pytest.raises(ValueError):
        assert_not_builtin("legal")


def test_assert_not_builtin_allows_custom():
    assert_not_builtin("custom")  # should not raise


def test_builtin_seed_matches_guard():
    for key in BUILTIN_DOMAIN_PROFILES:
        with pytest.raises(ValueError):
            assert_not_builtin(key)


@pytest.mark.asyncio
async def test_sync_is_idempotent(db_session):
    """Sync twice: the second run performs no repairs (drift = 0)."""
    service = DomainProfileService(db_session)
    await service.sync_builtin_profiles()
    await db_session.commit()
    second = await service.sync_builtin_profiles()
    await db_session.commit()
    assert second == 0
