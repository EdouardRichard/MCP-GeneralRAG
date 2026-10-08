# Research: 014 记忆感知检索与宿主消费

日期：2026-10-08。依据当前 [spec.md](spec.md)、[plan.md](plan.md)、宪法 v1.4.0、001–013 代码与两份记忆蓝图。本文完成 Phase 0 技术决策；**不是运行验收证据**，不构成质量、回归或受益结论。

编号与 plan.md 的 Phase 0 一致（§1–§13）。

## 1. 复用边界与增量面

**Decision**：`search_knowledge` 只在 MCP 工具层增量，`RetrievalService` 不改动；附加层由新增的 `MemoryService.attach()` 以关键字参数复用 `MemoryReader.recall()`（给 `recall()` 追加 `tool`/`channel` 关键字，默认值保持现状），不新建查询通道、不新写 scope/可见性/排序逻辑。`start_work` 复用既有 `_views`/预算骨架，新增纯函数组装器；文件投影复用 `MemoryHistory.load()` 与 `require_reducer_state`。

**Rationale**：`RetrievalService.search()`（`services/retrieval_service.py:161-208`，响应在 `:410-422`）是确定性检索路径，其响应是 `{completion_status, evidence, request_id}`（partial 时追加 `gaps`，异常时 `{completion_status, evidence, error, request_id}`）。在工具层之后附加可让未触发路径**零改动**，也避免把记忆失败引入检索服务的异常与 `failed_paths` 语义。`recall()`（`services/memory_reader.py:238-400`）已含五形态 scope 解析、四态可见性、delivered 去重、字符预算与 `memory_recall_runs` 审计，是唯一成熟读通道；规格要求"不重复 012 读路径与隔离防线"正是指此。

**Alternatives considered**：在 `retrieval_service.py` 内联记忆召回（污染确定性路径，失败语义与 `failed_paths` 需重写，回滚面大）；新建独立记忆检索服务或直查 Qdrant（第二条通道，重复 scope 下推与后置核验，违规格约束）；把附加层放进 005 Agent 状态机（引入前台等待并改检索图）。

证据：`backend/src/rag_mcp/services/retrieval_service.py`、`services/memory_service.py:54-60`、`services/memory_reader.py`、`mcp/search_knowledge.py`。

## 2. 分字段契约兼容性与字段顺序冻结

**Decision**：在 `search_knowledge` 现有签名末尾追加两个可选参数 `session_id: UUID | None = None`、`memory_context: Annotated[str | None, Field(min_length=1, max_length=4000)] = None`，以关键字转发进 `search_knowledge_core`（该函数已由 `*` 保护）。**不调用 `close_input_schema`**。未显式提供任一参数时返回 legacy dict 原样；显式提供且主检索 `completion_status != "failed"` 时按冻结顺序重建。新增冻结 golden 契约测试（pretty 文本镜像 + 有序键列表 + `structuredContent`）。冻结顺序为：

```
completion_status, evidence, related_memories, memory_notice, counts, gaps, error, request_id
```

其中 `evidence` 与 `related_memories` 相邻以在字段层体现分隔；`error` 仅失败态出现，而失败态不附加；legacy（未触发）响应保持今天的运行时顺序不动。

**Rationale**：实测 `search_knowledge` 返回普通 `dict[str, Any]`，FastMCP 走 `_create_dict_model` 并把返回同时生成 `structuredContent` 与 **pretty 打印**的文本镜像（`pydantic_core.to_json(result, fallback=str, indent=2)`），与记忆工具的紧凑 `memory_result`（`mcp/serialization.py:11-13` 的 `separators=(",",":")`）**不是同一序列化器**；不得"统一"。`mcp/shared/session.py:346` 的 `response.model_dump(by_alias=True, mode="json", exclude_none=True)` 保留 `structuredContent` 的插入顺序，且实测 `exclude_none` **不会**剥离 `structuredContent` 内部的 `None` → 门控必须"省略键"，绝不能"置 None"。既有 `tests/contract/test_012_old_tool_compat.py:36` 用 `json.dumps(..., sort_keys=True)` 比较两侧**同源**构建的工具定义与调用结果，`sort_keys=True` 抹掉属性顺序、`call_tool` 返回 `(content, structured)` 的 dict 相等也不比较键序 → 该测试**无法冻结今天的字节**，014 必须另加 golden。`close_input_schema`（`mcp/serialization.py:35-40`）会把 `additionalProperties:false` 写进 `inputSchema`，并让历史上被静默忽略的多余/拼写错误字段变成 `ValidationError`→`ToolError` 的不同响应，属真实破坏且对本 Feature 无收益（`search_knowledge` 当前不调用它）。

