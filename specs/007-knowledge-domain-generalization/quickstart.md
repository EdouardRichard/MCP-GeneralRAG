# Quickstart: Knowledge Domain Generalization (007)

**Branch**: `007-knowledge-domain-generalization` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)

> 端到端验证指南。契约引用见 [contracts](./contracts/)，数据模型见 [data-model.md](./data-model.md)，技术决策与评测目标见 [research.md](./research.md)。本指南只约束可观测的期望结果与验收口径；具体命令、迁移与完整测试套件由 tasks.md 与实现阶段提供。

## 前置条件

- 001–006 已交付并可运行：Web 管理、上传/切片/入库、Dense+Sparse+RRF+Rerank、图扩展、三 Agent 编排、MCP `search_knowledge`/`get_evidence`。
- PostgreSQL 与 Qdrant 可用（共享存储，蓝图 §8/§21.2）；007 迁移已执行（`domain_profiles` 建表 + 内置种子 + `knowledge_scopes.domain_key`/`slug` 回填 + `graph_edge`/`soft_relation` 删 project_id 列）。
- 评测基线工件存在：`eval/baseline_report.json`、`hybrid_comparison_report.json`、`graph_enhanced_comparison_report.json`、`agentic_comparison_report.json`、`instance_form_smoke_report.json`。
- 已创建至少一个 public+generic 知识域（或验收夹具），并有一个 project+se-project 存量域。
- 本机已安装 DeepSeek Harness（唯一必过参考客户端，SC-001；ChatGPT App 与 Claude Code 记录兼容性状态、不阻塞）。

## 场景 1 — 迁移与启动同步

**验证**：User Story 1/FR-002/FR-004/FR-005/SC-008。

1. 对存量库执行 alembic 迁移并启动系统。
2. 期望：`domain_profiles` 存在 se-project 与 generic 两内置行（is_builtin=true）；se-project 声明 8 种原生格式（markdown/java/openapi/ddl/go/python/word/pdf）+ calls/called_by/fk_references/fk_referenced_by 图关系词表 + SE planner 提示词；generic 声明通用文档格式集 + 空图关系 + 域中立提示词（[domain-profiles.management.schema.json](./contracts/domain-profiles.management.schema.json) 校验通过）。
3. 期望：全部存量 `knowledge_scopes` 获得 `domain_key='se-project'` 与唯一 `slug`；迁移后行为与升级前一致。
4. 期望：数据库行与进程内注册表一致（漂移 = 0）；人为篡改内置行字段后重启，漂移被修复；同步失败显式失败启动。

## 场景 2 — 域档案治理（内置只读 + 自定义 CRUD）

**验证**：User Story 1/FR-003/FR-005/FR-006/SC-008。

1. 经管理面（REST + Web）尝试修改/删除 se-project 与 generic 两内置档案（含字段级修改）。
2. 期望：100% 被拒绝并返回明确错误（内置只读保护）。
3. 创建自定义档案（声明格式集/词表/提示词/能力），随后更新、删除。
4. 期望：可创建、可被新知识域引用、可更新、可删除；仍被知识域引用时删除被拒绝（引用完整性不悬空）。
5. 读取任一档案。
6. 期望：档案数据仅为配置声明（格式名/词表/提示词片段/能力清单），不含任何知识内容。

## 场景 3 — 知识域创建（domain_key + slug）

**验证**：User Story 1/FR-001/FR-012/SC-011。

1. 创建一个 public+generic 知识域并显式指定 slug；再创建 project+se-project 域。
2. 期望：两域均携带 scope_type 与 domain_key 两正交维度；slug 全局唯一（重复 slug 创建 100% 被拒）。
3. 尝试变更已创建域的 slug。
4. 期望：变更请求 100% 被拒（创建后不可变）。

## 场景 4 — domain_scope 三种寻址形态

**验证**：User Story 2/FR-007/FR-008/FR-013/SC-002。

