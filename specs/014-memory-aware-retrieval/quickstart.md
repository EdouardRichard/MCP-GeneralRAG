# Quickstart: 014 记忆感知检索与宿主消费 — 验证指南

本文件是**运行验证指南**，不是实施说明。所有命令从仓库根 `D:\Project_new\docsToCode` 执行。契约见 [contracts/README.md](contracts/README.md)，数据形态见 [data-model.md](data-model.md)。

## 0. 前置条件

| 条件 | 说明 |
|---|---|
| Python ≥3.12 | `backend/pyproject.toml` 要求；依赖已装（`pytest`、`pytest-asyncio`、`jsonschema`） |
| PostgreSQL 可达 | `DATABASE_URL` 指向可写库；迁移需升至 `0104_runtime_activity_signals` 之后的新 head |
| Qdrant 可达 | `QDRANT_URL`；附加层的语义路径需要它，缺失时按独立降级验收（不是跳过） |
| 记忆数据 | 至少一个已解析 scope，含 `active` episodic（带 `expires_at`）与 procedural |
| 开关 | `MEMORY_AWARE_RETRIEVAL_ENABLED=true`、`MEMORY_CONSUMPTION_PROJECTION_ENABLED=true`（仅在对应阶段的隔离环境打开；默认关闭是发布状态，不是验收状态） |
| Windows 编码 | 运行器调用前设 `$env:PYTHONIOENCODING="utf-8"`，避免 cp936 控制台对中文/NBSP 抛 `UnicodeEncodeError` |

**重要**：默认关闭表示"未过闸不得进入默认路径"，不代表验收可以跳过实现。验收必须在隔离环境显式打开开关。

## 1. 契约与纯函数（无需数据库）

```powershell
cd backend
python -m pytest tests/contract/test_014_search_input_schema.py `
                 tests/contract/test_014_search_bytes_frozen.py `
                 tests/contract/test_014_search_attachment_schema.py `
                 tests/contract/test_014_start_work_schema.py `
                 tests/unit/test_014_working_set.py `
                 tests/unit/test_014_attachment_gating.py -q
