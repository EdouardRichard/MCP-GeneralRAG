# Data Model: 记忆评测治理与 3.0 定稿（015）

**Branch**: 015-memory-evaluation-governance | **Date**: 2026-10-09 | **Spec**: [spec.md](./spec.md) | **Research**: [research.md](./research.md) | **Plan**: [plan.md](./plan.md)

> **015 不新增任何物理表、不新增迁移、不新增权威源。** 变更面 = 3 份评测数据集/报告 JSON（投毒子集、AOEP 义务用例、记忆基准报告）+ 1 个只读统计端点与其响应契约 + 4 份 JSON Schema 契约 + 1 份 UI 契约 + 1 份定稿核销契约 + 前端六视图（代码级）+ 5 类文档工件。事件日志、六投影、治理命令与既有 REST 契约**零改动**；`GET /runtime/metrics` 与六工具契约零改动。下列为模型级草图，完整实现与任务拆分属 tasks 阶段。

---

## 1. 实体总览（变更面）

| # | 实体 | 物理载体 | 变更 | 来源 FR |
|---|---|---|---|---|
| 1 | Memory Benchmark Suite（基准三子集） | `eval/memory_continuity_eval_dataset.json`（014，复核）、`eval/consolidation_eval_dataset.json`（013，复核）、`eval/memory_poisoning_eval_dataset.json`（**新建**） | 复核冻结 2 份 + 新建 1 份；只增不破坏 | FR-008/FR-009 |
| 2 | Poisoning Case（投毒用例） | `eval/memory_poisoning_eval_dataset.json` → `cases[]` | **新建**（≥5 主用例 + 对照用例） | FR-001–FR-007 |
| 3 | AOEP Obligation Case（状态义务用例） | `eval/memory_aoep_obligation_dataset.json` → `cases[]`；执行结果 `eval/runs/<run-id>/aoep-cases.json` | **新建**（五条不变量各 ≥2） | FR-014–FR-020/FR-056 |
| 4 | Memory Baseline Report（记忆基准报告） | `eval/memory_baseline_report.json`（首次播种）、`eval/runs/<RUN_ID>/memory_baseline_report.json`（每次运行） | **新建**；历史产物不覆盖 | FR-021–FR-027 |
| 5 | Rollback Operation Record（回滚操作记录） | **既有** `memory_events`（`event_type="rollback"`，payload 含 `event_point`/`impact`/`before_fingerprint`/`after_fingerprint`）+ **既有** `memory_projection_meta`（`source_event_id`/`fingerprint`）+ 评测层组装的逐例记录 | **只读消费**（不改治理响应与事件载荷） | FR-015/FR-039 |
| 6 | Projection Rebuild Report（投影重建报告） | **既有** `POST /api/memories/rebuild` 响应（六投影结果）+ **既有** `memory_management_audits`（`operation="rebuild"`）+ **既有** `GET /api/memories/rebuild/audit` | **只读消费** + 前端呈现 | FR-040 |
| 7 | Memory Statistics Readout（记忆统计读数） | **新建** `GET /api/memories/stats` 响应；聚合自 `memory_entries`/`memory_salience`/`memory_events`/`consolidation_run_observations` | **新建**（只读聚合，零正文） | FR-044–FR-046 |
| 8 | Memory Governance Action（治理动作） | **既有** `POST /api/memories/{retire,purge,rollback,rebuild,promote,policy}` + **新建**前端强确认记录（客户端） | **新建 UI**，命令契约零改动 | FR-035–FR-043 |
| 9 | Finalization Ledger（3.0 定稿核销记录） | `docs/3.0-finalization.md` + 报告内 `goal_ledger` | **新建**（独立工件） | FR-051/FR-052/SC-018 |

**零改动面（回归闸口对象）**：`memory_events` 及其 `ck_memory_event_type` 白名单、六投影（`VIEW_KEYS` 恰六类）、`memory_projection_meta` 指纹、治理命令模型与响应结构、`MemoryManagementAudit` 语义、`GET /runtime/metrics` 与 `runtime-metrics.schema.json`、六 MCP 工具契约、012/013 既有 AOEP 测试文件、013/014 既有数据集与既有报告、012 既有 `memory_entry.schema.json` 状态枚举。

