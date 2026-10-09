# Quickstart: 记忆评测治理与 3.0 定稿（015）

**Branch**: 015-memory-evaluation-governance | **Date**: 2026-10-09 | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md) | **Model**: [data-model.md](./data-model.md) | **Contracts**: [contracts/README.md](./contracts/README.md)

> 本文件是**验证/运行指南**：每条场景给出前置、命令、预期观测与判定口径。实现细节属 tasks 与实现阶段。
> **通用前置**：真实 PostgreSQL + Qdrant 可用（`DATABASE_URL`/`QDRANT_URL`）；后端可导入（`backend/src` 在 `PYTHONPATH`，或经 `backend/pyproject.toml` 安装）；writer 实例租约可获取（REST 写路径测试用 `tests/integration/memory_acceptance.writer_owner`）；冻结 `RUN_ID=015-<YYYYMMDDHHMMSS>`。
> **通用纪律**：历史产物零覆盖；零分母记 `not_measurable` + 原因，MUST NOT 记 0；安全类零容差；未执行 MUST NOT 记为通过。

---

## VS-01 投毒子集构造、入库与契约（US1/US2，FR-001/002/007/008）

```powershell
python -m pytest backend/tests/contract/test_015_memory_benchmark_datasets.py -q
```

**预期**：`eval/memory_poisoning_eval_dataset.json` 通过 [poisoning-eval-dataset.schema.json](./contracts/poisoning-eval-dataset.schema.json) 校验；`cases` ≥5 条 `role=primary` 且**全部为 `risk_tier=high`**；覆盖 `role_hijack`（含 `role_hijack_zh` 中文变体）、`identity_override`、`tool_call_manipulation` 各 ≥1；`variant_class` 非 null ≥1；`language=zh` ≥1；`construction.mode="synthetic"` 且 `public_dataset_used=false`；每条 `_meta.review_status="reviewed"` 且有 `review_notes`/`grounded_source`。
**冻结时点（Clarifications 第二轮 Q6）**：`freeze.state="frozen"`、`freeze.first_frozen_at` 存在、`freeze.preconditions` 含"全部 primary 标记为高风险"与"全部 primary 落库隔离态"两项、`freeze.iteration_scope="within the frozen variant dictionary only"`；构造期若存在未识别/未隔离用例则**不得**写入首次冻结记录。
**隔离**：`isolation.dedicated_scope=true` 且 `forbidden_scope_ids` 含既有冻结集依赖域 `366084747748704256`；本子集写入 MUST NOT 落在该域。
**只增不破坏**：新增一条对照用例后，`cases` 中既有条目逐条哈希不变。

## VS-02 投毒全链路六道断言与权威获得计数（US1，FR-003/004/005）

```powershell
python -m pytest backend/tests/integration/test_015_poisoning_suite.py -q
```

**预期**：参数化逐条执行，每条产出 `case_id`/`pattern`/`flag_observed`/`status_observed`/`criterion_met` + 八项断言布尔值与 `control_surface_changes`。
- `primary` 用例 `criterion_met=true` ⇔ `injection_flags.risk_level=="high"` **且** `status=="quarantined"`。
- `default_recall_absent`/`consolidation_input_absent`/`attachment_absent`/`working_set_absent` 全为真。
- `control_surface_changes == 0`，且该断言在 `control`/未命中变种上**同样为真**（独立于检测结果）。
- `authority_gain_counts` 四项全为 0。
- `control` 用例（low 档 / 无命中）`criterion_met=false`，**不计入拦截率分子分母**，单独记 `control_cases`。
- 重跑一次，逐条结论与首次一致（结论稳定）。

## VS-03 检测不可用路径（US1，FR-006）

**前置**：注入检测器故障注入（`strict=True` 抛错路径）。
**预期**：写入被拒（结构化错误 `MEMORY_WRITE_UNAVAILABLE`），**进程不崩溃**；provenance/**脱敏**/范围/配额/隔离校验**不放宽**（同域其他写入仍按原规则拒绝）；该条**不进入**判定分子/分母，记 `detector_unavailable_cases`，MUST NOT 记为"已拦截"。
**可验断言**：`detect()` 在 `strict=False` 下永不抛错；`sanitize_memory` 在检测失败时抛 `ValueError` 而非降级为 `active`。

## VS-04 AOEP 回滚可溯（US3，FR-015/FR-019）

