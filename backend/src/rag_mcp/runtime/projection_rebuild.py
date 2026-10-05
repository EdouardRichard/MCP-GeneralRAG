from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from sqlalchemy import select, text

from rag_mcp.models.memory_history import MemorySnapshot, MemoryArchive, MemoryArchivedEvent
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_reducer import reduce_events, projection_fingerprint, ReducerState
from rag_mcp.utils.snowflake import generate_id

SNAPSHOT_VIEWS = {"relation": "entries", "dense": "dense", "links": "links", "summary": "summary", "file": "files", "salience": "salience"}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass
class RebuildResult:
    fingerprint: str
    status: str = "complete"
    state: ReducerState | None = None
    source: str = "full_log"


class ProjectionRebuilder:
    projection_types = ("relation", "vector", "links", "summary", "file", "salience")

    def rebuild(self, events, snapshot=None):
        events = list(events)
        if snapshot is not None:
            covered = snapshot.get("covered_through_event_id", 0)
            return self.restore(snapshot=snapshot, delta=[event for event in events if event["event_id"] > covered], full_events=events)
        state = reduce_events(events)
        return RebuildResult(projection_fingerprint(state), state=state)

    def restore(self, *, snapshot, delta, full_events=None):
        try:
            if not snapshot or snapshot.get("status") != "complete" or snapshot.get("schema_version") != 1:
                raise ValueError("SNAPSHOT_INVALID")
            prefix = snapshot["source_events"]
            scope_id = snapshot["scope_id"]
            covered = snapshot["covered_through_event_id"]
            if not prefix or prefix[-1]["event_id"] != covered or any(event["knowledge_scope_id"] != scope_id for event in prefix):
                raise ValueError("SNAPSHOT_INVALID")
            base = reduce_events(prefix)
            fingerprints = {name: projection_fingerprint(base[key]) for name, key in SNAPSHOT_VIEWS.items()}
            if fingerprints != snapshot["fingerprints"] or snapshot.get("state_fingerprint") != projection_fingerprint(base):
                raise ValueError("SNAPSHOT_INVALID")
            if full_events is not None and prefix != [event for event in full_events if event["event_id"] <= covered]:
                raise ValueError("SNAPSHOT_INVALID")
            if any(event["knowledge_scope_id"] != scope_id or event["event_id"] <= covered for event in delta):
                raise ValueError("SNAPSHOT_INVALID")
            state = reduce_events(delta, initial_state=base)
            return RebuildResult(projection_fingerprint(state), state=state, source="snapshot_delta")
        except (KeyError, ValueError, TypeError):
            if full_events is not None:
                return self.rebuild(full_events)
            raise ValueError("SNAPSHOT_INVALID") from None


