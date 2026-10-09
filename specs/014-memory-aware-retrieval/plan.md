# Implementation Plan: 记忆感知检索与宿主消费

**Branch**: `014-memory-aware-retrieval`（setup_plan 逻辑 Feature 名；实际 Git 分支为 `main`，本次不创建分支） | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Feature Directory**: `specs/014-memory-aware-retrieval`

**Input**: 已澄清的 014 规格（Clarifications Q1–Q12：Q1 文件投影分层并存与独立根、Q2 三宿主冒烟沿既有惯例、Q3 单档显式触发 + 独立预算、Q4 最近会话解析、Q5 `memory_context` 检测先行、Q6 事件驱动刷新与漂移修复、Q7 确定性判据为唯一闸门、Q8 顶层字段顺序冻结、Q9 消费层独立根目录、Q10 附加层并发发起、Q11 工作集新形态显式开关、Q12 条数由域策略配置）与用户指定模块/研究约束。

**Approved Decisions（2026-10-09，用户批准，见 spec Clarifications Session 2026-10-09）**：① 交付去重窗口 `delivered_ttl_seconds=3600` 秒，取代 012 的 7 天 `expires_at` 窗口，属已批准变更（须留证 + 012 会话时间线 E2E 按新口径通过）；② 顶层字段顺序以字段层相邻为准（新增三字段紧随 `evidence`），`start_work` 以运行时顺序为权威；③ 消费层 frontmatter 含 `untrusted: true`（十键）+ DIGEST/INDEX 文件头同义声明；④ agentic 路径下附加层不进入编排状态机，未触发响应在两路径逐字节一致。**这四项为冻结决议，规划与实现不再作为待澄清项处理。**

## Summary

在既有 MCP 工具面（锁定 6 工具，不新增）内做纯增量：`search_knowledge` 新增可选 `session_id`/`memory_context`，仅在显式信号下把记忆作为与 `evidence[]` **并列独立**的 `related_memories[]` 附加返回，走独立 800ms/800 字/top-3 预算与 `attach_min_score` 阈值，记忆侧任何失败都不改主检索状态；不传新参数时字段集合与文本镜像字节完全不变。附加与工作集复用 012 既有记忆读路径（参数化 `MemoryService.recall`，不新建通道），新增会话级已交付记忆集的跨通道去重；`start_work` 在显式开关下由纯函数组装器派生出未决事项/近期活动/相关 procedural 三类工作集，沿 005 装箱纪律且无 LLM。新增只读文件投影消费层（`{scope_slug}/{kind}/*.md` + frontmatter + DIGEST/INDEX），仅从已验证 reducer 状态渲染、可全量重建、写后异步刷新，与既有按数字 ID 的修订目录分层并存。以 ≥15 条多会话连续性四类查询做带记忆/无记忆对照（≥3% 或显式判据），并保证 012/013 E2E 与既有检索全集无回归。

研究见 [research.md](research.md)，模型见 [data-model.md](data-model.md)，接口见 [contracts/README.md](contracts/README.md)，验收见 [quickstart.md](quickstart.md)。不重建 012 读路径与隔离防线、005 装箱器、009 任务上下文泛化；不实现 015 完整治理 UI。

## Technical Context

**Language/Version**: Python ≥3.12（`backend/pyproject.toml`）；沿现有 asyncio/SQLAlchemy 2 async/Pydantic 2 风格；本期无前端新增。

**Primary Dependencies**: 无新依赖。FastAPI≥0.115、SQLAlchemy 2（asyncpg）、Alembic、Pydantic 2、`mcp` 1.29.1 FastMCP、jsonschema Draft202012、pytest/pytest-asyncio。**新代码路径不引入任何 LLM/网络依赖**：附加层与工作集组装、文件投影渲染/重建/漂移检测均为确定性代码；附加层只复用既有记忆读路径（dense 经既有 embedding provider）。