```

预期结果：

- 014 输入 schema 中 `query/project_scope/domain_scope/task_context/top_k` 的 JSON 与其在 `specs/009-domain-neutral-retrieval/contracts/mcp-search-input.schema.json` 中的原文**逐字节相等**；`required` 与 `anyOf` 不变；014 只多出 `session_id`/`memory_context`。
- 未触发响应的 `content_blocks[0].text` 与冻结的 pretty JSON golden 一致；有序键列表等于契约表。
- 附加条目与证据条目**双向** schema 反例不通过（混装被拒）；记忆条目携带 `source_position`/`source_version`/`relevance_score` 被拒（定位语义分界），`soft`/`distilled` 缺五元 `inference_meta` 被拒。
- 工作集纯函数：相同输入两次调用字节一致；无模型/网络调用；未决事项谓词的七类边界（A1–A7）逐条断言；`start_work` 顶层运行时顺序 == `[scope, domain_brief, digest, working_set, read_guidance, counts, package_fingerprint, request_id]`。
- 未触发响应在 `AGENTIC_RETRIEVAL_ENABLED=true` 下同样与 golden 逐字节一致。

## 2. 附加层与独立降级（需 PG + Qdrant）

```powershell
cd backend
python -m pytest tests/unit/test_014_attachment_gating.py tests/integration/test_014_memory_e2e.py -q
```

逐项核对：

| 场景 | 期望 |
|---|---|
| 不传新参数 | 响应无 `related_memories`/`memory_notice`/`counts`，且与基线字节一致 |
| 传 `session_id` | 附加层触发；阈值取保守档；`memory_notice.notice` 同时含不可信声明与 `recall_memory` 深读指引 |
| 传 `memory_context` | 以 `memory_context` 为召回查询；阈值取 `attach_min_score` |
| 记忆侧超时/不可用/全部低于阈值 | `related_memories` 为空、`memory_notice.failed_paths` 非空；`completion_status`/`evidence`/`gaps`/`error`/`request_id` 全部不变 |
| `memory_context` 检测先行 | 检测调用序先于召回/打分/排序；flags 随行；检测失败不阻塞主检索且不放宽阈值/过滤 |
| 并发与延迟 | 附加层与主检索并发发起；端到端耗时 ≤ max(主检索, 附加层)；主检索完成/超时后无遗留任务（串行视为不合格） |
| 主检索 `failed` | 返回 legacy 形态，不附加 |
| 条数/字数 | ≤3 条（上限 5）、附加总长 ≤800 字、摘录 ≤200 字、附加耗时 ≤800ms |
| 状态 | `quarantined`/`superseded`/`retired`/`archived`/已过期/写入未完成 均不出现 |
| 去重致空 | `related_memories` 为空 + `memory_notice` 说明 + `gaps[].suggested_action`；主检索 `completion_status`/`evidence` **不变**（不得用 `no_evidence` 表达记忆层空态） |

## 3. 会话级已交付集

```powershell
cd backend
python -m pytest tests/unit/test_014_delivery_set.py -q
```

核对：同一会话经 `recall_memory` → `search_knowledge`（附加）→ `start_work` 三通道依次交付同一批记忆时默认去重、`dropped_delivered` 如实计数；`include_delivered=true` 覆盖去重且**只**放宽去重；窗口超过 `delivered_ttl_seconds` 后记录不再参与去重；去重致空返回"无可用记忆"空态（`related_memories` 为空 + `memory_notice` + `gaps[].suggested_action`），**主检索 `completion_status`/`evidence` 不变**，不自动放宽 scope/状态/有效期/阈值；窗口默认 3600 秒取代 012 的 7 天 `expires_at` 属已批准变更，须在回归报告留证。

## 4. 工作集续接

```powershell
cd backend
python -m pytest tests/unit/test_014_working_set.py tests/unit/test_memory_reader_budgets.py -q
```

核对：`include_working_set=false` 时包体与 012 逐字节一致（且不含 `working_set` 子键）；`=true` 时三类桶按 `(observed_at, memory_id)` 倒序、`decisions` 为 append-only 的 `selected/deduped/truncated`；无会话时 `recent_activity=[]` 且 `session_resolved=null`；`read_guidance` 未被裁剪；三档预算仍 ≤2000/800/300 字；两种取值下 `start_work` 顶层运行时顺序均为 `[scope, domain_brief, digest, working_set, read_guidance, counts, package_fingerprint, request_id]`。

## 5. 文件投影消费层

```powershell
cd backend
python -m pytest tests/unit/test_014_projection_render.py `
                 tests/integration/test_014_consumption_projection.py `
                 tests/integration/test_014_no_bypass.py -q
```

手工核对（隔离环境）：

```powershell
# 触发一次记忆写入后：
Get-ChildItem -Recurse "$env:DATA_ROOT\..\memory_projection" | Select-Object -First 20 FullName
# 期望：<scope_slug>/<kind>/<memory_id>.md + <scope_slug>/DIGEST.md + <scope_slug>/INDEX.md
```

| 检查 | 期望 |
|---|---|
| frontmatter | 十个键齐全（含 `untrusted: true`）且顺序固定；正文与权威 `content_text` 逐字节一致 |
| 不可信声明 | 每个记忆文件 frontmatter 含 `untrusted: true`；`DIGEST.md`/`INDEX.md` 文件头含同义声明；缺失即不合格 |
| 字节稳定 | LF 结尾恰好一个换行、无 BOM；重复渲染字节一致；生成时刻不入文件 |
| 只读纵深 | 直接对渲染出的文件 `write_text` → `PermissionError`（需以非管理员身份、且先清除可能残留的只读位）；目录仍为可写（`0755`） |
| 应用层守卫 | 消费层模块无 `_upsert`、无事件追加入口；AST inventory 通过 |
| 全量重建 | 清空消费层后重建 → 路径/frontmatter/正文/DIGEST/INDEX 与日志一致，模型调用 0 |
| 非事实源 | 两层冲突一律以事件日志为准；以投影取代权威日志做事实/状态判定的次数 0；两层互为事实源导致的判定差异 0 |
| 分层并存 | 既有 `DATA_ROOT\memory_projection\<数字 scope id>\<数字 projection id>\`（含 `012-v1\<数字 scope id>\<kind>\` 与 `archives\`）与其校验器、重建/回滚报告**零变化** |
| 异步 | 写入响应不等待刷新；刷新失败不影响写入与读取；维护窗口对账能发现并修复漂移 |
| 删除传播 | 撤回/纠错/隔离/归档/回滚后消费层不残留可消费正文 |

## 6. 连续性对照闸门

```powershell
# 记录轮（真实执行，冻结快照）
python ..\eval\run_memory_comparison.py --dataset ..\eval\memory_continuity_eval_dataset.json `
    --mode record --cache-manifest ..\eval\runs\<run-id>\cache-manifest.json `
    --output ..\eval\runs\<run-id>\memory-record.json --run-id <run-id>

