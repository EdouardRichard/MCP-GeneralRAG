# Feature Specification: Graph Relation Registry（图关系注册表）

**Feature Branch**: `010-graph-relation-registry`

**Created**: 2026-09-06

**Status**: Delivered

**Input**: User description: "图关系注册表：GraphExtractor 插件接口正式抽象（extract(source, chunks, scope) -> list[edge] 收编现 duck-typing 契约，注册表按 format + domain_key 发现提取器）；java_call_graph 与 ddl_fk 迁移至插件接口（行为不变，004 数据集回归）；relation_type CHECK 放宽（graph/models.py:45-49 枚举改宽模式 + 应用层按域档案 graph_relations 词表校验，other_hard 逃生口退役）；文档交叉引用提取器作为非 SE 验证提取器（Markdown 内部链接 [x](#anchor)/相对链接、法规条文"依据第 X 条/参见 X.Y"引用 → references/referenced_by 硬边，产 parse_evidence，服务 legal 域档案）；图路径对 public/generic 域可用（007 已拆 Project 依赖，010 验证端到端）；graph_ready 门控语义不变（硬边 > 0 方可声明，无图档案自然不可声明）；软关系推断框架与格式无关确认回归。范围依据：2.0 蓝图 §3.8/§5-010/ADR-8，1.0 蓝图 §10/§8.2。硬性约束：显式知识域引用；跨域串库为零（图边以 knowledge_scope_id 为唯一隔离键）；Schema 合法率与来源可定位率 100%；硬/软关系区分不变（宪法 III），提取器必须产 parse_evidence。对照评测：004 图增强评测集（37 条，graph_enhanced_comparison_report.json）无回归；新增交叉引用受益子集 ≥6 条（法律域语料，含中文条文引用），结构性受益 ≥3%（沿用 004 SC-001 闸口）证明插件抽象与非 SE 图能力成立。不重复 004 已交付的 Java/DDL 硬关系与软关系推断、007 已交付的图三元组去 Project 依赖。输入材料：001–009 代码、eval/graph_enhanced_comparison_report.json、docs/通用RAG演进蓝图.md。"

## Scope Basis

2.0 蓝图《通用RAG演进蓝图.md》§3.8（图关系注册表与提取器插件：GraphExtractor 插件接口 `extract(source, chunks, scope) -> list[edge]` 正式抽象、注册表按 format + domain_key 发现提取器、java_call_graph/ddl_fk 迁移、relation_type CHECK 放宽、非 SE 交叉引用提取器、public/generic 图路径端到端、graph_ready 门控语义不变）、§5-010（数据与契约变更清单：新 `graph/extractors/base.py` + `graph/extractors/cross_reference.py`、`graph/models.py:45-49` 约束放宽 + 迁移、`ingestion_service.py:833-842` 注册表化）、ADR-8（图提取器插件化 + 交付一个非 SE 提取器作抽象验证——仅抽象不验证=未证明的接口，沿用 004 结构性受益闸口证明收益）、§6（评测策略：010 交叉引用子集 ≥6 条、结构性受益 ≥3% 沿用 004 闸口）、§7（Feature 划分：010 graph-relation-registry，40–50 任务规模，004 回归 + 交叉引用子集受益 ≥3%）、§8（风险缓解：图词表开放后硬边可信度稀释 → 硬/软关系区分不变（宪法 III）+ 提取器必须产 parse_evidence + 受益闸口不放松）。1.0 蓝图《蓝图.md》§10（双层图谱：硬关系 §10.1 / 软关系 §10.2）、§8.2（PostgreSQL 拥有图节点、图边、硬关系与软关系）。支撑：宪法 v1.3.0（原则 III 暴露不确定性——推断图关系与确定性关系可区分、原则 IV 来源可定位、原则 XI 领域中立——图关系词表经域档案声明、硬约束跨域泄漏为零/Schema 合法率 100%/来源可定位率 100%）。**前置已满足**：007 已交付域档案注册表（`graph_relations` 词表字段）与图三元组去 Project 依赖（`knowledge_scope_id` 为唯一图隔离键）；004 已交付 GraphEdge/SoftRelation 模型、Java 调用图与 DDL 外键提取器、软关系推断、graph_ready 能力门控、1–3 跳扩展与图增强对照评测。

## 对照评测声明

本 Feature 同时承担两类对照义务：**无回归义务**（004 图增强评测集 37 条，插件化重构不得改变既有硬关系行为）与**新能力质量对照义务**（交叉引用提取器在非 SE 法律域语料上证明结构性受益，沿用 004 SC-001 闸口）。

### 无回归基线 — 004 图增强评测集（37 条）

004 交付的图增强路径（混合检索 + 图关系扩展）评测记录于 `eval/graph_enhanced_comparison_report.json`；其中 004 图集为 37 条（该报告 `per_query_comparison` 索引 0–36，覆盖 Markdown/Java/DDL/OpenAPI/Go/Python 结构定位与中文查询，含 7 条结构性受益查询；报告后续索引 37–55 属 008/009 通用域格式查询，不在 004 图集回归口径内）。010 将 java_call_graph 与 ddl_fk 从 duck-typing 契约迁移至插件接口，是**纯重构**：迁移后同一语料、同一 scope、同一版本重跑 004 图集，非延迟指标（Recall@K/MRR/nDCG）在 1% 相对容差内一致（沿用 006/007 SC-009 无回归判定范式），证明插件化未改变既有硬关系语义。

### 质量对照基线 — 交叉引用受益子集（≥6 条）

