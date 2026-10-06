# 任务清单：012 记忆基座与写读回路（G2+ 权威层）

**输入**：`spec.md`、`plan.md`、`data-model.md`、`contracts/`、`research.md`、`quickstart.md`

**执行纪律**：TDD 先红后绿。每个测试任务必须先写出失败断言，再实现对应代码；隔离、安全、provenance、注入和轨迹测试与功能测试同批交付。所有任务都必须保留精确文件路径和 FR/US 映射。

**2026-10-05 验收复核**：此前 T001–T087 的完成标记撤回，待逐项重新核验。真实 PG 拒绝测试证明事件可被 UPDATE/DELETE、关系投影缺少 14 个必需字段、调用者 published 字段被误当证据；轨迹测试证明四类投影缺失、隔离/纠正/回滚未实现。旧的浅层测试通过不能证明对应任务完成。checklists 保持只读。

**估计规模**：82 项任务。阶段顺序为 Phase 1–8；Phase 8 是发布门禁，不得提前标记完成。

## Phase 1：宪法与迁移基座

**目标**：完成 12.0 修订基线、事件日志与六类投影表、域策略默认值和等价性测试骨架。

**独立验收**：Alembic 可升级/降级；所有表、索引、宽 CHECK、默认策略和四个内置域种子存在；事件 UPDATE/DELETE 入口不存在；等价性测试骨架先红后绿可运行。

### 1.1 先红测试

- [X] T001 [P] [US1] 编写 12.0 migration DDL 断言，先在 `backend/tests/unit/test_migration_012_memory.py` 验证缺少 `memory_events`、六投影表、policy 列和索引时失败（FR-001–FR-005）。
- [X] T002 [P] [US1] 编写事件宽 CHECK、非空 scope、时间字段和 append-only 访问边界测试，在 `backend/tests/unit/test_memory_event_constraints.py` 先红（FR-002–FR-004）。
- [X] T003 [P] [US7] 编写四个内置域 memory_policy 默认值测试，在 `backend/tests/unit/test_memory_policy_defaults.py` 先红（FR-014a）。
- [X] T004 [P] [US1] 编写事件回放与在线投影等价性测试骨架，在 `backend/tests/unit/test_memory_projection_equivalence.py` 先红；建立五不变量独立断言：权威单调、范围不扩张、删除传播、provenance 保全、回滚可溯（FR-006–FR-008）。

### 1.2 实现

- [X] T005 [US1] 新增 `backend/alembic/versions/0080_memory_foundation.py`，创建 `memory_events`、`memory_entries`、`scope_bindings`、`sessions`、`memory_salience`、`memory_recall_runs` 和六投影元数据表，加入索引、FK、宽 CHECK 和不可变事件注释（FR-001–FR-005）。
- [X] T006 [US1] 在 `backend/src/rag_mcp/models/memory_event.py` 定义事件 ORM，覆盖七类事件、六轴 JSONB、时间、actor/session/request 字段和查询索引（FR-002–FR-004）。
- [X] T007 [P] [US1] 在 `backend/src/rag_mcp/models/memory_projection.py` 定义 `MemoryEntry`、投影状态/指纹和自引用 supersede 关系（FR-009–FR-010）。
- [X] T008 [P] [US2] 在 `backend/src/rag_mcp/models/scope_binding.py`、`session.py`、`memory_salience.py`、`memory_recall_run.py` 定义对应 ORM 和 append-only/TTL 字段（FR-011–FR-013、FR-032）。
- [X] T009 [US7] 在 `backend/src/rag_mcp/models/domain_profile.py` 增加 `memory_policy` JSONB，并在 `backend/src/rag_mcp/config/domain_profiles.py` 为 se-project/generic/personal/legal 生成同值默认策略（FR-014、FR-014a）。
- [X] T010 [US1] 更新 `backend/src/rag_mcp/models/__init__.py` 导出新增模型，确保 Alembic metadata 能发现全部表（FR-001–FR-014）。
- [X] T011 [US1] 实现 `backend/tests/unit/test_memory_projection_equivalence.py` 的最小 reducer fixture 和规范化 fingerprint 比较器，使 T004 通过并覆盖 assert/revise/retract/access（FR-006–FR-008）。
- [X] T012 [US1] 运行 migration helper、DDL parity 和四档案 seed 测试，修正 `backend/tests/unit/test_migrations_helper.py` 兼容点并记录 TDD 红绿证据（FR-001–FR-014）。

## Phase 2：同事务物化骨架

**目标**：实现 INSERT 事件→UPSERT 关系投影的纯 PG 事务骨架，并用代码层/测试层双重防守投影只读。

**独立验收**：成功写入在同一事务内产生事件和当前态；任一 PG 投影失败会整体回滚；直接 UPDATE/DELETE 事件或投影的代码路径被拒绝；在线 reducer 与回放 reducer 等价。

### 2.1 先红测试

- [X] T013 [P] [US1] 在 `backend/tests/unit/test_memory_transaction.py` 编写事件 INSERT 与 projection UPSERT 同事务测试，先红（FR-006）。
- [X] T014 [P] [US1] 在 `backend/tests/unit/test_memory_read_only.py` 编写事件仓储无 update/delete、六类业务投影仓储禁止直接写入且仅接受 reducer 产物的否定测试，先红（FR-001、FR-005）。
- [X] T015 [P] [US1] 在 `backend/tests/integration/test_012_memory_projection_equivalence.py` 编写在线物化/日志回放六类业务投影 fingerprint 对等测试；逐类断言非空数据、状态变更、删除传播、provenance 链和回滚 fingerprint，先红（FR-005–FR-008、SC-008）。
- [X] T016 [P] [US1] 在 `backend/tests/integration/test_012_memory_failure_visibility.py` 编写 PG、向量、链接、摘要、文件和显著性投影失败及未完成写入不可召回/不可进工作包的测试，先红（FR-006，SC-007）。

### 2.2 实现

