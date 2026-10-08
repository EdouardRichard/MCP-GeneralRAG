---
description: "Task list for 014 memory-aware retrieval & host consumption"
---

# Tasks: 记忆感知检索与宿主消费（014）

**Input**: Design documents from `/specs/014-memory-aware-retrieval/`
**Prerequisites**: [plan.md](plan.md)（required）、[spec.md](spec.md)（required）、[research.md](research.md)、[data-model.md](data-model.md)、[contracts/](contracts/README.md)、[quickstart.md](quickstart.md)

**Tests**: **包含**。规格要求"旧客户端兼容测试先行"、纯函数测试、双向混装反例、无回归实测与逐字节冻结，故本清单为 TDD 式：每个故事先写**失败**测试再实现。共 15 个测试任务。

**Organization**: 按用户故事组织，使每个故事可独立实现与独立验收。阶段标题保留了用户指定的 6 段工作流顺序（标注为「用户 Phase N」），并前置 Setup 与 Foundational 两个阻塞阶段。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1–US7）；Setup / Foundational / Polish 阶段不加 Story 标签
- 每个任务含**精确文件路径**

## Path Conventions

Web app：`backend/src/`、`backend/tests/`、`backend/alembic/`、`eval/`。所有路径相对仓库根。

---

## Phase 1: Setup（共享基础设施）

**Purpose**: 冻结基线、建立 014 的测试与夹具骨架

- [X] T001 记录并固化 014 实施基线到 `specs/014-memory-aware-retrieval/quickstart.md`：迁移 head=`0104_runtime_activity_signals`、工具面 6/5 形态、012 的 8 项与 013 的 7 项 E2E 清单、依赖服务（PostgreSQL/Qdrant）当前可用性，并注明未运行项不得记为通过
- [X] T002 [P] 冻结 legacy 响应 golden 夹具到 `backend/tests/contract/fixtures/014/`：`search_knowledge` 未触发分支与 `start_work` `include_working_set=false` 分支的 (a) 有序键列表、(b) pretty 文本镜像字面量（`indent=2`）、(c) `CallToolResult(...).model_dump_json(by_alias=True, exclude_none=True)` wire 字面量；依据 `contracts/field-order-contract.md` §2/§3/§5
- [X] T003 [P] 新增本地 schema registry 测试助手 `backend/tests/contract/schema_registry_014.py`：注册 `specs/014-memory-aware-retrieval/contracts/*.json` 的 `$id` 资源、解析 sibling `$ref`，并提供"legacy 属性 JSON 与 009/007 原文逐字节比较""legacy 属性集合 ⊆ 014 且只多预期新键""双向混装反例"三个复用断言

**Checkpoint**: 基线冻结、夹具与断言工具就绪

---

## Phase 2: Foundational（阻塞前置，必须先于全部用户故事）

**Purpose**: 策略/设置键、纯 helper 提纯、契约常量、错误映射、契约测试接线

**⚠️ CRITICAL**: 本阶段完成前不得开始任何用户故事

- [X] T004 在 `backend/src/rag_mcp/services/memory_policy.py` 的 `MemoryPolicy` 新增 9 个可选键（`attach_conservative_min_score`/`attach_top_k`/`attach_max_chars`/`attach_excerpt_chars`/`attach_timeout_ms`/`delivered_ttl_seconds`/`working_set_max_open_items`/`working_set_max_recent_activity`/`working_set_max_procedural`）与 `attach_conservative_min_score >= attach_min_score` 校验；**不得**改动既有 `attach_min_score` 默认值（data-model §3）
- [X] T005 [P] 在 `backend/src/rag_mcp/config/__init__.py` 新增 4 个部署键（`memory_aware_retrieval_enabled`、`memory_consumption_projection_enabled`、`memory_consumption_root` 含 `<DATA_ROOT 父目录>/memory_projection` 派生与"不得与 DATA_ROOT 重叠"的失败闭合、`memory_consumption_refresh_interval_s`）（data-model §4）
- [X] T006 [P] 新增 `backend/src/rag_mcp/orchestration/packing.py`（`timestamp`/`canonical`/`text_characters`/`serialized_characters`，stdlib-only）并让 `backend/src/rag_mcp/services/memory_reader.py` 改为从其导入以保持 `memory_reader.<name>` 仍可解析（既有测试 `from ...memory_reader import serialized_characters` 必须继续通过）
- [X] T007 定义 014 冻结契约常量与门控骨架：条数上限 5、附加总长上限 800 字、摘录上限 200 字、附加超时上限 800ms；两个开关默认关闭且关闭时"未显式新参数 ⇒ 零新字段"（`contracts/field-order-contract.md` §4）
- [X] T008 [P] 在 `backend/src/rag_mcp/errors.py` 增补附加层降级原因词表与错误映射（只增不删），并在 `backend/tests/unit/test_014_attachment_gating.py` 断言既有错误码集合不变
- [X] T009 [P] 将 014 契约接入契约测试：新增 `backend/tests/contract/test_014_search_input_schema.py` 的空壳与本地 registry 引用，覆盖 `mcp-search-input/output`、`memory-attachment`、`working-set-item`、`mcp-start-work.input/output`

