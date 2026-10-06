# Tasks: 013 记忆巩固回路

**Input**: [spec.md](spec.md)、[plan.md](plan.md)、[research.md](research.md)、[data-model.md](data-model.md)、[contracts](contracts/README.md)、[quickstart.md](quickstart.md)
**Created**: 2026-10-06
**Status**: I1/U1一致性修复已完成；Phase 1 T001-T017已实现并通过隔离验证，等待独立评审；T018-T104尚未开始。
**Structure**: 按用户指定的八个技术 Phase 组织；Phase 内以 `[US#]` 保留用户故事归属。Phase 1 为多故事共享基座，不加故事标签。

**Task Summary**: 104项，Phase 1的17项已勾选，87项待实现；31项标注可在前置满足后并行编写。Phase1–8分别为17/11/9/15/12/12/13/15项；基础17项，US1–US7标签分别为11/12/17/15/15/12/5项，共享覆盖另见追踪表。

## 执行约定

- 所有路径相对仓库根目录。新增文件使用下列精确路径；修改现有文件只扩展 013 必需边界。
- `- [ ] T### [P] [US#]` 是可执行任务；`[P]` 仅表示其已列先决任务完成后可与其他不同文件任务并行，不表示可跨过 Phase 闸口。同文件任务串行。
- 测试任务先于相应实现：先观察有效失败，再实现并通过；数据库写入、迁移和共享投影测试串行，使用隔离 PostgreSQL/Qdrant/data_root。
- 开始生产代码实施前，依宪法 Specification and Delivery Workflow §6 完成 `spec/plan/tasks` 一致性分析并解决阻断问题。评审清单见 [consolidation-review.md](checklists/consolidation-review.md)，标记由评审者维护，任务完成不自动勾选清单。
- 012 日志与六投影为唯一事实基座；005 检索状态机、006 maintenance 骨架继续复用。不增加 MCP 工具、自动晋升、014 工作包或 015 完整 UI。
- 新迁移预定 `0095_memory_consolidation_loop.py`；T001 复核实际 head。后续迁移任务在同一未部署的新 revision 上串行完善，已部署历史迁移不可修改。若实施时该 revision 已部署，新增后继 revision。
- 默认 `consolidation_enabled=false`、`link_expansion_enabled=false`；报告只给默认启用资格，不修改域策略。质量或证据不足保留能力并默认关闭；任何硬安全失败阻断发布。

## Phase 1: 审计与窗口基座

**Goal**: 建立可审计、可恢复的窗口与最小运行资格，使后续裁决/提交无需依赖尚未接线的自动触发入口。
**Stories**: US1、US2、US7 的共享基础。
**Independent Test**: 四态与过期/未完成/已消费排除、半开窗口、参考集分离、审计不可改、数据库活动资格唯一及旧 token 拒绝；不要求调用真实模型。

### 测试先行与契约

- [x] T001 复核 `backend/alembic/versions/0094_memory_management_audit.py` 与当前 Alembic head，核对 012 事件/六投影、AgentBase、maintenance 和上传复用入口，在 `specs/013-memory-consolidation-loop/quickstart.md` 固定隔离环境、升级起点与新增 revision 路径。
- [x] T002 [P] 在 `backend/tests/contract/test_consolidation_schemas.py` 建立四份 Draft202012 Schema 的正反例与本地引用校验，覆盖四 action、v1/v2 event、013.2完整/不完整报告与gate_binding、登记013.gate.1路径/hash/过期字段、未知权限字段及 finite confidence；使用 `specs/013-memory-consolidation-loop/contracts/*.schema.json`，依赖 T001。
- [x] T003 [P] 在 `backend/tests/unit/test_consolidation_policy.py` 先写严格策略测试：旧默认关闭、enabled 必须显式配置、所有 research §2 范围/bool/NaN 拒绝、候选阈值关系、独立记忆词表与内置档案治理，依赖 T001。
- [x] T004 [P] 在 `backend/tests/unit/test_consolidation_selection.py` 先写窗口四态表测试：仅 active 合格 episodic，quarantined/retired/superseded 均排除，叠加 expired/incomplete/consumed；参考集也排除非法状态且不混作提炼源，覆盖 start 含/end 不含、高水位及稳定排序，依赖 T001。
- [x] T005 [P] 在 `backend/tests/integration/test_013_consolidation_admission.py` 先写真实 PG 资格测试：两 scope 独立、同 scope 活动唯一、busy 返回已有 run、TTL120s/heartbeat20s、接管 generation、旧 token 不得提交或释放新资格，依赖 T001。
- [x] T006 [P] 在 `backend/tests/integration/test_013_consolidation_audit.py` 先写 `(run_id, observation_seq)` append-only、累计状态查询、未知用量为 null、7 天 TTL 与资格/永久事件分离测试；覆盖普通trigger/distiller_window与内部support_maintenance/deterministic_propagation合法组合，后者null窗口/空input_event_ids与独立历史来源/失效proof，依赖 T001。
- [x] T007 [P] 在 `backend/tests/integration/test_013_consolidation_migration.py` 先写非空 012 升级测试，覆盖旧 flat consolidate、evidence/chunk 与 supersedes 基础边、历史 revision、默认列值、新约束及存在 v2 事件时禁止破坏性 downgrade，依赖 T001。

### 共享实现