> **AOEP 口径（FR-014/FR-056）**：五条不变量——回滚可溯 `traceable_rollback`、删除传播 `deletion_propagation`、权威单调 `authority_monotonicity`、provenance 保全 `provenance_preservation`、范围不扩张 `scope_non_expansion`——各 ≥2 例（合计 ≥10），五项名称与《宪法》XIII 第三条逐字对应；原 `authority_boundary` 已更名为 `authority_monotonicity`。覆盖率分配：VS-04 回滚可溯、VS-05 删除传播、VS-06 权威单调与范围不扩张（含缺失/空 scope 与歧义两类独立子用例）、VS-07 provenance 保全。

```powershell
$env:MEMORY_EVAL_EVIDENCE_DIR = "eval/runs/$env:RUN_ID/evidence"
python -m pytest backend/tests/integration/test_015_aoep_obligations.py -q -k traceable_rollback
```

**预期**（逐例，事件点与时间点各 ≥1）：
1. 权威日志存在 `event_type="rollback"` 且 `request_id` 与治理响应一致的记录；
2. `event_chain_closed=true`——以目标水位为界回放，事件 id 序列与权威日志逐项相等、无缺失、无重复（**不得**要求 id 数值连续，snowflake 稀疏）；
3. 事件 payload 的 `event_point` 与回滚前后 `memory_projection_meta.source_event_id` 一致；
4. `before_fingerprints`/`after_fingerprints` 与事件 payload 的 `before_fingerprint`/`after_fingerprint` 及独立复算值相等，**逐投影**（`relation`/`dense`/`links`/`summary`/`file`/`salience`）与 `memory_projection_meta.fingerprint` 相等；
5. `ProjectionRebuilder.inspect()` 全部 `matches_replay=true`；
6. `impact.entries` 与回滚前后 `entries` diff 计数一致；
7. **再次回滚到相邻检查点**结果自洽、指纹可复算；
8. `access` 事件保留；
9. **隔离**：逐例结果含 `isolated_scope_id`，为本次运行新建的专用隔离域；破坏性操作触及既有真实域或 013/014 冻结集依赖域（`366084747748704256`）的次数 = 0；隔离标识与运行后处置留记录。
**反例**：仅有审计记录（`request_id` 可查）而无事件链证据时，判定必须为**失败**。

## VS-05 AOEP 删除传播五投影逐投影（US3，FR-016）

```powershell
python -m pytest backend/tests/integration/test_015_aoep_obligations.py -q -k deletion_propagation
```

**预期**：墓碑化（`retire` 与 `purge` 两形态）后对 `relation`/`dense`/`links`/`summary`/`file` **五类各自独立断言**"该条可消费命中数 = 0"，逐投影记分；`projection_denominators` 五类**各自 ≥1**；`inspect()` 全部 `matches_replay=true`；权威日志**保留** `retract` 事件与来源链（`content_text`/`content_hash` 仍在事件内）。
**零分母处理**：任一类构造前分母为 0 → 该投影记 `not_measurable` + `"a zero denominator is not a measured zero"`，**不计为传播达标**，也不跳过。
**显著性不参与**：`salience` 为字段投影，不在本断言内。

## VS-06 AOEP 权威单调与范围不扩张（US3，FR-017/FR-018/FR-056）

```powershell
python -m pytest backend/tests/integration/test_015_aoep_obligations.py -q -k "authority_monotonicity or scope_non_expansion"
```

**预期**：
- **权威单调（`authority_monotonicity`，原 `authority_boundary` 更名；判据 research.md R6.3 用例构造 + R6.5 机器判据）**：越权写入（声明超出写入者权威 / 非写实例 / 只读实例）与经 MCP 面改写绑定表的尝试**全部被拒**（403 或结构化错误）；拒绝前后**权威日志 id 序列逐项相等**（`before_ids == after_ids`，逐项而非仅长度相等）、`authority` 轴取值不变、绑定表行集不变，拒绝均留审计；
- 范围不扩张：歧义或无法解析的 scope 引用被拒并**给出候选**（`AMBIGUOUS_DOMAIN_REF` / `MISSING_KNOWLEDGE_SCOPE`），无显式 scope 的写入（`record_memory` 缺 `scope_ref`）同样被拒并给出候选域，"回落最近域/全库"成功次数 = 0；MUST NOT 以"未尝试"记为 0；
- 两者逐例产出 `request_id`/`status`/影响面/前后指纹/可复现记录/`isolated_scope_id`。

## VS-07 AOEP provenance 保全（US3，FR-016/FR-056）

