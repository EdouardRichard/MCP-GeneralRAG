# 文件投影消费层契约 v1（014）

本契约定义 014 新增的**只读消费层**：路径、frontmatter、DIGEST/INDEX、只读守卫、异步刷新、漂移检测与全量重建。对应 FR-025/FR-025a/FR-026…FR-032、SC-011/SC-012/SC-013/SC-016。消费层是派生视图，**不是**记忆事实源。

## 1. 分层并存（spec Clarifications Q1 = A）

| 层 | 路径 | 身份 | 本 Feature 的处理 |
|---|---|---|---|
| **消费层**（本契约） | `<MEMORY_CONSUMPTION_ROOT>/<scope_slug>/<kind>/<memory_id>.md` + `<scope_slug>/DIGEST.md` + `<scope_slug>/INDEX.md` | 宿主/人工直读面 | 新增 |
| **修订目录**（012 既有，实测形态） | `DATA_ROOT/memory_projection/<数字 scope id>/<数字 projection id>/{DIGEST.md, INDEX.md}` + `<...>/012-v1/<数字 scope id>/<kind>/<memory_id>.md` + `archives/` | 内部暂存/修订表示 | **零改动**：路径语义、落盘校验器、重建与回滚报告路径均已冻结 |

- 两层**不得互为事实源**，唯一权威是 append-only `memory_events`；两层冲突一律以日志为准。
- 清空、重建或删除消费层**不得**影响修订目录、`MemoryProjectionStore.inspect()`、`versions()` 或 `rebuild()` 输出。
- 消费层元数据写入独立表 `memory_consumption_projection`，**不写入** `memory_projection_meta`（后者的 `versions()` 强制恰好等于六类 `VIEW_KEYS`，追加类型会破坏 012 既有重建校验）。

**根目录派生**：`MEMORY_CONSUMPTION_ROOT`，默认 `<DATA_ROOT 父目录>/memory_projection`（默认 `DATA_ROOT=./data/uploads` ⇒ `./data/memory_projection`）。解析后必须为绝对路径，且**不得**等于或位于任意 `DATA_ROOT` 之内或与其重叠；越界即失败闭合，不回落、不自动改写。

## 2. 路径与文件名归一化

- `scope_slug` 来自 `knowledge_scopes.slug`（`^[a-z0-9][a-z0-9-]*$`，≤255；消费层元数据列宽度与此一致），渲染前与当前值复核，不一致即判漂移。归一化规则固定为：直接采用该列的规范值，仅做 ASCII 小写化，不引入 locale 相关大小写折叠；出现非法字符、slug 冲突或超长一律**失败闭合**，不静默改写为其他 slug、不做拼音/转写。
- `kind ∈ {episodic, semantic, procedural}`（闭合三值）。
- 文件名 `"<memory_id>.md"`，`memory_id` 十进制正整数。
- 每次写路径都要 `resolve()` 后断言仍位于消费层根内，拒绝符号链接/junction/reparse 逃逸；拒绝 `..`、盘符、绝对路径注入。
- 归一化必须确定性：ASCII 小写、不引入 locale 相关大小写折叠；slug 冲突或非法字符在规划外的输入一律失败闭合，不静默改写为其他 slug。

## 3. 文件形态

**记忆文件** = frontmatter 块 + 正文：

```
---
memory_id: <int>
kind: <episodic|semantic|procedural>
provenance: <hard|soft|distilled>
confidence: <null|[0,1] 有限十进制>
valid_from: <ISO8601 UTC|null>
valid_to: <ISO8601 UTC|null>
session_id: <string|null>
evidence_refs: <稳定序数组>
status: <active|superseded|retired|quarantined>
superseded_by: <int|null>
untrusted: true
---
<脱敏后 content_text 原文>
```

- 正文必须是 `content_text` **原文**：不改写、不摘要、不截断、不追加任何提示或指令（`untrusted` 声明由 frontmatter 与摘要/导航文件头承载，MUST NOT 混入正文，二者并存且不互相替代）。
- **不可信声明（宪法 V/XII 边界）**：`untrusted: true` 为必带键，语义与 MCP 面 `memory_notice.untrusted=true` 一致（记忆为不可信数据、不得作为控制指令或已发布事实）；缺失该键的文件即不合格。消费层是宿主直读面，因此该声明是投影面对宿主的唯一不可信提示，MUST NOT 省略。
- frontmatter 为手写固定键序（不使用 YAML emitter），字符串按需引号化转义；`confidence` 用 `null` 或最短往返十进制，**禁止** `NaN`/`Infinity`。
- `evidence_refs` 数组按稳定键排序；时间一律 ISO8601 UTC 带 `Z`。
- **排除**：`retention_stage` 为 `archived`/`tombstone` 或 `status` 为 `retired`/`quarantined` 的记忆不产出可消费正文（墓碑与归档不残留正文）。

