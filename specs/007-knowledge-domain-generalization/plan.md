# Implementation Plan: Knowledge Domain Generalization (007)

**Branch**: `007-knowledge-domain-generalization` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-knowledge-domain-generalization/spec.md`；技术决策与评测目标闸门见 [research.md](./research.md)（§0 先声明相对既有基线的评测目标：无对照、架构泛化非回归 + 硬性指标保持）；数据模型见 [data-model.md](./data-model.md)；契约见 [contracts](./contracts/)；验证指南见 [quickstart.md](./quickstart.md)。

## Summary

007 在 001–006 已交付的检索能力之上做知识域泛化：**双轴知识域模型**（`scope_type` 结构轴沿用 project/public × 新增 `domain_key` 语义轴，正交自由组合）、**域档案注册表**（新表 `domain_profiles` 承载 supported_formats/chunk_type_extensions/graph_relations/prompt_overrides/default_capabilities，内置 se-project 与 generic 两档案，se-project 行为与 1.0 完全一致）、**MCP 兼容扩展**（`search_knowledge`/`get_evidence` 新增可选 `domain_scope`，与 `project_scope` 并集去重进统一解析器，二者至少一个非空，旧客户端逐字节不变；新增只读工具 `list_knowledge_domains` 只返回域元数据绝不返回知识内容）、**scope slug 全局按名寻址**（含 type:name 限定引用）与**三处 public/project 残留修复**（get_evidence public 断链 / agentic scope_type 硬编码 / 图三元组强制 Project 行）。检索路径默认行为零改动（宪法 VII）；对照评测要求为"无（架构泛化，非检索质量）"，替代义务 = 既有全集非回归三项 + 硬性指标保持 + 新功能验收（research §0）。

## Technical Context

**Language/Version**: Python 3.12（`requires-python >=3.12`，ruff target py312；宪法架构约束 Python/LangGraph/LangChain 后端基线，沿用 001–006）。

**Primary Dependencies**: FastAPI（管理面，复用 001）、FastMCP（MCP 服务，`mcp>=1.2.0`，签名即 schema——anyOf 约束由入口层显式校验补位）、SQLAlchemy async + asyncpg（复用 001）、Alembic（迁移，沿用 001 既有链）、Qdrant（检索，复用 001/002，不改）、`snowflake-id`（主键生成）、`jsonschema`（契约校验）、pydantic（REST 模式）。

**Storage**: PostgreSQL——新增 `domain_profiles` 表；`knowledge_scopes` 扩展 `domain_key`（FK 缺省 se-project）+ `slug`（全局唯一）；`graph_edge`/`soft_relation` 删除 `project_id` 列并重建含该列的复合索引。Qdrant 不变。详见 [data-model.md](./data-model.md)。

**Testing**: pytest（contract/integration/unit）+ 契约 Schema 校验（json-schema 2020-12，6 个 007 schema）+ 迁移/回填/启动同步集成测试 + `eval/` 既有套件重跑（run_comparison/run_graph_comparison/run_agentic_comparison/run_instance_form_smoke）+ 旧客户端逐字节兼容测试。

**Target Platform**: 本机 loopback HTTP（单用户，默认 127.0.0.1 绑定，宪法架构约束）；Streamable HTTP MCP 为主；DeepSeek Harness 为唯一必过参考客户端。

**Project Type**: web-service（扩展 001–006 既有 backend + frontend 展示泛化）。

**Performance Goals**: 检索热路径零变化——`project_scope` 路径零新增查询（P50/P95 期望无系统性变化）；`domain_scope` 仅新增 slug/type:name 解析分支（不进入 project_scope 路径）；`list_knowledge_domains` 单表扫描、秒级返回；无新增 LLM 调用（成本 0 变化）。

**Constraints**: 硬约束继承（跨域泄漏=0 / Schema 100% / 定位 100% / 显式引用）；旧客户端仅传 project_scope 逐字节不变（FR-009）；内置档案只读保护（含字段级，Q1）；slug 全局唯一 + 创建后不可变（Q2）；错误码枚举只增不删（FR-010）；`list_knowledge_domains` 绝不返回知识内容（FR-014/FR-022）。

**Scale/Scope**: 单用户本机；007 规模 60–75 任务（蓝图 §7）；混合域验收集 ≥2 project + ≥1 public（跨 se-project/generic 档案）；slug 全局命名空间跨 project/public。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.* 依据 `/.specify/memory/constitution.md` v1.3.0（原则 I/II/X 域中立化 + 新增原则 XI + 五硬约束跨域语义；ADR-7 已批准生效）。Phase 0 research.md §0 已置顶声明相对既有基线的评测目标（对照要求 = 无（架构泛化，非检索质量）；通过判定 = 非回归三项 + 硬性指标保持，FR-023/FR-024），满足"research.md 必须先声明评测目标"。

### Non-Negotiable Hard Constraints（宪法 v1.3.0 跨域语义）

| 硬约束 | 状态 | 依据 |
|--------|------|------|
| 跨知识域泄漏 = 0 | ✅ PASS | FR-020/SC-003：统一解析器输出活跃域集合，knowledge_scope_id 为唯一图隔离键（FR-018）；混合域验收集泄漏事件 = 0 |
| 无显式知识域引用检索须拒绝 | ✅ PASS | FR-007/FR-019/SC-012：入口层显式校验两参数并集非空，缺则拒绝、不回退默认/全库 |
| 上传内容不得作控制指令 | ✅ PASS | domain_profiles 为管理面配置数据（宪法 V）；007 不接入 prompt_overrides 运行时注入（属 009），不可信内容零接触 |
| MCP Schema 合法率 100% | ✅ PASS | FR-021/SC-004：输入 anyOf 放宽 + 错误码只增不删 + 候选增量字段，全部响应过声明 Schema |
| 证据来源可定位率 100% | ✅ PASS | FR-016/SC-005：public 证据展开修复后仍携带来源 ID/版本/位置 |

### Core Principles（11 条）

| 原则 | 状态 | 依据 |
|------|------|------|
| I 显式知识作用域 | ✅ PASS | FR-007/FR-019：project_scope 或 domain_scope 任一形式，二者至少一个非空 |
| II 域事实优先 | ✅ PASS | 007 不触碰检索融合/排序/公共与域证据并列语义；仅扩展作用域引用面 |
| III 暴露不确定性 | ✅ PASS | AMBIGUOUS_DOMAIN_REF 携带 scope_type/domain_key/slug 候选；四态 completion_status 不变 |
| IV 来源可定位 | ✅ PASS | FR-016 public 证据展开修复保持来源 ID/版本/位置；list_knowledge_domains 不返回正文 |
| V 数据与控制分离 | ✅ PASS | domain_profiles 为配置声明（FR-006 不含知识内容）；prompt_overrides 属管理面配置，007 不接线注入 |
| VI 确定性控制优先 | ✅ PASS | 统一引用解析器为确定性裁决；slug 唯一约束 DB 仲裁；无新增 LLM 判断 |
| VII 接口独立演进 | ✅ PASS | 007 契约独立 `$id /schemas/007/` 分版本演进；MCP 输入 anyOf 放宽（错误码只增不删）；DB 模型独立迁移 |
| VIII 知识版本不可混用 | ✅ PASS | project_id 经 scope→Project 联查派生、图数据可重建（FR-018）；007 不引入新索引版本 |
| IX 同步结果优先 | ✅ PASS | list_knowledge_domains 为同步只读工具；不依赖 Resources/Tasks |
| X 评测驱动优化 | ✅ PASS | research §0 闸门：对照要求 = 无（架构泛化）；替代义务 = 非回归三项 + 硬性指标（FR-023/FR-024）；无质量声明 |
| XI 领域中立 | ✅ PASS | 领域差异经 domain_profiles 声明（FR-003~FR-006）；se-project 为首个内置档案而非默认假设；007 不硬编码新领域假设 |

**Gate 结论**：无违规；无 Complexity Tracking 条目（无原则豁免）。**Phase 1 设计后复核**：data-model/contracts/quickstart 均不引入新违规——`domain_profiles` 为配置表（不进知识库/向量库）；`knowledge_scopes` 扩展列（domain_key/slug）不改变既有隔离语义；`graph_edge`/`soft_relation` 删列收敛隔离键、project_id 可派生重建；6 个 schema 独立 `$id` 演进、`$ref` 复用 007 common.schema.json；`list_knowledge_domains` 契约显式排除知识内容——全部硬约束与原则保持 PASS。

## Project Structure

### Documentation (this feature)

```text
specs/007-knowledge-domain-generalization/
├── plan.md              # 本文件（/speckit-plan 产出）
├── research.md          # Phase 0 产出（§0 评测目标闸门：对照"无" + 非回归判定 + 5 项技术决策）
├── data-model.md        # Phase 1 产出（domain_profiles 建表 / knowledge_scopes 扩展 / graph 删列 / slug / 引用与摘要）
├── quickstart.md        # Phase 1 产出（10 个端到端验证场景）
├── contracts/           # Phase 1 产出（MCP 契约 + 管理面契约，复用 common.schema.json 共享定义）
│   ├── common.schema.json                       # 共享定义（DomainKey/ScopeSlug/KnowledgeDomainReference/ScopeCandidate/能力摘要/错误码枚举）
│   ├── mcp-search-input.schema.json             # search_knowledge 输入（domain_scope + anyOf 放宽）
│   ├── mcp-get-evidence.schema.json             # get_evidence 输入/输出（domain_scope + anyOf，输出零改动）
│   ├── mcp-search-output.schema.json            # search_knowledge 输出（错误码只增不删 + 候选增量字段）
│   ├── list-domains.output.schema.json          # list_knowledge_domains 输出（元数据、无知识内容）
│   └── domain-profiles.management.schema.json   # 管理面域档案 CRUD + 知识域 domain_key/slug 分配
└── tasks.md             # /speckit-tasks 产出（本命令不创建）
```

### Source Code (repository root)

```text
backend/
├── src/rag_mcp/
│   ├── models/
│   │   ├── domain_profile.py            # 007 新增：DomainProfile ORM（domain_key PK + 6 配置字段 + is_builtin）
│   │   ├── knowledge_scope.py           # 扩展：domain_key（FK 缺省 se-project）+ slug（全局唯一）
│   │   └── graph/models.py              # 收缩：GraphEdge/SoftRelation 删除 project_id 列
│   ├── services/
│   │   ├── retrieval_service.py         # 改造：resolve_project_refs → resolve_knowledge_scopes（双参数并集 + slug/type:name）；_graph_scope_triple 去 Project 依赖
│   │   ├── evidence_service.py          # 修复：_resolve_scope_ids 复用统一解析器（public 断链）
│   │   ├── project_service.py           # 扩展：域档案 CRUD 服务 + slug 生成/分配 + domain_key 声明
│   │   └── domain_profile_service.py    # 007 新增：进程内注册表同步 + 内置只读保护守卫
│   ├── orchestration/
│   │   └── retrieval_pipeline.py        # 修复：knowledge_scope_type 硬编码 → 按 scope 实际类型（:451,:468）
│   ├── mcp/
│   │   ├── search_knowledge.py          # 扩展：domain_scope 可选参数 + 入口并集非空校验
│   │   ├── get_evidence.py              # 扩展：domain_scope 可选参数 + 入口并集非空校验
│   │   └── list_knowledge_domains.py    # 007 新增：只读工具（元数据、无知识内容）
│   ├── api/
│   │   └── projects.py                  # 扩展：域档案 CRUD 路由 + 知识域 domain_key/slug 管理
│   ├── schemas/
│   │   └── project.py                   # 扩展：域档案 / scope 分配 Pydantic 模式
│   ├── config/
│   │   └── domain_profiles.py           # 007 新增：内置档案种子定义 + 启动同步（漂移修复，失败显式失败）
│   └── ... (复用 001–006 既有 modules，检索路径默认行为零改动)
├── alembic/versions/
│   ├── 0070_create_domain_profiles.py   # domain_profiles 建表 + 内置 se-project/generic 种子
│   ├── 0071_extend_knowledge_scopes.py  # domain_key + slug 加列 + 存量回填（domain_key=se-project + 唯一 slug 生成）
│   └── 0072_drop_graph_project_id.py    # graph_edge/soft_relation 删 project_id + 索引重建
└── tests/
    ├── contract/                         # 6 个 007 schema 契约校验 + 对外 MCP schema 不回归 + 逐字节兼容
    ├── integration/                      # 迁移/回填/启动同步/域档案 CRUD（内置只读）/domain_scope 三种寻址/双参数并集/错误码双轨
    └── unit/                             # 统一解析器边界（空串/重复/混合）/slug 生成与唯一性/图隔离键/scope_type 修复