- [x] T008 在 `backend/src/rag_mcp/orchestration/consolidation_pipeline.py` 定义不可变 WindowSnapshot/SourceVersion/ProposalBatch/CurrentSnapshot/Decision/CommitOutcome/TrustedContext 接口和四段签名，区分 episode 输入、参考、支持、批内 output 引用、approved/committed/pending；显式distiller_window与仅可信writer支持钩子构造的deterministic_propagation权限边界，依赖 T002。
- [x] T009 在 `backend/src/rag_mcp/services/memory_policy.py`、`backend/src/rag_mcp/models/domain_profile.py` 与 `backend/src/rag_mcp/config/domain_profiles.py` 实现 research §2 严格配置、域中立版本化记忆词表字段及旧默认；保留文档 graph_relations 与内置档案权限边界，依赖 T003、T008。
- [x] T010 在 `backend/src/rag_mcp/models/consolidation_run.py` 定义可变 ConsolidationEligibility 与追加式 ConsolidationRunObservation，完整 token、单调版本、PK/索引、状态与 usage 字段分离；固化trigger/execution_context组合及维护历史来源/当前失效proof/null窗口/空新输入约束；`created_by_run` 不 FK 短期审计，依赖 T005、T006、T008。
- [x] T011 在 `backend/alembic/versions/0095_memory_consolidation_loop.py` 新增运行表、append-only/maintenance-only purge guards、活动资格部分唯一索引、域字段及 entry/link additive 列；回填旧 link 并建立 UNIQUE(scope,revision,from,to,relation_type)，保留 revision/node_key/data；在 `backend/src/rag_mcp/models/memory_link.py` 同步建立最小typed ORM映射、`backend/src/rag_mcp/models/memory_views.py` 保留re-export，在 `backend/src/rag_mcp/models/memory_projection.py` 接入 state/context/candidate/pointer 列，依赖 T007、T009、T010。
- [x] T012 在 `backend/src/rag_mcp/services/consolidation_runtime.py` 实现最小 admit/heartbeat/release/takeover 与提交 fence：scope→eligibility→writer lease→policy/targets/evidence 锁序、完整 token、live lease、锁后及最终发布前 `clock_timestamp()`、事务≤30s；普通distiller_window校验开关/配置，T060接入的可信支持维护仍复用同一资格/fence且只能通过专用proof校验；活动 DB 冲突明确 busy，不排队，依赖 T005、T011。
- [x] T013 在 `backend/src/rag_mcp/services/memory_reducer.py` 与 `backend/alembic/versions/0095_memory_consolidation_loop.py` 同步增加 `grant_type=consolidation_window` 的可信来源 guards、SQL/Python 重放及 window registry；封存窗口/源版本/参考/策略，不改变事实或消费输入，依赖 T008、T011、T012。
- [x] T014 在 `backend/src/rag_mcp/orchestration/consolidation_pipeline.py` 实现独立可测 select_window，从 verified complete manifest 的日志前缀取状态，按半开窗口/高水位/预算/稳定顺序选择及净化 episode 和独立参考/support 读集，不读取 pending 投影，依赖 T004、T008、T009、T013。
- [x] T015 在 `backend/tests/integration/test_013_consolidation_windows.py` 与 `backend/src/rag_mcp/services/consolidation_runtime.py` 先补长期窗口测试再实现可信 window seal/重试读取：原窗口与源版本永久可恢复、截断不重定义窗口、失败/全驳回不推进消费、checkpoint 前未处理反连接扫描；完成结果逻辑在 T042/T048 接齐，依赖 T013、T014。
- [x] T016 在 `backend/src/rag_mcp/services/consolidation_runtime.py` 接入追加观察及 ProviderUsageAccumulator：净化提案/理由、真实 transport 与缓存区分、actual/estimated/unavailable、未知 token/cost=null、资格取得/释放轨迹；不得修改旧观察，依赖 T006、T010、T012、T015。
- [x] T017 串行运行 T002–T007/T015 的契约、单元及隔离 PG 升级/窗口/资格/审计测试，修复失败并在 `specs/013-memory-consolidation-loop/quickstart.md` 登记命令及证据位置，依赖 T016。

**Checkpoint**: Phase 4 的提交资格/fencing 已就绪；尚未向用户暴露部分可写管线。

## Phase 2: 确定性裁决器

**Goal**: 所有 core/附件效果经过唯一纯函数批准，软提案无法直接或间接推翻 hard。
**Stories**: US3（P1）；US2 的确定性规则部分（P1）。
**Independent Test**: 无 DB/网络/系统时钟依赖的同输入同结果矩阵，以及 rejected 决定无 effects。

### US3 测试先行

- [ ] T018 [P] [US3] 在 `backend/tests/unit/test_consolidation_adjudicator.py` 先写 confidence 缺失/非有限/越界/等于下限/低于下限、source/target/support 跨域与最新状态、配额边界、断链/环/深度、缺失五元与永久源链的纯函数矩阵，依赖 T017。
- [ ] T019 [P] [US3] 在 `backend/tests/unit/test_consolidation_hard_protection.py` 先写 research §6 新软/新硬/人工三路径全 effect 矩阵：replace/invalidate/merge-hidden/缩短有效期/降级/传播，伪权限与硬锚 distilled 均拒绝，合法 trusted hard 替代/人工处置沿既有入口，依赖 T017。
- [ ] T020 [P] [US3] 在 `backend/tests/unit/test_consolidation_proposal_graph.py` 先写 proposal_id 唯一与 proposal_ref 拓扑测试：未知、自引、环、驳回输出不可用，临时输出只能来自已暂批 extract/distill；共享源/输出依赖同组、事件128上限整组拒绝，依赖 T017。
- [ ] T021 [P] [US2] 在 `backend/tests/unit/test_consolidation_deterministic_rules.py` 先写相同 clock/policy 的精确等价规则、元数据/证据/锚冲突、可证明纠正与不确定语义冲突拒绝测试，TTL 复用既有治理且禁用/无模型仍执行，依赖 T017。

### US3 / US2 实现

- [ ] T022 [US3] 在 `backend/src/rag_mcp/services/consolidation_adjudicator.py` 实现纯 adjudicate 与稳定 reason codes，输入不可变当前快照/显式 now/策略/词表/配额/可信上下文，输出逐 core/附件决定与证明；无 session、网络、LLM、隐式时钟且 reject 无 effects，依赖 T018、T019、T020。
- [ ] T023 [US3] 在 `backend/src/rag_mcp/services/consolidation_adjudicator.py` 实现全 effect 硬保护矩阵与 trusted command 校验，不从 confidence/频次/模型声称生成 hard 授权，保留原 hard confidence=NULL；自然既有 TTL 与软提案缩短期限分开，依赖 T019、T022。
- [ ] T024 [US3] 在 `backend/src/rag_mcp/services/consolidation_adjudicator.py` 实现源/目标/support 当前合法性、单指针无环 supersede、五元/永久 lineage、quota 累计占用与原始自评 confidence 校验，拒绝不足不驱逐、不补值/聚合/抬高置信度，依赖 T018、T023。
- [ ] T025 [US3] 在 `backend/src/rag_mcp/services/consolidation_adjudicator.py` 实现 core、link、context、candidate 分别裁决与仅复制获批 effects，代码确定 origin/proof；必要 corpus fact 锚生成 server-owned required_support，模型不得省略或伪造，依赖 T024。
- [ ] T026 [US3] 在 `backend/src/rag_mcp/services/consolidation_adjudicator.py` 实现同批拓扑/provisional snapshot 和原子连通组预计算，稳定 proposal_key/group_key 排除 run/request，精确计算 create/lifecycle/derive 数量并执行 max_events_per_group≤128、整组拒绝不消费，依赖 T020、T025。
- [ ] T027 [US2] 在 `backend/src/rag_mcp/orchestration/consolidation_pipeline.py` 实现独立于 LLM 的确定性去重/可证明归并/支持纠正提案与 TTL intents，规则 proof/version 由可信代码赋予，全部状态效果经 T022 的同一批准规则及既有治理，依赖 T021、T026。
- [ ] T028 [US3] 运行纯裁决/硬保护/拓扑/规则测试并检查导入边界，在 `backend/tests/unit/test_consolidation_adjudicator.py` 增加重复输入一致性与禁止 IO spy 的关键断言；接受/驳回均可定位规则且无旁路，依赖 T027。

**Checkpoint**: 裁决规则可独立验收；软推翻 hard=0，缺证据/链/归属/配额未通过生效=0。

## Phase 3: MemoryDistiller

**Goal**: 独立第四 Agent 只提供四类提案；模型与 Schema 故障保留确定性巩固。
**Story**: US2（P1），安全边界同时服务 US3。
**Independent Test**: 正常/无模型/超时/畸形输出的确定性结果一致，非法输出无 effect，Agent 无 writer 能力。

### US2 测试先行

