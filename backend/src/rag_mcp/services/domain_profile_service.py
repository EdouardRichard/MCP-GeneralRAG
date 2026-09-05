"""Domain profile registry service (007, T010).

In-process builtin-profile sync (drift repair, FR-005/SC-008) plus the builtin
read-only guard (Q1). Builtin rows are never mutable or removable; the guard is
enforced here and re-checked by the management API layer (FR-005).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_mcp.config.domain_profiles import (
    BUILTIN_DOMAIN_PROFILES,
    BUILTIN_DOMAIN_KEYS,
    is_builtin,
)
from rag_mcp.models.domain_profile import DomainProfile


def assert_not_builtin(domain_key: str) -> None:
    """Raise ValueError when domain_key names a builtin (read-only) profile."""
    if is_builtin(domain_key):
        raise ValueError("builtin domain profile '%s' is read-only" % domain_key)


class DomainProfileService:
    """Registry sync + builtin read-only guard (007, T010)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sync_builtin_profiles(self) -> int:
        """Reconcile DB builtin rows with the in-process seed; return repair count.

        Inserts missing builtin rows and rewrites any drifted field back to the
        authoritative seed (FR-005). The caller commits; a failure propagates so
        the startup can fail loudly rather than silently degrade (SC-008).
        """
        repairs = 0
        for key, seed in BUILTIN_DOMAIN_PROFILES.items():
            row = await self._get(key)
            if row is None:
                self._session.add(self._build(key, seed))
                repairs += 1
            elif not self._matches(row, seed):
                self._apply(row, seed)
                repairs += 1
        await self._session.flush()
        return repairs

    async def _get(self, domain_key: str) -> DomainProfile | None:
        result = await self._session.execute(
            select(DomainProfile).where(DomainProfile.domain_key == domain_key)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _build(key: str, seed: dict[str, Any]) -> DomainProfile:
        return DomainProfile(
            domain_key=key,
            name=seed["name"],
            description=seed.get("description"),
            supported_formats=seed["supported_formats"],
            chunk_type_extensions=seed.get("chunk_type_extensions"),
            graph_relations=seed["graph_relations"],
            prompt_overrides=seed.get("prompt_overrides"),
            default_capabilities=seed["default_capabilities"],
            is_builtin=True,
        )

    @staticmethod
    def _matches(row: DomainProfile, seed: dict[str, Any]) -> bool:
        return (
            row.name == seed["name"]
            and row.supported_formats == seed["supported_formats"]
            and row.graph_relations == seed["graph_relations"]
            and row.prompt_overrides == seed.get("prompt_overrides")
            and row.default_capabilities == seed["default_capabilities"]
            and bool(row.is_builtin) is True
        )

    @staticmethod
    def _apply(row: DomainProfile, seed: dict[str, Any]) -> None:
        row.name = seed["name"]
        row.description = seed.get("description")
        row.supported_formats = seed["supported_formats"]
        row.chunk_type_extensions = seed.get("chunk_type_extensions")
        row.graph_relations = seed["graph_relations"]
        row.prompt_overrides = seed.get("prompt_overrides")
        row.default_capabilities = seed["default_capabilities"]
        row.is_builtin = True
