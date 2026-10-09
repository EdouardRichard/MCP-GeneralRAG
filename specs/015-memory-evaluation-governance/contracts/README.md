# 015 契约索引

**Branch**: 015-memory-evaluation-governance | **Date**: 2026-10-09 | **Spec**: [../spec.md](../spec.md)

> 本目录为 015 的接口与产物契约。**全部为新增独立契约**（加法），不修改 001–014 任何既有 schema、报告或数据集（宪法 VII 独立接口演进 / SC-022 零破坏）。

## 契约清单

| 文件 | 类型 | 作用 | 校验位置 |
|---|---|---|---|
| [memory-benchmark-common.schema.json](./memory-benchmark-common.schema.json) | JSON Schema Draft 2020-12（纯 `$defs`） | 记忆基准报告共享块：`metricBlock`/`rateBlock`/`countBlock`/`latencyBlock`/`leakPath`/`hardMetricsBlock`（五件套 + 隔离泄漏 + `projection_integrity`〔FR-057〕/`state_metadata_completeness`〔FR-058〕）/`poisoningCaseEntry`/`aoepCaseEntry`/`watermark`/`subsetBlock`/`aoepBlock`/`invariantScore`/`reproducibilityBlock`/`configBlock`/`gateBlock`/`goalEntry`/`notMeasurableEntry` | 被报告 schema 引用；运行器与 contract 测试合并 `$defs` 后校验 |
| [memory-baseline-report.schema.json](./memory-baseline-report.schema.json) | JSON Schema | `eval/memory_baseline_report.json` 与 `eval/runs/<RUN_ID>/memory_baseline_report.json` 的根契约（三子集 + AOEP + 硬指标五件套 + 延迟 + 逐条 + 可复现性 + **回归证据块** + 七项目标判定） | `eval/run_memory_baseline.py` 落盘前校验；`backend/tests/contract/test_015_memory_baseline_report_schema.py` |
| [poisoning-eval-dataset.schema.json](./poisoning-eval-dataset.schema.json) | JSON Schema | `eval/memory_poisoning_eval_dataset.json` 条目契约（模式标签/变种档/八项断言/审核记录；`primary` 必为高危档；≥1 变种 + ≥1 中文）；**必填 `isolation` 块**（专用隔离域 + 既有冻结集依赖域禁入项）与**必填 `freeze` 块**（构造期可迭代、达标后首次冻结、冻结后只增不改） | `backend/tests/contract/test_015_memory_benchmark_datasets.py`；投毒 pytest 套件加载即校验 |
| [aoep-obligation-dataset.schema.json](./aoep-obligation-dataset.schema.json) | JSON Schema | `eval/memory_aoep_obligation_dataset.json` 用例契约（**五条不变量各 ≥2**——回滚可溯 `traceable_rollback`、删除传播 `deletion_propagation`、权威单调 `authority_monotonicity`、provenance 保全 `provenance_preservation`、范围不扩张 `scope_non_expansion`，与《宪法》XIII 第三条逐字对应；原 `authority_boundary` 已更名为 `authority_monotonicity`；回滚含时间点与事件点各 ≥1 且 ≥1 例可再次回滚；删除传播须列五投影）；**必填 `isolation` 块**（`per_run_dedicated` 隔离域与身份、禁入既有域、运行后处置留记录） | 同上 |
| [memory-stats-response.schema.json](./memory-stats-response.schema.json) | JSON Schema | `GET /api/memories/stats` 响应契约（计数与分位；零正文；`additionalProperties: false`） | `backend/tests/contract/test_015_memory_stats_schema.py` |
| [finalization-ledger.schema.json](./finalization-ledger.schema.json) | JSON Schema | 3.0 定稿核销记录契约（七项逐项判定 + 证据指针 + 未达成处置 + 定稿硬门四项） | 核销工件产出时校验 |
| [governance-ui-contract.md](./governance-ui-contract.md) | 文档契约 | 六视图、scope 显式过滤（无全局记忆正文视图）、强确认、单条边界、SSE 使用边界 | `frontend/tests/memory-governance.spec.ts`（Playwright 路由打桩） |

## 校验约定

