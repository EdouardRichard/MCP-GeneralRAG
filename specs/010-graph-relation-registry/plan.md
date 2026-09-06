# Implementation Plan: 图关系注册表（GraphExtractor 插件接口 + 交叉引用提取器）

**Branch**: `010-graph-relation-registry` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/010-graph-relation-registry/spec.md`（含 2026-09-06 澄清 Q1–Q4）

## Summary

将 004 的 duck-typing 图提取器契约收编为正式 **GraphExtractor 插件接口**（`extract(source, chunks, scope) -> list[edge]`，提取器声明 format 与成对关系类型），新建**图关系注册表**按 `format + domain_key`（经域档案 graph_relations 词表交集）发现提取器；java_call_graph / ddl_fk 迁移至接口（行为逐条不变）。将 `graph_edge.relation_type` 的闭合枚举 CHECK 放宽为宽模式 pattern + 应用层按域词表校验（`other_hard` 退役），同步加法放宽两份图关系契约 schema（内部数据契约 + MCP 图标注契约）。交付**文档交叉引用提取器**（Markdown 内部/相对链接 + 中英文法规条文引用 → `references/referenced_by` 成对硬边，混合锚定：来源按行号区间、目标按标题路径）作为非 SE 域验证提取器，落地 **legal 内置域档案**为其挂载域。清除图扩展查询侧三处 SE 硬编码（expansion 默认对、pipeline VALID_DIRECTIONS、反向 CTE CASE），使查询侧词表兼容随域档案声明。评测双档：004 图集 37 条无回归（1% 容差）+ 交叉引用受益子集 ≥6 条结构性受益 ≥3%（沿用 004 SC-001 闸口形式）。

## Technical Context

**Language/Version**: Python 3.12（后端）；前端无改动（007 已泛化域档案展示，legal 档案经既有 UI 自动呈现）

**Primary Dependencies**: 现有依赖零新增——SQLAlchemy 2.0（asyncpg）、Alembic、markdown-it-py（Markdown AST/行号，交叉引用提取复用其解析范式）、pytest/pytest-asyncio/jsonschema；不引入新解析器依赖

**Storage**: PostgreSQL（graph_edge 宽模式 CHECK 迁移 0074、domain_profiles 增 legal 内置行——经 007 启动同步种子，无 DDL）；Qdrant payload 不变

**Testing**: pytest 三层（unit/contract/integration）+ eval 对照运行器（复用 `GraphComparisonRunner` 三段闸口范式）；004 既有图测试集回归为闸口

**Target Platform**: Linux 服务器本机部署（loopback），沿用 001–009 环境

**Project Type**: web-service + MCP server（图关系注册表为摄入/检索内部架构，MCP 对外契约仅加法放宽 relation_type 取值域）

**Performance Goals**: 图扩展护栏沿用 004（跳数默认 2/上限 3、候选预算 10/20、图子超时 3s、总超时 30s）；交叉引用提取为入库期同步步骤，不新增运行时预算维度

**Constraints**: 提取器失败降级沿用 `ingestion_service.py:858-863`（记 reason、产 0 边、不断链）；注册表构建失败 = 启动失败（沿用 008 §5 范式）；SQL relation_type 过滤必须参数化（词表键可来自用户自定义档案，防注入）；宽模式 pattern `^[a-z][a-z0-9_]{0,62}$`（沿用 0073 范式）

**Scale/Scope**: 单用户本机；3 个内置域档案（se-project/generic/legal）；内置提取器 3 个（java_call_graph/ddl_fk/cross_reference）；评测语料：既有 004 图集 37 条 + 新法律域语料与 ≥6 条受益子集

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪法条款 | 映射 | 状态 |
|---------|------|------|
| I 显式知识域引用 | FR-024：图增强检索继承显式 project_scope/domain_scope，缺失拒绝、不回退全库 | ✅ 通过 |
| II 域事实优先 | 图层不涉及跨域证据融合；legal 域证据携带自身 scope 标识，public/project 并发语义由检索层既有机制保证 | ✅ 通过（不适用摄入/图层） |
| III 暴露不确定性 | FR-015 只对可确定引用产边（不可解析目标不产边）；提取失败降级记 reason 产 0 边；硬/软区分与软关系四态不变（FR-021/FR-022） | ✅ 通过 |
| IV 可定位证据 | FR-014/FR-027/SC-005/SC-012：每条硬边 parse_evidence（source_format/extractor/locator），locator 编码锚点/相对路径/条文号与行号，定位率 100% | ✅ 通过 |
| V 数据与控制分离 | 提取器消费已脱敏 redacted_text；提取器选择由注册表声明驱动，上传内容不控制分派；词表键经 pattern 校验入 SQL 参数化 | ✅ 通过 |
| VI 确定性控制优先 | 注册表发现确定性（声明序）；提取、词表校验、锚点消歧均无 LLM 介入；失败降级路径确定 | ✅ 通过 |
| VII 独立接口演进 | DB CHECK 宽模式（迁移 0074）/ MCP 图标注 schema relation_type **加法**放宽（旧值全兼容）/ 注册表内部接口各自演进，无破坏性变更（research R13） | ✅ 通过 |
| VIII 版本不混用 | 图边沿用 (knowledge_scope_id, index_version) 隔离；重建路径经注册表重放（宪法 VIII 可重建） | ✅ 通过 |
| IX 同步结果优先 | 无 Task/Resource 依赖；交叉引用提取在入库护栏内同步完成 | ✅ 通过 |
| X 评测驱动优化 | FR-028–FR-031/SC-001/SC-002：004 图集 37 条无回归 + 受益子集 ≥3% 闸口；未达阈值 legal 档案不声明词表（声明式不进默认路径，research R11/R12） | ✅ 通过 |
| XI 领域中立 | FR-007/FR-016：关系词表唯一来源为域档案 graph_relations；提取器不写死域名；**清除查询侧三处 SE 硬编码**（expansion.py 默认对、retrieval_pipeline.py VALID_DIRECTIONS、postgres_graph_store.py 反向 CASE，research R6） | ✅ 通过 |

**硬约束（Non-Negotiable）**：跨域串库 = 0（FR-023/FR-025，knowledge_scope_id 唯一隔离键，跨域相对链接不解析——scope 级 chunk 索引天然限域）、无显式引用拒绝检索（FR-024）、上传内容不作控制指令（V，registry 声明驱动）、Schema 合法率 100%（FR-026——**注**：MCP 图标注 schema 的 relation_type 枚举必须加法放宽为 pattern，否则法律域图增强响应携带 `references` 将无法通过校验、SC-004 自相矛盾；此为兼容演进而非契约破坏，research R13）、来源可定位率 100%（FR-027）——逐条承接，无豁免。

**结论**：无宪法违反项，无需 Complexity Tracking 豁免。一处需要显式说明的"契约修改"：图标注/图关系两份 schema 的 relation_type 由闭合枚举放宽为宽模式 pattern（加法兼容，既有值全部继续合法），这是 SC-004 可满足的先决条件，属宪法 VII 允许的兼容演进，已在 research R13 论证。

**Phase 1 设计后复检（post-design re-check）**：research R0–R15、data-model、两份契约与 quickstart 落定后复核——R6（expansion 默认不过滤，写侧词表保证合法性）强化 VI/XI 且经 SC-001 等价性闸口保护；R5（词表校验 fail-loud 整批拒绝→降级记 reason）符合 III；R13（两份 schema 加法放宽）符合 VII；R11（legal 内置档案）符合 XI；R12（双档评测 + 未达阈值声明式补救）符合 X。**复核结论：仍无违反项，gate 维持通过。**

## Project Structure

### Documentation (this feature)

```text
specs/010-graph-relation-registry/
├── plan.md              # 本文件
├── research.md          # Phase 0 输出（R0–R14 决策记录）
├── data-model.md        # Phase 1 输出（graph_edge 约束变更/legal 档案/边 dict 契约/迁移 0074）
├── quickstart.md        # Phase 1 输出（VS-01~VS-10 验证场景）
├── contracts/
│   ├── graph-extractor-registry.md      # 插件接口 + 注册表 + 降级语义 + 008 图钩子 supersession
│   └── cross-reference-extraction.md    # 交叉引用提取规则（中英文/锚定/对称/locator 编码/防误报）
└── tasks.md             # Phase 2 输出（/speckit-tasks，非本命令）
```

### Source Code (repository root)

```text
backend/
├── src/rag_mcp/
│   ├── graph/
│   │   ├── extractors/
│   │   │   ├── base.py             # 新增：GraphExtractor ABC（format/relation_pairs/chunk_scope 声明
│   │   │   │                       #   + extract(source, chunks, scope)）+ GraphExtractorRegistry
│   │   │   │                       #   （按 format 注册、按域词表交集发现、inverse map 聚合）
│   │   │   ├── cross_reference.py  # 新增：交叉引用提取器（format=markdown，
│   │   │   │                       #   references/referenced_by 成对硬边，混合锚定）
│   │   │   ├── java_call_graph.py  # 修改：实现插件接口（声明 java + calls/called_by 对），行为不变
│   │   │   └── ddl_fk.py           # 修改：实现插件接口（声明 ddl + fk 对），行为不变
│   │   ├── models.py               # 修改：relation_type CHECK 宽模式（45-49 drop/add）；
│   │   │                           #   validates 由闭合枚举改为 pattern + 禁 other_hard/inferred
│   │   ├── expansion.py            # 修改：删除 _BIDIRECTIONAL_PAIRS 硬编码默认；
│   │   │                           #   relation_types=None → 不过滤（写侧词表已保证域内合法）
│   │   │── capabilities.py         # 不变（graph_ready 门控语义保持，FR-020）
│   │   └── store/
│   │       ├── base.py             # 修改：GraphStore.write_edges 增必填 allowed_relation_types
│   │       └── postgres_graph_store.py  # 修改：词表校验（越界 raise→降级）、relation_types
│   │                                  │   SQL 参数化（ANY(:rts)）、反向 CTE CASE 由注册表
│   │                                  │   inverse map 生成、rebuild 经注册表发现
│   ├── parsers/
│   │   └── registry.py             # 修改：退役 FormatHandler.graph_extractor 字段与两个
│   │                               #   _*_graph_extractor 工厂（分派移交图层注册表）
│   ├── services/
│   │   ├── ingestion_service.py    # 修改：_extract_graph_relations 经 GraphExtractorRegistry
│   │   │                           #   发现（scope→domain_key→词表→交集）；降级语义不变（858-863）
│   │   └── domain_profile_service.py # 不变（resolve_planner_config / sync 复用）
│   ├── orchestration/
│   │   ├── retrieval_pipeline.py   # 修改：map_graph_params 的 VALID_DIRECTIONS 改为请求词表参数
│   │   │                           #   （BIDIRECTIONAL_DEFAULT 语义→空/全非法方向回退请求域词表全量；
│   │   │                           #   se-project 与 004 逐边等价，active 软关系参与面不变）
│   │   └── state_machine.py        # 修改：domain_planner_config.relation_vocab 穿线至
│   │                               #   retrieve_round → _recall_one → map_graph_params
│   ├── agents/query_planner.py     # 不变（009 已动态词表化）
│   └── config/
│       └── domain_profiles.py      # 修改：新增 legal 内置档案种子（references/referenced_by 词表）
├── alembic/versions/
│   └── 0074_widen_graph_edge_relation_type.py  # 新增：CHECK drop/add 宽模式 + other_hard 断言
├── tests/
│   ├── unit/
│   │   ├── test_graph_extractor_registry.py      # 新增：接口契约/发现交集/确定性/inverse map
│   │   ├── test_cross_reference_extractor.py     # 新增：链接/条文/锚定/对称/防误报规则集
│   │   ├── test_domain_profile_seed.py           # 扩展：legal 档案断言
│   │   └── test_migration_graph_edge.py          # 更新：宽模式断言 + other_hard 拒绝
│   ├── contract/
│   │   ├── _graph_schema_helper.py               # 更新：RelationType 宽模式
│   │   ├── test_graph_relations_schema.py        # 更新：枚举→pattern 断言
│   │   └── test_graph_extractor_registry_contract.py  # 新增：注册表契约（008 钩子 supersession）
│   └── integration/
│       ├── test_cross_reference_e2e.py           # 新增：legal 域入库→交叉引用边→图扩展→证据
│       ├── test_public_legal_graph_path.py       # 新增：public+legal 图路径端到端（US4）
│       └── test_us1_java_callgraph_recall.py 等  # 回归：004 图测试集（other_hard 引用更新）
└── （backend/ 树结束）