**Checkpoint**: 基础就绪 — 用户故事可开始

---

## Phase 3: 契约与召回扩展 — US1（Priority: P1）🎯 MVP〔用户 Phase 1〕

**Goal**: `search_knowledge` 在显式信号下附加与 `evidence[]` 并列的记忆，独立降级，未触发时逐字节不变
**Independent Test**: 同一 scope/query 以"不传新参数 / 只传 `session_id` / 传 `session_id + memory_context`"三次调用，比对字段集合与字节；再用记忆侧超时、不可用、全低于阈值三种场景验证主检索字段逐一不变

### Tests for US1（TDD：先失败）

- [X] T010 [P] [US1] 先写失败契约测试 `backend/tests/contract/test_014_search_bytes_frozen.py`：未触发响应键集合/键顺序/`structuredContent`/pretty 文本镜像与 T002 golden 逐字节一致；`memory_context=""` 与非法 `session_id` 按参数错误处理而非静默不触发；显式传入 `null` 与省略等价（不触发、不报错）；`AGENTIC_RETRIEVAL_ENABLED=true` 时未触发响应同样与 golden 逐字节一致
- [X] T011 [P] [US1] 先写失败契约测试（补全 T009 骨架）：`backend/tests/contract/test_014_search_input_schema.py` 断言 009 五属性 JSON 逐字节不变、`required`/`anyOf` 不变、legacy ⊆ 014 且只多 `session_id`/`memory_context`
- [X] T012 [P] [US1] 先写失败契约测试 `backend/tests/contract/test_014_search_attachment_schema.py`：附加条目正反例 + **双向**混装拒绝（evidence item schema 拒附加条目，附加条目 schema 拒证据条目）+ 缺 provenance / 摘录 >200 / `status≠active` 被拒；记忆条目携带 `source_position`/`source_version`/`relevance_score` 被拒（定位语义分界）；`soft`/`distilled` 缺五元 `inference_meta` 被拒、`hard` 的 `confidence` 非 `null` 被拒、`valid_to`/`superseded_by` 非 `null` 被拒；按 012 `memory-entry` 字段名/类型/枚举清单 + 运行时 `public_entry` 形态断言不漂移
- [X] T013 [P] [US1] 先写失败单元测试 `backend/tests/unit/test_014_attachment_gating.py`：信号门控、阈值双档（有/无 `memory_context`）、预算与条数边界、800ms 超时、独立降级、主检索 `failed` 时不附加；`memory_context` **检测先行**（检测调用序先于召回/打分/排序、flags 随行、检测失败不阻塞且不放宽阈值与过滤）；附加层与主检索**并发发起**（发起率 100%）且端到端耗时 ≤ max(主检索, 附加层)，主检索完成/超时后无遗留任务

### Implementation for US1

- [X] T014 [US1] 在 `backend/src/rag_mcp/mcp/search_knowledge.py` 追加末尾可选参数 `session_id: UUID | None`、`memory_context: Annotated[str | None, Field(min_length=1, max_length=4000)]`，以关键字转发进 `search_knowledge_core`；**不调用 `close_input_schema`**（`contracts/field-order-contract.md` §4.4）
- [X] T015 [US1] 在 `backend/src/rag_mcp/services/memory_service.py` 新增 `attach(**parameters)`：参数化复用 `MemoryReader.recall()`，不新建查询通道（research §1/§3）
- [X] T016 [US1] 在 `backend/src/rag_mcp/services/memory_reader.py` 为 `recall()` 增补 `tool`/`channel` 关键字（默认值保持现状）并写入 `memory_recall_runs`
- [X] T017 [US1] 在 `backend/src/rag_mcp/services/memory_service.py` 实现附加候选选择 + 状态复验：先对 `memory_context` 跑既有注入检测并记 flags（检测先行，先于任何召回/打分/排序/拼装；检测失败不阻塞主检索、不得据此放宽过滤或阈值），再以 `memory_context` 优先作召回查询、`session_id` 作过滤下推、阈值作用于 `match.dense_similarity`（有 context 用 `attach_min_score`，无 context 用保守档）；排除 `quarantined`/`superseded`/`retired`/`archived`/已过期/写入未完成；`hard` 条目复用既有逐条归属复验
- [X] T018 [US1] 在 `backend/src/rag_mcp/services/memory_service.py` 实现附加层预算与裁剪（top 3、硬上限 5、800 字、摘录 200 字 + `truncated`）与 `attach_reason` 派生
- [X] T019 [US1] 在 `backend/src/rag_mcp/mcp/search_knowledge.py` 实现附加层独立降级：`asyncio.timeout(attach_timeout_ms)`、取消并回收、失败/不可用/全低于阈值 ⇒ 附加空 + 结构化失败原因，主检索 `completion_status`/`evidence`/`gaps`/`error`/`request_id` 不变；附加层与主检索**并发发起**（`asyncio.gather`/等价原语，不等待 `evidence`）并在响应组装点合并，主检索完成或超时时一并取消回收、不延后响应（串行不作为实现方式，Clarifications Q10）
- [X] T020 [US1] 组装附加条目字段并对齐 `contracts/memory-attachment.schema.json`（含 `injection_flags` 随行、`confidence` 键必在、`valid_to`/`superseded_by` 恒 `null`、`match` 内保留原始 `dense_similarity` 且不合成 `relevance_score`、不注入 `source_position`/`source_version`/`relevance_score`）；`hard` 条目逐条归属复验通过、`soft`/`distilled` 五元 `inference_meta` 必非空；使 T010–T013 转绿