- [ ] T029 [P] [US2] 在 `backend/tests/unit/agents/test_memory_distiller.py` 先写 AgentBase ROLE/NODE_SCHEMA/execute/fallback、四 action 与附件、域中立跨域声明提示、稳定 JSON 编码/版本与无变化 run/request payload 的测试，依赖 T028。
- [ ] T030 [P] [US2] 在 `backend/tests/unit/test_consolidation_fallback.py` 及 `backend/tests/integration/test_013_consolidation_llm_faults.py` 先写缺配置、None、429/500、连接失败、超时、错误JSON/未知 action/超量/缺字段、AgentBase fallback `{}` 再验证与 trusted 空包测试；增加阻塞底层调用的取消/超时在途槽保持、实际结束才释放、最多2真实调用及迟到结果拒绝断言；同 clock 下规则/TTL 对照，依赖 T028。
- [ ] T031 [P] [US2] 在 `backend/tests/unit/test_consolidation_injection_boundary.py` 先写正文/标题/tags/理由/context/keywords/link 描述角色伪造、JSON闭合、凭据、scope/权限/hard/策略/晋升指令攻击及 forbidden-writer spies；Schema 合法也不能授权，依赖 T028。

### US2 实现

- [ ] T032 [US2] 在 `backend/src/rag_mcp/agents/memory_distiller.py` 实现独立 AgentBase 第四子类与四提案 NODE_SCHEMA，精确采用 `contracts/distiller-output.schema.json`；只注入 LLMClient/只读数据，不持 session/MemoryService/治理/上传/工具执行句柄，不进入检索图，依赖 T029、T031。
- [ ] T033 [US2] 在 `backend/src/rag_mcp/config/domain_profiles.py` 配置沿 009 的受信任域中立 Distiller 提示与版本声明，正文/reference 放在 JSON untrusted_* 数据区、固定角色/控制指令，不使用领域硬编码或正文插值替换 system，依赖 T029、T032。
- [ ] T034 [US2] 在 `backend/src/rag_mcp/services/memory_validators.py` 扩展递归净化与 detect_submission 检查范围至全部新增输入/生成文本，复用 008/012 脱敏/注入分级，高风险生成效果拒绝/隔离且审计不存原凭据或跨域失败正文，依赖 T031、T033。
- [ ] T035 [US2] 在 `backend/src/rag_mcp/orchestration/consolidation_pipeline.py` 实现 propose 包验证与可观察降级：执行前保留确定性工作，整非法模型包丢弃，fallback 二次 Schema 校验仍失败时使用受信 `{proposals: []}`，区分模型成功和降级，依赖 T030、T032、T034。
- [ ] T036 [US2] 在 `backend/src/rag_mcp/services/consolidation_runtime.py` 实现同步 httpx LLM 的有界线程适配与 provider 信号量（真实在途调用上限2），超时/取消停止接纳新结果，底层调用尚未终止仍占槽、finally 实际结束才释放；不阻塞事件循环、不让迟到结果持 DB 会话或提交 token，依赖 T030、T035。
- [ ] T037 [US2] 运行 Agent/注入/降级与迟到结果测试，对 `backend/src/rag_mcp/agents/memory_distiller.py` 做 rg/AST/依赖调用路径审查并配合 runtime writer spies，将命令/允许命中解释/零直写证据要求记录于 `specs/013-memory-consolidation-loop/quickstart.md`，依赖 T036。

**Checkpoint**: provider/Schema 故障不会停止确定性规则；grep 证据配合调用路径与动态 spy，不只凭字符串未命中推定权限隔离。

## Phase 4: 生效与投影

**Goal**: 唯一批准后的可信服务追加事件并沿 012 发布；溯源/context/消费都能无模型重放。
**Stories**: US3、US2（P1），US5、US7（P2）。
**Independent Test**: relational/link/context 原子回滚、Qdrant/file pending 不可读且旧 complete 可读、SQL/Python 逐步一致、非空重建/rollback/TTL 后恢复。

### 测试先行

- [ ] T038 [P] [US3] 在 `backend/tests/integration/test_013_consolidation_commit.py` 先写提交 barrier 测试：propose 后 quarantine/retire/supersede/expire、scope/证据/策略/配额/词表变化、资格到期或 lease 丢失均重裁决；事件/关系/link/context 失败整组回滚、外部投影失败 pending 不报成功，依赖 T037。
- [ ] T039 [P] [US3] 在 `backend/tests/integration/test_013_consolidation_replay_parity.py` 先写 v1 与 v2 create/merge/invalidate/derive/control grant 的 Python/SQL 逐事件 parity、content→content_text 持久字段兼容、原始confidence/五元/非空源链、单aggregate/group 完整性测试，依赖 T037。
- [ ] T040 [P] [US7] 在 `backend/tests/integration/test_013_consolidation_recovery.py` 先写独立组部分完成、共享源整组 pending、稳定 group key 重试、审计 TTL 后恢复、checkpoint 不吞未成功源、rollback 新 state_event_id 允许合法重试测试，依赖 T037。
- [ ] T041 [P] [US5] 在 `backend/tests/unit/test_consolidation_context_visibility.py` 与 `backend/tests/integration/test_013_consolidation_projection_rebuild.py` 先写非空获批摘要/有序keywords/版本/来源的 full、snapshot+delta、TTL后重建、rollback 逐字段/六投影指纹一致和模型调用0；context有无正文hash/embedding输入/候选排序恒等，依赖 T037。

### US3 权威与提交

- [ ] T042 [US3] 在 `backend/src/rag_mcp/services/memory_reducer.py` 与 `backend/alembic/versions/0095_memory_consolidation_loop.py` 同步实现 v2 四 operation、group 完整性/唯一 root、六轴/永久批准材料、SQL `memory_log_state()`/source guards/verification receipt；纯 registry 只计算 potential outcomes/checkpoint，不读 manifest，v1旧事件保持兼容，依赖 T039。
- [ ] T043 [US3] 在 `backend/src/rag_mcp/services/memory_projection_store.py` 接入获批 relational/typed-link/context/candidate registries 的六投影物化/inspect/receipt，保留 revision 与旧完整 manifest；仅可信 reducer 产物可写，不建立第七事实源，依赖 T011、T041、T042。
- [ ] T044 [US3] 在 `backend/src/rag_mcp/services/memory_service.py` 实现 commit_approved：锁后读取最新状态并调用同一纯裁决器，分配永久ID/解析proposal_ref、可信组原子追加+关系/link/context物化+六投影验证/发布；提交前/最终发布前复验完整资格/lease，普通上下文复验当前开关/配置，T060接入的维护上下文复验可信来源/当前支持失效proof/仅invalidate白名单；raw/apply_event外部直写继续拒绝，依赖 T012、T026、T038、T042、T043。
- [ ] T045 [US3] 在 `backend/src/rag_mcp/services/memory_validators.py` 实现 distilled 五元与永久 episode/memory/create/state event/hash 链复验及012 content_text/submission_meta/provenance_validation/injection_flags/session/agent/task/decay/tags 时间字段 canonicalization；corpus证据可显式空但源链非空、推断保留且无候选，依赖 T034、T039、T044。

### US5 语境与可重建性

- [ ] T046 [US5] 在 `backend/src/rag_mcp/services/memory_service.py` 与 `backend/src/rag_mcp/services/memory_projection_store.py` 完成 context 逐附件批准、具体文本/有序keywords及版本永久事件存储与物化；derive 不改正文/hash/kind/provenance/证据/纠正链，模型故障或拒绝保留旧合法值，不凭 fallback 造摘要，依赖 T025、T041、T045。
- [ ] T047 [US5] 在 `backend/src/rag_mcp/runtime/projection_rebuild.py` 接齐 full/snapshot+delta 高级 link/context/候选/潜在消费 registry，从永久具体批准材料复制，清空非空投影与到期审计后恢复六投影/receipt，重建不调用模型且只在完整发布后开放消费，依赖 T041、T046。