交叉引用提取器是 010 新增的**非 SE 图能力**，其价值须经评测证明（ADR-8、宪法原则 X）。评测对象为法律域语料（含中文法规条文引用）：在固定法律域评测子集（≥6 条，含 ≥1 条中文条文引用查询）上，运行"图增强 = 混合检索 + 交叉引用图扩展"路径相对"混合检索基线（不加交叉引用图扩展）"，结构性受益子集 MRR 与 nDCG 均值相对提升 ≥3%（沿用 004 SC-001 闸口），Recall@K 不下降。未达阈值则 legal 内置档案以空词表交付（research R11 声明式补救：cross_reference 不为 legal 触发、图路径不进入 legal 默认检索；提取器与注册表照常交付，可由自定义档案显式启用），不进入默认路径（宪法原则 X）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - GraphExtractor 插件接口与注册表 (Priority: P1)

入库流程从已切片 Chunk 出发确定性提取硬关系时，不再通过硬编码的 if/elif 或隐式 duck-typing 挑选提取器，而是通过图关系注册表按 `format + domain_key` 发现提取器：每个提取器声明它消费的源格式与它产出的关系类型，系统据此为该知识域的声明词表调用匹配的提取器。java_call_graph 与 ddl_fk 两个既有提取器迁移至该接口，迁移前后行为逐项不变。

**Why this priority**: 插件接口与注册表是 010 的主干（蓝图 §3.8、ADR-8），也是 relation_type 放宽、交叉引用提取器、public/generic 图路径三者的承载点。没有注册表，"新增提取器"仍意味着改代码而非改档案，宪法原则 XI（领域中立，图关系词表经域档案声明）无法在图层落地。

**Independent Test**: 在 se-project 域发布一个含 Java 调用关系与 DDL 外键关系的知识版本，验证注册表按 (format=java, domain_key=se-project) 与 (format=ddl, domain_key=se-project) 分别发现 java_call_graph 与 ddl_fk 提取器，产出边与迁移前逐条一致；再在声明 `references/referenced_by` 词表的域发布 markdown 语料，验证注册表发现 cross_reference 提取器而 se-project 域不发现它。

**Acceptance Scenarios**:

1. **Given** 图关系注册表已初始化且已注册 java_call_graph / ddl_fk / cross_reference 提取器，**When** 为某格式 + 域档案声明词表发起硬关系提取，**Then** 系统按 (format, domain_key) 精确发现匹配提取器：声明 calls/called_by 的 se-project 域对 java 格式命中 java_call_graph，对 ddl 格式命中 ddl_fk；声明 references/referenced_by 的域对 markdown 格式命中 cross_reference。
2. **Given** 一个格式在目标域档案词表下无任何匹配提取器（如 se-project 域对 markdown 格式，其词表不含 references/referenced_by 且无 markdown 提取器），**When** 提取流程执行，**Then** 系统不调用任何提取器、不产出硬边、不报错（无图档案/无匹配提取器 = 无硬边，graph_ready 自然不可声明）。
3. **Given** 提取器接口的规范返回结构，**When** 任一提取器返回边列表，**Then** 每条边携带规范字段（source_chunk_id/target_chunk_id/relation_type/direction/is_hard=true/version/knowledge_scope_id/index_version/parse_evidence），relation_type 必为域档案 graph_relations 词表成员。
4. **Given** 一个未实现规范接口的提取器，或产出域词表外关系类型的提取器，**When** 注册校验（接口/pairs/pattern）或执行/写入校验发生，**Then** 系统拒绝注册（接口或声明非法）或拒绝写入其产出边（词表外，应用层词表校验兜底，见 US2）。

---

### User Story 2 - relation_type CHECK 放宽与词表校验 (Priority: P1)

数据库层的 `graph_edge.relation_type` 从闭合枚举约束（`calls/called_by/fk_references/fk_referenced_by/other_hard`）放宽为宽模式约束，`other_hard` 逃生口退役；关系类型合法性改由应用层按请求域的域档案 `graph_relations` 词表校验。这使得新增关系类型（如 references/referenced_by）无需再改数据库枚举或借道 other_hard，而只需在域档案声明词表。

**Why this priority**: 这是宪法原则 XI（图关系词表经域档案声明、不硬编码）在图模型层的落地，也是交叉引用提取器能产出 references/referenced_by 硬边的先决条件（现有 CHECK 约束会拒绝该值）。`other_hard` 是 004 预留的框架占位逃生口，其存在违背"关系类型由域档案声明"的领域中立原则，故退役。

**Independent Test**: 向 graph_edge 写入一个关系类型为 `references`、来源/目标 chunk 属声明了 `references/referenced_by` 词表的域，验证写入成功（宽模式 CHECK 通过、应用层词表校验通过）；写入一个词表外值（如 `arbitrary_edge`）被应用层拒绝；写入 `other_hard` 被拒绝（退役）；对 se-project 域写入 `calls` 仍成功。

**Acceptance Scenarios**:

1. **Given** 迁移后的 graph_edge 表，**When** 数据库层对 relation_type 执行约束，**Then** 闭合枚举 CHECK 已放宽为宽模式约束（仅约束基本形态，如非空且长度有界；不再枚举具体关系类型字符串）。
2. **Given** 应用层关系类型校验，**When** 写入一条硬边，**Then** 其 relation_type 必为请求域档案 graph_relations 词表的键（如 se-project 域允许 calls/called_by/fk_references/fk_referenced_by；声明 references/referenced_by 的域允许 references/referenced_by）；词表外值被拒绝并携带明确错误。
3. **Given** 退役后的 `other_hard`，**When** 任何提取器或调用方尝试产出 relation_type=`other_hard` 的硬边，**Then** 系统拒绝；`other_hard` 不再出现于任何内置词表、文档契约或提取器产出。
4. **Given** 存量数据迁移，**When** 迁移执行，**Then** 数据库约束放宽不破坏既有硬边（004 图集回归为证）；若存在遗留 `other_hard` 行则迁移 MUST 显式处理（见 Edge Cases）。

---

### User Story 3 - 文档交叉引用提取器（非 SE 验证提取器） (Priority: P1)