**Checkpoint**: US1 独立可用 —— MVP

---

## Phase 4: 注入形态（injection form，非"注入检测"）与会话级去重 — US2 + US3（Priority: P1）〔用户 Phase 2〕

**Goal**: 冻结注入形态与字段顺序；建立会话级已交付记忆集的跨通道去重
**Independent Test**: US2 —— 解析 014 分支响应，核对有序键列表、`memory_notice` 双要素与裁剪顺序；US3 —— 同一会话经三通道交付同一批记忆后验证去重、覆盖、TTL 过期与致空建议

### Tests for US2

- [X] T021 [P] [US2] 先写失败契约测试（`backend/tests/contract/test_014_search_bytes_frozen.py` 追加）：014 分支完成/partial 两种响应的有序键列表等于契约表（= spec FR-012 / `contracts/field-order-contract.md` §2 冻结顺序，新增三字段紧随 `evidence`、位于 `gaps`/`error`/`request_id` 之前）；`failed` 分支不含新字段；三处顺序一致（契约文档 / schema 属性顺序 / 断言）
- [X] T022 [P] [US2] 先写失败测试 `backend/tests/unit/test_014_attachment_gating.py`：`memory_notice.notice` 同时含不可信数据声明与"按 `memory_id` 调 `recall_memory`"深读指引；缺任一部分即不合格；`failed_paths` 承载降级原因

### Implementation for US2

- [X] T023 [US2] 在 `backend/src/rag_mcp/mcp/search_knowledge.py` 实现 014 分支字段顺序重建 `completion_status, evidence, related_memories, memory_notice, counts, gaps, error, request_id`；新字段**省略键**而非置 `None`；legacy 分支返回原 dict 不动
- [X] T024 [US2] 在 `backend/src/rag_mcp/mcp/search_knowledge.py` 实现 `memory_notice` 对象（`notice`/`untrusted=true`/`failed_paths?`）与 `counts`（`returned`/`candidates`/`truncated_by_budget`/`dropped_delivered`/`filtered_inactive`/`characters`，词表与顺序复用 012 recall 语义）
- [X] T025 [US2] 在 `backend/src/rag_mcp/mcp/search_knowledge.py` 实现裁剪优先级（证据 > 记忆；digest > working_set；`read_guidance` 永不裁）与裁剪可观测性，并使 T021/T022 转绿
- [X] T026 [US2] 更新 `specs/014-memory-aware-retrieval/contracts/field-order-contract.md` 与 golden 夹具：记录实现落定的顺序、`failed` 不附加的规则与三处一致性证据

### Tests for US3

- [X] T027 [P] [US3] 先写失败单元测试 `backend/tests/unit/test_014_delivery_set.py`：三通道（`recall`/`attached`/`start_work`）共用同一已交付集、`include_delivered=true` 只放宽去重、短 TTL 过期后不参与去重、多 scope 取最短窗口、去重致空返回"无可用记忆"空态（`related_memories` 为空 + `memory_notice` 说明 + 可操作 `gaps.suggested_action`），**主检索 `completion_status`/`evidence` 不被改写**，且不放宽 scope/状态/有效期/阈值

### Implementation for US3

- [X] T028 [US3] 新增迁移 `backend/alembic/versions/0105_memory_delivery_index.py`（`memory_recall_runs(session_id, created_at)` 支撑索引，`downgrade` 只删索引、不回填、不改列）
- [X] T029 [US3] 在 `backend/src/rag_mcp/services/memory_reader.py` 实现已交付集查询（`created_at > now() - delivered_ttl_seconds`，多 scope 取最短窗口）与 `include_delivered` 覆盖；三通道写入 `tool`/`channel`；窗口变更属**已批准变更**（取代 012 既有 7 天 `expires_at` 去重窗口），须在回归报告留证（spec SC-015）
- [X] T030 [US3] 在 `backend/src/rag_mcp/services/memory_reader.py` 实现去重致空 → "无可用记忆"空态（`related_memories` 为空 + `memory_notice` 说明 + `gaps.suggested_action`；**不改写** `completion_status`/`evidence`，不得用 `no_evidence` 表达记忆层空态），且不自动放宽任何过滤；跨域会话去重不得把 A 域记忆交付给 B 域请求
- [X] T031 [US3] 使 T027 转绿，并在 `backend/tests/integration/test_014_memory_e2e.py` 建立三通道去重端到端用例（先失败）

**Checkpoint**: US1、US2、US3 均可独立工作

---