**Storage**: PostgreSQL 保持 `memory_events` 为唯一权威；`domain_profiles.memory_policy` 增加可选策略键（`extra="forbid"`，旧档案缺键取默认，不改变既有默认值以免扰动 013 的 policy_hash）；`memory_recall_runs` 复用既有 `channel`/`returned_ids`/`created_at` 承载已交付集，仅新增支撑索引；去重窗口改由策略键 `delivered_ttl_seconds`（默认 3600 秒）经 `created_at` 计算，**显式取代** 012 既有的 7 天 `expires_at` 去重窗口（`expires_at` 保留为运行态审计保留期）——属已批准变更，须在回归报告留证并证明 012 会话时间线 E2E 按新口径通过；新增 `memory_consumption_projection` 元数据表承载消费层指纹与状态（投影元数据/状态登记不计入六类投影）。文件系统新增只读消费层 `<DATA_ROOT 父目录>/memory_projection/<scope_slug>/<kind>/*.md` + `DIGEST.md` + `INDEX.md`；既有 `data/uploads/memory_projection/<数字 scope id>/<数字 projection id>/{012-v1/<数字 scope id>/<kind>/<memory_id>.md, DIGEST.md, INDEX.md, archives/}` 修订目录保持不变并降为内部暂存。Qdrant 仅经既有记忆读路径复用，不新增集合。

**Testing**: pytest + pytest-asyncio（`asyncio_mode=auto`）、jsonschema Draft202012、真实 PG/Qdrant 集成、冻结 golden 字节测试（pretty 文本镜像 + 有序键列表）、AST 无旁路 inventory、target-host 探针；eval 双跑对照 + report schema + 不覆盖历史报告。

**Target Platform**: Windows 开发 + 现有 Python 服务部署；单 writer/多 reader；管理 HTTP 默认 loopback；文件投影跨平台，POSIX 与 Windows 只读语义差异必须显式记录（Windows 目录只读属性不阻止子项创建/删除）。

**Project Type**: RAG MCP backend 增量（MCP 契约增量 + 只读派生投影 + 评测）。不新增 MCP 工具、不改检索排序/候选/融合、不引入 Agent 节点。

**Performance Goals**: 附加层独立预算 ≤800ms、默认 3 条（上限 5）、附加总长 ≤800 字、单条摘录 ≤200 字；主检索既有总超时预算（`retrieval.total_timeout_ms`=30000）**不增加**；附加层与主检索**并发发起**（附加层输入只依赖已解析作用域与查询/记忆上下文，不等待 `evidence`）并在响应组装点合并，端到端耗时 ≤ max(主检索, 附加层)，**串行执行不作为实现方式**；主检索完成或超时时并发任务一并取消并回收，绝不遗留未 await 任务；`start_work` 仍 ≤2s、三档 ≤2000/800/300 字；文件投影刷新异步、不进写入关键路径；连续性对照运行可复现（冻结快照 + 记录/重放）。

**Constraints**: 未显式提供新参数 → 新字段出现次数 0 且响应字节不变（含 pretty 文本镜像；`AGENTIC_RETRIEVAL_ENABLED=true` 时同样成立）；`related_memories` 与 `evidence` 分字段、混装 0；记忆条目 MUST NOT 携带 `source_position`/`source_version`（两套定位语义不混写）；附加条目 provenance 标注与 `injection_flags` 随行 100%；`soft`/`distilled` 五元推断元数据完备、`hard` 逐条归属复验通过；`memory_context` 检测先行 100%（检测失败不阻塞、不放宽）；quarantined/superseded/retired/archived/已过期进入附加层或工作集 = 0；跨域泄漏 0；记忆侧失败改变主检索 `completion_status`/`evidence`/`gaps`/`error` = 0；工作集组装 LLM 调用 0 且相同输入字节一致；文件投影只读且非事实源，绕过日志/校验直写 = 0；消费层 frontmatter 不可信标记（`untrusted: true`）完备率 100%；`memory_notice` 一句同时含不可信声明与深读指引；顶层字段顺序契约化并冻结断言（search_knowledge 与 start_work 两侧）；对照闸门 ≥3% 相对提升或显式任务完成判据；012 的 8 项 E2E、013 的 7 项 E2E 与既有检索全集按原口径无回归（非延迟 1% 容差）。不接受 `close_input_schema` 施加于 `search_knowledge`（会改变 inputSchema 字节并让历史被忽略的额外字段变成报错）。