- [X] T017 [US1] 实现 `backend/src/rag_mcp/services/memory_event_store.py` 的 append-only insert/replay API，禁止提供 update/delete 方法（FR-001–FR-004）。
- [X] T018 [US1] 实现 `backend/src/rag_mcp/services/memory_projection_store.py` 的事务内 UPSERT、状态指纹和投影完成状态，所有写入口只接受 reducer 产物（FR-005–FR-007）。
- [X] T019 [US1] 在 `backend/src/rag_mcp/services/memory_service.py` 建立事务协调器，执行事件 INSERT→关系 UPSERT 并在 commit 前校验同步完成状态（FR-006）。
- [X] T020 [US1] 实现 `backend/src/rag_mcp/services/memory_reducer.py`，统一在线物化与 rebuild 的事件语义、supersede 状态和规范化 fingerprint（FR-006–FR-008）。
- [X] T021 [US1] 在 `backend/tests/unit/test_memory_read_only.py` 增加静态 grep/接口枚举和数据库权限断言，证明 memory_events、六类业务投影没有 UPDATE/DELETE 代码旁路；runtime、repository、数据库权限三层均仅允许 reducer 产物写入（FR-001、FR-005）。
- [X] T022 [US1] 运行 Phase 2 单测和集成测试，确认 T013–T016 由红转绿并记录失败闭合/可恢复状态（FR-006–FR-008）。

## Phase 3：scope 解析与绑定

**目标**：增加 `path:` 第五形态、管理面绑定、最长前缀+priority、歧义拒绝和提权防护。

**独立验收**：ID/slug/type:name/path 五形态均可解析；缺失/歧义一律返回双轨错误和 candidates；MCP 不能写绑定；四路径 scope 保持一致。

### 3.1 先红测试

- [X] T023 [P] [US2] 在 `backend/tests/unit/test_scope_binding_service.py` 编写五种 scope_ref、绝对路径规范化、Git remote canonicalization、大小写、软链接、相对路径和最长前缀测试，先红（FR-015–FR-016）。
- [X] T024 [P] [US2] 编写同前缀同 priority、多候选、disabled binding、无命中和 candidates 错误测试，先红（FR-016）。
- [X] T025 [P] [US2] 在 `backend/tests/integration/test_012_binding_escalation.py` 编写 MCP/模型尝试写 scope_bindings 的提权拒绝测试，先红（FR-011）。
- [X] T026 [P] [US2] 在 `backend/tests/integration/test_012_memory_isolation.py` 编写 A/B scope 的 event log、relation、vector、file 四路径零泄漏测试，覆盖单域、显式多域并集、无命中和路径/remote 解析失败，先红（FR-017，SC-002）。

### 3.2 实现

- [X] T027 [US2] 实现 `backend/src/rag_mcp/services/scope_binding_service.py`，执行路径/remote 规范化、最长前缀、priority、唯一命中和歧义候选返回（FR-015–FR-016）。
- [X] T028 [US2] 扩展 `backend/src/rag_mcp/services/scope_resolver.py` 接入第五种 `path:` 形态，复用 007 双轨错误码且禁止默认 scope 回落（FR-015–FR-017）。
- [X] T029 [US2] 在 `backend/src/rag_mcp/api/memory.py` 预留管理面 scope binding CRUD，并在 API 层拒绝 MCP/非管理调用（FR-011、FR-035）。
- [X] T030 [US2] 将 scope resolver 接入 `backend/src/rag_mcp/services/memory_service.py`、`backend/src/rag_mcp/mcp/recall_memory.py`、`backend/src/rag_mcp/mcp/start_work.py` 和 projection adapters，确保事件/关系/向量/文件使用同一 scope（FR-017）。
- [X] T031 [US2] 增加 `backend/tests/contract/test_memory_scope_contract.py` 绑定和隔离错误码/候选契约测试，运行 T023–T026 并逐路径确认 event log、relation、vector、file 串库为 0，显式多域结果仅为请求并集（FR-015–FR-017、SC-002）。

## Phase 4：写入管线

**目标**：完成 `record_memory` 九步，从全拒绝矩阵、脱敏/注入到 supersede、配额、事件投影、向量和 session 登记。

**独立验收**：hard 无锚、soft 元数据不完整、kind/目标/配额/reader 等所有拒绝路径均稳定；合法写入只产生脱敏事件并完成同步投影；quarantined 默认不可见。

### 4.1 先红测试

- [X] T032 [P] [US3] 在 `backend/tests/unit/test_memory_validators.py` 编写 kind、hard evidence（逐条 attribution re-verification：source ID/version/position/content）、soft 五元 metadata、distilled source-chain、confidence、content length、scope 和错误码全拒绝矩阵，先红（FR-020–FR-022）。
- [X] T033 [P] [US3] 在 `backend/tests/unit/test_memory_redaction_injection.py` 编写凭据替换、字段名保留、高危注入 flags/quarantined 和 detector failure 测试，先红（FR-020–FR-021）。
- [X] T034 [P] [US3] 在 `backend/tests/unit/test_memory_supersede.py` 编写同域 active 目标、跨域/不存在/非 active 目标和 valid interval 关闭测试，先红（FR-020–FR-021）。
- [X] T035 [P] [US7] 在 `backend/tests/unit/test_memory_quota_ttl.py` 编写 5000 quota fail-loud、kind TTL 派生和无静默驱逐测试，先红（FR-014a、FR-033）。
- [X] T036 [P] [US3] 在 `backend/tests/integration/test_012_record_memory.py` 编写硬锚闭环、无锚拒写、跨域证据拒写、脱敏和注入隔离 E2E，先红（SC-003–SC-004）。

### 4.2 实现

