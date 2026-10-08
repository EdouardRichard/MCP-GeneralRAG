"""T042 — consumption layer: materialisation, rebuild, drift, propagation (US6).

These tests run against the real isolated PostgreSQL test database through the
shared ``db_session`` / ``engine`` fixtures. They never touch Qdrant and never
call an embedding model: the tree is derived from the append-only event log
through ``MemoryHistory``, which is exactly the production read path of the
consumption layer — so "zero model calls" is a property of the real code path,
not of a stub.

Layer coexistence (FR-025a/SC-016) is asserted directly: the revision tree
(``<numeric scope id>/<numeric projection id>/012-v1/<numeric scope id>/<kind>/``
plus ``DIGEST.md``/``INDEX.md`` and ``archives/``) is materialised first and must
stay byte-identical while the consumption layer is written, cleared and rebuilt.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path

import pytest

from rag_mcp.config import get_settings
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.runtime import memory_projection as projection
from rag_mcp.utils.snowflake import generate_id

SLUG_PREFIX = "c014-"


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path, monkeypatch):
    """Keep every filesystem effect inside the test's temporary directory."""
    monkeypatch.chdir(tmp_path)
    yield
    projection.set_consumer(None)
    projection._DIRTY_SCOPES.clear()
    projection._WORKER_TASKS.clear()


async def _scope(session):
    key = f"{SLUG_PREFIX}{generate_id() % 10**10:010d}"
    session.add(DomainProfile(domain_key=key, name=key, supported_formats=["markdown"],
                              graph_relations={}, default_capabilities={}, is_builtin=False,
                              memory_policy={}))
    await session.flush()
    scope = KnowledgeScope(scope_id=generate_id(), scope_type="public", slug=key, name=key,
                           domain_key=key, status="active")
    session.add(scope)
    await session.commit()
    return scope.scope_id, key


async def _id_floor(session) -> int:
    """Globally unique event identities: ``memory_events.event_id`` is a PK."""
    from sqlalchemy import func, select

    from rag_mcp.models.memory_event import MemoryEvent

    current = await session.scalar(select(func.max(MemoryEvent.event_id)))
    return int(current or 0) + 1_000_000


def _event(scope_id: int, memory_id: int, kind: str, text: str, *, event_id: int, **extra) -> dict:
    """A real authority event payload built with the production sanitizers.

    The append-only store re-runs ``sanitize_submission`` and requires the
    stored payload to equal its sanitized form, so the fixture derives the
    payload from exactly the helpers ``MemoryService.record()`` uses.
    """
    from datetime import datetime, timedelta, timezone

    from rag_mcp.services.memory_validators import derive_ttl, sanitize_submission

    stamp = datetime.now(timezone.utc)
    metadata = {
        "kind": kind,
        "provenance": extra.pop("provenance", "soft"),
        "inference_meta": {"source": "014 integration fixture", "confidence": 0.8,
                           "model_version": "fixture-v1", "time": stamp.isoformat(),
                           "supporting_evidence": []},
        "confidence": extra.pop("confidence", None),
        "title": extra.pop("title", None),
        "session_id": extra.pop("session_id", None),
        "agent_id": extra.pop("agent_id", None),
        "task_context": extra.pop("task_context", None),
        "supersedes_memory_id": extra.pop("supersedes_memory_id", None),
        "evidence_refs": sorted(set(extra.pop("evidence_refs", []))),
        "tags": sorted(set(extra.pop("tags", []))),
    }
    payload = {**metadata, "content_text": text,
               "content_hash": hashlib.sha256(text.encode()).hexdigest()}
    sanitized = sanitize_submission({**payload, "content": text})[1]
    payload["status"] = sanitized.status
    payload["injection_flags"] = sanitized.injection_flags
    payload["submission_meta"] = metadata
    payload["provenance_validation"] = {"provenance": metadata["provenance"], "validated": True,
                                        "attributions": []}
    payload["decay_rate"] = 0.05
    payload["created_at"] = stamp.isoformat()
    payload["updated_at"] = stamp.isoformat()
    ttl = derive_ttl(kind, {})
    payload["expires_at"] = (stamp + timedelta(days=ttl)).isoformat() if ttl else None
    assert not extra, f"unexpected fixture keys: {sorted(extra)}"
    return {
        "event_id": event_id,
        "aggregate_id": memory_id,
        "knowledge_scope_id": scope_id,
        "event_type": "assert",
        "occurred_at": stamp,
        "valid_from": stamp,
        "actor": "memory_tool",
        "request_id": f"req-{memory_id}",
        "authority": {"source": "inference"},
        "scope_meta": {"knowledge_scope_id": scope_id},
        "mutability": {"correction": "supersede"},
        "provenance_meta": payload["provenance_validation"],
        "recoverability": {"source": "event_log"},
        "actionability": "evidence",
        "payload": payload,
    }