**Alternatives considered**：对 `search_knowledge` 调用 `close_input_schema` 做"schema 补位校验"（改变 inputSchema 字节、破坏未知字段容忍；规格要求的"补位"改由 014 增量 schema 与显式类型/长度校验实现）；把 `search_knowledge` 改为经 `memory_result` 返回统一紧凑镜像（改变既有 pretty 字节，违 FR-001）；新增字段置 `None` 占位（客户端与 `exclude_none` 双重误读）；把 `related_memories` 追加在 `request_id` 之后（`request_id` 居中，契约可读性与 012 先例不符）。

证据：`backend/src/rag_mcp/mcp/search_knowledge.py:155-161,196-208`、`mcp/serialization.py:35-40`、`tests/contract/test_012_old_tool_compat.py`、`tests/unit/test_mcp_tool_annotations.py:32-58`、`specs/009-domain-neutral-retrieval/contracts/mcp-search-input.schema.json`。

## 3. 附加召回参数化与阈值口径

**Decision**：附加召回查询 = 提供 `memory_context` 时用 `memory_context`，否则用主 `query`；提供 `session_id` 时作为过滤下推（`recall()` 已支持 query+session 的 hybrid 模式）。阈值作用在 `match.dense_similarity`（运行时 `matches[mid]` 即 `public_entry` 的 `match` 对象，含 `dense_similarity`/`recency_rank`/`kind_rank`/`salience`/`fused_score`）：提供 `memory_context` 用既有 `attach_min_score`；未提供时用新键 `attach_conservative_min_score`（默认 0.50）实现"宁缺勿滥"。主检索为 `failed` 时不附加，返回 legacy dict。**执行时序**：附加层与主检索**并发发起**（`asyncio.gather`/等价并发原语；附加层输入只依赖已解析作用域与查询/记忆上下文，不等待 `evidence`），在响应组装点合并；主检索完成或超时时附加层任务一并取消并回收，串行（无论先后）MUST NOT 作为实现方式（Clarifications Q10）。

**Rationale**：`recall()` 在 `match` 中暴露 `dense_similarity`（`services/memory_reader.py:339`），而 `MemoryPolicy.attach_min_score` 的值域是 `[0,1]`（`services/memory_policy.py:60`），与余弦相似度同量纲、可直接比较；`fused_score` 是 `Σ wᵢ/(k+rankᵢ)`（k=60）量级约 0–0.05，用 `[0,1]` 阈值不可解释、也不可跨域配置。**不修改 `attach_min_score` 的既有默认 0.0**：013 的 gate binding 对完整 `MemoryPolicy` 取 `policy_hash`，改动默认值会使既有登记证明失效；则"宁缺勿滥"由新增的保守档承担，两者都显式可校验。附加层只过滤、不重排：`evidence` 与自身排序均不变（宪法 VI，且 `attach` 通过 `limit`/后置过滤实现，不改 `recall` 的融合权重）。

**Alternatives considered**：阈值用 `fused_score`（量纲错配，需重定义 policy 值域并破坏既有键语义）；未提供 context 时走无分的时间线模式（无法表达阈值，"宁缺勿滥"落空）；提高 `attach_min_score` 默认值（扰动 013 `policy_hash`）；未提供 context 时干脆不附加（丢掉 US1 场景 2 的"仅 session_id"触发路径）。

证据：`services/memory_reader.py:238-340`、`services/memory_policy.py:49-66`、`specs/013-memory-consolidation-loop/contracts/gate-proof.md:21`。

## 4. 注入形态与 counts 词表

**Decision**：`related_memories` 条目沿用 012 `memory-entry` 的字段词汇（比对基准 = 012 `memory-entry.schema.json` 的字段名/类型/枚举清单 + 运行时 `public_entry` 形态），收紧 `content_excerpt` 到 200 字，并把 `injection_flags` 与 `attach_reason` 列为必带、`valid_to`/`superseded_by` 固定为 `null`；记忆条目不携带 `source_position`/`source_version`/`relevance_score`（定位语义分界，宪法 IV）。`memory_notice` 为**对象** `{"notice": <一句话>, "untrusted": true, "failed_paths": [...]?}`，`notice` 一句话同时含不可信数据声明与按 `memory_id` 调 `recall_memory` 的深读指引；`counts` 复用 recall 词表与顺序 `returned, candidates, truncated_by_budget, dropped_delivered, filtered_inactive, characters`。**`memory_context` 检测先行**：进入任何召回、打分、排序或拼装之前先跑既有注入检测并记录 flags；`memory_context` 只作为与 `query` 同级的不可信数据信号，永不进入系统提示或控制指令，永不选择/扩张 scope、不改阈值/过滤/状态/工具；高风险片段在面向模型的文本中按既有 `sanitize_for_prompt` 隔离语义处理；检测自身失败不阻塞主检索，也不得被当作放宽过滤或阈值的依据（Clarifications Q5、FR-015/SC-002）。