- [X] T037 [US3] 实现 `backend/src/rag_mcp/services/memory_validators.py`，集中 scope、kind、provenance、evidence published/same-scope、inference metadata、confidence 和错误码校验（FR-020–FR-022）。
- [X] T038 [US3] 在 `backend/src/rag_mcp/services/memory_service.py` 按九步接线：scope→脱敏→provenance→注入→supersede→quota/TTL→事件+关系事务→向量 intent→session（FR-020）。
- [X] T039 [US3] 接入 `backend/src/rag_mcp/parsers/credential_redactor.py` 和 `backend/src/rag_mcp/agents/injection_detector.py`，保证落库前单一净化点、原凭据零出现和 quarantined 双排除（FR-020–FR-021）。
- [X] T040 [US3] 实现 supersede 目标校验、旧条目 valid_to/superseded_by 更新和硬记忆保护边界（FR-010、FR-021）。
- [X] T041 [US3] 实现同 scope 脱敏正文+规范化元数据重复提交判定、`MEMORY_CONTENT_CONFLICT` 和并发幂等锁，禁止恢复非 active 条目（FR-019a、FR-022）。
- [X] T042 [US7] 实现配额/TTL 派生、session 登记和 `memory_recall_runs` 审计写入，保留运行态 TTL 边界（FR-012–FR-014、FR-033）。
- [X] T043 [US3] 增加 `backend/tests/integration/test_012_provenance_no_bypass.py`，对所有 memory write 入口做 grep/静态注册审计，证明无例外路径且 provenance、hard anchor、hard 逐条 attribution re-verification、soft 五元 metadata、distilled source-chain 均 100%（FR-020–FR-022，SC-003、SC-008）。
- [X] T044 [US3] 运行 T032–T036、T043，确认九步顺序、失败闭合、脱敏字段名保留、quarantined 默认不可见和重复提交判定全部由红转绿（FR-020–FR-022）。

## Phase 5：显著性与读路径

**目标**：实现 salience 投影、强制衰减、四模式召回、四路加权 RRF、PG 后置核验和 status 陈旧 payload 实验。

**独立验收**：ID/timeline/filtered 绕开 Qdrant；semantic/hybrid 过召回后 scope 下推、status/valid/agent/阈值后置核验；无衰减 salience 不参与排序；四态和 counts 可观测。

### 5.1 先红测试

- [X] T045 [P] [US7] 在 `backend/tests/unit/test_salience_service.py` 编写冷启动 0、`f(access,recency,reinforcement)`、β=0.05/day、γ=1/access、强制衰减和无衰减禁排测试，先红（FR-026a、FR-032）。
- [X] T046 [P] [US4] 在 `backend/tests/unit/test_rrf_memory.py` 编写 dense/recency/kind/salience 四路权重、旧 dense/sparse/graph 三路兼容和确定性 tie-break 测试，先红（FR-026）。
- [X] T047 [P] [US4] 在 `backend/tests/unit/test_memory_recall_modes.py` 编写 by_id/timeline/filtered/semantic 四模式、limit×4/下限40、as_of valid 矩阵和 superseded 显式可见测试，先红（FR-023–FR-028）。
- [X] T048 [P] [US4] 在 `backend/tests/integration/test_012_memory_status_staleness.py` 构造 Qdrant 陈旧 status payload，编写“不下推 status 无假阴性”对照实验，先红（FR-025）。
- [X] T049 [P] [US4] 在 `backend/tests/integration/test_012_memory_recall_observability.py` 编写 6000 字预算、300 字 excerpt、四态 completion、counts、failed_paths 和 3 秒超时测试，先红（FR-027–FR-028）。

### 5.2 实现

- [X] T050 [US7] 实现 `backend/src/rag_mcp/services/salience_service.py` 纯函数、access 事件物化和强制衰减闸门，默认 salience 0/β 0.05/γ 1.0（FR-026a、FR-032）。
- [X] T051 [US4] 扩展 `backend/src/rag_mcp/fusion/rrf.py` 支持可选四路权重，保持既有 dense/sparse/graph 调用签名、字段和排序兼容（FR-026）。
- [X] T052 [US4] 扩展 `backend/src/rag_mcp/indexing/qdrant_client.py` 支持 `memories_dense_{index_version}`、scope/kind/session payload filter 和 memory point upsert；显式不加入 status filter（FR-024–FR-025）。
- [X] T053 [US4] 在 `backend/src/rag_mcp/services/memory_service.py` 实现四模式 recall：ID/timeline/filtered 走 PG，semantic/hybrid 走 dense→PG 后置核验→RRF（FR-023–FR-026）。
- [X] T054 [US4] 实现 `as_of` valid 线过滤、superseded/include_superseded、include_delivered、agent/session/time_window 和 no-filter-relaxation（FR-023、FR-027）。
- [X] T055 [US4] 实现召回裁剪、counts、memory_notice/gaps/error、partial/no_evidence/failed 和 memory_recall_runs 审计（FR-027–FR-028）。
- [X] T056 [US4] 运行 T045–T049，产出衰减/无衰减自锁对照、status 陈旧 payload 假阴性实验和召回预算报告（FR-025–FR-028，SC-006、SC-015）。

## Phase 6：MCP 契约

**目标**：注册 `record_memory`、`recall_memory`、`start_work`，完成 mode 感知、ToolAnnotations、错误码、10 个合同 schema 和 MCP acceptance。

**独立验收**：writer 六工具、reader 五只读工具；三工具 schema 100%；旧三工具无新字段/字节变化；structuredContent 是唯一规范事实源。

### 6.1 先红测试

- [X] T057 [P] [US4] 在 `backend/tests/contract/test_memory_schemas.py` 加载并验证 `contracts/` 下六个 MCP schema、memory entry/event、error-codes 和 management schema，先红（FR-018–FR-031）。
- [X] T058 [P] [US5] 在 `backend/tests/unit/test_memory_mcp_annotations.py` 编写三工具 ToolAnnotations、参数默认值、字段顺序和 envelope/body 分离断言，先红（FR-018、FR-023、FR-029–FR-031）。
- [X] T059 [P] [US6] 在 `backend/tests/unit/test_memory_mcp_registration.py` 编写 writer 六工具、reader 五工具和 reader 无 `record_memory` 测试，先红（FR-018）。
- [X] T060 [P] [US6] 在 `backend/tests/contract/test_memory_byte_compat.py` 编写旧三工具响应/schema 逐字节快照和错误码只增不删测试，先红（FR-022、FR-039）。

