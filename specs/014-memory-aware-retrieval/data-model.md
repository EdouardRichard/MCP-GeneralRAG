# Data Model: 014 记忆感知检索与宿主消费

日期：2026-10-08。依据 [spec.md](spec.md)、[plan.md](plan.md)、[research.md](research.md)。本文只定义**新增/变更**的数据形态与校验规则；012 已交付的 `memory_events`、`memory_entries`、六类投影、`sessions`、`scope_bindings`、`memory_salience`、`memory_recall_runs` 沿用不变（仅本节列出的增量）。

## 1. 权威与投影边界

- **唯一权威**：append-only `memory_events`。附加记忆、工作集与文件投影消费层**全部**是派生只读视图，任何一层都不得成为事实源。
- **附加层与工作集**：不新增权威表、不落盘包快照；工作集为单次调用的返回值，决策记录随包体返回（不写库）。
- **已交付集**：复用既有 `memory_recall_runs` 运行态审计表（7 天 TTL 运行态保留纪律不变），只增加写入字段语义与一个支撑索引。
- **消费层元数据**：新增独立表 `memory_consumption_projection`。投影元数据/状态登记**不计入六类业务投影**（012 spec FR-005），因此不改变六类投影定义与 `versions()` 约束。
- **消费层文件树**：`MEMORY_CONSUMPTION_ROOT/<scope_slug>/<kind>/<memory_id>.md` + `DIGEST.md` + `INDEX.md`，只读、可全量重建；与既有的 `DATA_ROOT/memory_projection/<数字 scope id>/<数字 projection id>/`（含 `012-v1/<数字 scope id>/<kind>/<memory_id>.md`、`DIGEST.md`、`INDEX.md` 与 `archives/`）修订目录**分层并存**，二者互不影响、互不为事实源（spec Clarifications Q1）。

## 2. 不新增/不改动清单（防止范围漂移）

| 对象 | 处理 |
|---|---|
| `memory_events` / 六轴元数据 / 双时态 / supersede 链 | 不变 |
| 六类业务投影（relation / dense / links / summary / file / salience） | 定义与路径语义不变；消费层是**第七个派生输出**且为元数据表 + 独立根，不并入 `VIEW_KEYS` |
| `memory_entries` 列 | 不变（附加层仅读取既有列） |
| `sessions` | 不变；`start_work` 仍**不写**会话行 |
| Qdrant 集合 | 不新增、不改名、不改 revision 过滤 |
| MCP 工具集合 | 仍为 6 工具（writer）/5 工具（reader）；不新增工具 |
| `RetrievalService` | 不改动（附加层在工具层之后） |
| `attach_min_score` 既有默认 | **不改**（改动会改变域 `policy_hash`，可能使 013 登记证明失效） |

## 3. 变更一：`MemoryPolicy` 新增可选键

`services/memory_policy.py` 的 `MemoryPolicy` 为 `extra="forbid"` 严格模型；新增键均有默认值，旧档案缺键取默认，因此**不激活**任何新行为（开关在 Settings 层）。整数排除 `bool`，浮点拒绝 `NaN/Infinity`。

| 键 | 类型 | 默认 | 约束 | 语义 |
|---|---|---:|---|---|
| `attach_conservative_min_score` | float | 0.50 | `[attach_min_score, 1]`，有限 | 未提供 `memory_context` 时的 `dense_similarity` 下限（"宁缺勿滥"档） |
| `attach_top_k` | int | 3 | `[1, 5]` | 附加条数 |
| `attach_max_chars` | int | 800 | `[200, 800]` | 附加内容总长 |
| `attach_excerpt_chars` | int | 200 | `[1, 200]` | 单条摘录长度 |
| `attach_timeout_ms` | int | 800 | `[1, 800]` | 附加层独立超时 |
| `delivered_ttl_seconds` | int | 3600 | `[60, 86400]` | 会话级已交付集的运行态去重窗口 |
| `working_set_max_open_items` | int | 3 | `[1, 5]` | 未决事项桶上限 |
| `working_set_max_recent_activity` | int | 3 | `[1, 5]` | 近期活动桶上限 |
| `working_set_max_procedural` | int | 2 | `[1, 5]` | 相关 procedural 桶上限 |