class MemoryHistory:
    def __init__(self, service):
        self.service, self.session = service, service.session

    async def _latest(self, scope_id):
        return await self.session.scalar(select(MemorySnapshot).where(MemorySnapshot.knowledge_scope_id == scope_id)
                                         .order_by(MemorySnapshot.covered_through_event_id.desc()).limit(1))

    async def capture(self, scope_id, *, now=None, force=False):
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:scope)"), {"scope": scope_id})
        events = await MemoryEventStore(self.session).replay(scope_id)
        if not events:
            return None
        reference = now or datetime.now(timezone.utc)
        latest = await self._latest(scope_id)
        fresh = [event for event in events if latest is None or event["event_id"] > latest.covered_through_event_id]
        if not fresh:
            return None
        since = latest.created_at if latest else datetime.fromisoformat(events[0]["occurred_at"])
        if not force and len(fresh) < 10000 and reference - since < timedelta(hours=24):
            return None
        current = await self.service.projections.current(scope_id)
        if current is None or current.source_event_id != events[-1]["event_id"]:
            raise ValueError("MEMORY_WRITE_UNAVAILABLE")
        if not all(row["matches_replay"] for row in (await self.service.inspect_projections(scope_id)).values()):
            raise ValueError("MEMORY_WRITE_UNAVAILABLE")
        state = reduce_events(events)
        payload = {"status": "complete", "schema_version": 1, "scope_id": scope_id,
            "covered_through_event_id": events[-1]["event_id"], "covered_through_occurred_at": events[-1]["occurred_at"],
            "source_events": events, "state_fingerprint": projection_fingerprint(state),
            "fingerprints": {name: projection_fingerprint(state[key]) for name, key in SNAPSHOT_VIEWS.items()}}
        self.session.add(MemorySnapshot(snapshot_id=generate_id(), knowledge_scope_id=scope_id,
            covered_through_event_id=events[-1]["event_id"], payload=payload,
            fingerprint=hashlib.sha256(encoded(payload)).hexdigest(), created_at=reference))
        await self.session.commit()
        return payload

    async def load(self, scope_id):
        events = await MemoryEventStore(self.session).replay(scope_id)
        latest = await self._latest(scope_id)
        snapshot = latest.payload if latest and hashlib.sha256(encoded(latest.payload)).hexdigest() == latest.fingerprint else None
        if snapshot is not None:
            prefix = [event for event in events if event["event_id"] <= latest.covered_through_event_id]
            if snapshot.get("source_events") != prefix:
                raise ValueError("MEMORY_WRITE_UNAVAILABLE: incomplete immutable checkpoint log")
            return ProjectionRebuilder().rebuild(events, snapshot=snapshot)
        return ProjectionRebuilder().rebuild(events)

    async def archive(self, scope_id, *, now=None):
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:scope)"), {"scope": scope_id})
        reference = now or datetime.now(timezone.utc)
        events = await MemoryEventStore(self.session).replay(scope_id)
        online = await MemoryEventStore(self.session).replay_online(scope_id)
        latest = await self._latest(scope_id)
        if latest is not None and (hashlib.sha256(encoded(latest.payload)).hexdigest() != latest.fingerprint
            or ProjectionRebuilder().rebuild(events, snapshot=latest.payload).source != "snapshot_delta"):
            latest = None
        protected = set()
        for event in events:
            if event["event_type"] in {"revise", "retract", "consolidate", "grant", "rollback"}:
                protected.add(event["aggregate_id"])
                protected.add(event["payload"].get("supersedes_memory_id"))
                protected.add(event["payload"].get("event_point"))
                protected.update(event["payload"].get("impact", {}).get("memory_ids", []))
            for ref in (event["payload"].get("inference_meta") or {}).get("supporting_evidence", []):
                identifier = ref.removeprefix("memory:")
                if identifier.isdecimal():
                    protected.add(int(identifier))
        eligible = [event for event in online if
            event["event_type"] == "access" and datetime.fromisoformat(event["occurred_at"]) < reference - timedelta(days=90)
            or event["event_type"] == "assert" and latest is not None and event["event_id"] <= latest.covered_through_event_id
            and event["aggregate_id"] not in protected]
        counts = {"access_count": sum(event["event_type"] == "access" for event in eligible),
                  "assert_count": sum(event["event_type"] == "assert" for event in eligible)}
        if not eligible:
            return counts
        archive_id = generate_id()
        root = self.service.projections.root
        path = (root / "archives" / str(scope_id) / f"{archive_id}.json").resolve()
        if not path.is_relative_to(root):
            raise ValueError("MEMORY_EVIDENCE_SCOPE_MISMATCH")
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = encoded(eligible)
        path.write_bytes(blob)
        self.session.add(MemoryArchive(archive_id=archive_id, knowledge_scope_id=scope_id,
            path=str(path), fingerprint=hashlib.sha256(blob).hexdigest(), created_at=reference))
        await self.session.flush()
        self.session.add_all([MemoryArchivedEvent(event_id=event["event_id"], archive_id=archive_id) for event in eligible])
        await self.session.commit()
        return {**counts, "archive_id": archive_id, "fingerprint": hashlib.sha256(blob).hexdigest()}
