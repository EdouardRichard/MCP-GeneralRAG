# Research: Knowledge Domain Generalization (007)

**Branch**: `007-knowledge-domain-generalization` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)

**Scope Basis**: 2.0 蓝图《通用RAG演进蓝图.md》§1.3-1（domain_scope 通用引用 + project_scope 零破坏）、§3.1（双轴模型）、§3.2（域档案注册表）、§3.6（MCP 契约兼容扩展）、§5-007（文件级变更清单）、§6（无回归义务）、§7（007 规模 60–75 任务）、ADR-1/ADR-2/ADR-3/ADR-7；1.0 蓝图 §4/§16；宪法 v1.3.0（原则 I/II/X/XI + 五硬约束跨域语义）。

> 本文件为 `/speckit-plan` Phase 0 产出。spec.md 澄清阶段已闭合全部 5 问（只读保护 / slug 唯一+不可变 / type:name 首期 / project_id 迁移删除 / list 全量返回，见 spec §Clarifications）。本文固化技术决策与"无对照"评测目标闸门。

---

## 0. 相对既有基线的评测目标（进入 plan 的闸门）

依据 spec §"对照评测声明（无检索质量对照——架构泛化）"、FR-023/FR-024 与 SC-009：本 Feature 的对照评测要求为 **无（架构泛化，非检索质量）**——不新增检索信号、不改变召回/融合/排序/图扩展/Agent 编排逻辑、不修改既有检索路径的默认行为（三处残留修复只拆除 public 断链/错标，见 §1.7），故不存在可对照的检索质量增量；评测义务仅为"行为不变确认 + 新功能验收 + 硬性指标保持"。

### 0.1 基线集（已记录于 eval 工件）

| 套件 | 数据集 / 报告 | 条目 | 判定口径 |
|------|--------------|------|----------|
| 001 Dense 基线 | `eval/eval_dataset.json` 前 11 条 / `baseline_report.json` | 11 | Recall 精确一致；MRR/nDCG 非延迟 1% 容差（单侧） |
| 002 混合基线 | 前 18 条 / `hybrid_comparison_report.json` | 18 | `--limit 18` 重跑，非延迟 1% 容差 |
| 003 格式集 | `format_expansion_report.json` / `regression_report.json` | — | 逐格式回归 |
| 004 图集 | `eval_dataset.json` 37 条 / `graph_enhanced_comparison_report.json` | 37 | 图增强对照 + 结构性受益子集闸口 |
| 005 agentic | `agentic_eval_dataset.json` / `agentic_comparison_report.json` | 44 | 三 Agent 对照（§1.6 闸口） |
| 006 冒烟 | `run_instance_form_smoke.py` / `instance_form_smoke_report.json` | 11 | 双形态冒烟（单侧非回归） |

### 0.2 期望变化（007 = 作用域引用模型 + 域配置架构的泛化）

| 指标 | 期望变化 | 判定口径 |
|------|----------|----------|
| **Recall@K / MRR / nDCG@K** | **0 变化**：检索热路径不改（三处修复仅作用于 public 域，见 §1.7） | 非延迟指标下降 >1% 判回归；高于基线记录为环境敏感漂移 |
| **P50 / P95** | 环境敏感、不设阈值；作用域解析新增 slug/type:name 分支仅在 `domain_scope` 路径生效，`project_scope` 路径零新增查询 | 记录对照并标注 env_sensitive |
| **模型成本** | **0 变化**：007 不新增任何 LLM 调用 | 与基线同为 0 |
| **逐字节兼容** | 仅 `project_scope` 请求的响应（错误码/message/candidates/输出结构）与 1.0 逐字节一致 | 兼容测试集逐字节比对（SC-001） |

### 0.3 通过判定（三项全过，FR-024/SC-009）

1. **既有全集无回归**：001/002 基线（11/18 条）、003 格式集、004 图集（37 条）、005 agentic（44 条）、006 冒烟（11 条）按各自既有口径重跑，非延迟指标在 1% 相对容差内一致（单侧非回归下界，沿用 006 SC-009 范式）。
2. **既有 pytest 验收套件全绿**：001–006 既有 pytest（1509 passed / 1 skipped 基线）全部通过。
3. **硬性指标保持**：跨知识域串库 = 0、MCP Schema 合法率 = 100%、来源可定位率 = 100%（混合域验收集，宪法硬约束跨域语义版，SC-003~SC-005）。