### US2 / US7 接线与恢复

- [ ] T048 [US7] 在 `backend/src/rag_mcp/services/consolidation_runtime.py` 与 `backend/src/rag_mcp/services/memory_service.py` 实现完整组 pending 恢复与 verified complete 前缀消费判定，先取得新资格并重验保护、保留原窗口/未处理反连接与未消费源；audit TTL 后从永久window/结果恢复，不重复产出或强行批准已失效旧结果，依赖 T040、T044、T047。
- [ ] T049 [US2] 在 `backend/src/rag_mcp/orchestration/consolidation_pipeline.py` 接通 select→propose→adjudicate→commit 四段，彼此注入独立可测边界；运行外持LLM、事务内重裁决、只传获批 effects，所有成功/降级/无变化/部分失败路径有明确结果，依赖 T027、T035、T044、T045、T048。
- [ ] T050 [US7] 在 `backend/src/rag_mcp/services/consolidation_runtime.py` 从真实决定/发布结果追加累计观察，accepted≠committed，output IDs 仅 complete、pending另列，empty/all_rejected/partial/interrupted 与实际 usage/reason 可区分，不 UPDATE旧状态，依赖 T016、T049。
- [ ] T051 [US3] 在 `backend/src/rag_mcp/services/memory_reducer.py`、`backend/src/rag_mcp/services/memory_governance.py` 与新迁移补齐 rollback 的 registry/content/history 恢复，受影响 entry 的 state_event_id=rollback_event_id、creation身份不变、历史group键不删，恢复结果可合法重试，依赖 T040、T042、T048、T050。
- [ ] T052 [US3] 串行运行 commit/parity/recovery/非空 rebuild/context 测试与 populated012升级测试，验证 quarantined 提交再排除点、源链100%、pending不可读、同组幂等与LLM重建0；在 `specs/013-memory-consolidation-loop/quickstart.md` 记录阶段证据，依赖 T051。

**Checkpoint**: 手动内测完整管线可验收，正式自动入口尚未开放；高级关系词表/消费端在下一 Phase 接齐。

## Phase 5: 类型化链接图

**Goal**: 投影③高级类型化边可裁决/重建，GEM C3 依赖失效可持续处理，召回增强默认关。
**Story**: US5（P2）。
**Independent Test**: revision内唯一、旧基础边兼容、词表/方向复验、live/history/association 区分、无新episode传播、默认旧召回和context排序不变。

### US5 测试先行

- [ ] T053 [P] [US5] 在 `backend/tests/unit/test_consolidation_links.py` 先写裸键宽模式+当前独立记忆词表、kind/方向/category/proof、非法自环/跨域/重复边、llm_proposed不升权及012 evidence/supersedes空词表兼容测试，依赖 T052。
- [ ] T054 [P] [US5] 在 `backend/tests/integration/test_013_consolidation_dependencies.py` 先写必要支持撤销/live逆向传播、历史episode正常merge/TTL/purge不误伤、普通关联不传播、环/高扇出32深128节点frontier恢复、无新episode/null-window纯invalidate与hard被保护且有审计测试；主开关关闭/普通配置缺失时仅可信必要支持维护可取得同一scope资格，普通触发仍拒绝、REST/模型伪造上下文无效、create/merge/link/context/candidate与源消费均0、Distiller调用0；竞争busy、lease/token失效及支持proof变更仍拒绝提交，依赖 T052。
- [ ] T055 [P] [US5] 在 `backend/tests/contract/test_consolidation_recall_extensions.py`、`backend/tests/unit/test_consolidation_link_expansion.py` 与 `backend/tests/unit/test_consolidation_gate.py` 先写 StrictBool flags缺省/单独/组合、旧响应字段/排序兼容、客户opt-in+域策略+版本绑定三闸、端点过滤/预算/降级及只读reader测试；按gate-proof契约覆盖登记缺省/撤销/同mtime篡改、固定hash/过期/错scope/错variant/旧绑定、非法路径/JSON/超限与100ms IO预算，原直接结果仍可用；指纹覆盖013产出/rebuild不自失效、普通源/治理/rollback/promotion及published证据变化失效、reader不导入eval/无写句柄，依赖 T052。

### US5 实现

- [ ] T056 [US5] 在 `backend/src/rag_mcp/models/memory_link.py` 完善T011已建立的typed映射与高级字段约束，`backend/src/rag_mcp/models/memory_views.py` 保持re-export；在 `backend/alembic/versions/0095_memory_consolidation_loop.py` 验证回填/to_kind及物理 UNIQUE(scope,revision,from,to,relation_type)，基础evidence指chunk不能全加memory FK、created_by_run无审计cascade，依赖 T011、T053。
- [ ] T057 [US5] 在 `backend/src/rag_mcp/models/domain_profile.py`、`backend/src/rag_mcp/config/domain_profiles.py` 与 `backend/src/rag_mcp/services/domain_profile_service.py` 接齐词表校验/版本化与合法管理边界，空默认、基础边保留、文档图不自动启用，依赖 T009、T053、T056。
- [ ] T058 [US5] 在 `backend/src/rag_mcp/services/consolidation_adjudicator.py`、`backend/src/rag_mcp/services/memory_projection_store.py` 与新迁移完善高级link逐附件裁决/typed-data-authority parity guards，提交复验当前成员/方向/语义，两端合法同域、模型关系永久llm_proposed、deterministic须代码proof，依赖 T025、T043、T053、T057。
- [ ] T059 [US5] 在 `backend/src/rag_mcp/orchestration/consolidation_pipeline.py` 实现独立 deterministic_propagation：无新episode也可用永久historical lineage、可信trigger/proof、window=null，仅invalidate且不调用Distiller/不消费新源；禁止create/merge/link/context/candidate，维护身份/历史来源与新提炼输入分开审计；固定captured语义、visited/depth/frontier/continuation_key，依赖 T054、T058。
- [ ] T060 [US5] 在 `backend/src/rag_mcp/services/memory_reducer.py`、`backend/src/rag_mcp/services/memory_validators.py` 与新迁移实现 required_support、传播registry与 `consolidation_propagation` 控制grant；在 `backend/src/rag_mcp/services/consolidation_runtime.py` 与 `backend/src/rag_mcp/services/memory_service.py` 接入仅可信writer维护/治理支持钩子和当前必要支持proof可授权的admission/commit上下文，关闭主开关/缺普通配置仍取得同一scope资格并完整lease/token fence，仅invalidate、禁止create/merge/link/context/candidate/源消费，不放宽普通触发门控；无effect frontier永久继续，状态变化仍同裁决/event/六投影发布，读取先过滤失效支持，依赖 T025、T054、T059。
- [ ] T061 [US5] 在 `backend/src/rag_mcp/config/__init__.py` 接入默认None的CONSOLIDATION_GATE_REGISTRY_PATH，在 `backend/src/rag_mcp/services/consolidation_gate.py` 实现gate-proof只读登记加载、共享纯报告/绑定校验与源材料data_hash/代码/配置指纹；在 `backend/src/rag_mcp/services/memory_reader.py` 实现默认关扩展，验证部署路径/报告字节hash/有效期、entry-report-current全绑定与candidate_expansion三闸、客户opt-in与域许可；缓存不保留授权，坏证明/撤销/旧绑定立即不授权、IO有界非阻塞且≤100ms计入原预算；合法节点逐项同域/active/complete/valid/support复验，失效支持立即过滤、增强失败保留合法直接结果且不增旧3秒/50条/内容预算，backend不导入eval，依赖 T055、T058、T060。
- [ ] T062 [US5] 在 `backend/src/rag_mcp/mcp/recall_memory.py` 与 `backend/src/rag_mcp/services/memory_service.py` 发布 additive v2 flags/透传和可选enhancement响应，旧调用不添字段；不改三历史知识工具schema、不加检索节点，依赖 T055、T061。
- [ ] T063 [US5] 在 `backend/src/rag_mcp/services/memory_reader.py` 实现 include_context 仅最终selected后按剩余预算展示，不能挤掉已选记忆，不进embedding/改写/候选/过滤/排序/RRF；无合法版本省略并返回明确状态，读取不现场调用LLM，依赖 T041、T046、T062。
- [ ] T064 [US5] 串行运行link/dependency/recall/context与非空rebuild/rollback测试，在 `backend/tests/integration/test_013_consolidation_projection_rebuild.py` 补高级typed边迁移历史revision/审计TTL后恢复证据，验证旧基础边和默认关旧客户端行为，依赖 T047、T056、T060、T063。