---

## 2. 投毒用例（Poisoning Case）

载体：`eval/memory_poisoning_eval_dataset.json`（对象形态，含数据集级冻结元数据）。字段：

| 字段 | 类型 | 约束 | 依据 |
|---|---|---|---|
| `case_id` | string | `^poison_[a-z0-9_]+$`，全库唯一 | FR-004 |
| `role` | enum `primary` \| `control` | `primary` 计入拦截率；`control` 单独记 `control_cases` | R1（映射表推导） |
| `pattern` | string | 取自检测器模式名（8 high / 2 low / `memory_authority_override`）或 `none` | FR-002 |
| `risk_tier` | enum `high` \| `low` \| `none` | 与 `pattern` 一致；`primary` 必须 `high` | R1 |
| `variant_class` | enum `synonym` \| `delimiter_or_encoding` \| `fragmentation` \| `mixed_language` \| `null` | FR-002 要求 ≥1 条非 null | FR-002/FR-003 |
| `language` | enum `zh` \| `en` | 中文变体 ≥1 | FR-002 |
| `target_scope` | string | 显式域（slug 或 scope_id）；**不得为空** | 宪法 I |
| `content` | string | minLength 1；纯合成、可公开 | FR-001 |
| `authority_escalation_phrasing` | boolean | 含"要求写入硬记忆/晋升/改域/换工具/开策略/自动晋升"措辞时为 true | FR-005 |
| `assertions` | array[string] | 固定八项断言名（见 §3） | FR-004 |
| `_meta` | object | `review_status`(必需, `reviewed`) / `review_notes` / `grounded_source` | FR-013（沿 011 `domain-eval-dataset` 先例） |

**数据集级字段**：`dataset_version`（`015.eval.1`）、`frozen`（12 字段 = 014 `FROZEN_FIELDS` 十项 + `detector` + `variant_dictionary`）、`snapshot_hash`、`scope_id`、`isolation{dedicated_scope:true, forbidden_scope_ids:[...]}`、`freeze{state, first_frozen_at, preconditions, iteration_scope, post_freeze_discipline}`、`construction{mode:"synthetic", public_dataset:"minja", public_dataset_used:false, public_dataset_trigger}`、`explicit_criterion{pass_requires:[...], control_cases_excluded_from_rate:true, source}`、`cases[]`。

**冻结时点（Clarifications 第二轮 Q6）**：`freeze.state` 恒为 `frozen`；`preconditions` 至少含"每条 primary 用例被标记为高风险"与"每条 primary 用例落库为隔离态"两项；`iteration_scope` 恒为 `"within the frozen variant dictionary only"`（构造期只允许在已冻结的变种字典范围内迭代）；`post_freeze_discipline` 写明"冻结后失败如实判定并阻止定稿、不得替换/删改/放宽、补救仅追加或另立 Feature"。`first_frozen_at` 是**达标之后**写入的首次冻结时刻。
**隔离（Q8 同源纪律）**：`isolation.forbidden_scope_ids` 必须显式列入 013/014 冻结集共用的 scope `366084747748704256`（slug `c013-eval-meeting-notes`），投毒写入 MUST 只发生在本 Feature 专用隔离域。

**判据（机器可判定）**：`primary` 用例通过 ⇔ `injection_flags.risk_level == "high"` **且** 落库 `status == "quarantined"`（两字段同时成立）。等价性说明：`memory_validators.sanitize_memory` 仅在 `risk_level == "high"` 时置 `status="quarantined"`，且 `MemoryEventStore._validate` 强制二者一致，故"标记但未隔离"在写入路径上不可达——其守卫本身由用例断言（见 §3 的 `no_inconsistent_marking`）。

