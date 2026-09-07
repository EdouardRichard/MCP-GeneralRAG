---
description: "Task list for 011 generic-domain-evaluation implementation"
---

# Tasks: 通用域评测与多域验收（两验证域语料/评测集/域基线 + 多域验收 + 前端中英文切换）

**Input**: Design documents from /specs/011-generic-domain-evaluation/

**Prerequisites**: plan.md、spec.md（含 2026-09-07 澄清 Q1=A/Q2=B + 前端 i18n 追加）、research.md（R0–R13）、data-model.md、contracts/（domain-baseline-common / generic-domain-baseline-report / legal-domain-baseline-report / domain-eval-dataset / frontend-locale-contract）、quickstart.md（VS-01~VS-10）

**Organization**: 按实现阶段组织（6 个阶段），每阶段映射 spec User Story 与 FR/SC；任务内标注 [US*] 维持故事可追溯。TDD 纪律仅适用于运行器扩展/种子/契约测试部分（迭代提示词 11.7）；语料与评测集为数据资产创作（人工审核前置）。

**Path Conventions**: 后端 backend/src/rag_mcp/、测试 backend/tests/、评测 eval/、契约 specs/011-generic-domain-evaluation/contracts/、前端 frontend/src/、文档 docs/ 与根 README.md。

---

## Phase 1: 语料与域档案（US1：personal 档案落地 + legal 格式扩展 + 两域语料入库）

**Goal**: 落地 personal 内置域档案（第四内置，FR-001）、legal 档案 supported_formats 扩展（FR-003，与受益闸口解耦），建设两域语料（个人域构造虚构四格式 / 法律域公开法规标准合同 Word/PDF + markdown 交叉引用，FR-002/FR-004），经既有链路幂等入库并发布（FR-002/FR-004/SC-010）。本阶段为后续评测集/基线/验收的物理基础。

**Independent Test**: python -m pytest backend/tests/unit/test_domain_profile_seed.py backend/tests/integration/test_011_corpus_ingest.py -v（VS-01/VS-02）；语料入库后 list_knowledge_domains 列出 personal/generic/legal scope 与能力摘要。

- [x] T001 [P] [US1] 在 backend/src/rag_mcp/config/domain_profiles.py 的 BUILTIN_DOMAIN_PROFILES 新增 personal 内置档案（第四内置）：domain_key="personal"、supported_formats=通用格式族全集（与 generic 一致）、graph_relations={}、prompt_overrides=NEUTRAL_PLANNER_PROMPT、default_capabilities={"retrieval_modes":["dense","hybrid"],"has_graph":false}、is_builtin=True（FR-001，research R8）；se-project/generic 条目逐字段不动
- [x] T002 [US1] 在 backend/src/rag_mcp/config/domain_profiles.py 扩展 legal 内置档案 supported_formats 为 ["markdown","word","pdf"]（FR-003）；graph_relations 维持现状（受益闸口结果在 Phase 2 T016 后视情况启用，格式扩展与闸口解耦）
- [x] T003 [P] [US1] 扩展 backend/tests/unit/test_domain_profile_seed.py：personal 档案断言（格式族/空词表/is_builtin）+ legal 格式扩展断言（含 chunk_type_extensions 保持 None，R13）+ se-project/generic 等价不回归（VS-01）
- [ ] T004 [P] [US1] 建设个人/团队通用知识库域语料 eval/corpora/generic/（FR-002，research R3）：markdown/txt/html/csv 四格式各 ≥2 个知识源、合计 5–15 文件，构造虚构样例（个人笔记/会议记录/清单/数据表/网页存档），含中文内容；语料结构形态完整（markdown 标题层级、txt 空行分段、html 标题、csv 表头）
- [ ] T005 [P] [US1] 扩充法律合规域语料 eval/corpora/legal/（FR-004，research R3）：Word 合同（"第X条"标题样式）+ PDF 法规（数字编号 X.Y 标题，因 PDF 解析器仅认数字编号）+ markdown 交叉引用语料（内部锚点/跨文件相对链接/中文条文引用三类形态）；采用公开法规/标准合同模板（Q2=B，版权与逐字转载边界处置见 spec Edge Cases）
- [ ] T006 [US1] 新建 eval/ingest_domain_corpora.py（FR-002/FR-004/SC-010，research R7）：幂等 scope 创建（public+personal、public+generic、public+legal）+ 语料入库 + 版本发布，走既有链路（域档案格式校验 + FormatHandler 注册表 + 转换层/原生切片 + 脱敏）；复用 run_cross_reference_comparison.py 的 scope 创建先例；失败 fail-loud
- [ ] T007 [US1] 新建 backend/tests/integration/test_011_corpus_ingest.py（VS-02）：四格式（markdown/txt/html/csv）与 word/pdf 语料入库后切片/检索/定位断言（csv=sheet: 前缀、html/markdown=标题路径、txt=段落、word="第X条"标题路径、pdf=page:N §编号路径）；域档案格式校验拒绝格式族外格式

