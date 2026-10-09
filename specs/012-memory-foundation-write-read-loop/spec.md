# Feature Specification: 记忆基座与写读回路（G2+ 权威层）

**Feature Branch**: `012-memory-foundation-write-read-loop`

**Created**: 2026-10-04

**Status**: Delivered

**Input**: User description: "记忆基座与写读回路（G2+ 权威层）：事件日志为唯一权威，新表 memory_events（append-only，永久不 UPDATE/DELETE；event_type ∈ assert|revise|retract|consolidate|access|grant|rollback；aggregate_id=memory_id；knowledge_scope_id NOT NULL 隔离键；payload JSONB；六轴元数据 authority/scope/mutability/provenance/recoverability/actionability；actor/session_id/request_id；occurred_at 系统时间 + valid_from/valid_to 事实时间；索引 (scope_id, aggregate_id, occurred_at)）；日志分段；六类派生投影可重建且只读；同事务物化；关系投影 DDL；三个 MCP 新工具 start_work、recall_memory、record_memory；五形态 scope_ref；分级信任校验；显著性动力学；治理、TTL、配额、遗忘阶梯、回滚、管理 REST、评测与硬性约束。"

## Scope Basis and Compatibility

本 Feature 依据《外置型记忆回路-开发实施蓝图》§2、§3、§4、§5、§7、§9、§10，
《外置型记忆回路演进蓝图》§3.1–§3.4、§3.7、ADR-1/2/3/7/8，长期记忆选型调研
中的 Q1–Q10、Q16–Q30、Q36、Q41–Q44、Q47、Q48，以及台账 ①–⑦ 全节点。宪法
v1.4.0 已批准并作为本 Feature 的约束基线。

本 Feature 建立 G2+ 事件权威层、关系/向量/显著性基础投影、读写 MCP 回路、scope
绑定、最小治理与回滚能力。六类投影在本 Feature 中均交付可运行的最小实现，包含
类型化链接图、层级摘要树和文件镜像的事件接口、重建、删除传播、回滚与隔离验证；
高级抽取、摘要生成、巩固、高级消费和文件异步刷新由 013/014 实现。所有投影
仍不得成为独立事实源。既有 `search_knowledge`、`get_evidence`、
`list_knowledge_domains` 和旧客户端行为逐字节兼容。

## 对照评测声明

本 Feature 无检索质量对照评测。它是新能力面，沿用 006/007 的工程特例范式，
验收重点是记忆写读功能、状态轨迹正确性、隔离与安全硬指标、AOEP 状态义务和既有
全集无回归。不得以新增记忆召回能力宣称既有语料检索质量提升。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 事件权威与可重建轨迹 (Priority: P1)

平台运维者需要知道每个记忆状态从何而来、何时有效、谁作出改变，并能在投影损坏或
迁移后由事件轨迹恢复完整状态。所有新增、纠正、撤回、巩固、访问、授权和回滚都
必须追加事件；关系表、向量、链接图、摘要树、文件镜像和显著性只是可重建的只读
视图。

**Why this priority**: 没有单一权威，跨域隔离、删除传播、回滚审计和恢复都无法证明。

**Independent Test**: 写入并纠正同一记忆，尝试直接更新或删除事件和投影，执行各类投影重建并比对指纹。

**Acceptance Scenarios**:

1. **Given** 一个已解析的知识域，**When** 新记忆成功写入，**Then** 系统追加一个 `assert` 事件并在同一成功边界内物化关系、向量和显著性初始状态。
2. **Given** 一个已有记忆，**When** 发生纠正或撤回，**Then** 只追加 `revise` 或 `retract` 事件，旧事件和旧正文不被 UPDATE/DELETE。
3. **Given** 任一投影被清空或版本变化，**When** 运行投影重建及一致性校验，**Then** 六类投影均可从事件日志恢复并输出数量、范围和指纹。
4. **Given** 管理员选择时间点或事件点，**When** 执行回滚，**Then** 系统重放到该点并追加带前后指纹和影响面的 `rollback` 事件；MCP 不能触发回滚。

### User Story 2 - 显式作用域与跨域隔离 (Priority: P1)

Agent 或管理工具必须显式指定一个或多个知识域。记忆条目只属于一个域；会话可跨域活动但不改变记忆隔离。支持数字 ID、slug、`type:name` 和 `path:`（绝对工作目录或 Git remote）引用。

**Why this priority**: 作用域是宪法原则 I 的唯一隔离键；任何回落到最近域或全库都会造成串库。

**Independent Test**: 为两个域登记相邻路径和 remote 绑定，分别执行写入、按 ID/查询/路径召回，并覆盖无命中与并列命中。

**Acceptance Scenarios**:

1. **Given** 唯一匹配的 scope 引用，**When** 调用记忆工具，**Then** 事件、关系、向量和文件路径保持同一 `knowledge_scope_id`。
2. **Given** `path:` 无绑定或同层级同优先级多命中，**When** 调用工具，**Then** 分别返回 `MISSING_KNOWLEDGE_SCOPE` 或 `AMBIGUOUS_DOMAIN_REF` 及候选，绝不回落。
3. **Given** A、B 两域各有记忆，**When** 在 B 域召回 A 域内容，**Then** 四路径串库数均为零。
4. **Given** MCP 客户端尝试写 `scope_bindings`，**When** 请求到达，**Then** 请求被拒绝；绑定只能由管理面通过 `grant` 事件物化。