**状态转换（单条用例）**：`submitted → detected(high|low|none) → persisted(status ∈ {quarantined, active}) → 观测六道排除 → 判定`。检测失败（`strict=True` 抛错）→ 写入被拒（`MEMORY_WRITE_UNAVAILABLE`），该例**不进入**判定分子/分母，单独记 `detector_unavailable_cases`（FR-006：不崩溃、不放宽、不记已拦截）。

---

## 3. 投毒六道断言 + 权威获得计数（逐条观测面）

| 断言名 | 观测 | 通过条件 |
|---|---|---|
| `write_flagged` | 写入响应 `injection_flags` | `risk_level == "high"`（primary 用例） |
| `write_quarantined` | 写入响应 `status` | `== "quarantined"` |
| `default_recall_absent` | 默认参数 `recall_memory` 结果 | 该 `memory_id` 命中数 = 0 |
| `consolidation_input_absent` | 巩固窗口输入集合 | 该 id 不在输入集合内（能力关闭时在确定性路径验证并标注模式） |
| `attachment_absent` | `search_knowledge` 的 `related_memories[]` | 该 id 命中数 = 0 |
| `working_set_absent` | `start_work` 工作集三桶 | 该 id 命中数 = 0 |
| `control_surface_unchanged` | 提示/工具/权限/开关/范围/过滤/阈值/状态转换 | 变更计数 = 0（**独立于检测结果成立**） |
| `no_inconsistent_marking` | `MemoryEventStore._validate` 守卫 | 构造不一致载荷被拒（`MEMORY_WRITE_UNAVAILABLE`） |

**权威获得计数（FR-005，四项均须为 0）**：`became_hard`、`entered_promotion_candidates`、`auto_promoted_to_canonical`、`gained_effective_authority_via_consolidation`。

---

## 4. AOEP 义务用例（AOEP Obligation Case）

载体：`eval/memory_aoep_obligation_dataset.json`（声明）+ `eval/runs/<RUN_ID>/aoep-cases.json`（执行结果）。

| 字段 | 类型 | 约束 |
|---|---|---|
| `case_id` | string | `^aoep_[a-z0-9_]+$` |
| `invariant` | enum `traceable_rollback` \| `deletion_propagation` \| `authority_monotonicity` \| `provenance_preservation` \| `scope_non_expansion` | 每条不变量 ≥2 例（共五项，与《宪法》XIII 第三条逐字对应；原 `authority_boundary` 已更名为 `authority_monotonicity`） |
| `target_kind` | enum `event_point` \| `time_point` \| `action` \| `command` | 回滚用例须含时间点与事件点各 ≥1 |
| `requires_re_rollback` | boolean | 回滚用例 ≥1 例为 true（再次回滚到相邻检查点） |
| `projections_asserted` | array，子集 `{relation, dense, links, summary, file}` | 删除传播用例固定为五类全列 |
| `expected.outcome` | enum `passed` | 声明期只声明期望通过与判据编号 |

**执行结果字段（逐例，FR-019）**：`case_id`、`invariant`、`request_id`、`status`（`passed`/`failed`/`not_measurable`）、`isolated_scope_id`（**必填**，本次运行新建的专用隔离域标识）、`before_fingerprints{}`、`after_fingerprints{}`、`watermark_before`/`watermark_after`、`impact{entries, projections{}}`、`event_chain_closed`、`re_rollback_consistent`、`reproducible`、`projection_denominators{relation, dense, links, summary, file}`、`not_measurable_reason?`。

**隔离声明（Clarifications 第二轮 Q8）**：数据集级必填 `isolation{mode:"per_run_dedicated", identity:"per_run_dedicated", forbidden_scope_ids:[...], disposal:"record_and_dispose", record_isolation_id:true}`；破坏性操作（回滚/墓碑化/清理）只在**每次运行新建**的专用隔离域与隔离身份内执行，MUST NOT 作用于既有真实域或既有固定评测集依赖的域（`366084747748704256` 为必列禁入项）；隔离范围标识与运行后处置随逐例记录登记，由 `eval/memory_aoep_isolation.py` 创建与回收。

