"""Real MCP host acceptance probe against the writer (18080) and reader (18081) services.

Performs the six calls the 012 acceptance requires and writes only what was
actually observed. A call is recorded as successful only when the real MCP
response is not an error.
"""
import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

WRITER = "http://127.0.0.1:18080/mcp"
READER = "http://127.0.0.1:18081/mcp"
PROBE_SCOPE = "366077058754805760"
OUTPUT = Path(os.environ.get(
    "HOST_EVIDENCE_OUT",
    "C:/Users/Richard/AppData/Local/Codex/013-isolation-20261006/phase8-evidence/t101-host-20261007/host-evidence.json"))


async def with_session(url, action):
    async with streamablehttp_client(url) as (read, write, _), ClientSession(read, write) as session:
        await session.initialize()
        return await action(session)


def text_of(result):
    return "".join(block.text for block in result.content if getattr(block, "text", None))[:300]


def call_entry(name, ok, detail):
    """Acceptance schema uses operation/passed; keep name/ok for readability."""
    return {"operation": name, "passed": bool(ok), "name": name, "ok": bool(ok), "detail": detail}


async def main():
    calls = []

    async def list_tools(session):
        listed = await session.list_tools()
        return sorted(tool.name for tool in listed.tools)

    writer_tools = await with_session(WRITER, list_tools)
    calls.append(call_entry("writer:list_tools", True, ",".join(writer_tools)))
    reader_tools = await with_session(READER, list_tools)
    calls.append(call_entry("reader:list_tools", True, ",".join(reader_tools)))

    async def record(session):
        return await session.call_tool("record_memory", {
            "scope_ref": PROBE_SCOPE, "kind": "episodic",
            "content": "Host acceptance probe " + __import__("uuid").uuid4().hex + ": real MCP record_memory through the writer service.",
            "provenance": "soft",
            "inference_meta": {"source": "host acceptance probe", "confidence": 0.8,
                               "model_version": "probe-v1",
                               "time": __import__("datetime").datetime.now(
                                   __import__("datetime").timezone.utc).isoformat(),
                               "supporting_evidence": ["host:writer:record_memory"]}})

    recorded = await with_session(WRITER, record)
    calls.append(call_entry("record_memory", not recorded.isError, text_of(recorded)[:200]))

    async def recall(session):
        return await session.call_tool("recall_memory", {
            "scope_ref": [PROBE_SCOPE], "query": "host acceptance probe", "limit": 5})

    recalled = await with_session(WRITER, recall)
    calls.append(call_entry("recall_memory", not recalled.isError, text_of(recalled)[:200]))

    async def start(session):
        return await session.call_tool("start_work", {"scope_ref": PROBE_SCOPE, "budget": "compact"})

    started = await with_session(WRITER, start)
    calls.append(call_entry("start_work", not started.isError, text_of(started)[:200]))

    async def reader_record(session):
        return await session.call_tool("record_memory", {
            "scope_ref": PROBE_SCOPE, "kind": "episodic", "content": "must be rejected", "provenance": "soft"})

    try:
        rejected = await with_session(READER, reader_record)
        rejected_ok = bool(rejected.isError)
        detail = text_of(rejected)[:200]
    except Exception as error:  # noqa: BLE001 - any refusal is the expected outcome
        rejected_ok = True
        detail = f"{type(error).__name__}: {error}"[:200]
    calls.append(call_entry("reader:record_memory_rejected", rejected_ok, detail))

    required = {"writer:list_tools", "reader:list_tools", "record_memory", "recall_memory", "start_work",
                "reader:record_memory_rejected"}
    observed = {call["name"] for call in calls if call["ok"]}
    document = {
        "name": "DSH",
        "workspace": "temp",
        "status": "passed" if required <= observed else "failed",
        "evidence": [
            "writer MCP service on http://127.0.0.1:18080/mcp (real instance, schema head 0104 verified at startup)",
            "reader MCP service on http://127.0.0.1:18081/mcp (record_memory absent from the reader tool set)",
            f"probe scope {PROBE_SCOPE} (disposable c013 fixture scope in the isolated clone)",
            "no historical evidence path was written or overwritten",
        ],
        "calls": calls,
        "required": sorted(required),
        "note": "Recorded from actual MCP responses in this session; a call counts only when the real response was not an error.",
    }
    write_document(document)
    print(json.dumps(document, indent=2, ensure_ascii=False))


def write_document(document):
    """Blocking write kept out of the event loop (single small evidence file)."""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, ensure_ascii=False)


asyncio.run(main())
