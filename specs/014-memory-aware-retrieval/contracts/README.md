# 014 契约索引

本目录是 Feature 014（记忆感知检索与宿主消费）的对外契约。**纯增量**：既有 001/007/009/012/013 契约文件一律不改动；014 以新文件承载增量并冻结兼容规则。

## 文件

| 文件 | 类型 | 说明 |
|---|---|---|
| [mcp-search-input.schema.json](mcp-search-input.schema.json) | JSON Schema Draft2020-12 | `search_knowledge` 输入增量：追加可选 `session_id`/`memory_context`；既有五属性逐字节保持 009 形态 |
| [mcp-search-output.schema.json](mcp-search-output.schema.json) | JSON Schema Draft2020-12 | `search_knowledge` 输出增量：追加 `related_memories`/`memory_notice`/`counts`；既有字段与 `required` 保持 007 形态；三者同生共死 |
| [memory-attachment.schema.json](memory-attachment.schema.json) | JSON Schema Draft2020-12 | 附加条目形态：沿用 012 `memory-entry` 词汇（比对基准见 schema 描述），摘录收紧至 200、`injection_flags`/`attach_reason` 必带、`valid_to`/`superseded_by` 固定 `null`，且不含任何证据定位字段（`source_position`/`source_version`/`relevance_score`） |
| [mcp-start-work.input.schema.json](mcp-start-work.input.schema.json) | JSON Schema Draft2020-12 | `start_work` 输入增量：追加显式开关 `include_working_set`（默认 false） |
| [mcp-start-work.output.schema.json](mcp-start-work.output.schema.json) | JSON Schema Draft2020-12 | `start_work` 输出增量：明确 `working_set` 的 legacy 与 014 两种形态 |
| [working-set-item.schema.json](working-set-item.schema.json) | JSON Schema Draft2020-12 | 工作集三类派生桶共用条目形态 |
| [common.schema.json](common.schema.json) | JSON Schema Draft2020-12 | 本地引用解析用共享定义：009 的 `definitions` 原文 + 补全 `ScopeCandidate`（007 定义）。仅用于本地解析，不改变任何 009 语义 |
| [field-order-contract.md](field-order-contract.md) | 文档契约 | 顶层字段顺序冻结、出现条件、兼容规则与必须新增的冻结断言 |
| [memory-consumption-projection.md](memory-consumption-projection.md) | 文档契约 | 只读消费层：分层并存、路径归一化、frontmatter、DIGEST/INDEX、只读守卫、异步刷新、漂移与重建 |
| [continuity-evaluation-contract.md](continuity-evaluation-contract.md) | 文档契约 | 连续性对照闸门、数据集、判据、可复现性、报告、硬指标与三宿主冒烟 |

## 版本

| 契约 | 版本 | 兼容基线 |
|---|---|---|
| `mcp-search-input` | 014.1 | 009（既有属性逐字节不变） |
| `mcp-search-output` | 014.1 | 007（既有字段与 `required` 不变） |
| `memory-attachment` | 014.1 | 012 `memory-entry`（共享字段名与类型不漂移） |
| `mcp-start-work`（输入/输出） | 014.1 | 012（顶层 `required` 与顺序不变） |
| `field-order-contract` | 1 | 014 新增（此前只有文字约定、无断言） |
| `memory-consumption-projection` | 1 | 014 新增（frontmatter 字段表为本 Feature 新增契约） |
| `continuity-evaluation-contract` | 1 | 013 评测/报告房规（隔离、退出码、不覆盖历史、不可计算基线） |

## 兼容与门控不变量（必须在实现与测试中同时成立）

1. **未触发零新增**：未显式提供 `session_id`/`memory_context` 时，`search_knowledge` 的键集合、键顺序、`structuredContent` 与 pretty 文本镜像逐字节不变；`start_work` 的 `include_working_set=false` 分支同样逐字节不变。
2. **省略而非置 None**：新字段的缺席由"省略键"表达；`exclude_none` 不会剥离 `structuredContent` 内的 `None`。
3. **不施加 extra=forbid**：运行时不得对 `search_knowledge` 调用 `close_input_schema`；历史被忽略的多余字段必须继续被忽略。
4. **分字段不混装**：附加条目不得通过 `evidence` item schema，反之亦然；由双向反例测试断言。
5. **同生共死**：014 分支下 `related_memories`、`memory_notice`、`counts` 同时出现或同时不出现。
6. **两条既有字节门禁不足**：`test_012_old_tool_compat.py` 两侧同源、`sort_keys=True` 且比较 dict 相等，无法冻结今天的字节 → 014 必须新增冻结 golden 测试。
7. **门控默认关闭**：`MEMORY_AWARE_RETRIEVAL_ENABLED` 与 `MEMORY_CONSUMPTION_PROJECTION_ENABLED` 默认 `false`；质量/硬指标/回归三闸全过且证据完整才具备开启资格，报告不自动改开关。
8. **三宿主**：DSH 必过；ChatGPT App / Claude Code 记录兼容状态不阻塞；未执行不得记为通过。
9. **定位语义分界（宪法 IV）**：`evidence[]` 用 `source_id`/`source_version`/`source_position`；记忆条目 MUST NOT 携带 `source_position`/`source_version`/`relevance_score`，其可定位性由 `provenance`/`evidence_refs`/有效期承担（`hard` 另需逐条归属复验）。两套语义不得混写，由双向反例与硬指标分项断言。
10. **投影面不可信声明（宪法 V/XII）**：消费层记忆文件 frontmatter MUST 含 `untrusted: true`，DIGEST.md/INDEX.md 文件头 MUST 含同义声明；正文仍为 `content_text` 原文（脱敏后），声明与原文并存、不互相替代。
11. **`memory_context` 检测先行（宪法 V）**：进入任何召回/打分/排序/拼装之前先跑既有注入检测并记 flags；检测失败不阻塞主检索，也不得作为放宽过滤或阈值的依据。该义务与 `related_memories`/`memory_notice`/`counts` 同属 014 契约面，必须被契约测试与硬指标覆盖。

## 相关文档

- 需求：[../spec.md](../spec.md)
- 规划：[../plan.md](../plan.md)
- 研究：[../research.md](../research.md)
- 数据模型：[../data-model.md](../data-model.md)
- 验收：[../quickstart.md](../quickstart.md)
- 上游契约：[../../009-domain-neutral-retrieval/contracts/](../../009-domain-neutral-retrieval/contracts/)、[../../007-knowledge-domain-generalization/contracts/](../../007-knowledge-domain-generalization/contracts/)、[../../012-memory-foundation-write-read-loop/contracts/](../../012-memory-foundation-write-read-loop/contracts/)、[../../013-memory-consolidation-loop/contracts/](../../013-memory-consolidation-loop/contracts/)