**Rationale**：012 的 `memory_notice` 是对象（`services/memory_reader.py:356,366` → `{"failed_paths":[...], "untrusted": true}`；`mcp/serialization.py:31` 只带 `failed_paths`）而**不是字符串**；把 014 的一句话放进对象成员既满足"一句话同时承载两件事"（FR-011），又保留结构化降级原因（FR-004 要求"失败原因可识别"），并避免同一字段名在两个工具间类型分裂。`counts` 的键与 FR-014 的五项要求一一对应：`returned`（返回条数）、`candidates`（候选条数）、`truncated_by_budget`（预算裁剪）、`dropped_delivered`（跨通道去重丢弃）、`filtered_inactive`（状态不可见过滤），`characters` 提供预算可观测性；复用 recall 词表使客户端可用一套解析。

**Alternatives considered**：`memory_notice` 为裸字符串（丢失结构化降级原因，且与 012 同名字段类型不一致）；新造 counts 键名（客户端两套解析，且与既有 `dropped_delivered` 语义重复）；用 JSON Schema `allOf` `$ref` 012 `memory-entry` 并覆写摘录上限（覆写语义隐晦，改用"词汇一致性测试"断言共享字段名与类型不漂移）。

证据：`services/memory_reader.py:341-360`、`mcp/serialization.py:16-32`、`specs/012-memory-foundation-write-read-loop/contracts/memory-entry.schema.json`、`contracts/mcp-recall-memory.output.schema.json`。

## 5. 会话级已交付集与短 TTL

**Decision**：复用 `memory_recall_runs`（已有 `channel`/`returned_ids`/`created_at`/`expires_at`）。写审计时填入 `tool` 与 `channel ∈ recall|attached|start_work`；去重查询改为 `session_id = :sid AND created_at > now() - :delivered_ttl_seconds`；新增策略键 `delivered_ttl_seconds`（默认 3600，范围 60–86400）。迁移 `0105_memory_delivery_index.py` 只新增支撑索引 `(session_id, created_at)`。`include_delivered=true` 跳过该查询；去重致空返回"无可用记忆"空态（`related_memories` 为空 + `memory_notice` 说明 + `gaps.suggested_action`），**不改写主检索 `completion_status`**，不放宽 scope/状态/有效期/阈值。**这是一处已批准变更**：`delivered_ttl_seconds` 默认 3600 秒取代 012 既有的 7 天 `expires_at` 去重窗口（spec Assumptions 已据此校正），因此 012"会话时间线与已交付过滤"E2E 必须按新口径通过并在回归报告留证（FR-038/SC-015）。

**Rationale**：既有去重查询用 `MemoryRecallRun.expires_at > now`（`services/memory_reader.py:288-289`），而 `expires_at` 默认是运行态 7 天（`models/memory_recall_run.py:23`）——这与规格"短 TTL"不符，且 Policy TTL 无法表达。改用 `created_at` + 策略 TTL 无需新列、无回填语义要辩护，且策略变更对未来生效。`channel` 列在 0081 迁移中已建（`alembic/versions/0081_memory_authority_constraints.py:66`）但代码从未写入，跨通道去重正需要它；`memory_recall_runs` 目前无 `session_id` 索引，短窗口高频查询需要支撑索引。

**Alternatives considered**：新增 `delivered_expires_at` 列并回填 `= expires_at`（多一列且回填语义必须辩护为"保持 012 行为"）；新建独立 delivered 表（多一个运行态权威面，运行态保留纪律需重做）；维持 7 天窗口（违"短 TTL"，且跨通道去重过度抑制）。

证据：`models/memory_recall_run.py`、`services/memory_reader.py:286-292,386-390`、`alembic/versions/0081_memory_authority_constraints.py:66`、`alembic/versions/0085_memory_recall_delivery.py`。

## 6. 未决事项语义边界与工作集组装器

**Decision**：新增纯函数模块 `orchestration/working_set.py`（stdlib-only），并新增无依赖纯 helper 模块 `orchestration/packing.py`（`timestamp/canonical/text_characters/serialized_characters`），`memory_reader` 改为从该模块导入以保持同名可用。共享可见性谓词：