### 0.4 明确不作的事

不设置任何质量提升阈值、不执行质量对照评测、不作质量提升声明（FR-023）；domain_scope 正名/双参数收敛为单一参数属蓝图 §9 MAJOR 触发条件；008/009/010 的四层档案消费接线不在本期（FR-006）。

---

## 1. 技术决策

### 1.1 双参数并集解析的边界（空串 / 重复 / 混合新旧引用）— 澄清 Q2/Q3 固化

- **Decision**: 在 `RetrievalService` 内以 `resolve_project_refs`（`retrieval_service.py:432-529`，现已支持数字 project_id / alias / repo_path / 数字 public scope ID）为底座，改造为统一解析器 `resolve_knowledge_scopes(project_scope, domain_scope)`：`project_scope` 沿用既有解析语义（零改动），`domain_scope` 走新解析链（数字 knowledge_scope_id 任意 scope_type → slug 全局按名 → type:name 限定引用），两路结果按 `scope_id` 并集去重后作为完整知识域集合。解析顺序见 spec FR-008。
  - **空串 / 纯空白条目**：两参数内均 MUST 跳过（沿用 1.0 既有语义）；跳过导致全部引用不可解析时按缺失作用域拒绝，绝不放宽为无约束/全库。
  - **重复引用**：同一 scope 被双参数重复引用（如 domain_scope 数字 ID 与 project_scope 数字 ID 指向同一域）或条目字面重复 → 去重后只参与一次，不放大结果集（FR-007/SC-002）。
  - **混合新旧引用**：`project_scope` 仅接受既有形态（project_id/alias/repo_path/数字 public scope ID），`domain_scope` 仅接受数字 scope ID/slug/type:name；slug 与 alias/repo_path 属不同命名空间、互不交叉匹配（FR-012）；数字 knowledge_scope_id 为双参数共有形态（同域经两参数引用时去重）。
  - **至少一个非空**：由服务入口层显式校验两参数并集非空补位（schema anyOf 只表达契约、入口层是执行护栏，见 §1.3）；均空/缺失 MUST 拒绝，不回退默认/全库。
  - **错误码双轨**：仅 project_scope 形态（domain_scope 缺失或空）→ 沿用旧码；涉及 domain_scope（非空）→ 发新码（FR-010）；混合请求中 project_scope 条目歧义但 domain_scope 非空时按"请求形态"发新码（spec Edge Case 固化）。
- **Rationale**: ADR-1 兼容扩展而非破坏性改名——旧解析路径与错误码逐字节保留；slug/type:name 只为 domain_scope 引入新寻址面，命名空间隔离消除与 alias/repo_path 的优先级裁决问题（Q2 决议）。
- **Alternatives considered**: ① 单一 `domain_scope` 正名替换 `project_scope`——破坏全部既有客户端与评测集，违反 ADR-1，否决（留 MAJOR）；② slug 与 alias 共用同一匹配空间——引入优先级仲裁与旧客户端行为漂移，违反命名空间隔离决议，否决。

### 1.2 slug 唯一性约束实现 — 澄清 Q2 固化

- **Decision**: `knowledge_scopes.slug` 列：`String` 非空、**全局唯一约束**（跨 project/public 单一命名空间，DB UNIQUE 约束仲裁冲突）；创建时分配（管理面显式指定或按名称 slugify 生成，冲突时追加数字后缀），存量迁移回填为全部既有域生成唯一 slug（slugify(name) + 冲突后缀）。**创建后不可变更**：服务/API 层拒绝任何 slug 更新请求（不提供更新端点 + 服务层守卫）；DB 只保证唯一性、不保证不可变（不可变是应用层约束）。slug 仅在 `domain_scope` 参数内解析，`project_scope` 专属 alias/repo_path/project_id 与其命名空间隔离（FR-012/SC-011）。
  - slug 词法：`^[a-z0-9][a-z0-9-]*$`（生成规则），与契约 `ScopeSlug` pattern 对齐；长度受 `String(255)` 约束。