1. 用 MCP 客户端分别以数字 knowledge_scope_id、scope slug、type:name（如 `public:法规库`）作为 `domain_scope` 检索 public+generic 域。
2. 期望：三种形态各自寻址成功、返回该域证据且 100% 通过输出 Schema 校验（[mcp-search-output.schema.json](./contracts/mcp-search-output.schema.json)）。
3. 以 domain_scope 寻址一个 project 类型域。
4. 期望：结果与等价 project_scope 引用检索一致（同一 scope 集合决定检索范围）。

## 场景 5 — 双参数并集去重

**验证**：User Story 2/FR-007/SC-002、Edge Cases。

1. 混合 project_scope + domain_scope 发起联合检索（含同一域被两参数重复引用、字面重复条目、空串/纯空白条目）。
2. 期望：两参数取并集、按解析结果去重；重复引用不放大结果集；空串条目跳过；跳过后无任何可解析引用则按缺失作用域拒绝。
3. 仅传 domain_scope 检索。
4. 期望：成功（入口层校验两参数并集非空，仅 domain_scope 形态合法）。

## 场景 6 — 错误码双轨

**验证**：User Story 2/FR-010/SC-010/SC-012。

1. 仅 project_scope 形态触发缺失/歧义场景（含两参数皆空）。
2. 期望：100% 返回旧码（MISSING_PROJECT_SCOPE / AMBIGUOUS_PROJECT_REF），candidates 字节级保持 1.0 形态。
3. 涉及 domain_scope 触发缺失/歧义（如 type:name 命中多个同名同类型活跃域）。
4. 期望：100% 返回新码（MISSING_KNOWLEDGE_SCOPE / AMBIGUOUS_DOMAIN_REF），candidates 增量携带 scope_type/domain_key/slug。
5. 无任何知识域引用的请求。
6. 期望：100% 被拒绝，全库回退事件数 = 0。

## 场景 7 — 旧客户端逐字节兼容

**验证**：User Story 2/User Story 5/FR-009/SC-001。

1. 仅传 project_scope 的兼容测试请求集（覆盖成功、歧义、缺失、非法输入形态）在 007 前后重放。
2. 期望：响应（错误码/错误消息/candidates/输出结构）逐字节一致；001–006 既有验收套件全绿。

## 场景 8 — list_knowledge_domains

**验证**：User Story 3/FR-014/FR-015/FR-022/SC-006。

1. 调用 `list_knowledge_domains`。
2. 期望：仅活跃域返回，每条含 ID/slug/名称/scope_type/domain_key/能力摘要（[list-domains.output.schema.json](./contracts/list-domains.output.schema.json) 校验通过）；archived/deleting 域不出现。
3. 审计响应内容。
4. 期望：知识内容出现次数 = 0（无 chunk 正文/证据摘录/来源片段；能力摘要来自域档案声明）。
5. 无活跃域实例调用。
6. 期望：返回空列表 + 成功状态，不报错。

## 场景 9 — 三处 public 残留修复

**验证**：User Story 4/FR-016/FR-017/FR-018/SC-007。

1. 在 public 域上传含可解析内容的材料并发布，以数字 public scope ID 检索并展开证据（search_knowledge → get_evidence 同作用域）。
2. 期望：证据展开成功、含完整内容与来源定位（不再断链）。
3. 开启 agentic 路径检索 public 域。
4. 期望：返回证据的 knowledge_scope_type 为 "public"（不再硬编码 "project"）；project 域证据不受影响。
5. 对声明 graph_ready 的 public 域发起图增强检索。
6. 期望：图路径可用（不再因缺 Project 行被排除）；knowledge_scope_id 是唯一图隔离键，跨域图边泄漏 = 0。

## 场景 10 — 无回归与硬性指标

**验证**：User Story 5/FR-024/SC-003/SC-004/SC-005/SC-009。