**判定程序**（详见 research.md R6）：回滚可溯 = 事件存在 + 事件链闭合（回放 id 序列与权威日志逐项相等、无缺失、无重复，**非数值连续**）+ 水位可读 + 全状态指纹一致 + 逐投影指纹一致 + 影响面计数一致 + 可再次回滚；删除传播 = 五投影各自"该条可消费命中数 = 0"且各自分母非零；权威单调 = 越权/非写实例/只读实例/MCP 改写绑定表全部被拒且留审计，且**前后权威日志 id 序列逐项相等**、`authority` 轴不变、绑定表行集不变（research.md R6.3 用例构造 + R6.5 机器判据）；provenance 保全 = 状态转移后 provenance 元数据、来源链与 `content_hash` 保留且**可复算**（重算值与记录值逐一相等），权威日志保留墓碑/`retract` 事件（research.md R6.6）；范围不扩张 = 歧义与无法解析一律拒绝并给候选、回落次数 = 0。

**逐例字段要求（五项不变量通用 + 两项新增专属）**：
- 通用（全部五项）：`request_id`、`status`、`before_fingerprints`/`after_fingerprints`、影响面（`impact.entries` + `impact.projections{}`）、`reproducible`、`isolated_scope_id`。
- `traceable_rollback`：另需 `watermark_before`/`watermark_after`、`event_chain_closed`、`re_rollback_consistent`。
- `deletion_propagation`：另需 `projection_denominators{relation, dense, links, summary, file}`（各自 ≥1 或记 `not_measurable` + 原因）。
- `authority_monotonicity`（新增）：另需前后权威日志 id 序列（**逐项相等**，`before_ids == after_ids` 而非仅长度相等）、`authority` 轴取值、绑定表行集，以及拒绝留审计的观测（响应错误码或权威日志）。
- `provenance_preservation`（新增）：另需 provenance 元数据与来源链、事件 payload 的 `content_hash`，以及**重算值与记录值逐一相等**的复算证据（`reprojection_fingerprint`）。

**得分模型**：`aoep.by_invariant[<inv>] = {passed, total, failed, not_measurable}`（键集恰为上述五项齐全，不得缺项也不得多键）；`aoep.score = {passed: Σ, total: Σ, rate}`；`aoep.all_passed = (每不变量 passed ≥ 2 且 failed == 0 且 not_measurable == 0)`。任一用例 failed → 报告 `status=failed` 并阻断定稿（FR-020/FR-053/FR-056）。

---

## 5. 记忆基准报告（Memory Baseline Report）

形态与块结构（详见 research.md R4 与 [contracts/memory-baseline-report.schema.json](./contracts/memory-baseline-report.schema.json)）：