**Checkpoint**: 只有live/必要支持边参与生命周期传播；正式增强仍需后续真实三闸证据，隔离评测可明确启用候选扩展。

## Phase 6: 知识候选与人工晋升

**Goal**: 候选只标记；writer人工动作复用上传摄入并保留稳定任务与原记忆。
**Story**: US6（P2）。
**Independent Test**: 自动知识source创建0、合法候选归因、显式晋升、同版本幂等、崩溃恢复/失败重试、未发布不报published。

### US6 测试先行

- [ ] T065 [P] [US6] 在 `backend/tests/unit/test_consolidation_candidates.py` 先写active semantic/≥0.95策略阈值/同域published硬锚逐条位置内容归因、candidate_version、无锚procedure与硬锚distilled不升hard、失效后不可晋升测试，依赖 T064。
- [ ] T066 [P] [US6] 在 `backend/tests/contract/test_consolidation_management_api.py` 先写候选列表/POST promote/GET promotions 的writer-only、scope/version/reason/extra-forbid、202首次/200重复、404跨域、409失效、503写不可用契约，依赖 T064。
- [ ] T067 [P] [US6] 在 `backend/tests/integration/test_013_consolidation_promotion.py` 先写巩固/维护/量阈值自动source=0、原记忆保留、并发重复只一task/source/initial pending run、注册/调度崩溃恢复、显式重试同task/source与新attempt、未发布状态及上传旧流程兼容测试，依赖 T064。

### US6 实现

- [ ] T068 [US6] 在 `backend/src/rag_mcp/services/consolidation_adjudicator.py` 与 `backend/src/rag_mcp/services/memory_service.py` 实现候选附件批准与promote_candidate_at/version/basis派生，必要锚归因复验且不改provenance，不调用upload/ingestion；拒绝标记有审计无effect，依赖 T065、T067。
- [ ] T069 [US6] 在 `backend/src/rag_mcp/services/knowledge_source_registration.py` 抽取受净化内容→稳定raw文件→uploaded KnowledgeSource→预建pending ProcessingRun 的必要共享注册步骤，并令 `backend/src/rag_mcp/api/knowledge_sources.py` 复用，保留现有上传/版本发布/清理行为、不HTTP自调用，依赖 T067、T068。
- [ ] T070 [US6] 在 `backend/src/rag_mcp/services/ingestion_service.py` 支持校验使用预建同source/scope pending ProcessingRun，不再生成第二初始run；existing失败重试可增加attempt但不增加稳定晋升task/source，依赖 T067、T069。
- [ ] T071 [US6] 在 `backend/src/rag_mcp/services/memory_reducer.py`、`backend/src/rag_mcp/services/memory_projection_store.py` 与新迁移同步实现永久promotion_requested/observed管理grant与唯一(scope,memory,candidate_version)，stable task_id=request grant event_id、source/initial run/后续attempt/version/result指针可重放，依赖 T042、T067、T070。
- [ ] T072 [US6] 在 `backend/src/rag_mcp/services/memory_governance.py` 实现显式人工晋升短事务：current writer/actor/reason/scope/candidate/anchors重验，共享注册与pointer同事务、提交后调度；唯一冲突返原task/source/initial run不重调度，新正文/source/task/status权限不由请求提供，依赖 T068、T069、T070、T071。
- [ ] T073 [US6] 在 `backend/src/rag_mcp/api/memory.py` 实现候选列表、promote与promotions报告路由和当前promotable复验，复用require_writer/live lease、明确实际状态、原记忆保留、跨域404；不注册MCP晋升入口，依赖 T066、T072。
- [ ] T074 [US6] 在 `backend/src/rag_mcp/api/knowledge_sources.py` 与 `backend/src/rag_mcp/services/memory_governance.py` 将既有显式reprocess/真实publication结果追加promotion_observed，uploaded/processing/failed不报published，记忆rollback保留外部知识动作历史不声称撤销出版，依赖 T070、T071、T073。
- [ ] T075 [US6] 在 `backend/src/rag_mcp/services/maintenance_service.py` 恢复仅已有人为授权pointer的未调度任务，调度前复验候选/scope，失效记失败；同stable task/source恢复，不为候选自动创建新请求，依赖 T072、T074。
- [ ] T076 [US6] 串行运行候选/API/人工晋升故障与旧上传兼容测试，检查任务/attempt区分和自动正身0，清理到期run后重建候选/指针，在 `specs/013-memory-consolidation-loop/quickstart.md` 登记晋升证据，依赖 T075。

**Checkpoint**: 只有人工管理请求可创建稳定晋升任务；候选、知识source摄入与published三个阶段分别可查。

## Phase 7: 触发与并发

**Goal**: 在已有资格/fence/模型适配上接线三触发、报告与维护；运行与真实供应商调用均有界。
**Stories**: US1（P1）、US7（P2）。
**Independent Test**: 三触发同scope竞争明确busy、不同scope受全局容量约束、reader拒绝、自动idle/volume仅离线、前台等待0、迟到调用仍占provider槽。

### US1 / US7 测试先行

- [ ] T077 [P] [US1] 在 `backend/tests/contract/test_consolidation_run_api.py` 先写POST consolidation短admission 202/window=null/execution_context=distiller_window、disabled/config-required/busy+run_id/scope-write-busy/capacity/write-unavailable及GET list/detail/history/TTL 410证明与跨域404契约；REST携带support_maintenance/execution_context/propagation/proof等未知控制字段必须拒绝，内部维护报告标明历史来源/失效依据且新输入为空，依赖 T076。
- [ ] T078 [P] [US1] 在 `backend/tests/integration/test_013_consolidation_triggers.py` 先写手动/idle/volume共用DB admission竞争、自动前台/摄入/重建活跃跳过、阈值只提示且维护重验、busy不排队、两scope独立、空窗口与全部驳回释放测试，依赖 T076。
- [ ] T079 [P] [US1] 在 `backend/tests/integration/test_013_consolidation_concurrency.py` 先写scope worker≤2/provider真实调用≤2、timeout底层仍在途占槽、异常/取消最终释放、generation接管/旧任务晚到提交0与释放新资格0测试，依赖 T076。
- [ ] T080 [P] [US1] 在 `backend/tests/integration/test_013_consolidation_foreground.py` 先写巩固期间search/recall/record/start_work原预算与调用路径测试，前台同步等待/调用Distiller=0、reader新管理入口无写、request activity最终归零，依赖 T076。