**Scale/Scope**: 附加层默认 3 条；连续性评测集 ≥15 条覆盖四类场景；消费层每条记忆一文件、按 `scope_slug`/`kind` 组织，摘要与导航每作用域各一份；新增 2 个 migration（0105 索引、0106 消费层元数据）、4 个新模块（`orchestration/packing.py`、`orchestration/working_set.py`、`runtime/memory_projection.py`、`models/memory_consumption.py`）、4 份契约增量 + 3 份新 schema + 3 份文档契约；不动既有修订目录、不改六类投影定义。

## Constitution Check

研究前：PASS，无豁免。设计后：PASS，以下契约与验证责任已定义；表示规划符合约束，**不代表实现指标/测试已通过**。

| 原则 | Phase0 依据 / Phase1 落实 | 判定 |
|---|---|---|
| I Explicit Scope | 附加层与工作集沿既有五形态 scope 解析与双轨错误；解析失败/歧义拒绝、不回落；附加不扩大 scope | PASS |
| II Domain Facts | 记忆与证据并列不互相替代；记忆不覆盖证据；域身份保留 | PASS |
| III Uncertainty | 推断与事实由 provenance/inference_meta 区分并随行；降级、缺口与裁剪在 notice/counts 中显式 | PASS |
| IV Locatable Evidence | `evidence[]` 语义与字段不动（`evidence_id`/`source_version`/`source_position` 100% 可定位）；记忆走独立字段并以 `provenance`/`evidence_refs`/有效期承担可定位性，MUST NOT 携带 `source_position`/`source_version`（两套定位语义不得混写，硬指标分项统计） | PASS |
| V Data/Control | 记忆正文与 `memory_context` 视为不可信数据且**检测先行**（进入召回/打分/排序/拼装前先检测并记 flags，检测失败不阻塞、不放宽）；`injection_flags` 随行；notice 显式声明不得作为控制指令；消费层记忆文件与 DIGEST/INDEX 均带 `untrusted: true` 声明（宿主直读面） | PASS |
| VI Deterministic Control | 附加筛选、预算、排序、工作集组装与投影渲染均为确定性代码；无 LLM 进控制路径 | PASS |
| VII Interface Evolution | `search_knowledge`/`start_work` 增量走独立 014 契约与版本；旧字段/必填/顺序不变 | PASS |
| VIII Version Non-Mixing | 不新增索引/集合；记忆向量沿用既有 revision 过滤，无 embedding 混用 | PASS |
| IX Synchronous Results | 仍为单次同步 Tool Call 直接返回；不依赖 Resources/Tasks；异步刷新不在关键路径 | PASS |
| X Evaluation-Driven | 连续性对照闸门（≥3% 或显式判据）+ 硬指标 + 既有全集回归；未达标默认关闭 | PASS |
| XI Domain Neutrality | 策略为声明式域键；`memory_context` 为域中立自由文本；无领域硬编码 | PASS |
| XII Memory Loop | 记忆读走既有显式 scope 与四态可见性；`provenance`/推断分离，`hard` 条目复用既有逐条归属复验（无锚/复验失败即排除），`soft`/`distilled` 五元元数据必非空；投影只读且可重建 | PASS |
| XIII Trajectory | 事件日志为唯一权威；消费层为只读派生并经校验状态渲染；漂移可检测、可全量重建 | PASS |

六项硬约束逐项复核：跨域泄漏 0（附加与工作集均强制 scope 下推/后置复验，既有隔离实测扩展）；未解析 scope 一律拒绝；记忆、`memory_context` 与文件投影内容不控制执行、工具、权限或状态转换（含 agentic 路由下不绕过）；MCP schema 合法率 100%（新增 schema 全量正反例）；证据可定位率 100%（`evidence[]` 未改动）与记忆 provenance 完备率 100%（`soft`/`distilled` 五元元数据、`hard` 逐条复验）分项统计、不混口径；投影完整率 100%（消费层可全量重建、只读、通过删除/来源/回滚校验，且不干扰既有修订目录）。设计无违反；实现任一不满足阻断发布，不能以默认关闭豁免。