### User Story 3 - 分级可信写入与纠正链 (Priority: P1)

Agent 可以记录 episodic、semantic 或 procedural 记忆。硬记忆必须绑定已发布且同域的证据；软记忆必须公开来源、置信度、模型版本、时间和支撑证据字段；纠正通过 supersede 链完成。脱敏先于落库，注入高危条目隔离。

**Why this priority**: 记忆同时承载事实、推断和行动经验；没有 provenance，召回结果不能安全影响后续推理。

**Independent Test**: 对 hard/soft 提交完整和缺失元数据、跨域证据、凭据和高危注入内容，验证拒绝码、隔离状态和投影。

**Acceptance Scenarios**:

1. **Given** hard 记忆缺少证据或证据不存在、跨域或未 published，**When** 写入，**Then** 返回 `MEMORY_EVIDENCE_ANCHOR_REQUIRED` 或 `MEMORY_EVIDENCE_SCOPE_MISMATCH`，不产生成功事件。
2. **Given** soft 记忆缺少五元 inference metadata 或 confidence 不在 [0,1]，**When** 写入，**Then** 返回 `MEMORY_INFERENCE_META_INCOMPLETE` 或 `MEMORY_PROVENANCE_INVALID`。
3. **Given** 内容含凭据或注入高危模式，**When** 管线运行，**Then** 凭据先替换为类型化占位符，高危条目标记 `quarantined`，默认召回和巩固排除。
4. **Given** active 记忆属于同一 scope，**When** 以 `supersedes_memory_id` 纠正，**Then** 追加 `revise` 事件、关闭旧有效期并建立单指针链；非法目标返回 `MEMORY_SUPERSEDE_TARGET_INVALID`。

### User Story 4 - 只读召回与会话续接 (Priority: P1)

调用者可以按 ID、时间线、结构过滤或语义查询读取记忆，并知道结果是否完整、降级或被裁剪。无 query 走时间线/结构，有 query 才走 dense 候选、关系后置核验和加权 RRF。默认不返回 superseded、retired 或 quarantined。

**Why this priority**: 读路径必须在可预期预算内给出可消费结果，并显式报告失败和缺口。

**Independent Test**: 建立多 session、agent、kind、supersede 和隔离态数据集，运行四种召回、as-of、预算裁剪、Qdrant 不可用和超时场景。

**Acceptance Scenarios**:

1. **Given** `memory_ids` 与 `query` 仅传其一，**When** 调用 `recall_memory`，**Then** 按 ID 顺序或确定性时间线/结构排序返回；非语义模式不访问 Qdrant。
2. **Given** 同时传 `memory_ids` 和 `query`，**When** 调用召回，**Then** 返回 `MEMORY_IDS_QUERY_CONFLICT` 且不放宽查询。
3. **Given** 有 query 的语义召回，**When** dense 候选返回，**Then** 强制下推 scope，在关系投影后置核验状态、时间和 agent，再按 dense、recency、kind、带衰减 salience 做加权 RRF；Qdrant 不接收 status 过滤。
4. **Given** dense 服务超时或不可用，**When** 召回在 3 秒内结束，**Then** 返回 `partial`、`failed_paths` 和可用结构结果；不改变原过滤条件。
5. **Given** 返回正文超过预算，**When** 裁剪，**Then** excerpt 最多 300 字并标记 truncated，counts 暴露候选数、返回数和裁剪原因；显式召回无硬阈值。

### User Story 5 - 会话开局工作包 (Priority: P2)

Agent 可以请求 `start_work`，得到域简介、稳定事实摘要、工作集和读取指引。调用纯只读、不写 session、不落盘包快照；包体与易变信封分离以保持字节稳定。

**Why this priority**: 工作包提供低成本、可缓存的常驻层上下文。

**Independent Test**: 对同一 scope/session 请求 standard、compact、minimal，比较重复调用包体字节并验证 2 秒超时。

**Acceptance Scenarios**:

1. **Given** 可解析的 scope，**When** 请求 `start_work`，**Then** 返回 scope、domain_brief、digest、working_set、read_guidance、package_fingerprint、counts 和 request_id。
2. **Given** 三档 budget，**When** 组装工作包，**Then** 包体分别不超过 2000、800、300 字；digest 优先，read_guidance 永不裁剪。
3. **Given** 相同输入且数据和域策略版本相同的重复请求，**When** 排除信封易变字段比较，**Then** 包体字节完全一致，且不产生包快照或写入事件；数据或域策略变化后重新组装最新工作包，包体内容变化时 package_fingerprint MUST 随之变化。
4. **Given** 2 秒内无法完成，**When** 超时，**Then** 返回可识别失败或降级状态，不阻塞显式召回。

### User Story 6 - writer/reader 边界与治理 (Priority: P2)

writer 实例写入记忆，reader 实例提供只读召回和运行态审计。管理者可以浏览、retire、显式 purge、触发重建和回滚；普通 MCP 不能执行治理动作。

**Why this priority**: 单写者/多读者模型必须阻止读实例或不受信任内容绕过治理边界。

**Independent Test**: 分别启动 writer/reader，检查工具清单、写请求错误、管理 REST 权限和治理审计事件。

**Acceptance Scenarios**:

1. **Given** reader 实例，**When** 请求 `record_memory`，**Then** 工具未注册或返回 `MEMORY_WRITE_UNAVAILABLE`，不追加事件。
2. **Given** 管理面执行 retire、purge、重建或回滚，**When** 成功，**Then** 结果可按 request_id 审计；purge 不静默删除所需墓碑和审计轨迹。
3. **Given** 普通 MCP 请求 grant、绑定变更或 rollback，**When** 到达，**Then** 请求被拒绝且不产生对应成功事件。

### User Story 7 - 运行态显著性与生命周期 (Priority: P2)

系统可以记录访问事件并更新显著性，但显著性只能影响留存、调度和带强制衰减的排序，不能改写事实、provenance、valid 时间线或 supersede 链。域管理员可配置配额、TTL、巩固开关、RRF 权重和衰减率；超配额 fail-loud。

**Why this priority**: 访问反馈能改善召回与遗忘顺序，但不能把高频使用误当成事实权威。

**Independent Test**: 生成 access 事件并执行衰减，比较排序；触发 TTL、遗忘阶梯和配额边界，核对状态、审计和传播。

**Acceptance Scenarios**:

1. **Given** recall/deep-read/attached/package access，**When** 记录访问，**Then** 追加 `access` 事件并更新显著性计数、时间、强化时间和衰减率，不改正文或信任等级。
2. **Given** salience 参与排序，**When** 强制衰减未执行，**Then** salience 不得参与排序；衰减后才可按域权重参与 RRF。
3. **Given** 数据达到运行态、access、episodic、semantic/procedural 保留期限，**When** maintenance 运行，**Then** 按 7 天、90 天、180 天、永生策略和 active→压缩→归档→墓碑阶梯处理。
4. **Given** scope 配额已满，**When** 写入新记忆，**Then** 返回 `MEMORY_QUOTA_EXCEEDED`，不静默驱逐或降级既有条目。

### User Story 8 - AOEP 状态义务与无回归 (Priority: P1)

发布负责人需要证明回滚可溯、删除传播、权威边界和范围不扩张，并保证 001–011 全集和旧三工具不变。

**Why this priority**: 这组状态义务是 G2+ 发布门槛，单次写读不能证明长期状态正确。

**Independent Test**: 在真实数据库、向量和文件环境运行 8 项记忆 E2E、AOEP 套件以及旧评测。

**Acceptance Scenarios**:

1. **Given** 八项记忆 E2E，**When** 全量运行，**Then** 每项都有 request_id、状态、指纹和可复现通过记录。
2. **Given** 四类 AOEP 用例各至少两条，**When** 运行，**Then** 日志、投影和管理审计均满足状态义务。
3. **Given** 001–011 既有全集和旧三工具客户端，**When** 重跑，**Then** 无回归，旧响应逐字节不变；新增字段仅在新工具或显式新参数出现。

### Edge Cases

- scope_ref 为空、不识别、路径不存在、绑定 disabled 或并列最高优先级时，一律拒绝并使用双轨作用域错误；不使用 session primary scope 回落。
- 绝对路径同时匹配短、长前缀时先取最长前缀，再取 priority；仍多命中则返回候选。
- session 可先后访问多个域；primary scope 仅默认值，不是隔离轴，也不触发已取消的 `MEMORY_SESSION_SCOPE_CONFLICT`。
- 脱敏后为空、超过 4000 字、kind 越界、调用者指定 status 或 tags 不可序列化时，无部分事件地拒绝。
- 同 scope 内相同脱敏正文的重复提交，MUST 在 scope、脱敏和 provenance 校验通过后比较规范化提交元数据；一致则返回已有 memory_id 和当前 status，不追加事件、不更新 session 或显著性、不重启 TTL。元数据不一致返回 `MEMORY_CONTENT_CONFLICT` 及同域已有 ID；已有写入未完成时返回可识别失败，不能作为成功重试或开放读取；retired/superseded/quarantined 条目不因重复提交恢复 active。
- 证据在校验期间失效、supersede 目标并发撤回、配额在事务中耗尽、向量写入失败或投影事务失败时，不能返回看似成功但不可恢复的 memory_id。
- 事件和关系状态已落库但向量或其他同步投影失败时，调用 MUST 返回失败；未完成写入 MUST 对所有召回和工作包路径不可见。恢复流程补齐并校验全部同步投影后才开放读取；若写入包含 supersede，纠正链切换前旧状态仍可见，不得提前隐藏旧记忆。
- `include_superseded=true` 只能展示纠正链；`include_delivered=true` 只能覆盖会话去重，不得包含 retired/quarantined 默认结果。
- `as_of` 只作用于事实有效线：条目在 `valid_from <= as_of < valid_to`（开放 `valid_to` 视为无穷）时可见；被 supersede 的旧条目只在其 valid 区间内、且调用者显式 `include_superseded=true` 时可见。`as_of` 不改变 observed 审计线。无有效条目、全部被 delivered 去重或预算裁剪为空时，使用四态 completion_status 和 gaps，不放宽筛选。
- access 高频段超过 90 天时仅移出在线存储并归档，事件原文永久保留；运行态审计保留 7 天。日志截断仅指已校验归档后的在线段裁剪，不能删除任何类型的事件或依赖链。快照缺失或损坏时可从完整在线及归档日志重放；若日志不完整或校验失败，必须 fail-loud。
- 投影暂时不可用时，关系投影可提供标注为 partial 的结果，但不得跨域或绕过 provenance/status 后置核验。