1. **`$defs` 合并模式（沿 011 先例）**：报告 schema 以相对引用写 `./memory-benchmark-common.schema.json#/$defs/<name>`；校验时加载两份文件、执行 `schema["$defs"].update(common["$defs"])`，再对 `$ref` 字符串做 `./memory-benchmark-common.schema.json#/$defs/` → `#/$defs/` 替换，最后 `jsonschema`（Draft 2020-12）`validate`。**不引入新的 schema registry 设施**（014 的 `referencing.Registry` 仅用于 MCP 契约，本 Feature 不复用）。
2. **正反例齐备**：每份 schema 的 contract 测试至少含 1 个合法样例与 1 个应当被拒的反例（关键约束：零分母编码、`primary` 低危档被拒、删除传播缺投影被拒、统计响应含正文键被拒、未达成项缺处置被拒）。
3. **不可测量编码（零容差）**：比率型 `{passed:0,total:0,rate:null,value:"not_measurable",reason:"…"}`；数值型 `{value:null,state:"not_measurable",reason:"a zero denominator is not a measured zero"}`。记 `0` 或 `100%` 即违约（FR-024/SC-011）。
4. **冻结与只增**：两份数据集带 `dataset_version`/`frozen`/`snapshot_hash`；投毒子集另带 `freeze`（首次冻结发生在全部 `primary` 用例"既标记又隔离"之后；冻结后失败如实判定并阻止定稿，不得替换/删改/放宽，补救仅追加或另立 Feature）与 `isolation`（专用隔离域 + 既有冻结集依赖域禁入项）；"只增不破坏"以"新增条目后既有条目哈希不变"可复算断言证明（SC-001）。
5. **破坏性操作隔离**：AOEP 数据集必填 `isolation`（`mode/identity = per_run_dedicated`、`forbidden_scope_ids` 必列 `366084747748704256`、`disposal = record_and_dispose`、`record_isolation_id = true`）；逐例结果必填 `isolated_scope_id`；破坏性操作触及既有真实域或既有固定评测集依赖域的次数 MUST 为 0（SC-004）。
6. **依赖模型的回归组**：报告 `regression.groups[]` 对 005/013 等组要求 `mode = record_then_replay` 且 `replay_real_network_calls = 0`，并以缓存 manifest 哈希留证；`mode` 仅允许 `single_round`/`record_then_replay` 两个取值。**FR-059 组→测试映射登记**：回归编排须落盘 `regression_group_map.json`，每组登记 `{group, runner, command, test_module, artifact}` 且与报告 `regression.groups[]` 双向一致（映射覆盖率 100%）；映射缺失或未执行的组 MUST NOT 记为通过。
7. **历史产物零覆盖**：报告路径存在即拒绝写入（`eval/runs/<RUN_ID>/` 唯一写入路径；追踪路径仅首次播种）；运行器 MUST NOT 复制 `eval/hard_metrics_014.py:435` 的无条件重写行为。
8. **不进默认路径**：报告**不含** `enters_default_path` 字段（宪法 X：建立锚点而非宣称改进）。
9. **零分母守卫（FR-057/FR-058/SC-026）**：`hardMetricsBlock.required` 恰为 9 键（`cross_domain_leakage`/`tool_schema_validity`/`source_locatability`/`memory_provenance_completeness`/`hard_memory_anchoring`/`quarantined_leakage`/`projection_integrity`/`state_metadata_completeness`/`all_passed`）。守卫分两类：**四个比率块**以 `total == 0` 判定，MUST 记 `rate = null` / `value = "not_measurable"` + 非空 `reason`；`cross_domain_leakage` 的四条 `leakPath`、`quarantined_leakage` 的五个 `countBlock`、`projection_integrity` 的每个 view（六投影：`relation`/`dense`/`links`/`summary`/`file`/`salience`）与 `state_metadata_completeness` 的每个轴以 `examined == 0` 判定，MUST 记 `state`/`value = "not_measurable"`（rate 块记 `rate = null`）+ 非空 `reason`。**四个比率块的 `passed` 是整数通过条数（014 口径），"全过"须写 `passed >= 1` 且 `rate == value == 1`，MUST NOT 写成布尔 `passed: true`**。`hard_metrics.all_passed` MUST 由各子块共同决定（含 `projection_integrity.all_views_measured == true` 且 `.all_passed == true`、`state_metadata_completeness.all_passed == true`），MUST NOT 独立写入 `true`；六轴齐备率须逐轴给出分母与结论。
10. **七项核销 1:1（SC-027）**：`goal_ledger`（报告）与 `finalization-ledger.schema.json` 的 `goals[]` MUST 恰 7 项、`uniqueItems`、`id` 唯一覆盖 1–7、`statement` 与实施蓝图 §1 逐字对应；`goals[4].verdict = not_achieved`（巩固受益）且 `verdict != achieved` 时 `disposition` 必填；`goals[]` 与报告 `goal_ledger` MUST 同源一致。

## 与既有契约的关系

- **沿用词汇**：`metricBlock`/`latencyBlock`/`reproducibilityBlock`/`configBlock` 语义沿用 002 `eval-comparison-report.schema.json` 与 011 `domain-baseline-common.schema.json`；数据集 `_meta` 审核记录形态沿用 011 `domain-eval-dataset.schema.json` 与 014 `memory_continuity_eval_dataset.json`。
- **加法扩展**：011 的 `hardConstraintsBlock`（`additionalProperties:false`，仅三指标）**不被复用也不被修改**；015 新建 `hardMetricsBlock`（五件套 + 隔离泄漏）。
- **零改动**：`specs/006-.../contracts/runtime-metrics.schema.json`、六工具 MCP 契约、`specs/012-.../contracts/*`、013/014 契约与数据集一律不动。