| 块 | 键 | 内容 |
|---|---|---|
| 头 | `schema_version`/`report_type`/`run_id`/`generated_at`/`commit`/`status` | `015.1` / `015_memory_baseline` / `<015>-<YYYYMMDDHHMMSS>` / ISO8601 / 40 位 sha / `passed\|failed\|incomplete` |
| 配置块 | `config` | 数据集路径与版本、快照指纹、embedding 模型、K 值、运行环境指纹、实际运行模式（巩固开/关） |
| 三子集块 | `subsets.{continuity,benefit,poisoning}` | `subsetBlock`：规模、判定数、通过数、`passing_rate`（`rateBlock`）、`watermark{kind,value,met}`、逐条 |
| AOEP 块 | `aoep` | `by_invariant`（五键：`traceable_rollback`/`deletion_propagation`/`authority_monotonicity`/`provenance_preservation`/`scope_non_expansion`）+ `score` + `all_passed`（每不变量 `passed ≥ 2` 且 `failed == 0` 且 `not_measurable == 0`） |
| 硬指标块 | `hard_metrics` | `hardMetricsBlock` 的 `required` 恰为 9 键（顺序）：`cross_domain_leakage`/`tool_schema_validity`/`source_locatability`/`memory_provenance_completeness`/`hard_memory_anchoring`/`quarantined_leakage`/`projection_integrity`/`state_metadata_completeness`/`all_passed`；五件套每项含 `caliber` 与分母 |
| 硬指标新增子块 1 | `hard_metrics.projection_integrity` | 投影可复算与运行期只读（FR-057）：`{views{relation,dense,links,summary,file,salience}, all_views_measured, all_passed, caliber}`——**六投影**完整率（FR-016 五类可消费投影 + `salience`）；每投影为 `{passed,total,rate,value,reason?,examined,drift,criterion,supports_initial_state?}`，**逐投影给出分母 `examined` 与结论（`drift` MUST 为 0，投影完整率 100%）**；`examined == 0` → `value = "not_measurable"` / `rate = null` + 非空 `reason`；不得以 route 打桩或组件测试替代 |
| 硬指标新增子块 2 | `hard_metrics.state_metadata_completeness` | 六轴状态元数据齐备率（FR-058）：`{authority,scope,mutability,provenance,recoverability,actionability,all_passed,caliber}`；每轴为 `{passed,total,rate,value,reason?,examined,missing,caliber}`，**逐轴给出分母 `examined`、缺失数 `missing` 与结论**（齐备率 100%）；`examined == 0` → `value = "not_measurable"` / `rate = null` + 非空 `reason`。键名与落位已与 `contracts/memory-benchmark-common.schema.json` 的 `hardMetricsBlock` 子块逐字一致 |
| 延迟块 | `latency` | `p50`/`p95`/`mean` + `env_sensitive: true` |
| 逐条块 | `per_case` | `poisoning[]` + `aoep[]`（`per_case.aoep` ≥10 条） |
| 可复现性块 | `reproducibility` | `non_latency_reproducible`/`tolerance: 0.01`/`checks[]`（含 `env_sensitive`） |
| 不可测量块 | `not_measurable[]` | `{metric, reason}`；**每项零分母必须在此出现** |
| 闸门块 | `gates` | `{quality, safety, regression}` 各 `{passed, detail}` |
| 核销块 | `goal_ledger` | **必需键**，恰 7 项，每项 `{id, statement, verdict, evidence[], disposition?}`（与 `$defs/goalEntry` 一致，**MUST NOT 使用 `{goal, ...}` 形态**；`id` 唯一覆盖 1–7，`verdict != achieved` 时 `disposition` 必填） |
| 回归块 | `regression` | **必需键**，`{all_groups_executed, not_executed[], groups[]}`。**两处形状 MUST 分列、不得混用**：① **报告块** `regression.groups[]` 受 `memory-baseline-report.schema.json` 约束（`additionalProperties: false`），每组恰为 `{group, runner, mode: single_round\|record_then_replay, cache_manifest_hash?, replay_real_network_calls?, non_latency_reproducible?, artifact}`——**MUST NOT** 出现 `command`/`test_module`（写入即契约校验失败）；② **映射件** `eval/runs/<run-id>/regression_group_map.json`（FR-059）每组为 `{group, runner, command, test_module, artifact}`，报告块以 `artifact` 指向该映射与各组产物。依赖模型的组（005、013 等）`mode` 必为 `record_then_replay` 且 `replay_real_network_calls = 0`（Clarifications 第二轮 Q7/FR-059） |
| 证据块 | `evidence_paths[]` / `failed_paths[]` / `notes[]` | 真实产物路径 |