## Requirements *(mandatory)*

### Functional Requirements

#### 权威日志与投影

- **FR-001**: 系统 MUST 将 `memory_events` 作为唯一权威写入点；事件 MUST append-only，永久禁止 UPDATE/DELETE 语义。
- **FR-002**: `event_type` MUST 仅接受 `assert`、`revise`、`retract`、`consolidate`、`access`、`grant`、`rollback`；`aggregate_id` MUST 指向 memory_id，`knowledge_scope_id` MUST NOT NULL。
- **FR-003**: 每个事件 MUST 保存 JSONB payload、六轴元数据、actor、session_id、request_id、不可变 occurred_at 系统时间和 valid_from/valid_to 事实时间。
- **FR-004**: 系统 MUST 建立 `(knowledge_scope_id, aggregate_id, occurred_at)` 和 `(knowledge_scope_id, event_type, occurred_at)` 索引；所有类型事件原文 MUST 永久保留且不可变，旧段可移出在线存储并归档，access 段 TTL 90 天仅限制在线保留；快照、归档和在线段裁剪 MUST 可审计，裁剪前 MUST 验证归档完整性。
- **FR-004a**: 日志快照 MUST 默认按每 10,000 个权威事件或 24 小时（先到者）执行，并带快照 event_id、时间、六类投影指纹和 schema/index 版本；快照仅加速恢复，不替代事件权威。截断 MUST 仅指移出在线存储并归档后的在线段裁剪，禁止删除事件原文。rebuild MUST 可从最近有效快照加增量事件恢复，也可从完整在线及归档日志全量重放；快照缺失或校验失败时 MUST 尝试完整日志重放，日志不完整或校验失败则 fail-loud，不能声称完整恢复。
- **FR-005**: 关系、dense 向量、链接图、摘要树、文件镜像和显著性场 MUST 是只读、可重建派生投影，不得成为事实源；六类投影 MUST 在 012 中交付可运行的最小实现，支持事件派生、重建、删除传播和回滚。所有六类投影的运行时写入口 MUST 仅接受 reducer 产物，禁止直接写事实或旁路 UPDATE/DELETE；验收 MUST 对每一类投影分别验证非空数据、状态变更、删除传播、回滚结果和可重建 fingerprint，不得以仅定义接口、空实现或空指纹声明通过。六类业务投影固定为 relation、dense vector、typed links、summary tree、file mirror、salience；projection metadata/status registry 不计入六类。高级抽取、摘要生成和文件异步刷新由 013/014 交付。
- **FR-006**: 成功写入 MUST 在同一成功边界内追加事件并更新同步投影；不得暴露最终一致性窗口。若事件或任一六类投影已落库但其他同步投影失败，MUST 返回失败并保留可恢复状态；事件、关系、向量、链接、摘要、文件和显著性六类投影在全部补齐且一致性校验通过前 MUST 对所有读路径不可见，恢复完成后才开放读取。写入完成状态 MUST 独立于 active/superseded/retired/quarantined 生命周期状态；supersede 的新旧状态切换 MUST 遵守同一可见性边界。
- **FR-007**: retract、retire、purge 和 rollback MUST 传播到六类投影；重建工具 MUST 支持全量或 since_event_id 重放并输出各投影一致性校验。
- **FR-008**: 系统 MUST 强制并分别验证五项不变量：权威单调（只能追加事件、不得重写历史）、范围不扩张（派生结果不得超出请求 scope 并集）、删除传播（retract/retire/purge/rollback 在六类投影同步生效）、provenance 保全（事件到所有投影的来源链不可丢失或伪造）和回滚可溯（管理面 rollback 自身追加事件并保留 reason、impact、前后 fingerprint）。任一不变量失败 MUST 阻止发布。

#### 关系投影与生命周期

- **FR-009**: `memory_entries` MUST 包含 memory_id、knowledge_scope_id、kind、provenance、title、脱敏 content_text（≤4000）、scope 内唯一 content_hash、evidence_refs、inference_meta、confidence、status、supersede 双指针、双时态四时间戳、session/agent/task_context、injection_flags 和 promote_candidate_at。
- **FR-010**: status MUST 仅接受 active、superseded、retired、quarantined；默认读取只回 active 且有效条目，superseded 仅显式包含，quarantined 不得进默认召回或巩固。
- **FR-011**: `scope_bindings` MUST 支持 workdir_prefix、git_remote、dir_name，保存 binding value、scope、priority、状态，并保证 `(binding_kind,binding_value)` 唯一；MCP 不能写它。
- **FR-012**: `sessions` MUST 记录 session、agent、primary_scope_id、起止活动、状态和过期时间；primary scope 仅默认值。
- **FR-013**: `memory_recall_runs` MUST 以 7 天 TTL 记录 request_id、tool、channel、session、scope、mode、返回数、包指纹、降级、失败路径、耗时和过期时间。
- **FR-014**: `domain_profiles.memory_policy` MUST 支持 kind TTL、per-scope quota、consolidation_enabled、RRF 权重、三档 start_work budget、attach_min_score 和 decay_rate。
- **FR-014a**: 首期默认 `memory_policy` MUST 为 `episodic_ttl_days=180`、`semantic_procedural_ttl_days=null`（永生）、`per_scope_memory_quota=5000`、`decay_rate=0.05/day`、`rrf_weights={dense:1.0,recency:0.5,kind:0.3,salience:0.2}`；内置 se-project、generic、personal、legal 四档案使用相同默认值，自定义域可由管理面显式覆盖并审计。