**Checkpoint**: 两域语料入库发布、personal/legal 域档案就绪；语料可重放（幂等）。评测集与基线可在此基础上建设。

---

## Phase 2: 评测集与运行器（US2 + US3：固定评测集 + 域基线运行器 + 两份基线报告 + 交叉引用受益再验证）

**Goal**: 建设两域固定评测集（各 ≥10 条，LLM 生成 + 人工审核，FR-005~FR-007），新增域基线薄入口运行器（FR-008）并产出两份域基线报告（FR-009/FR-010），执行法律域交叉引用受益再验证并按 Q1=A 双分支处置 legal 词表（FR-011）。

**Independent Test**: python -m pytest backend/tests/contract/test_domain_eval_dataset_schema.py backend/tests/contract/test_domain_baseline_report_schema.py -v（VS-03/VS-04 契约面）+ python eval/run_domain_baseline.py（两份报告过 schema、非延迟 1% 容差可重复）+ python eval/run_legal_benefit.py（受益闸口结论与词表处置一致）。

- [ ] T008 [P] [US2] 新建 eval/generic_domain_eval_dataset.json（FR-005/FR-006，research R2）：≥10 条，条目含 query / domain_scope（slug）/ expected_heading / format / language / _meta.review；覆盖 markdown/txt/html/csv 每格式 ≥2 条（≥1 自然语言 + ≥1 结构定位）+ ≥2 条中文；查询由 LLM 生成并经人工审核（review_status="reviewed" + review_notes + grounded_source）
- [ ] T009 [P] [US2] 新建 eval/legal_domain_eval_dataset.json（FR-005/FR-006）：≥10 条，条文结构检索子集 ≥4（Word/PDF 承载，含中文条款查询）+ 交叉引用受益子集 ≥6（is_structural_benefit=true，含 ≥1 中文条文引用查询）+ ≥2 中文；人工审核记录随库
- [ ] T010 [US2] 新建 backend/tests/contract/test_domain_eval_dataset_schema.py（VS-03）：两份数据集通过 contracts/domain-eval-dataset.schema.json 校验 + 覆盖断言（条数/格式每类 ≥2/中文 ≥2/条文结构 ≥4/受益 ≥6）+ 既有数据集零改动断言（eval_dataset.json / agentic_eval_dataset.json / cross_reference_eval_dataset.json 逐字节不变，SC-001）
- [ ] T011 [P] [US3] 新建 backend/tests/contract/test_domain_baseline_report_schema.py（VS-04 契约面）：两份报告契约 schema（generic-domain-baseline-report.schema.json / legal-domain-baseline-report.schema.json）的校验断言——dense/hybrid 指标块、P50/P95、逐查询条目（domain_scope + expected_heading）、硬指标块、可重复性块；legal 报告额外 cross_reference_benefit 块；无 enters_default_path 字段（FR-010）
- [ ] T012 [US3] 新建 eval/run_domain_baseline.py（FR-008/FR-009，research R1）：薄入口导入 run_eval.py / run_comparison.py 内核（run_single_eval / compute_metrics / check_reproducibility）；解析 domain_scope（slug/数字 ID → scope 集合）；expected_heading 结构锚点运行时解析；同会话 dense + hybrid 双臂；产出域基线报告并经契约 schema 校验；可重复性检查（非延迟 1% 容差）
- [ ] T013 [US3] 运行个人/团队域基线并产出 eval/generic_domain_baseline_report.json（SC-002）：验证报告过 generic-domain-baseline-report.schema.json、dense/hybrid 双路径指标 + P50/P95 齐全、逐查询明细完整、硬指标实测、非延迟 1% 容差可重复；报告为历史产物（后续勿覆盖）
- [ ] T014 [US3] 运行法律域基线并产出 eval/legal_domain_baseline_report.json（SC-002）：同 T013，经 legal-domain-baseline-report.schema.json 校验
- [ ] T015 [US3] 新建 eval/run_legal_benefit.py（FR-011，research R9）：同会话混合检索基线臂 vs 图增强臂（混合 + 交叉引用扩展）对照，受益子集 = legal_domain_eval_dataset.json 的 is_structural_benefit 条目（≥6）；图边提取沿用 010 runner 的注册表显式触发机制（不改变 cross_reference 提取器行为）；闸口 = MRR 与 nDCG 均值相对提升 ≥3% + Recall 非降 + 硬指标全过；零可测图边记录"无可测量受益"（宪法 III）；产出 vocabulary_disposition 记录
- [ ] T016 [US3] 按受益闸口结果处置 legal 档案 graph_relations（FR-011，Q1=A 双分支，research R9）：达标 → domain_profiles.py legal 行 graph_relations={"references":["out","in"],"referenced_by":["out","in"]} + default_capabilities.has_graph=true + retrieval_modes 增 graph_enhanced；未达标 → 维持空词表现状；同步更新 test_domain_profile_seed.py 断言与 data-model.md §2.2 两分支记录

**Checkpoint**: 两域评测集与两份域基线报告在库、交叉引用受益再验证有可审计结论；legal 词表状态与闸口结果一致。

---

## Phase 3: 多域端到端验收（US4：混合域检索 + 发现流程 + 硬指标三件套 + 双形态冒烟）

**Goal**: 在混合域环境（public+personal、public+generic、public+legal、project+se-project）执行 MCP 双工具 domain_scope 三形态寻址闭环 + list_knowledge_domains 发现流程，全量实测硬指标三件套（串库=0/Schema 100%/定位 100%，FR-014/FR-023~FR-025），writer/reader 双形态冒烟（FR-015）。

**Independent Test**: python -m pytest backend/tests/integration/test_011_multidomain_acceptance.py backend/tests/integration/test_deepseek_harness_dual_form.py backend/tests/e2e/test_deepseek_harness_e2e.py -v（VS-06，DeepSeek Harness 必过目标宿主）；验收记录 eval/multi_domain_acceptance_report.json 落盘。

- [ ] T017 [US4] 新建 backend/tests/integration/test_011_multidomain_acceptance.py（FR-012/FR-013，SC-004）：混合域环境四语义轴 scope；list_knowledge_domains 发现 → 以返回 slug/ID 构造 domain_scope（数字 ID / slug / type:name 三形态）→ search_knowledge 检索 → get_evidence 展开的完整闭环断言；发现条目仅含域元数据无知识内容
- [ ] T018 [US4] 在 backend/tests/integration/test_011_multidomain_acceptance.py 增硬指标三件套实测断言（FR-014/FR-023~FR-025，SC-003）：跨域串库=0（单域引用不返回他域证据 + 多域引用各证据归属正确）、三工具 Schema 合法率=100%、来源可定位率=100%（含 Word 标题路径与 PDF page:N §编号前缀证据）
- [ ] T019 [US4] 在 backend/tests/integration/test_011_multidomain_acceptance.py 增四类引用场景断言（FR-022）：仅 project_scope（旧码不变）、仅 domain_scope、双参数混用（并集去重）、两参数皆空（拒绝不回退全库）
- [ ] T020 [US4] 扩展 backend/tests/integration/test_deepseek_harness_dual_form.py（FR-015/SC-006）：混合域验收集（三域）在 writer/reader 双实例形态下各跑一轮，单侧非回归判定（006 口径，复用房规既有 dual-form 测试）
- [ ] T021 [US4] 扩展 backend/tests/e2e/test_deepseek_harness_e2e.py（FR-015 目标宿主测试）：MCP 双工具以 domain_scope 三形态寻址 + list_knowledge_domains 跨三域闭环，DeepSeek Harness 必过参考客户端；并持久化多域验收记录 eval/multi_domain_acceptance_report.json（FR-014）：场景清单 + 三件套逐条实测记录 + 参考客户端结论（ChatGPT/Claude 记录兼容状态）

**Checkpoint**: 多域端到端闭环走通、硬指标三件套全量实测通过、验收记录落盘。

---

## Phase 4: 全集回归与文档债（US5 + US6 文档债：001–006 重跑 + roadmap/README/spec Status）

**Goal**: 001–006 全部报告按各自口径重跑确认无回归（FR-016/FR-017），并清理三处文档债（roadmap 至 2.0 状态 / README 纠正 / 001–006 及 007–010 spec Status 更新，FR-018~FR-020）。

**Independent Test**: python eval/run_regression_011.py（六组重跑 1% 容差、历史报告零覆盖）；人工审计 roadmap/README/spec Status 与交付事实一致。

- [ ] T022 [US5] 新建 eval/run_regression_011.py（FR-016，research R11）：六组重跑编排——001 Dense 基线 11 条（run_eval.py --mode dense 前 11 条）、002 混合对照 18 条（run_comparison.py --limit 18）、003 格式集 37 条 + 逐格式对照、004 图集 37 条（run_graph_comparison.py --limit 37）、005 agentic 组合全集（run_agentic_comparison.py）、006 双形态冒烟（run_instance_form_smoke.py）；产物落 011 前缀新文件（不覆盖历史报告）；非延迟指标 1% 相对容差比对
- [ ] T023 [US5] 运行 001–006 全集回归并确认无回归（SC-005）：产物 eval/011_*_regression_report.json，非延迟指标（Recall@K/MRR/nDCG）与历史报告 1% 容差内一致；历史报告文件零改动
- [ ] T024 [US5] 复跑 010 交叉引用对照口径确认提取器行为不变（FR-017）：按 eval/run_cross_reference_comparison.py 的机制复跑（其经注册表显式触发提取器、不依赖 legal 档案词表）并对照 eval/cross_reference_comparison_report.json 历史口径，确认 legal 档案扩展与新语料未造成口径漂移
- [ ] T025 [US6] 更新 docs/1.0-iteration-roadmap.md 至 2.0 收官状态（FR-018）：补齐 003–011 交付记录（含 2.0 视角迭代史）、状态行更新（现"002 Delivered"过时）、Remaining Gaps 与 2.0 触发条件（蓝图 §9）对齐
- [ ] T026 [P] [US6] 更新 eval/README.md（FR-018）：登记两域数据集（generic/legal_domain_eval_dataset.json）、两份域基线报告、域基线/受益/回归运行器用法与 001–006 重跑口径（沿用既有登记纪律）
- [ ] T027 [P] [US6] 纠正根 README.md 过时陈述（FR-019）："仅包含规划与规格工件，尚无业务实现代码"、"当前仓库处于规格设计阶段"、"首个纵向 Feature：001"等更新为如实反映已交付系统（MCP 检索四路径、多知识域、转换层摄入、评测体系），不超售
- [ ] T028 [P] [US6] 更新 specs/001-* 至 specs/010-* 各 spec.md 的 Status 行（FR-020）：001–006 必须更新为已交付状态、007–010 同步核对（若仍为 Draft 一并更新），措辞全库统一；仅改 Status 行与文档性陈述、规格正文语义零改动

**Checkpoint**: 全集回归无回归、文档债核销（roadmap/README/spec Status 与事实一致）。

---

## Phase 5: 前端中英文切换（US7：语言资源层 + 切换器 + 持久化，仅前端）

**Goal**: 前端管理界面加入中英文切换（FR-027~FR-031）：自建语言资源层（零依赖）+ antd locale 接线 + localStorage 持久化；范围严格限于前端自产文案，后端错误消息与领域数据原样展示（FR-029/FR-031）。

**Independent Test**: cd frontend && pnpm dev 后人工逐页面审计（VS-08）：三页面 + App 头部前端自产文案随切换、中文态英文残留=0 / 英文态中文残留=0、后端消息与领域数据原样、刷新后偏好保留、默认英文。

- [ ] T029 [P] [US7] 新建 frontend/src/i18n/en.ts（FR-027，research R10）：将现状硬编码英文文案迁移为类型化字典（projects./projectDetail./domainProfiles./common. 分组，约 65 键）
- [ ] T030 [P] [US7] 新建 frontend/src/i18n/zh.ts（FR-027）：中文资源（与 en.ts 同键、同类型 Record）
- [ ] T031 [US7] 新建 frontend/src/i18n/index.ts（FR-027）：LocaleProvider（React Context）+ useLocale() + t(key) hook + localStorage 持久化（键 rag-mcp.locale，损坏/缺失回落英文）
- [ ] T032 [US7] 修改 frontend/src/App.tsx（FR-028）：ConfigProvider 挂 antd locale（zhCN / enUS 随语言）+ Header 增语言切换器
- [ ] T033 [P] [US7] 修改 frontend/src/pages/ProjectsPage.tsx（FR-029/FR-030）：硬编码字符串 → t(key)；后端 err.message 与领域数据（项目名/slug/domain_key/状态码）原样展示不翻译
- [ ] T034 [P] [US7] 修改 frontend/src/pages/ProjectDetailPage.tsx（FR-029/FR-030）：同 T033
- [ ] T035 [P] [US7] 修改 frontend/src/pages/DomainProfilesPage.tsx（FR-029/FR-030）：同 T033
- [ ] T036 [US7] 执行前端零残留与持久化验收（SC-011，VS-08；覆盖 frontend/src/ 三页面 + App.tsx）：中文态英文残留=0 / 英文态中文残留=0（含 antd 分页/日期/确认组件）、后端错误消息与领域数据字节级不变、刷新后偏好保留

**Checkpoint**: 前端三页面双语完整覆盖、零残留、后端与 MCP 契约零改动。

---

## Phase 6: 2.0 定稿与收尾（US6 核销 + Polish）

**Goal**: 产出 2.0 演进目标逐项核销记录（FR-021），执行 quickstart 全场景验证与 pytest 全集回归收尾（宪法工作流项 6：spec/plan/tasks 一致性分析通过后方可视为收敛）。

**Independent Test**: 人工审计 docs/2.0-finalization.md（§1.3 五项目标逐项达成判定 + 证据指针）；python -m pytest backend/tests/ 全绿；quickstart VS-01~VS-10 全部通过。

- [ ] T037 [US6] 新建 docs/2.0-finalization.md（FR-021，SC-009）：对蓝图 §1.3 五项演进目标逐项核销——目标 1（domain_scope 检索）→007 domain_scope + 多域验收报告；目标 2（新格式边际成本 ≤2 文件）→008 注册表记录；目标 3（首批格式可上传/切片/检索/定位）→008 格式集验收 + 011 个人域语料覆盖；目标 4（两验证域 ≥10 条 + 基线 + 1.0 评测集无回归）→011 两域评测集与基线 + 001–006 回归；目标 5（混合域硬指标三件套）→011 多域验收报告；未达成项显式标注原因与去向（蓝图正文冻结不改）
- [ ] T038 [Polish] 运行 quickstart.md VS-01~VS-10 全场景验证（含域基线/受益/多域验收/回归/前端 i18n/文档债/核销），确认全部通过
- [ ] T039 [Polish] 运行 python -m pytest backend/tests/ 全集（001–010 既有测试零回归）+ 前端 pnpm build 成功，确认 011 变更未破坏既有交付

**Checkpoint**: 2.0 定稿核销记录落盘、quickstart 与 pytest 全集通过、Feature 收敛。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1（语料与域档案）**: 无前置，可立即开始；为后续全部阶段的物理基础
- **Phase 2（评测集与运行器）**: 依赖 Phase 1（语料入库 + 域档案就绪）
- **Phase 3（多域端到端验收）**: 依赖 Phase 1（scope 已建）+ Phase 2（评测集/基线为硬指标测量参照）；可与 Phase 2 部分并行（scope 就绪即可跑闭环）
- **Phase 4（全集回归与文档债）**: 依赖 Phase 1–3 稳定（回归需系统稳定；文档债可提前并行于 Phase 2/3）
- **Phase 5（前端中英文切换）**: 仅依赖前端既存（不依赖 Phase 1–4），可与 Phase 2/3/4 并行
- **Phase 6（2.0 定稿与收尾）**: 依赖 Phase 1–5 全部完成

### User Story 依赖

- **US1（P1）**: 无依赖，先行（Foundational）
- **US2 + US3（P1）**: 依赖 US1
- **US4（P1）**: 依赖 US1（+ US2 评测集为测量参照）
- **US5（P2）**: 依赖 US1–US4
- **US6（P2，文档债+定稿）**: 文档债部分可并行；定稿核销依赖 US1–US5 + US7
- **US7（P2，前端 i18n）**: 独立，可与其他阶段并行

### Within Each Story

- 测试先行（TDD，运行器/种子/契约部分）：seed 测试 → 种子实现；数据集/报告 schema 测试 → 数据集/报告产物校验
- 语料与评测集为数据资产：人工审核前置（T004/T005 语料结构形态、T008/T009 查询审核记录）
- 运行器（T012/T015/T022）依赖其内核（run_eval/run_comparison/010 runner 导入复用）

### Parallel Opportunities

- Phase 1：T004（个人域语料）/ T005（法律域语料）可并行；T001/T003（种子+测试）与语料创作可并行
- Phase 2：T008（个人域数据集）/ T009（法律域数据集）/ T011（报告 schema 测试）可并行
- Phase 4：T026（eval README）/ T027（根 README）/ T028（spec Status）可并行
- Phase 5：T029（en.ts）/ T030（zh.ts）可并行；T033/T034/T035（三页面迁移）可并行
- 跨阶段：Phase 5（前端 i18n）全程可与 Phase 2/3/4 并行（不同文件、无依赖）

---

## Implementation Strategy

### MVP First（US1 先行）

1. 完成 Phase 1（语料与域档案）——两域语料入库、personal/legal 档案就绪
2. **STOP & VALIDATE**：python -m pytest backend/tests/unit/test_domain_profile_seed.py backend/tests/integration/test_011_corpus_ingest.py -v 通过；list_knowledge_domains 列出三域
3. 再进入 Phase 2（评测集 + 基线报告，本 Feature 核心交付）

### Incremental Delivery

1. Phase 1 → 两域语料可检索、档案可发现（地基）
2. Phase 2 → 两域评测集 + 两份域基线报告 + 受益再验证结论（核心锚点，SC-001/SC-002/SC-007）
3. Phase 3 → 多域闭环 + 硬指标三件套（SC-003/SC-004/SC-006）
4. Phase 4 → 全集回归 + 文档债（SC-005/SC-008）
5. Phase 5 → 前端双语（SC-011，可并行交付）
6. Phase 6 → 2.0 定稿核销（SC-009）+ 全量收尾

### Parallel Team Strategy

- 开发者 A：Phase 1 + Phase 2（语料/评测集/运行器/基线）
- 开发者 B：Phase 3 + Phase 4（多域验收/回归/文档债）
- 开发者 C：Phase 5（前端 i18n，独立并行）

---

## Notes

- [P] 任务 = 不同文件、无未完成任务依赖，可并行
- [Story] 标签映射任务到用户故事以维持可追溯（US1~US7）
- 每个用户故事可独立完成与验证；阶段间依赖见 Dependencies
- 语料与评测集为数据资产，须先经人工审核（T004/T005/T008/T009 含审核记录）
- 基线报告一经产出不得覆盖重写（T013/T014 为历史产物；后续重跑落新文件）
- 提交纪律：commit 前缀 "011 Txxx"（迭代提示词 11.7）；每任务或逻辑组后 commit
- 评测集一经入库不得破坏既有条目（T010 断言既有数据集零改动）
- 避免：模糊任务、同文件冲突、跨故事依赖破坏独立性