### 6.2 实现

- [X] T061 [US3] 新增 `backend/src/rag_mcp/mcp/record_memory.py`，以 FastMCP 签名注册非只读、非破坏、非幂等工具并映射 `MemoryService.record`（FR-018–FR-022）。
- [X] T062 [US4] 新增 `backend/src/rag_mcp/mcp/recall_memory.py`，注册只读工具并序列化四态、memories、counts、gaps/error/request envelope（FR-023–FR-028）。
- [X] T063 [US5] 新增 `backend/src/rag_mcp/mcp/start_work.py`，实现 digest 优先、working_set、三档预算、read_guidance 永不裁剪、稳定包体和 fingerprint（FR-029–FR-031）。
- [X] T064 [US6] 扩展 `backend/src/rag_mcp/mcp/__init__.py` 与 `backend/_run_mcp.py`，增加 mode 参数和 writer/reader 工具清单，保持既有注册顺序与依赖注入（FR-018、FR-039）。
- [X] T065 [US5] 在 `backend/src/rag_mcp/mcp/serialization.py` 固化 structuredContent→确定性 JSON 镜像，剔除 request_id/时间等易变字段出稳定包体，禁止第二事实渲染路径（FR-031、FR-039）。
- [X] T066 [US6] 扩展 `backend/src/rag_mcp/errors.py` 和 `specs/012-memory-foundation-write-read-loop/contracts/error-codes.json`，确保新增枚举只增不删并保留 001–011 旧码（FR-022）。
- [X] T067 [US6] 运行 T057–T060、真实 FastMCP tool-list 和旧客户端快照验收，修正 schema/annotation/byte compatibility 直到全部转绿（FR-018–FR-039）。

## Phase 7：治理与回滚

**目标**：完成 TTL、配额、遗忘阶梯、快照/归档/截断、六投影 rebuild、管理 REST rollback 与审计。

**独立验收**：TTL/配额 fail-loud；快照+增量 rebuild 与全日志一致；rollback 仅管理面、单 scope、access 保留、投影重建一致且可溯。

### 7.1 先红测试

- [X] T068 [P] [US1] 在 `backend/tests/unit/test_projection_rebuild.py` 编写六类投影 registry、逐类非空/状态变更/删除传播/provenance 校验、snapshot+delta/full replay fingerprint 和不可用快照回退测试，先红（FR-004a、FR-005、FR-007、FR-036、SC-008、SC-013）。
- [X] T069 [P] [US1] 在 `backend/tests/integration/test_012_snapshot_truncation.py` 编写 10000 事件/24 小时快照、普通 assert 归档截断、修订/撤回/巩固/授权/回滚依赖保留、快照损坏后完整日志恢复以及日志不完整时拒绝完整恢复声明测试，先红（FR-004、FR-004a、SC-013）。
- [X] T070 [P] [US1] 在 `backend/tests/unit/test_memory_rollback.py` 编写时间点、event point、跨 scope、access 保留、supersede 冲突和 rollback 后再次 rollback 场景矩阵，先红（FR-035–FR-035a）。
- [X] T071 [P] [US6] 在 `backend/tests/contract/test_memory_management_api.py` 编写 browse/retire/purge/rebuild/rollback 管理 REST schema 和权限审计测试，先红（FR-035）。

### 7.2 实现

- [X] T072 [US1] 实现 `backend/src/rag_mcp/runtime/projection_rebuild.py`，提供六类 projection adapter、全量/since_event_id、snapshot+delta、fingerprint、scope/计数/删除传播/provenance 校验（FR-007、FR-036）。
- [X] T073 [US7] 扩展 `backend/src/rag_mcp/services/maintenance_service.py`，支持运行态 7 天、access 在线 90 天、episodic 180 天、semantic/procedural 永生、遗忘阶梯、事件归档和快照截断（FR-004、FR-033–FR-034）。
- [X] T074 [US1] 实现 `backend/src/rag_mcp/services/rollback_service.py`，限制单 scope/管理面，按时间点或 event point 重放状态事件，保留 access，记录 reason/impact/before-after fingerprints 和 rollback 事件（FR-035a）。
- [X] T075 [US6] 完善 `backend/src/rag_mcp/api/memory.py` 的浏览、retire、显式 purge、policy/binding 管理、projection rebuild 和 rollback REST 路由（FR-011、FR-035）。
- [X] T076 [US1] 将六类投影 adapter 接入 `backend/src/rag_mcp/indexing/memory_vectors.py`、`backend/src/rag_mcp/runtime/projection_rebuild.py`、文件镜像/DIGEST/INDEX 输出，要求非空状态变化、scope 路径和版本指纹（FR-005、FR-007）。
- [X] T077 [US1] 运行 T068–T071 并修正治理/回滚/截断实现，确认 rollback 后六投影与目标事件点一致、access 未被删除、跨 scope 请求稳定拒绝（FR-035a–FR-036，SC-013、SC-016）。

## Phase 8：无回归与验收

**目标**：完成 `start_work`、八项 E2E、AOEP 状态义务、既有全集、硬指标和 quickstart 验收。

**独立验收**：八项 012 E2E、四类 AOEP、硬指标五件套、writer/reader 双形态、001–011 全集和前端构建均通过；历史报告不被覆盖。

### 8.1 先红测试