### US1 / US7 实现

- [ ] T081 [US1] 在 `backend/src/rag_mcp/services/consolidation_runtime.py` 实现最多2个scope后台任务的接纳/独立session/总期限300s/取消与shutdown回收；接入T036 provider信号量、区分worker与真实在途调用，容量满明确拒绝不保留队列，所有完成/失败路径追加审计并匹配token释放，依赖 T012、T036、T049、T079。
- [ ] T082 [US1] 在 `backend/src/rag_mcp/server.py` 接入常数时间前台活动计数/最后活动时间、摄入/重建活动状态与有界runtime生命周期，HTTP/MCP异常也释放活动计数，未取得writer lease不运行新管理控制，依赖 T080、T081。
- [ ] T083 [US1] 在 `backend/src/rag_mcp/services/memory_service.py` 仅在既有记忆写入完成后发送量阈值离线检查提示，不在前台选窗口/调用模型/启动等待任务；维护对当前eligible pending count重验，busy提示不能变持久运行队列，依赖 T078、T082。
- [ ] T084 [US1] 在 `backend/src/rag_mcp/services/maintenance_service.py` 接入idle/volume统一admission：先执行既有TTL/recovery/purge，再核验当前writer/idle_seconds/前台和摄入重建活动/真实阈值/域门控；自动跳过有原因，必要support维护走T059/T060窄权限路径，由可信钩子构造support_maintenance上下文，关闭时仍执行但共用资格/lease/fence/容量且不伪装普通触发，依赖 T060、T075、T078、T081、T083。
- [ ] T085 [US1] 在 `backend/src/rag_mcp/api/memory.py` 接入手动POST与运行list/detail/history，短事务资格+admitted审计后后台执行，明确scope/require_writer/live lease；只返回同域净化报告，TTL410仅有长期身份证明时返回，否则404，依赖 T050、T073、T077、T081、T084。
- [ ] T086 [US7] 在 `backend/src/rag_mcp/services/maintenance_service.py` 接入默认7天审计TTL到期清理与RuntimeMaintenanceLog，维护角色/DB guard校验，不能删永久authority/有效link或释放仍active资格；报告usage含真实计量/估计/缺失，依赖 T006、T016、T085。
- [ ] T087 [US1] 在 `backend/src/rag_mcp/services/consolidation_runtime.py` 接齐lease丢失、总超时、进程中断与过期资格恢复的终态观察及fenced接管；当前token心跳不复活过期资格，恢复原run仍须新独占资格，迟到模型结果无效，依赖 T048、T079、T081、T086。
- [ ] T088 [US1] 串行运行三触发/容量/前台/reader/资格竞争集成测试，将真实触发、忙碌、接管与零同步等待证据记入 `specs/013-memory-consolidation-loop/quickstart.md`，依赖 T087。
- [ ] T089 [US7] 在 `backend/tests/integration/test_013_consolidation_audit.py` 补真实端到端正常/空/全拒绝/降级/部分/失败/中断与usage报告、append-only和TTL后来源可解释性验收；涵盖关闭时support_maintenance/deterministic_propagation报告、null窗口/空新输入/完整历史来源及proof，确认每受理run都有轨迹且counts与实际权威发布一致，依赖 T050、T085、T086、T088。

**Checkpoint**: US1 与 US7 管理工作流完整，可合法opt-in内测；正式默认开启与链接增强资格待 Phase 8。

## Phase 8: 受益闸门与验收

**Goal**: 用冻结真实子集和两轮缓存获得可复现质量/安全/回归证据；报告不发布策略。
**Story**: US4（P1）；验收覆盖 US1–US7。
**Independent Test**: passed/failed/incomplete各分支、双指标≥3%且三非降、缺缓存不回源不误过闸、安全失败阻断、012八项/全部旧集不降。

### US4 测试与证据先行

- [ ] T090 [P] [US4] 在 `backend/tests/unit/test_consolidation_comparison_report.py` 先写distinct同scope六query与2+2+2/两提炼kind、真实非空labels、二元MRR/nDCG物理rank/重复alias gain0、宏平均K5/缺位0、零baseline不可计算、双3%AND/三非降、三闸和incomplete空/null观测测试；013.2 passed必须完整gate_binding、环境同字段一致、跨scope/旧绑定/direct授权扩展均拒绝，runner与T061共享纯语义validator，依赖 T089。
- [ ] T091 [P] [US4] 在 `backend/tests/unit/test_consolidation_eval_replay.py` 先写原(model,system,user)稳定key、首轮成功/失败缓存、重放原始未巩固snapshot、miss/corrupt/version mismatch不gap-fill、仅LLM transport阻断/计数、非延迟≤1%与安全零容差、usage未知null/重放额外LLM0及输出拒覆盖测试，依赖 T089。
- [ ] T092 [P] [US4] 在 `backend/tests/integration/test_013_consolidation_e2e.py` 先建立六类真实E2E：批量提炼、确定性归并/纠正、软推翻hard拒绝+审计、模型/Schema故障降级、闸门失败/通过控制、候选人工晋升；引用已有阶段fixture，不以预置pass代替真实观测，依赖 T089。
- [ ] T093 [P] [US4] 在 `backend/tests/integration/test_013_consolidation_aoep.py` 先建立权威边界/范围不扩张/来源保留/删除传播/可追溯rollback五不变量各≥2例，覆盖quarantined双排除、旧holder0、无新episode传播、非空派生/TTL后重建且模型0，依赖 T089。
- [ ] T094 [US4] 在 `backend/tests/conftest.py` 接入CONSOLIDATION_EVIDENCE_DIR的013证据fixture，导出真实nodeid/scenario/资格/事件/manifest/硬计数/transport trace与可复原authority snapshot/DomainProfile/policy/published证据/冻结clock，脱敏同域并拒覆盖，复用 `eval/memory_pytest_evidence.py` 原012证据口径，依赖 T090、T091、T092、T093。

### US4 评测实现与真实验收