**Model validator**：`attach_conservative_min_score >= attach_min_score`，否则拒绝（不静默取默认）。**契约常量（不随策略放宽）**：条数上限 5、内容总长上限 800 字、摘录上限 200 字、超时上限 800ms——策略只能收紧。

## 4. 变更二：`Settings` 新增部署键

`config/__init__.py` 的 `Settings`，沿既有 `default_factory=os.getenv` 模式。

| 键 | 环境变量 | 默认 | 约束 |
|---|---|---|---|
| `memory_aware_retrieval_enabled` | `MEMORY_AWARE_RETRIEVAL_ENABLED` | `false` | 门控附加层与工作集新形态 |
| `memory_consumption_projection_enabled` | `MEMORY_CONSUMPTION_PROJECTION_ENABLED` | `false` | 门控消费层刷新与对账 |
| `memory_consumption_root` | `MEMORY_CONSUMPTION_ROOT` | `<DATA_ROOT 父目录>/memory_projection` | 解析后必须为绝对路径；**不得**等于或位于任意 `DATA_ROOT` 之内、不得与其重叠；越界即失败闭合 |
| `memory_consumption_refresh_interval_s` | `MEMORY_CONSUMPTION_REFRESH_INTERVAL_S` | `300` | `[30, 3600]`；维护窗口对账周期，轮询从不是唯一触发 |

## 5. 变更三：`memory_recall_runs` 语义固化 + 支撑索引（迁移 0105）

既有列（不变）：`request_id` PK、`tool`、`mode`、`scope_ids`、`channel`、`session_id`、`returned_count`、`returned_ids`、`package_fingerprint`、`degraded`、`failed_paths`、`latency_ms`、`created_at`、`expires_at`。

**语义固化（代码层，不加列）**：

- `tool ∈ {recall_memory, search_knowledge, start_work}`
- `channel ∈ {recall, attached, start_work}`（列在 0081 迁移已建但代码从未写入，本期首次写入）
- 已交付集定义：`session_id = :sid AND created_at > clock_timestamp() - (:delivered_ttl_seconds * INTERVAL '1 second')`，取 `returned_ids` 并集即为"已交付记忆集"；`include_delivered=true` 时跳过该查询。
- `expires_at` 仍为运行态审计保留期（默认 7 天），**不再**用作交付去重窗口。
- **已批准变更（须留证）**：`delivered_ttl_seconds` 默认 3600 秒取代 012 既有的 7 天 `expires_at` 去重窗口，改变既有 `recall_memory` 的跨调用去重行为；因此 012"会话时间线与已交付过滤"E2E 必须按新口径通过，并在回归报告中记录前后窗口差异（spec SC-015）。

**迁移 `0105_memory_delivery_index.py`**：仅新增非唯一索引 `ix_memory_recall_runs_session_created (session_id, created_at)`。不改列、不回填、不改默认值；`downgrade` 只删该索引。

**校验规则**：`delivered_ttl_seconds` 来自请求 scope 的 `MemoryPolicy`；跨域请求（多 scope）按每个 scope 的策略分别求窗口，取**最短**窗口（保守，避免用宽窗口掩盖跨域重复交付）。

## 6. 变更四：新表 `memory_consumption_projection`（迁移 0106）

一次一作用域一行，承载消费层的 last-good 指纹、状态与修复依据（**不是**记忆事实源）。