```powershell
python -m pytest backend/tests/integration/test_015_aoep_obligations.py -q -k provenance_preservation
```

**预期**（逐例，`retire`/`purge`/`rollback` 状态转移各 ≥1）：
1. 状态转移后 provenance 元数据与来源链**保留**；
2. 事件 payload 的 `content_hash` 仍在，且**重算值与记录值逐一相等**（可复算，不得仅"字段存在"）；
3. 权威日志**保留**墓碑/`retract` 事件与来源链，历史**未被物理回删**；
4. 受影响投影经 `reprojection_fingerprint` 复算一致；
5. 逐例产出 `request_id`/`status`/`before_fingerprints`/`after_fingerprints`/影响面/`isolated_scope_id`；判据 research.md R6.6。

## VS-08 三子集复核冻结、只增不破坏与元数据校正（US2，FR-009–FR-013）

**预期**：
- `eval/memory_continuity_eval_dataset.json`（`014.eval.1`，16 条）复核结论为"接受或修订"，四类场景齐备、`zh=8`、逐条 `_meta.review_status="reviewed"`；
- `eval/consolidation_eval_dataset.json`（`013.eval.1`，6 条）复核确认规模与对照口径（相对提升；基线为零判不可计算），如实继承 013 结论（`incomplete`、`default_enable_eligible=false`、开关默认关闭）；
- 三份数据集均带 `dataset_version`/`frozen`/`snapshot_hash`；
- **元数据校正（有界授权）**：`eval/memory_continuity_eval_dataset.json` 的 `$.source.human_review` 仍写 `"pending T053 human review; every query _meta.review_status is pending_review"`，与逐条 `reviewed` 矛盾；按 spec 要求**校正该数据集级字段**并留变更理由与前后值。**边界**：`queries[]` 全部 16 条（问题、判据、锚点、`_meta`）**逐字节不变**（哈希 pin）；MUST NOT 借"校正"改写任何条目；
- 既有条目被原地改写/删除次数 = 0。

## VS-09 基准报告产出、契约校验与历史产物不覆盖（US4，FR-021–FR-027）

```powershell
python eval/run_memory_baseline.py --output "eval/runs/$env:RUN_ID/memory_baseline_report.json" `
    --poisoning eval/memory_poisoning_eval_dataset.json `
    --aoep eval/memory_aoep_obligation_dataset.json `
    --aoep-results "eval/runs/$env:RUN_ID/evidence/aoep-cases.json"
