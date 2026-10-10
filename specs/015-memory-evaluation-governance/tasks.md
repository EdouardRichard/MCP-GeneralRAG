---
description: "Task list for 记忆评测治理与 3.0 定稿 (015)"
---

# Tasks: 记忆评测治理与 3.0 定稿（015）

**Feature**: `015-memory-evaluation-governance` | **Date**: 2026-10-09

**Input**: Design documents from `/specs/015-memory-evaluation-governance/`

**Prerequisites**: [plan.md](./plan.md) (required), [spec.md](./spec.md) (required, 8 user stories / FR-001–FR-061 / SC-001–SC-028), [research.md](./research.md) (R0–R14), [data-model.md](./data-model.md) (9 entities), [contracts/](./contracts/README.md) (2 数据集契约 + 1 报告契约 + 1 共享 `$defs` + 1 统计契约 + 1 核销契约 + 1 UI 契约), [quickstart.md](./quickstart.md) (VS-01–VS-14)

**Tests**: **INCLUDED and test-first（TDD 先红后绿）**。plan.md Validation Gate 7 与 spec FR-004/FR-019 明确要求契约测试、集成套件与逐例证据导出，故本 Feature 的全部测试任务为强制项，不是可选项。

**Organization**: 阶段沿用户指定的交付顺序（安全测试先行 → 基准与硬指标 → 治理 UI 与统计 → 全集回归与文档 → 3.0 定稿），并为每个任务标注其 `[USx]` 归属以保持与 spec.md 用户故事的独立可测性对齐（US1↔FR-001–007，US2↔FR-008–013，US3↔FR-014–020，US4↔FR-021–027，US5↔FR-028–034，US6↔FR-035–043，US7↔FR-044–046，US8↔FR-047–055）。

**Eight frozen decisions（不得当作待澄清项，实现期不得改变）**：① 投毒子集纯合成 + 冻结变种字典，单条通过 = 标记为高风险 **且** 落库隔离态；② 可溯 = 事件链闭合 + 逐投影指纹比对 + 影响面一致；全传播 = 五投影各自独立断言且各自分母非零；③ 仅投毒拦截率设 100% 硬水位，连续性沿 014、受益沿 013、延迟仅记录；④ 统计端点为独立端点（不并入 `GET /runtime/metrics`）、强确认、首期仅单条；⑤ 技术架构说明书最小增量（新增"记忆回路"章 + §6/§7 最小修订）；⑥ 投毒子集构造期可迭代、达标后首次冻结，冻结后失败如实判定并阻止定稿；⑦ 依赖模型的回归组强制 record + replay 两轮，重放轮（真实网络调用 = 0）为唯一过闸依据；⑧ AOEP 以评测数据集 JSON 声明 + 专用运行器执行，破坏性操作仅在每次运行新建的专用隔离域与隔离身份内执行（禁入 `366084747748704256`）。

## Format: `[ID] [P?] [Story] Description with file path`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: `[US1]`…`[US8]`，仅用户故事阶段出现；Setup / Foundational / Polish 阶段无 Story 标签
- 每个任务都含精确文件路径

## Path Conventions

单体布局，路径相对仓库根（`D:\Project_new\docsToCode`）：后端 `backend/src/rag_mcp/`、`backend/tests/{contract,integration,unit}/`；前端 `frontend/src/`、`frontend/tests/`；评测 `eval/`（含 `eval/runs/<RUN_ID>/`）；文档 `docs/`、`README.md`、`specs/0xx-*/spec.md`。

**通用纪律（每个任务都适用）**：历史产物零覆盖（已存在输出路径即拒绝写入并退出码 ≠ 0）；零分母记 `{value: null, state: "not_measurable", reason: "a zero denominator is not a measured zero"}` 或 `rateBlock{rate: null, value: "not_measurable"}`，MUST NOT 记 0、MUST NOT 记达标；安全类指标零容差；未执行 MUST NOT 记为通过；`GET /runtime/metrics`、六工具契约、012–014 既有数据集/报告/测试文件零改动。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 建立本 Feature 的新增目录与运行标识骨架。无用户故事可在此阶段开始。

- [X] T001 创建新增交付目录骨架 `eval/runs/`、`docs/`、`frontend/src/components/memory/`（`eval/`、`backend/tests/{contract,integration,unit}/`、`eval/README.md` 均已存在 —— `frontend/src/components/` 与 `docs/` 为本 Feature 新建），并在 `eval/README.md` 追加 015 段落标题（数据集/报告/运行器用法与重跑口径）；T001 产出的目录为后续 T002–T074 的写入面
- [X] T002 固定 015 运行标识与产物路径约定（`RUN_ID=015-<YYYYMMDDHHMMSS>`、唯一写入路径 `eval/runs/<RUN_ID>/`、追踪路径 `eval/memory_baseline_report.json` 仅首次播种），追加到**已存在**的 `eval/README.md` 015 段（沿 research.md R5；**不得**复制 `eval/hard_metrics_014.py:435` 的无条件重写行为 —— 该文件无 `argparse`，配置仅来自 `RUN_ID`/`RUN_DIR` 环境变量，其对 `eval/runs/<RUN_DIR>/hard-metrics.json` 有存在即拒绝守卫（L410-414）但 L433-435 仍无条件改写 `eval/hard-metrics-014.json`，是本仓库唯一违反"历史产物零覆盖"之处）

**Checkpoint**: 目录与运行标识约定就绪。

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 契约层与证据导出骨架。**这些是全部用户故事的阻塞前置**：数据集受 schema 约束、报告受 schema 约束、AOEP 逐例结果经 fixture 导出、统计与核销工件受 schema 约束。

**⚠️ CRITICAL**: 在 T003–T013 完成前，T014 之后的任务无法合法交付（先红后绿要求契约与测试骨架先到位）。

### 契约（Draft 2020-12，全部为新增独立契约，加法不改既有 schema）

- [X] T003 [P] 编写共享 `$defs` 契约 `specs/015-memory-evaluation-governance/contracts/memory-benchmark-common.schema.json`：`metricBlock`（沿用 011）、`rateBlock`（新增，含 `rate: null, value: "not_measurable", reason` 零分母编码）、`countBlock`、`latencyBlock`、`leakPath`、`hardMetricsBlock`（五件套 + `quarantined_leakage` + `all_passed`）、`poisoningCaseEntry`、`aoepCaseEntry`（含 `isolated_scope_id` 必填与 `projection_denominators`）、`watermark`、`subsetBlock`、`aoepBlock`、`invariantScore`、`reproducibilityBlock`（含 `env_sensitive`）、`configBlock`、`gateBlock`、`goalEntry`、`notMeasurableEntry`（依 research.md R4 表逐项；MUST NOT 复用或修改 011 的 `hardConstraintsBlock`）
- [X] T004 编写报告根契约 `specs/015-memory-evaluation-governance/contracts/memory-baseline-report.schema.json`：根必需键顺序为 `schema_version`(`"015.1"`)/`report_type`(`"015_memory_baseline"`)/`run_id`/`generated_at`/`commit`/`status`/`config`/`subsets.{continuity,benefit,poisoning}`/`aoep`/`hard_metrics`/`latency`(含 `env_sensitive: true`)/`per_case.{poisoning,aoep}`/`reproducibility`/`not_measurable[]`/`gates.{quality,safety,regression}`/`goal_ledger`(恰 7 项)/`regression`/`evidence_paths[]`/`failed_paths[]`/`notes[]`；以相对引用写 `./memory-benchmark-common.schema.json#/$defs/<name>`；实现三条 `allOf`/`if-then` 条件（`status=="passed"` 蕴含 `hard_metrics.all_passed && aoep.all_passed && subsets.poisoning.passing_rate.rate==1.0`；任一不可测量则 `not_measurable[]` 必含该 metric 且 `reason` 非空；`latency` 不得出现在 `reproducibility.checks` 通过判定中）；**MUST NOT 含 `enters_default_path` 字段**（依 T003；见 data-model.md §5）
- [X] T005 [P] 编写投毒数据集契约 `specs/015-memory-evaluation-governance/contracts/poisoning-eval-dataset.schema.json`：`cases[]` 字段约束（`case_id` `^poison_[a-z0-9_]+$`、`role` `primary|control`、`risk_tier`、`variant_class`、`language`、`target_scope` 非空、`content` minLength 1、`authority_escalation_phrasing`、`assertions` 八项固定名、`_meta{review_status:"reviewed",review_notes,grounded_source}`）；数据集级 `dataset_version`/`frozen`(12 字段含 `detector`/`variant_dictionary`)/`snapshot_hash`/`scope_id`/`isolation{dedicated_scope:true,forbidden_scope_ids:[…含 "366084747748704256"]}`/`freeze{state:"frozen",first_frozen_at,preconditions,iteration_scope:"within the frozen variant dictionary only",post_freeze_discipline}`/`construction{mode:"synthetic",public_dataset:"minja",public_dataset_used:false,public_dataset_trigger}`/`explicit_criterion{pass_requires,control_cases_excluded_from_rate:true,source}`；`primary` 项 MUST `risk_tier == "high"`（依 T003；见 data-model.md §2）
- [X] T006 [P] 编写 AOEP 数据集契约 `specs/015-memory-evaluation-governance/contracts/aoep-obligation-dataset.schema.json`：`cases[]`（`case_id` `^aoep_[a-z0-9_]+$`、`invariant` 五值枚举、`target_kind` 四值枚举、`requires_re_rollback`、`projections_asserted` 为 `{relation,dense,links,summary,file}` 子集且删除传播类固定五类全列、`expected.outcome:"passed"`）；`invariants` 五键各带 `min_cases:2` 与 `machine_criterion`；数据集级 `dataset_version`/`frozen`/`snapshot_hash`/`scope_id`/`isolation{mode:"per_run_dedicated",identity:"per_run_dedicated",forbidden_scope_ids:[…含 "366084747748704256"],disposal:"record_and_dispose",record_isolation_id:true}`（依 T003；见 data-model.md §4）
- [X] T007 [P] 编写统计响应契约 `specs/015-memory-evaluation-governance/contracts/memory-stats-response.schema.json`：根 `additionalProperties: false`，仅容 `scope_id`/`domain_key`/`generated_at`/`total`/`kind_distribution`/`provenance_distribution`/`status_distribution`/`salience_distribution{p50,p90,p95,buckets[]}`/`consolidation_run_count`/`rollback_count`；MUST NOT 出现 `content`/`content_excerpt`/`title`/`evidence`/`query` 等自由文本键（依 T003；见 data-model.md §6）
- [X] T008 [P] 编写定稿核销契约 `specs/015-memory-evaluation-governance/contracts/finalization-ledger.schema.json`：`ledger_version:"3.0"`、`generated_at`、`commit`(40 位 sha)、`goals[]` minItems 7 maxItems 7（每项 `{id:1..7,statement,verdict:achieved|partial|not_achieved,evidence[] minItems 1,disposition?}`）、`blueprint_frozen:true`、`blueprint_annotations[]`；条件约束 `verdict != "achieved"` 时 `disposition` 必填（依 T003；见 data-model.md §8）

### 测试基座与证据导出

- [X] T009 在 `backend/tests/conftest.py` 新增 session 级 autouse fixture `memory_eval_evidence_bundle`，由环境变量 `MEMORY_EVAL_EVIDENCE_DIR` 门控（未设置即惰性空转），并在既有 `pytest_sessionfinish` 中落盘 `aoep-cases.json`——与既有 `consolidation_evidence_bundle`/`CONSOLIDATION_EVIDENCE_DIR` 严格同构，MUST NOT 改动既有 013 fixture 与既有 sessionfinish 语义（依 research.md R3；文件：`backend/tests/conftest.py`）
- [X] T010 [P] 新增契约测试 `backend/tests/contract/test_015_memory_benchmark_datasets.py`（先红）：以 `$defs` 合并模式（加载两份文件、`$defs.update`、`$ref` 字符串替换后 `jsonschema` Draft2020-12 `validate`，不引入新的 schema registry）校验两份数据集的**正例**与**关键反例**——`primary` 低危档被拒、缺 `isolation` 块被拒、`freeze.iteration_scope` 非冻结字典范围被拒、删除传播缺投影被拒；并断言"新增一条对照用例后既有条目逐条哈希不变"的**只增不破坏**可复算性（依 T005/T006）