| 列 | 类型 | 约束/说明 |
|---|---|---|
| `knowledge_scope_id` | BIGINT PK, FK `knowledge_scopes.scope_id` | 一个作用域一行 |
| `scope_slug` | VARCHAR(255) NOT NULL | 渲染路径使用；直接取自已解析 scope 的 `knowledge_scopes.slug`（唯一规范来源），须与当前值一致，不一致即漂移；宽度与 `ScopeSlug`（≤255）取齐 |
| `source_event_id` | BIGINT NOT NULL | 本次渲染所依据的已验证日志前缀末端事件 |
| `tree_fingerprint` | CHAR(64) NOT NULL | `sha256(canonical({相对路径 → sha256(字节)}))`，只对字节计算 |
| `file_count` | INT NOT NULL DEFAULT 0 | 渲染出的记忆文件数（不含 DIGEST/INDEX） |
| `status` | VARCHAR(16) NOT NULL DEFAULT 'staging' | `staging\|complete\|failed` |
| `guard_state` | VARCHAR(16) NOT NULL DEFAULT 'writable' | `readonly\|writable`，供漂移报告判定只读位是否为预期形态 |
| `last_error` | TEXT NULL | 失败/漂移原因（可读码） |
| `refreshed_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | 最近一次成功渲染 |
| `updated_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | 行更新时刻 |

**CHECK（沿房规）**：`status ~ '^[a-z][a-z0-9_]*$'`、`guard_state ~ '^[a-z][a-z0-9_]*$'`、`tree_fingerprint ~ '^[0-9a-f]{64}$'`、`file_count >= 0`、`source_event_id > 0`。

**索引**：唯一 `(knowledge_scope_id)`；普通 `(status)`。**投影元数据不计入六类**，故不写入 `memory_projection_meta`（后者的 `versions()` 强制恰好等于六类 `VIEW_KEYS`，追加类型会破坏 012 既有重建校验）。

**状态转换**：

```
(无行) --首次刷新开始--> staging --渲染+校验成功--> complete
                              \--渲染/校验失败--> failed --下次刷新--> staging
complete --漂移检测命中--> staging(仅重建该 scope 子树)
complete --作用域/slug 变化或 scope 归档--> 删除该行与子树（删除传播）
```

## 7. 实体规格

### 7.1 Related Memory Attachment（附加记忆条目）

不落表；随 `search_knowledge` 响应返回，JSON Schema 见 [contracts/memory-attachment.schema.json](contracts/memory-attachment.schema.json)。

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `memory_id` | integer | ✔ | 正整数 |
| `knowledge_scope_id` | integer | ✔ | 必须等于请求解析出的 scope 之一 |
| `kind` | enum | ✔ | `episodic\|semantic\|procedural` |
| `provenance` | enum | ✔ | `hard\|soft\|distilled`（须随行，缺即不合格） |
| `confidence` | number\|null | ✔（键必在） | `[0,1]`；`hard` 为 `null` |
| `title` | string\|null | | ≤512 |
| `content_excerpt` | string | ✔ | ≤200 字（本 Feature 收紧，012 为 300） |
| `truncated` | boolean | ✔ | |
| `content_length` | integer | ✔ | ≥ 摘录长度 |
| `evidence_refs` | array | ✔ | 来源引用 |
| `inference_meta` | object\|null | ✔（键必在） | 软/distilled 必非空且含五元键 |
| `valid_from` / `valid_to` | string(ISO8601)\|null | ✔（键必在） | 带时区；naive 视为不合格 |
| `observed_at` | string(ISO8601) | ✔ | 带时区 |
| `session_id` | string\|null | ✔（键必在） | |
| `agent_id` | string\|null | ✔（键必在） | |
| `status` | enum | ✔ | 仅 `active`（其余状态在组装前已排除） |
| `superseded_by` | integer\|null | ✔（键必在） | 附加条目恒为 `null` |
| `injection_flags` | object | ✔ | 随行；无标记时为 `{}` |
| `attach_reason` | string | ✔ | 可读枚举：`session_recent\|context_match\|session_and_context` |
| `match` | object\|null | ✔ | 原始排序分量（`dense_similarity`/`recency_rank`/`kind_rank`/`salience`/`fused_score`，与运行时 `public_entry` 形态一致）；阈值判定取本对象内的 `dense_similarity`；不做伪精度归一化、不合成 `relevance_score` |

