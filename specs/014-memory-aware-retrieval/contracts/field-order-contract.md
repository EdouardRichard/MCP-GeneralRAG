# 顶层字段顺序契约 v1（014）

本契约冻结 `search_knowledge`（014 增量）与 `start_work`（014 增量）的顶层字段顺序与出现条件。对应 FR-012、FR-020/FR-024、SC-005、SC-009。

## 1. 为什么必须冻结

- 实测 FastMCP 把 `search_knowledge` 的 `dict` 返回同时生成 `structuredContent` 与**文本镜像**，文本镜像由 `pydantic_core.to_json(..., indent=2)` 生成（pretty 打印），与记忆工具的紧凑 `memory_result`（`separators=(",",":")`）**不是同一序列化器**。
- 实测 `mcp/shared/session.py` 的 `response.model_dump(by_alias=True, mode="json", exclude_none=True)` 保留 `structuredContent` 的插入顺序，且 `exclude_none` **不会**剥离 `structuredContent` 内部的 `None`。
- 因此：(a) 键顺序在协议层**可观测**；(b) 新字段的**缺席必须由"省略键"表达，绝不能由"置 None"表达**；(c) 不得为了统一而更换序列化器。

## 2. `search_knowledge` 冻结顺序

**legacy 分支（未显式提供 `session_id` 与 `memory_context`）——保持今天的运行时顺序不动：**

```
成功:            completion_status, evidence, request_id
partial(成功):   completion_status, evidence, request_id, gaps
failed:          completion_status, evidence, error, request_id
```

**014 分支（显式提供至少一个信号且主检索 `completion_status != "failed"`）——按下列顺序重建：**

```
completion_status, evidence, related_memories, memory_notice, counts, gaps, error, request_id
```

出现规则：

| 字段 | 出现条件 |
|---|---|
| `completion_status` / `evidence` / `request_id` | 恒在 |
| `related_memories` | 014 分支：恒在（可为空数组；附加层全部失败/低于阈值时为空） |
| `memory_notice` | 014 分支：恒在（与 `related_memories` 同生共死） |
| `counts` | 014 分支：恒在（与 `related_memories` 同生共死） |
| `gaps` | `completion_status == "partial"`；或 014 分支下去重致空时按规格给出可操作建议动作（**不改写** `completion_status`/`evidence`，不得用 `no_evidence` 表达记忆层空态） |
| `error` | `completion_status == "failed"`。014 分支不附加，故 014 分支不出现 `error` |

**不变量**：`evidence` 与 `related_memories` 相邻，在字段层体现分隔（`evidence[]` ‖ `related_memories[]`）；`evidence` 的 JSON 值、数量与顺序与未触发时逐字节一致。

## 3. `start_work` 冻结顺序

顶层顺序保持 012 **运行时**顺序：`scope, domain_brief, digest, working_set, read_guidance, counts, package_fingerprint, request_id`（实测 `services/memory_reader.py` 的 `start_work()` 返回体顺序）。014 输出 schema 的 `required`/属性声明顺序沿用 012 schema（`... package_fingerprint, counts ...`），仅为声明用途；**运行时与断言的权威顺序为本节上式**，两者不一致时以运行时顺序为准并把差异记录在契约测试中。

`working_set` 内部：

- `include_working_set=false`（默认）：`{"memories": [...]}`，与 012 逐字节一致；**不得**出现 `working_set` 子键。
- `include_working_set=true`：`{"memories": [...], "working_set": {"open_items", "recent_activity", "procedural", "decisions", "truncated", "session_resolved"}}`，三个桶内条目顺序为各桶的 `(observed_at, memory_id)` 倒序，`decisions` 为 append-only 的 `selected|deduped|truncated` 序列。

**易变字段**：`package_fingerprint` 由包体（不含自身与 `request_id`）的 `canonical` 摘要计算；`request_id` 不在包体与指纹内（L3 注入时剔除）。

## 4. 兼容规则（FR-001 / FR-024）

1. 未显式提供新参数时，`search_knowledge` 的键集合、键顺序、`structuredContent` 与文本镜像**逐字节不变**。
2. `start_work` 的 `include_working_set=false` 分支**逐字节不变**；不得以 `session_id`、`agent_id`、`budget` 或数据规模作为新形态的隐式开关。
3. 新字段一律**省略**而非置 `None`。
4. 运行时**不得**对 `search_knowledge` 施加 `extra=forbid`（`close_input_schema`）：那会把 `additionalProperties:false` 写入 `inputSchema`，并让历史上被静默忽略的多余/拼写错误字段变成 `ToolError`，属真实破坏。
5. 既有 `tests/contract/test_012_old_tool_compat.py` 两侧同源构建、`sort_keys=True`、且 `call_tool` 返回 dict 相等——**不能**冻结今天的字节。014 必须新增冻结 golden 测试。

## 5. 必须新增的冻结断言

| 断言 | 对象 |
|---|---|
| `list(structured) == [...]`（上表顺序） | 014 分支成功/partial 两种 |
| `content_blocks[0].text` 等于冻结的 pretty JSON 字面量 | 014 分支与 legacy 分支各一份 |
| `CallToolResult(...).model_dump_json(by_alias=True, exclude_none=True)` 等于冻结 wire 字面量 | legacy 分支 |
| 每个既有属性 JSON 与其在 009 契约中的原文逐字节相等；`required` 不变 | 014 输入 schema |
| legacy 属性集合 ⊆ 014 属性集合，且 014 只多出预期的新键 | 输入 schemas |
| `working_set` 在 `include_working_set=false` 时不含 `working_set` 子键 | start_work |
| `list(body) == [scope, domain_brief, digest, working_set, read_guidance, counts, package_fingerprint, request_id]`（运行时权威顺序，`include_working_set` 两种取值各一份） | start_work 顶层 |