系统从法律/文档语料的 Markdown 中确定性提取交叉引用硬关系：Markdown 内部链接 `[x](#anchor)` 与相对链接 `[x](path.md#anchor)`，以及法规条文的"依据第 X 条 / 参见 X.Y"引用，产出 `references`（引用方 → 被引用方）与 `referenced_by`（被引用方 → 引用方）成对硬边，每条边携带 parse_evidence。该提取器作为非 SE 域验证提取器，在声明 references/referenced_by 词表的域（法律域为首个验证域）中启用。

**Why this priority**: ADR-8 要求"交付一个非 SE 提取器作抽象验证"——仅抽象不验证 = 未证明的接口。交叉引用提取器直击法律验证域，证明插件抽象与"非 SE 图能力"成立，且其受益须过 ≥3% 结构性受益闸口才进入默认路径。

**Independent Test**: 在法律域（domain_key=legal，引用内置 legal 档案）发布含内部链接、相对链接与中文条文引用（"依据第 X 条"/"参见 X.Y"）的 Markdown 语料，验证提取器成对产出 references/referenced_by 硬边、每条边 parse_evidence 可定位（锚点/相对路径/条文号与行号）；再对"谁引用了第 X 条"类查询运行图增强，验证被引用条款证据被召回且标记为硬关系证据。

**Acceptance Scenarios**:

1. **Given** 法律域 Markdown 语料含内部链接 `[x](#anchor)`，**When** 交叉引用提取执行，**Then** 从含链接的 Chunk 到锚点对应标题 Chunk 产出 `references` 硬边（反向 `referenced_by`），parse_evidence 记录链接文本、锚点与源行号。
2. **Given** 法律域 Markdown 语料含相对链接 `[x](./path.md#anchor)`，**When** 交叉引用提取执行，**Then** 从链接 Chunk 到相对路径解析出的目标文件标题 Chunk 产出 `references`/`referenced_by` 硬边对，parse_evidence 记录相对路径与目标锚点。
3. **Given** 法律域语料含中文法规引用"依据第 X 条"或"参见 X.Y"，**When** 交叉引用提取执行，**Then** 从引用 Chunk 到对应条文 Chunk 产出 `references`/`referenced_by` 硬边对，parse_evidence 记录条文号、引用片段与源行号。
4. **Given** 引用目标不存在于语料（锚点/相对路径/条文号无法解析到任何 Chunk），**When** 交叉引用提取执行，**Then** 不产出该条边（宪法原则 III：不确定关系不得伪造，只对可确定的引用产边）。
5. **Given** 一条交叉引用关系的来源与目标为同一 Chunk（自引用），**When** 提取执行，**Then** 不产出自环边（沿用 004 DDL 自引用无自环约定）。

---

### User Story 4 - public/generic 域图路径端到端 (Priority: P2)

007 已拆除图三元组对 Project 行的强制依赖（`knowledge_scope_id` 成为唯一图隔离键），010 验证该能力端到端：一个 public 类型、无 Project 行的知识域，只要其域档案声明图关系词表且知识版本声明 graph_ready（硬边 > 0），即可走图增强检索路径并返回可定位的硬关系证据。

**Why this priority**: 宪法原则 I 与 XI 要求 public/generic 域成为一等公民；007 修的是"图路径不被 Project 行门槛排除"的正确性，010 补上"声明了图词表的非 project 域确实能跑通图增强"的端到端验证，使"无图档案自然不可声明、有图档案自然可用"成立。

**Independent Test**: 创建一个 public + legal 域（引用内置 legal 档案，声明 references/referenced_by 词表），上传 markdown 语料、发布声明 graph_ready 的版本（硬边 > 0），以 domain_scope 寻址发起图增强检索，验证返回的图扩展证据可定位、knowledge_scope_type 为 public、跨域图边泄漏为零；再对 public + generic（无图档案）域验证其不可声明 graph_ready 且图路径不启用。

**Acceptance Scenarios**:

1. **Given** 一个 public 类型知识域（无 Project 行）声明了图关系词表且其知识版本硬边 > 0 并声明 graph_ready，**When** 以 domain_scope 寻址发起图增强检索，**Then** 图路径端到端可用，返回硬关系证据且 evidence 的 knowledge_scope_type 为该域真实值 public（沿用 007 FR-017 口径）。
2. **Given** 一个 public + generic 域（graph_relations 为空），**When** 其知识版本发布或图检索尝试发生，**Then** 该域不可声明 graph_ready（无图词表 → 无提取器 → 硬边 = 0），图路径不启用，仅 Dense/混合检索可用。
3. **Given** 图隔离以 knowledge_scope_id 为唯一键，**When** 跨两个声明图词表的域（其一 public）并发图增强检索，**Then** 跨域图边泄漏事件数为零（任一域不返回另一域图边的证据）。

---

### User Story 5 - graph_ready 门控不变与软关系格式无关回归 (Priority: P2)

graph_ready 门控语义保持不变：仅当知识版本硬边 > 0 方可声明 graph_ready；无图档案的域（词表为空、无匹配提取器）自然不可声明。同时，软关系推断框架保持格式无关——插件化与词表放宽不改动软关系推断的输入/产出/四态生命周期，软关系仍与硬关系可区分、不得伪装为项目事实（宪法 III）。

**Why this priority**: 这是 010 的"不破坏"闸口：插件化与词表放宽只改"硬关系从哪来、关系类型允许哪些值"，不得顺带改变 graph_ready 门控语义或软关系推断框架；后者是 004 已交付且经评测的宪法 III/VI 行为，回归即违规。

**Independent Test**: 发布一个硬边 = 0 的版本验证 graph_ready 不可声明、发布硬边 > 0 的版本验证可声明；对同一语料重跑软关系推断，验证软关系产出、五项元数据、四态生命周期与硬/软区分标注与 010 前一致（004 软关系测试集回归）。

