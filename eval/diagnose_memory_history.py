"""Read-only timing of retained history; no event or projection writes."""
import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter

from sqlalchemy import text

from rag_mcp.db import dispose_engine, get_session_factory
from rag_mcp.services.memory_event_store import MemoryEventStore
from rag_mcp.services.memory_reducer import projection_fingerprint, reduce_events


async def diagnose(scope_id):
    async with get_session_factory()() as session:
        if scope_id is None:
            scope_id = (await session.execute(text("SELECT knowledge_scope_id FROM memory_events GROUP BY knowledge_scope_id ORDER BY count(*) DESC LIMIT 1"))).scalar_one()
        timings = {}
        start = perf_counter()
        events = await MemoryEventStore(session).replay(scope_id)
        timings["event_fetch_and_decode_seconds"] = perf_counter() - start
        start = perf_counter()
        state = reduce_events(events)
        timings["python_full_replay_seconds"] = perf_counter() - start
        start = perf_counter()
        await session.execute(text("SELECT jsonb_typeof(memory_log_state(:scope, :revision))"),
                              {"scope": scope_id, "revision": events[-1]["event_id"]})
        timings["database_full_replay_seconds"] = perf_counter() - start
        await session.rollback()
        return {"scope_id": scope_id, "event_count": len(events), "last_event_id": events[-1]["event_id"],
                "fingerprint": projection_fingerprint(state), "timings": timings, "writes": 0}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("historical output exists")
    try:
        result = await diagnose(args.scope)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
        print(json.dumps(result))
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