## Project Structure

### Documentation (this feature)

```text
specs/014-memory-aware-retrieval/
  spec.md
  plan.md
  research.md
  data-model.md
  quickstart.md
  checklists/requirements.md
  contracts/
    README.md
    common.schema.json                    # 本地引用解析（009 定义原文 + 007 ScopeCandidate 补全）
    mcp-search-input.schema.json          # 014 增量（追加 session_id/memory_context）
    mcp-search-output.schema.json         # 014 增量（related_memories/memory_notice/counts）
    memory-attachment.schema.json         # 新：附加条目（复用 012 memory-entry 词汇，摘录收紧至 200）
    mcp-start-work.input.schema.json      # 014 增量（追加显式开关 include_working_set）
    mcp-start-work.output.schema.json     # 014 增量（working_set legacy 与 014 两种形态）
    working-set-item.schema.json          # 新：工作集三类派生桶条目
    field-order-contract.md               # 新：顶层字段顺序冻结与兼容规则
    memory-consumption-projection.md      # 新：文件投影消费层契约（只读守卫/渲染/重建/漂移）
    continuity-evaluation-contract.md     # 新：连续性对照闸门与报告契约
  tasks.md                                # /speckit-tasks 输出，不由本命令创建
```

### Source Code (repository root)

```text
backend/src/rag_mcp/
  mcp/search_knowledge.py                 # 增量可选参数；显式信号门控；附加层编排与 800ms 预算
  mcp/start_work.py                       # 追加明确开关（StrictBool 默认 false）
  services/memory_reader.py               # recall() 增补 tool/channel 参数；start_work() 新形态分支；纯 helper 改由 packing 导入
  services/memory_service.py              # 新增 attach()：参数化复用 recall()，不新建查询通道
  services/memory_policy.py               # 新增可选策略键（附加预算/阈值、delivered TTL、工作集桶上限）
  orchestration/packing.py                # 新：无依赖纯 helper（timestamp/canonical/text_characters/serialized_characters）
  orchestration/working_set.py            # 新：纯函数工作集组装器（可见性谓词/会话派生/桶排序/装箱决策）
  runtime/memory_projection.py            # 新：消费层渲染/物化/只读守卫/漂移检测/全量重建/异步刷新调度
  models/memory_consumption.py            # 新：消费层元数据模型（指纹/状态/source_event_id）
  config/__init__.py                      # 新开关与消费层根目录设置
  services/maintenance_service.py         # 维护窗口内消费层对账与修复（非唯一触发）
  server.py                               # 消费层刷新/对账任务的启动与回收
backend/alembic/versions/
  0105_memory_delivery_index.py           # memory_recall_runs(session_id, created_at) 支撑索引
  0106_memory_consumption_projection.py   # 消费层元数据表
backend/tests/
  contract/schema_registry_014.py                # 本地 schema registry 与逐字节/混装断言助手
  contract/test_014_search_input_schema.py        # 旧属性 JSON 逐字节不变 + 新属性追加
  contract/test_014_search_bytes_frozen.py        # 冻结 pretty 文本镜像 + 有序键列表 golden
  contract/test_014_search_attachment_schema.py   # 附加条目 schema 正反例 + 与 012 词汇一致性
  contract/test_014_start_work_schema.py          # start_work 增量开关与新形态
  contract/test_014_continuity_dataset.py         # 连续性数据集形态/覆盖/中文/sha256 pin
  contract/test_014_continuity_report.py          # 对照报告 schema 与基线零新字段
  contract/fixtures/014/                          # legacy 字节 golden 夹具
  unit/test_014_working_set.py                    # 纯函数：可见性边界/会话派生/排序/装箱/无 LLM
  unit/test_014_attachment_gating.py              # 信号门控/阈值/预算/降级
  unit/test_014_delivery_set.py                   # 跨通道去重/覆盖/TTL/致空建议
  unit/test_014_projection_render.py              # 渲染确定性/字节稳定/frontmatter
  integration/test_014_consumption_projection.py  # 物化/重建/漂移/删除传播/两布局互不影响
  integration/test_014_no_bypass.py               # AST：消费层无未授权写入口
  integration/test_014_memory_e2e.py              # 014 四类 E2E
eval/
  memory_continuity_eval_dataset.json             # 新：≥15 条四类连续性查询（含中文）
  run_memory_comparison.py                        # 新：带记忆/无记忆对照运行器与报告
  memory_continuity_support.py                    # 新：对照臂恢复/指标/报告编码（复用 013 房规）
  runs/<unique-run>/memory-*.json                 # 报告，不覆盖历史
```

