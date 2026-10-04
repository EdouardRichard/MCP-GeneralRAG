from dataclasses import dataclass
from rag_mcp.services.memory_reducer import reduce_events, projection_fingerprint


@dataclass
class RebuildResult:
    fingerprint: str
    status: str = "complete"


class ProjectionRebuilder:
    projection_types = ("relation", "vector", "links", "summary", "file", "salience")

    def rebuild(self, events, snapshot=None):
        return RebuildResult(projection_fingerprint(reduce_events(events)))

    def restore(self, *, snapshot, delta):
        if not snapshot or snapshot.get("status") != "complete":
            raise ValueError("SNAPSHOT_INVALID")
        return self.rebuild(delta, snapshot=snapshot)