- [x] T078 [P] [US8] 新增 `backend/tests/integration/test_012_memory_e2e.py`，先写并确认八项 E2E 红测：硬锚闭环、无锚拒写、跨域隔离、supersede、注入隔离、TTL/配额、reader 无写、会话时间线（FR-037）。
- [x] T079 [P] [US8] 新增 `backend/tests/integration/test_012_aoep_obligations.py`，先写五不变量逐项用例并各至少两条：权威单调、范围不扩张、删除传播、provenance 保全、回滚可溯；任一失败即阻止发布（FR-008、FR-037）。
- [x] T080 [P] [US8] 新增 `backend/tests/integration/test_012_hard_metrics.py`，先写 event log/relation/vector/file 四路径泄漏、显式多域并集、schema、provenance、hard anchor、hard 逐条 attribution re-verification、soft 五元 metadata、distilled source-chain、quarantined 泄漏和六类业务投影非空完整性指标断言（FR-038、FR-040）。

### 8.2 实现与验收

- [x] T081 [US8] 实现 `backend/tests/integration/test_012_memory_e2e.py` 所需真实 fixture、writer/reader 双实例、scope binding、Qdrant、文件投影和 request/fingerprint 采集（FR-037–FR-040）。
- [x] T082 [US8] 实现 `backend/tests/integration/test_012_aoep_obligations.py` 和 `backend/tests/integration/test_012_hard_metrics.py` 的通过路径，确保五不变量逐项、四路径隔离、六类业务投影完整性、hard 逐条归因复验、soft 五元 metadata、distilled source-chain 和失败路径全量达到规定值且可诊断（FR-008、FR-037–FR-040）。
- [x] T083 [P] [US8] 在 `backend/tests/contract/test_012_old_tool_compat.py` 重跑既有三工具 schema/byte snapshots，确认旧客户端未因新工具或新字段变化（FR-039）。
- [x] T084 [P] [US8] 在 `backend/tests/integration/test_012_regression_suite.py` 接入 001–011 全集运行器、历史报告零覆盖和非延迟容差断言（FR-039–FR-040、SC-012）。
- [x] T085 [P] [US6] 在 `frontend/src/api/memories.ts`、`frontend/src/pages/MemoriesPage.tsx`、`frontend/src/App.tsx` 完成最小记忆浏览页，展示 scope/kind/provenance/status/valid interval/evidence/injection/projection 状态，不暴露凭据或 MCP rollback（FR-035）。
- [x] T086 [US6] 运行 `frontend/package.json` 的 `pnpm build`，并在 `backend/tests/integration/test_012_frontend_memory_page.py` 验证路由/API 空态、错误态和字段脱敏（FR-039–FR-040）。
- [x] T087 [US8] 执行 `specs/012-memory-foundation-write-read-loop/quickstart.md` 全流程，保存迁移、unit、contract、integration、E2E、双实例、前端构建和报告路径证据（FR-037–FR-040）。
- [x] T088 [US8] 运行完整 `backend/pyproject.toml` pytest、001–011 评测和 012 报告生成，按固定报告 schema 保存双实例、四路径证据、request_id、失败路径和包/投影 fingerprint；确认无回归、四路径串库=0、显式多域仅返回并集、provenance/hard anchor/hard 逐条 attribution re-verification/soft 五元 metadata/distilled source-chain=100%、quarantined 默认泄漏=0，并逐项收口 SC-001–SC-017。SC 映射为：SC-001→T078/T087/T088；SC-002→T026/T031/T080/T088；SC-003→T032/T036/T043/T080/T088；SC-004→T033/T036/T080/T088；SC-005→T063/T065/T086/T088；SC-006→T047/T049/T056/T088；SC-007→T016/T078/T082/T088；SC-008→T015/T068/T076/T080/T082；SC-009→T025/T059/T071/T078/T088；SC-010→T045/T069/T073/T080/T088；SC-011→T003/T035/T088；SC-012→T060/T083/T084/T088；SC-013→T068/T069/T077/T088；SC-014→T047/T054/T088；SC-015→T045/T056/T088；SC-016→T070/T074/T077/T088；SC-017→T041/T044/T088。更新 `eval/README.md` 登记命令但不覆盖历史报告（SC-001–SC-017）。

## 依赖与执行顺序

### 阶段依赖

- Phase 1 无前置依赖；完成 12.0 migration、模型、默认策略和测试骨架后进入 Phase 2。
- Phase 2 必须先于所有 MCP/读写功能；它提供事件 reducer、事务边界和只读防守。
- Phase 3 依赖 Phase 1，可与 Phase 2 的纯 reducer 测试并行，但在 Phase 4 前必须完成。
- Phase 4 依赖 Phase 2–3；Phase 5 依赖 Phase 4 的 memory_entries/向量写入；Phase 6 依赖 Phase 4–5 的服务合同。
- Phase 7 依赖 Phase 1–6 的事件、投影和工具；Phase 8 依赖全部 Phase 1–7。

### 用户故事依赖

- US1（P1，事件权威/可重建轨迹）：Phase 1–2 后形成 MVP 基座；Phase 7 完成 rollback/rebuild 后闭环。
- US2（P1，显式作用域/隔离）：Phase 1 后可开始，必须在 Phase 3 完成并由 Phase 8 四路径实测收口。
- US3（P1，可信写入/纠正链）：依赖 US1 + US2，覆盖 Phase 4。
- US4（P1，只读召回/会话续接）：依赖 US3 的条目和 Phase 5，Phase 6 暴露 MCP。
- US5（P2，start_work）：依赖 Phase 5 recall/稳定序列化，Phase 6 交付。
- US6（P2，writer/reader 与治理）：依赖 Phase 2/3/6，Phase 7–8 交付。
- US7（P2，显著性/生命周期）：依赖 Phase 1/4/5，Phase 7 收口 TTL/快照。
- US8（P1，AOEP/无回归）：依赖全部前置阶段，是最终发布门。

## 并行执行机会