#### scope 解析与隔离

- **FR-015**: 五种 scope_ref MUST 为数字 ID、slug、type:name、path:<绝对路径>、path:<git remote>；解析顺序和双轨错误码稳定。
- **FR-016**: path MUST 通过 bindings 做最长前缀、priority、唯一命中；无命中或歧义必须拒绝并返回候选，不得回落。
- **FR-017**: 写入绑定恰好一个 scope；多域读取必须显式声明，事件、关系、向量和文件路径必须保留 scope，四路径串库硬指标为零。

#### record_memory

- **FR-018**: `record_memory` MUST 仅在 writer 注册，annotations 为 readOnlyHint=False、destructiveHint=False、idempotentHint=False；reader 不得提供。
- **FR-019**: 输入 MUST 支持 scope_ref、kind、content、provenance、evidence_refs、confidence、title、tags、session_id、agent_id、task_context、supersedes_memory_id；成功输出含 memory_id、status、provenance_validation、injection_flags、request_id。
- **FR-019a**: 系统 MUST 在同 scope 内对相同脱敏正文实施重复提交判定。通过当前 scope、脱敏和 provenance 校验后，kind、provenance、evidence_refs、inference_meta、confidence、title、tags、session_id、agent_id、task_context、supersedes_memory_id 等规范化提交元数据均一致时，MUST 返回已有 memory_id 和当前 status，且不追加事件或改变状态、session、显著性和 TTL；缺省字段按相同默认规则规范化，request_id 和系统生成时间不参与等价判定。元数据不同 MUST 返回 `MEMORY_CONTENT_CONFLICT` 及同域已有 memory_id，不静默合并。已有写入未完成时 MUST 按 FR-006 返回失败；并发等价提交最终 MUST 只有一个 memory_id 和一组权威写入事件。
- **FR-020**: 管线 MUST 按九步执行：scope、脱敏、provenance、注入、supersede、配额/TTL、事件与关系同事务、向量、session；任一步失败禁止成功响应，未完成写入按 FR-006 保持不可见，由恢复流程补齐并校验后开放读取。
- **FR-021**: hard 必须有至少一条逐条复验存在、同域、published 的 evidence_refs，并对每条 evidence 执行内容、source ID、version、position 的 item-by-item attribution re-verification；soft 必须有来源、confidence、模型版本、时间、支撑证据五元 metadata；distilled 必须有可逐条追溯的源链并保留其推导关系。hard 锚定率和逐条归因复验率均为 100%，soft 五元 metadata 完备率和 distilled 源链完整率均为 100%。
- **FR-022**: 错误枚举只增不删，至少包含 `MEMORY_EVIDENCE_ANCHOR_REQUIRED`、`MEMORY_EVIDENCE_SCOPE_MISMATCH`、`MEMORY_INFERENCE_META_INCOMPLETE`、`MEMORY_PROVENANCE_INVALID`、`MEMORY_KIND_INVALID`、`MEMORY_SUPERSEDE_TARGET_INVALID`、`MEMORY_CONTENT_CONFLICT`、`MEMORY_QUOTA_EXCEEDED`、`MEMORY_WRITE_UNAVAILABLE`、`MEMORY_IDS_QUERY_CONFLICT`、`MEMORY_ROLLBACK_FORBIDDEN`、`MEMORY_TIMEOUT`、`SYSTEM_ERROR`；不得重新引入 `MEMORY_SESSION_SCOPE_CONFLICT`。

#### recall_memory

- **FR-023**: `recall_memory` MUST 为只读工具，接受多域 scope_ref、query、memory_ids、kind、session_id、agent_id、time_window、as_of、include_superseded、include_delivered、limit；limit 默认 10、上限 50，memory_ids 与 query 互斥。
- **FR-024**: 无 query 的 ID、时间线、结构模式 MUST 绕开 Qdrant；有 query 时 MUST dense→PG 后置核验→加权 RRF，过召回至少 limit×4 且不低于 40。
- **FR-025**: Qdrant MUST 强制下推 scope，kind/session 可下推；status、valid time、agent、阈值在 PG 后置核验；status 不得下推 Qdrant。
- **FR-026**: 排序可组合 dense、recency、kind、salience；salience 仅在强制衰减执行后参与，不改事实/provenance；显式召回无硬阈值。
- **FR-026a**: 无 access 记录的 memory MUST 以 `salience=0` 冷启动；`β` 衰减和 `γ` 强化系数 MUST 从已解析域的 `decay_rate` 派生，首期按 `β=0.05/day`、`γ=1.0/access` 执行，参数来源为 domain policy 默认值或管理面覆盖；默认 RRF salience 权重首期启用为 0.2，015 可依据评测调优，但不得在无衰减时启用。
- **FR-027**: 输出 MUST 含 completion_status（complete/partial/no_evidence/failed）、memories、counts、可选 notice/gaps/error、request_id；预算≤6000字，excerpt≤300字并标记 truncated。
- **FR-028**: recall 超时预算 3 秒；dense 失败或部分投影不可用时返回 failed_paths 和降级结果，不扩大 scope、取消过滤或混入 quarantined。

#### start_work