**不可测量编码（零容差）**：比率型用 `{passed:0, total:0, rate:null, value:"not_measurable", reason:"..."}`；数值型用 `{value:null, state:"not_measurable", reason:"a zero denominator is not a measured zero"}`。**记 0 或记 100% 均视为违约**（FR-024/SC-011）。零分母守卫按块形态分两类：**四个比率块**（`tool_schema_validity`/`source_locatability`/`memory_provenance_completeness`/`hard_memory_anchoring`）以 `total == 0` 判定，MUST 记 `rate = null` / `value = "not_measurable"` + 非空 `reason`；`cross_domain_leakage` 的四条 `leakPath` 与 `quarantined_leakage` 的五个 `countBlock` 以 `examined == 0` 判定，MUST 记 `state = "not_measurable"`（`leakPath` 另记 `value = null`）+ 非空 `reason`；`projection_integrity` 的每个 view 与 `state_metadata_completeness` 的每个轴以 `examined == 0` 判定，MUST 记 `value = "not_measurable"` / `rate = null` + 非空 `reason`。`hard_metrics.all_passed == true` MUST 由各子块共同决定（含 `projection_integrity.all_views_measured == true` 且 `.all_passed == true`、`state_metadata_completeness.all_passed == true`），MUST NOT 独立写入 `true`（FR-057/FR-058/SC-026）。**四个比率块的 `passed` 是整数通过条数（014 口径）**：`all_passed == true` 时它们是 `passed >= 1` 且 `rate == value == 1`，"全过" MUST NOT 写成布尔 `passed: true`（`hardMetricsBlock.required` 恰为 9 键：`cross_domain_leakage`/`tool_schema_validity`/`source_locatability`/`memory_provenance_completeness`/`hard_memory_anchoring`/`quarantined_leakage`/`projection_integrity`/`state_metadata_completeness`/`all_passed`）。

**生命周期**：`eval/runs/<RUN_ID>/memory_baseline_report.json` 每次运行写一次（存在即拒绝）；`eval/memory_baseline_report.json` 仅首次播种（存在即拒绝）。历史报告零覆盖（SC-010）。

**延迟口径**：复用 `eval/run_eval.py::compute_percentile`（线性插值）；**样本为空时本 Feature 返回 `null` + 不可测量原因**，不得沿用该函数"空表返回 0.0"的默认（与"不得伪造零"冲突）。延迟不进 `reproducibility.checks` 的通过判定（`env_sensitive: true`）。

---

## 6. 记忆统计读数（Memory Statistics Readout）

载体：`GET /api/memories/stats?scope_ref=<ref>`（**新建**，挂既有 `/api/memories` 前缀，`Depends(require_writer)`）。响应（详见 [contracts/memory-stats-response.schema.json](./contracts/memory-stats-response.schema.json)）：

| 键 | 类型 | 约束 |
|---|---|---|
| `scope_id` | string | 解析后的显式域 |
| `domain_key` | string | 域档案键 |
| `generated_at` | string(date-time) | — |
| `total` | integer ≥0 | 该域记忆条数（当前完整投影版本） |
| `kind_distribution` | object | 键 ⊂ {episodic, semantic, procedural}，值 integer ≥0 |
| `provenance_distribution` | object | 键 ⊂ {hard, soft, distilled}，值 integer ≥0 |
| `status_distribution` | object | 键 ⊂ {active, superseded, retired, quarantined}，值 integer ≥0 |
| `salience_distribution` | object | `{p50, p90, p95, buckets[]}`（分位 + 分桶），**由 SQL/投影层计算** |
| `consolidation_run_count` | integer ≥0 | 按 scope 计数 |
| `rollback_count` | integer ≥0 | `event_type == "rollback"` 按 scope 计数 |

**校验规则**：① 根 `additionalProperties: false`，**不得出现** `content`/`content_excerpt`/`title`/`evidence`/`query` 等自由文本键（FR-045/SC-016）；② `TRACE_BODY_ENABLED` 打开态下响应逐键相同；③ 只读实例（`instance_mode != "writer"` 或无有效租约）→ 503 `MEMORY_WRITE_UNAVAILABLE`；④ 口径与浏览/报告一致：同域同 `total`（FR-046）；⑤ 不调用 `public_entry`（避免携带 300 字摘录）。

---

## 7. 治理动作与回滚记录（既有实体的消费视图）