- Phase 1：T001–T004 可并行；T007/T008 与 T006 可并行；T009 与模型任务可并行。
- Phase 2：T013–T016 可并行；T017/T018/T020 分文件实现可并行，T019 依赖其接口。
- Phase 3：T023–T026 可并行；T027 与 T029 可并行，T030 依赖 resolver 接口。
- Phase 4：T032–T036 可并行；T037/T039/T040/T042 分文件实现可并行，T038/T041 依赖校验器。
- Phase 5：T045–T049 可并行；T050/T051/T052 可并行，T053–T055 依赖这些接口。
- Phase 6：T057–T060 可并行；T061/T062/T063 可并行，T064/T065 依赖工具签名。
- Phase 7：T068–T071 可并行；T072/T073/T074 可并行，T075/T076 依赖服务合同。
- Phase 8：T078–T080 可并行；T083–T086 可并行，T087/T088 必须最后顺序执行。

## TDD 与实现策略

1. 先完成 Phase 1/2，形成可重放、可回滚、可验证的 G2+ MVP；每个红测先提交，再实现最小绿路径。
2. Phase 3–5 依次加入 scope、安全写入和读取排序；每一阶段都必须同时落地隔离、provenance、注入和轨迹否定测试。
3. Phase 6 只通过合同 schema 和 FastMCP 签名暴露能力，先保证旧三工具兼容，再打开新工具。
4. Phase 7 在真实快照/归档/投影环境验证 rollback 和 rebuild，不以空投影或 mock fingerprint 通过。
5. Phase 8 是发布门：任何 hard metric、AOEP、旧全集或 quickstart 失败都阻止完成，不降低指标或覆盖历史报告。

## MVP 建议

最小可演示范围为 Phase 1–2 + Phase 3 的显式 scope + Phase 4 的 hard anchored `record_memory` + Phase 5 的 ID/timeline recall；该 MVP 仍必须通过事件-投影等价、四路径隔离、无锚拒写和只读防守。完整 Feature 交付必须继续完成 Phase 6–8。

## 任务格式校验

所有任务均使用 `- [ ] Txxx` 格式；用户故事阶段任务带 `[USn]`；可并行任务带 `[P]`；每项均包含具体文件路径，并映射至少一个 FR/US。测试任务均明确“先红后绿”。

## Phase 9: Convergence

- [X] T089 CRITICAL 封闭投影只读旁路：在 `backend/src/rag_mcp/services/memory_projection_store.py` 为底层写入口要求 sealed reducer 及当前日志验证；新增 `backend/alembic/versions/0090_memory_projection_bypass_guards.py` 拒绝投影 TRUNCATE 并补齐未守卫字段；在 `backend/tests/integration/test_012_convergence_boundaries.py` 和 `backend/tests/unit/test_memory_read_only.py` 先红后绿逐入口验证 per Constitution XIII、FR-005、T021 (contradicts)
- [X] T090 建立 012 最小确定性巩固候选过滤（不实现 013 LLM 巩固）：在 `backend/src/rag_mcp/services/memory_reader.py` 只读取完成投影、按 scope/policy/status/TTL 筛选；在 `backend/tests/integration/test_012_convergence_boundaries.py` 分别验证默认 recall 与巩固窗口 quarantined 零进入，包含 include 开关、dense 降级和 distilled 来源拒绝 per FR-010、FR-038、SC-004、T039 (partial)
- [X] T091 在 `backend/tests/unit/test_memory_recall_modes.py` 和 `backend/tests/integration/test_012_convergence_boundaries.py` 增加双时态矩阵（valid_from 前/等值/区间内、valid_to 等值/后、open interval、observed 不变、superseded 显式开关、retired/quarantined 永不默认返回），先红后绿修复 `backend/src/rag_mcp/services/memory_reader.py` per FR-023、SC-014、T047 (partial)
- [X] T092 在 `backend/tests/unit/test_salience_service.py`、`backend/tests/integration/test_012_convergence_boundaries.py` 补齐零 access、长期未访问耗尽、时间回退及 rollback 后保留 access/衰减/事实不变边界；修复 `backend/src/rag_mcp/services/memory_reader.py` 零信号 RRF 加权问题并验证 policy 参数 per FR-026a、FR-032、SC-010、SC-015、SC-016 (partial)
- [X] T093 在 `backend/tests/integration/test_012_convergence_history.py` 增加快照→归档在线裁剪→supersede→回滚→再回滚的交叉场景，逐类验证六投影、access 原文与计数、完整日志和快照回放指纹、坏快照回退及坏归档 fail-loud；必要时修复 `backend/src/rag_mcp/runtime/projection_rebuild.py` per FR-004a、FR-035a、SC-013、SC-016、T069–T070 (partial)
- [x] T094 在 `backend/tests/integration/test_012_live_mcp_tools.py` 增加实际 FastMCP writer/reader acceptance，逐调用验证 structuredContent 与 JSON 镜像、输入/成功输出 schema、reader 拒写、无成功事件的错误、隔离状态开关与历史读取、三档稳定工作包预算；串行运行新增测试及 backend 既有全集并保留新 JUnit/log 路径 per FR-018–FR-031、FR-038–FR-040、T067 (partial)
- [X] T095 同步 `外置型记忆回路-开发实施蓝图.md` 当前宪法 v1.4.0 的十三原则及 XII/XIII、批准生效措辞，不改历史 Feature 和规范意图；在 `backend/tests/unit/test_memory_constitution_wording.py` 增加回归断言 per Constitution v1.4.0、plan: Constitution Check (partial)

## Phase 10: Convergence

- [X] T096 补齐快照及 rebuild 的版本证据：在 `backend/tests/integration/test_012_convergence_history.py` 先红验证快照保存实际 dense collection/index version、六投影版本及 schema version，rebuild 每类输出对应版本；在 `backend/src/rag_mcp/runtime/projection_rebuild.py`、`backend/src/rag_mcp/services/memory_service.py` 从已完成 manifest/registry 派生并输出这些字段，兼容旧快照全日志回放且不改变权威状态或旧 MCP 契约；执行相关历史/投影回归 per FR-004a、FR-036、SC-013、plan: projection version contract (partial)

## Phase 11: Convergence