- **FR-029**: `start_work` MUST 为纯只读，接受 scope_ref、session_id、task_hint、agent_id、include=both、budget=standard|compact|minimal，不写 session 或包快照。
- **FR-030**: 输出 MUST 含 scope、domain_brief、digest、working_set、read_guidance、package_fingerprint、counts、request_id；预算分别≤2000/800/300字，digest 优先，read_guidance 永不裁剪。
- **FR-031**: 包体 MUST 不含 request_id、生成时间等易变信封字段；相同输入且数据和域策略版本相同时，包体 MUST 字节稳定，不得仅因调用时钟或请求审计变化而改变。数据或域策略版本变化后 MUST 重新组装最新工作包，包体内容变化时 package_fingerprint MUST 随之变化；不得以 session 固定首次包体。无需新增显式版本参数或包快照存储；超时预算 2 秒。

#### 显著性、TTL、治理

- **FR-032**: `memory_salience` MUST 保存 salience、access_count、last_access_at、reinforced_at、decay_rate；access 在线保留 TTL 90 天，到期归档且事件原文永久保留，显著性含 recency 和 −βI+γA 强制衰减。
- **FR-033**: 分层 TTL MUST 为运行态 7 天、access 在线保留 90 天、episodic 默认 180 天、semantic/procedural 默认永生，允许域策略覆盖；TTL、遗忘和 purge MUST 不删除事件原文，维护不得静默越过配额或清除审计轨迹。
- **FR-034**: 遗忘阶梯 MUST 支持 active→压缩→归档→墓碑；墓碑和撤回退出默认召回、巩固、向量、文件、摘要路径，历史事件仍可审计。
- **FR-035**: 管理 REST MUST 至少提供浏览、retire、显式 purge、重建触发和回滚；rollback 仅管理面发起并含依据、影响面、前后指纹；MCP 不提供回滚。
- **FR-035a**: rollback MUST 只接受单一 `knowledge_scope_id` 和时间点或事件点；跨 scope 请求必须返回 `MEMORY_ROLLBACK_FORBIDDEN`。回滚只重放权威状态事件，不撤销或重写 `access` 事件；文件镜像、摘要树和其他投影必须从回滚点重建。若目标点与 supersede 链冲突，以目标事件点的事件顺序为唯一仲裁：目标点之前的 supersede 生效，之后的 revise/retract 在回滚状态中不可见但保留在日志中，回滚事件记录受影响链和前后指纹。
- **FR-036**: 重建 MUST 支持六类投影，输出范围、版本、计数、指纹、跨域检查和一致性结果；不得直接写权威日志。

#### 评测与兼容性

- **FR-037**: 必须提供 8 项 E2E：硬锚闭环、无锚拒写、跨域隔离、supersede、注入隔离、TTL/配额、reader 无写、会话时间线，并补充 AOEP 回滚、删除传播、权威边界、范围不扩张用例。
- **FR-038**: 混合域验收 MUST 实测跨域串库=0、MCP schema 合法率=100%、provenance 完备率=100%、hard 锚定率=100%、hard 逐条归因复验率=100%、soft 五元 metadata 完备率=100%、distilled 源链完整率=100%、quarantined 进入默认召回和巩固窗口次数=0。
- **FR-039**: 001–011 全集 MUST 重跑且无回归；旧三工具和旧客户端 MUST 逐字节不变，新字段仅在新工具或显式新参数出现。
- **FR-040**: 评测 MUST 按固定报告 schema 记录双实例结果、四路径隔离证据（event log、relation、vector、file）、显式多域并集结果、失败路径、request_id、包/投影指纹和环境信息，报告保存于不覆盖历史报告的路径。

### Key Entities *(include if feature involves data)*