**Acceptance Scenarios**:

1. **Given** 一个知识版本的硬边计数，**When** 发布声明执行，**Then** 硬边 > 0 方可声明 graph_ready；硬边 = 0 或域无图档案时声明被拒绝或 graph_ready 不置位（门控语义与 004 一致）。
2. **Given** 插件化与词表放宽后的系统，**When** 软关系推断对任意格式语料执行，**Then** 推断框架格式无关：软关系产出不受提取器注册表与关系类型词表影响，五项必填元数据与四态生命周期（inferred/active/superseded/retired）不变。
3. **Given** 同一条关系既有硬关系又有软关系判定，**When** 系统组织返回证据，**Then** 硬/软区分不变（宪法 III）：硬关系为准、软关系不得覆盖硬关系、MCP 结果中两者可区分标注，软关系不得升级为硬关系。

---

### Edge Cases

- 某格式在目标域档案词表下无匹配提取器：MUST 不调用提取器、不产边、不报错，graph_ready 自然不可声明（无图档案/无匹配提取器 = 无硬边）。
- 提取器产出的 relation_type 不在目标域词表内：应用层校验 MUST 拒绝写入并报明确错误（域词表兜底，防宽模式 CHECK 放行越界值）。
- 存量 `other_hard` 行：迁移 MUST 显式处置（004 提取器从未产出 other_hard，验收环境断言其数量为 0；非零则 MUST 阻断迁移并要求回填策略，MUST NOT 静默丢弃或静默映射，澄清 Q3，见 Assumptions）。
- 交叉引用目标无法解析（锚点/相对路径/条文号不在语料）：MUST 不产边（不确定关系不得伪造，宪法 III）；同一文档内锚点大小写/空格归一化的具体规则由 plan.md 固化，本规格约束"只对可确定引用产边"。
- 锚点/条文号匹配多个 Chunk（重复标题）：MUST 以确定性规则消歧（规则由 plan.md 固化，如文档内首个匹配或视为不可解析），不产生随机或顺序敏感的不确定归属（宪法 VI，澄清 Q1）。
- 交叉引用自引用（引用方 = 被引用方同一 Chunk）：MUST 不产自环边（沿用 004 DDL 自引用无自环约定）。
- 相对链接指向域外/未入库文件：MUST 不产边（无对应 Chunk）；不跨域补全（跨域泄漏为零）。
- 一个格式 + 域词表命中多个提取器（如未来既有内部链接又有其他 markdown 提取器）：注册表 MUST 以确定性顺序合并各提取器产边并按唯一键去重，不因顺序产生非确定结果（宪法 VI）。
- 一个提取器声明的关系类型与域词表部分交集：非成对关系类型只产交集内关系类型；成对方向关系类型（references/referenced_by、calls/called_by、fk_references/fk_referenced_by）MUST 成对声明并成对产出（澄清 Q2 对称约定），只声明或只产出单侧的提取器注册 MUST 被拒绝；域词表只含成对关系单侧时，提取器仍成对产边、写入层整批拒绝并降级记 hard_degraded_reason 产 0 边（R5 fail-loud），不产生"按声明裁剪"的单向边。
- 图提取在 1–3 跳内因交叉引用产生大量候选（如高频被引条文）：沿用 004 FR-017 图扩展候选预算与结构权重截断，不因扇出爆炸突破延迟或证据预算。
- 同一查询并发多次图增强检索：请求级作用域、证据账本与图扩展中间状态不得串扰（沿用 001–007 并发隔离）。

## Requirements *(mandatory)*

### Functional Requirements

**GraphExtractor 插件接口与注册表（蓝图 §3.8、ADR-8）**

- **FR-001**: 系统 MUST 提供正式的 GraphExtractor 插件接口，规范签名为 `extract(source, chunks, scope) -> list[edge]`，收编现有 java_call_graph / ddl_fk 的 duck-typing 契约；每个提取器 MUST 声明其消费的源格式（format）与产出的关系类型集合（relation_types）。
- **FR-002**: 系统 MUST 提供图关系注册表，按 `format + domain_key` 发现提取器：给定源格式与请求域的域档案 graph_relations 词表，注册表返回其产出关系类型与该域词表有交集的提取器；发现 MUST 确定性（同一输入同一次序）。
- **FR-003**: 提取器产出的每条硬边 MUST 携带规范字段 `source_chunk_id`/`target_chunk_id`/`relation_type`/`direction`/`is_hard`(=true)/`version`/`knowledge_scope_id`/`index_version`/`parse_evidence`；parse_evidence MUST 至少含 source_format、extractor 标识与可定位 locator（宪法 IV 来源可定位、ADR-8 提取器必须产 parse_evidence）。
- **FR-004**: 提取器的 relation_type MUST 为请求域域档案 graph_relations 词表的键；接口层与应用层 MUST 对越界关系类型拒绝（域词表为唯一合法来源，宪法 XI）。
- **FR-005**: 系统 MUST 将 java_call_graph 与 ddl_fk 迁移至插件接口，迁移后产边行为逐条不变（同语料、同 scope、同版本产出与迁移前一致的边集合，含 relation_type、方向配对、去重键与 parse_evidence locator）。
- **FR-006**: 入库硬关系提取 MUST 通过注册表委托执行（收敛 `ingestion_service.py:833-842` 等既有提取调用点），MUST NOT 保留按格式/域硬编码的提取器挑选分支（蓝图 §5-010 注册表化）。
- **FR-007**: 注册表与提取器声明 MUST 不硬编码特定知识域假设：se-project 的 calls/called_by/fk_references/fk_referenced_by 与法律域的 references/referenced_by 均经域档案词表 + 提取器声明表达，不在代码路径中写死（宪法 XI）。

**relation_type CHECK 放宽与词表校验（蓝图 §3.8、§5-010）**

