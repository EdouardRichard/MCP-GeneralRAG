# 通用 RAG 系统演进蓝图（2.0）

**状态**：已批准（六项关键决策 + 转换层策略已由系统负责人确认）
**日期**：2026-09-05
**目标读者**：产品规划者、系统架构师、检索工程师、Agent 工程师、后续 specKit Feature 负责人
**上游文档**：`蓝图.md`（1.0 系统设计蓝图，继续有效；本文档是其 2.0 演进增量，未覆盖处一律以 1.0 蓝图为准）

---

## 1. 系统定位与演进目标

### 1.1 定位重述

本系统是面向单用户、多知识域工作场景的**检索增强服务**。它通过 MCP 向 ChatGPT App、DeepSeek Harness、Claude Code 等外部 Agent 提供与当前知识域贴合、来源可定位的检索证据。系统不生成最终产物，不对产出物执行质量门禁——这一 1.0 定位（`蓝图.md` §1）在 2.0 不变。

### 1.2 2.0 核心主张：检索质量自研，解析广度外包

1.0 系统围绕软件工程领域构建，其格式解析器（tree-sitter 符号切片、OpenAPI/DDL 结构切片等）是为"检索增强编码 Agent"深度定制的。演进为通用 RAG 系统时，我们拒绝沿此路径为每种通用格式手写解析器，而是确立分工：