- **Memory Event**: 唯一权威的不可变记忆轨迹，承载事件、scope、六轴元数据、时间和行动者。
- **Memory Entry**: 事件物化的当前关系状态，含分型、provenance、双时态、纠正链和生命周期。
- **Knowledge Scope**: 唯一隔离单元；记忆恰好属于一个域，多域读取必须显式声明。
- **Scope Binding**: 管理面维护的路径/Git remote/目录到 scope 的绑定，按最长前缀与 priority 解析。
- **Session**: 记忆活动的续接登记，不是隔离轴，可跨域活动。
- **Memory Salience**: access 事件派生的衰减反馈，只影响排序、留存和调度。
- **Memory Recall Run**: 7 天 TTL 的运行态审计，含模式、数量、降级、耗时和包指纹。
- **Projection Set**: 关系、向量、链接、摘要、文件、显著性六类只读可重建视图。
- **Memory Policy**: 域档案中的 TTL、配额、巩固、排序预算、附加阈值和衰减配置。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 8 项 Feature E2E 与 4 类 AOEP 状态义务用例全部通过，且每项有 request_id、状态、指纹和可复现记录。
- **SC-002**: 事件、关系、向量、文件四路径跨域泄漏为 0；显式多域请求仅返回请求并集条目。
- **SC-003**: 成功写入 provenance 完备率 100%，hard evidence 锚定率 100%；无锚 hard 写入不得产生成功事件。
- **SC-004**: quarantined 进入默认 recall 或巩固窗口次数为 0；凭据原值进入四路径次数为 0。
- **SC-005**: start_work 三档包体分别≤2000/800/300字，相同输入且数据和域策略版本相同时包体字节稳定率100%，单纯调用时钟或请求审计变化不改变包体；新增、纠正、retire、rollback 或策略变更后工作包反映最新状态的正确率100%，包体变化时指纹变化率100%；read_guidance 裁剪次数为0，超时不超过2秒。
- **SC-006**: recall 在3秒内返回四态之一；ID/timeline/结构过滤不调用 Qdrant，语义路径 scope 后置核验覆盖率100%。
- **SC-007**: 事件追加与同步投影不存在可观测最终一致性窗口；在事件和关系状态落库后注入向量或其他同步投影故障，失败响应率100%、未完成写入被召回或进入工作包次数为0；恢复补齐并校验后可见性正确率100%，supersede 未完成时旧状态保持可见率100%，不得产生不可恢复的孤儿状态。
- **SC-008**: 六类投影均以非空数据及状态变更验证重建、删除传播和回滚；投影重建后计数、scope 分布、删除传播、provenance 链和指纹与事件回放一致率100%；仅有接口或空实现的投影不得计为通过。
- **SC-009**: reader `record_memory` 暴露次数为0，普通 MCP 回滚成功次数为0，scope_bindings 被 MCP 写入次数为0。
- **SC-010**: access 事件全部受90天在线保留 TTL管理，到期归档后事件原文完整率100%、物理删除次数为0；未执行强制衰减时 salience 参与排序次数为0；salience 不改变事实、provenance、时间线或纠正链。
- **SC-011**: 四个内置域的默认策略均为 episodic 180 天、semantic/procedural 永生、每域配额 5000、decay_rate 0.05/day 和 RRF 权重 1.0/0.5/0.3/0.2；超配额写入拒绝率100%，semantic/procedural 默认不因TTL静默清除。
- **SC-013**: 快照按 10,000 个权威事件或 24 小时先到者生成；在线段裁剪后，从快照加增量事件 rebuild 与从完整在线及归档日志全量重放的六类投影指纹一致率为 100%，所有类型事件零丢失；快照缺失或损坏时完整日志重放恢复成功率100%，日志不完整或校验失败时拒绝完整恢复声明率100%。
- **SC-014**: `as_of` 查询在 valid 时间线上的可见性矩阵 100% 通过：旧 superseded 条目仅在其 valid 区间且显式 include_superseded 时返回，observed 线不被 as_of 改写。
- **SC-015**: salience 冷启动值为 0、默认衰减为 0.05/day、强化系数为 1.0/access；无衰减参与排序次数为 0，首期 salience RRF 权重为 0.2。
- **SC-016**: 跨 scope rollback 成功次数为 0，access 事件被回滚或删除次数为 0；rollback 后文件镜像和其他投影重建指纹与目标事件点一致率为 100%。
- **SC-017**: 同 scope 等价重复提交（含并发）复用同一 memory_id 比例100%，新增重复事件及状态/TTL/session/显著性变更次数为0；相同正文但提交元数据不同的请求冲突拒绝率100%；未完成写入被重复提交转为成功响应次数为0，非 active 条目因重复提交恢复 active 次数为0；不同 scope 的相同正文独立处理且不泄露对方 ID。
- **SC-012**: 001–011 全集通过，非延迟结果在既有容差内，旧三工具和旧客户端响应逐字节不变。

## 范围内 / 范围外

### 范围内

- G2+ `memory_events`、六轴元数据、双时态、事件分段、索引和不可变约束。
- `memory_entries`、`scope_bindings`、`sessions`、`memory_salience`、`memory_recall_runs` 和 `domain_profiles.memory_policy`。
- 六类投影的可运行最小实现，以及只读、可重建、删除传播、回滚和一致性契约；本 Feature 同步物化关系、dense 向量和显著性，链接图、摘要树和文件镜像也须通过非空数据及状态变更验收，后续 Feature 按契约接入高级生成与消费。
- 三个 MCP 工具及 writer/reader 边界、五形态 scope_ref、绑定解析、信任校验、脱敏、注入隔离、supersede、配额、TTL、遗忘、治理 REST、回滚和验收。

### 范围外

- 013 的 LLM 巩固提议、类型化链接图高级抽取、摘要生成与受益闸门；本 Feature 定义 consolidate 事件和投影接口，并交付六类投影最小实现。
- 014 的 search_knowledge 记忆感知增量、working_set 高级组装和异步文件刷新。
- 记忆自动写回 canonical knowledge base；知识候选晋升必须由管理面人工动作完成。
- 宿主原生 memory bridge、代理拦截、Resources 常驻、服务端推送、认证、多租户、OCR 和新检索质量优化。
- 重建 007 作用域解析器、008 脱敏管线、006 maintenance 骨架；仅做兼容扩展和接线。

## Assumptions