- **FR-008**: 系统 MUST 将 `graph_edge` 的 relation_type 数据库 CHECK 约束从闭合枚举放宽为宽模式（仅约束基本形态，如非空且长度有界；不再枚举具体关系类型字符串）；迁移 MUST 保证放宽不破坏既有硬边数据（004 图集回归为证）。存量 relation_type MUST 保持原值（遗留合法，澄清 Q3）：calls/called_by/fk_references/fk_referenced_by 已与 se-project 域档案 graph_relations 词表键一致，零重写；MUST NOT 引入词表命名空间前缀（如 se:calls 形式的域前缀）——域隔离由 `knowledge_scope_id` 承担，relation_type 保持裸词表键，跨域同名关系类型不冲突。
- **FR-009**: 系统 MUST 在应用层按请求域的域档案 graph_relations 词表校验关系类型：graph_edge 写入前，relation_type 必为该域词表键；词表外值拒绝并报明确错误（宪法 XI 图词表经域档案声明）。
- **FR-010**: `other_hard` 逃生口 MUST 退役：任何提取器/调用方产出 relation_type=other_hard 的硬边 MUST 被拒绝；other_hard MUST 从全部内置词表、契约文档与提取器产出中移除；存量 other_hard 行按 Edge Cases 口径显式处置（断言为 0，非零则阻断迁移并要求回填策略，MUST NOT 静默丢弃或映射，澄清 Q3）。
- **FR-011**: soft_relation 的 relation_type 约束（恒为 `inferred`）与 GraphEdge is_hard=true 约束 MUST 保持不变（硬/软区分不变，宪法 III）；放宽仅作用于硬边 relation_type 的取值范围。
- **FR-012**: 图关系词表校验 MUST 与 007/009 的 relation_vocab 消费一致：域档案 graph_relations 是图关系词表唯一权威来源；新增关系类型（references/referenced_by）通过域档案声明生效，无需改数据库枚举或借道逃生口。

**文档交叉引用提取器（蓝图 §3.8、ADR-8）**

- **FR-013**: 系统 MUST 交付文档交叉引用提取器（cross_reference，format=markdown），确定性提取两类引用硬边：（a）Markdown 内部链接 `[x](#anchor)` 与相对链接 `[x](path.md#anchor)`；（b）法规条文引用"依据第 X 条 / 参见 X.Y"；产出 `references`（引用方 → 被引用方）与 `referenced_by`（被引用方 → 引用方）成对硬边，is_hard=true。双向边生成与 calls/called_by、fk_references/fk_referenced_by 完全对称（澄清 Q2）：每条可确定引用 MUST 同时产出 references 与 referenced_by 两条硬边（direction=out，去重键 (source_chunk_id, target_chunk_id, relation_type) 唯一），MUST NOT 只落单向边或按需动态补产反向边。
- **FR-014**: 交叉引用提取器产出的每条边 MUST 携带 parse_evidence，记录引用类型（内部链接/相对链接/条文引用）、链接文本、锚点或相对路径、条文号与源行号，使关系可独立定位与审计（宪法 IV）。
- **FR-015**: 交叉引用提取器 MUST 只对可确定的引用产边：锚点/相对路径/条文号无法解析到本域语料内的目标 Chunk 时 MUST 不产该边（宪法 III 不确定关系不伪造）；自引用不产自环边。引用锚定语义 MUST 为混合锚定（澄清 Q1）：来源端点按行号区间归属（引用出现的行号落在来源 Chunk 的 `[start_line, end_line]` 区间），目标端点按标题路径匹配（锚点/条文号匹配目标 Chunk 的 `section_path` 末段标题）；MUST 复用解析器已产出的 section_path 与行号元数据，MUST NOT 在提取器内重新解析标题树或退化为 position_path 前缀匹配。
- **FR-016**: 交叉引用提取器 MUST 为领域中立实现：其启用由域档案 graph_relations 词表声明 references/referenced_by 决定，不得在提取器内写死"legal"或任何具体域名（宪法 XI）。法律域为首个声明并验证的挂载域：本 Feature MUST 落地 legal 内置域档案（domain_key=legal，graph_relations 声明 references/referenced_by 及方向，supported_formats 至少含 markdown，is_builtin，受 007 内置只读保护），作为第三个内置档案交付（例外：交叉引用受益闸口（FR-030）未达阈值时，legal 档案以空 graph_relations 词表交付——research R11 声明式补救，cross_reference 不为 legal 触发、图路径不进入 legal 默认检索，提取器与注册表照常交付、可由自定义档案显式启用）；011 在其上建设法律域语料与域基线（澄清 Q4）。
- **FR-017**: 交叉引用提取器 MUST 实现 GraphExtractor 插件接口并注册进图关系注册表（format=markdown），其关系类型声明为 references/referenced_by；se-project 域（词表不含 references/referenced_by）MUST NOT 命中该提取器。
- **FR-018**: 交叉引用图扩展候选 MUST 并入既有图扩展/融合链路（作为图关系的第 3 信号语义不变，1–3 跳、候选预算与结构权重沿用 004 FR-006/FR-007/FR-017），不另建检索路径。

**public/generic 图路径、graph_ready 门控与软关系回归（蓝图 §3.8、宪法 XI）**