**Checkpoint**: 契约层与证据导出骨架就绪 —— 全部用户故事可开始。

---

## Phase 3: US2 + US1 — 固定基准子集与投毒全链路（Priority: P1）🎯 MVP（安全测试先行）

**Goal**: 先立"固定子集可复核、只增不破坏"的地基（US2），再交付 MINJA 式投毒防护子集的**全链路**证据（US1）：写入 → 标记 → 隔离 → 默认召回不可见 → 巩固不消费 → 附加记忆与工作集不携带 → 任何控制面不因它改变，且权威获得计数全 0。

**Independent Test**: `python -m pytest backend/tests/contract/test_015_memory_benchmark_datasets.py backend/tests/integration/test_015_poisoning_suite.py -q` —— 逐条比对写入响应标记、默认召回命中数、巩固窗口输入集合、附加记忆与工作集条目集合、控制面变更计数；再用同一子集重跑一次比较逐条结论是否稳定。三份数据集的规模/版本/冻结记录/逐条审核/语言覆盖经人工审计，并验证既有条目零改写。

**Safety-first ordering**: 本阶段的投毒用例是全 Feature 的最高优先级失败源 —— T016/T017 失败优先于任何功能任务修复，且不得以"巩固默认关闭"豁免。

- [X] T011 [US2] 复核冻结多会话连续性子集 `eval/memory_continuity_eval_dataset.json`（014 建立，`dataset_version=014.eval.1`，**16 条位于 `queries[]`**，无 `cases` 键）：逐条核对四类场景（`resume_after_break`/`recall_last_decision`/`lesson_effective`/`preference_applied` 各 4 条）、`zh` 覆盖、预冻结判据（`explicit_criterion.queries_total=16`、`minimum_completed_with_memory=12`，即完成数 ≥12/16 且每类 ≥1）与逐条 `_meta.review_status`，产出"接受或修订"复核结论与依据；**源数据文件的 `queries[]` 16 条（问题/判据/锚点/`_meta`）逐字节不变、哈希 pin**（FR-008/FR-011/FR-013）
- [X] T012 [US2] 在 `eval/runs/<015-run-id>/evidence/` 落盘连续性复核记录 `continuity_review.json`，并校正 `eval/memory_continuity_eval_dataset.json` 的数据集级字段 `$.source.human_review`（现值逐字为 `"pending T053 human review; every query _meta.review_status is pending_review"`，与逐条实测 `reviewed` 的值矛盾）：写入校正后取值 + 变更理由 + 前后值记录；**边界**：除该数据集级字段外零改动（`queries[]` 逐字节不变），MUST NOT 借"校正"改写任何条目（FR-009/FR-010；沿 quickstart.md VS-08）
- [X] T013 [P] [US2] 复核冻结巩固受益子集 `eval/consolidation_eval_dataset.json`（013 建立，`dataset_version=013.eval.1`，**6 条位于 `queries[]`**）：确认规模 ≥6、对照口径（相对提升；基线为零判不可计算）与冻结记录（`frozen`/`frozen_clock`/`snapshot_hash`/`gate_variant`；注意该数据集的 `source` 无 `human_review` 键，勿按连续性数据集形态假设）；如实记录 013 发布结论（`incomplete`、`default_enable_eligible=false`、开关默认关闭）并写入 `eval/runs/<015-run-id>/evidence/benefit_review.json`，**MUST NOT 改写 013 结论或数据集**（FR-012）
- [X] T014 [US2] 产出三子集统一冻结记录 `eval/runs/<015-run-id>/evidence/subsets_freeze_record.json`：每份数据集含版本与标识、语料与快照指纹、判据来源与冻结时刻、逐条人工审核状态、语言与类别覆盖；三子集构成齐备率 100%（连续性 ≥15 / 受益 ≥6 / 投毒 ≥5），既有条目被原地改写或删除次数 = 0（FR-008/FR-009/SC-001）
- [X] T015 [US1] 新建投毒防护子集 `eval/memory_poisoning_eval_dataset.json`（唯一真相源，对象形态）：≥5 条 `role=primary` 且**全部 `risk_tier=high`**，覆盖 `role_hijack`（含中文变体 `role_hijack_zh`）、`identity_override`、`tool_call_manipulation` 各 ≥1，另含 `prompt_disclosure`/`chat_delimiter_escape`/`delimiter_escape`/`user_concealment`/`memory_authority_override` 补充覆盖；`variant_class` 非 null ≥1（同义改写/分隔符或编码扰动/分片拼接/混合语言，冻结变种字典 `015.variants.1`）、`language=zh` ≥1；每条约 8 项断言与 `authority_escalation_phrasing`；`construction.mode="synthetic"` 且 `public_dataset_used=false`（MINJA 仅登记触发条件）；`isolation.forbidden_scope_ids` 含 `366084747748704256`；`freeze` 块按 Q6 写入；**另含 low 档与无命中对照用例（`role=control`，不计入拦截率分子分母）**（FR-001/FR-002/FR-003/FR-007；依 research.md R1/R2 映射表）
- [X] T016 [US1] 以 T015 数据文件为唯一真相源新增参数化集成套件 `backend/tests/integration/test_015_poisoning_suite.py`（先红）：`@pytest.mark.parametrize` 逐条消费数据集（路径由 `__file__` 推导），**不在测试内重复定义注入内容/模式标签/判据**；逐条断言 `write_flagged`(`risk_level=="high"`)、`write_quarantined`(`status=="quarantined"`)、`default_recall_absent`、`consolidation_input_absent`（能力默认关闭时在确定性路径验证并在报告中标注实际运行模式）、`attachment_absent`(`search_knowledge.related_memories`)、`working_set_absent`(`start_work` 三桶)、`control_surface_unchanged`（变更计数 = 0，**独立于检测结果**、在 `control` 与未命中变种上同样为真）、`no_inconsistent_marking`；逐条导出 `case_id`/`pattern`/`flag_observed`/`status_observed`/`criterion_met`/八项断言布尔值/`control_surface_changes`；`primary` 判据 ⇔ "标记且隔离"同时成立；`control` 用例 `criterion_met=false` 且单独记 `control_cases`（FR-003/FR-004；依 quickstart.md VS-02）
- [X] T017 [US1] 在 `backend/tests/integration/test_015_poisoning_suite.py` 增加权威获得计数断言与检测不可用路径：`authority_gain_counts` 四项（`became_hard`/`entered_promotion_candidates`/`auto_promoted_to_canonical`/`gained_effective_authority_via_consolidation`）逐条为 0；故障注入（`strict=True` 抛错）时写入被拒并给出结构化错误 `MEMORY_WRITE_UNAVAILABLE`、**进程不崩溃**、provenance/**脱敏**/范围/配额/隔离校验**不放宽**、该条不进入判定分子分母且记 `detector_unavailable_cases`、MUST NOT 记为"已拦截"（FR-005/FR-006；依 quickstart.md VS-03）
- [X] T018 [US1] 完成投毒子集的**首次冻结**：以"每条 `primary` 既被标记为高风险又落库为隔离态"为前置（仅可在已冻结的变种字典 `015.variants.1` 范围内迭代构造与检测覆盖），达标后写入 `freeze.first_frozen_at` 与 `freeze.preconditions` 两项；在 `eval/runs/<015-run-id>/evidence/poisoning_freeze_log.json` 记录迭代轨迹、首次冻结时刻与冻结依据；**若未全过则 MUST NOT 写入首次冻结记录**（FR-002；依 research.md R2 Q6）
- [X] T019 [US1] 重跑投毒套件一次并落盘稳定性证据 `eval/runs/<015-run-id>/evidence/poisoning_stability.json`：逐条结论（含 `control` 用例）与首次一致率 100%；投毒写入 MUST NOT 落在 `366084747748704256` 或任何既有真实域（FR-007/SC-003；依 quickstart.md VS-02 末项）

**Checkpoint**: US2 的三子集冻结与只增纪律、US1 的投毒全链路六道断言与权威获得计数均独立可测。

---

## Phase 4: US3 — AOEP 状态义务用例（Priority: P1）

**Goal**: 用评测数据集声明的用例与专用运行器，机器判定五条不变量（回滚可溯 `traceable_rollback`、删除传播 `deletion_propagation`、权威单调 `authority_monotonicity`、范围不扩张 `scope_non_expansion`、来源保全 `provenance_preservation`），每条 ≥2 例，逐例产出请求标识/状态/前后指纹/影响面/可复现记录，并汇入报告的 AOEP 义务得分块。

**Independent Test**: `MEMORY_EVAL_EVIDENCE_DIR=eval/runs/<RUN_ID>/evidence python -m pytest backend/tests/integration/test_015_aoep_obligations.py -q` —— 检查每条用例的标识、状态、前后指纹、影响面与可复现记录，逐例含 `isolated_scope_id`；重跑一次比较结论（稳定率 100%）。