- **Rationale**: 全局唯一约束是"按名无歧义寻址"的 DB 级保证（SC-011 重复 slug 拒绝率 100%）；不可变保证 `domain_scope` 引用可重放（FR-012）；命名空间隔离复用 1.0 既有寻址形态零迁移。
- **Alternatives considered**: ① 按 scope_type 分段唯一（project 与 public 各一命名空间）——type:name 已承担"类型+名"限定语义，slug 保持全局唯一以简化解析（数字→slug 一步命中），否决；② slug 可变——破坏引用重放，违反 Q2 决议，否决；③ 无 slug 仅 type:name——public 域无 Project 行，无法沿用 alias/repo_path，slug 是 public 域首个非数字按名寻址形态，必须交付（FR-013）。

### 1.3 anyOf 放宽 + 入口层显式校验补位（FastMCP 签名即 schema）

- **Decision**: FastMCP 以签名派生 inputSchema（`mcp/search_knowledge.py` / `get_evidence.py` 的 `project_scope: list[str]` 现为必填）。007 将两工具签名改为 `project_scope: list[str] | None = None` 与 `domain_scope: list[str] | None = None`（均可选），**入口层**（`search_knowledge_core` / `get_evidence` 工具入口）显式校验两参数并集非空——为空则按双轨错误码拒绝（MISSING_PROJECT_SCOPE / MISSING_KNOWLEDGE_SCOPE）。契约 schema（`mcp-search-input.schema.json` / `mcp-get-evidence.schema.json`）以 `anyOf: [{required:["project_scope"]},{required:["domain_scope"]}]` 表达"至少一个"（放宽 `required: ["project_scope"]`），`required` 只保留 `query`/`evidence_id`。
- **Rationale**: 蓝图 §8 风险明言"schema anyOf 弱化至少一个 scope 约束 → 入口层显式校验补位，沿用 1.0 服务端固定护栏原则"；FastMCP 签名无法原生表达 anyOf，故以"签名可选 + 入口校验 + 契约 anyOf 文档化"三层一致达成语义；旧客户端仅传 project_scope 的行为逐字节不变（入口校验分支对旧形态零影响）。
- **Alternatives considered**: ① 手工覆盖 FastMCP 生成的 inputSchema 注入 anyOf——与 FastMCP"签名即 schema"机制割裂、维护成本高，且无运行时收益（入口校验已覆盖），否决；② 保持 project_scope 必填 + domain_scope 可选——无法表达"仅 domain_scope"形态（新客户端只传 domain_scope 会被 FastMCP 拒绝），违反 FR-007，否决。

### 1.4 graph_edge / soft_relation 存量 project_id 列处置 — 澄清 Q4 固化

- **Decision**: **迁移删除列**（非"保留列停止写入"）：`graph_edge.project_id` 与 `soft_relation.project_id` 随 alembic 迁移删除；`knowledge_scope_id` 成为唯一图隔离键。同步重建含 project_id 的复合索引——`idx_graph_edge_source` / `idx_graph_edge_target` / `idx_soft_relation_active` 移除 project_id 键位；`uniq_graph_edge`（本就以 scope_id 为键）与 `idx_soft_relation_pair` 不变。图抽取/写入路径（graph 模块）停止写 project_id。`_graph_scope_triple`（`retrieval_service.py:1090-1122`）去除"须存在 Project 行"门槛，改为按 scope_id + graph_ready 版本直接裁决；project_id 可经 `scope_id → Project.knowledge_scope_id` 联查派生，图数据可重建（宪法 VIII），无检索信息损失（FR-018）。
- **Rationale**: project_id 相对 knowledge_scope_id 是 1:1 冗余（Project.knowledge_scope_id UNIQUE FK）；public 域无 Project 行，NOT NULL project_id 使 public 域永远无法落图（缺陷 site 3 根因）；"保留列停止写入"会留下需 NULL 化的历史列与两套索引语义，不如迁移删除干净（Q4 决议）。
- **Alternatives considered**: ① 保留列 + 停止写入（置 0/NULL）——历史列语义残留、索引含冗余键、未来仍需二次迁移，否决；② 保留列 + 继续写入 project 域——无法覆盖 public 域，缺陷不闭环，否决；③ 软删除列（改名 legacy）——同等复杂度但留下死列，否决。