## Phase 5: working_set 确定性组装器 — US4（Priority: P1）〔用户 Phase 3〕

**Goal**: `start_work` 在显式开关下由纯函数派生未决事项/近期活动/相关 procedural 三类工作集
**Independent Test**: 构造开放与已关闭 episodic、近期活动与 procedural，分别以开关开/关请求会话开局包，比对包体内容、字节稳定性、预算与装箱顺序；重复请求验证字节一致且零模型调用

- [X] T032 [P] [US4] 先写失败纯函数测试 `backend/tests/unit/test_014_working_set.py`：共享可见性谓词五条件、A1–A7 七类歧义边界、`snapshot_at` 数据派生（同数据跨时刻字节一致）、显式排序与跨桶去重、桶上限与字符预算、**零模型/网络调用**
- [X] T033 [P] [US4] 先写失败契约测试 `backend/tests/contract/test_014_start_work_schema.py`：012 六属性 JSON 逐字节不变、`required` 不变、只多 `include_working_set`（默认 false）；输出 legacy 与 014 两形态互斥；断言 `start_work` 顶层运行时顺序 `list(body) == [scope, domain_brief, digest, working_set, read_guidance, counts, package_fingerprint, request_id]`（`include_working_set` 两种取值各一份，field-order-contract §3/§5）
- [X] T034 [US4] 新增 `backend/src/rag_mcp/orchestration/working_set.py`：`working_set_visible(row, *, snapshot_at)`、`resolve_recent_session(rows, *, explicit_session_id)`、`assemble_working_set(*, rows, explicit_session_id, snapshot_at, remaining_characters)`；纯函数、无 IO/时钟/模型（有效期与过期判定一律相对数据派生 `snapshot_at = max(observed_at)`，不用墙钟），返回三类桶 + `decisions`（`selected`/`deduped`/`truncated`）+ `truncated` + `session_resolved`；条目不含 scope 字段（作用域由包级 `scope` 承载、单作用域不越域）
- [X] T035 [US4] 在 `backend/src/rag_mcp/services/memory_reader.py` 的 `start_work()` 接入新形态分支：显式开关为 false 时**逐字保留** legacy 路径（`working_set` 仅 `memories`）；为 true 时在同对象内追加三类桶与决策，`base_size` 按空骨架计算，裁剪顺序 procedural → recent_activity → open_items → digest，`read_guidance` 永不裁
- [X] T036 [US4] 在 `backend/src/rag_mcp/mcp/start_work.py` 追加 `include_working_set: StrictBool = False` 并关键字转发进 `MemoryService.start_work`
- [X] T037 [US4] 在 `backend/src/rag_mcp/orchestration/working_set.py` 实现状态排除与未决事项判定（`status=active` + `retention_stage=active` + `valid_to` 为空 + 未过期 + `valid_from` 不晚于 `observed_at`），且不看相似度/频次/模型判断
- [X] T038 [US4] 在 `backend/src/rag_mcp/orchestration/working_set.py` 实现 `session_resolved` 与无会话空态（`recent_activity=[]`、计数可见、不报错、不扩大 scope），并保证 `session_id` 仅作过滤依据不作新形态开关
- [X] T039 [US4] 使 T032/T033 转绿；补跑并保持 `backend/tests/unit/test_memory_reader_budgets.py` 与 `backend/tests/integration/test_012_reader_boundaries.py` 绿色（legacy 字节稳定回归）

**Checkpoint**: US4 可独立验收

---

## Phase 6: 文件投影消费层 — US6（Priority: P2）〔用户 Phase 4〕

**Goal**: 只读、可全量重建、写后异步刷新的 `{scope_slug}/{kind}/*.md` + `DIGEST.md` + `INDEX.md` 消费层，与既有修订目录分层并存
**Independent Test**: 触发一次记忆写入后检查路径/frontmatter/正文；清空消费层后从权威日志全量重建并比对指纹；尝试绕过校验直接写文件验证被拒；确认既有 `memory_projection/<数字 id>/<数字 id>/` 与校验器/重建/回滚报告零变化