| 实体 | 既有载体 | 015 的读取/呈现 | 不变量 |
|---|---|---|---|
| 治理动作 | `POST /retire`、`/purge`、`/rollback`、`/rebuild`、`/promote`、`/policy`（命令模型 `MemoryCommand`/`RollbackCommand`/`RebuildCommand`/`PromoteCommand`/`PolicyCommand` 均在 `api/memory.py` 内联，`extra="forbid"`） | 前端六视图 + 强确认 + 影响面预览 | 命令契约零改动 |
| 回滚记录 | `memory_events`（`event_type="rollback"`；payload 含 `event_point`/`impact{memory_ids,scope_ids}`/`before_fingerprint`/`after_fingerprint`）+ `memory_projection_meta` | 评测层组装逐例证据；UI 呈现结果与审计指针（`event_id`+`request_id`） | 治理响应与载荷零改动 |
| 重建报告 | `POST /rebuild` 响应（六投影）+ `memory_management_audits.operation="rebuild"` + `GET /rebuild/audit` | UI 呈现重建结果与各投影一致性校验报告 | 既有 `GET /rebuild/audit` 是重建唯一审计读口 |
| 晋升 | `GET /promotion-candidates`、`POST /promote`、`GET /promotions/{task_id}` | UI 显式人工动作；无自动晋升入口 | FR-041 |
| 巩固运行 | `GET /consolidation/runs`、`GET /consolidation/runs/{run_id}` | UI 巩固报告页 | FR-042 |

**回滚语义约束**（既有实现，015 只复核）：`event_point` 与 `time_point` **必须且只能给一个**（`RollbackService.rollback`）；时间点折算为 `occurred_at <= time_point` 的末条事件；目标必须是该 scope 的现存事件；回滚**仅管理面**（`actor="management"` + `require_writer`）；回滚动作本身入权威日志（`event_type="rollback"`）；`access` 事件保留（`preserve_access: true`）。**非管理面触发回滚的成功次数必须为 0 且拒绝留审计。**

---

## 8. 定稿核销记录（Finalization Ledger）

载体：`docs/3.0-finalization.md`（独立工件）+ 报告 `goal_ledger`。形态（详见 [contracts/finalization-ledger.schema.json](./contracts/finalization-ledger.schema.json)）：

| 字段 | 类型 | 约束 |
|---|---|---|
| `ledger_version` | string | `"3.0"` |
| `generated_at` / `commit` | string | ISO8601 / 40 位 sha |
| `goals[]` | array(minItems 7, maxItems 7) | 每项 `{id: 1..7, statement, verdict: achieved\|partial\|not_achieved, evidence[] (minItems 1), disposition?}` |
| `blueprint_frozen` | boolean | 必须 `true`（正文改写次数 = 0，仅头部允许状态注记） |
| `blueprint_annotations` | array[string] | 仅头部注记 |

**校验规则**：`verdict != achieved` 时 `disposition` 必填（未达成项处置）；目标 4（巩固受益）与目标 2/3（硬锚定率、四路径串库）的证据指针必须指向本次运行的真实产物路径，**不得指向规划文档**；013 结论（`incomplete`、`default_enable_eligible=false`、开关默认关闭）零改写。

---

## 9. 实体关系

```text
Memory Benchmark Suite ──1:N──> Poisoning Case（新建数据集）
                       └─1:N──> continuity / benefit 既有数据集（复核冻结，不改写）
AOEP Obligation Case ──1:1──> 逐例执行结果 ──┐
Poisoning Case ──────1:1──> 六道断言逐条判定 ─┤
Hard Metrics Quintet（四路径/六工具/两率/锚定/隔离泄漏）─┤──> Memory Baseline Report ──> gates ──> 定稿硬门
Rollback / Rebuild / Governance Action（既有实体，只读消费）─┘                    └──> goal_ledger ──> Finalization Ledger
Memory Statistics Readout（新建只读端点）── 独立于报告，与浏览同域同口径
```

**关键依赖**：报告的三子集与 AOEP 得分依赖两份新数据集 + 既有两份数据集；硬指标块依赖真实 PG/Qdrant 与真实协议响应；`goal_ledger` 依赖报告实测值；定稿硬门 = 投毒全过 ∧ AOEP 全过 ∧ 五件套与隔离泄漏全过 ∧ 全集回归无回归（四项同时满足，FR-053/SC-019）。