```

**预期**：报告经 [memory-baseline-report.schema.json](./contracts/memory-baseline-report.schema.json)（+ 共享 `$defs` 合并）校验；含三子集指标（各自 `watermark`）、`aoep.by_invariant` 得分、`hard_metrics` 五件套 + 隔离泄漏 + **`projection_integrity`（FR-057）与 `state_metadata_completeness`（FR-058）两个新增实测子块**、`latency`（`env_sensitive=true`）、`per_case`、`reproducibility`、`not_measurable[]`、`gates`、`goal_ledger`（7 项，每项 `{id, statement, verdict, evidence[], disposition?}`）、**`regression`（必需键）**、`evidence_paths`。
- 首次运行在**不存在**时播种 `eval/memory_baseline_report.json`；
- 第二次运行写入新的 `eval/runs/<RUN_ID2>/…`，**首次报告逐字节不变**；对已存在路径再写必须被**拒绝**（退出码 ≠ 0）；
- 同快照同版本重跑两遍，非延迟指标 1% 相对容差内一致；延迟不参与该判定；
- 巩固关闭时 `not_measurable` 必含 `benefit.relative_gain`。

## VS-10 硬指标五件套 + 隔离泄漏全量实测（US5，FR-028–FR-034）

**预期**：
1. **跨域串库**：四路径（权威事件日志/关系/向量/文件）各自 `examined ≥1` 且 `leaks=0`；任一路径 `examined=0` → 该路径 `not_measurable`，**整体不得判达标**（这是 014 遗留 `cross_domain_leakage.value = null` 的修复点）；
2. **六工具契约合法率**：`tools_checked` 恰六个（`search_knowledge`/`get_evidence`/`list_knowledge_domains`/`recall_memory`/`start_work`/`record_memory`），分母非零，含非法输入负例且负例被拒；
3. **来源可定位率** 与 **记忆 provenance 完备率** 各 100%，**口径分开不合并**；
4. **硬记忆锚定率**：`hard_items_examined > 0` 且无锚写入一律被拒，给出被拒样本与错误码分布（不得沿用 014 的 `hard_items_examined = 0` 结论）；
5. **隔离泄漏**：默认召回/巩固窗口/附加记忆/工作集/控制面**五处独立分母**，出现次数均为 0。
6. **投影可复算与运行期只读（FR-057）**：`hard_metrics.projection_integrity` 对**六投影**（`relation`/`dense`/`links`/`summary`/`file`/`salience`）各给出分母（`examined ≥1`）与结论（`drift = 0`），投影完整率 100%；任一分母为零 → 该投影记 `value = "not_measurable"` / `rate = null` + 原因且整体不得判达标；运行期只读以真实 PG/Qdrant 与真实协议响应实测，**不得以 route 打桩或组件测试替代**；`all_views_measured == true` 且 `all_passed == true` 才计入 `hard_metrics.all_passed`。
7. **六轴状态元数据齐备率（FR-058）**：`hard_metrics.state_metadata_completeness` 对 `authority`/`scope`/`mutability`/`provenance`/`recoverability`/`actionability` **六轴逐轴给出分母 `examined`、缺失数 `missing` 与结论**（齐备率 100%）；任一轴分母为零 → 该轴记 `not_measurable` + 原因且整体不得判达标；`all_passed == true` 才计入 `hard_metrics.all_passed`。
8. **零分母守卫与 `all_passed` 绑定（SC-026）**：四个比率块以 `total == 0` 判零分母、`leakPath`/`countBlock`/两新子块以 `examined == 0` 判零分母，MUST 记 `not_measurable` 并给原因，MUST NOT 以 `rate/value = 1.0` 过关；**四个比率块的 `passed` 是整数通过条数（014 口径），"全过"须写 `passed >= 1` 且 `rate == value == 1`，MUST NOT 写成布尔 `passed: true`**；`hard_metrics.all_passed` MUST 由各子块共同决定，不得独立写 `true`。
9. **AOEP 五条不变量（FR-056）**：`aoep.by_invariant` 键集恰为五项齐全，每条 `passed ≥2`，合计 ≥10 例；`aoep.all_passed = 每不变量 passed ≥ 2 且 failed == 0 且 not_measurable == 0`。
**反例**：以测试桩或预设结论替代实测即失败；安全类以 1% 容差替代判定即失败；零分母被计为达标即失败。

## VS-11 统计端点（US7，FR-044–FR-046）

```powershell
python -m pytest backend/tests/contract/test_015_memory_stats_schema.py backend/tests/unit/test_015_memory_statistics.py -q
```

**预期**：
- `GET /api/memories/stats?scope_ref=<域>` 返回 `total`/`kind_distribution`/`provenance_distribution`/`status_distribution`/`salience_distribution`（分位 + 分桶）/`consolidation_run_count`/`rollback_count`，经 [memory-stats-response.schema.json](./contracts/memory-stats-response.schema.json) 校验；
- 响应中 `content`/`content_excerpt`/`title`/`evidence`/`query` 等自由文本键出现次数 = 0，且 `TRACE_BODY_ENABLED=true` 时响应**逐键相同**；
- 只读实例或无效租约访问 → 503 `MEMORY_WRITE_UNAVAILABLE`；缺 `scope_ref` → 422；
- 同域 `total` 与 `GET /api/memories` 的 `total` 一致；
- `GET /runtime/metrics` 响应与 006 契约**零改动**（回归断言）。

## VS-12 治理 UI 六视图、scope 门、强确认与单条边界（US6，FR-035–FR-043）

```powershell
cd frontend
pnpm build
pnpm exec playwright test tests/memory.spec.ts tests/memory-governance.spec.ts
```

**预期**：
- `pnpm build`（`tsc -b` 严格模式）通过——`en.ts`/`zh.ts` 键集一致，缺键即失败；
- 既有 `tests/memory.spec.ts` 两条断言保持通过（无横向溢出；写不可用时 `MEMORY_WRITE_UNAVAILABLE` 出现在 Alert 中）；
- 新规格：六视图（浏览/治理/回滚/投影重建/晋升/巩固报告）+ 统计面板可达；六维过滤可用；**未选域时对 `/api/memories?**` 与 `/api/memories/stats` 的请求次数为 0**，页面不出现正文；
- `purge`/`retire`/`rollback` 必须经 `ConfirmActionModal`（需输入目标确认值）方可提交；缺少强确认即可提交 = 失败；
- 无 `rowSelection`/`Checkbox`/批量入口；
- 回滚与投影重建视图在管理面可见，MCP 面无对应入口；
- 投影重建失败显式呈现；晋升无自动入口；巩固报告含失败与拒绝原因。

## VS-13 文档债、3.0 核销与全集回归（US8，FR-047–FR-054）

```powershell
python eval/run_regression_015.py --run-id $env:RUN_ID
```

**预期**：
- `docs/1.0-iteration-roadmap.md`（含 001–015 与 3.0 状态行，注明该路径被 `.gitignore` 忽略的事实）、`README.md` 记忆能力章（无超售）、`docs/技术架构说明书.md`（记忆回路章 + §6/§7 最小修订）、001–014 `spec.md` Status（011–014 → `Delivered`；001–010 复核一致；013 未达成结论零改写）齐备；
- `docs/3.0-finalization.md` 经 [finalization-ledger.schema.json](./contracts/finalization-ledger.schema.json) 校验：七项逐项判定 + 证据指针 + 未达成项处置；`blueprint_frozen=true`；目标 4 如实记 `not_achieved`/不可计算并给处置；目标 2/3 的证据指针指向本次真实产物；
- 全集回归：001–014 全部组按各自口径重跑，产物落 `eval/runs/<RUN_ID>/`，非延迟 1% 容差、安全零容差；**依赖模型的组（005 Agent 编排、013 巩固等）强制 record + replay 两轮**——记录轮冻结模型响应与缓存指纹，重放轮（真实网络调用 = 0）为唯一过闸依据，实时调用结果不得过闸，缓存指纹与重放网络调用计数登记在报告 `regression.groups[]`（`mode` 仅允许 `single_round` / `record_then_replay`）；未执行项记 `not_executed`；历史报告逐字节零覆盖；
- 定稿硬门四项（投毒全过 ∧ AOEP 全过 ∧ 五件套与隔离泄漏全过 ∧ 全集回归无回归）同时满足方可判通过。
- **规格同步项（已核验）**：FR-054 正文（spec.md:275）**已含** record + replay 要求（记录轮冻结模型响应与缓存指纹；重放轮真实网络调用 = 0 且为唯一过闸依据）；本条为 T061 的核验登记对象，不再编辑正文。

---

## 不得声称（本 Feature 的诚实边界）

- 不得把"测试通过"写作"指标实测达标"（FR-034）。
- 不得把零分母写作 0 或 100%（FR-024）。
- 不得把巩固受益写作已达成——013 结论为 `incomplete`、默认关闭、无可主张受益，本 Feature 如实继承且不宣称改进（FR-012/FR-026/SC-021）。
- 不得声称 SSE 刷新已生效：`publish_event` 在 `backend/` 内无调用点，当前流只发 `heartbeat`；治理 UI 的正确性来自 REST 拉取（research.md R10）。
- 不得声称架构说明书为全量 3.0 重写；范围为"新增记忆回路章 + §6/§7 最小修订"（澄清 Q5）。
- 不得以"序号链无缺口"的字面含义（id 数值连续）判定失败——判据是回放序列与权威日志逐项相等（research.md R6）。
- **不得声称已完成目标 MCP 宿主评测或成本评测**——该两项不在本 Feature 范围（宿主证据仅沿 FR-054 回归组重跑），须在报告与 T073 范围决策登记中如实记为范围外（FR-060）。
- **不得把 015 未自测的 `supersede` 链、确定性裁决、正身不可经记忆通道变更表述为 015 已验证**——三项属 012/013 既有交付，仅由 FR-054 回归组重跑承担（FR-054/FR-056）。

---

## VS-14 缺失 scope 引用的读写拒绝（US3，FR-061/SC-028）

```powershell
python -m pytest backend/tests/integration/test_015_aoep_obligations.py -q -k "scope_non_expansion and missing_scope"
```

**预期**（与 VS-06 的**歧义**用例**分开构造**，各自样本量 ≥1）：
1. `record_memory` **缺失或为空**（含空串与只含空白）`scope_ref` → 被拒（`MISSING_KNOWLEDGE_SCOPE` 结构化错误）并给出候选域；读取类调用同规则；
2. "回落最近域" / "回落全库" 成功次数 = 0；
3. 拒绝本身留审计（响应错误码或权威日志可观测）；
4. **缺失 ≠ 歧义**：两类用例分别记分、分别给出非零样本量；MUST NOT 以"未尝试"记为 0；
5. 逐例产出 `request_id`/`status`/影响面/可复现记录/`isolated_scope_id`；判据 research.md R6.4 与 spec FR-061。