**Structure Decision**: 保持 backend ownership；增量集中在 MCP 契约层、记忆读路径参数化、一个纯函数组装模块与一个只读投影模块，无新仓库、无新检索引擎、无新权威源。`orchestration/packing.py` 只承载与 IO/Qdrant 无关的纯 helper，`memory_reader` 改为从该模块导入以保持同名可用（既有 `from ...memory_reader import serialized_characters/public_entry/...` 不受影响）。消费层元数据用独立表而非复用 `memory_projection_meta`：后者 `versions()` 强制恰好等于六类 `VIEW_KEYS`，追加类型会破坏 012 既有重建校验。

## Phase 0: Research Decisions

research.md 覆盖 13 项决策：复用边界与增量面（§1）、分字段契约兼容性与字段顺序冻结（§2）、附加召回参数化、阈值口径与并发时序（§3）、注入形态、counts 词表与 `memory_context` 检测先行（§4）、会话级已交付集与短 TTL（§5）、未决事项语义边界与工作集组装器（§6）、文件投影只读消费层与只读守卫（§7）、DIGEST/INDEX 生成确定性与字节稳定（§8）、异步刷新不进关键路径（§9）、连续性判据的测量学设计（§10）、三宿主直读可行性实测（§11）、默认启用门控与关闭条件（§12）、材料局限与缺口（§13）。台账原文缺失（①-4/①-11/②-8/③-8 无原文，Q24/Q41–Q43 仅序位推测）与 ADR-12 只有引用无定义，均如实记录、不补造决议。

下表为首次实现的冻结默认值，**不声称经过质量校准**；评测前冻结，修改后重新评测，绝不按模型输出调整。

| 键 | 默认 | 合法范围/约束 |
|---|---:|---|
| `attach_min_score`（既有，本期消费） | 0.0 | `[0,1]`；不改变默认值以免扰动 013 的 `policy_hash` |
| `attach_conservative_min_score`（新） | 0.50 | `[attach_min_score,1]`；未**同时**提供 `memory_context` 与 `session_id` 时的 `dense_similarity` 下限（T106 裁定） |
| `attach_top_k`（新） | 3 | 整数 1–5；硬上限 5 |
| `attach_max_chars`（新） | 800 | 整数 200–800；硬上限 800 |
| `attach_excerpt_chars`（新） | 200 | 整数 1–200；硬上限 200 |
| `attach_timeout_ms`（新） | 800 | 整数 1–800；硬上限 800 |
| `delivered_ttl_seconds`（新） | 3600 | 整数 60–86400；会话级已交付集短 TTL。**已批准变更**：取代 012 既有 7 天 `expires_at` 去重窗口，须在回归报告留证并证明 012 会话时间线 E2E 按新口径通过 |
| `working_set_max_open_items`（新） | 3 | 整数 1–5 |
| `working_set_max_recent_activity`（新） | 3 | 整数 1–5 |
| `working_set_max_procedural`（新） | 2 | 整数 1–5 |
| `MEMORY_AWARE_RETRIEVAL_ENABLED`（Settings） | false | 门控附加层与工作集新形态；未达标保持关闭 |
| `MEMORY_CONSUMPTION_PROJECTION_ENABLED`（Settings） | false | 门控消费层刷新与对账 |
| `MEMORY_CONSUMPTION_ROOT`（Settings） | `<DATA_ROOT 父目录>/memory_projection` | 默认解析为 `./data/memory_projection`；不得与任意 `DATA_ROOT` 或其子目录重叠 |
| `MEMORY_CONSUMPTION_REFRESH_INTERVAL_S`（Settings） | 300 | 维护窗口内对账周期；轮询从不是唯一触发 |