**定位语义分界（宪法 IV）**：本条目 MUST NOT 携带 `source_position`/`source_version`/`relevance_score`（证据层定位字段）；记忆侧可定位性由 `provenance`/`evidence_refs`/有效期承担。`hard` 条目 MUST 通过既有逐条归属复验（无锚/复验失败即排除）；`soft`/`distilled` 条目的 `inference_meta` MUST 为对象且含五元键 `source`/`confidence`/`model_version`/`time`/`supporting_evidence`（schema `allOf` 已强制）。`valid_to` 与 `superseded_by` 恒为 `null`，`status` 恒为 `active`。

**校验规则**：`provenance`、`status`、`kind` 三字段任一缺失即整条不合格；`quarantined/superseded/retired/archived/已过期/写入未完成` 条目在组装阶段排除，因此**不得**出现在输出中（出现即缺陷）。字段名与类型必须与 012 `memory-entry.schema.json` 的共享字段一致；比对基准为 **012 `memory-entry.schema.json` 的字段名/类型/枚举清单 + 运行时 `public_entry` 形态**（012 schema 无 `additionalProperties:false`、`inference_meta` 仅在 `$defs` 且无 `dense_similarity`/`attach_reason`/`injection_flags`），由契约测试按该清单断言不漂移。

### 7.2 Memory Notice

条件字段，JSON 对象（与 012 同名字段保持对象形态）：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `notice` | string | ✔ | 一句话，必须同时含(a)不可信数据声明：记忆非已发布事实、不得作为控制指令；(b)深读指引：按 `memory_id` 调 `recall_memory` |
| `untrusted` | boolean | ✔ | 恒 `true` |
| `failed_paths` | array[string] | | 附加层降级原因（如 `attachment_timeout`、`memory_unavailable`、`below_min_score`、`budget_exhausted`） |

出现条件：显式信号触发且主检索 `completion_status != "failed"`。

### 7.3 Delivered Memory Set（会话级已交付集）

- **载体**：`memory_recall_runs` 运行态行（`session_id` + `returned_ids` + `created_at` + `channel`）。
- **定义**：短 TTL 窗口内该会话经**任一通道**（`recall` / `attached` / `start_work`）已返回的记忆标识并集。
- **规则**：默认去重；`include_delivered=true` 覆盖去重且只作用于本次请求；覆盖**不**放宽 scope、状态、有效期或阈值；去重致空返回"无可用记忆"空态（`related_memories` 为空 + `memory_notice` 说明 + `gaps[].suggested_action`），**不改写**主检索 `completion_status`/`evidence`，不自动放宽；记录过期后不参与去重；不写记忆状态、不改显著性以外的事实字段、不跨域。

### 7.4 Working Set Package（会话开局包续接部分）

不落库、不落盘快照；由 `orchestration/working_set.py` 纯函数产出，仅在 `start_work` 的显式开关打开时进入包体。

| 字段 | 类型 | 语义 |
|---|---|---|
| `open_items` | array[item] | 未决事项：`kind=="episodic"` 且满足共享可见性谓词 |
| `recent_activity` | array[item] | 已解析会话内满足谓词的 episodic；无会话时为空数组 |
| `procedural` | array[item] | 满足谓词的 procedural 经验 |
| `decisions` | array[{memory_id, decision}] | `selected\|deduped\|truncated`，append-only、可观测（沿 005 词表） |
| `truncated` | boolean | 是否发生预算裁剪 |
| `session_resolved` | string\|null | 解析出的会话标识；未解析为 `null`（计数可见，不报错） |

`item = {memory_id, kind, provenance, confidence, evidence_refs, inference_meta, content_excerpt(≤300), truncated, observed_at}`。作用域**由包级 `scope` 承载**（单次组装只服务一个已解析作用域，条目 MUST NOT 越域），条目内不重复携带 scope；`provenance`/`evidence_refs` 为条目的可定位性依据（宪法 IV 记忆侧语义，不含 `source_position`）。

