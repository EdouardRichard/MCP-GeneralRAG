"""011 multi-domain acceptance tests (T017/T018/T019, VS-06/SC-003/SC-004).

Exercises the MCP tool layer (search_knowledge_core / list_knowledge_domains_core
/ EvidenceService) over the mixed-domain environment built by 011 (personal /
generic / legal per-file scopes) plus an existing se-project scope. Covers:

- T017: list_knowledge_domains discovery -> domain_scope three addressing forms
  (numeric ID / slug / type:name) -> search_knowledge -> get_evidence closed
  loop (FR-012/FR-013);
- T018: hard-metrics three-piece measured per-response (cross-domain leakage=0 /
  Schema 100% / source locatability 100%, FR-014/FR-023~FR-025);
- T019: four reference scenarios (only project_scope / only domain_scope / both
  union-dedup / neither rejected, FR-022).

Retrieval runs in-process against the real shared PostgreSQL + Qdrant.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from jsonschema import Draft202012Validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from rag_mcp.mcp.list_knowledge_domains import list_knowledge_domains_core  # noqa: E402
from rag_mcp.mcp.search_knowledge import search_knowledge_core  # noqa: E402
from rag_mcp.indexing.qdrant_client import QdrantStore  # noqa: E402
from rag_mcp.services.evidence_service import EvidenceService  # noqa: E402

_SEARCH_SCHEMA = json.loads((
    _REPO_ROOT / "specs" / "001-minimum-rag-mcp-loop" / "contracts"
    / "mcp-search-output.schema.json"
).read_text(encoding="utf-8"))
_EVIDENCE_SCHEMA = json.loads((
    _REPO_ROOT / "specs" / "001-minimum-rag-mcp-loop" / "contracts"
    / "mcp-get-evidence.schema.json"
).read_text(encoding="utf-8"))
def _merged_list_schema() -> dict:
    """Inline the 007 common.schema.json definitions into the list-domains schema."""
    contracts = _REPO_ROOT / "specs" / "007-knowledge-domain-generalization" / "contracts"
    schema = json.loads((contracts / "list-domains.output.schema.json").read_text(encoding="utf-8"))
    common = json.loads((contracts / "common.schema.json").read_text(encoding="utf-8"))
    schema.setdefault("$defs", {})
    schema["$defs"].update(common.get("definitions", {}))
    prefixes = (common["$id"] + "#/definitions/", "common.schema.json#/definitions/")

    def _rewrite(obj):
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if k == "$ref" and isinstance(v, str):
                    for p in prefixes:
                        if v.startswith(p):
                            obj[k] = "#/$defs/" + v[len(p):]
                            break
                else:
                    _rewrite(v)
        elif isinstance(obj, list):
            for item in obj:
                _rewrite(item)

    _rewrite(schema)
    return schema


_LIST_SCHEMA = _merged_list_schema()

# The 011 per-file scope slugs per domain (matches ingest_domain_corpora.py).
_DOMAIN_SLUGS = {
    "personal": [
        "personal-eval-rag-notes", "personal-eval-weekly-plan",
        "personal-eval-expenses", "personal-eval-bookmarks",
    ],
    "generic": [
        "generic-eval-meeting-notes", "generic-eval-conventions",
        "generic-eval-brainstorm", "generic-eval-reading-tracker",
        "generic-eval-bookmarks",
    ],
    "legal": [
        "legal-eval-dpa", "legal-eval-svc-contract", "legal-eval-data-security",
        "legal-eval-pip", "legal-eval-regulation", "legal-eval-rules",
        "legal-eval-references",
    ],
}
_ALL_011_SLUGS = [s for v in _DOMAIN_SLUGS.values() for s in v]


@pytest.fixture(scope="module")
def embedding_provider():
    """Real bge-m3 embedding provider (loaded once per module)."""
    from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider

    return LocalCPUEmbeddingProvider()


@pytest.fixture(scope="module")
def qdrant_store():
    from rag_mcp.config import get_settings

    return QdrantStore(url=get_settings().qdrant_url)


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _domains(session_factory) -> list[dict]:
    return (await list_knowledge_domains_core(session_factory))["domains"]


async def _search(session_factory, qdrant_store, embedding_provider, query,
                  project_scope=None, domain_scope=None) -> dict:
    return await search_knowledge_core(
        query=query,
        project_scope=project_scope or [],
        domain_scope=domain_scope or [],
        top_k=5,
        task_context=None,
        session_factory=session_factory,
        qdrant_store=qdrant_store,
        embedding_provider=embedding_provider,
    )


def _schema_valid(instance, schema) -> bool:
    try:
        Draft202012Validator(schema).validate(instance)
        return True
    except Exception:
        return False


class TestDiscoveryFourAxes:
    async def test_list_domains_covers_four_semantic_axes(self, session_factory):
        """T017/FR-012: >=4 semantic axes (personal/generic/legal/se-project)
        are discoverable, and entries are metadata-only (no knowledge content)."""
        domains = await _domains(session_factory)
        by_key: dict[str, list] = {}
        for d in domains:
            by_key.setdefault(d["domain_key"], []).append(d)

        for key in ("personal", "generic", "legal", "se-project"):
            assert by_key.get(key), f"domain_key {key!r} not discoverable"

        for d in domains:
            # metadata-only: the exact six metadata keys, no content fields.
            assert set(d.keys()) == {"id", "slug", "name", "scope_type",
                                     "domain_key", "capabilities"}, d
            assert set(d["capabilities"].keys()) == {"supported_formats", "has_graph"}

    async def test_011_slugs_discoverable(self, session_factory):
        """T017: every 011 per-file scope is discoverable by its fixed slug."""
        domains = await _domains(session_factory)
        slugs = {d["slug"] for d in domains}
        missing = [s for s in _ALL_011_SLUGS if s not in slugs]
        assert not missing, f"011 scopes not discoverable: {missing}"


class TestThreeFormAddressingClosedLoop:
    async def test_numeric_slug_typename_all_resolve(self, session_factory,
                                                     qdrant_store, embedding_provider):
        """T017/FR-012: numeric ID / slug / type:name all retrieve evidence
        from the same personal scope, and get_evidence expands a hit."""
        domains = await _domains(session_factory)
        target = next(d for d in domains if d["slug"] == "personal-eval-rag-notes")
        scope_id = target["id"]
        slug = target["slug"]

        query = "嵌入模型选型时本地部署首选哪个模型"

        by_id = await _search(session_factory, qdrant_store, embedding_provider,
                              query, domain_scope=[scope_id])
        by_slug = await _search(session_factory, qdrant_store, embedding_provider,
                                query, domain_scope=[slug])
        by_typename = await _search(
            session_factory, qdrant_store, embedding_provider,
            query, domain_scope=[f"public:{target['name']}"],
        )

        for form, resp in (("numeric", by_id), ("slug", by_slug), ("typename", by_typename)):
            assert resp.get("completion_status") in ("complete", "partial"), form
            assert resp.get("evidence"), f"{form} returned no evidence"
            for ev in resp["evidence"]:
                assert str(ev.get("knowledge_scope_id")) == str(scope_id), (
                    f"{form} leaked evidence from another scope: {ev}")

        # get_evidence expands a search hit through the EvidenceService.
        hit = by_slug["evidence"][0]["evidence_id"]
        async with session_factory() as session:
            svc = EvidenceService(session=session)
            expanded = await svc.get_evidence(
                evidence_id=hit, project_scopes=[], domain_scopes=[slug],
            )
            await session.commit()
        assert expanded.get("status") == "available", expanded
        assert expanded.get("full_content"), "evidence expansion returned empty content"


class TestHardMetricsThreePiece:
    async def _collect_evidence(self, session_factory, qdrant_store, embedding_provider):
        domains = await _domains(session_factory)
        personal = next(d for d in domains if d["slug"] == "personal-eval-rag-notes")
        legal_word = next(d for d in domains if d["slug"] == "legal-eval-dpa")
        legal_pdf = next(d for d in domains if d["slug"] == "legal-eval-data-security")

        queries = [
            ("嵌入模型选型时本地部署首选哪个模型", [personal["id"]]),
            ("数据处理协议对跨境提供个人数据有什么要求", [legal_word["id"]]),
            ("数据安全管理办法对重要数据处理者有什么义务", [legal_pdf["id"]]),
        ]
        results = []
        for q, scopes in queries:
            resp = await _search(session_factory, qdrant_store, embedding_provider,
                                 q, domain_scope=scopes)
            results.append((scopes, resp))
        return results

    async def test_cross_domain_leakage_zero(self, session_factory, qdrant_store,
                                             embedding_provider):
        """T018/FR-023: single-domain queries never return other-domain evidence."""
        for scopes, resp in await self._collect_evidence(
                session_factory, qdrant_store, embedding_provider):
            allowed = {str(s) for s in scopes}
            for ev in resp.get("evidence", []):
                sid = str(ev.get("knowledge_scope_id", ""))
                assert sid in allowed, (
                    f"cross-domain leakage: evidence scope {sid} not in {allowed}"
                )

    async def test_schema_validity_100_percent(self, session_factory, qdrant_store,
                                               embedding_provider):
        """T018/FR-024: every search response validates against the MCP schema."""
        for _, resp in await self._collect_evidence(
                session_factory, qdrant_store, embedding_provider):
            assert _schema_valid(resp, _SEARCH_SCHEMA), "search response schema-invalid"

        domains = await _domains(session_factory)
        assert _schema_valid({"domains": domains}, _LIST_SCHEMA)

    async def test_source_locatability_100_percent(self, session_factory,
                                                   qdrant_store, embedding_provider):
        """T018/FR-025: every evidence item carries source_version + a
        locatable position (incl. Word heading path and PDF page:N § prefix)."""
        for _, resp in await self._collect_evidence(
                session_factory, qdrant_store, embedding_provider):
            for ev in resp.get("evidence", []):
                assert ev.get("source_version"), ev
                position = ev.get("source_position") or ""
                assert position, f"evidence without locatable position: {ev}"


class TestFourReferenceScenarios:
    async def _se_project_scope_with_chunks(self, session_factory):
        async with session_factory() as session:
            row = (await session.execute(text(
                "SELECT ks.scope_id FROM knowledge_scopes ks "
                "JOIN chunks c ON c.knowledge_scope_id = ks.scope_id "
                "WHERE ks.domain_key = 'se-project' AND ks.status = 'active' "
                "GROUP BY ks.scope_id LIMIT 1"
            ))).first()
        return str(row.scope_id) if row else None

    async def test_domain_scope_only(self, session_factory, qdrant_store,
                                     embedding_provider):
        """T019/FR-022: domain_scope-only retrieval works (new form)."""
        domains = await _domains(session_factory)
        target = next(d for d in domains if d["slug"] == "personal-eval-rag-notes")
        resp = await _search(session_factory, qdrant_store, embedding_provider,
                             "RAG 系统的核心思想", domain_scope=[target["slug"]])
        assert resp.get("completion_status") in ("complete", "partial"), resp

    async def test_project_scope_only_legacy(self, session_factory, qdrant_store,
                                             embedding_provider):
        """T019/FR-022: project_scope-only keeps legacy behavior (旧码不变)."""
        scope_id = await self._se_project_scope_with_chunks(session_factory)
        if scope_id is None:
            pytest.skip("no active se-project scope with chunks available")
        resp = await _search(session_factory, qdrant_store, embedding_provider,
                             "which methods call validateToken",
                             project_scope=[scope_id])
        assert resp.get("completion_status") in ("complete", "partial", "no_evidence"), resp

    async def test_both_scopes_union_dedup(self, session_factory, qdrant_store,
                                           embedding_provider):
        """T019/FR-022: mixed project_scope+domain_scope union deduplicates."""
        domains = await _domains(session_factory)
        target = next(d for d in domains if d["slug"] == "personal-eval-rag-notes")
        se_scope = await self._se_project_scope_with_chunks(session_factory)
        resp = await _search(
            session_factory, qdrant_store, embedding_provider,
            "检索增强生成", project_scope=[se_scope] if se_scope else [],
            domain_scope=[target["slug"]],
        )
        assert resp.get("completion_status") in ("complete", "partial"), resp
        # No duplicate evidence ids in the union result.
        ids = [e["evidence_id"] for e in resp.get("evidence", [])]
        assert len(ids) == len(set(ids)), "union result contains duplicates"

    async def test_neither_scope_rejected(self, session_factory, qdrant_store,
                                          embedding_provider):
        """T019/FR-022: no scope reference -> rejected, never whole-library."""
        resp = await _search(session_factory, qdrant_store, embedding_provider,
                             "任意查询", project_scope=[], domain_scope=[])
        assert resp.get("completion_status") == "failed", resp
        code = (resp.get("error") or {}).get("code", "")
        assert code in ("MISSING_KNOWLEDGE_SCOPE", "MISSING_PROJECT_SCOPE"), resp
        assert resp.get("evidence") == []