- **FR-019**: public/generic 域图路径 MUST 端到端可用：一个 public 类型、无 Project 行的知识域，其域档案声明图词表且版本硬边 > 0 时，图增强检索可用（以 knowledge_scope_id 为唯一图隔离键，007 已拆 Project 依赖，010 验证）；返回证据的 knowledge_scope_type 为该域真实值。
- **FR-020**: graph_ready 门控语义 MUST 不变：仅硬边 > 0 的知识版本方可声明 graph_ready；无图档案域（词表为空、无匹配提取器）MUST NOT 声明 graph_ready 且不启用图路径（沿用 004 FR-013/FR-015 门控语义，实现锚点 `ingestion_service.py:491-509`）。
- **FR-021**: 软关系推断框架 MUST 保持格式无关：插件化与关系类型词表放宽 MUST NOT 改变软关系推断的输入、产出、五项必填元数据与四态生命周期（inferred/active/superseded/retired）；软关系 MUST NOT 升级为硬关系，硬关系只能由确定性提取产生（宪法 III/VI）。
- **FR-022**: 硬/软关系区分 MUST 保持不变：MCP 返回结果 MUST 明确区分硬关系（可验证证据）与推断关系；软关系与硬关系冲突时两者并列返回、软关系不得静默覆盖硬关系（宪法 III、004 FR-004）。
- **FR-023**: 图节点、图边、硬关系与软关系 MUST 全部以 `knowledge_scope_id` 为唯一隔离键隔离存储（007 已拆 project_id，FR-018 口径）；图扩展只在请求作用域内沿边扩展，跨域图边泄漏事件数为零（宪法硬约束）。

**硬性约束（宪法 v1.3.0）**

- **FR-024**: 图增强检索 MUST 继承显式知识域引用要求：缺少显式 project_scope/domain_scope（二者至少一个非空）的检索 MUST 被拒绝，MUST NOT 回退默认或全库（宪法 I、007 FR-019）。
- **FR-025**: 跨知识域串库 MUST 为零：任一图关系、图扩展证据或 Chunk 不得从一域出现在另一域检索中，除非显式多域引用包含该域；验收集断言泄漏事件数 = 0（宪法硬约束，图边以 knowledge_scope_id 为唯一隔离键）。
- **FR-026**: 图增强检索 Tool 成功响应 MUST 100% 通过 `search_knowledge`/`get_evidence` 输出 Schema 校验；010 对外 MCP 契约仅作加法放宽——图标注契约（`mcp-search-output.graph-annotation.schema.json`）的 relation_type 取值域由闭合枚举放宽为宽模式 pattern，既有值全部继续合法、无破坏性变更（宪法 VII、硬约束 Schema 合法率 100%；不放宽则法律域图增强响应携带 references 标注无法通过校验、SC-004 无法成立，research R13）。
- **FR-027**: 图增强检索返回的每条证据（含交叉引用图扩展召回的硬关系证据）MUST 携带来源 ID、版本与可定位位置，来源可定位率 = 100%（宪法 IV、硬约束）。

**对照评测（蓝图 §6/§24.3、宪法 X）**

- **FR-028**: 系统 MUST 在 004 图增强评测集（37 条，`eval/graph_enhanced_comparison_report.json` 索引 0–36）上重跑插件化后的图增强路径，非延迟指标（Recall@K/MRR/nDCG）在 1% 相对容差内与迁移前一致（无回归）；se-project 域插件化重构后的行为与 1.0 逐项一致。
- **FR-029**: 系统 MUST 新增交叉引用受益评测子集 ≥6 条（法律域语料，含 ≥1 条中文条文引用查询，如"谁引用了第 X 条"），遵循 AI 生成、人工审核、JSON 格式的固定集约定；用于证明交叉引用图扩展的结构性受益。
- **FR-030**: 交叉引用图扩展 MUST 在受益子集上证明相对混合检索基线（不加交叉引用图扩展）的结构性受益——MRR 与 nDCG 均值相对提升 ≥3%（沿用 004 SC-001 闸口）、Recall@K 不下降，且不违反任何硬性验收指标，方可进入默认检索路径；未达阈值则 legal 内置档案以空词表交付（R11 声明式补救：cross_reference 不为 legal 触发、图路径不进入 legal 默认检索；提取器与注册表照常交付，自定义档案可显式启用），不进入默认路径（宪法 X）。
- **FR-031**: 对照评测 MUST 逐查询记录混合基线排名与图增强排名、图扩展路径分数（关系类型、跳数、结构权重），使排名变化可解释（宪法 IV，沿用 004 FR-023）；在同一环境会话内先重跑基线再运行图增强以保证延迟增量公平（沿用 004 FR-025）。

### Key Entities *(include if feature involves data)*