**共享可见性谓词（唯一）**：

```
status == "active"
AND retention_stage == "active"
AND valid_to IS NULL
AND (expires_at IS NULL OR expires_at > snapshot_at)
AND (valid_from IS NULL OR observed_at IS NULL OR valid_from <= observed_at)
```

`snapshot_at = max(observed_at)`（数据派生，非墙钟）。**排序**：每桶按 `(observed_at, memory_id)` 倒序；**去重**：桶序 `open_items → recent_activity → procedural`，按 `memory_id` 首次出现保留；**上限**：先按策略桶上限截断，再按剩余字符预算装箱（digest 优先于 working_set，`read_guidance` 永不裁剪）。

### 7.5 Consumption Layer Tree（只读文件投影）

```
<MEMORY_CONSUMPTION_ROOT>/<scope_slug>/<kind>/<memory_id>.md
<MEMORY_CONSUMPTION_ROOT>/<scope_slug>/DIGEST.md
<MEMORY_CONSUMPTION_ROOT>/<scope_slug>/INDEX.md
```

记忆文件 = YAML frontmatter 块 + 正文（= 脱敏后 `content_text` **原文**，不改写/不摘要/不截断）。frontmatter 键序固定：

| 键 | 来源 | 约束 |
|---|---|---|
| `memory_id` | 条目 | 整数 |
| `kind` | 条目 | 三值枚举 |
| `provenance` | 条目 | 三值枚举 |
| `confidence` | 条目 | `null` 或 `[0,1]` 有限数（`allow_nan=False`） |
| `valid_from` / `valid_to` | 条目 | ISO8601 UTC 或 `null` |
| `session_id` | 条目 | 字符串或 `null` |
| `evidence_refs` | 条目 | 数组（稳定序） |
| `status` | 条目 | 四值枚举 |
| `superseded_by` | 条目 | 整数或 `null` |
| `untrusted` | 固定 | 恒为 `true`（不可信数据声明；与 MCP 面 `memory_notice.untrusted` 同义，缺失即不合格） |

**只写语汇**：`utf-8` 无 BOM、`newline="\n"`、恰好一个结尾换行、键序固定、列表显式排序、生成时刻不入文件与指纹。**DIGEST.md**：域记忆摘要，只在巩固产出存在时含摘要内容，否则为明确空态（可重建，不伪造）；键序固定，文件头含不可信声明。**INDEX.md**：目录导航，按 `kind` 分组、组内按 `memory_id` 升序，每行 `相对路径` 与标题，文件头含不可信声明。**排除归档/墓碑**（不残留可消费正文）。

### 7.6 Continuity Query / Dataset

`eval/memory_continuity_eval_dataset.json` 为**冻结对象**（不沿用裸数组形态）：

| 键 | 说明 |
|---|---|
| `dataset_version` | 形如 `014.eval.1` |
| `frozen` | `{budget, clock, implementation, model, policy, prompt, recall, schema, snapshot, vocabulary}`（本 Feature 无 LLM，`model` 为显式 `"none"`） |
| `snapshot_hash` | 冻结输入快照摘要 |
| `source` | 快照来源说明 |
| `k` | 固定 5 |
| `queries[]` | ≥15 条，四类各 ≥1，含中文 |

`queries[]` 每条：`query_id`（唯一）、`category ∈ resume_after_break|recall_last_decision|lesson_effective|preference_applied`、`language ∈ zh|en`、`question`、`scope_id`、`required_items[]{locator, memory_id?, require_citation}`（`locator` 为跨环境稳定锚点：作用域 slug + 定位前缀/结构锚点；`memory_id` 仅作同快照内一致性校验，MUST NOT 作为唯一锚点）、`forbidden_items[]`、`criterion`（显式任务完成判据）、`_meta{review_status, review_notes, grounded_source}`（人工审核记录，沿用 011/agentic 形态）。