# 重放轮（次轮必须零真实网络调用）
python ..\eval\run_memory_comparison.py --dataset ..\eval\memory_continuity_eval_dataset.json `
    --mode replay --cache-manifest ..\eval\runs\<run-id>\cache-manifest.json `
    --output ..\eval\runs\<run-id>\memory-replay.json --run-id <run-id>
```

核对：数据集 ≥15 条、四类各 ≥1、含中文（`zh` ≥2）、`frozen` 键完整、期望锚点为跨环境稳定 `locator`（不以 `memory_id` 为唯一锚点）、`_meta.review_status/review_notes/grounded_source` 齐备、sha256 被测试 pin；两臂库内容与预算一致；基线响应零新字段；`relative_gain ≥ 0.03` **或**预冻显式判据达标；`without_memory == 0` 时必须为 `BASELINE_ZERO_NOT_COMPUTABLE`；两轮非延迟漂移 ≤1%；重放真实网络调用 0；退出码 0/1/2 语义正确；报告路径唯一且拒绝覆盖。

## 7. 三宿主冒烟与回归

```powershell
# DSH（唯一必过参考客户端；需先启动 PostgreSQL/Qdrant 与 writer/reader MCP 端点）
python eval\probe_mcp_host.py
python -m pytest backend/tests/integration/test_target_host_smoke.py -q

# 回归：012 的 8 项 E2E、013 的 7 项 E2E、既有检索全集
cd backend
python -m pytest tests/integration/test_012_memory_e2e.py `
                 tests/integration/test_013_consolidation_e2e.py `
                 tests/contract/test_012_old_tool_compat.py -q