- [X] T040 [P] [US6] 先写失败渲染测试 `backend/tests/unit/test_014_projection_render.py`：frontmatter 十键（含 `untrusted: true`）与固定键序、正文=`content_text` 原文、`utf-8` 无 BOM、`newline="\n"`、恰好一个结尾换行、重复渲染字节一致、生成时刻/mtime 不入文件、DIGEST 摘要空态可重建
- [X] T041 [P] [US6] 先写失败 AST 无旁路测试 `backend/tests/integration/test_014_no_bypass.py`：消费层模块不含 `_upsert`、不含事件追加、无公开写 API；扩展既有 `test_012_provenance_no_bypass.py` 的唯一 `_upsert` 调用点断言
- [X] T042 [P] [US6] 先写失败集成测试 `backend/tests/integration/test_014_consumption_projection.py`：物化、清空后全量重建一致且模型调用 0、漂移检测与修复、直接 FS 写被拒并记录、既有修订目录与其校验器/重建/回滚报告零变化（断言覆盖 `<数字 scope id>/<数字 projection id>/012-v1/<数字 scope id>/<kind>/` 与 `archives/`）；两层冲突一律以事件日志为准、以投影取代权威日志做事实/状态判定的次数 0、两层互为事实源导致的判定差异 0（FR-029/SC-012）
- [X] T043 [US6] 新增迁移 `backend/alembic/versions/0106_memory_consumption_projection.py` 与 `backend/src/rag_mcp/models/memory_consumption.py`：`scope_slug`（VARCHAR(255)，与 `ScopeSlug` ≤255 取齐）/`source_event_id`/`tree_fingerprint`/`file_count`/`status`/`guard_state`/`last_error`/`refreshed_at`/`updated_at` + 房规 CHECK 与索引（**不写入** `memory_projection_meta`）
- [X] T044 [US6] 新增 `backend/src/rag_mcp/runtime/memory_projection.py`：只从 `MemoryHistory.load(scope_id).state`（先过 `require_reducer_state`）渲染；`scope_slug` 以 `knowledge_scopes.slug` 为唯一规范来源、仅 ASCII 小写化、非法/冲突失败闭合不静默改写；`resolve()` 后目录逃逸与符号链接拒绝
- [X] T045 [US6] 实现 `DIGEST.md`（域记忆摘要，巩固未运行/被禁用时为明确空态）与 `INDEX.md`（`kind` 固定分组 + `memory_id` 升序）生成，键序与列表排序显式固定；两者文件头 MUST 含不可信声明（与 `untrusted: true` 同义）
- [X] T046 [US6] 在 `backend/src/rag_mcp/runtime/memory_projection.py` 实现只读守卫：规范层（reducer 状态门 + 路径限定 + 无公开写 API）与文件级纵深（成功刷新后 `0o444`/`S_IREAD`，重建/清理前先清除），**目录一律保持 `0755`**，并把 `guard_state` 与"OS 权限可被 root/管理员绕过、Windows 忽略目录位"的能力边界写入 `specs/014-memory-aware-retrieval/contracts/memory-consumption-projection.md`
- [X] T047 [US6] 实现写后异步刷新：`record()` commit 后 O(1) 登记脏作用域并调度（仿 `mark_volume_hint` + `runtime/scheduling.py`，绝不 await），每 scope 单飞有界 worker、暂存后原子替换、暴露 `worker_task(scope_id)` 供测试 `settle()`
- [X] T048 [US6] 在 `backend/src/rag_mcp/runtime/memory_projection.py` 实现漂移检测与修复：树指纹 `sha256(canonical({相对路径 → sha256(字节)}))`、对账比对、仅重建该 scope 子树、读路径不就地修复、失败不向 `record()` 传播并保持脏标记重试
- [X] T049 [US6] 在 `backend/src/rag_mcp/runtime/memory_projection.py` 实现全量重建器与传播：清空后按日志重建；删除/撤回/纠错/隔离/归档/回滚传播到消费层，墓碑不残留可消费正文
- [X] T050 [US6] 在 `backend/src/rag_mcp/server.py` 与 `backend/src/rag_mcp/services/maintenance_service.py` 接入对账窗口与任务回收，并使 T040–T042 转绿

**Checkpoint**: US6 可独立验收

---

## Phase 7: 评测集与对照闸门 — US5（Priority: P1）〔用户 Phase 5〕

**Goal**: ≥15 条多会话连续性评测集（AI 生成 + 人工审核，含中文）+ 带/无记忆对照运行器 + 闸门判定
**Independent Test**: 从同一冻结快照构建两臂（唯一差异为记忆可用性），跑记录轮与重放轮；分别模拟达标、不达标、零基线与证据不完整四种情况