- 复用 007 域档案与双轨作用域解析器、008 `credential_redactor`、006 maintenance 和 writer/reader 纪律。
- 首期为单写者/多读者；reader 可写运行态审计和 access，但不能写知识内容或绑定表。
- 现有 PostgreSQL、Qdrant、evidence 归属/published 校验和 Snowflake 风格 ID 可用；向量集合按 index version 隔离。
- 跨存储写入失败可留下可恢复的未完成状态，但所有读路径在同步投影补齐并校验前屏蔽本次写入；恢复完成后才切换可见性，写入完成状态不扩展生命周期 status 枚举。
- 六类投影的最小实现与运行验收均属于 012；013/014 承接高级抽取、摘要生成、巩固、消费及文件异步刷新，不承接本期最小投影验收。
- MCP 顶层字段顺序由 schema 固化；request_id、occurred_at 等易变字段只在信封/审计，不进入 start_work 稳定包体。包体字节稳定以相同输入、相同数据和域策略版本为前提；状态变化后返回最新包体，包体内容变化时指纹随之变化，不固定 session 首次包体。
- hard confidence 保持 NULL；soft/distilled 即使支撑证据为空也必须存在五元 metadata，并在 recall 中显式区分推断。
- content_hash 的唯一性按 scope 内脱敏正文判定；等价重复提交复用已有 ID，不追加事件，非等价元数据拒绝，不通过重复提交修改生命周期或恢复未完成写入。
- 默认策略为 episodic 180 天、semantic/procedural 永生、每域配额 5000、decay_rate 0.05/day、RRF 权重 dense/recency/kind/salience=1.0/0.5/0.3/0.2、access 在线保留 90 天、recall 审计7天；四个内置档案同值，自定义域可明确覆盖。
- 快照按 10,000 个权威事件或 24 小时先到者生成，仅加速恢复；所有类型事件原文永久保留，截断仅为已校验归档后的在线段裁剪。rebuild 优先使用有效快照加增量事件；快照缺失或损坏时从完整在线及归档日志重放，日志不完整或校验失败即失败闭合。
- `as_of` 只查询 valid 时间线；superseded 条目仅在其有效区间且显式 include_superseded=true 时可见，observed 线只用于审计和确定性时间线排序。
- salience 初始值为 0；β=0.05/day、γ=1.0/access 来自域 policy 默认值，可由管理面覆盖并在 015 评测调优；首期按 0.2 权重启用 salience，但必须先执行衰减。
- rollback 只针对单 scope，access 事件不回滚；回滚后文件、摘要、向量和其他投影必须重建。supersede 冲突按目标事件点的日志顺序仲裁，回滚事件记录被隐藏的后续链，不删除它们。
- 新能力评测沿 001–011 运行器和报告纪律执行，不建立独立检索质量基线且不覆盖历史报告。

## Clarifications

### Session 2026-10-04

- Q1: `memory_policy` 的默认 TTL、配额、衰减和 RRF 权重，以及四个内置档案是否同值？ → A: 四个内置档案同值：episodic 180 天；semantic/procedural 永生；每域配额 5000；decay_rate 0.05/day；RRF dense/recency/kind/salience=1.0/0.5/0.3/0.2；自定义域可显式覆盖。
- Q2: 日志快照与截断采用何种周期和保留规则，截断后如何保持 rebuild 语义？ → A: 每 10,000 个权威事件或 24 小时先到者生成快照；截断和恢复规则以本日后续事件保留澄清为准：所有事件原文永久保留，截断仅为归档后的在线段裁剪，快照仅加速恢复。
- Q3: `as_of` 作用于哪条时间线，superseded 条目何时可见？ → A: `as_of` 只作用于 valid 事实线；superseded 条目仅在其 valid 区间且显式 `include_superseded=true` 时可见；observed 线保留审计语义。
- Q4: 显著性如何冷启动、如何确定 β/γ，首期是否参与排序？ → A: 无 access 初始 salience=0；β=0.05/day、γ=1.0/access 来自域 policy 默认值并可由管理面覆盖；首期按 salience 权重 0.2 启用，015 评测调优，但无衰减不得参与排序。
- Q5: 回滚是否跨 scope、是否影响 access 和文件投影，如何处理 supersede 冲突？ → A: rollback 只允许单 scope；不影响或删除 access 事件；文件和其他投影必须重建；按目标事件点的日志顺序仲裁 supersede，目标点后的链在回滚状态中隐藏但保留在日志中。

- Q: 快照生成后，旧事件应如何保留，才能统一“永久不可删除”和“允许截断”的要求？ → A: 所有事件永久保留；快照用于加速恢复，旧段可归档；access 的 90 天 TTL 仅限制在线保留。
- Q: 如果事件和关系状态已落库，但向量写入失败，这条记忆应如何处理？ → A: 返回失败；记忆保持不可见，恢复流程补齐全部同步投影并校验后才可见。
- Q: 012 发布时，链接图、摘要树和文件镜像这三类投影需要交付到什么程度？ → A: 六类投影均有最小实现，可验证重建、删除传播和回滚；高级抽取、摘要生成及文件刷新留给 013/014。
- Q: 同一知识域再次写入相同脱敏正文时，record_memory 应如何处理？ → A: 正文和来源、信任等级、纠正关系等规范化提交元数据一致时返回已有 ID，不追加事件；不一致则拒绝。
- Q: 相同参数调用 start_work，但期间记忆或域策略发生变化时，工作包是否应更新？ → A: 数据或策略变化后允许更新；相同输入、相同状态版本下包体字节一致，包体变化时指纹随之变化。

本轮新增 5 项决议已同步到 Scope Basis and Compatibility、User Scenarios & Testing、Functional Requirements、Success Criteria、范围内 / 范围外和 Assumptions；本轮提问额度已用完。grant 的非记忆管理对象与 aggregate_id=memory_id 的映射、会话 delivered 去重在 012/014 的交付边界仍需后续澄清；归档介质、跨存储恢复机制及各投影最小实现细节留待规划。