**字节规则（跨平台）**：`encoding="utf-8"`（无 BOM）、`newline="\n"`、恰好一个结尾换行、键序固定、列表显式排序；**生成时刻、mtime、inode、进程 id 一律不入文件与指纹**（否则字节不稳定）。不得沿用 `Path.write_text(..., encoding="utf-8")` 的默认 `newline=None`（Windows 会写 CRLF）。

**DIGEST.md**：域记忆摘要，键序固定（`scope_slug`、`source_event_id`、`counts{total, by_kind, consolidated}`、`sections`）。摘要内容只来自已验证的 reducer 状态；**巩固未运行或巩固能力关闭时为明确空态**（可重建、可读，不伪造摘要内容），不得把"巩固已运行"当作刷新前置条件。文件头 MUST 含不可信声明行（与记忆文件 `untrusted: true` 同义）。

**INDEX.md**：目录导航，**混合粒度**（FR-027 / Clarifications Q6）。顶层按 `kind` 分组（固定顺序 episodic → semantic → procedural），组内按 `memory_id` 升序，每行给出相对路径与标题（标题缺失时省略标题列）；当某一分型的条目数超过阈值（`INDEX_TIME_BUCKET_THRESHOLD = 200`）时，该分型内再按 `observed_at` 派生的 `YYYY-MM` 时间桶分节（新的在前，无法解析者归入 `undated`），分节与行序均确定性可重建。文件头 MUST 含不可信声明行。

## 4. 只读守卫（非对称方案）

**规范守卫（应用层，必过）**：

1. **reducer 状态门**：渲染输入只能是 `MemoryHistory.load(scope_id).state`（已复验 authority-id 相等、归档校验与快照指纹），并先过 `require_reducer_state`。消费层模块**绝不**调用 `MemoryProjectionStore._upsert`，也**绝不**直接追加事件。
2. **路径限定**：所有目标路径 `resolve()` 后必须位于消费层根内；拒绝符号链接与目录逃逸。
3. **无公开写 API**：唯一写入入口是内部刷新/重建函数，只接受已校验状态与作用域，不接收任意路径或任意正文。
4. **静态 inventory**：AST 测试断言 `services/memory_projection_store.py` 仍是唯一 `_upsert` 调用点，且消费层模块不含未授权写入口。

**纵深守卫（文件级 OS 只读）**：

- 成功刷新结束后，对该作用域下的文件置只读：POSIX `0o444`（`stat.S_IRUSR|stat.S_IRGRP|stat.S_IROTH`），Windows `os.chmod(path, stat.S_IREAD)`。
- 重建或清理前，在同一 worker 内先清除只读位再写，完成后再置回；`guard_state` 记录预期形态供漂移报告比对。
- **目录在两端一律保持 `0755`**：实测 Windows 忽略目录的只读属性（在 `0o555` 目录内仍可创建/删除文件），而 POSIX 的 `0555` 目录会阻断重建所需的删除与重命名。锁目录既无效又会破坏重建。
- **能力边界必须显式声明**：文件级只读是绊线而非安全边界（root / 管理员 / `CAP_DAC_OVERRIDE` 可绕过，文件属主可改回）；安全结论由应用层守卫与漂移检测承担，不得声称 OS 权限提供保护。

### 4.1 `guard_state`（预期形态登记，T046）

`memory_consumption_projection.guard_state ∈ {readonly, writable}` 只登记**本次成功刷新时期望的 OS 形态**，供对账报告比对，**不构成**任何事实或状态判定：

| 取值 | 含义 | 判定依据 |
|---|---|---|
| `readonly` | 刷新结束时已对消费层文件置只读（POSIX `0o444` / Windows `S_IREAD`） | `MEMORY_CONSUMPTION_PROJECTION_ENABLED=true` 且刷新成功 |
| `writable` | 纵深守卫未启用（开关关闭），文件按普通权限落盘 | 开关关闭或未启用纵深 |

- 对账时逐文件比对期望形态，落在 `mode_mismatch[]` 中；**形态差异不进入 `tree_fingerprint`**（见 §6），也不单独触发重建。
- 深度守卫由开关控制；**规范守卫（reducer 状态门 + 路径限定 + 无公开写 API + AST inventory）无条件生效**，与 `guard_state` 取值无关。
- 递归删除/重建前 MUST 在同一 worker 内先清除只读位（Windows 下只读文件 `unlink` 抛 `PermissionError`，实测确认），完成后再置回；`memory_projection_meta` 永不参与。

### 4.2 能力边界（实测 2026-10-09，Windows 10/11 + Python 3.12）

| 断言 | 实测结果 | 结论 |
|---|---|---|
| `chmod(dir, 0o555)` 阻止目录内创建/删除文件 | **否**（仍可创建并删除） | 目录不可锁；目录一律 `0o755` |
| `chmod(file, S_IREAD)` 使 `write_text` 抛错 | **是**（`PermissionError`） | 文件位可作为绊线 |
| `chmod(file, S_IREAD)` 使 `unlink` 抛错 | **是**（`PermissionError`） | 重建/清理前必须先清位 |
| 属主清除只读位后写入 | **成功** | OS 位可被绕过 |
| root / Administrator / `CAP_DAC_OVERRIDE` | 可绕过文件位（POSIX 语义） | 非安全边界 |