- **解析广度是商品能力**：Office 文档、网页、表格、邮件等通用格式的"转 Markdown"由成熟的第三方转换器承担（主选微软 [markitdown](https://github.com/microsoft/markitdown)，Apache-2.0，覆盖 DOCX/XLSX/PPTX/PDF/HTML/CSV/JSON/XML/EPUB/Outlook 消息等），转换后的 Markdown IR 复用已交付并验证的 `MarkdownParser`（heading/paragraph/list/table 通用 chunk_type）完成结构切片。
- **检索增强效果是核心竞争力**：系统自有工程投入集中于——混合检索（dense/sparse/RRF/rerank）、图扩展、Agentic 编排、scope 隔离、证据可定位、能力门控、评测驱动优化。这些是 001–006 已建立且领域中立的能力，2.0 的全部演进不得稀释它们。
- **已交付的原生解析器冻结不动**：markdown/java/openapi/ddl/go/python/word/pdf 八种解析器已通过 1509 项测试与逐格式评测验收，属于已回收的沉没投资，不做向转换层的迁移；仅当未来对照评测证明转换层达到或超过原生质量时，才评估替换（宪法 X，评测驱动）。
- **新格式默认走转换层**：任何新增通用格式首先尝试"转换器 + 注册表条目"路径；仅当转换产物无法满足结构切片或检索质量要求（评测证明）时，才立项原生解析器。

### 1.3 演进目标（可度量）

1. 外部 Agent 可通过 MCP 以通用知识域引用（`domain_scope`）对一个或多个任意知识域执行检索增强，旧 `project_scope` 客户端零破坏。
2. 新增一种通用文档格式的边际成本 ≤ 2 个文件（注册表条目 + 可选小适配器），不再出现"4 处 if/elif + 3 个 DB CHECK 约束 + 1 次迁移"的格式税。
3. 首批通用格式（HTML/TXT/CSV/JSON/YAML/XML/XLSX/PPTX/EML）全部可上传、可切片、可检索、证据可定位。
4. 两个验证域（个人/团队通用知识库、法律合规）各自建立 ≥10 条固定评测集并产出域基线报告；1.0 全部既有评测集（37 + 44 条）无回归。
5. 硬性验收指标在混合域验收集上全部成立：跨域串库 = 0、MCP Schema 合法率 = 100%、来源可定位率 = 100%（1.0 §24.2 原样继承，"项目"语义扩展为"知识域"）。

---

## 2. 现状审计：1.0 领域耦合全景

### 2.1 交付基线

001–006 六个 Feature 全部交付收敛（六个 tasks.md 零未勾选；101 提交，2026-08-26 → 09-04；pytest 1509 passed / 1 skipped）。Dense/混合/图增强/Agentic 四条检索路径均已通过对照评测闸口进入或可用于默认路径。

### 2.2 领域耦合点位（九处，均经第一手代码验证）

| # | 点位 | 证据 | 通用化归属 |
|---|------|------|-----------|
| 1 | 格式分发 4 处 if/elif（无注册表） | `api/knowledge_sources.py:305-351`（_detect_format）、`services/ingestion_service.py:582-631`（_parse_content）、`parsers/text_extractor.py:16,23-29`（BINARY_FORMATS）、`ingestion_service.py:833-842`（图提取器分发） | 008 |
| 2 | 4 个 DB CHECK 枚举（format 8 值 ×2、chunk_type 18 值、relation_type 5 值） | `models/knowledge_source.py:40-44`、`models/chunk.py:26-30`、`models/retrieval_run.py:46-51`（注意 format 列为 String(8)）、`graph/models.py:45-49` | 008 / 010 |
| 3 | chunk_type 18 值中 14 个 SE 专属；`table` 在 Word 表格与 DDL 表间撞名 | `models/chunk.py:26-30`、`word_parser.py:132` vs `ddl_parser.py:285-305` | 008 |
| 4 | project 残留 3 处：get_evidence 无法展开 public 证据（断链）、agentic 证据硬编码 scope_type、图三元组强制 Project 行 | `services/evidence_service.py:328-372`、`orchestration/retrieval_pipeline.py:451,468`、`services/retrieval_service.py:1114-1122` | 007 |
| 5 | MCP 契约 SE 语义：task_context 的 current_file/current_symbol/work_phase（SDLC 枚举）且下游未消费；SourcePosition 以 Java 符号路径为示例；错误码/candidates 钉死"项目" | `specs/001-.../contracts/mcp-search-input.schema.json:24-48`、`contracts/common.schema.json:34-37`、`retrieval_service.py:151` | 007 / 009 |
| 6 | query_planner 提示词通篇 SE 举例；relation_directions 词表硬编码 4 值 | `agents/query_planner.py:72-111`（提示词）、`:44-48`（NODE_SCHEMA enum）、`:25-26`（常量） | 009 |
| 7 | 宪法 I/II/X 以 project-knowledge 为主语；交付工作流第 2 条写死"Markdown 与 Java 摄入" | `.specify/memory/constitution.md:32-39,41-47,93-98,150-152` | 007 |
| 8 | 评测集全 SE：37 条（符号/章节查询）+ agentic 44 条；生成器按 chunk_type 二分 | `eval/eval_dataset.json`、`eval/generate_dataset.py:89-96` | 011 |
| 9 | 前端 accept 硬编码 11 扩展名；types 联合类型停留在两格式时代 | `frontend/src/pages/ProjectDetailPage.tsx:273,287`、`frontend/src/types/index.ts:16` | 008 |

### 2.3 已领域中立的资产（演进地基，禁止稀释）

- **检索内核**：dense/sparse 召回、RRF 融合、Cross-Encoder rerank、per-source 守卫、四态 completion_status、Qdrant payload + PG 版本双侧 scope 强制隔离（串库实测 0）。
- **knowledge_scope 模型骨架**：scope_type 二元 + 全下游实体强制 scope_id FK；public 已达"可创建/可上传/可检索"（差 §2.2#4 三处残留）。
- **能力门控**：knowledge_versions.capabilities JSONB（新 flag 零 DDL）+ graph_ready 蕴含校验。
- **编排与治理**：版本原子发布、派生索引可重建、凭据脱敏（IT 凭据级，通用）、注入检测、writer/reader 单写多读、Provider 配置、运行指标。
- **文档三解析器**：Markdown/Word/PDF 本身领域中立（PDF 标题启发式仅认数字编号，见 §9 触发条件）。

---

## 3. 目标架构

### 3.1 知识域双轴模型

knowledge_scope 保留为唯一隔离单元（宪法 I 不变），其类型拆为两个正交维度：

- **结构轴 `scope_type`（沿用，闭合）**：`project` | `public`。这是承载代码语义的维度——public scope 无 Project 行、不参与 repo_path/alias 寻址；project scope 反之。存量代码与数据零迁移。
- **语义轴 `domain_key`（新增，开放）**：FK → `domain_profiles.domain_key`。声明该知识域的领域属性（如 `se-project`、`generic`、`legal`、`personal`、`finance`），决定：可接受的格式集、chunk_type 扩展词表、图关系词表、planner 提示词覆盖、默认能力声明。

**内置域档案**：`se-project`（默认档案：8 原生格式 + calls/fk 图关系 + 现 SE planner 提示词，行为与 1.0 完全一致）、`generic`（通用文档档案：转换层格式集 + doc 三原生格式、无图关系、域中立提示词）。`legal`/`personal` 等域档案由 011 评测语料建设时落地。project/public 结构轴 × 语义轴自由组合（如"法律公共域"= public + legal）。

### 3.2 域档案注册表（DomainProfile）

新表 `domain_profiles`：`domain_key`（PK）、`name`、`description`、`supported_formats`（JSONB 数组）、`chunk_type_extensions`（JSONB：命名空间扩展词表）、`graph_relations`（JSONB：该域可用的 relation_type 词表及方向）、`prompt_overrides`（JSONB：planner 提示词注入片段——关系词表、检索示例）、`default_capabilities`（JSONB）、`is_builtin`（bool）。应用启动时与进程内注册表同步；管理面提供 CRUD（自定义域档案）与内置档案的只读保护。

域档案是"一处声明、四层消费"的配置中枢：摄入层（格式接受性校验）→ 切片层（chunk_type 扩展校验）→ 图层（关系词表）→ 编排层（planner 提示词）。四个消费点全部走注册表，不再各自硬编码。

### 3.3 两层摄入架构与 FormatHandler 注册表

```
上传 → FormatHandler 注册表（唯一分发点）
  ├─ 原生结构解析层（冻结，8 种）：markdown/java/openapi/ddl/go/python/word/pdf
  │     └─ 结构感知切片（symbol/endpoint/table… SE chunk_type）
  └─ 转换层（新增）：可插拔转换器，主选 markitdown 适配器
        └─ 任意通用格式 → Markdown IR → 凭据脱敏 → MarkdownParser 切片
              （通用 chunk_type：heading/paragraph/list/table/section）
首批转换层格式：html / txt* / csv / json / yaml / xml / xlsx / pptx / eml
（*txt 为极轻量原生处理器：空行分段，chunk_type=paragraph）
```

注册表条目声明：`format` 名、扩展名集、tier（native | converter）、binary/text、解析器工厂或转换器规格、可选图提取器挂钩、定位前缀。四处 if/elif 分发点全部收敛到注册表；错误消息从注册表生成，消除手抄漂移。凭据脱敏顺序保持"转文本之后、切片之前"，对两层一致（宪法 V 不变）。

转换层证据定位语义：position 为"转换后表示的标题路径"（如 `# Sheet1`、`# Inbox > Re: 合同评审`），粒度与现行 Word 一致，满足宪法 IV 的人可定位要求；不做原文档锚点还原（docx 段 ID、PDF 坐标）——列入 §9 触发条件。

### 3.4 chunk_type 两级词表

- **L1 通用闭合集**（DB 宽模式约束 + 注册表校验）：`section / heading / paragraph / list / table`（存量通用 4 值 + 沿用）。
- **L2 命名空间扩展**：`^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$` 形态（如 `legal:article`），由域档案的 chunk_type_extensions 声明，应用层按 scope 的域档案校验。
- **存量 18 值作为合法遗留值原样保留**（不做数据迁移）；SE 专属类型在 se-project 档案下继续使用；`table` 撞名通过"格式 + 域档案"上下文消歧并在文档中显式记录。

### 3.5 证据定位前缀规范

`source_position`（自由字符串契约不变）内部约定统一前缀，008 落地并在 009 写入契约描述：

| 前缀/形态 | 适用 | 状态 |
|---|---|---|
| `# A > ## B` 标题路径 | markdown/word/转换层格式 | 存量 + 新增沿用 |
| `page:N [§ 编号路径]` | pdf（含合成行号 page*1000） | 存量沿用 |
| `com.foo.Bar#method` 符号路径 | java/go/python | 存量沿用 |
| `sheet:SheetName` | xlsx/csv（转换层） | 新增 |
| `path:/json/key` | json/yaml/xml（转换层） | 新增 |
| `msg:Subject` | eml/msg（转换层） | 新增 |

### 3.6 MCP 契约兼容扩展

- **`search_knowledge` / `get_evidence` 新增可选参数 `domain_scope: string[]`**：与 `project_scope` 取并集去重后进入统一解析器；二者至少一个非空（schema 以 anyOf 表达，放宽 `required: ["project_scope"]`）。`domain_scope` 条目解析顺序：数字 knowledge_scope_id（任意类型）→ scope slug（新增全局唯一按名寻址，覆盖 public/任意域）→ `type:name` 限定引用（如 `public:法规库`）。旧客户端仅传 project_scope 的行为逐字节不变。
- **错误码策略**：仅传 project_scope 时沿用旧码（MISSING_PROJECT_SCOPE / AMBIGUOUS_PROJECT_REF）；涉及 domain_scope 时发新码（MISSING_KNOWLEDGE_SCOPE / AMBIGUOUS_DOMAIN_REF）；schema 枚举收录全集；candidates 结构增量添加 scope_type/domain_key/slug 字段。
- **新增只读工具 `list_knowledge_domains`**：返回活跃 scope 的 ID/slug/名称/scope_type/domain_key/能力摘要（支持格式、是否有图）。它只暴露域元数据、绝不返回知识内容，因此不构成宪法 I 禁止的隐式全库检索——发现域 ≠ 检索知识。
- **输出契约零改动**：evidence 的 knowledge_scope_id/knowledge_scope_type 本就域中立。
- **task_context 泛化（009）**：current_file/current_symbol/work_phase 保留为编码域约定字段（兼容存量客户端），新增可选自由字符串 `activity`（任意域描述当前工作）；schema 描述整体域中立化。

### 3.7 检索编排域中立化

- query_planner 基础系统提示词重写为域中立（信号选择规则以"标识符/定义/关系"抽象表述），SE 举例与关系词表全部移入 se-project 档案的 prompt_overrides；运行时按请求 scope 的域档案注入。se-project 档案下的规划行为与 1.0 一致（用 005 数据集回归验证）。
- `relation_directions` 枚举改为动态：由请求 scope 域档案的 graph_relations 词表生成；无图档案返回空词表（图信号不可规划）。
- evidence_analyst / context_orchestrator / injection_detector 已中立，仅回归验证。
- gaps 与错误文案去"project"措辞（`retrieval_service.py:947-949` 等）。

### 3.8 图关系注册表与提取器插件

- **GraphExtractor 插件接口**：`extract(source, chunks, scope) -> list[edge]` 正式抽象（现 duck-typing 契约收编），注册表按 format + domain_key 发现提取器；java_call_graph 与 ddl_fk 迁移至接口（行为不变，004 数据集回归）。
- **relation_type CHECK 放宽**：`graph/models.py:45-49` 枚举约束改为宽模式 + 应用层按域档案词表校验；`other_hard` 逃生口退役。
- **非 SE 验证提取器（010 交付）**：文档交叉引用提取器——Markdown 内部链接 `[x](#anchor)` / 相对链接、法规条文的"依据第 X 条 / 参见 X.Y"引用 → `references / referenced_by` 硬边；在法律域语料上以 004 同款"结构性受益 ≥3%"闸口验证抽象成立。
- 图三元组的 Project 依赖由 007 拆除（project_id 从隔离键中移除，以 knowledge_scope_id 为唯一图隔离键）；010 验证 public/generic 域图路径端到端可用。
- graph_ready 门控语义不变：硬边 > 0 方可声明（`ingestion_service.py:451-457`），无图档案的域自然不可声明。

---

## 4. 关键设计决策记录（ADR）

| # | 决策 | 理由与代价 |
|---|------|-----------|
| ADR-1 | **兼容扩展而非破坏性改名**：新增 domain_scope 可选参数，project_scope 保留 | 输出契约本已域中立；FastMCP 签名改名会破坏全部既有客户端与评测集；schema anyOf 弱化与双参数心智负担是可接受代价。破坏性正名留待未来 MAJOR 大版本 |
| ADR-2 | **双轴知识域模型**（scope_type 结构轴 × domain_key 语义轴） | scope_type 的 project/public 区分在代码中是承重的（寻址、图三元组、Project 行）；新增正交语义轴避免存量迁移，语义与结构解耦 |
| ADR-3 | **域档案注册表**为格式/词表/提示词/图关系的唯一配置中枢 | 消除四层各自硬编码；"新增域"从改代码降为建档案 |
| ADR-4 | **转换层优先（markitdown）**；原生 8 解析器冻结；新格式默认转换层 | 解析广度是商品能力；聚焦检索增强质量。代价：转换格式的定位粒度限于标题路径；转换器成为新依赖（Apache-2.0，pip 可装） |
| ADR-5 | **FormatHandler 注册表**收敛 4 处 if/elif | 每格式边际成本 ≤2 文件；错误消息单一事实源 |
| ADR-6 | **两级 chunk_type 词表 + 存量 18 值遗留保留（不迁移）** | 避免 Qdrant payload 与 PG 存量数据重写；`table` 撞名以格式+域档案消歧并文档化 |
| ADR-7 | **宪法 MINOR 修订 v1.2.0 → v1.3.0**：I/II/X 域中立化 + 新增原则 XI（领域中立） | 语义扩展而非原则删除/重定义 → MINOR；修订必须随 007 显式走 /speckit-constitution 流程并附 Sync Impact Report |
| ADR-8 | **图提取器插件化 + 交付一个非 SE 提取器作抽象验证** | 仅抽象不验证=未证明的接口；文档交叉引用提取器直击法律验证域，沿用 004 结构性受益闸口证明收益 |

---

## 5. 数据与契约变更清单（文件级，供 plan 阶段细化）

**007 知识域泛化**：新表 `domain_profiles` + `knowledge_scopes.domain_key` 列（迁移）；`project_service.py` / `api/projects.py` / `schemas/project.py` 域档案与 slug 管理；`mcp/search_knowledge.py` / `get_evidence.py` 签名扩展；`retrieval_service.py` resolve 双参数并集 + slug/type:name 寻址；`evidence_service.py:328-372` public 断链修复；`retrieval_pipeline.py:451,468` scope_type 硬编码修复；`retrieval_service.py:1114-1122` 图三元组去 Project 依赖；新 `mcp/list_knowledge_domains.py`；contracts 新增/扩展 schema（domain-scope.input、list-domains.output、错误码枚举扩展）；宪法 v1.3.0；前端 scope 展示泛化。

**008 通用摄入通道**：新 `parsers/registry.py`（FormatHandler 注册表）+ `parsers/converter.py`（markitdown 适配器）+ `parsers/txt_parser.py`（轻量原生）；`api/knowledge_sources.py` _detect_format → 注册表委托；`ingestion_service.py:582-631,833-842` → 注册表委托；`text_extractor.py` 并入注册表 binary 声明；`models/knowledge_source.py` / `chunk.py` / `retrieval_run.py`（String(8)→String(32)）CHECK 放宽 + 迁移；`pyproject.toml` 增 markitdown 依赖；前端 accept/文案/types 更新。

**009 检索编排域中立化**：`agents/query_planner.py` 提示词重写 + 动态 relation_directions；`mcp-search-input.schema.json` task_context 描述 + activity 字段；`common.schema.json` SourcePosition 前缀规范表；`retrieval_service.py` gaps/错误文案；`config/` planner 档案注入接线。

**010 图关系注册表**：新 `graph/extractors/base.py`（插件接口）+ `graph/extractors/cross_reference.py`；java_call_graph/ddl_fk 迁移接口；`graph/models.py:45-49` 约束放宽 + 迁移；`ingestion_service.py:833-842` 注册表化；planner 词表接域档案。

**011 通用域评测**：`eval/generic_domain_eval_dataset.json`、`eval/legal_domain_eval_dataset.json` + 生成器扩展 + 域基线报告；quickstart 多域验收；文档债清理（roadmap/README/spec Status）。

---

## 6. 评估策略

- **无回归义务（每个 Feature）**：001/002 基线 11/18 条、003 格式集、004 图集 37 条、005 agentic 44 条、006 冒烟 11 条，按所属 Feature 的既有口径重跑，非延迟指标在 1% 相对容差内一致；se-project 域档案行为与 1.0 逐项一致。
- **新能力评测**：008 每新格式 ≥2 条查询（≥1 自然语言 + ≥1 结构定位）+ 转换层契约测试；010 交叉引用子集 ≥6 条，结构性受益 ≥3%（004 闸口沿用）；007/009 以功能与无回归验收为主（对照义务声明沿用 006 "工程硬化"特例范式）。
- **011 域基线**：个人知识库域与法律域各 ≥10 条（AI 生成 + 人工审核入库，沿用固定集纪律），产出 dense/hybrid 域基线报告，作为后续通用域优化的对照锚点。
- **硬指标三件套**（跨域语义）：在混合域验收集上串库 = 0 / Schema 合法率 = 100% / 定位率 = 100%。

---

## 7. Feature 划分（007–011，纵向可独立验收）

| Feature | 名称 | 核心交付 | 规模预估 | 对照评测义务 |
|---|---|---|---|---|
| **007** | knowledge-domain-generalization | 宪法 v1.3.0；双轴知识域 + 域档案注册表；domain_scope 兼容扩展 + list_knowledge_domains；3 处 public 残留修复；scope slug 寻址 | 60–75 任务 | 无检索质量对照（架构泛化）；既有全集无回归 + 新参数功能验收 |
| **008** | universal-ingestion-channel | FormatHandler 注册表；markitdown 转换层；首批 9 格式；CHECK 放宽；定位前缀规范 | 55–70 任务 | 每新格式 ≥2 条 + 003 回归 + 硬指标 |
| **009** | domain-neutral-retrieval | planner 域中立提示词 + 档案注入；动态关系词表；task_context 泛化；契约描述中立化 | 35–45 任务 | 005 agentic 44 条 + 确定性 37 条无回归 |
| **010** | graph-relation-registry | 提取器插件接口 + 注册表；relation_type 放宽；交叉引用提取器（非 SE 验证） | 40–50 任务 | 004 回归 + 交叉引用子集受益 ≥3% |
| **011** | generic-domain-evaluation | 两验证域语料与评测集；域基线报告；多域端到端验收；文档债清理；2.0 定稿 | 30–40 任务 | 域基线建立 + 硬指标全量 + 全集回归 |

执行纪律沿用 1.0 §23：每 Feature 完整走 specify → clarify → plan → checklist → tasks → analyze → implement → converge 生命周期，前序 Feature 收敛后启动下一个；全部提示词见《通用RAG演进-SpecKit迭代提示词.md》。

---

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| markitdown 依赖引入（供应链/版本漂移） | 锁定版本 + 转换器接口可插拔（pandoc/tika 可替换）+ 转换层契约测试固化行为 |
| 转换产物质量不稳定（表格破碎/标题丢失） | 每格式 ≥2 条评测查询把关；不合格格式走原生兜底立项（ADR-4 例外路径） |
| schema anyOf 弱化"至少一个 scope"约束 | 入口层显式校验（两参数并集非空）补位，沿用 1.0 "服务端固定护栏"原则 |
| 双参数（project_scope/domain_scope）长期并存心智负担 | 007 契约文档明确"project_scope 为兼容形式、新集成一律用 domain_scope"；收敛留待未来 MAJOR |
| planner 提示词重构导致 SE 域规划质量回退 | se-project 档案 prompt_overrides 逐句保留 1.0 规则；005 数据集回归闸口 |
| 图词表开放后硬边可信度稀释 | 硬/软关系区分不变（宪法 III）；提取器必须产 parse_evidence；受益闸口不放松 |
| 通用域敏感内容（PII/医疗）越界 | 维持 1.0 §26 立场：不预设广义脱敏；受监管域语料入库前由用户负责，触发条件不变 |

---

## 9. 演进触发条件（继承 1.0 §26 并新增）

继承（不变）：自动内容同步 / Neo4j / MCP Tasks / 认证 / 敏感内容脱敏 / 更强 Embedding。
新增：

- **原文档锚点定位**：用户域出现"标题路径粒度不足定位"的真实痛点（如长合同精确到条款段）。
- **OCR 通道**：扫描件成为主要资料形态且转换层无法覆盖。
- **原生解析器替换评估**：某存量格式的转换层对照评测达到原生质量，且维护成本显著。
- **domain_scope 正名**：客户端生态完成迁移、双参数兼容层维护成本超过收益，触发 MAJOR 版本统一参数。
- **新原生解析器**：某新格式经转换层评测无法达标且检索价值明确。

---

## 10. 与 1.0 蓝图的衔接

- 1.0 蓝图 §1–§22（除被本文 §3 显式修订的段落）继续有效；§23 Feature 列表由本文 §7 延续（007–011）；§24 评估策略由本文 §6 扩展；§25 首期成功条件已达成并封存；§26 由本文 §9 扩展。
- 宪法 v1.3.0（007 修订）发布前，以 v1.2.0 为准；修订后宪法继续凌驾全部 Feature 工件（governance 不变）。
- 本文档批准即冻结为目标架构基线；后续架构变更须走宪法修订或新蓝图章节，不得隐藏在 Feature 内（1.0 治理纪律）。