specs/003-structured-asset-expansion/contracts/    # 仓库根（契约集中地，003 起约定）
├── graph-relations.schema.json                   # 修改：RelationType 枚举→宽 pattern（加法，R13）
└── mcp-search-output.graph-annotation.schema.json # 修改：relation_type 枚举→宽 pattern（加法，SC-004 先决）

eval/                                              # 仓库根
├── corpora/legal/                                 # 新增：法律域语料（虚构法规 markdown，
│                                                  #   含内部链接/相对链接/中文条文引用）
├── cross_reference_eval_dataset.json              # 新增：受益子集 ≥6 条（含中文条文查询）
├── run_cross_reference_comparison.py              # 新增：法律域混合基线 vs 交叉引用图增强对照
├── run_graph_comparison.py                        # 复用：004 图集 37 条回归重跑
└── 010_graph_regression_report.json               # 新增产物：004 回归报告（不覆盖历史报告）
```

**Structure Decision**: 单仓库 `backend/`（Python FastAPI + MCP）+ `eval/`（评测运行器与语料）。图提取器注册表落位 `graph/extractors/base.py`（图层自有注册表，蓝图 §5-010），**supersede** 008 FormatHandlerRegistry 的 `graph_extractor` 单值钩子（结构性不足：无法表达多提取器与域轴，research R2）；FormatHandlerRegistry 仍是格式检测/解析/二进制三分发的单一事实源。迁移顺延至 0074（当前 head 0073，drop/add 沿用 0073 范式）。legal 内置档案经 007 既有 `sync_builtin_profiles` 启动同步种子化，无新迁移。前端零改动。

## Complexity Tracking

> 无宪法违反项，本表留空。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | | |
