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

## 6. 实现落定记录（T026，2026-10-09）

本节记录**实现实测**，不改动 §2–§5 的冻结内容。

### 6.1 三处顺序一致性（`search_knowledge` 014 分支）

| 位置 | 值 | 取证 |
|---|---|---|
| 契约文档 §2 | `completion_status, evidence, related_memories, memory_notice, counts, gaps, error, request_id` | 本文件 |
| schema 属性声明顺序 | 同上（`mcp-search-output.schema.json` 的 `properties` 前 8 项） | `tests/contract/test_014_search_bytes_frozen.py::test_runtime_order_equals_the_schema_declaration_order` |
| 运行时常量 | `mcp/search_knowledge.py` 的 `ATTACHMENT_FIELD_ORDER`（`merge_attachment_response` 按它重建） | `test_documented_order_equals_the_runtime_and_schema_order` |

**实测补充（重要）**：运行时发出的键列表是上表的**子序列**——`gaps` 仅在 `completion_status == "partial"` 或去重致空时出现，`error` 在 014 分支**永不**出现（014 分支只在主检索非 `failed` 时构建）。因此断言形式为「实际键序列 == 冻结表剔除缺席键后的序列」，而非「恒等于 8 键」。取证：`test_014_branch_key_order_is_exactly_the_contract_table[complete|partial|no_evidence]`。

### 6.2 `failed` 分支不附加

主检索 `completion_status == "failed"` ⇒ 直接返回 legacy dict，**不**构建 014 分支（不出现 `related_memories`/`memory_notice`/`counts`），并取消并回收已并发发起的附加层任务。取证：`tests/unit/test_014_attachment_gating.py::test_main_search_failure_attaches_nothing`、`::test_failed_main_search_cancels_a_running_attachment`、`tests/contract/test_014_search_bytes_frozen.py::test_end_to_end_failed_primary_has_no_new_fields`。

### 6.3 未触发/开关关闭的字节冻结

`MEMORY_AWARE_RETRIEVAL_ENABLED=false` 或未显式提供信号 ⇒ 返回主检索 dict **原对象**（引用相等）。四个 completion 状态的 pretty 镜像与 wire 字面量逐字节等于 T002 golden；显式 `null` 与省略等价；`AGENTIC_RETRIEVAL_ENABLED=true`（agentic 不可用回落路径）下同样逐字节一致。取证：`tests/contract/test_014_search_bytes_frozen.py`（30 项通过）。

### 6.4 裁剪优先级（`search_knowledge` 侧）

- **证据 > 记忆**：`evidence` 数组按引用原样搬运；附加层裁剪（条数 / 800 字 / 200 字摘录）**绝不**删减或重排 `evidence`。取证：`test_014_branch_never_drops_or_reorders_evidence`。
- **裁剪可观测**：`counts.truncated_by_budget` 与 `counts.characters` 随行；`memory_notice.failed_paths` 承载降级原因且唯一排序（字节稳定）。取证：`test_014_branch_omits_keys_instead_of_setting_them_to_none`、`test_failed_paths_ride_along_for_every_degradation_reason`。
- `digest > working_set` 与 `read_guidance` 永不裁剪属 `start_work` 侧（§3、T033/US4）。

### 6.5 `memory_notice` 构造方式

`notice` 由两个必需片段**组合**而成（`NOTICE_UNTRUSTED_DECLARATION` + `NOTICE_DEEP_READ_GUIDANCE`），而非一段自由文本，因此无法发布缺少任一要素的 notice；`notice_is_compliant()` 同时供硬指标统计复用（T069）。取证：`tests/unit/test_014_attachment_gating.py` 的 T022 段落（92 项通过）。