### 1.5 域档案注册表：建表、种子与启动同步

- **Decision**: 新表 `domain_profiles`（字段见 [data-model.md](./data-model.md) §2）。迁移内**种子化两内置行**：`se-project`（supported_formats = 8 种 1.0 原生格式 markdown/java/openapi/ddl/go/python/word/pdf；graph_relations = calls/called_by/fk_references/fk_referenced_by 及方向；prompt_overrides = 现 SE planner 提示词内容（`agents/query_planner.py` 既有提示词逐句冻结）；default_capabilities = 1.0 既有默认能力）、`generic`（supported_formats = 转换层格式（008 前瞻声明）+ markdown/word/pdf；graph_relations 空；prompt_overrides 域中立提示词；通用默认能力）。`is_builtin=true`。应用启动时执行**进程内注册表同步**：读取 DB 行与内置/自定义注册表比对，修复漂移（内置行字段偏离则回写种子），同步失败 MUST 显式失败启动（不静默降级为硬编码，FR-005/SC-008）。
- **Rationale**: 蓝图 §3.2"一处声明、四层消费"；007 只建表 + 种子 + 同步 + list 能力摘要消费，四个消费点（格式/切片/图/编排）接线属 008/009/010（FR-006 明确 007 不改变这四层行为）。se-project 档案 = 1.0 行为，generic 档案 = 前瞻声明。
- **Alternatives considered**: ① 运行时按需插入种子（无迁移）——首次启动竞态 + 种子版本不可审计，否决；② 进程内硬编码常量不入库——违反 ADR-3"唯一配置中枢"，否决。

### 1.6 005 agentic 数据集回归闸口 + 三处残留修复的行为边界

- **Decision**: 005 回归闸口 = 重跑 `python eval/run_agentic_comparison.py`（`agentic_eval_dataset.json` 44 条），断言非延迟指标 1% 容差单侧非回归 + 硬性指标全过（沿用 005 既有口径）。三处修复的**行为边界**（只影响 public 域、project 域字节不变）：
  - **修复 1（get_evidence public 断链）**：`evidence_service._resolve_scope_ids`（`evidence_service.py:328-372`）改为复用统一解析器——数字 public scope ID 直达 public 域，不再仅经 Project 表；`get_evidence` 入口同样接受 `domain_scope`（含 slug/type:name）。
  - **修复 2（agentic scope_type 硬编码）**：`retrieval_pipeline.py:451,468` 的 `"knowledge_scope_type": "project"` 改为按 scope 实际类型（经 scope_type 映射查询），主条目与父级条目同步修正；project 域证据值仍为 "project"（005 数据集全 SE/project 域 → 逐字节不变）。
  - **修复 3（图三元组去 Project 依赖）**：见 §1.4，`_graph_scope_triple` 去除 Project 行门槛，public graph_ready 域获得图检索资格。
- **Rationale**: 005 数据集全为 SE/project 域，修复 2 对 project 域输出零改动 → 005 44 条逐字节回归是"修复不污染既有路径"的最强闸口；修复 1/3 只开启此前损坏的 public 路径，以新增功能验收覆盖（SC-007）。
- **Alternatives considered**: ① 仅以 pytest 验收代理替 005 评测重跑——偏离蓝图 §6"按所属 Feature 既有口径重跑"，否决；② 将 agentic scope_type 改为统一从 scope 表联查（增加一次查询）——通过既有 `version_scope_map`/新建 `scope_type_map` 一次性预取避免热路径加查，采用预取方案（见 tasks）。

### 1.7 list_knowledge_domains 只读工具与能力摘要来源

- **Decision**: 新增只读 MCP 工具 `list_knowledge_domains`（无输入参数，首期全量返回活跃域、无过滤/分页，Q5 决议）。每个条目 = {ID、slug、name、scope_type、domain_key、capabilities}，其中 `capabilities` = {supported_formats, has_graph} 由 `domain_profiles` 声明派生（has_graph = graph_relations 非空）；MUST NOT 返回任何知识内容（chunk/证据/摘录/来源片段均为禁止输出，FR-014/FR-022/SC-006）。仅活跃域返回；archived/deleting 域不出现；空实例返回空列表 + 成功状态。
- **Rationale**: "发现域 ≠ 检索知识"，不构成宪法 I 禁止的隐式全库检索；能力摘要来自域档案声明而非知识内容，天然满足 SC-006 知识内容 = 0。
- **Alternatives considered**: ① 首期带 domain_key 过滤参数——Q5 决议为首期全量、偏好参数后置为未来兼容扩展（只增不改），否决；② 返回域档案全量字段——泄露过多配置细节且无调用方需求，收敛为能力摘要，否决。

