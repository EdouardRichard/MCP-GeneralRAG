class MemoryProjectionStore:
    """Projection state is writable only from reducer output."""

    def __init__(self):
        self._states = {}

    def upsert_from_reducer(self, memory_id, reducer_state):
        if not isinstance(reducer_state, dict) or "entries" not in reducer_state:
            raise TypeError("projection writes require reducer output")
        self._states[memory_id] = {"status": "complete", "state": reducer_state}
        return self._states[memory_id]

    def mark_failed(self, memory_id, path):
        self._states[memory_id] = {"status": "failed", "failed_path": path}
        return self._states[memory_id]

    def recallable(self, memory_id):
        return self._states.get(memory_id, {}).get("status") == "complete"