async def _append(session, **fields):
    from rag_mcp.models.memory_event import MemoryEvent
    from rag_mcp.services.memory_event_store import MemoryEventStore

    await MemoryEventStore(session).append(MemoryEvent(**fields))
    await session.commit()


async def _consumer(engine, tmp_path, monkeypatch, *, lock=True):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    monkeypatch.setattr(projection, "_enabled", lambda: lock)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return projection.MemoryProjectionConsumer(root=tmp_path / "consumption",
                                               source=projection.InProcessTreeSource(factory))


class _CountingSource:
    """Wrap a tree source and count how often it re-derived state from the log."""

    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    async def state(self, scope_id):
        self.calls += 1
        return await self.inner.state(scope_id)


def _revision_tree_marker(data_root: Path, scope_id: int) -> Path:
    """A representative 012 revision subtree, created before 014 runs."""
    revision = data_root / "memory_projection" / str(scope_id) / "9001"
    (revision / "012-v1" / str(scope_id) / "episodic").mkdir(parents=True, exist_ok=True)
    (revision / "archives" / str(scope_id)).mkdir(parents=True, exist_ok=True)
    (revision / "DIGEST.md").write_bytes(b'{"frozen":"012 digest"}')
    (revision / "INDEX.md").write_bytes(f"012-v1/{scope_id}/episodic/1.md".encode())
    (revision / "012-v1" / str(scope_id) / "episodic" / "1.md").write_bytes(b"# Memory 1\n\n012 body")
    (revision / "archives" / str(scope_id) / "1.json").write_bytes(b'[{"event_id":1}]')
    return revision