- **GraphExtractor（图提取器）**: 确定性硬关系提取的插件单元，规范接口 `extract(source, chunks, scope) -> list[edge]`；声明 source format 与 relation_types；内置 java_call_graph（format=java，产 calls/called_by）、ddl_fk（format=ddl，产 fk_references/fk_referenced_by）、cross_reference（format=markdown，产 references/referenced_by）。产出硬边必带 parse_evidence。
- **图关系注册表（Graph Extractor Registry）**: 按 (format, domain_key) 发现提取器的注册与查找中枢；以域档案 graph_relations 词表为关系类型合法来源，收敛入库硬关系提取调用点。
- **图边（Graph Edge）**: 图节点（Chunk）间的关系边，硬关系 is_hard=true；relation_type 取值由域档案词表声明（不再闭合枚举、无 other_hard 逃生口）；以 knowledge_scope_id 为唯一隔离键，携带 parse_evidence（source_format/extractor/locator）。
- **关系类型词表（Graph Relation Vocabulary）**: 域档案 graph_relations 字段，声明该域可用关系类型及方向；se-project = calls/called_by/fk_references/fk_referenced_by，legal（首个非 SE 验证域，010 落地内置档案）= references/referenced_by，generic = 空。
- **交叉引用关系（Cross Reference）**: 文档引用关系硬边对 references/referenced_by，来源于 Markdown 内部/相对链接与法规条文引用，是首个非 SE 图关系类型。
- **域档案（DomainProfile，沿用 007）**: graph_relations 词表的声明载体；010 落地第三个内置域档案 legal（domain_key=legal，graph_relations={references, referenced_by}，supported_formats 至少含 markdown，is_builtin 只读保护），作为交叉引用提取器的挂载域（澄清 Q4）。
- **图增强评测报告（Comparison Report）**: 004 图集 37 条无回归对照 + 交叉引用受益子集 ≥6 条结构性受益对照的评测产物，逐查询记录排名与图扩展路径。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 插件化无回归：004 图增强评测集（37 条）重跑后非延迟指标（Recall@K/MRR/nDCG）与迁移前在 1% 相对容差内一致；se-project 域 java_call_graph/ddl_fk 产边逐条与迁移前一致（同语料、同 scope、同版本）。
- **SC-002**: 交叉引用结构性受益：法律域受益子集（≥6 条，含 ≥1 中文条文引用）上，"图增强 = 混合检索 + 交叉引用图扩展"相对混合检索基线的 MRR 与 nDCG 均值相对提升 ≥3%，Recall@K 不下降；此为交叉引用图扩展进入默认检索路径的闸口，未达阈值则 legal 档案以空词表交付（research R11 声明式补救），交叉引用图扩展不进入默认路径、可由自定义档案显式启用。
- **SC-003**: 跨知识域串库为零：混合域验收集（含 public + legal 与 project + se-project）中跨域图边泄漏事件数 = 0（knowledge_scope_id 为唯一图隔离键）。
- **SC-004**: Schema 合法率 100%：验收集全部图增强检索 Tool 成功响应 100% 通过 search_knowledge / get_evidence 输出 Schema 校验（对外契约仅加法放宽 relation_type 取值域，见 FR-026 与 research R13）。
- **SC-005**: 来源可定位率 100%：验收集全部返回证据（含交叉引用硬关系证据）100% 携带来源 ID、版本与可定位位置（锚点/相对路径/条文号/符号路径/表名等）。
- **SC-006**: 词表校验有效：relation_type 词表外值与 `other_hard` 写入拒绝率 100%；宽模式 CHECK 迁移后既有硬边数据无损且 relation_type 保持原值（零重写，澄清 Q3）（004 图集回归为证）。
- **SC-007**: 注册表发现正确：se-project 域对 java/ddl 格式命中对应提取器、对 markdown 格式不命中 cross_reference；声明 references/referenced_by 的域（legal 内置档案）对 markdown 格式命中 cross_reference；无匹配提取器时不产边不报错。
- **SC-008**: public/generic 图路径端到端：public + 声明图词表域的图增强检索成功率 100%（证据 knowledge_scope_type 为 public、可定位、跨域泄漏 = 0）；public + generic（无图档案）域不可声明 graph_ready。
- **SC-009**: graph_ready 门控不变：硬边 = 0 的版本声明 graph_ready 被拒绝/不置位，硬边 > 0 的版本可声明；无图档案域自然不可声明。
- **SC-010**: 软关系回归与硬/软区分不变：软关系推断对任意格式产出与 004 一致（五项元数据、四态生命周期）；MCP 结果硬/软可区分，软关系不覆盖硬关系、不升级为硬关系（宪法 III）。
- **SC-011**: 对照评测可重复：同一环境连续两次运行的非延迟指标在 1% 容差内一致（沿用 004 SC-007）；延迟标注环境敏感。
- **SC-012**: 提取器 parse_evidence 完备：验收集全部硬边（含交叉引用硬边）parse_evidence 含 source_format、extractor 标识与可定位 locator，缺失率 = 0（ADR-8、宪法 IV）；交叉引用硬边成对对称（每条 references 均有对应 referenced_by 反向边，澄清 Q2），成对缺失率 = 0。

## 范围内 / 范围外

### 范围内（010）

- GraphExtractor 插件接口（`extract(source, chunks, scope) -> list[edge]`）与图关系注册表（按 format + domain_key 发现）。
- java_call_graph / ddl_fk 迁移至插件接口（行为不变）+ `ingestion_service.py:833-842` 提取调用注册表化。
- relation_type CHECK 放宽（graph/models.py:45-49 宽模式）+ 应用层按域档案 graph_relations 词表校验 + `other_hard` 逃生口退役（含迁移）。
- 文档交叉引用提取器（cross_reference）：Markdown 内部/相对链接 + 法规条文引用 → references/referenced_by 硬边，产 parse_evidence，服务声明 references/referenced_by 的域（法律域为首个验证域）。
- legal 内置域档案落地（第三个内置档案：domain_key=legal、references/referenced_by 词表、markdown 格式集、内置只读保护），作为交叉引用提取器挂载域并承载受益 ≥3% 验证（澄清 Q4；受益闸口未达阈值时以空词表形态交付，research R11 声明式补救）。
- public/generic 域图路径端到端验证（007 已拆 Project 依赖，010 验证）。
- graph_ready 门控语义不变（硬边 > 0 方可声明）与软关系推断框架格式无关确认回归。
- 004 图集 37 条无回归 + 交叉引用受益子集 ≥6 条结构性受益 ≥3% 对照评测。

### 范围外（不重复 001–009）

- Java/DDL/Markdown 解析与切片、Dense/Sparse 检索、RRF/DBSF 融合、Rerank（001–003 已实现；010 复用其已产出 Chunk）。
- 图节点/图边/硬关系/软关系的 PostgreSQL 存储、1–3 跳扩展、图扩展候选预算与结构权重（004 已实现；010 复用并仅放宽 relation_type 取值来源）。
- 软关系 LLM 推断本身（004 已实现；010 仅确认格式无关回归，不重做推断框架）。
- 域档案注册表、domain_scope/slug 寻址、图三元组去 Project 依赖、public 证据断链修复（007 已实现；010 仅做 public/generic 图路径端到端验证）。
- 法律域/个人知识库域完整评测语料库与域基线报告建设（011；010 落地 legal 内置域档案并仅建设交叉引用受益子集 ≥6 条以证明抽象成立，不建设完整法律域语料库与域基线报告）。
- 蓝图 §10.1 中其余硬关系类型（模块依赖、配置引用、测试覆盖等）的完整覆盖——010 建立插件化框架并交付交叉引用作非 SE 验证，其余硬关系类型作为插件框架内的后续批次按独立验收扩展。
- Neo4j、自动内容同步、认证多用户、OCR、敏感内容脱敏（触发条件未满足，不在本期）。