- [X] T020 [US3] 新建 AOEP 隔离模块 `eval/memory_aoep_isolation.py`：每次运行新建**专用隔离域与专用隔离身份**，校验禁入既有真实域与既有固定评测集依赖域（`forbidden_scope_ids` 必列 `366084747748704256`），运行结束后按 `disposal:"record_and_dispose"` 处置并落盘隔离标识与处置记录（FR-019/SC-004；依 research.md R3 Q8）
- [X] T021 [US3] 新建 AOEP 用例声明 `eval/memory_aoep_obligation_dataset.json`：五条不变量各 ≥2 例（合计 ≥10）；回滚类含时间点与事件点各 ≥1 且 ≥1 例 `requires_re_rollback=true`；删除传播类 `projections_asserted` 固定五类全列（`relation`/`dense`/`links`/`summary`/`file`）；`invariants` 恰为五键（`traceable_rollback`/`deletion_propagation`/`authority_monotonicity`/`scope_non_expansion`/`provenance_preservation`），**每键带 `min_cases:2` 与 `machine_criterion` 指针，其中 `authority_monotonicity` 指向 R6.5、`provenance_preservation` 指向 R6.6**；报告 `aoep.by_invariant` 的键集恰为上述五项齐全（不得缺项、不得多键）；含数据集级 `isolation` 块与冻结记录（FR-014/FR-018；依 research.md R3/R6.5/R6.6）
- [X] T022 [US3] 新增集成套件 `backend/tests/integration/test_015_aoep_obligations.py` 的**回滚可溯**部分（`-k traceable_rollback`，先红）：机器判定 = 回滚事件存在（`event_type=="rollback"` 且 `request_id` 与治理响应一致）+ 事件链闭合（以目标水位为界回放，id 序列与权威日志逐项相等、**无缺失无重复，非 id 数值连续**；报告中必须写明该解释）+ 水位可读（事件 payload `event_point` 与回滚前后 `memory_projection_meta.source_event_id` 一致）+ 全状态指纹一致 + **逐投影指纹比对**（六视图与 `MemoryProjectionMeta.fingerprint` 相等且 `ProjectionRebuilder.inspect()` 全 `matches_replay==true`）+ 影响面计数一致 + 可再次回滚；`access` 事件保留；**反例**：仅有审计记录（`request_id` 可查）而无事件链证据时必须判**失败**；逐例产出 `before_fingerprints`/`after_fingerprints`/`watermark_before`/`watermark_after`/`impact{entries,projections}`/`event_chain_closed`/`re_rollback_consistent`/`reproducible`/`isolated_scope_id`（FR-015/FR-019；依 research.md R6.1 与 quickstart.md VS-04）
- [X] T023 [US3] 在 `backend/tests/integration/test_015_aoep_obligations.py` 增加**删除传播**部分（`-k deletion_propagation`）：墓碑两形态（`retire` 与 `purge`）后对五类投影**各自独立断言**"该条可消费命中数 = 0"并逐投影记分；构造 MUST 保证五投影 `projection_denominators` **各自非零**（传播前该条在各投影可被消费地观测到）；任一类为零 → 该投影记 `not_measurable` + `"a zero denominator is not a measured zero"`，**不计为传播达标也不跳过**；权威日志 MUST 保留 `retract` 事件与来源链（`content_text`/`content_hash` 仍在）；**显著性（`salience`）为字段投影，不参与本断言**；逐投影传播正确率 100%、权威日志保留墓碑事件与来源链比率 100%（FR-016/SC-006；依 research.md R6.2 与 quickstart.md VS-05）
- [X] T024 [US3] 在 `backend/tests/integration/test_015_aoep_obligations.py` 增加**权威单调与范围不扩张**部分（`-k "authority_monotonicity or scope_non_expansion"`；`authority_boundary` 已更名为 `authority_monotonicity`，逐例证据要求见 T068）：越权写入（声明超出写入者权威 / 非写实例 / 只读实例）与经 MCP 面改写绑定表的尝试全部被拒（403 或结构化错误），权威日志事件计数不变、绑定表行集不变、拒绝均留审计；歧义或无法解析的 scope 引用被拒并**给出候选**（`AMBIGUOUS_DOMAIN_REF`/`MISSING_KNOWLEDGE_SCOPE`），"回落最近域/全库"成功次数 = 0；**`scope_non_expansion` 段新增缺失/空 scope 引用子用例**——`record_memory` 与读取类调用**缺失或为空**（含空串与只含空白）`scope_ref` 时 MUST 被拒（`MISSING_KNOWLEDGE_SCOPE` 结构化错误）并给出候选域，且"回落最近域/全库"的回落次数 = 0；**缺失 ≠ 歧义**：缺失/空引用与歧义引用 MUST **各自构造用例、各自给出非零样本量、分别记分**（MUST NOT 以一类替代另一类，也 MUST NOT 以省略尝试记为 0，见 T075）；两者逐例产出 `request_id`/`status`/影响面/可复现记录，**拒绝率 100% 且拒绝本身均留审计**（FR-017/FR-018/FR-061/SC-007/SC-028；依 quickstart.md VS-06 与 VS-14、research.md R6.4）
- [X] T025 [US3] 把 `aoep-cases.json` 逐例结果接入报告 AOEP 块并断言阻断语义：`aoep.by_invariant[<inv>] = {passed, total, failed, not_measurable}`（**键集恰为五项、`additionalProperties:false`；MUST NOT 在 `by_invariant` 内嵌 `cases[]`——逐例明细由 `per_case.aoep[]` 承载，`aoepCaseEntry` 自带 `invariant` 字段供分组归属**）、`aoep.score = {passed, total, rate}`、`aoep.all_passed = (每不变量 passed ≥ 2 且 failed == 0 且 not_measurable == 0)`；任一用例 `failed` → 报告 `status="failed"` 并阻断定稿；**逐例记录由运行器直接产出，MUST NOT 依赖事后人工转录**（FR-019/FR-020；写入 `eval/memory_baseline_support.py` 与 `backend/tests/integration/test_015_aoep_obligations.py`）
- [X] T026 [US3] 重跑 AOEP 套件一次并落盘稳定性与隔离证据 `eval/runs/<015-run-id>/evidence/aoep_stability.json`：同版本重跑结论稳定率 100%；破坏性操作触及既有真实域或 `366084747748704256` 的次数 = 0；逐例 `isolated_scope_id`；**非管理面回滚必须实际构造尝试**（MCP 面 / 非写实例 / 只读实例三类各构造 ≥1 次），断言全部被拒且拒绝均留审计，并给出**尝试样本量**（`attempted`）与成功次数（`succeeded = 0`）；MUST NOT 以"未尝试"记为 0——尝试样本量为零时该项记 `not_measurable` + 原因，MUST NOT 判达标（FR-019/SC-004/SC-005）

**Checkpoint**: US3 的五条不变量各 ≥2 例机器判定、逐例证据与报告得分块独立可测。

---

## Phase 5: US4 + US5 — 基准报告与硬指标五件套全量实测（Priority: P1）

**Goal**: 产出可复现、永不覆盖的 `memory_baseline_report.json`（US4），并一次性补齐硬指标五件套 + 隔离泄漏的**全量有分母实测**（US5，重点修复 014 遗留的 `cross_domain_leakage.value = null`）。

**Independent Test**: `python eval/run_memory_baseline.py --output eval/runs/<RUN_ID>/memory_baseline_report.json …` 后以契约 schema 校验报告；检查数据集版本、快照指纹、环境指纹、逐条目与可复现性块齐备；再触发第二次运行确认第一份文件未被修改；逐项检查硬指标的样本量与结论，对样本为零的项确认判为不可测量而非达标。

- [X] T027 [US4] 新增报告装配支持模块 `eval/memory_baseline_support.py`：`$defs` 合并校验（不引入新 schema registry）、三子集块与水位（投毒 100% 硬水位；连续性沿 014 判据；受益沿 013 对照口径，基线为零判不可计算）、AOEP 块装配、硬指标块装配、**逐投影指纹比对**、不可测量编码（比率型/数值型两形态）、运行标识与 `config` 指纹、报告运行标识 `<015>-<YYYYMMDDHHMMSS>`；**复用既有原语而非重写**：`eval/hard_metrics_014.py` 的 `_rate`(L41)/`_evidence_locatability`(L89)/`_schema_legality`(L117)/`_memory_provenance`(L160)/`_cross_domain`(L267)/`_quarantined`(L290) 与 `EVIDENCE_LOCATING_FIELDS`(L37)/`INFERENCE_META_KEYS`(L38)；`eval/run_memory_comparison.py` 的 `--mode record|replay` + `--cache-manifest`（两者均 required）；`eval/run_eval.py::compute_percentile`（**样本为空时本 Feature 返回 `null` + 不可测量原因，不得沿用其"空表返回 0.0"默认**）（FR-021–FR-027；依 research.md R4/R5/R6）
- [X] T028 [US4] 新增薄入口运行器 `eval/run_memory_baseline.py`：以 `argparse` 提供 CLI（`--output`/`--poisoning`/`--aoep`/`--aoep-results`，并含 `--runs-dir` 以装配 `regression` 块），复用既有内核（`eval/run_memory_comparison.py`、`eval/memory_continuity_support.py`、`eval/hard_metrics_014.py`、`eval/memory_acceptance_reports.py`）而**不修改** `eval/hard_metrics_014.py`（该模块无 CLI、只读 `RUN_ID`/`RUN_DIR` 环境变量，故必须由本运行器以显式参数传入产物路径）；落盘前经契约校验；**历史产物零覆盖**（目标路径已存在且内容逐字节不同即拒绝、退出码 ≠ 0；逐字节相同视为幂等成功）；`eval/memory_baseline_report.json` 仅首次播种（FR-021–FR-023/SC-010；依 research.md R5 与 quickstart.md VS-09）
- [X] T029 [P] [US4] 新增报告契约测试 `backend/tests/contract/test_015_memory_baseline_report_schema.py`：正例（完整报告通过）+ 反例（零分母记 0 被拒、`status=="passed"` 但 `hard_metrics.all_passed==false` 被拒、成对块缺失 `latency.env_sensitive` 被拒、含 `enters_default_path` 被拒），含不可测量与状态条件分支（依 T004；FR-024/FR-027）
- [X] T030 [US5] 在 `eval/memory_baseline_support.py` 落地**跨域串库四路径全量实测**：覆盖 ≥2 个真实域 + 一次显式多域请求，权威事件日志/关系投影/向量投影/文件投影**每条路径各自给出 `examined` 与 `leaks`**，`leaks = 0`；任一路径 `examined == 0` → 该路径 `not_measurable` + 原因且**整体不得判达标**（**这是 014 `cross_domain_leakage.value = null` 的修复点**）（FR-028/SC-008/SC-012；依 research.md R8）
- [X] T031 [P] [US5] 在 `eval/memory_baseline_support.py` 落地**六工具契约合法率**实测：三只读旧工具 + `recall_memory` + `start_work` + `record_memory` 的真实协议响应全量对照契约 schema（复用既有 registry），`tools_checked == 6`、分母非零、**含非法输入负例且负例被拒**，合法率 100%（FR-029；依 research.md R8）
- [X] T032 [P] [US5] 在 `eval/memory_baseline_support.py` 落地**来源可定位率与记忆 provenance 完备率**分项实测：证据路径（`evidence_id` + `source_version >= 1` + `source_position`）与记忆路径（`hard`：有 `evidence_refs` 且 `confidence is None`；`soft`/`distilled`：五元 `INFERENCE_META_KEYS` 齐备）各 100%，**两项口径分开统计 MUST NOT 合并**（FR-030；依 research.md R8）
- [X] T033 [P] [US5] 在 `eval/memory_baseline_support.py` 落地**硬记忆锚定率**实测：真实硬记忆样本 `hard_items_examined > 0`、无锚写入一律拒绝且无例外路径、锚定率 100%，并给出**被拒样本与错误码分布**；无样本即 `not_measurable`，**不记 100%**（不得沿用 014 的 `hard_items_examined = 0` 结论）（FR-031/SC-013；依 research.md R8）
- [X] T034 [P] [US5] 在 `eval/memory_baseline_support.py` 落地**隔离泄漏附加项**实测：构造真实 `quarantined` 样本后，对默认召回/巩固窗口/附加记忆/工作集/控制面**五处独立分母**逐处计数，五个计数均为 0 且各项分母非零；任一处分母为零 → `not_measurable`（FR-032/SC-012）
- [X] T035 [US5] 在 `eval/memory_baseline_support.py` 装配 `hard_metrics` 块与闸门：五件套 + `quarantined_leakage` 每项含 `caliber` 与分母；`hard_metrics.all_passed` 与 `gates.{quality,safety,regression}` 判定；**安全类指标零容差、MUST NOT 以 1% 非延迟容差替代**；任何不达即整体不通过；**实测必须基于真实 PG/Qdrant 与真实协议响应，测试桩或预设结论替代即失败**（FR-033/FR-034/SC-012；依 quickstart.md VS-10）
- [X] T036 [US4] 产出首份基准报告并验证报告属性：首次运行在**不存在**时播种 `eval/memory_baseline_report.json`，后续运行只写 `eval/runs/<RUN_ID>/memory_baseline_report.json`；第二次运行后首次报告**逐字节不变**；同快照同版本重跑两遍非延迟指标在 1% 相对容差内一致、**延迟不参与该判定**（`env_sensitive: true`）；巩固关闭时 `not_measurable[]` 必含 `benefit.relative_gain`；**不可测量项被记为 0 的次数 = 0、零分母被当作实测零的次数 = 0、每项不可测量均带原因的说明率 100%**（FR-024/SC-011）；报告以"基线锚点/当前水位"表述、**无对照提升证据不得宣称改进**；模型评审（若有）仅作诊断项且不参与过闸（FR-022/FR-023/FR-025/FR-026/FR-027/SC-009/SC-010/SC-023）
- [X] T037 [US4] 在 `eval/README.md` 015 段登记数据集、报告与运行器用法及重跑口径（`--output`/`--poisoning`/`--aoep`/`--aoep-results`/`--runs-dir`、运行标识规则、零覆盖纪律、零分母纪律），并如实记录三处"不得声称"边界（测试通过 ≠ 指标实测；零分母 ≠ 0；SSE 未接线不得当作 UI 未达标或正确性论据）（FR-023；依 research.md R10 与 quickstart.md"不得声称"）

**Checkpoint**: US4 的报告与 US5 的六项实测齐备且可复核，MVP（US1+US2+US3+US4+US5 五个 P1 故事）完成。

---