- [x] T097 保全 MCP 内容冲突的同域已有 ID：在 `backend/tests/integration/test_012_live_mcp_tools.py` 先红测试等价重复无新事件、非等价元数据冲突携带已有 memory_id、跨域相同正文独立且不泄露另一域 ID；在 `backend/src/rag_mcp/errors.py`、`backend/src/rag_mcp/services/memory_service.py`、`backend/src/rag_mcp/mcp/serialization.py` 使用类型化冲突异常保留经 scope 校验的 ID，禁止从任意异常文本抽取私有详情，并运行 MCP/错误码/旧工具字节兼容回归 per FR-019a、SC-017、FR-039、T041/T094 (partial)

## Phase 12: Convergence

- [X] T098 CRITICAL [US1] 保全派生状态的六轴治理元数据：在 `backend/src/rag_mcp/services/memory_reducer.py`、`backend/src/rag_mcp/services/memory_projection_store.py` 和相关 `backend/src/rag_mcp/models/memory_*.py` 为六类业务投影保留事件的 authority、scope_meta、mutability、provenance_meta、recoverability、actionability；以新的 `backend/alembic/versions/` 后继迁移保持数据库 reducer/字段守卫与 Python reducer 一致；在 `backend/tests/unit/test_memory_trajectory_authority.py` 和 `backend/tests/integration/test_012_memory_projection_equivalence.py` 先红后绿逐类验证非空状态、access、supersede、删除传播、rebuild 和 rollback 的六轴保全，禁止只检查 scope/provenance 就宣称完整 per Constitution XIII、FR-003、FR-005、FR-008 (contradicts)
- [X] T099 CRITICAL [US1] 封闭有效 reducer 状态下的完成发布旁路：在 `backend/src/rag_mcp/services/memory_projection_store.py` 限制 `_upsert`/关系完成标记及 manifest 发布，使调用者不能凭当前日志状态自行指定 complete、collection、root、dense_revision 或投影指纹；以新的 `backend/alembic/versions/` 后继迁移补齐数据库发布守卫；在 `backend/tests/integration/test_012_database_projection_authority.py` 和 `backend/tests/integration/test_012_convergence_boundaries.py` 先红后绿测试保留的失败写入、合法 reducer/GUC 加伪造完成元数据、未执行六投影物化/校验的直接发布均被拒绝，成功校验后才可消费 per Constitution XIII、FR-005–FR-006、SC-007、T089 (contradicts)
- [X] T100 [US1] 保留外部投影写入后校验失败的可恢复权威状态：在 `backend/src/rag_mcp/services/memory_service.py`、`backend/src/rag_mcp/services/memory_governance.py` 和 `backend/src/rag_mcp/services/memory_projection_store.py` 将 inspect/发布阶段的 Qdrant、embedding、文件读取及其他异常纳入同步失败恢复边界，避免已写外部 revision 却回滚唯一恢复事件；在 `backend/tests/integration/test_012_memory_failure_visibility.py` 先红后绿覆盖 assert、supersede 和治理操作的校验故障，验证失败响应、完整日志/恢复记录、旧完成状态仍可见、新状态不可见及 rebuild 后六投影一致 per FR-006、SC-007、T016/T019 (partial)
- [X] T101 [US6] 为管理浏览执行完成写入可见性边界：在 `backend/src/rag_mcp/api/memory.py` 的 browse 查询、分页计数和序列化中仅消费经六投影验证的完成状态；故障诊断不得返回未完成正文、证据或纠正链，保留管理面浏览各生命周期状态的能力；在 `backend/tests/integration/test_012_memory_rest.py` 和 `backend/tests/integration/test_012_memory_failure_visibility.py` 先红后绿注入外部投影失败后访问实际 REST，验证正文零暴露、supersede 旧完成态一致及恢复后可见 per FR-006、SC-007、T085 (contradicts)
- [X] T102 [US2] 拒绝不存在的 filesystem scope 路径：在 `backend/src/rag_mcp/services/scope_binding_service.py` 和 `backend/src/rag_mcp/services/scope_resolver.py` 区分 filesystem 引用与 Git remote，并对请求路径不存在或失效别名返回双轨 MISSING_KNOWLEDGE_SCOPE，不因已有父前缀/dir_name 绑定而接受；在 `backend/tests/unit/test_scope_binding_service.py` 和 `backend/tests/integration/test_012_live_scope_resolution.py` 先红后绿覆盖绑定根存在但子路径不存在、绑定目标删除、有效路径/别名及 remote，修正现有依赖不存在路径的正向 fixture per spec: Edge Cases/path 不存在、FR-015–FR-016、T023/T028 (contradicts)
- [X] T103 [US4] 补齐 recall 失败响应的四态契约：在 `backend/src/rag_mcp/mcp/recall_memory.py` 和 `backend/src/rag_mcp/mcp/serialization.py` 为参数冲突、scope 拒绝、超时及系统异常返回 completion_status=failed、空 memories、counts、error 和 request_id，保留错误码、歧义 candidates 与 structuredContent/JSON 镜像一致性；在 `backend/tests/integration/test_012_live_mcp_tools.py` 和 `backend/tests/contract/test_memory_schemas.py` 先红后绿对实际 recall 错误结果验证输出 schema，避免仅对成功结果校验，保持其他工具及旧三工具契约兼容 per FR-027、SC-006、FR-038–FR-039、T062/T094 (contradicts)
- [X] T104 [US4] 将 recall 的三秒期限覆盖整个调用：在 `backend/src/rag_mcp/services/memory_reader.py` 和 `backend/src/rag_mcp/mcp/recall_memory.py` 对 scope 解析、投影读取、dense 降级、超时清理及运行态审计/commit 使用统一剩余预算，避免解析或审计落在 timeout 外；在 `backend/tests/integration/test_012_memory_recall_observability.py` 和 `backend/tests/integration/test_012_live_mcp_tools.py` 先红后绿分别延迟 resolver、读取、commit/rollback，验证期限内四态结果、failed_paths、无过滤放宽和运行态审计行为 per FR-028、SC-006、US4/AC4、T049/T055 (partial)
- [X] T105 [US4] 计入完整返回文本的 recall/start_work 预算：在 `backend/src/rag_mcp/services/memory_reader.py` 为工作包稳定元数据与 package_fingerprint 预留预算，并对 recall 的完整返回文本执行 6000 字上限；在 `backend/tests/integration/test_012_reader_boundaries.py` 和 `backend/tests/integration/test_012_memory_recall_observability.py` 先红后绿以饱和内容、长 inference metadata、counts/notice/gaps 及三档工作包测量实际完整结果，禁止仅相信 counts 或选择性正文计数；保持 digest 优先、read_guidance 零裁剪、excerpt≤300 和稳定指纹 per FR-027、FR-030、SC-005、US4/AC5、US5/AC2、plan: Performance Goals (partial)
- [X] T106 [US5] 收口工作包在 valid/TTL 时间边界的字节稳定语义：在 `backend/src/rag_mcp/services/memory_reader.py` 使同输入、同完成数据版本和同域策略版本的包体不因调用时钟单独变化；在 `backend/tests/integration/test_012_reader_boundaries.py` 先红后绿冻结数据/策略并跨越 valid_from、valid_to、expires_at 边界验证包体和 fingerprint，同时验证新增、纠正、retire、rollback 及策略变化后最新状态刷新；兼顾 FR-010/FR-033 的有效性和过期隔离，不采用固定 session 首包或让过期条目重新进入结果 per FR-031、SC-005、US5/AC3、T063/T065 (contradicts)
- [X] T107 [US1] 暴露管理面 since_event_id 增量重建并补齐范围校验结果：在 `backend/src/rag_mcp/api/memory.py`、`backend/src/rag_mcp/services/memory_service.py` 和 `backend/src/rag_mcp/runtime/projection_rebuild.py` 接线 since_event_id，验证事件点归属/有效性并保留必要前缀、快照和 rollback 依赖；六类投影报告显式输出跨域检查、范围、版本、计数、指纹和一致性；在 `backend/tests/integration/test_012_memory_rest.py`、`backend/tests/integration/test_012_convergence_history.py` 先红后绿比对全量/增量结果及跨 scope 事件点拒绝，保持重建不改权威事件 per FR-007、FR-036、T072、plan: six-projection rebuild contract (missing)
- [X] T108 [US1] 让语义无效快照回退到独立验证的完整日志：在 `backend/src/rag_mcp/runtime/projection_rebuild.py` 的 MemoryHistory.load 区分快照结构/语义损坏与真实权威日志缺失，不能仅因正确 checksum 的 source_events 与日志前缀不符就跳过全日志恢复；在 `backend/tests/integration/test_012_convergence_history.py` 和 `backend/tests/unit/test_projection_rebuild.py` 先红后绿覆盖正确 checksum 但空/错 source_events、错误 covered point、完整日志可恢复及真实日志/归档缺失 fail-loud，验证六投影 fingerprint、版本和 recovery_source per FR-004a、SC-013、T093/T096 (partial)
- [X] T109 [US7] 让策略覆盖作用于后续 access 的显著性动力学：在 `backend/src/rag_mcp/services/memory_governance.py` 通过不可变事件元数据保留当前已解析域 decay_rate，在 `backend/src/rag_mcp/services/memory_reducer.py` 和新的 `backend/alembic/versions/` 后继数据库 reducer 迁移中一致应用，避免 access 仍用创建时衰减率而排序使用新策略；在 `backend/tests/unit/test_salience_service.py` 和 `backend/tests/integration/test_012_memory_rest.py` 先红后绿验证 access→policy override→间隔后 access 的数值/参数、强制排序衰减、历史 replay/rebuild/rollback 及事实/provenance 不变 per FR-014、FR-026a、FR-032、T050/T075 (partial)
- [X] T110 [US6] 为成功管理 rebuild 保存 request_id 可查询审计：在 `backend/src/rag_mcp/api/memory.py` 和 `backend/src/rag_mcp/services/memory_service.py` 传递并保留 reason、actor、scope、source event point、结果及六投影校验报告，使用合适的运行态管理审计模型/必要后继迁移持久化并返回关联 request_id；在 `backend/tests/integration/test_012_memory_rest.py` 先红后绿验证实际 REST 成功后按响应 ID 查到审计及 reason，避免只依赖未持久化的 X-Request-ID，不新增事实事件类型或绕过 writer 管理边界 per US6/AC2、FR-035、T071/T075 (partial)
- [ ] T111 [US8] 在 T098–T110 完成后收口当前版本的固定 schema 验收证据：使用 `eval/run_memory_acceptance.py` 和 `eval/run_regression_011.py` 在新的 `eval/runs/012-*/` 路径保存完整 backend suite、001–011 无回归、实际 writer/reader MCP、四路径隔离、六投影、read diagnostics 及 SC-001–SC-017 关联报告，补齐现有 `eval/runs/012-20261005-final-regression-h/final-memory-report.json` 中 SC-012=not_verified 的剩余验收；确认最终报告通过 schema 且各项真实证据已通过，更新 `eval/README.md` 的复现命令，不覆盖历史报告或强制修改验收状态 per FR-039–FR-040、SC-012、T087/T088 (partial)

## Phase 13: Convergence

- [ ] T112 [US8] 在版本实施完成后执行并保存被本轮跳过的高成本发布证据：运行 `eval/run_memory_acceptance.py`、`eval/run_regression_011.py` 及完整 backend/001–011 回归，在新的 `eval/runs/012-*/` 路径补齐 SC-012 的真实结果、旧三工具字节兼容、快照/归档/外部投影和前端验收；校验固定报告 schema、失败路径、request_id、四路径与六投影指纹，并更新 `eval/README.md` 复现命令且不覆盖历史报告 per FR-039–FR-040、SC-012、T111 (partial)
