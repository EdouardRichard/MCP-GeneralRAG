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
    relation_vocab_union,
    validate_memory_link_vocabulary,
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

    async def create_profile(self, data: dict[str, Any]) -> DomainProfile:
        """Create a custom domain profile (builtin keys rejected)."""
        assert_not_builtin(data["domain_key"])
        profile = DomainProfile(
            domain_key=data["domain_key"],
            name=data["name"],
            description=data.get("description"),
            supported_formats=data["supported_formats"],
            chunk_type_extensions=data.get("chunk_type_extensions"),
            graph_relations=data.get("graph_relations", {}),
            prompt_overrides=data.get("prompt_overrides"),
            default_capabilities=data.get("default_capabilities", {}),
            memory_link_vocabulary=validate_memory_link_vocabulary(data.get("memory_link_vocabulary", [])),
            is_builtin=False,
        )
        self._session.add(profile)
        await self._session.flush()
        return profile

    async def update_profile(self, domain_key: str, data: dict[str, Any]) -> DomainProfile:
        """Update a custom domain profile (builtin keys rejected, field-level)."""
        assert_not_builtin(domain_key)
        row = await self._get(domain_key)
        if row is None:
            raise ValueError("domain profile '%s' not found" % domain_key)
        row.name = data.get("name", row.name)
        row.description = data.get("description", row.description)
        row.supported_formats = data.get("supported_formats", row.supported_formats)
        row.chunk_type_extensions = data.get("chunk_type_extensions", row.chunk_type_extensions)
        row.graph_relations = data.get("graph_relations", row.graph_relations)
        row.prompt_overrides = data.get("prompt_overrides", row.prompt_overrides)
        row.default_capabilities = data.get("default_capabilities", row.default_capabilities)
        if "memory_link_vocabulary" in data:
            row.memory_link_vocabulary = validate_memory_link_vocabulary(data["memory_link_vocabulary"])
        await self._session.flush()
        return row

    async def delete_profile(self, domain_key: str) -> bool:
        """Delete a custom profile; reject builtin + referenced profiles."""
        assert_not_builtin(domain_key)
        from rag_mcp.models.knowledge_scope import KnowledgeScope
        referenced = await self._session.execute(
            select(KnowledgeScope.scope_id).where(
                KnowledgeScope.domain_key == domain_key
            ).limit(1)
        )
        if referenced.scalar_one_or_none() is not None:
            raise ValueError("domain profile '%s' is still referenced by a knowledge domain" % domain_key)
        row = await self._get(domain_key)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def list_profiles(self) -> list[DomainProfile]:
        result = await self._session.execute(
            select(DomainProfile).order_by(DomainProfile.domain_key)
        )
        return list(result.scalars().all())

    async def resolve_planner_config(self, scope_ids: list[int]) -> dict[str, Any]:
        """Resolve the planner config for a request's scope set (009, T005, R7).

        Queries knowledge_scopes.domain_key for the scope set, then the
        domain_profiles rows, and derives the per-request planner config:
          - distinct_domain_keys: deduped domain_key set (>=1)
          - relation_vocab: deterministic union of graph_relations keys (R4)
          - prompt_override: the single profile's query_planner_system_prompt
            when exactly one distinct domain_key declares it; else None.
        """
        from rag_mcp.models.knowledge_scope import KnowledgeScope

        if not scope_ids:
            return {
                "distinct_domain_keys": [],
                "relation_vocab": [],
                "prompt_override": None,
            }

        result = await self._session.execute(
            select(KnowledgeScope.domain_key).where(
                KnowledgeScope.scope_id.in_(list(scope_ids))
            )
        )
        domain_keys = sorted(set(result.scalars().all()))
        if not domain_keys:
            return {
                "distinct_domain_keys": [],
                "relation_vocab": [],
                "prompt_override": None,
            }

        profiles_result = await self._session.execute(
            select(DomainProfile).where(DomainProfile.domain_key.in_(domain_keys))
        )
        profiles = list(profiles_result.scalars().all())

        relation_vocab = relation_vocab_union([p.graph_relations for p in profiles])

        prompt_override = None
        if len(domain_keys) == 1 and profiles:
            overrides = profiles[0].prompt_overrides or {}
            prompt_override = overrides.get("query_planner_system_prompt")

        return {
            "distinct_domain_keys": domain_keys,
            "relation_vocab": relation_vocab,
            "prompt_override": prompt_override,
        }

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
            memory_link_vocabulary=seed.get("memory_link_vocabulary", []),
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
            and (row.memory_link_vocabulary or []) == seed.get("memory_link_vocabulary", [])
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
        row.memory_link_vocabulary = seed.get("memory_link_vocabulary", [])
        row.is_builtin = True