## Clarifications

### Session 2026-09-06

- Q: 交叉引用边应如何把一条引用（Markdown 链接或"依据第 X 条"条文引用）锚定到具体的 chunk？ → A: 混合锚定——来源端点按行号区间归属（引用出现的行落在来源 Chunk 的 [start_line, end_line] 区间），目标端点按标题路径匹配（锚点/条文号匹配目标 Chunk 的 section_path 末段标题）；复用解析器已产出的 section_path 与行号元数据，不在提取器内重新解析标题树。
- Q: references/referenced_by 是否应与 calls/called_by 一样，对每条可确定引用总是同时产出正反两条硬边？ → A: 成对对称产出——每条可确定引用同时落库 references（引用方→被引用方）与 referenced_by（被引用方→引用方）两条硬边，direction=out，去重键 (source_chunk_id, target_chunk_id, relation_type) 唯一，与 calls/called_by、fk_references/fk_referenced_by 的对称约定完全一致。
- Q: 存量 graph_edge 的 relation_type 应保持原值（遗留合法），还是规范化入词表命名空间（如加域前缀 se:calls）？ → A: 保持原值（遗留合法）——calls/called_by/fk_references/fk_referenced_by 已与 se-project 域档案词表键一致，零重写；仅 other_hard 退役（存量断言为 0，非零则阻断迁移并要求回填）。不引入命名空间前缀：域隔离由 knowledge_scope_id 承担，relation_type 保持裸词表键，跨域同名关系类型不冲突。
- Q: legal 域档案是否在本 Feature 落地（作为交叉引用提取器的挂载域），还是仅用 se-project+generic + 临时夹具验证插件抽象、把法律域受益验证推迟到 011？ → A: 本 Feature 落地 legal 内置域档案（domain_key=legal，graph_relations={references, referenced_by}，supported_formats 至少含 markdown，is_builtin，受 007 内置只读保护），作为第三个内置档案并完成交叉引用受益 ≥3% 法律域验证；011 在其上建设法律域语料与域基线。

## Assumptions

- 010 复用 001/003 已建立的 Java/DDL/Markdown 切片与 002/004 已建立的混合检索与图扩展链路，在其已产出 Chunk 上提取硬关系，不重新实现解析、切片、嵌入、融合、Rerank。
- 插件接口的 source format 取值沿用既有格式名（java/ddl/markdown 等，与 007 域档案 supported_formats 口径一致）；具体接口基类、注册表实现位置与发现签名细节（`graph/extractors/base.py`）由 plan.md / research.md 固化，本规格约束签名语义、发现语义与产边契约。
- 关系类型词表（graph_relations）的权威来源为 007 域档案字段；010 不新增数据库层关系类型枚举，只放宽 CHECK 并委托应用层词表校验。
- legal 域档案建立机制已由澄清 Q4 固化为内置档案落地（第三个内置档案，受 007 内置只读保护）；其 default_capabilities（retrieval_modes/has_graph）与 prompt_overrides 的具体声明内容由 plan.md / research.md 固化，graph_relations 与 supported_formats 的声明口径见 FR-016。
- 存量 `other_hard` 行：004 提取器从未产出 other_hard，验收环境断言其数量为 0；若迁移发现非零存量，MUST 显式阻断迁移并要求回填策略，MUST NOT 静默丢弃或静默映射（宪法 III/IV；澄清 Q3 确认其余 4 值保持原值、零重写）。
- 交叉引用提取器的锚定语义已由澄清 Q1 固化（来源端点按行号区间归属、目标端点按 section_path 标题匹配，复用解析器既有元数据）；锚点归一化、相对路径基目录、条文号正则（"第 X 条/第 X 条 Y 款/X.Y"）与重复标题消歧规则的精确格式仍由 plan.md / research.md 固化；本规格只约束"确定性、只对可确定引用产边、成对对称产 references/referenced_by 硬边、parse_evidence 可定位"。
- 交叉引用图扩展沿用 004 图扩展护栏（跳数默认 2/上限 3、候选预算默认 10/上限 20、图扩展子超时默认 3s、总超时 30s），不新增护栏维度。
- 对照评测前，评测法律域语料需先上传、切片、触发重建并发布声明 graph_ready 的版本（硬边 > 0），使交叉引用图扩展路径可执行；受益子集遵循 AI 生成、人工审核、JSON 格式约定，与 004 结构受益子集同款口径。
- 004 图集 37 条 = `eval/graph_enhanced_comparison_report.json` 的 `per_query_comparison` 索引 0–36；该报告当前 config.num_queries=56（含 008/009 通用域格式查询），010 的 004 无回归口径仅覆盖这 37 条，其余查询不在本 Feature 回归断言内（其无回归由 008/009 各自口径保障）。
- 010 面向 001–009 已验证的单用户、本机部署环境；并发隔离沿用请求级隔离（5 并发），不引入多实例或分布式协调。
- 010 对 search_knowledge / get_evidence 对外契约仅作加法放宽（图标注契约 relation_type 取值域由闭合枚举放宽为宽模式 pattern，既有 6 值全部继续合法、无破坏性变更，宪法 VII、research R13）；证据结构、completion_status 四态、来源定位格式沿用 001/004，交叉引用硬关系证据通过既有契约增补可区分的硬关系标注返回。
- 验收参考客户端沿用 006/007 惯例：DeepSeek Harness 为唯一必过参考客户端（图增强 search_knowledge / get_evidence 端到端调用与 Schema 校验必须通过）；ChatGPT App 与 Claude Code 记录兼容性状态、不作 010 验收阻塞项。