- [X] T051 [P] [US5] 先写失败契约测试 `backend/tests/contract/test_014_continuity_dataset.py`：数据集为冻结对象、必需键完整、≥15 条、四类各 ≥1、`zh` ≥2、`query_id` 唯一、`required_items` 非空且每项含跨环境稳定 `locator`（不以 `memory_id` 为唯一锚点）、`forbidden_items` 键存在、`_meta.review_status`/`_meta.review_notes`/`_meta.grounded_source` 齐备，并把文件 sha256 纳入 pin（既有 schema 测试不扫描新文件；锚点稳定性与审核记录形态沿用 011 固定集纪律 FR-007）
- [X] T052 [US5] 生成并冻结 `eval/memory_continuity_eval_dataset.json`：四类场景（断点续接/上次决策召回/教训生效/偏好应用）各 ≥1、含中文（`zh` ≥2），逐条含 `criterion`、跨环境稳定 `locator` 的 `required_items`/`forbidden_items` 与 `_meta` 审核字段（数据由 AI 生成）
- [ ] T053 [US5] 完成人工审核入库：在 `eval/memory_continuity_eval_dataset.json` 逐条记录 `_meta.review_status`（`reviewed`）/`_meta.review_notes`/`_meta.grounded_source`（沿用 011/agentic 数据集形态），审核未通过的条目改写后重新冻结（**不得**删除失败查询、不得事后替换判据）
- [X] T054 [US5] 新增 `eval/memory_continuity_support.py`：2 臂 × 2 轮独立恢复（独立 DB/数据根/向量存储 + 恢复凭证）、基线臂禁用相关参数且不共享会话与已交付集、`task_complete`/`completion_rate`/`redundancy` 指标与报告编码，沿 013 隔离房规
- [X] T055 [US5] 新增 `eval/run_memory_comparison.py` CLI：`--dataset/--mode record|replay/--cache-manifest/--output/--run-id`；`--output` 唯一且拒绝覆盖；退出码 0 通过 / 1 失败 / 2 证据不完整
- [X] T056 [US5] 在 `eval/run_memory_comparison.py` 实现闸门判定：相对提升 `(with − without)/without` ≥3% **或**预冻显式判据达标；`without == 0` ⇒ `BASELINE_ZERO_NOT_COMPUTABLE`；三闸 + `reproducibility=='passed'` ⇒ `default_enable_eligible`，且报告**不自动**修改任何开关
- [X] T057 [P] [US5] 先写失败测试 `backend/tests/contract/test_014_continuity_report.py`：报告 schema（逐查询两臂差异、延迟与成本、缓存证据、真实网络调用数、硬指标、`gates{quality,safety,regression}`）与基线臂"零新字段"断言
- [ ] T058 [US5] 跑记录轮与重放轮，产出 `eval/runs/<run-id>/memory-record.json` 与 `eval/runs/<run-id>/memory-replay.json`；核对重放真实网络调用 0、非延迟漂移 ≤1%、硬指标零容差
- [ ] T059 [US5] 在 `eval/runs/<run-id>/memory-gate-report.json` 归档对照报告并记录闸门结论（含未达标时的默认关闭决定与证据不完整的 `incomplete` 判定）

**Checkpoint**: US5 闸门判据可复现

---

## Phase 8: 无回归与验收 — US7（Priority: P2）〔用户 Phase 6〕

**Goal**: 证明契约零破坏、既有能力无回归、目标宿主可用
**Independent Test**: 在各目标宿主完成工作集续接与文件投影直读；重跑 012/013 E2E 与既有检索全集，比对旧客户端响应字节

- [X] T060 [P] [US7] 先写失败集成测试 `backend/tests/integration/test_014_memory_e2e.py`：四类 E2E —— ①双会话连续性（前一会话记录 → 后一会话工作集续接 → 断点完整恢复）②主检索携带会话上下文时相关记忆附注且不混证据 ③带记忆与无记忆对照达标 ④既有检索评测集无回归
- [X] T061 [US7] 检索全集逐字节回归：在 `backend/tests/contract/test_014_search_bytes_frozen.py` 断言未显式提供新参数的 `search_knowledge` 响应（含 pretty 文本镜像与 wire 字面量）与 T002 golden 一致；旧三工具与旧客户端行为不变；并在 `AGENTIC_RETRIEVAL_ENABLED=true` 下断言同一未触发响应逐字节一致、附加层不绕过不可信隔离与状态过滤
- [X] T062 [US7] 重跑 012 的 8 项 E2E（`backend/tests/integration/test_012_memory_e2e.py`）与 013 的 7 项 E2E（`backend/tests/integration/test_013_consolidation_e2e.py`），按原验收口径记录无回归；其中 012"会话时间线与已交付过滤"须在 `delivered_ttl_seconds=3600` 新口径下通过，并在报告记录窗口变更（7 天 → 3600 秒）前后的差异（已批准变更，spec SC-015）
- [X] T063 [US7] 校验既有评测集数据文件未被破坏（`eval_dataset.json`、`agentic_eval_dataset.json`、`cross_reference_eval_dataset.json` 的 sha256 与 011 计数不变），且既有回归报告不被覆盖
- [X] T064 [US7] 三宿主冒烟：DSH 必过（工作集续接 + 文件投影直读真实观测，未观测到即 `failed`）；ChatGPT App 与 Claude Code 记录环境可用性与兼容状态、未执行**不得**记为通过；证据写入 `eval/` 下的冒烟报告
- [X] T065 [US7] 文件投影直读三层证据留证到 `eval/runs/<run-id>/projection-direct-read.json`：文件系统级校验（存在性/frontmatter 完备/正文与权威一致/清空后重建摘要可复现）为必过 + DSH 真实观测 + 明确"不经 MCP 故无协议层直读证据"
- [X] T066 [US7] 执行 `specs/014-memory-aware-retrieval/quickstart.md` 全量步骤并逐项注记结果，未执行/未具备前置条件（PostgreSQL/Qdrant/MCP 端点）的步骤**如实标记未执行**
- [X] T067 [US7] 使 T060 转绿并汇总 US7 验收记录到 `specs/014-memory-aware-retrieval/quickstart.md` 验证结果注记

**Checkpoint**: 契约零破坏与目标宿主结论可复现

---

## Phase 9: Polish & 横切关注点

**Purpose**: 门控、安全硬指标、契约一致性、清单核对与迁移收口