```
status == "active"
AND retention_stage == "active"
AND valid_to IS NULL
AND (expires_at IS NULL OR expires_at > snapshot_at)
AND (valid_from IS NULL OR observed_at IS NULL OR valid_from <= observed_at)
```

`snapshot_at` **由数据派生**（scope 内 `max(observed_at)`），不使用墙钟。会话派生：显式 `session_id` 优先；否则在同 scope 内取 `session_id` 非空的 episodic 中 `max(observed_at)` 所属会话，并列时取字典序最大的 `session_id`；无候选则"近期活动"为空且计数可见，不报错、不扩大 scope。桶序 `open_items → recent_activity → procedural`，每桶按 `(observed_at, memory_id)` 倒序，跨桶按 `memory_id` 去重并记录 `selected/deduped/truncated` 决策。`start_work` 新增显式 `StrictBool` 开关（默认 `False`）承载新形态；legacy 分支逐字保留。

**歧义清单与裁定**（"未决事项 = 无 `valid_to` 的开放 episodic"）：

| # | 组合 | 现状 | 裁定与理由 |
|---|---|---|---|
| A1 | `valid_to NULL` + `expires_at` 已设（**episodic 的常态**） | `stable_package_visible` 排除（`:94`） | 以 `expires_at > snapshot_at` 为准；仅"已过期"排除。否则桶恒空、功能不可验收 |
| A2 | 曾被 supersede | `revise` 写 `valid_to`（`memory_reducer.py:226-231`） | `valid_to IS NULL` 是"未被关闭"的**可靠代理**，但不充分 |
| A3 | `status=retired` 而 `valid_to NULL` | 现有路径都会写 `valid_to`（`:248-250,330-337`）；旧 manifest 可能残留 | 必须合取 `status=="active"`，绝不单看 `valid_to` |
| A4 | `retention_stage ∈ compressed/archived` | `compressed` 两个谓词都放行；`archived` 仅靠 `:91` 排除 | 未决事项要求 `retention_stage=="active"`（不把压缩态当作"未决"） |
| A5 | 会话已过期 | `sessions.expires_at` 为运行态（`maintenance_service.py:503-510` 清理），记忆行 `session_id` 无 FK | 会话过期**不**作为未决判定条件，也不得据此隐藏记忆 |
| A6 | `observed_at` 缺失/naive/不可解析 | `stable_package_visible:95`、`start_work:600` 会抛错 | 视为非候选（不抛错），并以 `memory_id` 兜底排序 |
| A7 | `valid_from` 晚于 `observed_at` | 排除（`:96`） | 沿用排除，视为尚未生效 |

**Rationale**：实测 `stable_package_visible`（`services/memory_reader.py:88-96`）拒绝任何 `expires_at` 非空行，而 `record()` 对 episodic 恒写 `now + 180d`（`memory_validators.py:420-421` 的 `derive_ttl` 默认 180，`memory_service.py:224-231` 落库）→ **今天真实数据下 `working_set.memories` 恒为空**，唯一"非空"断言用的是 monkeypatch 原始 dict（`tests/integration/test_012_reader_boundaries.py:94-111`）。因此"无 `valid_to`"单独不足以定义可用桶，必须显式定义开放度。`_views` 读 `payload["state"]["entries"]`（`:181,188`）而非 `dense`，故 archived/compressed 行确实到达谓词，`:91` 的 retention 检查是有效防线。`snapshot_at` 必须数据派生，否则同数据在不同时刻产出不同字节，违 SC-009 的"相同输入字节一致"。`ContextSelectionList` 的 PK/FK 指向 `evidence_ledger_entry`（`orchestration/models.py:189-194`），无法承载记忆决策 → 决策留在包内，但沿用 005 的 `selected/deduped/truncated` 词表与 append-only 语义。

**Alternatives considered**：沿用 `stable_package_visible`（桶恒空，US4 不可验收）；只用 `valid_to IS NULL`（quarantined/archived 会漏入，违 FR-023）；用 `datetime.now()` 作 `snapshot_at`（字节不稳定）；把 `session_id` 当作新形态开关（legacy 调用本就传 `session_id` 且期望旧过滤形态，会破坏既有字节）；把决策写入 `ContextSelectionList`（外键不匹配）。

证据：`services/memory_reader.py:65-96,173-213,589-672`、`services/memory_reducer.py:203-240,330-337`、`services/memory_service.py:224-231`、`services/memory_validators.py:420-421`、`models/memory_projection.py`、`models/session.py`、`orchestration/context_selection.py`、`orchestration/models.py`。

## 7. 文件投影只读消费层与只读守卫