### 1.8 domain_key 回填与新建默认

- **Decision**: 迁移为全部存量 `knowledge_scopes`（project 与 public）赋 `domain_key='se-project'`（NOT NULL 缺省 se-project）；新建知识域未声明 domain_key 时默认 se-project（与存量口径一致，FR-002）；管理面创建时可显式选择任意档案。
- **Rationale**: 保证 1.0 行为逐项一致（存量 public 域亦赋 se-project，见 spec Assumptions）；语义轴缺省与结构轴正交。
- **Alternatives considered**: ① 存量 public 域默认 generic——public 域在 1.0 即按 SE 语义解析（沿用原生解析器），改 generic 会改变行为，否决。

### 1.9 错误码双轨与 candidates 增量扩展

- **Decision**: 错误码枚举**只增不删**——新增 `MISSING_KNOWLEDGE_SCOPE` / `AMBIGUOUS_DOMAIN_REF`，旧码 `MISSING_PROJECT_SCOPE` / `AMBIGUOUS_PROJECT_REF` / `INVALID_PROJECT_REF` 等全保留。`AMBIGUOUS_DOMAIN_REF` 的 `candidates` 元素 = 旧候选字段（name 等）+ 增量可选 `scope_type`/`domain_key`/`slug`；旧码响应的 candidates 字节级保持 1.0 形态（`project_id`/`name`/`alias`/`repo_path`，FR-010/SC-010）。
- **Rationale**: 契约 schema 错误码枚举收录新旧全集且只增不删（ADR-1 兼容扩展）；candidates 增量字段为调用方提供 slug/type:name 消除歧义所需信息。
- **Alternatives considered**: ① 复用旧码表达 domain_scope 歧义——无法区分"涉及 domain_scope"的形态，违反双轨决议，否决。

### 1.10 管理面与前端泛化（REST + Web）

- **Decision**: 复用既有 REST 管理 API（`api/` 路由 + `schemas/project.py` Pydantic 模式）+ Web 前端：新增域档案 CRUD（内置只读保护：is_builtin 行拒绝 update/delete，含字段级）、知识域创建时的 domain_key 声明与 slug 分配/展示、前端知识域列表/详情呈现 scope_type/domain_key/slug 维度；不引入新检索入口（FR-026）。
- **Rationale**: 蓝图 §5-007（`project_service.py` / `api/projects.py` / `schemas/project.py` 域档案与 slug 管理）；管理面是域档案唯一写入口，内置只读保护在服务层 + API 层双重生效（Q1 决议）。
- **Alternatives considered**: ① 仅 DB 层保护内置行——绕过 API 的写入路径不可防御，否决（服务层 MUST 校验 is_builtin）。

---

## 2. 遗留与风险

| 风险 | 缓解 | 归属 |
|------|------|------|
| schema anyOf 弱化"至少一个 scope" | 入口层显式校验并集非空补位（§1.3）；双轨错误码 | 007（本节固化） |
| 双参数长期并存心智负担 | 契约文档明确"project_scope 为兼容形式、新集成一律用 domain_scope"；收敛留待 MAJOR | 蓝图 §8/§9 |
| slug 生成规则与回填细节 | 词法 + slugify 规则已在 §1.2 固化；具体 slugify 实现与冲突后缀策略由 tasks.md 实现 | plan 已定口径 |
| 图列删除后 project_id 派生一致性 | 联查派生 + 004 图集回归 + 图数据可重建（宪法 VIII） | 007 |
| 存量图数据迁移（project_id 删除） | 迁移删除列 + 索引重建，004 图集 37 条回归证明无数据损失（FR-018/SC-007） | 007 |

> 无 Constitution 违规豁免；无 `[NEEDS CLARIFICATION]` 残留（spec 澄清阶段已闭合 5 问）。
