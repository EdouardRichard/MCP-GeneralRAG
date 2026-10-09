# Implementation Plan: 记忆评测治理与 3.0 定稿

**Branch**: `015-memory-evaluation-governance`（setup_plan 逻辑 Feature 名；实际 Git 分支为 `main`，本次不创建分支） | **Date**: 2026-10-09 | **Spec**: [spec.md](spec.md)

**Feature Directory**: `specs/015-memory-evaluation-governance`

**Input**: 已澄清的 015 规格（Clarifications **两轮** Session 2026-10-09：第一轮 Q1–Q5，第二轮 Q6–Q8）+ 用户指定技术上下文（eval 运行器扩展、投毒与 AOEP 用例双形态、MemoryPage 六视图沿 ProjectDetailPage SSE 模式、统计端点决议落地、文档工件清单与写作顺序）+ 用户指定 research.md 必覆盖的五项内容。

**Approved Decisions（2026-10-09，用户批准，见 spec Clarifications 两轮 Session）**：① 投毒子集首期**纯合成构造**（既有检测器已知模式 + 冻结变种字典），公开 MINJA 数据集仅登记为触发条件；单条通过判据 = **写入被标记为高风险 且 落库状态为隔离态**（二者同时成立）；② **可溯** = 权威日志回滚事件存在 + 事件链闭合（前后水位/事件序号、序号链无缺口）+ 逐投影指纹比对 + 影响面计数一致；**全传播** = 关系/向量/链接/摘要/文件**五投影各自独立断言**且**各自分母非零**，零分母记不可测量；③ **仅投毒拦截率设 100% 硬水位**；连续性沿 014 既有判据（≥12/16 且每类 ≥1）；巩固受益沿 013 既有对照口径（基线为零判不可计算）；**延迟仅记录、不设门**；④ 统计端点为**独立端点**（不并入 `GET /runtime/metrics`、不改其契约）、仅写实例管理面、显式域参数；purge/回滚用**强确认**；首期**仅单条**，批量列为触发条件；⑤ 技术架构说明书**最小增量**（新增"记忆回路"章 + 仅 §6 契约层/§7 运行态最小修订）；⑥ **投毒子集构造期可迭代、达标后首次冻结**——仅在已冻结变种字典范围内迭代到每条 `primary` 用例既被标记又落库隔离态才写入 `first_frozen_at`；冻结后失败如实判定并阻止定稿，不得替换/删改/放宽，补救仅以追加新条目或另立 Feature；⑦ **全集回归中依赖模型的组（005 Agent 编排、013 巩固等）强制 record + replay 两轮**——记录轮冻结模型响应与缓存指纹，重放轮（真实网络调用 = 0）为唯一过闸依据，实时调用结果不得过闸，缓存指纹与重放网络调用计数随回归证据登记；⑧ **AOEP 用例以评测数据集 JSON（用例声明）+ 专用运行器承载**，破坏性操作（回滚/墓碑/清理）**只在每次运行新建的专用隔离域与隔离身份内执行**，逐例记录由运行器直接产出并汇入报告 AOEP 得分块，**不作用于既有真实域或既有固定评测集依赖的域**。**这八项为冻结决议，规划与实现不再作为待澄清项处理。**

## Summary

为 3.0 记忆回路建立**可复核、只增不破坏的固定评测基准**并完成治理与定稿：新建记忆投毒防护子集（≥5 条，纯合成、MINJA 式全链路断言）与 AOEP 状态义务用例（五条不变量各 ≥2 例，机器可判定判据）；复核冻结 014 多会话连续性（16 条）与 013 巩固受益（6 条）两份既有固定集；产出 `eval/memory_baseline_report.json`（三子集指标 + AOEP 义务得分 + 硬指标五件套实测 + 隔离泄漏 + P50/P95 延迟，沿 001/002/011 报告契约形态，历史产物不覆盖）；补齐硬指标五件套全量有分母实测（重点修复 014 遗留的 `cross_domain_leakage.value = null` 零分母）；以管理面六视图（浏览/治理/回滚/投影重建/晋升/巩固报告）补完治理 UI 并新增独立统计端点 `GET /api/memories/stats`；清理文档债（迭代路线至 3.0、根 README 记忆能力章、技术架构说明书 3.0 章、001–014 spec Status）并产出 3.0 定稿核销独立工件；执行 001–014 全集回归。

**双形态交付是本 Feature 的核心工程决策**：投毒与 AOEP 用例以 **eval 数据文件为唯一真相源**（冻结、只增、可被报告引用），以 **pytest 集成套件为执行器**（参数化消费同一数据文件，CI 可跑、逐用例可观测），避免"数据一份、测试一份"的双真相漂移。**AOEP 的破坏性操作在每次运行新建的专用隔离域与隔离身份内执行**（显式禁入 013/014 冻结集共用的 scope `366084747748704256`），逐例记录由运行器直接产出并汇入报告的 AOEP 义务得分块。**全集回归中依赖模型的组走 record + replay 两轮**，以重放轮（真实网络调用 = 0）为唯一过闸依据。

研究见 [research.md](research.md)，模型见 [data-model.md](data-model.md)，接口见 [contracts/README.md](contracts/README.md)，验收见 [quickstart.md](quickstart.md)。不重建 012–014 已交付能力（事件日志与六投影、写读管线、分级信任、注入检测接线、巩固裁决器、附加记忆与工作集、既有隔离防线、既有 E2E 与既有 AOEP 断言）——本 Feature 只消费与测量它们。

## Technical Context

**Language/Version**: Python ≥3.12（`backend/pyproject.toml`，沿 asyncio/SQLAlchemy 2 async/Pydantic 2 风格）；TypeScript 5.6 / React 18 / antd 5（前端六视图与统计展示）；JSON Schema Draft 2020-12（报告与数据集契约）。

**Primary Dependencies**: 无新依赖。后端复用 FastAPI、SQLAlchemy 2、Pydantic 2、jsonschema Draft202012、pytest/pytest-asyncio（`asyncio_mode=auto`）；eval 运行器复用既有内核（`run_memory_comparison.py`、`memory_continuity_support.py`、`hard_metrics_014.py`、`memory_acceptance_reports.py`）；前端复用既有 `api/memories.ts`、`hooks/useSSE.ts`、`i18n` 资源层与 antd 5 组件。**本 Feature 不引入任何新 LLM/网络依赖，无新检索路径、无新 MCP 工具、无新域模型**。

**Storage**: PostgreSQL **预期零 DDL**——统计端点只读既有 `MemoryEntry`（经 `MemoryProjectionMeta` 六投影校验）、`MemoryEvent`（回滚计数按事件类型）、`ConsolidationRunObservation`（巩固运行计数）、`MemorySalience`（显著性分布）、`MemoryManagementAudit`（治理审计）；投毒与 AOEP 用例复用 012 既有事件日志与投影物化路径，不新增表。若实测证明统计聚合需要支撑索引，**新增独立迁移**（不改动既有迁移与既有表语义）。Qdrant 仅经既有记忆读路径复用，不新增集合。文件系统：`eval/` 新增数据集/运行器/报告，`eval/runs/<015-run-id>/` 承载重跑与回归产物；`docs/` 需新建目录（当前工作区不存在）。

**Testing**: pytest 三层（contract：报告/数据集/统计响应 schema 正反例；integration：投毒执行器与 AOEP 义务套件，真实 PG/Qdrant；unit：统计聚合与报告装配纯函数）+ eval 对照运行器（基线报告、硬指标五件套、全集回归）；报告与数据集经 jsonschema Draft202012 校验。前端**无组件测试基座**（`frontend/package.json` 无 `test`/`lint` 脚本，`node_modules` 仅含 playwright/tsc/vite），故前端验证 = `pnpm build`（`tsc -b` 严格模式，i18n 键缺失即编译失败）+ Playwright（唯一测试基座，`frontend/tests/`，`baseURL http://127.0.0.1:5178`，`reuseExistingServer: true`）新增路由打桩规格；既有 `frontend/tests/memory.spec.ts` 两条断言（无横向溢出、回滚/写不可用时 `MEMORY_WRITE_UNAVAILABLE` 以 Alert 呈现）必须保持通过。

**Target Platform**: Windows 开发 + 现有 Linux/Python 服务部署；单 writer/多 reader（管理面仅 writer，`require_writer` 依赖 writer 租约，否则 503 `MEMORY_WRITE_UNAVAILABLE`）；管理 HTTP 默认 loopback。

**Project Type**: RAG MCP backend 增量 + 前端管理面增量 + 评测/文档工程。不新增 MCP 工具（工具面锁定六个）、不改变六工具口径与既有响应字节、不新增写治理入口到 MCP 面。

**Performance Goals**: 离线评测批处理，无实时性能目标；延迟 P50/P95 仅记录并标注环境敏感，**不设通过门、不参与 1% 非延迟容差判定**；统计端点按域聚合，**不得拉取正文计算分位**（聚合在 SQL/投影层完成，只输出计数与分位）；治理 UI 加载与刷新沿既有分页（每页 20）与 SSE 增量刷新，不引入全库扫描。

**Constraints**: 投毒子集与 AOEP 义务用例全过是定稿硬前置（FR-053）；投毒拦截率 = **100% 硬水位**（安全零容差，不得以容差替代）；**投毒子集构造期可迭代、达标后首次冻结**，冻结后任何失败如实判定并阻止定稿，不得替换/删改/放宽既有条目；**AOEP 破坏性操作仅在每次运行新建的专用隔离域与隔离身份内执行**，不得作用于既有真实域或既有固定评测集依赖的域（013/014 共用 scope `366084747748704256` 为显式禁入项），隔离范围标识与运行后处置须留记录；**依赖模型的回归组强制 record + replay**，实时调用不得过闸；评测集一经入库**只增不破坏**；基准报告为**历史产物不覆盖重写**（运行器拒绝覆盖已存在输出路径）；治理 UI **不得**提供无域过滤的全局记忆正文视图（未选域时为空态或仅域级汇总）；回滚**仅管理面**且必有审计；零分母一律记"不可测量 + 原因"，**不得记 0、不得记为达标**；`GET /runtime/metrics` 与六工具契约**零改动**；全集回归非延迟 1% 相对容差、安全指标零容差，未执行不得记为通过。**SSE 不作为正确性依赖**：治理 UI 的数据正确性由 REST 拉取（挂载时 + 每次治理动作后 + 手动刷新）保证，SSE 仅作可选增量刷新信号（沿用 `useSSE` 单一 topic），因此 SSE 未接线不得被记为 UI 未达标，也不得反过来以 SSE 论证正确性。

**Scale/Scope**: 三子集——连续性 ≥15 条（既有 16 条复核冻结）、巩固受益 ≥6 条（既有 6 条复核冻结）、投毒防护 ≥5 条（新建）；AOEP 五条不变量各 ≥2 例（≥10 例）；硬指标五件套 + 隔离泄漏（五投影分母独立）；1 份基准报告 + 1 份报告契约（含共享 `$defs`）+ 2 份数据集契约 + 1 份统计响应契约 + 1 份治理 UI 契约 + 1 份定稿核销契约；1 个统计端点；前端 6 个视图 + 1 个强确认组件；5 类文档工件。任务规模预估 35–45（蓝图 §8.4 六任务组）；**本 tasks.md 实际 75 项**（T001–T075，含 Phase 9 回填 T068–T075 与两侧张后的计数差，如实登记而非回填估计区间）。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | Phase 0 依据 / Phase 1 落实 | 判定 |
|---|---|---|
| I Explicit Scope | 全部评测/统计/治理读写与检索一律携带显式域引用；统计端点强制显式域参数；治理 UI 未选域不返回任何正文；范围不扩张用例覆盖歧义拒绝与不回落 | PASS |
| II Domain Facts | 三子集与统计均按域呈现；域身份在报告逐条目与统计分桶中保留；不产生跨域混合正文 | PASS |
| III Uncertainty | 不可测量项显式记 `not_measurable` + 原因（零分母、能力关闭）；巩固默认关闭与"无可主张受益"如实继承，不改写；延迟环境敏感性标注 | PASS |
| IV Locatable Evidence | 来源可定位率 100%（证据路径）与记忆 provenance 完备率 100%（记忆路径）**分项统计不合并**；报告逐条目保留锚点与来源指针 | PASS |
| V Data and Control Separation | 投毒子集证明注入内容被标记、隔离且不改变提示/工具/权限/开关/范围/过滤/阈值/状态转换；变种"控制面不被改变"断言**独立于检测命中**；检测异常不崩溃、不放宽校验、不记"已拦截" | PASS |
| VI Deterministic Control | 检测器、隔离判定、回滚重放、投影重建、统计聚合与报告装配均为确定性代码；本 Feature 无 LLM 进控制路径；模型评审（若有）仅作诊断项 | PASS |
| VII Interface Evolution | 统计端点为**新增独立端点**，`/runtime/metrics` 与六工具契约、OpenAPI 既有路径零改动；报告/数据集 schema 为新增独立契约 | PASS |
| IX Synchronous Results | 评测为同步批处理产物；治理 UI 走既有 REST + SSE；无 Resources/Tasks 依赖 | PASS |
| X Evaluation-Driven | 本 Feature 即记忆基准与状态义务基线的**建立者**：以"基线锚点/当前水位"表述，缺少对照提升证据不得宣称改进；投毒 100% 硬水位、连续性/受益沿既有判据、延迟仅记录；**范围决策（FR-060）：目标 MCP 宿主评测与成本评测不在本 Feature 范围**——宿主证据仅沿 FR-054 的回归组重跑，两项缺位如实登记为范围外、触发条件满足后另立 Feature，故本行判定为"通过（含范围外如实登记）"而非无条件 PASS | PASS（含 FR-060 范围外登记） |
| XII External Memory Loop | 硬记忆锚定率 100%、软/distilled provenance 完备率 100% 全量实测（FR-030/FR-031）；纠正链不物理删除、墓碑保留来源链（FR-016）；知识候选不自动入正身（自动晋升次数 = 0，FR-041）；记忆不可信数据边界经投毒子集实测（FR-001/FR-005）。**`supersede` 链、确定性裁决、正身不可经记忆通道变更三项由 FR-054 回归 012/013 既有交付物承担（015 不重建、不自证）**；本 Feature 新增的强制点为 provenance 保全（FR-056）与六轴状态元数据齐备（FR-058） | PASS |
| XIII Governed Trajectory | 事件日志为唯一权威；六投影为只读派生；五不变量（回滚可溯、删除传播、权威单调、provenance 保全、范围不扩张）由 AOEP 用例逐条机器判定——五项名称与《宪法》XIII 第三条**逐字对应**，原 `authority_boundary` 已更名为 `authority_monotonicity`（FR-014/FR-056）；回滚仅管理面且回滚动作自身入日志 | PASS |

**六项不可协商硬约束逐项复核**：① 跨域串库 = 0——事件日志/关系/向量/文件**四路径各自实测样本量 ≥1 且串库数为 0**，零样本路径不得记为达标（修复 014 的 `cross_domain_leakage.value = null`）；② 无显式 scope 一律拒绝——AOEP 范围不扩张用例（**缺失/空引用与歧义引用两类各自构造、各自非零样本量**，缺失 ≠ 歧义，FR-061/SC-028）与统计端点参数校验覆盖，"回落最近域/全库"次数 = 0；③ 上传与记忆内容不得控制执行——投毒子集六道断言 + 隔离泄漏 = 0；④ MCP Schema 合法率 100%——六工具真实协议响应对照契约 schema，含非法输入负例，分母非零；⑤ 来源可定位率 100%；⑥ 投影完整率 100%——删除传播五投影逐投影断言 + 重建后一致性校验 + 逐投影可复算/运行期只读实测（FR-057 的 `hard_metrics.projection_integrity`，六视图各自分母、零分母记不可测量）。

**结论**：无宪法违反项，无需 Complexity Tracking 豁免。需显式说明的三处非违反性判断：① 统计端点为**加法**（新路径，不动 006 契约）；② 投毒与 AOEP 用例为**新增评测资产**（不修改 012/013 既有断言与既有数据集）；③ `docs/1.0-iteration-roadmap.md` 与 `docs/技术架构说明书.md` 当前**不在工作区**，交付形态为"按同一路径重建"，属 FR-047/FR-049 明示要求，非范围扩张。

**Phase 1 设计后复检（post-design re-check）**：R1（纯合成投毒子集 + 冻结变种字典）不引入外部依赖，符合"冻结可复现"与硬约束 ③；R2/R3（eval 数据文件为唯一真相源、pytest 参数化消费）不产生双真相，符合 X 与硬约束 ④；R4（薄入口运行器复用内核）不改 001/002/011 口径，符合 VII；R5（报告历史产物 + 拒绝覆盖 + 时间戳运行标识）符合 X；R6（逐投影指纹 + 事件链闭合 + 零分母纪律）符合 XIII 与 III；R9（独立统计端点、显式域、零正文）符合 I/VII 与 006 隐私护栏先例；R10/R11（scope 门 + 强确认 + 仅单条）符合 I 与铁律五；R13（七项核销含未达成项如实处置）符合 X。**复核结论：仍无违反项，gate 维持通过。**

## Project Structure

### Documentation (this feature)

```text
specs/015-memory-evaluation-governance/
├── spec.md                                    # 已澄清（Q1–Q5 冻结决议）
├── plan.md                                    # 本文件（/speckit-plan 输出）
├── research.md                                # Phase 0 输出（R0–R14 决策记录 + 五项必覆盖内容）
├── data-model.md                              # Phase 1 输出（九类实体 + 报告/数据集/统计形态）
├── quickstart.md                              # Phase 1 输出（VS-01~VS-14 验证场景）
├── contracts/
│   ├── README.md                              # 契约索引与冻结规则
│   ├── memory-benchmark-common.schema.json    # 共享 $defs（指标块/延迟块/硬指标块/子集块/AOEP 块/可复现性块/配置块）
│   ├── memory-baseline-report.schema.json     # 记忆基准报告契约（三子集 + AOEP 得分 + 硬指标五件套 + 延迟）
│   ├── poisoning-eval-dataset.schema.json     # 投毒子集条目契约（模式标签/变种/六道断言/判据）
│   ├── aoep-obligation-dataset.schema.json    # AOEP 义务用例契约（不变量/目标/机器判据/逐投影判定）
│   ├── memory-stats-response.schema.json      # 统计端点响应契约（只含计数与分位，无正文）
│   ├── governance-ui-contract.md              # 治理 UI 契约（六视图、scope 门、强确认、单条边界）
│   └── finalization-ledger.schema.json        # 3.0 定稿核销工件契约（七项逐项判定 + 证据指针）
└── tasks.md                                   # /speckit-tasks 输出，不由本命令创建
```

### Source Code (repository root)

```text
backend/src/rag_mcp/
  api/memory.py                                 # 修改：新增 GET /stats（挂既有 router prefix="/api/memories"）
  services/memory_statistics.py                 # 新增：按域聚合（条数/kind/provenance/显著性分桶/巩固与回滚计数，零正文）
backend/tests/
  contract/test_015_memory_baseline_report_schema.py   # 新增：报告契约正反例（含不可测量与状态条件分支）
  contract/test_015_memory_benchmark_datasets.py       # 新增：投毒/AOEP 数据集体例校验 + 只增不破坏断言
  contract/test_015_memory_stats_schema.py             # 新增：统计响应契约 + 零正文断言（含正文开关打开态）
  integration/test_015_poisoning_suite.py              # 新增：参数化消费投毒数据文件，六道断言逐条执行
  integration/test_015_aoep_obligations.py             # 新增：五条不变量各 ≥2 例，机器判定并导出逐例结果
  unit/test_015_memory_statistics.py                   # 新增：聚合纯函数（分桶边界、空域、无正文）
frontend/src/
  pages/MemoriesPage.tsx                        # 修改：六视图骨架（Tabs）+ 域选择为必选门（保持既有 List 浏览为默认视图）
  components/memory/                            # 新增目录（frontend/src/ 现无 components/）
  components/memory/MemoryBrowseView.tsx        # 新增：浏览 + 六维过滤（域/分型/状态/provenance/会话/显著性）
  components/memory/MemoryGovernanceView.tsx    # 新增：下线/显式清理（唯一清理路径）+ 影响面 + 审计指针
  components/memory/MemoryRollbackView.tsx      # 新增：回滚目标选择 + 影响面预览 + 强确认 + 结果/审计
  components/memory/MemoryRebuildView.tsx       # 新增：投影重建触发 + 各投影一致性校验报告
  components/memory/MemoryPromotionView.tsx     # 新增：晋升候选队列 + 人工晋升（无自动晋升入口）
  components/memory/MemoryConsolidationView.tsx # 新增：巩固报告页（consolidation_runs 明细与失败/拒绝原因）
  components/memory/MemoryStatsPanel.tsx        # 新增：域级统计面板（无正文）
  components/memory/ConfirmActionModal.tsx      # 新增：强确认（须输入目标确认值方可提交）
  api/memories.ts                               # 修改：stats/retire/purge/rollback/rebuild/promotion/consolidation 客户端与类型
  i18n/zh.ts, i18n/en.ts                        # 修改：六视图与强确认中英文案（en 为基线，缺 zh 键即 tsc 报错）
frontend/tests/memory-governance.spec.ts        # 新增：Playwright 路由打桩规格（六视图、六维过滤、scope 门、强确认、无批量）
eval/
  memory_poisoning_eval_dataset.json            # 新增：≥5 条纯合成投毒用例（冻结、只增、含变种与中文、含 isolation/freeze 块）
  memory_aoep_obligation_dataset.json           # 新增：五条不变量各 ≥2 例（冻结、只增、含逐运行专用隔离域声明）
  memory_aoep_isolation.py                      # 新增：每次运行新建专用隔离域与隔离身份、禁入既有域校验、运行后处置记录
  run_memory_baseline.py                        # 新增：三子集 + AOEP + 硬指标五件套 + 延迟 → 基准报告（薄入口）
  memory_baseline_support.py                    # 新增：报告装配/逐投影指纹/不可测量编码/时间戳运行标识
  run_regression_015.py                         # 新增：001–014 全集回归编排（产物落 eval/runs/<015-run-id>/）
  memory_baseline_report.json                   # 新增（首次产物；历史产物，勿覆盖）
  runs/<015-run-id>/                            # 新增：重跑报告、AOEP 逐例结果、回归产物、JUnit
docs/
  1.0-iteration-roadmap.md                      # 重建：001–015 交付记录 + 3.0 状态行（路径被 .gitignore 忽略但仍须产出）
  技术架构说明书.md                              # 重建：新增"记忆回路"章 + §6 契约层/§7 运行态最小修订
  3.0-finalization.md                           # 新增：实施蓝图 §1 七项演进目标逐项核销（独立工件）
README.md                                       # 修改：新增记忆能力章节（六工具/分级信任/治理与回滚边界/评测与硬指标/隐私边界）
specs/001-*/spec.md … specs/014-*/spec.md       # 修改：Status 按交付事实更新（011–014 草稿→已交付；001–010 复核一致）
```

**Structure Decision**: 保持 backend / frontend / eval / docs 既有单体布局，无新增项目、无新增权威源、无新迁移预期。交付面集中在四处：`eval/`（两份新数据集、薄入口基线运行器与支持模块、回归编排、报告产物）、`backend/`（一个只读统计端点 + 一个聚合服务 + 五份测试）、`frontend/src/`（MemoriesPage 六视图 + 强确认组件 + api/i18n 增量；`components/memory/` 为新建目录，`frontend/src/` 此前无 `components/`）、`docs/`（三份文档工件 + 001–014 状态更新）。三处需显式记录的既有约束：① **投毒与 AOEP 用例采用"eval 数据文件为唯一真相源、pytest 参数化消费"的双形态**——数据文件保证报告可引用与冻结可复现，pytest 套件保证 CI 可跑与逐例可观测，两者不重复定义内容；② **统计端点挂既有 `APIRouter(prefix="/api/memories")`**，即 `GET /api/memories/stats`——spec Clarifications 记的 `/api/memory/stats` 为简写，语义（独立端点、显式域、仅写实例管理面、不并入 `/runtime/metrics`）不变，本计划采用与既有路由前缀一致的具体路径以免在 `/api/memories` 之外另起一套命名；③ **SSE 复用但不作正确性依赖**——`useSSE` 只有 `ProjectDetailPage` 一个消费者，且 `publish_event` 在 `backend/` 内**无任何调用点**（当前流只发 `heartbeat`），hooks 的一次性 connect 亦使 `scope:<id>` topic 在冷启动下不会重订阅；因此治理 UI 以 REST 拉取为正确性路径，SSE 仅作可选增量信号，并将该既有局限如实记入 research.md R10 与报告，不伪称 SSE 刷新已生效。

## Phase 0: Research Decisions

research.md 覆盖 15 项决策（R0–R14），其中五项为用户指定必覆盖内容：**R1**（投毒用例与检测器模式映射表：8 个 high-risk + 2 个 low-risk 模式逐条映射与变种字典构造）、**R6**（AOEP 义务的机器可判定判据：事件链闭合 + 逐投影指纹 + 五投影分母纪律）、**R4**（基准报告 schema 定义：块结构、必需键、条件分支、不可测量编码）、**R10**（治理 UI 的 scope 显式过滤交互：六视图 + 无全局记忆正文视图 + SSE 刷新边界）、**R13**（3.0 目标核销判据-证据对照表预填：七项逐项判据与证据工件指针）。其余决策：R0 基线声明与水位、R2 投毒双形态 **+ 冻结时点（Q6）**、R3 AOEP 双形态 **+ 逐运行专用隔离域与身份（Q8）**、R5 报告历史产物与运行标识、R7 与 012/013 既有 AOEP 的边界、R8 硬指标五件套全量实测方法、R9 统计端点决议落地、R11 强确认与单条边界、R12 文档工件清单与写作顺序、R14 全集回归编排 **+ record/replay 两轮（Q7）**。

关键现状锚点（2026-10-09 工作树，只读核验）：`InjectionDetector.detect()` 返回 `InjectionReport(suspicious, risk_level ∈ {none,low,high}, matched_patterns)` 且**永不抛异常**（`strict=False` 时）；`services/memory_projection_store.py` 的 `VIEW_KEYS` 恰为六投影 `{relation:entries, dense:dense, links:links, summary:summary, file:files, salience:salience}`，`versions()` **强制恰好六类齐全**；`services/memory_reducer.py` 提供 `reduce_events(events, *, initial_state=None)` 与 `projection_fingerprint(state)`（对 canonical JSON 取 sha256），是本 Feature 逐投影指纹与状态复算的既有原语；`api/memory.py` 的 `APIRouter(prefix="/api/memories")` 已提供 browse/bindings/policy/retire/purge/usage/rollback/bindings/rebuild/rebuild-audit/promotion-candidates/promote/promotions/{id}/consolidation/consolidation/runs，写操作一律 `Depends(require_writer)`；既有 AOEP 断言位于 `tests/integration/test_012_aoep_obligations.py`（5 例）与 `test_013_consolidation_aoep.py`（11 例），本 Feature **只新增不修改**。

## Phase 1: Implementation Groups

以下为供 tasks 阶段拆分的单元/依赖，**不是实施完成声明**。任务组沿蓝图 §8.4 六组（015-1…015-6）展开。

| 单元 | 对应蓝图组 | 产出 | 依赖 | 独立验证 |
|---|---|---|---|---|
| A 投毒子集与执行器 | 015-1 | `eval/memory_poisoning_eval_dataset.json`（≥5 条纯合成，模式标签 + 变种字典 + 六道断言 + 判据 + `isolation`/`freeze` 块）、`backend/tests/integration/test_015_poisoning_suite.py`（参数化消费数据文件） | 012（检测接线/隔离/双排除） | 模式覆盖 role_hijack(+zh)/identity_override/tool_call_manipulation 各 ≥1；变种 ≥1 且判定不依赖命中；"标记且隔离"逐条判定；六道断言逐条可观测；检测异常不崩溃、不放宽、不记已拦截；**首次冻结发生在全部 primary 用例"既标记又隔离"之后，冻结时点入记录**；写入不触及 013/014 冻结集依赖域；重跑结论稳定 |
| B AOEP 义务用例与判据 | 015-2 | `eval/memory_aoep_obligation_dataset.json`（五条不变量各 ≥2 + `isolation` 块）、`eval/memory_aoep_isolation.py`（每次运行新建专用隔离域与身份、禁入既有域校验、运行后处置记录）、`backend/tests/integration/test_015_aoep_obligations.py`（机器判定并导出逐例结果 JSON） | A、012/013 既有原语 | 回滚可溯=事件链闭合+序号链无缺失/无重复+逐投影指纹比对+影响面一致；删除传播=五投影各自断言且各自分母非零；权威单调=越权/MCP 改写绑定表被拒 + 权威日志 id 序列前后逐项相等且留审计（`authority_monotonicity`，原 `authority_boundary` 更名）；provenance 保全=状态转移后 provenance 与 `content_hash` 保留且可复算（`provenance_preservation`）；范围不扩张=歧义拒绝且回落次数 0；**逐例含 `isolated_scope_id`，破坏性操作触及既有真实域或 013/014 冻结集依赖域的次数 = 0**，隔离标识与处置记录齐备；逐例含 request_id/状态/前后指纹/影响面/可复现记录 |
| C 基准报告契约与运行器 | 015-2 | `contracts/memory-benchmark-common.schema.json`、`memory-baseline-report.schema.json`、`run_memory_baseline.py`、`memory_baseline_support.py`、`eval/memory_baseline_report.json` | A,B | 报告经契约 schema 校验；三子集指标 + AOEP 得分 + 硬指标五件套 + 隔离泄漏 + P50/P95 齐备；不可测量记 null+原因（记 0 次数为 0）；历史产物不覆盖（已存在输出路径拒绝写入）；同快照同版本重跑在 1% 容差内 |
| D 硬指标五件套全量实测 | 015-3 | 四路径多域串库实测（修复 `cross_domain_leakage.value = null`）、六工具契约全量含负例、定位率与 provenance 分项、硬锚定率含被拒样本与错误码分布、隔离泄漏五投影独立分母 | C | 每条路径样本量 ≥1；零分母不记达标；安全指标零容差、不以容差替代；真实 PG/Qdrant/协议响应，测试桩替代次数为 0 |
| E 统计端点 | 015-4 | `services/memory_statistics.py`、`api/memory.py` 新增 `GET /api/memories/stats`、`contracts/memory-stats-response.schema.json`、`tests/unit/test_015_memory_statistics.py`、`tests/contract/test_015_memory_stats_schema.py` | 012 投影 | 按域返回条数/kind 分布/provenance 分布/显著性分位分桶/巩固计数/回滚计数；零正文（正文开关打开态亦然）；非授权或只读实例访问失败；口径与浏览一致；`/runtime/metrics` 契约零改动 |
| F 治理 UI 六视图 | 015-4 | `MemoriesPage.tsx` 六视图 + `components/memory/*` + `ConfirmActionModal` + `api/memories.ts` + i18n 双语 + `frontend/tests/memory-governance.spec.ts` | E | 八项操作可从管理面完成；六维过滤可用；未选域时无任何跨域正文列表；purge/回滚强确认（缺强确认即可提交次数为 0）；批量入口不存在；MCP 面无回滚/删除入口；投影重建与校验报告可见、失败显式；晋升为显式人工动作；`pnpm build` 通过且既有 `memory.spec.ts` 两条断言保持通过 |
| G 全集回归 | 015-5 | `eval/run_regression_015.py` + `eval/runs/<015-run-id>/` 产物（含 record/replay 封存缓存与 manifest） | A–F | 001–014 全部组按各自口径重跑；**依赖模型的组（005、013 等）走 record + replay 两轮，重放轮真实网络调用 = 0 且为唯一过闸依据，缓存指纹与重放网络调用计数入报告 `regression.groups[]`**；非延迟 1% 容差、安全零容差；未执行记 `not_executed`；历史报告零覆盖；012–014 E2E 与 AOEP 按原口径通过 |
| H 文档债与 3.0 定稿 | 015-6 | `docs/1.0-iteration-roadmap.md`、`README.md` 记忆章、`docs/技术架构说明书.md`（记忆回路章 + §6/§7 最小修订）、`docs/3.0-finalization.md`、001–014 spec Status | G | 四份文档与核销工件齐备；核销七项逐项判定 + 证据指针 + 未达成处置；蓝图正文改写次数 0；未达成结论（巩固默认关闭、无可主张受益、默认启用资格为假）零改写；无超售陈述 |

顺序纪律：**安全测试先行**（A 的投毒子集与 B 的权威单调/范围不扩张先红后绿），先立契约与判据（C）再做全量实测（D）与端点/UI（E/F），最后回归（G）与文档定稿（H）。任何一项安全类失败优先于功能任务修复，且不得以"默认关闭"豁免。

## Requirement Coverage

| 要求 | 设计/验证 |
|---|---|
| FR-001…FR-007 | A：纯合成子集、模式与变种覆盖、判据"标记且隔离"、六道断言逐条可观测、权威/正身通道次数 0、检测异常不崩溃不放宽不记拦截、入库纯追加；**首次冻结发生在构造期全过之后（FR-002 冻结时点），冻结后失败如实判定并阻止定稿、补救仅追加或另立 Feature** |
| FR-008…FR-013 | C：三子集构成与复核冻结记录（版本/标识/语料与快照指纹/判据来源/冻结时刻/逐条审核/语言与类别覆盖）、只增不破坏、连续性四类场景与预冻结判据、受益子集 013 结论如实继承、跨环境稳定锚点与零放宽 |
| FR-014…FR-020 | B：五条不变量各 ≥2 例、**以评测数据集工件声明并由专用运行器执行留证**、时间点与事件点回滚各 ≥1 且可再次回滚、五投影全传播且权威日志保留墓碑与来源链、权威单调（越权与 MCP 绑定表写入被拒 + 前后权威日志 id 序列逐项相等）与 provenance 保全（状态转移后保留且可复算）、范围不扩张与串库 0、逐例证据齐备且重跑稳定、**破坏性操作限于每次运行新建的专用隔离域与隔离身份且不触及既有真实域**、结果汇入 AOEP 义务得分并阻断定稿 |
| FR-021…FR-027 | C：报告齐备性、001/002/011 契约形态与指纹、历史产物不覆盖与登记、不可测量显式化、达成判定与未达成处置、锚点而非改进、非延迟可复现（模型评审仅诊断） |
| FR-028…FR-034 | D：四路径多域串库全量实测、六工具契约全量含负例、定位率与 provenance 分项、硬锚定率含被拒样本与错误码、隔离泄漏五项独立分母、任一不达即整体不通过、真实运行证据零桩替代 |
| FR-035…FR-043 | F：八项治理操作、六维过滤与显式域门、下线/清理影响面与强确认与审计指针、纠正链可导航、回滚面板仅管理面含影响面预览/强确认/结果/审计、投影重建与一致性校验报告、显式人工晋升、巩固报告页与域策略编辑、房规与服务端校验 |
| FR-044…FR-046 | E：独立统计端点 `GET /api/memories/stats`、按域五类分布与两计数、零正文隐私护栏与写实例可用、口径与浏览及报告一致、不拉正文算分位、不并入 `/runtime/metrics` |
| FR-047…FR-050 | H：迭代路线重建至 3.0、README 记忆能力章无超售、技术架构说明书 3.0 章最小增量、001–014 Status 按事实更新且未达成结论零改写 |
| FR-051…FR-055 | H/G：七项逐项核销独立工件、蓝图正文冻结、定稿硬门（投毒全过 + AOEP 全过 + 五件套与隔离泄漏全过 + 全集回归无回归）、001–014 全集回归按各自口径且**依赖模型的组走 record + replay 两轮、重放轮真实网络调用 = 0 为唯一过闸依据**、三子集水位口径（仅投毒 100% 硬水位；连续性/受益沿既有判据；延迟仅记录） |
| FR-056 | B（US3）：AOEP 数据集与报告覆盖《宪法》XIII 第三条五项不变量，含两条新增——权威单调 `authority_monotonicity`（前后权威日志 id 序列逐项相等、权威等级不变、绑定表行集不变、拒绝留审计）与 provenance 保全 `provenance_preservation`（状态转移后 provenance/来源链/`content_hash` 保留且可复算）；每条 ≥2 例；`invariants` 键集与 `aoep.by_invariant` 键集恰为五项齐全（T021/T024/T068/T069） |
| FR-057 | D（US5）：报告 `hard_metrics.projection_integrity` 显式记录投影可复算与运行期只读实测（投影完整率 100%，逐投影 `examined ≥1`、`drift = 0`），零分母记 `not_measurable` + 原因；MUST NOT 以 route 打桩或组件测试替代（T070） |
| FR-058 | D（US5）：报告 `hard_metrics.state_metadata_completeness` 显式记录六轴（`authority`/`scope`/`mutability`/`provenance`/`recoverability`/`actionability`）状态元数据齐备率，各轴单独给出分母与结论，零分母记 `not_measurable` + 原因（T071） |
| FR-059 | G（US8）：全集回归的组→测试映射显式登记（每组 `{group, runner, command, test_module, artifact}`，落 `regression_group_map.json`），重放轮真实网络调用实测为 0 且缓存 manifest 哈希登记；映射缺失或未执行的组 MUST NOT 记为通过（T058/T059/T060） |
| FR-060 | H/G（US8）：范围决策如实登记——目标 MCP 宿主评测与成本评测不在本 Feature 范围，宿主证据仅沿 FR-054 回归组重跑，两项缺位登记为范围外并写明纳入触发条件（T073）；真实域语料由 FR-028/FR-034 承担，投毒子集为纯合成（FR-002）不构成真实域语料 |
| FR-061 | B（US3）：无显式 scope 的记忆读写一律拒绝——缺失/空（含空串与只含空白）`scope_ref` MUST 被拒（`MISSING_KNOWLEDGE_SCOPE`）并给候选、不回落最近域/全库、拒绝留审计；**缺失 ≠ 歧义**，两类用例各自构造、各自非零样本量（T024 歧义 / T075 缺失与空） |

US1→A，US2→C，US3→B，US4→C，US5→D，US6→F，US7→E，US8→H；FR-056→US3/B（T068/T069），FR-057/FR-058→US5/D（T070/T071），FR-059→US8/G（T058–T060），FR-060→US8/H（T073），**FR-061→US3/B（T024/T075）**，脱敏断言 FR-006 回填→US1/A（T072），七项目标 1:1 核验→Polish（T074）。SC-001–SC-028 均有对应观测（SC-028 由 T024/T075 与 quickstart VS-14 观测）；不得以文档、mock 或单测替代真实 PG/Qdrant、真实协议响应与真实回滚/重建实证。

## Validation And Delivery Gates

1. **契约/数据资产**：四份 JSON Schema（报告、投毒数据集、AOEP 数据集、统计响应）与定稿核销契约全部 Draft202012 引用可解析、正反例通过；投毒与 AOEP 数据集满足规模/覆盖/语言/冻结记录；**只增不破坏**由"新增一条不改变既有条目"的可复算断言证明（既有条目哈希不变）；013/014 既有数据集与既有报告字节零改动。
2. **安全（最高优先级）**：投毒子集六道断言逐条全过且判据为"标记且隔离"；隔离内容进入默认召回/巩固窗口/附加记忆/工作集/控制面次数 = 0；投毒内容成为硬记忆/进入晋升候选/自动晋升正身/经巩固获得生效权威次数 = 0；检测异常路径不崩溃、不放宽、不记已拦截；权威单调（越权写入、非写实例、只读实例、MCP 改写绑定表）拒绝率 100% 且留审计；范围不扩张拒绝率 100% 且回落次数 0。
3. **AOEP 机器判定与隔离**：五条不变量各 ≥2 例（合计 ≥10），其中**权威单调与 provenance 保全各 ≥2 例**（FR-056）；回滚可溯由事件链闭合（前后水位与事件序号；序号链判据 = 回放序列与权威日志逐项相等、无缺失、无重复，**非数值连续**）+ 逐投影指纹比对 + 影响面计数一致判定；删除传播对关系/向量/链接/摘要/文件五投影各自断言且各自分母非零，零分母记不可测量；逐例产出 request_id/状态/前后指纹/影响面/可复现记录 + `isolated_scope_id`；同版本重跑结论稳定率 100%；非管理面回滚成功次数 0 且拒绝留审计；**破坏性操作触及既有真实域或 013/014 冻结集依赖域（scope `366084747748704256`）的次数 = 0，隔离范围标识与运行后处置记录完备率 100%**。
4. **报告与硬指标**：`memory_baseline_report.json` 经契约校验、三子集指标 + AOEP 得分 + 五件套 + 隔离泄漏 + P50/P95 齐备；四路径串库各路径样本量 ≥1 且为 0；六工具契约合法率 100%（分母非零、含负例）；定位率与 provenance 完备率各 100% 且分项；硬锚定率 100% 且有被拒样本与错误码分布；不可测量项记 null + 原因、记 0 次数为 0；历史报告零覆盖（已存在输出路径拒绝写入）。
5. **端点与 UI**：统计端点按域返回五类分布与两计数、零正文（正文开关打开态亦然）、仅写实例管理面可用、口径与浏览一致、不并入 `/runtime/metrics`；治理 UI 八项操作与六维过滤可用；未选域无跨域正文列表；purge/回滚强确认不可绕过；批量入口不存在；MCP 面无回滚/删除入口；投影重建失败显式呈现。
6. **回归与定稿**：001–014 全部组按各自口径重跑（1.0 六组、2.0 两组、012–014 新增组及其 E2E/AOEP/宿主证据），非延迟 1% 相对容差、安全零容差；**依赖模型的组（005、013 等）强制 record + replay 两轮，重放轮真实网络调用 = 0 为唯一过闸依据，实时调用不得过闸，缓存指纹与重放网络调用计数记入报告 `regression.groups[]`**；未执行项记 `not_executed`、历史报告零覆盖；3.0 定稿硬门四项同时满足方可判定通过；七项核销逐项判定 + 证据指针 + 未达成处置齐备；蓝图正文改写次数 0；001–014 未达成结论零改写。
   **规格同步项**：已核验 FR-054 正文（spec.md:275）已含 record + replay 要求（记录轮冻结模型响应与缓存指纹、重放轮真实网络调用 = 0 且为唯一过闸依据）；T061 负责核验登记，不再编辑正文。
7. **纪律**：TDD 先红后绿；checklist 只读；评测集只增不破坏；基准报告不覆盖重写；安全测试失败优先级高于一切功能任务；不修改宪法、蓝图正文与既有 001–014 报告。

## Complexity Tracking

> 无宪法例外，无需豁免记录。

必要复杂性来自四处既有约束，均以既有原语化解而非新建基础设施：① **逐投影指纹已存在，缺的是水位与投影级影响面**——`MemoryProjectionMeta.fingerprint` 落盘的就是 `projection_fingerprint(state[key])`（`memory_projection_store.py:232`），`ProjectionRebuilder.inspect()` 已返回每视图 `{count, fingerprint, matches_replay}`，故 R6 的"逐投影指纹比对"直接复用；真正的缺口是治理响应 `impact` 只有 `{memory_ids, scope_ids}` 且不含事件水位——本 Feature 以**评测层组合既有系统产物**（事件 payload 的 `event_point` + `MemoryProjectionMeta.source_event_id` + `inspect()` 的投影计数）补齐，**不改 012 的治理响应与事件载荷**；② **"序号链无缺口"必须重新解释**——`event_id` 由 snowflake 生成、数值天然稀疏，字面连续性检查会恒假，故判定为"回放 id 序列与权威日志逐项相等、无缺失、无重复"（既有 `projection_rebuild.py:143-146` 与 `reduce_events` 的重复检测即此语义），该解释必须写进 CLI 文档与报告 `detail`；③ **五投影分母纪律**——FR-016 的五类（关系/向量/链接/摘要/文件）不含显著性字段投影，而 `memory_projection_store.versions()` 强制恰好六类齐全，故用例构造必须显式保证五类在前置状态可观测，sali​ence 字段投影不参与该断言；④ **统计端点的零正文与不拉正文**——聚合必须在 SQL/投影层完成（`MemoryEntry` 经 `MemoryProjectionMeta` 校验、`MemorySalience` 分桶、`MemoryEvent` 按类型计数、`ConsolidationRunObservation` 计数），不得经 `public_entry` 取正文后本地计算；⑤ **报告不可测量语义**——014 的 `hard-metrics-014.json` 已确立 `value: null` + 原因（"a zero denominator is not a measured zero"），015 沿用同一编码并把 `cross_domain_leakage` 从 null 修为有分母实测。另有一处既有缺陷不得复制：`hard_metrics_014.py:435` 无条件重写追踪产物 `eval/hard-metrics-014.json`，是本仓库唯一违反"历史产物不覆盖"的位置，015 的运行器一律"存在即拒绝"。未另建事实权威、未新增 MCP 工具、未新建检索通道、未新增迁移。