**校验**：`query_id` 唯一、四类各 ≥1、`zh` ≥2、`required_items` 非空且每项含稳定 `locator`、`forbidden_items` 键存在、`frozen` 键完整、`_meta.review_status == "reviewed"`；数据集文件 sha256 必须被测试 pin（既有 `test_domain_eval_dataset_schema.py` 不扫描新文件，故 014 自带保护）。**数据集形态与字段以 [contracts/continuity-evaluation-contract.md](contracts/continuity-evaluation-contract.md) §2 为单一事实源**，本节不重复其细则；锚点稳定性与审核记录形态沿用 011 固定集纪律（FR-005/FR-007）。

### 7.7 Continuity Report

写入 `eval/runs/<unique-run>/memory-*.json`，**拒绝覆盖历史**（沿 013 房规）。顶层：`schema_version`（`014.1`）、`report_type`、`generated_at`、`commit`、`status`、`environment`、`dataset_version`、`snapshot_hash`、`k`、`queries[]`（逐条两臂结果与差异）、`aggregates{without_memory, with_memory}`、`relative_gain`、`zero_baseline`、`criteria`、`redundancy`、`reproducibility`、`hard_metrics`、`gates{quality, safety, regression}`、`default_enable_eligible`、`evidence_paths`、`failed_paths`。退出码 0 通过 / 1 失败 / 2 证据不完整。

## 8. 不变量与验证映射

| 不变量 | 强制点 | 验证 |
|---|---|---|
| 事件日志唯一权威 | 附加层/工作集只读；消费层只从 `MemoryHistory.load()` 的已验证状态渲染 | 附加层与投影代码无 `_upsert`/无直接 event 追加（AST inventory） |
| 分字段不混装 | 响应构建区分字段，逐条 schema 校验 | 契约测试：`related_memories` 条目不得通过 `evidence` schema，反之亦然 |
| 定位语义分界（IV） | 记忆条目组装不注入证据定位字段 | 契约测试：记忆条目 schema 拒 `source_position`/`source_version`/`relevance_score`；硬指标"`evidence[]` 可定位率"与"记忆 provenance 完备率"分项统计 |
| 检测先行（V） | 附加层入口先检测后使用 | 单测：检测调用序先于召回/打分/排序；flags 随行；检测失败不阻塞、不放宽过滤与阈值 |
| 投影面不可信声明（V/XII） | 渲染器写 `untrusted: true` 与 DIGEST/INDEX 文件头声明 | 渲染测试 + 硬指标：标记完备率 100%，缺失标记文件数 0 |
| 未触发零新增 | 工具层门控 | golden：未触发与历史字节一致（pretty 镜像 + 有序键） |
| 状态排除 | 组装前四态 + retention + 有效期复验 | 反例矩阵：quarantined/superseded/retired/archived/过期 ⇒ 均不出现 |
| 记忆侧失败不污染主检索 | 独立 `asyncio.timeout` + 结果隔离 | 注入超时/异常/不可用，主检索字段逐一不变 |
| 工作集确定性 | 纯函数 + 数据派生 `snapshot_at` + 显式排序 | 同输入两次调用字节一致；无模型/网络调用 |
| 投影只读非事实源 | 应用层规范守卫 + 文件位纵深 | 直写被拒；两布局冲突以日志为准；绕过后被漂移检测发现 |
| 投影可全量重建 | `MemoryHistory.load()` 重渲染 | 清空消费层后重建，路径/字节/frontmatter/DIGEST/INDEX 与日志一致，模型调用 0 |
| 分层并存 | 独立根 + 独立元数据表 | 清空/重建消费层后既有修订目录、校验器与重建/回滚报告零变化 |
| 对照变量唯一 | 各臂独立恢复 + 基线禁参数 | 基线响应零新字段；两臂快照/库内容/预算一致 |