所有整数排除 bool，所有浮点拒绝 NaN/Infinity；策略非法值拒绝而非静默取默认。冻结契约常量（不随策略放宽）：附加条数上限 5、附加总长上限 800 字、摘录上限 200 字、附加超时上限 800ms。

## Phase 1: Implementation Groups

以下为供 tasks 阶段拆分的单元/依赖，**不是实施完成声明**。

| 单元 | 产出 | 依赖 | 独立验证 |
|---|---|---|---|
| A 契约/策略 | 014 输入/输出/start_work 增量 schema、`memory-attachment.schema.json`、字段顺序契约、`MemoryPolicy` 新键、`Settings` 新开关与消费层根目录 | 009/012/013 | 旧属性 JSON 逐字节不变、`required` 不变、新键缺省不激活、非法值拒绝、顺序契约文档与断言一致 |
| B 附加层召回 | `search_knowledge` 可选参数与显式信号门控；`memory_context` 检测先行（检测并记 flags 后再进入任何召回/打分/排序/拼装）；`MemoryService.attach` 参数化复用 `recall` 并与主检索**并发发起**、组装点合并、完成/超时一并回收；阈值/预算/独立降级/状态复验 | A | 未触发字节不变；失败不改主状态；阈值与预算边界；并发发起率 100% 且端到端 ≤ max(主,附加)；同域泄漏 0 |
| C 注入形态 | 冻结字段顺序（含 partial/失败分支，evidence 与 related_memories 字段层相邻）、`memory_notice` 对象、`counts` 词表、`injection_flags` 随行、裁剪优先级、定位语义分界（记忆不带 `source_position`） | A,B | 有序键列表 + 冻结 pretty golden；混装 0；notice 双要素 100%；记忆携带证据定位字段数 0 |
| D 已交付集 | `recall` 写入 `channel`/`tool`；跨通道去重查询与短 TTL（`delivered_ttl_seconds` 默认 3600，取代 012 的 7 天窗口，属已批准变更）；`include_delivered` 覆盖；去重致空建议动作 | A,B | 三通道去重、覆盖只放宽去重、TTL 过期不复用、致空返回"无可用记忆"空态且**不改写** `completion_status`/`evidence` |
| E 工作集组装器 | `orchestration/packing.py` 提纯、`orchestration/working_set.py` 纯函数、`start_work` 增量开关与装箱 | A,D | 纯函数确定性/无 LLM；未决事项边界；quarantined/archived=0；legacy 字节稳定；预算与 read_guidance |
| F 文件投影 | `runtime/memory_projection.py` 渲染/物化/只读守卫/漂移/重建；迁移 0105/0106；异步刷新与维护对账 | A | frontmatter 与正文原文一致；重建=日志且模型调用 0；直写 0（含 AST）；两布局互不影响；删除/回滚传播 |
| G 评测/发布 | `eval/memory_continuity_eval_dataset.json`、`run_memory_comparison.py`、闸门判定、三宿主冒烟、全集回归 | B,C,D,E,F | ≥15 条四类且含中文；基线禁参数；≥3% 或显式判据；硬指标；012 8 项、013 7 项、既有检索全集 |

先建立契约与旧字节冻结验证，再接有权限隔离的读路径与投影，最后跑对照与回归。质量评测使用同原始快照的隔离副本，报告写入不覆盖历史的路径。

## Requirement Coverage