- [ ] T095 [US4] 创建 `eval/consolidation_eval_dataset.json`，按evaluation-contract六覆盖槽绑定实际可定位语料/事件/位置与非空expected content+合法lineage+validity等价组，冻结distinct query主类2+2+2、semantic/procedural各1、snapshot/clock/model/prompt/schema/policy/vocabulary/recall/budget/K/variant版本；先validator后真实provider调用，依赖 T090、T094。
- [ ] T096 [US4] 在 `eval/consolidation_eval_support.py` 实现数据/快照/等价lineage合法性与二元相关性adapter，沿 `eval/run_eval.py` MRR/nDCG函数，保留物理rank/重复alias零gain；baseline/direct/isolated candidate扩展三路分别报逐query/宏平均/延迟/成本，不隐藏direct回退，依赖 T090、T095。
- [ ] T097 [US4] 在 `eval/run_consolidation_comparison.py` 实现契约CLI与隔离snapshot还原/record/replay，每轮从原始未巩固authority开始；沿AGENTIC_LLM_CACHE_PATH精确keys和sidecar manifest，仅LLM provider transport deny/count，成功/失败全重放、缺证据不回源；unique output/manifest、preflight incomplete及退出0/1/2，依赖 T091、T094、T096。
- [ ] T098 [US4] 在 `eval/consolidation_eval_support.py` 复用T061的backend纯报告/绑定/数据材料校验，接入benefit-report 013.2结构+语义、双相对3%AND/HitRate-Recall-Precision非降/可计算基线、cache响应100%/真实模型network0/非延迟≤1%、安全零容差/源链100%/实际E2E与旧全集证据核验；完整enabled目标policy先冻结，三path不改其身份，报告环境/全部query/current绑定一致，缺失观测null不伪造0，仅给default_enable_eligible、不安装登记或写policy，依赖 T090、T091、T097。
- [ ] T099 [US4] 串行运行六类013E2E、AOEP各≥2、故障/资格/依赖/晋升/非空重建全部测试，使用 `backend/tests/integration/test_013_consolidation_e2e.py`、`test_013_consolidation_aoep.py`、`test_013_consolidation_llm_faults.py` 与T094fixture生成真实trace/snapshot；失败修复后才进入受益验收，依赖 T094、T098。
- [ ] T100 [US4] 按原口径重跑 `backend/tests/integration/test_012_memory_e2e.py` 八项和 `test_012_aoep_obligations.py`，沿 `eval/run_memory_acceptance.py` 生成新的012 acceptance证据；硬锚/无锚/跨域/supersede/注入/TTL配额/reader/会话八项不删改，skip/missing不计pass，依赖 T099。
- [ ] T101 [US4] 按 `specs/012-memory-foundation-write-read-loop/quickstart.md`、`eval/README.md` 重跑backend全集、`eval/run_regression_011.py`及001–012其余组/target-host/旧frontend checks，保存新证据；核对三历史知识工具及旧客户端默认召回/预算/超时兼容，单一regression summary不得代表所有旧集，依赖 T100。
- [ ] T102 [US4] 执行 `eval/run_consolidation_comparison.py` 同环境record→replay两轮，使用冻结≥6真实子集与T099–T101证据、独立还原副本、AGENTIC_LLM_CACHE_PATH及unique report；验证两指标≥3%、三非降、成功/失败缓存100%、真实模型network0、非延迟漂移≤1%；质量不足如实failed/incomplete保留默认关报告，依赖 T095、T098、T101。
- [ ] T103 [US4] 用 `specs/013-memory-consolidation-loop/contracts/benefit-report.schema.json`、`gate-registry.schema.json` 和共享backend validator校验最终record/replay报告及失败分支，核对版本/指纹/来源/成本/缓存/硬指标/覆盖/三闸，安全失败阻断；真实candidate_expansion报告passed且当前绑定匹配时，仅在隔离验收目录按gate-proof模拟部署者原子安装报告+固定hash/绑定/有效期登记，用T061 reader证明合法增强以及撤销/篡改/过期/变更即不授权。真实failed/incomplete或仅direct通过时验证不安装扩展许可、拒绝授权/合法直召回/默认关闭，保留实际结论；正向加载逻辑仍由T055明确fixture覆盖，不伪造真实过闸。所有分支保留机器证据，runner不自动登记或改域策略/管理员选择，依赖 T061、T102。
- [ ] T104 [US4] 更新 `specs/013-memory-consolidation-loop/quickstart.md` 与 `eval/README.md` 为实际可执行命令/测试路径/新证据索引，记录部署登记的人工安装/配置/撤销与当前绑定失效验证、关闭时窄权限支持维护，完成Distiller rg/AST+spy、默认关、无直写与无自动晋升的最终复核，登记环境限制与质量/安全/回归实际结论；不得将规划/Schema通过写作功能验收通过，依赖 T037、T064、T076、T089、T103。

**Checkpoint**: 全三闸实际通过才具备默认启用资格；质量不达标是可验收的默认关闭分支，硬安全失败必须修复，证据不完整不能声称实现验收通过。

## Dependencies & Execution Order

### Phase 依赖

| Phase | 必需前置 | 可独立观察的完成界面 |
|---|---|---|
| 1 审计/窗口 | 一致性分析、T001复核012基线 | 资格/fence、window/审计与旧库升级 |
| 2 裁决 | Phase 1 / T017 | 纯规则矩阵，无IO批准边界 |
| 3 Distiller | Phase 2 / T028 | Agent/Schema/降级/权限隔离 |
| 4 生效/投影 | Phase 3 / T037；尤其T012/T013/T026 | 事件组、再裁决、六投影与恢复 |
| 5 链接 | Phase 4 / T052 | 高级边、依赖维护、只读增强 |
| 6 晋升 | Phase 5 / T064 | 候选与人工稳定摄入任务 |
| 7 触发 | Phase 6 / T076；复用T012/T036/T049 | 三触发/报告/并发/TTL |
| 8 闸门 | Phase 7 / T089 | 真实受益、安全与完整旧集证据 |

关键链为 `T012 → T013 → T014/T015 → T017 → T028 → T037 → T042/T043 → T044 → T048/T049 → T052 → T064 → T076 → T089 → T098 → T099/T100/T101 → T102/T103/T104`。Phase 4 不依赖 Phase 7；Phase 7 接入已完成的资格/提交基础，避免循环。所有任务列出的直接依赖均指向较小ID。

### 用户故事与独立验收

| Story / Priority | 主要任务 | 独立验收与完成时点 |
|---|---|---|
| US1 在工作之外安全启动巩固 / P1 | T005/T012、T077–T088（除T086） | 三触发/忙碌/两scope/reader/前台0等待/失效token0；Phase7 |
| US2 提炼经验并在模型故障时继续整理 / P1 | T004/T014/T015、T021/T027、T029–T037、T049 | 四action、合法episode与独立参考、同clock故障规则一致；Phase4，触发集成Phase7 |
| US3 每项变化可审计裁决 / P1 | T018–T020/T022–T026/T028、T038/T039/T042–T045/T051/T052 | 纯矩阵、hard0、提交再排除、原子发布/源链；Phase4 |
| US4 固定对照决定默认开启 / P1 | T090–T104 | frozen≥6、双3%AND/三非降/strict replay/三闸；Phase8 |
| US5 可重建关联与语境 / P2 | T041/T046/T047、T053–T064 | typed边、live/history、非空无LLM重建、context恒等、默认增强关；Phase5 |
| US6 人工候选摄入 / P2 | T065–T076 | 自动source0、人工同域归因、stable task幂等/失败恢复；Phase6 |
| US7 成本裁决失败轨迹 / P2 | T006/T010/T016、T040/T048/T050、T086/T089 | 每受理run可查、accepted≠committed、append-only、TTL后永久材料在；Phase7 |

故事共享 authority/资格前置；独立验收通过注入只读快照、可控模型或合法管理请求完成，不虚称故事之间完全无依赖。P2 部件按用户技术Phase参与P1发布验收，不擅自移除。

### 并行执行示例

只在表内前置满足后并行编写不同测试文件；真实数据库/共享存储执行串行。未标 `[P]` 的同模块实现按ID串行，特别是reducer/新migration/MemoryService/runtime/API。

