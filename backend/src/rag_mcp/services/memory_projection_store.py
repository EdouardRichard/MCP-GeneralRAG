import asyncio
import gzip
import json
import math
from datetime import datetime
from pathlib import Path

from qdrant_client.models import PointStruct
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from rag_mcp.config import get_settings
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
from rag_mcp.models.memory_salience import MemorySalience
from rag_mcp.models.memory_views import MemoryLink, MemorySummaryNode
from rag_mcp.models.scope_binding import ScopeBinding
from rag_mcp.indexing.memory_vectors import revision_filter, revision_point_id
from rag_mcp.services.memory_reducer import projection_fingerprint, require_reducer_state


VIEW_KEYS = {"relation": "entries", "dense": "dense", "links": "links",
             "summary": "summary", "file": "files", "salience": "salience"}


def file_index(state):
    return "\n".join(sorted(key for key, row in state["files"].items() if row.get("retention_stage") != "archived"))


class ProjectionFailure(ValueError):
    def __init__(self, path):
        self.path = path
        super().__init__(f"MEMORY_WRITE_UNAVAILABLE:{path}")


class MemoryProjectionStore:
    """Projection state is writable only from reducer output."""

    def __init__(self, session=None, *, qdrant_store=None, embedding_provider=None, projection_root=None):
        self.session = session
        self.qdrant = qdrant_store
        self.embedding = embedding_provider
        self.root = Path(projection_root or Path(get_settings().data_root) / "memory_projection").resolve()
        self._verified_authority = None

    def upsert_from_reducer(self, memory_id, reducer_state):
        require_reducer_state(reducer_state)
        raise PermissionError("projection mutation requires current immutable log authority")

    def mark_failed(self, memory_id, path):
        raise PermissionError("projection mutation requires current immutable log authority")

    async def current(self, scope_id):
        return await self.session.get(MemoryProjectionMeta, f"current:{scope_id}", populate_existing=True)

    def _check_scope(self, state, scope_id):
        require_reducer_state(state)
        if any(row["knowledge_scope_id"] != scope_id for key in ("entries", "bindings") for row in state[key].values()):
            raise ValueError("MEMORY_EVIDENCE_SCOPE_MISMATCH")

    async def _authorize(self, state, scope_id, event_id):
        self._check_scope(state, scope_id)
        from rag_mcp.services.memory_event_store import MemoryEventStore
        from rag_mcp.services.memory_reducer import reduce_events

        await self.session.execute(text("SELECT pg_advisory_xact_lock(:scope)"), {"scope": scope_id})
        latest = await self.session.scalar(select(func.max(MemoryEvent.event_id)).where(MemoryEvent.knowledge_scope_id == scope_id))
        if latest != event_id:
            raise ValueError("projection authority must match current immutable log replay")
        # Reuse only an exact log verification within the same root/savepoint.
        # Each adapter still locks the scope and checks its latest log revision.
        transaction = self.session.sync_session.get_nested_transaction() or self.session.sync_session.get_transaction()
        fingerprint = projection_fingerprint(state)
        authority = (transaction, scope_id, event_id, fingerprint)
        if self._verified_authority != authority:
            history = await MemoryEventStore(self.session).replay(scope_id)
            if not history or history[-1]["event_id"] != event_id or fingerprint != projection_fingerprint(reduce_events(history)):
                raise ValueError("projection authority must match current immutable log replay")
            self._verified_authority = authority
        await self.session.execute(text("SET LOCAL ROLE rag_memory_reducer"))
        await self.session.execute(text("SELECT set_config('rag_memory.reducer_event', :event, true)"), {"event": str(event_id)})

    async def _upsert(self, model, values, key):
        statement = insert(model).values(**values)
        await self.session.execute(statement.on_conflict_do_update(
            index_elements=[key], set_={name: getattr(statement.excluded, name) for name in values if name != key}
        ))

    async def _materialize_relation(self, state, scope_id, event_id, *, write_status="complete"):
        await self._authorize(state, scope_id, event_id)
        columns = {column.name: column for column in MemoryEntry.__table__.columns}
        for row in state["entries"].values():
            values = {key: value for key, value in row.items() if key in columns}
            for name, value in tuple(values.items()):
                if value is not None and isinstance(value, str) and name.endswith("_at") or value is not None and isinstance(value, str) and name in {"valid_from", "valid_to"}:
                    values[name] = datetime.fromisoformat(value)
            values["write_status"] = write_status
            await self._upsert(MemoryEntry, values, "memory_id")

    async def _materialize_dense(self, state, scope_id, event_id):
        await self._authorize(state, scope_id, event_id)
        model = get_settings().embedding_model.replace("/", "_").replace("-", "_")
        collection = f"memories_dense_{model}_012_v2"
        if not await asyncio.to_thread(self.qdrant.collection_exists, collection):
            await asyncio.to_thread(self.qdrant.create_collection, collection, self.embedding.get_dimension())
        rows = list(state["dense"].values())
        if rows:
            vectors = await self.embedding.embed_texts([row["content_text"] for row in rows])
            points = [PointStruct(id=revision_point_id(scope_id, event_id, row["memory_id"]), vector=vector,
                                  payload={**row, "knowledge_scope_id": str(scope_id), "projection_revision": str(event_id)})
                      for row, vector in zip(rows, vectors, strict=True)]
            await asyncio.to_thread(self.qdrant._client.upsert, collection_name=collection, points=points, wait=True)
        return collection

    async def _materialize_links(self, state, scope_id, event_id):
        await self._authorize(state, scope_id, event_id)
        for key, row in state["links"].items():
            await self._upsert(MemoryLink, {"row_id": f"{scope_id}:{event_id}:{key}",
                "knowledge_scope_id": scope_id, "revision_id": event_id, "node_key": key, "data": row}, "row_id")

    async def _materialize_summary(self, state, scope_id, event_id):
        await self._authorize(state, scope_id, event_id)
        for key, rows in state["summary"].items():
            await self._upsert(MemorySummaryNode, {"row_id": f"{scope_id}:{event_id}:{key}",
                "knowledge_scope_id": scope_id, "revision_id": event_id, "node_key": key, "data": rows}, "row_id")
        directory = self.root / str(scope_id) / str(event_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "DIGEST.md").write_text(json.dumps(state["summary"], sort_keys=True, ensure_ascii=False), encoding="utf-8")
        (directory / "INDEX.md").write_text(file_index(state), encoding="utf-8")

    async def _materialize_files(self, state, scope_id, event_id):
        await self._authorize(state, scope_id, event_id)
        directory = (self.root / str(scope_id) / str(event_id)).resolve()
        if not directory.is_relative_to(self.root):
            raise ValueError("MEMORY_EVIDENCE_SCOPE_MISMATCH")
        expected = set(state["files"]) | {"DIGEST.md", "INDEX.md"}
        for path in directory.rglob("*"):
            if path.is_file() or path.is_symlink():
                if not path.resolve().is_relative_to(directory):
                    raise ValueError("MEMORY_EVIDENCE_SCOPE_MISMATCH")
                if path.relative_to(directory).as_posix() not in expected:
                    path.unlink()
        for key, row in state["files"].items():
            path = (directory / key).resolve()
            if not path.is_relative_to(directory.resolve()) or row["knowledge_scope_id"] != scope_id:
                raise ValueError("MEMORY_EVIDENCE_SCOPE_MISMATCH")
            path.parent.mkdir(parents=True, exist_ok=True)
            if key.endswith(".gz"):
                path.write_bytes(gzip.compress(row["body"].encode("utf-8"), mtime=0))
            else:
                path.write_text(row["body"], encoding="utf-8")

    async def _materialize_salience(self, state, scope_id, event_id):
        await self._authorize(state, scope_id, event_id)
        for row in state["salience"].values():
            values = {key: value for key, value in row.items() if key in MemorySalience.__table__.columns}
            for key in ("last_access_at", "reinforced_at"):
                if values.get(key):
                    values[key] = datetime.fromisoformat(values[key])
            await self._upsert(MemorySalience, values, "memory_id")

    async def _materialize_bindings(self, state, scope_id, event_id):
        if not state["bindings"]:
            return
        await self._authorize(state, scope_id, event_id)
        for row in state["bindings"].values():
            values = {key: value for key, value in row.items() if key in ScopeBinding.__table__.columns}
            existing = await self.session.get(ScopeBinding, values["binding_id"], populate_existing=True)
            if existing and all(getattr(existing, key) == value for key, value in values.items()):
                continue
            await self._upsert(ScopeBinding, values, "binding_id")

    async def materialize(self, state, scope_id, event_id):
        collection = None
        for path in ("relation", "dense", "links", "summary", "files", "salience"):
            try:
                result = await getattr(self, f"_materialize_{path}")(state, scope_id, event_id)
                if path == "dense":
                    collection = result
            except Exception as error:
                raise ProjectionFailure(path) from error
        await self._authorize(state, scope_id, event_id)
        await self._materialize_bindings(state, scope_id, event_id)
        for name, key in VIEW_KEYS.items():
            await self._upsert(MemoryProjectionMeta, {
                "projection_id": f"{scope_id}:{event_id}:{name}", "projection_type": name,
                "knowledge_scope_id": scope_id, "source_event_id": event_id, "status": "complete",
                "fingerprint": projection_fingerprint(state[key]),
                "payload": {"state": state[key], "collection": collection, "root": str(self.root), "dense_revision": event_id},
            }, "projection_id")
        await self._upsert(MemoryProjectionMeta, {
            "projection_id": f"current:{scope_id}", "projection_type": "manifest",
            "knowledge_scope_id": scope_id, "source_event_id": event_id, "status": "complete",
            "fingerprint": projection_fingerprint(state),
            "payload": {"state": state.export(), "collection": collection, "root": str(self.root), "dense_revision": event_id},
        }, "projection_id")
        await self.session.flush()

    async def retain_failure(self, state, scope_id, event_id, path):
        await self._materialize_relation(state, scope_id, event_id, write_status="failed")
        await self._upsert(MemoryProjectionMeta, {
            "projection_id": f"pending:{scope_id}:{event_id}", "projection_type": "pending",
            "knowledge_scope_id": scope_id, "source_event_id": event_id, "status": "failed",
            "fingerprint": projection_fingerprint(state),
            "payload": {"state": state.export(), "failed_paths": [path]},
        }, "projection_id")

    async def inspect(self, state, scope_id):
        require_reducer_state(state)
        current = await self.current(scope_id)
        if not current or current.status != "complete":
            raise ValueError("MEMORY_WRITE_UNAVAILABLE")
        revision = current.source_event_id
        actual = {}
        rows = (await self.session.execute(select(MemoryEntry).where(
            MemoryEntry.knowledge_scope_id == scope_id, MemoryEntry.write_status == "complete"
        ).execution_options(populate_existing=True))).scalars().all()
        expected = state["entries"]
        actual["relation"] = {}
        for row in rows:
            if row.memory_id not in expected:
                actual["relation"][row.memory_id] = {"unexpected": True}
                continue
            projected = {}
            for key, value in expected[row.memory_id].items():
                if key not in MemoryEntry.__table__.columns:
                    continue
                stored = getattr(row, key)
                projected[key] = stored.isoformat() if isinstance(stored, datetime) else stored
            actual["relation"][row.memory_id] = projected
        expected_relation = {mid: {key: value for key, value in row.items() if key in MemoryEntry.__table__.columns}
                             for mid, row in expected.items()}
        points, _ = await asyncio.to_thread(self.qdrant._client.scroll,
            collection_name=current.payload["collection"], scroll_filter=revision_filter(scope_id, current.payload.get("dense_revision")),
            limit=10000, with_payload=True, with_vectors=True)
        actual["dense"] = {int(point.payload["memory_id"]): {
            **{key: value for key, value in point.payload.items() if key != "projection_revision"},
            "knowledge_scope_id": int(point.payload["knowledge_scope_id"])} for point in points}
        expected_ids = sorted(state["dense"])
        vectors = await self.embedding.embed_texts([state["dense"][mid]["content_text"] for mid in expected_ids])
        expected_vectors = dict(zip(expected_ids, vectors, strict=True))
        actual_vectors = {int(point.payload["memory_id"]): point.vector for point in points}
        vectors_match = set(actual_vectors) == set(expected_vectors) and all(
            isinstance(actual_vectors[mid], list) and len(actual_vectors[mid]) == len(vector)
            and all(math.isclose(actual, expected, abs_tol=1e-6, rel_tol=1e-5)
                    for actual, expected in zip(actual_vectors[mid], vector, strict=True))
            for mid, vector in expected_vectors.items())
        for name, model in (("links", MemoryLink), ("summary", MemorySummaryNode)):
            rows = (await self.session.execute(select(model).where(model.knowledge_scope_id == scope_id, model.revision_id == revision))).scalars().all()
            actual[name] = {row.node_key: row.data for row in rows}
        directory = Path(current.payload["root"]) / str(scope_id) / str(revision)
        actual["file"] = {}
        expected_paths = set(state["files"]) | {"DIGEST.md", "INDEX.md"}
        extra_files = sorted(path.relative_to(directory).as_posix() for path in directory.rglob("*")
                             if (path.is_file() or path.is_symlink()) and path.relative_to(directory).as_posix() not in expected_paths)
        for key, row in state["files"].items():
            path = directory / key
            if path.is_file():
                actual["file"][key] = {**row, "body": gzip.decompress(path.read_bytes()).decode("utf-8") if key.endswith(".gz") else path.read_text(encoding="utf-8")}
        rows = (await self.session.execute(select(MemorySalience, MemoryEntry).join(MemoryEntry).where(MemoryEntry.knowledge_scope_id == scope_id))).all()
        actual["salience"] = {}
        for row, entry in rows:
            expected_row = state["salience"].get(row.memory_id)
            if expected_row:
                actual["salience"][row.memory_id] = {"memory_id": row.memory_id,
                    "knowledge_scope_id": entry.knowledge_scope_id, "evidence_refs": entry.evidence_refs,
                    "provenance": entry.provenance, "inference_meta": entry.inference_meta, "salience": row.salience,
                    "access_count": row.access_count, "decay_rate": row.decay_rate,
                    "reinforced_at": row.reinforced_at.isoformat() if row.reinforced_at else None,
                    "last_access_at": row.last_access_at.isoformat() if row.last_access_at else None}
        report = {}
        for name, key in VIEW_KEYS.items():
            target = expected_relation if name == "relation" else state[key]
            fingerprint = projection_fingerprint(actual[name])
            matches = fingerprint == projection_fingerprint(target)
            if name == "dense":
                matches = matches and vectors_match
                fingerprint = projection_fingerprint({"payload": actual[name], "vectors": actual_vectors})
            if name == "file":
                matches = matches and not extra_files and (directory / "INDEX.md").read_text(encoding="utf-8") == file_index(state)
                fingerprint = projection_fingerprint({"files": actual[name], "unexpected": extra_files})
            if name == "summary":
                matches = matches and (directory / "DIGEST.md").read_text(encoding="utf-8") == json.dumps(state["summary"], sort_keys=True, ensure_ascii=False)
            report[name] = {"count": len(actual[name]), "fingerprint": fingerprint, "matches_replay": matches}
        return report