**Decision**：新增消费层根设置 `MEMORY_CONSUMPTION_ROOT`，默认 `<DATA_ROOT 父目录>/memory_projection`（默认 `DATA_ROOT=./data/uploads` ⇒ `./data/memory_projection`），显式拒绝与任意 `DATA_ROOT` 或其子目录重叠。新增 `runtime/memory_projection.py`，**只**从 `MemoryHistory.load(scope_id).state`（`runtime/projection_rebuild.py:140-156`，已复验 authority-id 相等与快照指纹）渲染，先过 `require_reducer_state`，且**绝不**调用 `MemoryProjectionStore._upsert`。消费层是宿主直读面，因此每个记忆文件的 frontmatter 与 `DIGEST.md`/`INDEX.md` 文件头 MUST 含 `untrusted: true` 同义声明（与 MCP 面 `memory_notice.untrusted` 一致），正文仍为脱敏后 `content_text` 原文、不改写不追加指令；声明与原文并存、互不替代（宪法 V/XII）。只读守卫采用**应用层为规范 + 文件级 OS 只读为纵深**的非对称方案：规范守卫 = reducer 状态门 + 路径解析限定（`resolve()` + 目录逃逸/符号链接拒绝）+ 无公开写 API + AST inventory；纵深 = 成功刷新后对该 scope 下文件置只读（POSIX `0o444` / Windows `S_IREAD`），重建或清理前在同一 worker 内先清除。**目录在两端一律保持 `0755`**。刷新异步、不进关键路径；维护窗口做全层对账与修复。

**Rationale**：仓库当前**零 `chmod`/`stat.S_*` 先例**，既有安全靠路径限定与静态无旁路测试（`services/memory_projection_store.py:163-176,334-335`、`runtime/projection_rebuild.py:122-129,191-193`、`tests/integration/test_012_provenance_no_bypass.py:33-50` 的 AST inventory）。实测（Windows `%TEMP%`）`:chmod(file, S_IREAD)` → `0o100444`，`write_text`/`unlink` 均 `PermissionError`；但 `chmod(dir, 0o555)` 后**在目录内创建与删除文件仍然成功**——Windows 忽略目录只读属性。POSIX 上 `0555` 目录会阻断重建所需的删除/重命名。故目录不可锁、文件锁只能作绊线（root/管理员可绕过），规范守卫只能是应用层。消费层与既有修订目录**分层并存**（spec Clarifications Q1）：既有 `data/uploads/memory_projection/<数字 scope id>/<数字 projection id>/` 与其校验器、重建/回滚报告路径零改动；`inspect()` 从 `current.payload["root"]`（`:331`）取目录，因此独立根天然安全。

**Alternatives considered**：只做 OS 只读（Windows 目录无效、root 绕过、崩溃留下半锁树）；只做应用层（外部编辑器/脚本仍可改，故保留文件位作纵深）；把消费层指纹写进 `memory_projection_meta`（`versions()` 强制恰好等于六类 `VIEW_KEYS`，`:63-73`，追加类型会破坏 012 既有重建校验）→ 改用独立元数据表（投影元数据/状态登记不计入六类，见 012 spec FR-005）；把消费层做成 MCP 资源或在协议层暴露（违"工具面锁定 6"且投影不应经协议输出）。

证据：`services/memory_projection_store.py`、`runtime/projection_rebuild.py`、`tests/integration/test_012_provenance_no_bypass.py`、`tests/unit/test_memory_read_only.py`、`config/__init__.py:193-195`。

## 8. DIGEST/INDEX 生成确定性与字节稳定

**Decision**：消费层所有 Markdown 以 `encoding="utf-8"`（无 BOM）、显式 `newline="\n"`、恰好一个结尾换行写入；frontmatter 手写固定键序（不依赖 YAML emitter）；JSON 取值一律 `allow_nan=False`；列表一律以显式稳定键排序（记忆文件按 `(kind, memory_id)`，INDEX 按相对路径字典序）；`DIGEST.md` 的键序固定为 `{"scope", "source_event_id", "counts", "sections"}` 形式的显式序列，内容只来自 reducer 状态；指纹只对文件字节计算，**生成时刻、mtime、inode 一律不入内容与指纹**。

**Rationale**：既有 `_materialize_summary` 用 `Path.write_text(encoding="utf-8")`（`newline=None`），在 Windows 上写 CRLF（`services/memory_projection_store.py:158-159`），其 `inspect()` 读取时按 `newline=None` 归一化后比较（`:362,365`）。消费层是新增契约，必须显式钉死 LF 才能跨平台字节一致。`json.dumps` 默认 `allow_nan=True` 会产出不合格 YAML 的 `NaN`；YAML emitter 存在 `True/None/yes/1.0` 隐式类型与键序风险，故手写 frontmatter。既有确定性先例：`canonical()`（`memory_reader.py:40-41`）、`projection_fingerprint()`（`memory_reducer.py:381-385`）、`gzip.compress(..., mtime=0)`（`memory_projection_store.py:179`）、`serialized_characters()` 定点循环（`memory_reader.py:52-62`）。易踩的非确定性来源：`set` 迭代、`dict` 插入序、`os.listdir`/`rglob` 顺序、locale/`strftime`、`default=str` 渲染 datetime、浮点 `repr`、Unicode NFC/NFD、gzip 等级。

**Alternatives considered**：用 PyYAML 转储 frontmatter（新增依赖 + 隐式类型/键序风险）；沿用 `newline=None`（平台相关字节，违"同内容同字节"）；把生成时刻/巩固版本时间写入 DIGEST（字节不稳定且违"包体不含易变字段"的既有原则）。

证据：`services/memory_projection_store.py:27-28,151-181,285-367`、`services/memory_reader.py:40-62`、`services/memory_reducer.py:381-385`、`services/consolidation_adjudicator.py:454-459`（CRLF 归一化先例）、`.gitattributes`。

## 9. 异步刷新不进关键路径

**Decision**：写入 `record()` 成功 commit 后 O(1) 触发（仿 `mark_volume_hint`：进程内合并脏集 + `schedule_projection_refresh(scope_id)`，沿 `runtime/scheduling.py` 的 `begin/end` 活动跟踪 + `loop.create_task`，无运行循环则跳过，**绝不 await**）。每 scope 单飞有界 worker，自带数据库会话与截止时间，并向测试暴露 `worker_task(scope_id)` 句柄；渲染先写暂存目录再原子替换，读者永不见半棵树。消费层元数据表持久化 last-good 指纹与 `source_event_id`（重启后可复验）。维护窗口（`server.py:193-228` 的 `_ttl_cleanup_loop` 时段）做全层对账：按 scope 重算"相对路径 → 字节 sha256"的树指纹并与元数据比对，漂移时只删除该 scope 子树并从日志重渲染。刷新/对账失败绝不向 `record()` 传播（仿 `services/memory_service.py:280-298` 的既有失败隔离），记录原因并保持脏标记重试。

**Rationale**：`_ttl_cleanup_loop` 与维护 tick 的 O(1) hint 是仓库既有"离线工作不阻塞前台"范式（`mark_volume_hint` 由 `maintenance_service.py:400-411` 消费，逐条件复验）。`memory_service.py:273-279` 已在 commit 后调用 hint，同一位置可加同量级调用。测试确定性沿用 `tests/integration/phase7_fixtures.py:83-92` 的 `settle()`（`asyncio.wait_for(asyncio.shield(worker_task))`）范式。DIGEST 依赖巩固产出（013 当前默认关闭）→ 摘要必须允许明确空态并仍可重建，不得把"巩固已运行"当作刷新前置。

**Alternatives considered**：同步刷新（进入写入关键路径，违 FR-031）；仅靠进程内 hint（重启即丢失，无法满足"漂移可修复"）；仅靠定时轮询（延迟不可控，且 FR-031 要求刷新由写入驱动）；用后台线程直接写文件（绕过事件循环与 reducer 状态门，且与 `asyncio.to_thread` 既有边界不一致）。

证据：`services/memory_service.py:273-298`、`runtime/activity.py:135-159`、`runtime/scheduling.py`、`server.py:193-228`、`services/maintenance_service.py:400-439`、`tests/integration/phase7_fixtures.py:83-92`。

## 10. 连续性判据的测量学设计

**Decision**：数据集为**冻结对象**（含 `dataset_version`、`frozen{...}`、`snapshot_hash`、`queries[]`），≥15 条、四类各 ≥1（跨会话任务断点续接 / 上次决策召回 / 教训生效 / 偏好应用）、含中文，AI 生成 + 人工审核。每条冻结 `required_items[]`（每项带期望 `memory_id` 或证据定位，并标注是否要求可定位引用）、`forbidden_items[]`（禁止项/越域项）、`category`、`language`、`criterion`。判定：每 query 二元 `task_complete = 全部 required 命中且引用可定位 AND 零 forbidden/越域/非法项`；`completion_rate = completed / queries`；相对提升 `(with − without) / without`；`without == 0` → `BASELINE_ZERO_NOT_COMPUTABLE`，改用预冻显式判据（如 ≥12/15 且四类各 ≥1）；冗余度 = `1 − distinct_items / total_items`。两臂各自独立恢复（沿用 013 的隔离身份范式，简化为 2 臂 × 2 轮），基线臂不传 `session_id`/`memory_context`、不共享 session 与已交付集，并断言基线响应零新字段。报告沿用 013 房规：`--output` 唯一且拒绝覆盖、退出码 0/1/2、`k=5`、非延迟漂移 ≤0.01、重放真实网络调用 0。

**Rationale**：仓库**不存在任何任务完成或冗余度指标**（`task_completion|completion_rate` 与 `redundan|冗余` 均无相关命中），必须新定义；采用纯规则判据（而非 LLM 裁判）满足宪法 VI，且可逐条复算、可人工审核。`BASELINE_ZERO_NOT_COMPUTABLE` 直接沿用 013 显式"不可计算"语义（`eval/run_consolidation_comparison.py:264-290`），不得以极小值或无穷冒充过闸。两臂同快照隔离保证"启用变量是记忆可用性而非库内容"（规格硬约束）。既有 `binary_metrics`/`macro_average`（`services/consolidation_gate.py:147-185`）与 `run_eval.py` 的 `compute_mrr`/`compute_ndcg_at_k` 只在某一臂产出排名/定位结果集时作为辅助指标复用，不作连续性主判据。

**Alternatives considered**：以 MRR/nDCG 作连续性主判据（连续性判据是任务结果而非排序，规格要求"或显式任务完成判据"）；LLM 裁判打分（不可复算、进控制路径，违 VI）；把"无记忆臂答不出"记作命中（伪造基线，把基线推高反而更难达标）；单臂多次运行取最优（不可复现）。

证据：`eval/run_consolidation_comparison.py:258-290,1413-1438`、`eval/consolidation_restore_support.py`、`services/consolidation_gate.py:147-185`、`eval/run_eval.py:319-425`、`tests/contract/test_domain_eval_dataset_schema.py:134-144`、`specs/013-memory-consolidation-loop/contracts/evaluation-contract.md`。

**数据集保护缺口（须在 014 补齐）**：`test_domain_eval_dataset_schema.py` 只钉住 3 个既有数据集的 sha256，**不扫描新文件**，因此 014 新增的 `eval/memory_continuity_eval_dataset.json` 既无继承义务也无保护；014 必须自带 schema 校验测试（查询数、四类覆盖、中文、required/forbidden 结构、`frozen` 完整性）并把自己的 sha256 纳入 pin。

## 11. 三宿主对文件投影直读的可行性实测

**Decision**：三宿主冒烟沿用既定阻塞策略（DSH 必过；ChatGPT App / Claude Code 记录兼容状态、不作阻塞项）。对"文件投影直读"采用三层证据：(a) **必过**——文件系统级校验（存在性、frontmatter 完备率、正文与权威 `content_text` 逐字节一致、清空后全量重建摘要可复现），即 SC-011；(b) **DSH 端到端探针**——沿 `eval/probe_mcp_host.py` 风格记录真实 MCP 调用与宿主读取投影路径的真实观测，未观测到即 `status=failed`；(c) **Claude Code / ChatGPT App** 只记录环境可用性与兼容状态，未执行一律不得记为通过。

**Rationale**：实测本机只有 `3080`（DSH Web GUI，PID 19436）在监听；`8080/18080/18081/6333/5432` 全部关闭，无 postgres/qdrant/uvicorn 进程（`.env` 的 `QDRANT_URL` 指向远程）。`claude.exe` 存在，但 `~/.claude.json` 的 `mcpServers` 为空 `{}`（无 rag-mcp 条目）；`~/.codex/config.toml` 无 mcpServers/8080；`claude_desktop_config.json` 不存在。仓库内唯一宿主探针 `eval/probe_mcp_host.py` 仅覆盖 DSH（writer `18080`/reader `18081`，输出 `host-evidence.json`），`tests/integration/test_target_host_smoke.py` 用 `pytest.fail`（从不 skip）且需要 8080 上的真实 MCP 服务。**文件投影是文件系统读取，不经 MCP**，因此在协议层**不存在**"宿主直读"证据；诚实的可验证替代只能是文件系统摘要校验 + DSH 真实观测 + 其余记录状态。当前要跑通端到端宿主冒烟还需先启动 PostgreSQL、Qdrant 与 MCP 服务，属运行成本而非设计缺口。