frontend/
└── src/
    ├── pages/                            # 扩展：知识域列表/详情呈现 scope_type/domain_key/slug；域档案管理页
    └── api/                              # 扩展：域档案 CRUD + scope 分配的 API client
```

**Structure Decision**: 单 web-service 后端，扩展 001–006 既有 `backend/src/rag_mcp/`，新增 `models/domain_profile.py`、`services/domain_profile_service.py`、`mcp/list_knowledge_domains.py`、`config/domain_profiles.py`；改造 `services/retrieval_service.py`（统一解析器 + 图三元组）、`services/evidence_service.py`（public 断链）、`orchestration/retrieval_pipeline.py`（scope_type 硬编码）；迁移链从既有 head（0062）续接 0070~0072。frontend 仅展示与管理泛化（不新增检索 UI）。

### 数据模型扩展

详见 [data-model.md](./data-model.md)。新增 `domain_profiles` 表（domain_key PK + supported_formats/chunk_type_extensions/graph_relations/prompt_overrides/default_capabilities JSONB + is_builtin）；`knowledge_scopes` 扩展 `domain_key`（FK 缺省 se-project）与 `slug`（全局唯一、创建后不可变）；`graph_edge`/`soft_relation` 删除 `project_id` 列并重建含该列的复合索引（`knowledge_scope_id` 成为唯一图隔离键）。迁移仅由 writer 管理进程执行（沿用 006）；Qdrant 零改动。

### 契约变更

契约置于 [contracts/](./contracts/)，`$ref` 复用 007 common.schema.json 共享定义（独立 `$id /schemas/007/` 分版本演进）。**对外 MCP 契约变更仅限**（FR-011）：① 输入 schema 新增可选 `domain_scope` + `required:["project_scope"]` 放宽为 anyOf（二者至少一个）；② 错误码枚举只增不删（新增 MISSING_KNOWLEDGE_SCOPE / AMBIGUOUS_DOMAIN_REF）；③ candidates 增量添加可选 scope_type/domain_key/slug；④ 新增 `list_knowledge_domains` 输出契约。输出结构（evidence 的 knowledge_scope_id/knowledge_scope_type 等）零改动；旧码响应 candidates 字节级保持 1.0 形态。

## Complexity Tracking

> 无 Constitution 违规需豁免——本表为空。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