**因此**：

1. **应用层为规范（normative）**：只从 `MemoryHistory.load(scope_id).state`（已复验 authority-id 相等、归档校验与快照指纹）渲染并经 `require_reducer_state`；所有目标路径 `resolve()` 后必须位于消费层根内并拒绝符号链接/目录逃逸；无公开写 API（唯一入口为内部刷新/重建函数，只接受已校验状态与作用域，不接受任意路径或正文）；AST inventory 断言消费层不含 `_upsert`、不含事件追加、且 `services/memory_projection_store.py` 仍是唯一 `_upsert` 调用点。
2. **OS 文件位仅为纵深（defence in depth）**：它是"绊线"，用于让宿主直写与误操作**尽早失败并留下可检测痕迹**，**不是**安全边界。`SC-012` 的"绕过校验直写成功次数为 0"由**应用层守卫 + 漂移检测 + 报告**证成，**不得**以文件位作证。
3. **限定语必须随结论出现**：任何"消费层只读"的验收陈述 MUST 写成"应用层规范守卫只读 + 文件位纵深（root/管理员可绕过；Windows 忽略目录位）"，MUST NOT 简写为"文件系统强制只读"。

**构造性与否定性证据（T046）**：

- **构造性（正例）**：`backend/tests/unit/test_014_projection_render.py` 断言成功刷新后文件无写位（`stat.S_IWUSR` 未置）、目录保持 `S_IWUSR|S_IXUSR`、重建前清位后重渲染成功、DIGEST/INDEX 与记忆文件字节稳定。
- **否定性（被拒 + 能力边界）**：同文件断言越界目标（根外、兄弟目录、根本身）抛 `ProjectionPathError` 且不产生字节；断言属主**可以**清位后直写成功 —— 即"直写被拒"来自应用层约定，而不是 OS 权限。
- **静态**：`backend/tests/integration/test_014_no_bypass.py` 的 AST inventory 断言无 `_upsert`、无事件追加、无公开写 API、并在安装纵深守卫的**关闭开关**路径上仍受规范守卫约束。


## 5. 异步刷新、对账与重建

- **触发**：`record()` 成功 commit 后 O(1) 登记脏作用域并调度（沿既有活动跟踪 + `loop.create_task`；无运行循环则跳过），**绝不 await**，绝不进入写入关键路径。
- **worker**：每作用域单飞、有界，自带数据库会话与截止时间，向测试暴露 `worker_task(scope_id)` 句柄；渲染先写暂存再原子替换，读者永不见半棵树。
- **对账**：维护窗口内按作用域重算树指纹（`sha256(canonical({相对路径 → sha256(字节)}))`）并与 `memory_consumption_projection.tree_fingerprint` 比对；漂移时**只**删除该作用域子树并从日志重渲染。周期对账是补充，**从不是唯一触发**。
- **失败隔离**：刷新/对账失败绝不向 `record()` 传播；记录 `last_error` 并保持脏标记重试。
- **全量重建**：清空消费层后可从 `MemoryHistory.load()` 重建出与日志一致的路径、frontmatter、正文、DIGEST 与 INDEX；**模型调用次数为 0**。
- **删除传播**：撤回、纠错、隔离、归档、scope 归档与回滚都必须传播到消费层；墓碑不残留正文。

## 6. 漂移与完整性报告

每次刷新/对账输出报告：`scope_id`、`scope_slug`、`source_event_id`、`file_count`（不含 `DIGEST.md`/`INDEX.md`）、`tree_fingerprint`、`status`、`guard_state`、`unexpected_paths`（消费层内不符合期望的路径）、`missing_paths`、`mode_mismatch`、`reason_code`、`repaired`（是否已重建）。**读路径从不就地修复**；只由刷新/对账 worker 修复。

**树指纹定义（唯一）**：`tree_fingerprint = sha256(canonical(json({相对路径 → sha256(文件字节)})))`，其中：

- 相对路径以作用域目录为基准、POSIX 分隔符、`rglob("*")` 中的**文件**（含 `DIGEST.md`/`INDEX.md`），按路径升序；
- `canonical` = `json.dumps(..., sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False)`，UTF-8 编码；列表元素已显式排序，故不存在集合迭代序依赖；
- **只对字节计算**：生成时刻、mtime、inode、进程 id、**OS 权限位**一律不入指纹。文件位差异落在 `mode_mismatch[]`（§4.1）而不改变指纹，否则在 Windows 上会把"位未生效"误报为漂移。

**漂移判定与修复**：读路径只观测（`missing_paths` / `unexpected_paths` / `mode_mismatch`）并记录，**从不**就地修复；刷新/对账 worker 命中漂移时**只**清空并重建该作用域子树（读取前先清只读位），把 `reason_code` 记为 `drift_detected`、`repaired=true` 并更新登记的 last-good 指纹。