python ..\eval\run_comparison.py --output ..\eval\runs\<run-id>\retrieval-regression.json
```

| 检查 | 期望 |
|---|---|
| DSH 工作集续接 | 端到端通过并记录可复现证据 |
| DSH 文件投影直读 | 记录宿主真实读取投影路径的观测；未观测到即 `failed` |
| Claude Code / ChatGPT App | 只记录环境可用性与兼容状态；未执行**不得**记为通过 |
| 012 的 8 项 E2E | 全部通过（硬锚闭环、无锚拒写、跨域隔离、supersede、注入隔离、TTL/配额、reader 无写、会话时间线） |
| 013 的 7 项 E2E | 全部通过 |
| 旧三工具与旧客户端 | 未显式提供新参数的响应逐字节不变 |
| 既有检索全集 | 按 011 口径无回归，非延迟指标在 1% 相对容差内（安全硬指标零容差） |
| 交付窗口变更 | `delivered_ttl_seconds=3600` 取代 012 的 7 天窗口已在报告中留证，且 012"会话时间线与已交付过滤"按新口径通过 |

## 8. 发布判定

- **质量闸**：连续性 ≥3% 或预冻显式判据达标。
- **安全闸**（零容差、分项不混口径）：跨域泄漏 0；MCP schema 合法率 100%；`evidence[]` 来源可定位率 100%（`source_id`/`source_version`/`source_position`）；记忆 provenance 完备率 100%（`soft`/`distilled` 五元元数据 + `hard` 逐条归属复验；记忆条目携带证据定位字段数 0）；`memory_context` 检测先行率 100%；`quarantined` 进入默认召回/附加/工作集 次数 0；文件投影绕过直写 0；消费层 `untrusted: true` 标记完备率 100%。
- **回归闸**：012/013 E2E 与既有全集无回归；旧客户端字节不变。
- 三闸全过且证据完整 ⇒ `default_enable_eligible=true`；否则保持 `MEMORY_AWARE_RETRIEVAL_ENABLED=false` 与 `MEMORY_CONSUMPTION_PROJECTION_ENABLED=false`，保留能力与报告。**报告不自动修改任何开关。**

> 注意：本指南中的端到端与对照步骤需要真实 PostgreSQL、Qdrant 与 MCP 服务；本机当前只有 3080（DSH GUI）在监听，运行前必须先启动这些依赖。未执行必须记为未执行，不得记为通过。

## 9. 014 实施基线（T001 冻结，2026-10-09）

本节是 014 实现的**实测基线**，只记录实际观测到的值。未运行的项一律标记为「未执行」，**不得**记为通过。

### 9.1 迁移与工具面

| 项 | 实测值 | 取证命令 |
|---|---|---|
| Alembic 迁移总数 | 45 个 revision，**单一 head** | `backend/alembic/versions/*.py` 的 `revision`/`down_revision` 图 |
| 迁移 head | `0104_runtime_activity_signals`（`0104_runtime_activity_signals.py`） | 同上 |
| 工具面（writer / reader） | writer = `search_knowledge, get_evidence, list_knowledge_domains, recall_memory, start_work, record_memory`（6）；reader = 去掉 `record_memory`（5） | `python -m pytest tests/contract/test_012_actual_tool_surface.py -q` → **13 passed in 8.28s** |
| `search_knowledge` 输入面 | 9 属性 `query/project_scope/domain_scope/top_k/task_context`（+ 007/009 既有）；**不调用 `close_input_schema`** | `backend/src/rag_mcp/mcp/search_knowledge.py` 无 `close_input_schema` 调用点 |

### 9.2 依赖服务可用性（2026-10-09 实测）

**修正（同日，T031 执行期间发现）**：最初只探测了 `127.0.0.1`，得出"PG/Qdrant 关闭"的结论是**不完整**的。仓库根 `.env` 把两个服务都指向远端主机：

| 服务 | 配置来源与端点 | 状态 |
|---|---|---|
| PostgreSQL | `.env` 的 `DATABASE_URL` → `postgresql+asyncpg://***@106.55.49.216:7899/rag_mcp` | **可用**（实测） |
| Qdrant | `.env` 的 `QDRANT_URL` → `http://106.55.49.216:6333` | **可用**（实测，dense 路径实际返回分数） |
| 本机 PostgreSQL | `127.0.0.1:5432` | CLOSED（本地未部署） |
| 本机 Qdrant | `127.0.0.1:6333` | CLOSED（本地未部署） |
| DSH Web GUI | `127.0.0.1:3080` | OPEN |
| MCP writer / reader / 默认 端点 | `127.0.0.1:18080` / `18081` / `8080` | **CLOSED**（未启动 MCP 服务） |

**可用性实测证据（本轮真实执行）**：

| 命令 | 实测结果 |
|---|---|
| `python -m pytest tests/integration/test_012_live_reader.py -q` | **5 passed in 34.24s**（证明远端 PG 可用，dense/Qdrant 路径可用） |
| `python -m pytest tests/integration/test_014_memory_e2e.py -q` | **3 passed in 23.45s**（014 三通道去重 / 致空态 / 跨域隔离，真实 PG+Qdrant） |
| `python -m pytest tests/unit/test_consolidation_link_expansion.py -q` | 3 failed（**013 写入隔离门**：需显式 `CONSOLIDATION_ISOLATED_DATABASE`，属既有纪律，不是 014 回归） |
| `python -m pytest tests/integration/test_012_memory_e2e.py`、`tests/integration/test_013_consolidation_e2e.py` | **未执行**（T062 待跑；013 需隔离库） |

**结论**：本环境**具备** PG/Qdrant 前置条件（远端共享实例，仓库既有 012 live 验收即写此库），但**不具备** MCP 端点与"显式隔离库"。因此 §2、§3、§5、§7 中真实 PG/Qdrant 可执行步骤**必须实际执行**并留证；仅依赖 MCP 端点或隔离库的步骤（宿主冒烟、013 写入类 E2E）不得记为通过。写入均为随机命名的临时作用域（`reader-<snowflake>`），不修改既有数据。

**副作用如实记录**：T031 首次执行时测试前提有误（对未携带该 `session_id` 的记忆做会话过滤），产生 4 个临时作用域与少量事件/审计行的写入；已修正为"记录时即绑定 session_id"，并保留本注记。


### 9.3 既有测试基线（`cd backend`）

| 命令 | 实测结果 |
|---|---|
| `python -m pytest tests/unit -q` | **2105 passed, 3 failed** in 105.46s |
| 3 个失败 | `tests/unit/test_consolidation_link_expansion.py::{test_legacy_calls_stay_byte_compatible_without_flags, test_include_context_is_presentation_only_after_final_selection, test_link_expansion_three_gate_combinations}` |
| 失败原因 | **环境门控**：`tests/integration/consolidation_fixtures.py:15` 断言 `CONSOLIDATION_ISOLATED_DATABASE` 必须显式设置且等于 `DATABASE_URL` 的库名（为保护 013 写入）。属前置条件缺失，**不是** 014 引入的代码回归 |
| `python -m pytest tests/contract/test_012_actual_tool_surface.py -q` | 13 passed |

014 任何阶段都必须保持该基线（3 个环境门控失败不得增加；一旦提供 `CONSOLIDATION_ISOLATED_DATABASE` 与真实库，应回到 2108 passed）。

### 9.4 012 的 E2E 清单（`backend/tests/integration/test_012_memory_e2e.py`，实测收集 11 项）

按规格 8 项验收口径分组如下（分组为口径映射，测试函数名保留实测原文）：

| 口径 | 测试函数 |
|---|---|
| ① 硬锚闭环 | `test_e2e_hard_anchor_roundtrip` |
| ② 无锚拒写 | `test_e2e_no_anchor_has_no_event_or_projection` |
| ③ 跨域隔离 | `test_e2e_scope_isolation_is_an_explicit_union` |
| ④ supersede | `test_e2e_supersede_keeps_history_and_refreshes_package` |
| ⑤ 注入隔离 | `test_e2e_injection_never_enters_dense_or_package` |
| ⑥ TTL/配额 | `test_e2e_ttl_quota_fail_loud_without_silent_eviction` |
| ⑦ reader 无写 | `test_e2e_reader_has_no_write_or_governance_tools` |
| ⑧ 会话时间线 | `test_e2e_session_timeline_and_delivered_filter`（**T062 须按 `delivered_ttl_seconds=3600` 新口径通过**） |
| （同文件附加）隔离读取与时间线 | `test_memory_e2e_quarantine_reader_and_timeline` |
| （同文件附加）并发等价提交单权威事件 | `test_concurrent_equivalent_submissions_have_one_authority_event` |
| （同文件附加）relation 失败整体回滚 | `test_relation_failure_rolls_back_event_and_all_projection_visibility` |

### 9.5 013 的 E2E 清单（`backend/tests/integration/test_013_consolidation_e2e.py`，实测收集 7 项）

1. `test_e2e_batch_distillation_publishes_real_authority`
2. `test_e2e_deterministic_merge_deduplicates_equivalent_outputs`
3. `test_e2e_support_withdrawal_corrects_the_dependent_without_new_episodes`
4. `test_e2e_soft_overturn_of_hard_fact_is_rejected_and_audited`
5. `test_e2e_model_schema_fault_degrades_without_publishing`
6. `test_e2e_benefit_gate_fails_closed_on_real_zero_baseline`
7. `test_e2e_candidate_promotion_requires_explicit_human_action`

**基线声明**：以上 18 项 E2E 在本基线环境下**未执行**（无 PG，且 013 写入要求显式隔离库），T062 执行时须如实记录实际结果。
