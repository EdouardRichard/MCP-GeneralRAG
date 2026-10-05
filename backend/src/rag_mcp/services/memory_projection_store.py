import asyncio
import json
from datetime import datetime
from pathlib import Path

from qdrant_client.models import PointStruct
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from rag_mcp.config import get_settings
from rag_mcp.models.memory_projection import MemoryEntry
from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
from rag_mcp.models.memory_salience import MemorySalience
from rag_mcp.models.memory_views import MemoryLink, MemorySummaryNode
from rag_mcp.services.memory_reducer import projection_fingerprint, require_reducer_state


VIEW_KEYS = {"relation": "entries", "dense": "dense", "links": "links",
             "summary": "summary", "file": "files", "salience": "salience"}


class MemoryProjectionStore:
    """Projection state is writable only from reducer output."""

    def __init__(self, session=None, *, qdrant_store=None, embedding_provider=None, projection_root=None):
        self._states = {}
        self.session = session
        self.qdrant = qdrant_store
        self.embedding = embedding_provider
        self.root = Path(projection_root or Path(get_settings().data_root) / "memory_projection").resolve()

    def upsert_from_reducer(self, memory_id, reducer_state):
        from rag_mcp.services.memory_reducer import require_reducer_state
        require_reducer_state(reducer_state)
        self._states[memory_id] = {"status": "complete", "state": reducer_state}
        return self._states[memory_id]

    def mark_failed(self, memory_id, path):
        self._states[memory_id] = {"status": "failed", "failed_path": path}
        return self._states[memory_id]

    def recallable(self, memory_id):
        return self._states.get(memory_id, {}).get("status") == "complete"

    async def current(self, scope_id):
        return await self.session.get(MemoryProjectionMeta, f"current:{scope_id}", populate_existing=True)

    async def _authorize(self, state, scope_id, event_id):
        require_reducer_state(state)
        if any(row["knowledge_scope_id"] != scope_id for row in state["entries"].values()):
            raise ValueError("MEMORY_EVIDENCE_SCOPE_MISMATCH")
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
        require_reducer_state(state)
        model = get_settings().embedding_model.replace("/", "_").replace("-", "_")
        collection = f"memories_dense_{model}_012_v1_s{scope_id}_e{event_id}"
        if not await asyncio.to_thread(self.qdrant.collection_exists, collection):
            await asyncio.to_thread(self.qdrant.create_collection, collection, self.embedding.get_dimension())
        rows = list(state["dense"].values())
        if rows:
            vectors = await self.embedding.embed_texts([row["content_text"] for row in rows])
            points = [PointStruct(id=row["memory_id"], vector=vector,
                                  payload={**row, "knowledge_scope_id": str(scope_id)})
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
        (directory / "INDEX.md").write_text("\n".join(sorted(state["files"])), encoding="utf-8")

    async def _materialize_files(self, state, scope_id, event_id):
        require_reducer_state(state)
        directory = self.root / str(scope_id) / str(event_id)
        for key, row in state["files"].items():
            path = (directory / key).resolve()
            if not path.is_relative_to(directory.resolve()) or row["knowledge_scope_id"] != scope_id:
                raise ValueError("MEMORY_EVIDENCE_SCOPE_MISMATCH")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(row["body"], encoding="utf-8")

    async def _materialize_salience(self, state, scope_id, event_id):
        await self._authorize(state, scope_id, event_id)
        for row in state["salience"].values():
            values = {key: value for key, value in row.items() if key in MemorySalience.__table__.columns}
            if values.get("last_access_at"):
                values["last_access_at"] = datetime.fromisoformat(values["last_access_at"])
            await self._upsert(MemorySalience, values, "memory_id")

    async def materialize(self, state, scope_id, event_id):
        await self._materialize_relation(state, scope_id, event_id)
        collection = await self._materialize_dense(state, scope_id, event_id)
        await self._materialize_links(state, scope_id, event_id)
        await self._materialize_summary(state, scope_id, event_id)
        await self._materialize_files(state, scope_id, event_id)
        await self._materialize_salience(state, scope_id, event_id)
        await self._authorize(state, scope_id, event_id)
        for name, key in VIEW_KEYS.items():
            await self._upsert(MemoryProjectionMeta, {
                "projection_id": f"{scope_id}:{event_id}:{name}", "projection_type": name,
                "knowledge_scope_id": scope_id, "source_event_id": event_id, "status": "complete",
                "fingerprint": projection_fingerprint(state[key]),
                "payload": {"state": state[key], "collection": collection, "root": str(self.root)},
            }, "projection_id")
        await self._upsert(MemoryProjectionMeta, {
            "projection_id": f"current:{scope_id}", "projection_type": "manifest",
            "knowledge_scope_id": scope_id, "source_event_id": event_id, "status": "complete",
            "fingerprint": projection_fingerprint(state),
            "payload": {"state": state.export(), "collection": collection, "root": str(self.root)},
        }, "projection_id")
        await self.session.flush()

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
            collection_name=current.payload["collection"], limit=10000, with_payload=True, with_vectors=True)
        actual["dense"] = {int(point.id): {**point.payload, "knowledge_scope_id": int(point.payload["knowledge_scope_id"])} for point in points}
        if points and any(not point.vector or len(point.vector) != self.embedding.get_dimension() for point in points):
            raise ValueError("invalid real vector projection")
        for name, model in (("links", MemoryLink), ("summary", MemorySummaryNode)):
            rows = (await self.session.execute(select(model).where(model.knowledge_scope_id == scope_id, model.revision_id == revision))).scalars().all()
            actual[name] = {row.node_key: row.data for row in rows}
        directory = Path(current.payload["root"]) / str(scope_id) / str(revision)
        actual["file"] = {}
        for key, row in state["files"].items():
            path = directory / key
            if path.is_file():
                actual["file"][key] = {**row, "body": path.read_text(encoding="utf-8")}
        rows = (await self.session.execute(select(MemorySalience).join(MemoryEntry).where(MemoryEntry.knowledge_scope_id == scope_id))).scalars().all()
        actual["salience"] = {}
        for row in rows:
            expected_row = state["salience"].get(row.memory_id)
            if expected_row:
                actual["salience"][row.memory_id] = {**expected_row, "salience": row.salience,
                    "access_count": row.access_count, "decay_rate": row.decay_rate,
                    "last_access_at": row.last_access_at.isoformat() if row.last_access_at else None}
        report = {}
        for name, key in VIEW_KEYS.items():
            target = expected_relation if name == "relation" else state[key]
            fingerprint = projection_fingerprint(actual[name])
            matches = fingerprint == projection_fingerprint(target)
            if name == "summary":
                matches = matches and (directory / "DIGEST.md").read_text(encoding="utf-8") == json.dumps(state["summary"], sort_keys=True, ensure_ascii=False)
            report[name] = {"count": len(actual[name]), "fingerprint": fingerprint, "matches_replay": matches}
        return report