def _snapshot(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


# ---------------------------------------------------------------------------
# materialise / rebuild / drift / coexistence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_materialise_rebuild_and_drift_detection(db_session, engine, tmp_path, monkeypatch):
    scope_id, slug = await _scope(db_session)
    floor = await _id_floor(db_session)
    await _append(db_session, **_event(scope_id, floor + 1, "episodic",
                                       "第一轮：发票抬头必须与合同主体一致。", event_id=floor + 1))
    await _append(db_session, **_event(scope_id, floor + 2, "semantic",
                                       "line one\nline two", event_id=floor + 2))
    await _append(db_session, **_event(scope_id, floor + 3, "procedural",
                                       "always confirm the header", event_id=floor + 3))

    data_root = Path(get_settings().data_root).resolve()
    revision = _revision_tree_marker(data_root, scope_id)
    before = _snapshot(revision)
    consumption_root = (tmp_path / "consumption").resolve()

    consumer = await _consumer(engine, tmp_path, monkeypatch)
    monkeypatch.setattr(consumer, "guard", projection.ConsumptionGuard(consumption_root))
    source = _CountingSource(consumer.source)
    consumer.source = source
    assert consumer.root == consumption_root

    report = await consumer.apply_tree(scope_id, session=db_session)
    assert report.status == "complete"
    assert report.file_count == 3
    assert report.guard_state == "readonly"
    await db_session.commit()
    manifest = consumer.guard.manifest(consumption_root / slug)
    assert sorted(manifest) == ["DIGEST.md", "INDEX.md", f"episodic/{floor + 1}.md",
                                f"procedural/{floor + 3}.md", f"semantic/{floor + 2}.md"]

    body = (consumption_root / slug / "episodic" / f"{floor + 1}.md").read_text(encoding="utf-8")
    assert body.split("---\n", 2)[2] == "第一轮：发票抬头必须与合同主体一致。\n"
    assert "\nuntrusted: true\n" in body
    assert "012 body" not in body

    # §7.5: registered in the dedicated table only, never in the six-view meta.
    from sqlalchemy import func, select

    from rag_mcp.models.memory_consumption import MemoryConsumptionProjection
    from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta

    row = await db_session.get(MemoryConsumptionProjection, scope_id)
    assert row is not None and row.scope_slug == slug and row.status == "complete"
    assert row.tree_fingerprint == report.tree_fingerprint
    assert row.guard_state == "readonly"
    assert await db_session.scalar(select(func.count()).select_from(MemoryProjectionMeta)
                                   .where(MemoryProjectionMeta.knowledge_scope_id == scope_id)) == 0

    # Two layouts coexist: the revision tree is byte-identical and holds no
    # consumption-layer directory.
    assert _snapshot(revision) == before
    assert (consumption_root / slug).is_dir()
    assert not list((data_root / "memory_projection").rglob(slug))

    # Drift: a direct filesystem write is detected and repaired by the worker.
    target = consumption_root / slug / "episodic" / f"{floor + 1}.md"
    projection._clear_readonly(target)
    target.write_text("host tampered with this", encoding="utf-8", newline="\n")
    stray = consumption_root / slug / "episodic" / "999999.md"
    projection._clear_readonly(stray)
    stray.write_text("unexpected", encoding="utf-8", newline="\n")

    repaired = await consumer.apply_tree(scope_id, session=db_session)
    await db_session.commit()
    assert repaired.repaired is True
    assert "episodic/999999.md" in repaired.unexpected_paths
    assert repaired.reason_code == "drift_detected"
    assert target.read_text(encoding="utf-8").split("---\n", 2)[2] == "第一轮：发票抬头必须与合同主体一致。\n"
    assert not stray.exists()
    assert _snapshot(revision) == before

    # Read path never repairs in place: reading only observes the drift.
    projection._clear_readonly(target)
    target.write_text("tampered again", encoding="utf-8", newline="\n")
    expected = projection.tree_manifest(projection.render_tree(
        (await consumer.source.state(scope_id)).state, slug=slug))[f"episodic/{floor + 1}.md"]
    assert consumer.guard.manifest(consumption_root / slug)[f"episodic/{floor + 1}.md"] != expected
    assert target.read_text(encoding="utf-8") == "tampered again"


@pytest.mark.asyncio
async def test_full_rebuild_after_clearing_is_byte_identical_with_zero_model_calls(
        db_session, engine, tmp_path, monkeypatch):
    scope_id, slug = await _scope(db_session)
    floor = await _id_floor(db_session)
    await _append(db_session, **_event(scope_id, floor + 1, "episodic", "断点续接的上下文", event_id=floor + 1))
    await _append(db_session, **_event(scope_id, floor + 2, "semantic", "dense fact", event_id=floor + 2))

    consumer = await _consumer(engine, tmp_path, monkeypatch)
    source = _CountingSource(consumer.source)
    consumer.source = source
    first = await consumer.apply_tree(scope_id, session=db_session)
    first_manifest = consumer.guard.manifest(consumer.root / slug)

    # Clearing the layer means clearing the file bits first (contract §4).
    projection._clear_readonly_tree(consumer.root / slug)
    shutil.rmtree(consumer.root / slug)
    source.calls = 0
    rebuilt = await consumer.apply_tree(scope_id, session=db_session, force_rebuild=True)

    assert source.calls == 1, "a full rebuild re-derives state from the log exactly once"
    assert rebuilt.tree_fingerprint == first.tree_fingerprint
    assert consumer.guard.manifest(consumer.root / slug) == first_manifest
    assert not list((Path(get_settings().data_root).resolve() / "memory_projection").rglob(f"*{slug}*"))


@pytest.mark.asyncio
async def test_deletion_propagation_leaves_no_consumable_body(db_session, engine, tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from rag_mcp.models.memory_event import MemoryEvent
    from rag_mcp.services.memory_event_store import MemoryEventStore

    scope_id, slug = await _scope(db_session)
    floor = await _id_floor(db_session)
    await _append(db_session, **_event(scope_id, floor + 1, "episodic", "active content", event_id=floor + 1))
    await _append(db_session, **_event(scope_id, floor + 2, "episodic", "content to retract", event_id=floor + 2))

    consumer = await _consumer(engine, tmp_path, monkeypatch)
    await consumer.apply_tree(scope_id, session=db_session)
    published = consumer.root / slug / "episodic" / f"{floor + 2}.md"
    assert "content to retract" in published.read_text(encoding="utf-8")

    # Retraction is an authority event: it must propagate to the consumption
    # layer and leave no consumable body behind (FR-032/SC-013).
    await MemoryEventStore(db_session).append(MemoryEvent(**{
        "event_id": floor + 3, "aggregate_id": floor + 2, "knowledge_scope_id": scope_id,
        "event_type": "retract", "occurred_at": datetime.now(timezone.utc), "payload": {},
        "actor": "management", "request_id": "req-retract", "authority": {"source": "event_log"},
        "scope_meta": {"knowledge_scope_id": scope_id}, "mutability": {"correction": "supersede"},
        "provenance_meta": {}, "recoverability": {"source": "event_log"}, "actionability": None,
    }))
    await db_session.commit()

    report = await consumer.apply_tree(scope_id, session=db_session)
    assert report.file_count == 1
    assert not published.exists()
    for path in (consumer.root / slug).rglob("*"):
        if path.is_file():
            assert "content to retract" not in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# asynchronous, event-driven refresh (FR-031) and reconciliation (FR-031a)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dirty_nudge_schedules_one_bounded_worker_per_scope(db_session, engine, tmp_path, monkeypatch):
    scope_id, slug = await _scope(db_session)
    floor = await _id_floor(db_session)
    await _append(db_session, **_event(scope_id, floor + 1, "episodic", "写在前面", event_id=floor + 1))

    consumer = await _consumer(engine, tmp_path, monkeypatch)
    projection.set_consumer(consumer)

    projection.mark_memory_projection_dirty(scope_id)
    task = projection.worker_task(scope_id)
    assert task is not None, "the nudge must schedule a worker without awaiting it"
    projection.mark_memory_projection_dirty(scope_id)  # single-flight: no second worker
    assert projection.worker_task(scope_id) is task
    await asyncio.wait_for(asyncio.shield(task), 60)

    assert (consumer.root / slug / "episodic" / f"{floor + 1}.md").is_file()
    assert projection.worker_task(scope_id) is None
    assert (consumer.root / slug).is_dir()  # published by the worker, not left staging


@pytest.mark.asyncio
async def test_reconcile_removes_a_stale_scope_row_and_subtree(db_session, engine, tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    scope_id, slug = await _scope(db_session)
    floor = await _id_floor(db_session)
    await _append(db_session, **_event(scope_id, floor + 1, "episodic", "content", event_id=floor + 1))

    consumer = await _consumer(engine, tmp_path, monkeypatch)
    projection.set_consumer(consumer)
    await consumer.apply_tree(scope_id, session=db_session)
    await db_session.commit()  # release the registry row before the sweep opens its own session
    assert (consumer.root / slug).is_dir()

    # A scope that is no longer active is deletion propagation, not drift.
    scope = await db_session.get(KnowledgeScope, scope_id)
    scope.status = "archived"
    await db_session.commit()

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        report = await asyncio.wait_for(projection.reconcile(scope_id, session_factory=factory), 60)
        assert [item["status"] for item in report["processed"]] == ["removed"]
        assert not (consumer.root / slug).exists()
    finally:
        await _dispose_scope(scope_id)


async def _dispose_scope(scope_id: int) -> None:
    """Remove this test's derived registry rows without touching the event log."""
    from sqlalchemy import text

    from rag_mcp.db import get_session_factory

    async with get_session_factory()() as session:
        await session.execute(text("DELETE FROM memory_consumption_projection WHERE knowledge_scope_id = :scope"),
                              {"scope": scope_id})
        await session.commit()