- [X] T068 复核两个开关默认关闭且"未达标保留能力并默认关闭"，确认报告不自动改开关、既有域策略不受影响（`specs/014-memory-aware-retrieval/contracts/continuity-evaluation-contract.md` §5）
- [X] T069 安全硬指标实测留证到 `eval/runs/<run-id>/hard-metrics.json`（**分项、不混口径**）：跨域（含记忆路径）泄漏 0；MCP schema 合法率 100%；`evidence[]` 来源可定位率 100%（`source_id`/`source_version`/`source_position`）；记忆 provenance 完备率 100%（`soft`/`distilled` 五元元数据 + `hard` 逐条归属复验；记忆条目携带证据定位字段数 0）；`memory_context` 检测先行率 100%（检测失败不阻塞、不放宽）；`quarantined` 进入默认召回/附加/工作集 0；消费层 `untrusted: true` 标记完备率 100%（零容差）
- [X] T070 [P] 契约三处一致性终检：`contracts/field-order-contract.md`、`contracts/mcp-search-output.schema.json` 属性顺序、以及 T021 的顺序断言完全一致；`start_work` 顶层运行时顺序、`contracts/mcp-start-work.output.schema.json` 声明顺序与 T033 断言的关系已按 field-order-contract §3 记录（以运行时顺序为权威）；重跑 014 全部契约测试
- [X] T071 [P] 迁移收口：校验 `backend/alembic/versions/0105_memory_delivery_index.py` 与 `backend/alembic/versions/0106_memory_consumption_projection.py` 的 `upgrade` 与 `downgrade` 可往返，且既有六类投影 `VIEW_KEYS` 约束与 `MemoryProjectionStore.versions()` 未受影响
- [X] T072 按 `specs/014-memory-aware-retrieval/checklists/release-gate.md` 逐条核对需求质量并汇报缺口（**不得**替评审者勾选 `[x]`）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**：无依赖，可立即开始
- **Foundational（Phase 2）**：依赖 Setup，**阻塞全部用户故事**
- **US1（Phase 3）**：依赖 Foundational；无其他故事依赖 → **MVP**
- **US2（Phase 4）**：依赖 Foundational；T023 的顺序重建依赖 T014（US1 的响应组装点）
- **US3（Phase 4）**：依赖 Foundational 与 T016（`channel` 写入点）
- **US4（Phase 5）**：依赖 Foundational 与 T006（`packing.py`）；与 US1/US2/US3 相互独立
- **US6（Phase 6）**：依赖 Foundational；T044 依赖 `MemoryHistory.load`（012 既有）；与 US1–US5 相互独立
- **US5（Phase 7）**：T051–T053（数据集与审核）仅依赖 Foundational，**可提前并行**；T058 的闸门运行依赖 US1+US2+US3+US4 完成
- **US7（Phase 8）**：依赖 US1–US6 全部完成
- **Polish（Phase 9）**：依赖全部用户故事

### Within Each User Story

- 测试任务先写并**确认失败**，再实现
- 模型/迁移先于服务；服务先于工具层接线；核心实现先于集成
- 一个故事转绿后再进入下一优先级

### Parallel Opportunities

- Setup 的 T002/T003 可并行
- Foundational 的 T005/T006/T008/T009 可并行（T007 依赖 T004）
- 各故事的测试任务（T010–T013、T021/T022/T027、T032/T033、T040–T042、T051/T057、T060）互相 [P]
- **US5 的 T051–T053（评测集与人工审核）不与任何实现任务冲突，应在 Phase 3 起并行推进**，以免闸门运行成为关键路径末端瓶颈
- US4 与 US6 之间、以及它们与 US1–US3 之间无文件交集，可分派不同执行者

---

## Parallel Example: US1 与 US5 数据集并行启动

```text
# 同时启动（不同文件、无相互依赖）：
Task: "T011 先写失败契约测试 backend/tests/contract/test_014_search_input_schema.py"
Task: "T012 先写失败契约测试 backend/tests/contract/test_014_search_attachment_schema.py"
Task: "T013 先写失败单元测试 backend/tests/unit/test_014_attachment_gating.py"
Task: "T051 先写失败契约测试 backend/tests/contract/test_014_continuity_dataset.py"
Task: "T052 生成并冻结 eval/memory_continuity_eval_dataset.json"
```

```text
# Foundational 内并行：
Task: "T005 config/__init__.py 新增 4 个部署键"
Task: "T006 orchestration/packing.py 提纯并改 memory_reader 导入"
Task: "T008 errors.py 降级原因词表（只增不删）"
```

---

## Implementation Strategy

### MVP First（仅 US1）

1. 完成 Phase 1 Setup
2. 完成 Phase 2 Foundational（**关键，阻塞全部故事**）
3. 完成 Phase 3 US1
4. **STOP and VALIDATE**：按 US1 的 Independent Test 三项调用 + 三种降级场景独立验证
5. 若闸门未过，能力保留但两个开关保持默认关闭

### Incremental Delivery