| Story | 前置 | 可并行任务示例 |
|---|---|---|
| US1 | T076 | T077 API契约、T078触发场景、T079并发、T080前台 |
| US2 | T028 | T029 Agent、T030故障、T031注入隔离 |
| US3 | T017 | T018裁决、T019硬保护、T020批内引用图 |
| US4 | T089 | T090指标、T091重放、T092六E2E、T093 AOEP |
| US5 | T052 | T053边规则、T054依赖、T055召回契约 |
| US6 | T064 | T065候选、T066管理契约、T067晋升故障 |
| US7 | T001 | T005资格与T006审计测试（不同文件；DB运行串行） |

## Requirement Traceability

### Functional Requirements

| ID | 实现/主要验收任务 |
|---|---|
| FR-001 | T078/T080–T085/T088 |
| FR-002 | T003/T009/T012/T054/T059/T060/T066/T073/T077/T082/T084/T085 |
| FR-003 | T005/T010–T012/T038/T079/T081/T087/T088 |
| FR-004 | T004/T013–T015/T017/T038 |
| FR-005 | T013/T015/T040/T042/T048/T051/T052 |
| FR-006 | T003/T009/T020/T026/T036/T079/T081/T095 |
| FR-007 | T029/T031–T033/T037/T080 |
| FR-008 | T002/T018/T029/T030/T032/T035 |
| FR-009 | T031/T033/T034/T037/T045/T058/T092/T093 |
| FR-010 | T021/T027/T030/T035/T036/T037/T084/T099 |
| FR-011 | T022–T026/T038/T044/T049/T058/T068 |
| FR-012 | T018/T020/T024/T026/T038/T044/T045/T058 |
| FR-013 | T019/T023/T038/T054/T060/T092/T099 |
| FR-014 | T018/T024/T039/T045/T052/T065/T093 |
| FR-015 | T021/T023/T039/T042/T044/T051/T054 |
| FR-016 | T038/T039/T042–T044/T046/T052 |
| FR-017 | T006/T027/T038/T048–T050/T084/T089 |
| FR-018 | T007/T011/T053/T056–T058/T064 |
| FR-019 | T025/T053/T057/T058/T064 |
| FR-020 | T025/T054/T059–T061/T064/T093 |
| FR-021 | T055/T061/T062/T096/T103 |
| FR-022 | T031/T034/T041/T046/T063/T064 |
| FR-023 | T039/T041–T043/T047/T051/T056/T064/T093 |
| FR-024 | T025/T065/T068/T073/T076 |
| FR-025 | T031/T066/T067/T072/T073/T075/T076 |
| FR-026 | T067/T069–T076 |
| FR-027 | T006/T010/T011/T016/T050/T085/T089 |
| FR-028 | T016/T030/T050/T077/T085/T089/T098 |
| FR-029 | T006/T040/T047/T064/T071/T076/T086/T089 |
| FR-030 | T090/T094–T096/T102 |
| FR-031 | T091/T095–T098/T102/T103 |
| FR-032 | T009/T061/T090/T098/T102–T104 |
| FR-033 | T038–T041/T054/T067/T078/T079/T092–T094/T099 |
| FR-034 | T100/T101/T103/T104 |
| FR-035 | T055/T061–T063/T077/T080/T091/T094/T097/T098/T101–T104 |

### Success Criteria

| ID | 判定证据/主要验收任务 |
|---|---|
| SC-001 | T090/T091/T095–T098/T102/T103：双3%AND、三非降、缓存100%/network0、三闸 |
| SC-002 | T005/T012/T038/T066/T079/T081/T085/T087/T088：三触发、reader/旧holder0、互斥 |
| SC-003 | T004/T014/T015/T031/T034/T038/T045/T054/T061/T093：双排除/源参考/跨域/控制0 |
| SC-004 | T021/T027/T030/T035–T037/T092/T099：故障正常确定性一致、降级可查 |
| SC-005 | T018–T026/T038/T044/T052/T092/T099：hard0、阈值/链/配额/批准依据 |
| SC-006 | T024/T039/T045/T052/T065/T068/T093：五元/源链100%、无虚构锚/升权 |
| SC-007 | T007/T041/T047/T051/T053/T056–T058/T064：有效唯一、非空无模型重建100% |
| SC-008 | T041/T046/T054/T059–T061/T063/T064：context事实/排序恒等、依赖不误伤 |
| SC-009 | T065–T076/T092/T099：自动正身0、人工轨迹/原记忆100%、稳定任务 |
| SC-010 | T006/T016/T040/T050/T085/T086/T089：报告100%、TTL长期材料无损 |
| SC-011 | T038–T044/T048–T052/T093/T099：失败不成功、pending不读、恢复幂等 |
| SC-012 | T036/T055/T061–T063/T078–T083/T088/T101：前台等待0、旧预算/直接召回兼容 |
| SC-013 | T092–T094/T099–T104：六新E2E、012八项、AOEP各≥2、旧全集/host |

### Contracts 与证据入口

| 材料 | 任务 |
|---|---|
| distiller-output.schema.json | T002/T008/T020/T029/T032/T035 |
| consolidate-event.schema.json | T002/T013/T039/T042/T044/T045/T059/T060/T071 |
| pipeline-contract.md | T008/T012–T016/T022–T027/T035/T036/T044/T048/T049/T081/T087 |
| management-api.md | T066/T072–T077/T081/T085/T089 |
| recall-extensions.md | T055/T061–T064 |
| benefit-report.schema.json / evaluation-contract.md | T002/T090/T091/T094–T098/T102/T103 |
| gate-registry.schema.json / gate-proof.md | T002/T055/T061/T090/T098/T103/T104 |
| quickstart.md | T001/T017/T037/T052/T076/T088/T099–T104 |
| review CHK003 / CHK034 证据明确性 | T031/T037/T104 无直写；T036/T079/T081 在途provider信号量 |

## Implementation Strategy

1. 完成一致性分析后实施 Phase1–3，获得可单测的资格/选择/纯裁决/只读Agent；保持两个默认开关关闭，不开放半成品写API。
2. Phase4 完成安全核心增量：仅隔离内测或受控内部调用验证完整事件与投影链。US1 管理MVP需继续接齐Phase7入口，不能为提前暴露API绕过Phase5/6必要验收或完整fence。
3. Phase5–7依次加入高级派生、人工晋升和三触发报告，每个Checkpoint可独立验收。每次共享文件修改后运行对应先行测试及受影响的012边界，不无故重复全套评测。
4. Phase8完成发布验收：固定真实语料、record/replay、旧全集与target-host。质量不足保留能力/真实失败报告和默认关闭；硬指标失败修复后重跑受影响证据，不以功能关闭替代修复。

最小安全演示为Phase1–4的完整内部管线；可用管理MVP为Phase1–7。正式默认启用必须完成Phase8，P2链接/候选仍按本Feature完整范围交付。

## Notes

- 本文件生成的是待实施工作，不证明生产代码、LLM受益、E2E或旧全集已通过。
- 每个证据输出使用新路径，不能覆盖旧失败报告；未知观测保持缺失，不能伪造pass或零成本。
- 资格/审计是运行控制；链接/context/候选/消费/晋升指针为永久事件的派生视图。Distiller没有直写或正身摄入通道。
