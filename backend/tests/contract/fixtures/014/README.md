# 014 legacy byte-freeze golden fixtures

Owner: 014 T002 (`backend/tests/contract/test_014_search_bytes_frozen.py` consumes them).
Contract: `specs/014-memory-aware-retrieval/contracts/field-order-contract.md` §2/§3/§5.

## Why these exist

`tests/contract/test_012_old_tool_compat.py` builds both sides from the same source and
compares with `sort_keys=True`, so it erases property order and cannot freeze today's
bytes. 014 adds new fields to the same tools, therefore it needs its own frozen goldens.

Two different serializers are involved (measured, mcp 1.29.1):

| Tool | Return type | Unstructured mirror | structuredContent |
|---|---|---|---|
| `search_knowledge` | `dict[str, Any]` | `pydantic_core.to_json(body, fallback=str, indent=2)` — **pretty, 2-space indent** | `output_model.model_dump(mode="json", by_alias=True)`, insertion order preserved |
| `start_work` | `CallToolResult` (`memory_result`) | `json.dumps(body, ensure_ascii=False, separators=(",", ":"))` — **compact** | the same dict |

Both are wrapped by `CallToolResult(...).model_dump_json(by_alias=True, exclude_none=True)`
and `exclude_none` does **not** strip `None` inside `structuredContent`, which is exactly
why 014 must express a missing new field by **omitting the key** and never by `None`.

## Files

| File | Frozen object |
|---|---|
| `legacy_search_knowledge.golden.json` | `search_knowledge` untriggered branch: `complete` / `partial` / `no_evidence` / `failed` — ordered key list, pretty mirror literal, wire literal |
| `legacy_start_work.golden.json` | `start_work` `include_working_set=false` branch: ordered top-level key list, compact mirror literal, wire literal, and the `working_set` sub-keys |
| `_generate_golden.py` | Deterministic regenerator. Runs the **real** FastMCP registration + result conversion with a stubbed core/service, so the goldens are the actual serializer output, not a hand-written guess. |

## How they were produced

```powershell
cd backend
python tests/contract/fixtures/014/_generate_golden.py
```

The generator stubs only the *service* layer (`search_knowledge_core`,
`MemoryService.start_work`) and keeps everything else real: FastMCP registration,
`_convert_to_content`, `CallToolResult` validation and `model_dump_json`. The stub returns
a fixed body whose evidence values are inert placeholders; the freeze is about the
serializer and the key order, which are independent of the evidence payload.

`python tests/contract/fixtures/014/_generate_golden.py --check` re-derives every literal
and exits non-zero on any drift, so the goldens are self-verifying.

## Regeneration policy

These files MUST NOT be regenerated to make a failing test pass. Any change to a frozen
literal is a client-visible protocol break and needs an explicit contract revision
(`field-order-contract.md`) plus evidence that no existing client depends on the old bytes.