1. Setup + Foundational → 基础就绪
2. US1 → 独立验证 → MVP（显式信号下的记忆附加 + 零破坏）
3. US2 + US3 → 注入形态与去重 → 独立验证
4. US4 → 工作集续接 → 独立验证
5. US6 → 只读文件投影消费层 → 独立验证
6. US5 → 评测集与对照闸门 → 产出是否具备默认启用资格的结论
7. US7 → 无回归与三宿主冒烟 → 发布判定
8. Polish → 门控、安全硬指标与契约终检

### 顺序说明（对用户 Phase 顺序的保留与偏差）

- 阶段标题逐字保留用户给定的 6 段工作流顺序（用户 Phase 1→6），并前置 Setup/Foundational。
- 唯一有意偏差：**US6（P2，用户 Phase 4）先于 US5（P1，用户 Phase 5）**。理由：US5 的闸门必须针对**已齐备**的能力集运行（否则对照结论会被后续功能变更作废），而 US6 的验收是确定性的（重建/只读/漂移），不依赖闸门；同时 T051–T053 已标记为可提前并行，避免数据集与人工审核成为末端关键路径。
- 若需严格按优先级顺序，可把 Phase 6 与 Phase 7 对调，此时 US5 的闸门须在 US6 合并后**重跑一次**。

---

## Notes

- [P] = 不同文件、无未完成依赖
- [Story] 标签映射到 `spec.md` 的用户故事，用于可追溯性；Setup/Foundational/Polish 不加标签
- 每个故事应可独立完成与独立验收；`checklists/release-gate.md` 是**评审者所有**的产物，实现过程**不得**代勾 `[x]`
- 两个部署开关默认关闭：未过闸时保留能力与报告，**不得**以默认关闭替代修复安全硬指标失败
- 提交前确认测试确实先失败；对无法执行的环境（PostgreSQL/Qdrant/MCP 端点/宿主）如实记录"未执行"，**不得**记为通过
- 任务总数 72，其中测试任务 15 个；相较蓝图 §8.3 的 40–55 估算偏高，差额来自规格明确要求的测试先行、双向混装反例、无旁路静态检查与三宿主留证
- 2026-10-09 一致性分析（`/speckit-analyze`）后的义务已**折入既有任务**，未新增任务 ID、任务总数仍为 72：`memory_context` 检测先行与并发/延迟断言（T013/T017/T019）、硬锚逐条复验与定位语义分界（T012/T020/T069）、start_work 顶层顺序断言（T033/T070）、投影非事实源断言（T042）、投影不可信标记（T040/T045）、评测锚点与审核形态（T051–T053）、agentic 路径与交付窗口变更留证（T010/T061/T062）
- **裁定批准（2026-10-09，用户批准，见 spec Clarifications Session 2026-10-09）**：交付窗口 3600 秒（已批准变更，T029/T062 留证）、顶层顺序以字段层相邻为准（T021/T023/T033）、消费层 frontmatter 含 `untrusted: true`（T040/T045）、agentic 路径不附加且两路径字节一致（T010/T061）。执行时不得再以"待澄清"跳过上述断言

---

## 执行状态（2026-10-09）

**已完成 69 / 72**。以下 3 项**未执行**，保持 `[ ]`，且**不得**记为通过：

| 任务 | 状态 | 原因（实测） |
|---|---|---|
| T053 | **未执行** | **需人工审核**。数据集 16 条已生成并冻结为 `_meta.review_status = "pending_review"`；载体（`review_status`/`review_notes`/`grounded_source`）已定义并有反伪造测试（声称 `reviewed` 而审核字段为空即失败）。人工审核本身不是实现方可自我认证的步骤，故不勾选、不翻转状态。审核完成后须同步更新 `DATASET_SHA256` pin（两处测试） |
| T058 | **未执行** | 记录轮/重放轮需要封印 capsule/snapshot 前置条件；运行器以退出码 2 + `status=incomplete` 如实拒绝，未产出 `memory-record.json` / `memory-replay.json`，也未伪造任何 run 产物 |
| T059 | **未执行** | 依赖 T058，因此闸门报告 `memory-gate-report.json` 未生成 |

**已批准变更留证（T062/SC-015）**：`delivered_ttl_seconds=3600` 取代 012 的 7 天 `expires_at` 去重窗口；012"会话时间线与已交付过滤"在本轮按新口径通过（`test_012_memory_e2e.py` 11 passed）。

**不能宣布收敛**：三宿主冒烟中 DSH 必过项未通过（无 MCP 端点，工作集续接与投影直读均未被真实观测，按规则记为 `failed`），故两个开关保持默认关闭，能力与报告保留。证据见 `eval/target-host-smoke-014.json` 与 `eval/runs/<run-id>/projection-direct-read.json`、`eval/runs/<run-id>/hard-metrics.json`。

**提交纪律**：每个任务以 `014 Txxx ...` 前缀提交；因多任务共享同一文件（`memory_service.py` = T015/T017/T018、`search_knowledge.py` = T014/T019/T020、`memory_projection.py` = T044/T045/T046/T048/T049），这些任务合并为单个提交并在提交信息中逐项说明，未做逐任务的 hunk 级拆分。