1. 重跑 001/002 基线（`python eval/run_comparison.py --limit 18`）、004 图集（`python eval/run_graph_comparison.py`）、005 agentic（`python eval/run_agentic_comparison.py`）、006 冒烟（`python eval/run_instance_form_smoke.py`）与 pytest 全集。
2. 期望：非延迟指标在 1% 相对容差内一致（单侧非回归下界）；pytest 全绿。
3. 在混合知识域验收集上断言硬指标。
4. 期望：跨域串库 = 0、MCP Schema 合法率 = 100%、来源可定位率 = 100%。

---

## 验证结果记录（T047 / T056 收敛）

> 007 交付后 10 场景的可观测验证结果与验收证据。自动化测试与评测工件均提交于 007 分支；目标宿主（DeepSeek Harness）MCP 端到端状态见「场景 4/8 附注」。

### 评测工件（T043 无回归重跑，已入库 eval/）

| 套件 | 报告 | 硬约束（串库/Schema/定位） | 非延迟可复现 | 结论 |
|------|------|---------------------------|--------------|------|
| 002 混合基线（--limit 18） | eval/007_hybrid_report.json | 0 / 100% / 100% | true | 无回归，enters_default_path=true |
| 004 图集（37 条） | eval/007_graph_report.json | 0 / 100% / 100% | true | three_gate_pass=true |
| 005 agentic（44 条） | eval/007_agentic_report.json | schema_valid_all=true | true | 无回归 |
| 003 格式集 / 002 有限集 | eval/format_expansion_report_002_limited.json | — | — | 重跑通过 |
| 006 冒烟（11 条） | eval/instance_form_smoke_report.json | — | — | 重跑通过 |

### 场景 → 自动化测试映射

| 场景 | 验证目标 | 自动化测试文件 |
|------|----------|----------------|
| 1 迁移与启动同步 | FR-002/004/005/SC-008 | test_migration_007.py、test_domain_profile_seed.py、test_domain_profile_sync.py |
| 2 域档案治理 | FR-003/005/006/SC-008 | test_profile_crud.py、test_domain_profile_schema.py |
| 3 知识域创建 | FR-001/012/SC-011 | test_scope_slug.py |
| 4 domain_scope 三形态 | FR-007/008/013/SC-002 | test_search_domain_scope_mcp.py（T054）、test_resolver_addressing.py |
| 5 双参数并集去重 | FR-007/SC-002 | test_resolver_boundaries.py、test_search_domain_scope_mcp.py |
| 6 错误码双轨 | FR-010/SC-010/SC-012 | test_error_dual_track.py |
| 7 旧客户端逐字节 | FR-009/SC-001 | test_byte_compat.py |
| 8 list_knowledge_domains | FR-014/015/022/SC-006 | test_list_domains_mcp.py（T053）、test_list_domains_schema.py、test_hard_metrics.py |
| 9 三处残留修复 | FR-016/017/018/SC-007 | test_public_evidence.py（T051）、test_agentic_scope_type.py（T050）、test_graph_isolation.py |
| 10 无回归 + 硬指标 | FR-019~024/SC-003~009 | test_hard_metrics.py + 上表评测工件 |

### 场景 4/8 目标宿主（DeepSeek Harness）附注

MCP 入口层验收已由 FastMCP call_tool 自动化测试固化（T053/T054）：工具经真实注册 + 入口调用 + 声明 Schema 校验，构成 SC-002/SC-004/SC-006 的可复现判据。当前会话 GUI「MCP」浮窗所连 rag-mcp 服务器暴露的是 007 之前的签名（search_knowledge/get_evidence 无 domain_scope、无 list_knowledge_domains、描述仍为 "Requires explicit project scope(s)"）——需在 007 分支重启该 MCP 服务器后，方可对 domain_scope 三形态 + list_knowledge_domains 做实机 DeepSeek Harness 端到端调用。