**Alternatives considered**：声称三宿主皆完成端到端直读（无证据，违宪法 X 与 FR-037）；把未执行记为通过（FR-037 明令禁止）；为直读新增 MCP 工具或资源（违"工具面锁定 6"，且投影作为派生视图不应经协议成为第二消费面）；只做文件系统校验而完全不碰宿主（放弃 DSH 必过义务）。

证据：`eval/probe_mcp_host.py`、`tests/integration/test_target_host_smoke.py`、`tests/integration/test_deepseek_harness_dual_form.py:248-255`、`README.md:203-211,257`、`specs/006-runtime-hardening/contracts/common.schema.json:22`（`HostTarget` 枚举）。

## 12. 默认启用门控与关闭条件

**Decision**：两个部署开关默认 `false`：`MEMORY_AWARE_RETRIEVAL_ENABLED` 门控附加层与工作集新形态，仅当连续性闸门质量（≥3% 或显式判据）、硬指标（跨域 0、schema 100%、provenance 100%、隔离泄漏 0）与既有回归三闸全过、且报告证据完整时可开启；`MEMORY_CONSUMPTION_PROJECTION_ENABLED` 门控消费层刷新与对账，仅当投影验收（渲染确定性、重建与日志一致、只读守卫、删除/回滚传播、两布局互不影响）全过时可开启。**不复制 013 的 per-scope 登记证明机制**。

**Rationale**：013 的 gate-proof（`contracts/gate-proof.md`）是"按请求、按 scope 授权可能扩大候选取集的链接扩展"，需要逐请求绑定复验、报告 SHA256、有效期与实现指纹。014 的附加层**不改变 scope、候选、融合或排序**，只在同一 scope 内附加带 provenance 的只读条目，风险面与授权粒度不同；用部署级开关 + 冻结报告即可，避免把 013 的机制（以及其当前 `default_enable_eligible=false` 的状态）传染为 014 的验收阻塞。质量未达标时能力保留、开关关闭、报告留存（FR-035）。

**Alternatives considered**：复用 013 登记证明（机制与风险不匹配，且会把"013 默认关闭"耦合进 014 验收）；默认开启（违 FR-035 与宪法 X）；把开关做成域策略键（域级开关会让同一部署出现"部分域可附件"的额外语义，且 014 的对照闸门是部署级结论）。

证据：`specs/013-memory-consolidation-loop/contracts/gate-proof.md:5-11,47-55`、`config/__init__.py:233-237`（`GRAPH_ENHANCED_RETRIEVAL_ENABLED` 先例）、`specs/014-memory-aware-retrieval/spec.md` FR-035。

## 13. 材料局限与缺口

**Decision**：如实记录并只采用可核验来源，**不补造决议**。

- 《记忆召回链路-逐节点技术选型台账.md》**不在工作区**：①-4、①-11、②-8、③-8 无任何可得原文；Q24 与 Q41–Q43 只能由实施蓝图 §10.1 的序位映射推测。Q6、Q26–Q30、Q29 有可核验旁证（§10.1 与 §3.2/§4.6）。
- **ADR-12 只有引用、没有定义**：演进蓝图 §4 的 ADR 表止于 ADR-11，"ADR-12"仅出现在文首修订表「文件投影列为"挂起项" → 采纳为投影⑤（只读、可重建、含 DIGEST/INDEX、禁止直写）（ADR-12 / Q41–Q43）」。本规划不杜撰其决策理由与代价。
- 文件投影的 **frontmatter 字段清单**（`memory_id/kind/provenance/confidence/valid 时间/session/evidence_refs/status/superseded_by`）在现有材料中**无既有契约**，属本 Feature 新增契约。
- "三宿主对文件投影直读"的判据在现有材料中无定义（仓库无三宿主冒烟脚本或文档）；§11 给出的是本机可实证的替代方案。
- `search_knowledge` 顶层字段顺序此前**只有文字约定、无顺序断言测试**（`specs/012-.../spec.md:300`），本 Feature 新增可执行断言与 golden。
- 013 当前 `default_enable_eligible=false` 且巩固真实耗时为分钟级 ⇒ 消费层的 DIGEST 必须允许明确空态，不把"巩固已产出摘要"当作前置条件。
- 本次规划只做只读核验，**未重跑** 012/013 E2E、既有全集或任何质量/回归评测；规划通过不等于功能、回归或受益证据。

**Rationale**：与 013 同一纪律（"不补造台账决议"）。

**Alternatives considered**：把蓝图序位映射当作台账原文引用（伪造决议）；按 ADR-12 编号编造决策与代价（不可核验）；据推测决定 frontmatter 字段（改由用户明确要求 + 本 Feature 冻结为新增契约）。