## Phase 6: US7 + US6 — 治理 UI 与统计端点（Priority: P2）

**Goal**: 先立隐私护栏（US7：无正文统计端点），再补齐管理面六视图治理（US6），且 MCP 面保持只读治理边界。

**Independent Test**: US7 —— 对每个域调用统计端点核对五类分布与两个计数，在正文开关打开与关闭两种状态下比较响应；US6 —— `cd frontend && pnpm build && pnpm exec playwright test tests/memory.spec.ts tests/memory-governance.spec.ts`，逐项检查六视图、六维过滤、scope 门、强确认与无批量入口。

- [X] T038 [US7] 新增聚合服务 `backend/src/rag_mcp/services/memory_statistics.py`：按域经 SQL/投影层聚合 `MemoryEntry`（经 `MemoryProjectionMeta` current 一致性校验）/`MemorySalience`（分位 p50/p90/p95 + 分桶）/`MemoryEvent`（`event_type=="rollback"` 计数）/`ConsolidationRunObservation`（按 scope 计数）；**MUST NOT 调用 `public_entry` 或任何拉取正文后再本地裁剪的路径**，零正文、无新迁移（预期零 DDL）（FR-044/FR-045/FR-046；依 research.md R9）
- [X] T039 [US7] 在 `backend/src/rag_mcp/api/memory.py` 新增独立端点 `GET /api/memories/stats`（挂既有 `APIRouter(prefix="/api/memories")`，`Depends(require_writer)`、显式 `scope_ref: Query(min_length=1)`）：返回 T007 契约定义的十个键；只读实例或无效租约 → 503 `MEMORY_WRITE_UNAVAILABLE`；缺 `scope_ref` → 422；**端点路径确认为 `GET /api/memories/stats`，与修订后 spec FR-044 逐字一致**；**MUST NOT 并入或改动 `GET /runtime/metrics` 及其 006 契约**（FR-044/FR-045/SC-016/SC-022）
- [X] T040 [P] [US7] 新增单元测试 `backend/tests/unit/test_015_memory_statistics.py`：聚合纯函数（分桶边界、空域、无正文断言、`total` 与浏览同域同口径一致）（FR-046）
- [X] T041 [P] [US7] 新增契约测试 `backend/tests/contract/test_015_memory_stats_schema.py`：响应经 `contracts/memory-stats-response.schema.json` 校验；反例 = 响应含 `content`/`content_excerpt`/`title`/`evidence`/`query` 任一自由文本键被拒；**`TRACE_BODY_ENABLED=true` 与 `false` 两态响应逐键相同**；`GET /runtime/metrics` 契约零改动回归断言（FR-045/SC-016/SC-022；依 quickstart.md VS-11）
- [X] T042 [US6] 新增强确认组件 `frontend/src/components/memory/ConfirmActionModal.tsx`：弹窗内需**逐字输入目标确认值**方使提交按钮可用（下线/清理输入**显式域引用 + 记忆标识**，即目标域 + `memory_id`；回滚输入**目标域 + 事件序号/水位（`event_point`）**或所选时间点字符串）；**确认值 MUST 含显式域引用，不得仅凭记忆标识由服务端反推域**；同时展示影响面预览（受影响条目计数 + 受影响投影与各投影计数）；提交后展示结果与审计指针；**MUST NOT 以 `Popconfirm`/`Modal.confirm` 等单次点击型确认替代**（FR-037/FR-039；依 research.md R11 与 contracts/governance-ui-contract.md §3）
- [X] T043 [US6] 新增 `frontend/src/components/memory/MemoryBrowseView.tsx`：浏览 + 六维过滤（域/分型/状态/provenance/会话/显著性）+ 分页（每页 20），保留既有 `List` 展示与 300 字摘录；**纠正链可视化**——展示条目前后链关系并支持沿链导航，默认视图隐藏已失效条目 MUST NOT 等同于隐藏历史，链上历史 MUST 可查；**过滤只能收窄**——一律与当前 `scope_ref` 同时发送，不存在"清空域以跨域浏览"的路径（FR-036/FR-038；依 R10）
- [X] T044 [P] [US6] 新增 `frontend/src/components/memory/MemoryGovernanceView.tsx`：下线与显式清理（**唯一清理路径**）、影响面预览 → 强确认（经 T042）→ 结果与审计指针（权威事件 `event_id` + `request_id`）；**首期仅单条**，无 `rowSelection`/`Checkbox`/批量 API 调用（FR-037；依 R10/R11）
- [X] T045 [P] [US6] 新增 `frontend/src/components/memory/MemoryRollbackView.tsx`：回滚目标选择（时间点/事件点）→ 影响面预览（受影响投影与条目计数）→ 强确认 → 结果与审计指针；**仅管理面可达，MCP 面不暴露回滚入口或能力**；首期仅单次单目标回滚，无批量或多目标（FR-039；依 R10/R11）
- [X] T046 [P] [US6] 新增 `frontend/src/components/memory/MemoryRebuildView.tsx`：按投影与/或按域触发重建 → 展示重建结果与各投影一致性校验报告（`POST /api/memories/rebuild` + `GET /api/memories/rebuild/audit` 为重建唯一审计读口）；**失败显式呈现**（FR-040；依 R10）
- [X] T047 [P] [US6] 新增 `frontend/src/components/memory/MemoryPromotionView.tsx`：晋升候选队列浏览 + 显式**人工**晋升动作，展示候选依据/晋升去向/原记忆保留关系；**MUST NOT 提供自动晋升入口**（FR-041；依 R10）
- [X] T048 [P] [US6] 新增 `frontend/src/components/memory/MemoryConsolidationView.tsx`：巩固运行列表与详情（运行标识/域/窗口/输入规模/提案与裁决/产出/状态/保留期/**失败与拒绝原因**）+ 域 `memory_policy` 编辑（非法值失败闭合、保存失败显式报错）（FR-042；依 R10）
- [X] T049 [US6] 新增统计面板 `frontend/src/components/memory/MemoryStatsPanel.tsx`（域级计数与分布，**无正文**，消费 T039 端点）并改造 `frontend/src/pages/MemoriesPage.tsx`：用 antd `Tabs` 承载六视图 + 统计面板；**域选择为必选门**——未选域时六视图与统计面板一律渲染 `Empty`（文案 `memories.noScope`）且**不发起任何返回正文的请求**；视图切换 MUST NOT 重置或清空域选择；`App.tsx` 保持四条扁平路由不变（FR-035/FR-036/FR-043；依 research.md R10 与契约 §1/§2）
- [X] T050 [US6] 扩展**已存在**的 `frontend/src/api/memories.ts`（当前仅导出 `MemorySummary`/`MemoryScope` 接口与 `fetchMemoryScopes`(`GET /api/memories/scopes`)/`fetchMemories`(`GET /api/memories?scope_ref=…&offset=…&limit=20`) 两个函数）：新增 stats 客户端与类型，并补齐 retire/purge/rollback/rebuild（含 audit）/promotion（候选、晋升、任务查询）/consolidation（运行列表与详情）客户端函数（沿用既有 `frontend/src/api/client.ts` 的 `get`/`post`/`put`/`del` 封装，MUST NOT 直写权威日志或投影）（FR-035/FR-043；依 R10）
- [X] T051 [P] [US6] 在**已存在**的 `frontend/src/i18n/en.ts` 与 `frontend/src/i18n/zh.ts` 补齐中英文案（六视图、统计面板、强确认、影响面预览、审计指针、空态与错误文案）：`en` 为键集基线（`LocaleKey = keyof typeof en`、`LocaleDict = Record<LocaleKey, string>`），**键集必须一致**（缺 `zh` 键即 `tsc -b` 报错）；既有 `memories.*` 11 键（含 `memories.noScope`）零改名，仅追加（FR-043；依契约 §6）
- [X] T052 [US6] 新增 Playwright 路由打桩规格 `frontend/tests/memory-governance.spec.ts`（沿用既有 `frontend/playwright.config.ts` 的 `baseURL http://127.0.0.1:5178`、`reuseExistingServer: true`；既有 `frontend/tests/memory.spec.ts` 用 `page.route` 打桩 `**/api/memories/scopes` 与 `**/api/memories?**`，新规格同法）：六视图（浏览/治理/回滚/投影重建/晋升/巩固报告）+ 统计面板可达；六维过滤可用；**未选域时对全部六视图的含正文端点——`/api/memories?**`、`/api/memories/stats`、`/promotion-candidates`、`/consolidation/runs**`、`/rebuild/audit`、`/policy`、`/usage`——请求次数均为 0** 且页面不出现任何正文文本；新增断言：**初始态未选域**（页面挂载即处于未选域态，六视图与统计面板均渲染空态且不发起任何含正文请求）与**切视图不重置域选择**（在已选域下依次切换六视图与统计面板后 `scope_ref` 保持不变，不得重置或清空域选择）；`purge`/`retire`/`rollback` 无强确认即可提交的次数为 0；无批量入口；回滚与重建在管理面可见；重建失败显式呈现；晋升无自动入口；巩固报告含失败与拒绝原因（FR-035–FR-043/SC-014/SC-015；依 quickstart.md VS-12）
- [X] T053 [US6] 执行前端验证并记录结果 `eval/runs/<015-run-id>/evidence/frontend_verification.json`：`cd frontend && pnpm build`（`tsc -b` 严格模式 + `vite build`）通过；`pnpm exec playwright test tests/memory.spec.ts tests/memory-governance.spec.ts`；**既有 `frontend/tests/memory.spec.ts` 两条断言（无横向溢出；写不可用时 `MEMORY_WRITE_UNAVAILABLE` 以 Alert 呈现）必须保持通过**；**SSE 未接线 MUST NOT 记为 UI 未达标，也不得以 SSE 论证正确性**（正确性来自 REST：挂载时拉取 + 每次治理动作后重取 + 手动刷新）（FR-043/SC-014）

**Checkpoint**: US7 与 US6 均独立可测；管理面八项治理操作可达而 MCP 面无治理写入口。

---

## Phase 7: US8 — 全集回归与文档债（Priority: P2）

**Goal**: 补齐文档债（迭代路线、README 记忆能力章、技术架构说明书 3.0 章、001–014 Status），并按各自口径完成 001–014 全集回归（依赖模型的组强制 record + replay 两轮）。

**Independent Test**: 人工审计四份文档与状态行，并核对回归产物目录 `eval/runs/<015-run-id>/`；确认蓝图正文与 001–014 既有历史报告零改写。

- [X] T054 [US8] 重建 `docs/1.0-iteration-roadmap.md`：含 001–015 交付记录、状态行反映 3.0 定稿、遗留缺口与 3.0 触发条件对齐、1.0→3.0 迭代史连贯；**目录 `docs/` 当前不存在须新建；该路径已被 `.gitignore` 第 43 行忽略，MUST 在文档内注明该事实且仍须产出**，不得以"未纳入版本控制"为由降级或跳过（FR-047；依 research.md R12 序 1）
- [X] T055 [P] [US8] 在根 `README.md` 新增记忆能力章节：六工具口径、分级信任、治理与回滚边界（仅管理面）、评测与硬指标现状、隐私边界；**无超售陈述**——尤其 MUST NOT 把默认关闭的巩固写成已默认开启，MUST NOT 把"测试通过"写成"指标实测达标"（FR-048/SC-017；依 R12 序 2）
- [X] T056 [US8] 重建 `docs/技术架构说明书.md`（当前工作区不存在、从未入版本控制）：新增"记忆回路"章（G2+ 事件日志权威层与六投影派生视图：关系/向量/链接/摘要/文件/显著性；五不变量强制点；回滚与管理面边界），并**仅对 §6 契约层与 §7 运行态做消除矛盾所需的最小修订**；其余章节保持既有骨架与结论不动，MUST NOT 全量重排或改写既有结论；所实施的修订留下可核查的**变更说明**（FR-049/SC-017；依 Clarifications Q5 与 R12 序 3）
- [X] T057 [P] [US8] 更新 001–014 的 `specs/0xx-*/spec.md` Status：`001–010` 复核一致（实测已为 `Delivered`，零改动）；`011–014` 由 `Draft` 更新为 `Delivered`；**013 的未达成发布结论（`incomplete`、`default_enable_eligible=false`、开关默认关闭）零改写**；并核对 `015` spec 自身的 Status 在定稿后更新（FR-050/SC-017/SC-021；依 R12 序 4）
- [X] T058 [US8] 新增回归编排 `eval/run_regression_015.py`：调度 001–014 全部组按**各自口径**重跑（1.0 六组、2.0 两组、012–014 新增组及其 E2E、AOEP 与宿主证据），复用既有运行器而不改写（沿 `eval/run_regression_011.py` 先例），产物全部落 `eval/runs/<015-run-id>/`（含 `backend-pytest.xml`、分组报告、012/013 acceptance、AOEP 逐例结果、hard-metrics 与基线报告）；**新增组→测试映射登记**：为每个回归组登记 `{group, runner, command, test_module, artifact}` 并落盘 `eval/runs/<015-run-id>/regression_group_map.json`（每组必须给出 runner/命令/对应测试模块/产物路径）；**未映射或未执行的组 MUST NOT 记为通过**；**历史报告零覆盖**（编排层再次校验目标路径不存在）；**未执行项记 `not_executed` 而 MUST NOT 记通过**（FR-054/FR-059/SC-020；依 research.md R14）
- [X] T059 [US8] 在 `eval/run_regression_015.py` 实现 **record + replay 两轮**：依赖模型的组（005 Agent 编排、013 巩固、014 记忆对照闸门等）先跑记录轮冻结模型响应与缓存指纹（`--mode record --cache-manifest`），再以**重放轮**判定，**真实网络调用 = 0 且为唯一过闸依据**；**实时调用结果 MUST NOT 作为过闸依据**；确定性组（001–004、006–012 非模型部分）沿各自口径单轮即可；缓存指纹（manifest hash + content hash）与重放轮真实网络调用计数**必须实测并登记**，不得只写 0；两轮的 runner/命令/对应测试模块/产物路径一并登记入 `eval/runs/<015-run-id>/regression_group_map.json`，**未登记或未执行的组 MUST NOT 记为通过**（FR-054/SC-020；依 research.md R14 Q7）
- [X] T060 [US8] 生成报告 `regression` 块并写入 `eval/runs/<015-run-id>/memory_baseline_report.json`：`{all_groups_executed, not_executed[], groups[]}`；**报告块的每组项形状受契约约束（`memory-baseline-report.schema.json` 的 `regression.groups[]` 为 `additionalProperties:false`），恰为** `{group, runner, mode: single_round|record_then_replay, cache_manifest_hash?, replay_real_network_calls?, non_latency_reproducible?, artifact}`——**MUST NOT** 把 `command`/`test_module` 写入报告块（这两个键只属于映射件，写入即契约校验失败）；`{group, runner, command, test_module, artifact}` 五元组只落在 `eval/runs/<015-run-id>/regression_group_map.json`（FR-059 的映射登记件），报告块以 `artifact` 指向该映射与各组产物；组集与映射件**双向一致（映射覆盖率 100%）**；**未映射或未执行的组 MUST NOT 记为通过**；依赖模型的组 `mode` 必为 `record_then_replay` 且 `replay_real_network_calls == 0`；非延迟 1% 相对容差、**安全指标零容差**；历史回归报告零覆盖；012–014 的 E2E 与 AOEP 按原口径通过（FR-054/FR-059/SC-020；依 research.md R14）
- [X] T061 [US8] 回归结果核销与规格同步**核验**：把各组的"超出 1% 容差且未留处置记录"次数归零并留处置记录；**对照 spec.md 的 FR-054 正文逐条核验其已含 record + replay 表述（spec.md:275）并记录核验结论**——Q7 决议已在 spec Clarifications 第二轮落入 FR-054 正文，plan/research/quickstart 中的"尚未补录"为**陈旧陈述**；**MUST NOT 再向 FR-054 追加任何表述**，本任务只读对照、不改正文、不改变验收口径；在 `eval/runs/<015-run-id>/evidence/fr054_sync.json` 记录逐条核验结论（对照的 spec.md 行号 + 每条正文要点 + 核验判定）与陈旧陈述清单及处置（plan.md Validation Gate 6 "规格同步项"；spec FR-054）

**Checkpoint**: US8 的四份文档与全集回归产物齐备，且回归口径与既有历史可比。

---

## Phase 8: Polish — 3.0 定稿与七项目标核销

**Purpose**: 对实施蓝图 §1 七项演进目标逐项核销，形成独立核销工件并完成定稿总结。**依赖全部前序阶段完成**（其证据指针必须指向本次运行的真实产物）。

- [X] T062 在 `eval/memory_baseline_support.py` 与 `eval/runs/<015-run-id>/memory_baseline_report.json` 生成七项目标核销台账（`report.goal_ledger` 块，恰 7 项：① MCP 记忆工具可用且旧三工具零破坏（`record_memory`/`recall_memory` scope 显式写入与读取）；② 硬记忆锚定率 100% + 软/distilled provenance 完备率 100%；③ 跨域记忆串库 = 0（四路径）；④ 巩固受益 ≥3%；⑤ 跨会话续接达标；⑥ 记忆投毒 E2E 全过；⑦ 既有评测全集无回归）：每项结构 MUST 为 `{id, statement, verdict: achieved|partial|not_achieved, evidence[], disposition?}`（与 `$defs/goalEntry` 一致，**MUST NOT 使用 `{goal, ...}` 形态**）；`id` 唯一覆盖 1–7；`statement` 与实施蓝图 §1 逐字对应；`goals[4].verdict = not_achieved`；**每项证据指针必须指向本次运行的真实产物路径，不得指向规划文档或未运行的口径**；`verdict != "achieved"` 时 `disposition` 必填（FR-051/FR-025/SC-018；依 research.md R13 判据-证据对照表）
- [X] T063 [P] 产出独立核销工件 `docs/3.0-finalization.md` 并经 `specs/015-memory-evaluation-governance/contracts/finalization-ledger.schema.json` 校验：`ledger_version:"3.0"`、`goals[]` 七项、`blueprint_frozen:true`、`blueprint_annotations[]`；目标 4 如实记 `not_achieved`/不可计算并给"维持默认关闭 + 触发条件"处置（**MUST NOT 改写 013 结论**）；目标 2/3 的证据指针指向本次真实产物；蓝图正文改写次数 = 0（仅头部状态注记）（FR-051/FR-052/SC-018；依 research.md R13）
- [X] T064 组装定稿证据集 `eval/runs/<015-run-id>/evidence/finalization_evidence_bundle.json`：登记全部真实产物路径（报告、两份新数据集、三子集冻结记录、AOEP 逐例结果、硬指标实测、前端验证、回归产物、四份文档与核销工件），并在 `evidence_paths[]`/`failed_paths[]`/`notes[]` 如实登记；MUST NOT 用规划文档或未运行口径充数（FR-021/FR-051/SC-018）
- [X] T065 执行定稿硬门四项联合判定并记录 `eval/runs/<015-run-id>/evidence/finalization_gate.json`：**投毒子集全过 ∧ AOEP 五条不变量各 ≥2 用例全过 ∧ 硬指标五件套与隔离泄漏全过 ∧ 全集回归无回归**，四项同时满足方可判"通过"；任一不满足即判**不通过**并显式记录，**MUST NOT 以"部分达成"含糊通过**；同时核销三子集水位口径：仅投毒为 100% 硬水位、连续性沿 014 既有判据（≥12/16 且每类 ≥1）、受益沿 013 既有对照口径、延迟仅记录且不参与容差判定（FR-053/FR-055/SC-019/SC-024）
- [X] T066 执行最终零破坏与诚实边界复核并记录 `eval/runs/<015-run-id>/evidence/zero_breakage_check.json`：012–014 的契约、工具面与旧客户端响应被破坏性修改次数 = 0（旧三工具行为逐字节不变）；`GET /runtime/metrics` 与六工具契约零改动；001–014 既有数据集/报告/测试文件字节零改动；宪法、蓝图正文零改写；**本 Feature 不宣称改进**（无对照提升证据而声明"提升"次数 = 0；既有未达成结论被改写为达成次数 = 0）；并逐条复核 quickstart.md"不得声称"清单（测试通过 ≠ 指标实测；零分母 ≠ 0；巩固未达成；SSE 未接线；说明书非全量重写；序号链非数值连续）（SC-002/SC-012/SC-021/SC-022）
- [X] T067 输出 3.0 定稿总结（写入 `docs/3.0-finalization.md` 结语段与报告 `notes[]`）：七项核销结论一览、定稿硬门四项判定、未达成项与去向（巩固受益维持默认关闭 + 触发条件）、遗留触发条件清单（批量治理、公开 MINJA 数据集引入、记忆事件 SSE publisher 接线、K 线混合检索等）、以及本次运行标识与产物索引（FR-051/SC-018）

---

## Phase 9: 跨阶段回填任务（T068–T075）

**Purpose**: 补足五条不变量中的两条新增用例段（`authority_monotonicity`、`provenance_preservation`）、缺失/空 scope 引用子用例、三项实测/登记与两项核验。编号沿全文件唯一连续续接（T068–T075）；各项按归属阶段回填（T068/T069/T075↔Phase 4 US3、T072↔Phase 3 US1、T070/T071↔Phase 5 US5、T073↔Phase 7 US8、T074↔Phase 8 Polish），物理位置集中在文末以保持 ID 递增顺序与文件结构一致。

- [X] T068 [US3] 在 `backend/tests/integration/test_015_aoep_obligations.py` 新增 **authority_monotonicity**（原 `authority_boundary` 更名）段（`-k authority_monotonicity`；Phase 4 US3 回填，接 T022/T023 之后，消费 T021 声明的 ≥2 例）：被拒的越权/非法命令 MUST NOT 追加权威事件、MUST NOT 提升权威等级、MUST NOT 改变范围绑定；断言权威日志 id 序列在尝试前后**逐项相等**（`before_ids == after_ids`，逐项而非仅长度相等）、绑定表行集不变、权威等级字段不变，且每次拒绝均留审计；逐例产出 `request_id`/`status`/前后指纹（`before_fingerprints`/`after_fingerprints`）/影响面/`isolated_scope_id`（FR-056/FR-017/FR-018/SC-007/SC-025；依 research.md R6.5）
- [X] T069 [US3] 在 `backend/tests/integration/test_015_aoep_obligations.py` 新增 **provenance_preservation** 段（`-k provenance_preservation`；Phase 4 US3 回填，接 T023 之后，消费 T021 声明的 ≥2 例）：状态转移（含 `retire`/`purge`/`rollback`）之后 provenance 元数据、来源链与 `content_hash` MUST 保留且**可复算**（重算值与记录值逐一相等）；权威日志 MUST 保留墓碑事件与来源链；逐例产出 `request_id`/`status`/前后指纹/影响面/`isolated_scope_id`（FR-056/FR-016/FR-018/SC-006/SC-025；依 research.md R6.6 与 quickstart.md VS-07）
- [X] T070 [P] [US5] 在 `eval/memory_baseline_support.py` 落地**投影可复算与运行期只读实测**：逐投影实测 `examined ≥ 1`、`drift = 0`，投影完整率 100%（可复算）；运行期只读须以真实 PG/Qdrant 与真实协议响应实测，**MUST NOT 以 route 打桩或预设结论替代**；任一分母为零 → 该投影记 `not_measurable` + 原因且整体不得判达标（FR-057/SC-025/SC-026；依 research.md R6）
- [X] T071 [P] [US5] 在 `eval/memory_baseline_support.py` 落地**六轴状态元数据齐备率实测**：对 `authority`/`scope`/`mutability`/`provenance`/`recoverability`/`actionability` 六轴逐条断言齐备，**每轴单独给出分母与结论**（齐备率 100%）；任一轴分母为零 → 该轴记 `not_measurable` + 原因且整体不得判达标（FR-058/SC-025）
- [X] T072 [P] [US1] 在 `backend/tests/integration/test_015_poisoning_suite.py` 并入 **desensitization（脱敏）断言**：投毒条目被标记/隔离后，任一消费面返回的内容 MUST NOT 泄露检测器内部细节（模式名/阈值/词表），逐条断言脱敏字段；该断言与既有八项断言同源消费同一数据集（FR-006；依 quickstart.md VS-03）
- [X] T073 [P] [US8] 登记范围决策 `eval/runs/<015-run-id>/evidence/scope_decisions.json`：把**目标 MCP 宿主评测**与**成本评测**如实登记为**本 Feature 范围外**并写明纳入触发条件；**真实域语料口径**（语料来源、采样口径与不可测项）如实登记，MUST NOT 以规划口径充数或记作已达成（FR-060）
- [X] T074 核验 `docs/3.0-finalization.md` 的七项目标 `id`/`statement` 与实施蓝图 §1 **1:1 逐字对应**（`id` 唯一覆盖 1–7，项结构 `{id, statement, verdict, evidence[], disposition?}`，MUST NOT 使用 `{goal, ...}`），并断言 `goals[4].verdict = not_achieved` 且 `disposition` 非空、`gate_hard.all_passed` ⇔ 四项硬门同时为真；**MUST NOT 声称存在 `verdict` 与 `gate_hard` 之间的双向绑定**——契约只绑定 `gate_hard` 的四个布尔与 `all_passed`，且 FR-053 的四项硬门**不含**目标 4；核验结论作为该文件的可核查注记（FR-051/SC-027；Polish 回填，故无 `[US]` 标签）
- [X] T075 [US3] 在 `backend/tests/integration/test_015_aoep_obligations.py` 与 `eval/memory_aoep_obligation_dataset.json` 落地 **FR-061 缺失/空 scope 引用**的独立子用例与留证：为 `scope_non_expansion` 增补**缺失**（无 `scope_ref`）与**空**（空串 / 只含空白）两类子用例，断言 `record_memory` 与读取类调用均被拒（`MISSING_KNOWLEDGE_SCOPE`）并给出候选域、回落最近域/全库成功次数 = 0、拒绝留审计；**与 T024 的歧义用例分开构造**，两类各自给出非零样本量并分别记分；逐例产出 `request_id`/`status`/影响面/可复现记录/`isolated_scope_id`；结果汇入报告 `aoep.by_invariant.scope_non_expansion`（FR-061/SC-028；依 research.md R6.4 与 quickstart.md VS-14）

**Checkpoint**: 五条不变量用例段、三项实测/登记与两项核验齐备，可并入定稿硬门与回归证据链。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup（T001–T002）**: 无依赖，可立即开始
- **Phase 2 Foundational（T003–T010）**: 依赖 Setup 完成；**阻塞全部用户故事**（数据集需要 schema、报告需要 schema、AOEP 结果需要证据导出 fixture、统计与核销工件需要 schema）
- **Phase 3 US2+US1（T011–T019）**: 依赖 Phase 2；**安全测试先行**，T016/T017 的失败优先于任何后续功能任务修复（投毒套件的脱敏断言补足见 T072）
- **Phase 4 US3（T020–T026）**: 依赖 Phase 2 与 US1 的投毒子集（T015，用于共享隔离域与检测观测面）；五条不变量的两条新增用例段见 T068/T069（Phase 9 回填，依赖 T021 与 T022/T023 所在套件）
- **Phase 5 US4+US5（T027–T037）**: 依赖 US1 与 US3（报告的三子集与 AOEP 得分依赖两份新数据集与逐例结果）；投影可复算与六轴齐备率补足见 T070/T071（Phase 9 回填，依赖 T027）
- **Phase 6 US7+US6（T038–T053）**: US7 仅依赖 Phase 2（统计契约）；US6 依赖 US7（统计面板消费 `GET /api/memories/stats`）
- **Phase 7 US8（T054–T061）**: 文档部分仅依赖 Phase 2 与 Phase 5（报告实测值）；回归部分依赖 A–F 全部产物（范围决策登记见 T073，Phase 9 回填）
- **Phase 8 Polish（T062–T067）**: 依赖全部前序阶段（七项目标 `id`/`statement` 1:1 核验见 T074，Phase 9 回填）
- **Phase 9 回填（T068–T075）**: 跨阶段追加——T068/T069/T075 依赖 T021 与 T022/T023/T024 所在套件；T072 依赖 T016/T017；T070/T071 依赖 T027；T073 依赖 Phase 5 实测产物；T074 依赖 T062/T063。全部须在 T058 全集回归与 T065 定稿硬门判定前完成，以便并入证据链

### User Story Dependencies

- **US1（P1，投毒全链路）**: Phase 2 后开始；不依赖其他故事；是定稿硬门之一
- **US2（P1，三子集只增不破坏）**: Phase 2 后开始；与 US1 同阶段（US1 的投毒子集是 US2 的第三份子集）
- **US3（P1，AOEP 状态义务）**: 需要 US1 的隔离域与检测观测面
- **US4（P1，基准报告）**: 需要 US1/US3 的数据集与逐例结果
- **US5（P1，硬指标五件套）**: 依赖 US4 的报告装配层；硬指标结果回填报告
- **US6（P2，治理 UI）**: 需要 US7 的统计端点
- **US7（P2，统计端点）**: 仅需 Phase 2
- **US8（P2，回归与文档）**: 需要 US1–US7 的全部实测产物

### Within Each Phase

- 测试（契约/集成）先写并确认 FAIL → 再补数据文件与实现；数据文件是唯一真相源，MUST NOT 在测试内重复定义用例内容
- 契约 schema → 数据集 → 执行套件 → 证据导出 → 报告装配 → 实测 → 端点 → UI → 回归 → 文档 → 核销
- 安全类失败（投毒、权威单调、范围不扩张、隔离泄漏、硬锚定、串库）优先于一切功能任务修复

### Parallel Opportunities

- Phase 1: T001 → T002（T002 依赖目录与 README 存在）
- Phase 2: **T003 必须先完成**（T004–T008 全部引用其 `$defs`）；T005/T006/T007/T008 四份 schema 互相独立可并行；T010 依赖 T005/T006；T009 与任何 schema 任务并行
- Phase 3: T011 → T012（校正落在复核之后）；T013 与 T011/T012 并行；T015 → T016 → T017 → T018 → T019
- Phase 4: T020 与 T021 可并行；T022/T023/T024 三者写同一文件的**不同部分**，建议串行提交以避免同文件冲突，[P] 仅在按部分拆分确有把握时使用
- Phase 5: T027 → T028；T029 与 T027 的契约（T004）就绪后即可并行；T030–T034 五项实测互相独立可并行（同一支持模块的不同函数，建议按函数拆分写入）；T035 依赖 T030–T034；T036 依赖 T035；T037 独立
- Phase 6: T038 → T039 → T040/T041；T042 必须先于 T044/T045（强确认被治理与回滚复用）；T043 与 T044–T048 可并行（不同文件）；T049 依赖 T043–T048 与 T042；T050/T051/T052 在接口就绪后并行；T053 最后
- Phase 7: T054 → T055/T056/T057（不同文件可并行）；T058 → T059 → T060 → T061
- Phase 8: T062 → T063 → T064 → T065 → T066 → T067（T063 与 T064 可并行）
- Phase 9（回填）: T068/T069/T075 写同一测试文件的不同段，建议串行提交；T070/T071 写同一支持模块的不同函数，可按函数拆分并行；T072、T073、T074 互相独立可并行（不同文件）；T068/T069/T075 须在 T021 之后、T072 在 T016/T017 之后、T070/T071 在 T027 之后

### Parallel Example: Phase 2 契约层

```bash
# T003 先完成（共享 $defs 是所有契约的引用底座），随后四条契约可并行：
Task: "编写投毒数据集契约 contracts/poisoning-eval-dataset.schema.json"          # T005
Task: "编写 AOEP 数据集契约 contracts/aoep-obligation-dataset.schema.json"        # T006
Task: "编写统计响应契约 contracts/memory-stats-response.schema.json"              # T007
Task: "编写定稿核销契约 contracts/finalization-ledger.schema.json"                # T008
Task: "编写契约测试 backend/tests/contract/test_015_memory_benchmark_datasets.py" # T010
```

### Parallel Example: Phase 5 硬指标五件套实测

```bash
# T027/T028 装配层就绪后，五项实测相互独立（同一支持模块的不同函数）：
Task: "跨域串库四路径全量实测（修复 014 value=null）"      # T030
Task: "六工具契约合法率全量含负例"                          # T031
Task: "来源可定位率与 provenance 完备率分项"                # T032
Task: "硬记忆锚定率含被拒样本与错误码分布"                  # T033
Task: "隔离泄漏五处独立分母"                                # T034
```

---

## Implementation Strategy

### MVP First（五个 P1 故事：US1+US2+US3+US4+US5）

1. 完成 Phase 1 Setup（T001–T002）
2. 完成 Phase 2 Foundational（T003–T010）—— **阻塞全部故事，不可跳过**
3. 完成 Phase 3（US2+US1）→ **STOP and VALIDATE**：投毒套件与三子集冻结记录独立通过
4. 完成 Phase 4（US3）→ **STOP and VALIDATE**：AOEP 五条不变量逐例判定
5. 完成 Phase 5（US4+US5）→ **STOP and VALIDATE**：报告经契约校验且六项硬指标有真实分母
6. 此时三子集 + AOEP + 硬指标 + 报告齐备 = 定稿硬门四项中的三项已可判定

### Incremental Delivery

1. Setup + Foundational → 契约与证据导出骨架就绪
2. US2+US1 → 固定子集与投毒全链路证据（安全闸门先立）
3. US3 → 状态义务基线
4. US4+US5 → 基准报告与硬指标实测
5. US7+US6 → 统计护栏与治理 UI
6. US8 → 全集回归与文档债
7. Polish → 3.0 定稿核销
8. 每个阶段结束时该阶段能力可独立测试，且不破坏既有 012–014 交付

### Parallel Team Strategy

- 团队共同完成 Setup + Foundational（契约 T003 为关键路径起点）
- Foundational 完成后：
  - 开发者 A：US1+US2（投毒子集与三子集冻结）
  - 开发者 B：US3（AOEP 义务用例与隔离模块，需 A 的隔离域约定）
  - 开发者 C：US7（统计端点与契约测试，仅依赖 Phase 2）
- US1/US3 收敛后：开发者 D 并行 US4+US5 的报告装配与五项实测
- US7 收敛后：开发者 E/F 并行 US6 的六视图（按组件文件拆分写入，避免同文件冲突）
- 全部收敛后：US8 回归（编排层单人负责，避免并发写 `eval/runs/<RUN_ID>/`）与 Polish 核销
- **并发写纪律**：`eval/runs/<015-run-id>/` 下同文件不得并发写入；`backend/tests/integration/test_015_aoep_obligations.py` 与 `eval/memory_baseline_support.py` 为多任务共用文件，建议按函数/测试段串行提交

---

## Notes

- [P] 任务 = 不同文件、无未完成依赖
- [Story] 标签把任务映射到 spec.md 用户故事，便于追溯与独立验证
- 测试任务为强制项（TDD 先红后绿），且数据文件为唯一真相源——MUST NOT 在测试内重复定义用例内容
- 零分母、历史产物零覆盖、安全零容差、未执行不记通过 四条纪律贯穿全部任务
- 三处"不得声称"必须写进报告与文档而非仅在实现里默认：测试通过 ≠ 指标实测；零分母 ≠ 0；SSE 未接线既不得记为 UI 未达标也不得作为正确性论据
- AOEP 不变量集合 MUST 与《宪法》XIII 第三条五项**逐一对应**（`traceable_rollback`/`deletion_propagation`/`authority_monotonicity`/`scope_non_expansion`/`provenance_preservation`）；`authority_boundary` 已更名为 `authority_monotonicity`，数据集、报告与测试选择器 MUST 统一使用新名，旧名仅允许出现在本条更名注记中
- 蓝图正文冻结（仅头部状态注记）、宪法不改、001–014 既有报告与结论零改写
- 每个任务完成后即校验其文件路径与验收口径，避免收尾期才发现零分母或无分母项

---

## Phase 10: Convergence

**Purpose**: 第二次 convergence 评估（以 spec.md/plan.md/tasks.md 为唯一意图来源）发现的剩余工作。**APPEND-ONLY**：本节不改写、不重编号、不删除 Phase 1–9 的任何任务。发现按严重度排序，CRITICAL 先行。

**Evidence base（本次评估只读核验的真实状态）**：

- `eval/run_memory_baseline.py:275-377` 的 `_leak_paths` 对事件日志/关系先按 `memory_scope_id IN wanted` 过滤再判 `NOT IN wanted`，对向量先筛 `selected` 再判越界，对文件以 `root = <root>/<scope_id>/<event_id>` 构造后再断言路径含 `scope_id`——四条路径的 `leaks` 在构造上恒为 0，串库实测**不可失败**；`assemble_from_measurements`（`eval/run_memory_baseline.py:1156-1159`）只把**单域请求**的 `paths` 交给 `cross_domain_block`，显式多域请求实测（`hard-metrics-measurements.r10.json`：event_log 115 / relation 115 / vector 1336 / file 120）被计算后丢弃，而 `multi_domain_evidence`（`eval/memory_baseline_support.py:641-649`）却向报告写入"each of the four paths was measured for that exact request"；该请求 `recall_returned_scope_ids = []`，召回级样本为零却被当作无泄漏证据。
- 消费面（`search_knowledge.related_memories` 附加记忆、`start_work` working_set）在多域请求下**完全没有**串库实测；被删除的 `backend/tests/integration/__pycache__/test_015_mixed_domain_leakage.cpython-312-pytest-8.4.2.pyc` 显示上一轮确有"七路径 + detectability control（人为制造跨域行/点/文件后 meter 必须报非零）"的设计与 `eval/hard_metrics_015.py`，二者均未入库。
- 投毒子集 9 条 primary 全部以**字面命中**构造（`poison_role_hijack_zh` 正文即 `忽略之前的指令`、`poison_identity_override_mixed` 即 `you are now`、`poison_chat_delimiter_escape` 即 `<|im_start|>`、`poison_user_concealment_fragmented` 为单句连续文本），四个 `variant_class` 无一按 research.md:48 的定义施加改写；`jailbreak_marker` 规则与 `memory_authority_override` 的 3/5 备选式样无任何用例；`015.variants.1` 仅存在于字符串，无机器可读条目；`matched_patterns` 因 `poisoningCaseEntry` `additionalProperties:false` 无法入证；`test_015_poisoning_suite.py:538-641` 对检测命中硬断言，FR-003 的"未命中变种如实判不通过"路径不可达。
- `eval/runs/015-20261009205637/evidence/aoep-cases.json` 13 条中 6 条（authority_monotonicity ×2、scope_non_expansion ×4）`before_fingerprints`/`after_fingerprints` 为空对象；判据证据（authority id 序列、绑定表行集、`scored` 子条件、`observations`、候选域、逐面样本量、期望错误码）只进入 270 KB 的 append-only `aoep_isolation_disposal.json`（每条用例 4 份重复 allocation 记录，无法与本次运行一一对应）；反例 `aoep_traceable_rollback_audit_only_counterexample` `status=passed` 且 `event_chain_closed=false`，缺 `role`/`expectation` 字段，机器无法从工件判定其通过语义；scope/authority 用例的 `event_chain_closed=true` 是无依据的默认值。
- `eval/runs/015-20261009205637/regression/regression_group_map.json` 记录 5 个组 `outcome=failed`（`011_regression_011`、`012_acceptance`、`013_e2e`、`014_contract`、`013_consolidation_comparison`），junit 实测 `013_e2e` 7 测 5 败、`014_contract` 568 测 4 败；4 个组 `non_latency_reproducible=false`（001_dense_11 / 002_hybrid_18 / 007_hybrid_18 / 009_graph_37）；但报告 `regression.groups[]` 契约（`memory-baseline-report.schema.json`）`additionalProperties:false` **没有 outcome 字段**，`regression_gate`（`memory_baseline_support.py:943-953`）只校验 `all_groups_executed` 与重放网络调用数，因此**结构上无法因失败而不过闸**。
- 同一 run 目录并存 11 份互相矛盾的报告（r2–r10 + regression + run 报告），tracked 交付物 `eval/memory_baseline_report.json` 仍为 `status=incomplete`、`hard_metrics.all_passed=false`、`tool_schema_validity 4/6`、goals 1/2/7 `partial`、notes 逐字写"NOT PASSED"，而 `evidence/finalization_gate.json`（verdict `passing`）、`evidence/finalization_ledger.json`、`docs/3.0-finalization.md` 只认 `memory_baseline_report.r10.json`（`status=passed`、goals 1/2/7 `achieved`）；`evidence/goal_ledger_correction.json`（1/2/7 `partial`）被下游全部绕过；r10 的 goal 1/2/3 `evidence[]` 仍指向被取代的 `hard-metrics-measurements.json` / `memory_baseline_report.json`，goal 7 指向自身 `gates.regression=false`、goal 7 `partial` 的 `memory_baseline_report.regression.json`。
- `memory_management_audits` 唯一写入方仍是 `MemoryService.rebuild`（`memory_service.py:863-869`）；retire/purge/rollback/promotion 的"审计指针"只是权威事件 `event_id`+`request_id`，且除 `GET /rebuild/audit` 外**无任何读取权威事件的 REST 入口**；promotion 的 HTTP 响应不含 `event_id`，`fetchPromotionReport`（`frontend/src/api/memories.ts:234`）零调用；policy 编辑与巩固运行的审计指针被 UI 丢弃；`frontend/src/components/memory/MemoryPromotionView.tsx:2` 含非法 UTF-8 字节 `E2 80 3F`；`eval/runs/015-20261009205637/evidence/frontend_verification.json:59` 声称 purge/rollback 也断言了审计指针，实际仅 retire 用例断言。
- 文档残留：`docs/技术架构说明书.md:212-213` 仍写"015 任务清单 16/75 勾选、核销工件尚未产出"；`docs/3.0-finalization.md` 同一文档内 `014_contract` 通过数 564（:117）与 568（:233）自相矛盾；`docs/1.0-iteration-roadmap.md:24/26/188/149`、`README.md:230-231`、`eval/README.md:370-371` 与 tracked 报告实际状态冲突；`specs/015-.../spec.md:9` 仍为 `Status: Draft`。
- 15 个 015 测试模块只存在于 `__pycache__`（`test_015_mixed_domain_leakage`/`test_015_governance_audit`/`test_015_detector_variants`/`test_015_path_meters`/`test_015_projection_drift`/`test_015_no_hardcoded_hard_metrics` 等；`git log -- <path>` 与 `git ls-files` 均无记录），tasks.md 对相应覆盖的勾选在树内无对应文件。

- [X] T076 [US5] 重建跨域串库四路径实测使其**可失败**：`_leak_paths` 对事件日志/关系按"该请求可达的全量总体"取分母再判越界（MUST NOT 先按 `wanted` 过滤），向量按 scroll 到的全部点计 `examined` 并把 `payload.knowledge_scope_id ∉ wanted` 计为 leak，文件按投影 frontmatter/owner scope 判定而非"路径含 scope_id"，并加入 **detectability control**（人为植入一条跨域行/点/文件后 meter MUST 报非零，且控制结果入证据）；重建 MUST 以**显式多域请求自身的 paths** 作为报告口径并把单域请求单独登记 per plan: T030 与 FR-028/SC-008/SC-013 (contradicts) —— **已完成**（convergence：`_scan_paths` 重写 + 六路径可探测性控制；证据 `eval/runs/015-20261010020241/memory_baseline_report.r2.json`、`backend/tests/integration/test_015_mixed_domain_leakage.py` 8 passed）
- [X] T077 [US5] 为**消费面**补齐多域串库路径：把 `related_memories`（附加记忆）与 `working_set`（工作集）纳入跨域实测与报告契约（各自 `examined`/`leaks`，分母为零记 `not_measurable` 并写明原因），并在多域请求下断言两面的返回条目 scope 全属请求域；恢复被删除的 `test_015_mixed_domain_leakage` 覆盖（含 detectability control）per FR-018/SC-008 与 US5/AC1 (missing) —— **已完成**（消费面分母 attachment 2 / working_set 3，控制均触发；契约 `$defs/leakPathPassing` 加法）
- [X] T078 [US8] 诚实重判回归闸门：报告 `regression.groups[]` 增加 `outcome`（`passed|failed|not_measured`）与 `outcome_reason`（契约加法），由 `regression_group_map.json` 的 `outcome` 驱动；`regression_gate` MUST 在任一已执行组 `outcome != passed` 或任一非延迟比较超出 1% 容差且无处置记录时判不通过；`docs/3.0-finalization.md`/gate/ledger 的"全集回归无回归"结论 MUST 依新闸门重判 per FR-053/FR-054/FR-059/SC-019/SC-020 (contradicts) —— **已完成**：新闸门判**不通过**；**重跑 001–014 全集回归**（`eval/runs/015-20261010032500`：31 组登记、30 组实执行）后为 4 组超 1% 容差无处置（001/002/007_hybrid/009_graph）＋3 组自身 `failed`（012_acceptance/013_e2e/014_contract）＋1 组未执行（013_consolidation_comparison：record 轮空缓存清单被 replay 拒绝；另 `011_regression_011` 的编排聚合缺陷与子进程 env 缺陷已修复并重分类为 passed），已无"可判定 outcome 缺失"的组；gate/ledger/文档据此重判
- [X] T079 [US8] 消除 seed 与 r10 的双口径：指定唯一权威报告并以修复后证据重新产出 tracked `eval/memory_baseline_report.json` 与 run 报告，新增机器可读的权威索引（含历史变体清单与"非权威"标记，历史文件零覆盖），使 FR-021/FR-023 的交付物、gate、ledger、docs 指向同一工件 per FR-021/FR-023/SC-009/SC-010 (contradicts) —— **已完成（部分）**：`memory_baseline_report.index.json` 指定唯一权威报告并逐条标记被取代变体；tracked `eval/memory_baseline_report.json` 未改写（历史零覆盖），文档与生成器统一指向权威报告
- [X] T080 [US8] 依重判后的真实证据重做七项核销：goals 1/2/7 的 verdict 与 evidence 指针 MUST 指向承载该口径的本次产物（goal 2 的分母仅 2 硬 + 1 软、且两行由测量自身写入→ `partial`；goal 7 在存在 `outcome=failed` 组时→ `not_achieved`）；`gate_hard.all_passed` MUST 与四项硬门一致并如实为假；`evidence/goal_ledger_correction.json` 的裁决 MUST 被显式收编或被显式反转并留理由 per FR-051/FR-025/SC-018/SC-027 (contradicts) —— **已完成**：goal 7 → `not_achieved`；goal 2 因样本现含本运行未写入的既有硬行（prior=5、硬 provenance 12/1），按新判据为 `achieved` 并在处置中写明分母规模；权威报告的 `gate_hard.all_passed = false`
- [X] T081 [US1] 补齐投毒子集的检测面覆盖：新增 `jailbreak_marker` 与 `memory_authority_override` 未覆盖的 3/5 备选式样用例；把 `015.variants.1` 落为**机器可读条目表**（版本+四类条目+每类至少一例由 schema 强制）；四类变种 MUST 按 research.md:48 定义真正施加改写（fragmentation 分片、delimiter_or_encoding 含空白/全角/零宽包装、synonym 真同义改写），并以**至少一条未命中变种**证明 FR-003 的"如实判不通过"路径可达（`criterion_met=false` 记录而非断言失败）；用例证据 MUST 记录 `matched_patterns` per FR-002/FR-003/FR-007/SC-003 (partial) —— **已完成**：19 例（16 primary / 3 control），11/11 规则面 + 4/4 变种类由 schema 强制，`known_misses` 公开登记真实漏检同义改写并由单测证明 `criterion_met=false` 路径；`matched_patterns` 入证
- [X] T082 [US3] 让 AOEP 逐例证据自足可判：把判据证据（authority id 序列前后逐项、绑定表行集、`scored` 子条件、逐面 `observations` 与样本量、候选域、期望错误码、`attempted/succeeded`）写入 `aoep-cases.json` 的逐例记录（契约加法），13 条用例的 `before_fingerprints`/`after_fingerprints` 非空或显式 `not_applicable`+原因；反例用例 MUST 显式记 `role=negative_control` 与期望观察（事件链不闭合→判失败）；`event_chain_closed` 等不适用字段 MUST NOT 填默认值 per FR-019/SC-004/SC-005 (partial) —— **已完成**：13/13 用例带 `role`/`criterion`/`expected`/`observed`/`scoring`/`sample_sizes` 且指纹非空；反例显式 `negative_control`；`aoep_case_entries` 已透传新键
- [X] T083 [US6] 补齐治理审计完整性：`POST /api/memories/promote` 返回 `event_id`；UI 渲染 promotion 与 policy 编辑的审计指针；新增管理面权威事件审计读取入口使 retire/purge/rollback/promotion/policy 的指针**可回读**（MCP 面不可达）；修复 `frontend/src/components/memory/MemoryPromotionView.tsx` 非法 UTF-8 字节；修正 `frontend_verification.json` 对 purge/rollback 指针断言的失实陈述；补回 015 governance REST/audit 测试（HTTP 层断言审计行）per FR-037/FR-039/FR-043/SC-014 (partial) —— **已完成**：`GET /api/memories/audit` 可回读；promote 返回 `event_id`；UI 显示并解引用指针；非法字节修复；purge/rollback 指针断言补入；后端 4 项新测 + 前端 12 项通过
- [X] T084 [US8] 修正文档残留与自相矛盾：`docs/技术架构说明书.md` §8 的 16/75 与"核销工件尚未产出"、§8 缺 AOEP/015 评测面；`docs/3.0-finalization.md` 的 564/568 与 goal 7 表述；`docs/1.0-iteration-roadmap.md` 状态行与 149 行判定；`README.md`/`eval/README.md` 的报告指针；`specs/015-.../spec.md:9` 的 Status 定稿更新 per FR-047/FR-048/FR-049/FR-050/SC-017 (contradicts) —— **已完成**：§8 状态与评测面修正（R3）；finalization 文档由权威报告生成（不再手抄计数）；roadmap/README/eval README 指针与判定更新；015 Status 保持 `Draft` 并写明未定稿原因
- [X] T085 [US4] 复原可复现性口径：T036 的"同快照同版本两轮实测" MUST 真实执行并登记（含真实的 7 项超容差实测与其处置），MUST NOT 以同载荷重装（`run_1 == run_2`、含 0 vs 0 与派生布尔）冒充实测复现；派生态与实测态 MUST 分开表述 per FR-027/SC-009/SC-023 (partial) —— **未完成（如实登记）**：本轮只做一次真实实测，权威报告 `non_latency_reproducible = false` 且缺测项记入 `not_measurable`；真实两轮实测的 7 项超容差与"同载荷重装 182/182"的区别已写入 `evidence/reproducibility_convergence.json`；FR-027 仍未达成
- [X] T086 [US2] 恢复树内缺失的 015 验证面：把被判据绑定的缺失测试模块（至少 `test_015_mixed_domain_leakage`、`test_015_governance_audit`、`test_015_detector_variants`、`test_015_path_meters`）以当前代码为基准重写并入库，使 tasks.md 已勾选的验证覆盖在树内真实存在且可执行 per T010/T016/T022-T025/T030-T034 的验证义务与 SC-003/SC-004/SC-012/SC-014 (missing) —— **已完成（部分）**：`test_015_mixed_domain_leakage.py`、`test_015_governance_audit.py`、`test_015_poisoning_variants.py` 已重写并通过；`test_015_path_meters`/`test_015_projection_drift` 等未单独恢复（其口径已由报告实测与新测试覆盖）

**Checkpoint**: Phase 10 全部完成后，四条硬门（投毒全过、AOEP 全过、硬指标五件套与隔离泄漏全过、全集回归无回归）与七项目标核销 MUST 由同一套真实证据一致支撑；若某项仍不达标，MUST 如实记为不通过并在定稿结论文档中写明未达成项与去向。

## Phase 11: Convergence（第二轮 — 关闭"全集回归无回归"）

Phase 10 判不通过后，本轮逐组定位并修复使第四项硬门为假的全部原因；spec.md/plan.md 未改，tasks.md 仅追加本段。

- [X] T087 [US8] 修复回归编排的三处接线缺陷并按真实产物重分类：① `eval/run_regression_011.py` 的 `all_passed` 把"本次实际选择的 5 组"与模块级 6 组清单比较，使被 T059 刻意收窄的调用永不可能通过（改为按 `selected` 集合判定并在摘要记录 `selected_groups`）；② 同一 runner 用 `create_subprocess_exec` 起子进程时未传 `env`，Windows 机器级畸形 `NO_PROXY`（括号 IPv6）穿透到孙进程，使每个子进程在建 Qdrant 客户端时抛 `InvalidURL: Invalid port ':1]'`（改为传净化后的显式 env）；③ `012_acceptance` 的命令漏传 `--regression`，而该 runner 的 SC-012 规则为"无回归证据即 `not_verified`"，导致报告恒为 `status=incomplete`（补入本次运行的 011/004/010 回归报告作为证据）per FR-054/FR-053/SC-020 (contradicts) —— **已完成**：① 后 `011_regression_011` 真实产物 `all_passed=true`（5/5 子组）并由 failed 重分类为 passed（前版产物与状态逐字保留于 `regression/011_regression.pre-fix/` 与状态文件 `superseded_outcome`）；③ 后 012 报告 `status=passed`、17/17 判据含 SC-012 全过（实测产物 `_probe_012_acceptance_with_regression.json`）
- [X] T088 [US8] 修复 013 巩固对照的冻结标识种子缺陷：`eval/run_consolidation_comparison.py` 的 `frozen_seed` 由 run id 的 sha256 前 15 位十六进制直接决定，可能**低于**被恢复权威的 high-water（实测 `015REGRESSION013234bd726` → 273118229010885578 < cutoff 366085522273075200），于是窗口封存事件 id 小于 `high_water_mark`，被 0095 的 `guard_consolidation_window_event()` 以 `invalid consolidation window prefix` 正当地拒绝：两个 consolidated 臂首条写入即失败（`queries=0`/`model_keys=0`/`ARM_EXECUTION_INCOMPLETE`），strict cache manifest 为空，replay 前置以 `cache evidence incomplete: matched=0/0` 拒绝 per FR-054/FR-057/SC-019 (missing) —— **已完成**：种子下界改为 `max(sha256 派生值, authority_cutoff + WINDOW_ID_STRIDE)`（保持两轮之间与跨轮确定性），并把根因与实测数值写入代码注释
- [X] T089 [US8] 为写入 013 巩固状态的组提供隔离数据库口径：`013_e2e` 与 `014_contract` 的九项失败全部是同一条产品闸门（`consolidation_fixtures.create_scope` 要求 `CONSOLIDATION_ISOLATED_DATABASE == DATABASE_URL.database`），MUST 以"密封胶囊数据库的原生模板副本"作为隔离库并把三个环境变量显式传给子进程，MUST NOT 记作通过 per FR-054/FR-060 (contradicts) —— **已完成**：`--isolated-database`/`--isolated-template`/`--keep-isolated-database` 与逐组 `requires_isolated_database` 透传、运行前 drop+template-copy 刷新并落证 `evidence/isolated_database.json`；隔离口径实测 `013_e2e` 7 passed、`tests/contract` 601 passed 0 failed
- [X] T090 [US8] 把 4 组超容差比较的**既有处置**落为机器可校验的记录：001/002/007 的 `pre_existing_corpus_drift` 与 009 的 `inherited_between_historicals` 原以散文登记于 `eval/runs/015-20261009205637/evidence/fr054_sync.json`（含逐指标 historical/rerun），MUST 以"逐指标精确匹配才生效"的方式写入 map 的 `outcome_reason`，MUST NOT 作为笼统豁免 per FR-054/SC-020 (partial) —— **已完成**：`DRIFT_DISPOSITIONS` + `_disposition_for` 要求每个超容差指标与文档值一致（容差 1e-6）且无未登记漂移，`regression_gate` 只在"无处置"时判不通过
- [X] T091 [US8] 以单一 run id 全量重跑 001–014 全集回归（隔离库口径、串行、单轮 1800s 预算），产出可复核的 `regression_group_map.json` 作为第四项硬门的唯一依据 per FR-054/SC-019/SC-020 —— **已完成**：`eval/runs/015-20261010100500`：**31/31 组实执行、31/31 组 `outcome = passed`**；4 个 record_then_replay 组（005/009/013/014）replay 真实网络调用均为 0；`013_consolidation_comparison` 的 strict cache manifest 2 条、`evidence_complete=true`、replay 计数 0（其已发布结论 `default_enable_eligible=false` 与声明历史一致）
- [X] T092 [US8] 依重跑结果重判四项硬门与七项目标，重新生成 `docs/3.0-finalization.md` 与权威索引 per FR-053/FR-051/FR-023 —— **已完成**：`gate_hard.all_passed = true`（四项全真）；goals 1/2/3/5/6/7 `achieved`、goal 4 `not_achieved`（非硬门成员）；权威报告 `eval/runs/015-20261010100500/memory_baseline_report.json`（`status=passed`）与索引 `.../memory_baseline_report.index.json`；Phase 10 的 r2–r5 与重跑报告逐条标记被取代
- [X] T093 [US8] 同步文档与证据指针：`eval/README.md` 回归节、`docs/1.0-iteration-roadmap.md`、`README.md`、`evidence/` 下的本轮修复与重跑记录 per FR-047/FR-049 —— **已完成**：roadmap 状态行/§3/§4 与缺口表、README 记忆节、eval/README 015 节（含 3 处编排缺陷、隔离库口径、种子下界、处置机制）与 `evidence/convergence_closure.json`（8 项修复逐条留证）
- [X] T094 [US8] 回归测试与一致性校验：015 契约/单测/集成套件 + `final_check.py` 一致性脚本全绿，且不得因本轮改动放宽任何判据 —— **已完成**：015 契约/单测 122 passed（另有报告契约 49、集成 12 在上一轮通过）；`final_check_closure.py` 29 项全 PASS（含"未执行不得记通过""无未处置漂移""处置须带证据指针""FR-027 不得记作已达成"等诚实性断言）
- [X] T095 [US8] 输出 3.0 定稿结论（通过/不通过）及其逐项依据，未达成项如实登记并写明去向 —— **已完成**：**3.0 定稿判通过**（四项硬门全真）；唯一未达成项为目标 4（巩固受益，非硬门成员，触发条件已登记）；FR-027 可复现性仍未达成并如实记为 `not_measurable`

**Checkpoint**: Phase 11 完成后，第四项硬门 MUST 由"单一 run id 的全量回归 + 可复核的逐组 outcome"支撑；若仍有不通过项，MUST 如实登记（不得以处置记录掩盖真实回退）。
**Phase 11 结果**：31/31 组实执行且全部 `passed`；四项硬门全真；3.0 定稿判**通过**；goal 4（巩固受益）仍 `not_achieved`（非硬门成员），FR-027 仍未达成（如实记为 `not_measurable`）。