| 要求 | 设计/验证 |
|---|---|
| FR-001/002/003 | A/B/C 显式信号门控、三者同生共死、分字段、provenance 与 flags、定位语义分界（记忆不带 `source_position`/`source_version`）、`hard` 逐条归属复验与 `soft`/`distilled` 五元元数据；SC-001/002 |
| FR-004/005/006/007/008 | B 独立降级、预算、阈值双档、状态复验；SC-003/004 |
| FR-009…FR-015 | A/C 序列化镜像、字段层分隔、notice、顺序契约、裁剪优先级、counts、注入边界；SC-005/006/007 |
| FR-016…FR-019 | D 已交付集、跨通道去重、覆盖、致空建议、非事实源；SC-008 |
| FR-020…FR-024 | E 三类派生、纯函数、装箱纪律、状态排除、增量兼容；SC-009 |
| FR-025/FR-025a | A/F 消费层布局与分层并存、契约标注、既有修订目录实测形态（含 `012-v1/<kind>` 与 `archives/`）零接触；SC-016 |
| FR-026…FR-032 | F frontmatter（含 `untrusted: true`）/原文、DIGEST/INDEX 不可信声明、重建、非事实源、禁止直写、异步刷新、删除传播；SC-011/012/013 |
| FR-033/FR-034/FR-035 | G 评测集（跨环境稳定锚点、审核记录 `_meta` 形态）、对照闸门、三闸与默认关闭；SC-010/015 |
| FR-036/FR-037/FR-038/FR-039 | G 四类 E2E、三宿主冒烟、既有全集无回归（非延迟 1% 容差 + 交付窗口变更留证）、错误码只增不删；SC-014/015 |

US1 由 B/C 覆盖，US2 由 C 覆盖，US3 由 D 覆盖，US4 由 E 覆盖，US5 由 G 覆盖，US6 由 F 覆盖，US7 由 G 覆盖。SC-001–SC-016 均有对应观测；不得以文档、mock 或单测替代真实 PG/Qdrant、host 与对照实证。

## Validation And Delivery Gates

1. 契约/纯函数：新 schema 全部 Draft202012 引用可解析、正反例通过；旧属性 JSON 与 `required` 逐字节不变；字段顺序断言与冻结 pretty/structured golden 一致（`search_knowledge` 014 分支与 legacy 分支、`start_work` 顶层运行时顺序各一份）；纯函数在给定输入下字节稳定且无模型调用。
2. 隔离/安全：附加层与工作集跨域泄漏 0；quarantined/superseded/retired/archived/过期进入 0；`injection_flags` 随行 100%；`memory_context` 检测先行 100%（含检测失败不阻塞、不放宽）；`soft`/`distilled` 五元元数据完备、`hard` 逐条归属复验通过；消费层 AST 无旁路、绕过直写 0、`untrusted: true` 标记完备；未解析/歧义 scope 拒绝且不回落。
3. 读取行为：未触发路径字节不变（含 `AGENTIC_RETRIEVAL_ENABLED=true` 路径）；三态触发；阈值与预算边界；附加层与主检索并发发起且不增加端到端延迟；记忆侧失败不改主状态；已交付集三通道去重、覆盖、TTL 过期与致空建议（不改写主检索 `completion_status`）；工作集未决事项边界与 legacy 字节稳定。
4. 投影：消费层渲染确定性、frontmatter/正文一致、`untrusted: true` 标记完备、清空后全量重建与日志一致、刷新/对账异步且失败可恢复、删除/回滚传播；既有 `data/uploads/memory_projection/<数字 id>/<数字 id>/`（含 `012-v1/<数字 id>/<kind>/` 与 `archives/`）修订目录及其校验器/重建/回滚报告路径零改动。
5. 发布：真实域冻结 ≥15 条四类查询（含中文 ≥2、锚点跨环境稳定、审核记录随库）、基线禁用相关参数、记录/重放可复现、≥3% 或显式判据、硬指标全过（可定位与 provenance 分项）、012 的 8 项 E2E、013 的 7 项 E2E、既有检索全集与旧客户端逐字节不变（非延迟 1% 容差）、交付去重窗口变更留证。质量/复现不完整即默认关闭；安全失败阻断发布。

## Complexity Tracking

无宪法例外。必要复杂性来自三处既有约束：`search_knowledge` 的文本镜像由 FastMCP 生成 pretty JSON 而非 `memory_result` 紧凑序列化，因此字节冻结必须用 golden 断言而非统一序列化器；`working_set` 既有谓词因 `expires_at` 恒非空而在真实数据上恒空，新形态必须显式定义开放度谓词并以数据派生的 `snapshot_at` 保证字节稳定；消费层与既有修订目录必须分层并存，故新增独立元数据表而不复用 `memory_projection_meta`（后者 `versions()` 强制恰好六类）。未另建事实权威、未新建检索通道、未新增 MCP 工具。
