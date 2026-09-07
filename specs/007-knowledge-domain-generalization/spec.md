# Feature Specification: Knowledge Domain Generalization（知识域泛化）

**Feature Branch**: `007-knowledge-domain-generalization`

**Created**: 2026-09-05

**Status**: Delivered

**Input**: User description: "知识域泛化：双轴知识域模型（scope_type 结构轴沿用 project/public × 新增 domain_key 语义轴）、域档案 DomainProfile 注册表（domain_profiles 表：supported_formats/chunk_type_extensions/graph_relations/prompt_overrides/default_capabilities，内置 se-project 与 generic 两档案，se-project 行为与 1.0 完全一致）、MCP 兼容扩展（search_knowledge 与 get_evidence 新增可选 domain_scope 参数，与 project_scope 并集去重进统一解析器，二者至少一个非空，旧客户端逐字节不变；新增只读工具 list_knowledge_domains 只返回域元数据绝不返回知识内容）、scope slug 全局按名寻址（含 type:name 限定引用）、修复三处 public/project 残留（get_evidence 无法展开 public 证据的断链 evidence_service.py:328-372；agentic 证据硬编码 knowledge_scope_type=\"project\" retrieval_pipeline.py:451,468；图三元组强制 Project 行 retrieval_service.py:1114-1122）、错误码双轨制（仅 project_scope 沿用旧码，涉及 domain_scope 发 MISSING_KNOWLEDGE_SCOPE/AMBIGUOUS_DOMAIN_REF 新码）。范围依据：2.0 蓝图 §1/§3.1/§3.2/§3.6/§5-007/§7/ADR-1/ADR-2/ADR-3/ADR-7，1.0 蓝图 §4/§16。硬性约束：检索必须显式知识域引用（project_scope 或 domain_scope）；跨知识域串库为零；MCP Schema 合法率与来源可定位率 100%；list_knowledge_domains 不得返回任何知识内容。对照评测：无检索质量对照（架构泛化，沿用 006 工程硬化特例范式）；既有评测全集（001/002 基线、003 格式集、004 图集、005 agentic、006 冒烟）无回归；新 domain_scope/slug/list_knowledge_domains 功能验收。不重复 001–006 已实现能力（project/public scope 创建、上传、检索均已有）。输入材料：001–006 代码与契约、docs/通用RAG演进蓝图.md。前置：宪法 v1.3.0 修订已批准。"

**Scope Basis**: 2.0 蓝图《通用RAG演进蓝图.md》§1（系统定位与演进目标：§1.2 核心主张之检索增强核心竞争力与 §1.3 演进目标 1——domain_scope 通用知识域引用、旧 project_scope 客户端零破坏）、§3.1（知识域双轴模型：scope_type 结构轴 × domain_key 语义轴、内置域档案、结构/语义自由组合）、§3.2（域档案注册表 DomainProfile：字段、"一处声明、四层消费"配置中枢、管理面 CRUD 与内置只读保护）、§3.6（MCP 契约兼容扩展：domain_scope 可选参数、并集去重、slug/type:name 寻址、错误码策略、list_knowledge_domains、输出契约零改动）、§5-007（007 数据与契约变更清单，文件级）、§7（Feature 划分：007 knowledge-domain-generalization，60–75 任务规模，无检索质量对照）、ADR-1（兼容扩展而非破坏性改名）、ADR-2（双轴知识域模型）、ADR-3（域档案注册表为唯一配置中枢）、ADR-7（宪法 MINOR 修订 v1.2.0 → v1.3.0）；1.0 蓝图 `蓝图.md` §4（知识域与项目隔离：knowledge_scope 统一抽象、scope_type 二元、public 域不伪装项目、检索显式作用域与候选返回）、§16（MCP 通信设计：§16.5 核心 Tools、§16.7 输出格式）。支撑：宪法 v1.3.0（原则 I 显式知识域引用双形式、II 域事实优先、X 评测驱动、XI 领域中立；五硬约束跨域语义版）。**前置已满足**：宪法 v1.3.0 修订已按 ADR-7 批准生效（`.specify/memory/constitution.md`，2026-09-05），007 以其为合规基线，本 Feature 不修改宪法。

## 对照评测声明（无检索质量对照——架构泛化）

本 Feature 相对既有基线的检索质量对照评测要求为 **无（架构泛化，非检索质量）**，沿用 006 工程硬化特例范式（2.0 蓝图 §6："007/009 以功能与无回归验收为主"）。

理由：007 交付的是作用域引用模型与域配置架构的泛化——双轴知识域模型、域档案注册表、MCP 兼容参数扩展、slug 寻址与三处 public/project 残留修复。它不新增检索信号、不改变召回/融合/排序/图扩展/Agent 编排逻辑、不修改既有检索路径的默认行为，因此不存在可对照的检索质量增量。进入 `plan.md` 前，`research.md` 中的相对基线声明固化为"**无（架构泛化，非检索质量）**"。

替代的评测义务（仅合规、非回归与功能验收，不构成质量对照）：

1. **硬性验收指标保持**（宪法 v1.3.0 硬约束、1.0 §24.2 语义扩展为知识域）：检索必须显式知识域引用（`project_scope` 或 `domain_scope` 任一形式，缺失即拒绝）、跨知识域串库 = 0、MCP Schema 合法率 = 100%、来源可定位率 = 100%，在混合知识域（project/public × se-project/generic）验收测试集上成立。
2. **既有评测全集无回归**：001/002 基线（11/18 条）、003 格式集、004 图集（37 条）、005 agentic（44 条）、006 冒烟（11 条）按各自 Feature 既有口径重跑，非延迟指标在 1% 相对容差内一致（沿用 006 SC-009 判定范式）；se-project 域档案下的行为与 1.0 逐项一致。
3. **新功能验收**：domain_scope 三种寻址形态（数字 scope ID / slug / type:name）、list_knowledge_domains、错误码双轨、三处残留修复各有独立功能验收（见 Success Criteria）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 双轴知识域与域档案管理 (Priority: P1)

管理者为知识域声明领域属性：创建知识域时选择域档案（domain_key），系统按档案声明该域的格式集、chunk_type 扩展词表、图关系词表、提示词覆盖与默认能力。内置 se-project 与 generic 两个域档案随系统交付：se-project 档案下的系统行为与 1.0 完全一致；generic 档案面向通用文档域。管理者可创建、修改、删除自定义域档案，但内置档案受只读保护。project/public 结构轴与 domain_key 语义轴自由组合（如 public + generic = 通用公共域、project + se-project = 1.0 项目域）。

**Why this priority**: 双轴模型与域档案注册表是 2.0 演进的地基（蓝图 §3.1/§3.2、ADR-2/ADR-3）——domain_scope 寻址、list_knowledge_domains 能力摘要、后续 008–010 的四层消费（格式/切片/图/编排）全部依赖 domain_key 语义轴与 domain_profiles 注册表先存在。没有它，其余交付物无从挂载。

**Independent Test**: 通过管理面（REST API + Web）分别创建一个 public+generic 知识域与一个 project+se-project 知识域，验证两者均可创建、可上传、可检索，并按各自域档案元数据被 list_knowledge_domains 列出；尝试修改/删除内置档案被拒绝；se-project 域上的既有检索行为与 1.0 一致（以 001–006 既有验收套件全绿为证）。

**Acceptance Scenarios**:

1. **Given** 域档案注册表已初始化，**When** 系统启动，**Then** 内置档案 se-project 与 generic 存在且标记为内置（is_builtin）：se-project 声明 1.0 既有 8 种原生格式（markdown/java/openapi/ddl/go/python/word/pdf）与 calls/called_by/fk_references/fk_referenced_by 图关系词表及现 SE planner 提示词内容；generic 声明通用文档格式集（转换层格式 + markdown/word/pdf）、无图关系、域中立提示词。数据库行与进程内注册表同步。
2. **Given** 管理面，**When** 管理者创建知识域并声明 domain_key，**Then** 该知识域携带 scope_type（project|public）与 domain_key（引用域档案）两个正交维度；未声明时按默认档案赋值（与存量语义一致，见 Assumptions）。
3. **Given** 内置域档案，**When** 管理者尝试修改或删除，**Then** 操作被拒绝并返回明确错误（只读保护）。
4. **Given** 管理者创建自定义域档案，**When** 提交合法的格式集/词表/提示词/能力声明，**Then** 档案可创建、可被新知识域引用、可更新、可删除（仍被知识域引用时删除被拒绝）。
5. **Given** 任一域档案，**When** 其声明被读取，**Then** 档案数据仅为配置声明（格式名、词表、提示词片段、能力清单），不含任何知识内容。
6. **Given** 存量知识域（升级部署），**When** 迁移执行，**Then** 既有 knowledge_scopes 全部获得 domain_key 赋值且行为与升级前一致（存量 project 与 public 域默认赋 se-project 以保证 1.0 行为不变）。

---

### User Story 2 - domain_scope 兼容检索与统一寻址 (Priority: P1)

外部 Agent 以新的 `domain_scope` 参数检索任意知识域：条目可以是数字 knowledge_scope_id、全局唯一 scope slug，或 `type:name` 限定引用（如 `public:法规库`）。`domain_scope` 与旧 `project_scope` 可同时出现，二者取并集去重后进入统一引用解析器；两个参数至少一个非空，缺失即拒绝、绝不回退全库。仅传 project_scope 的旧客户端行为逐字节不变。错误码双轨：仅 project_scope 沿用旧码（MISSING_PROJECT_SCOPE / AMBIGUOUS_PROJECT_REF），涉及 domain_scope 时发新码（MISSING_KNOWLEDGE_SCOPE / AMBIGUOUS_DOMAIN_REF）。

**Why this priority**: 这是 2.0 演进目标 1 的用户可见出口（蓝图 §1.3-1）：外部 Agent 以通用知识域引用对一个或多个任意知识域执行检索增强，且旧 project_scope 客户端零破坏（ADR-1）。US1 的域档案只有通过这条检索通路才对最终用户产生价值。

**Independent Test**: 用 MCP 客户端分别以三种 domain_scope 形态（数字 scope ID、slug、type:name）检索一个 public+generic 域，验证均返回该域证据且通过输出 Schema 校验；再混合 project_scope + domain_scope 发起联合检索，验证并集生效、去重正确、跨域串库为 0；最后仅传 project_scope 重放 001–006 既有验收请求，验证响应逐字节不变。

**Acceptance Scenarios**:

1. **Given** search_knowledge 或 get_evidence 请求携带 domain_scope（数字 scope ID），**When** 条目指向任一 scope_type（project/public）的活跃知识域，**Then** 该域参与检索，与显式 scope ID 寻址等价。
2. **Given** 请求携带 domain_scope（slug），**When** slug 全局唯一命中一个活跃知识域，**Then** 该域参与检索；slug 不存在或指向非活跃域时该条目不产生作用域约束（按 1.0 引用解析语义跳过，若因此无任何引用可解析则按缺失作用域拒绝，见 Edge Cases）。
3. **Given** 请求携带 domain_scope（type:name 限定引用，如 `public:法规库`），**When** 该 (scope_type, 名称) 组合在活跃域中唯一命中，**Then** 该域参与检索；命中多个时停止检索并以 AMBIGUOUS_DOMAIN_REF 返回候选（候选携带 scope_type/domain_key/slug，见 FR-010）。
4. **Given** 请求同时携带 project_scope 与 domain_scope，**When** 引用解析执行，**Then** 两参数引用取并集、按解析结果去重后作为本次请求的完整知识域集合；两参数至少一个非空，均为空或缺失时拒绝（不回退默认或全库）。
5. **Given** 仅携带 project_scope 的旧客户端请求，**When** 其在 007 后的系统上执行，**Then** 行为逐字节不变：解析路径、错误码（MISSING_PROJECT_SCOPE / AMBIGUOUS_PROJECT_REF）、错误消息、candidates 结构与输出契约均与 1.0 一致（以既有验收套件全绿 + 逐字节兼容测试为证）。
6. **Given** 携带 domain_scope 的请求解析失败（无任何引用可解析或存在歧义），**When** 错误返回，**Then** 错误码为 MISSING_KNOWLEDGE_SCOPE / AMBIGUOUS_DOMAIN_REF；契约 schema 错误码枚举收录新旧全集（只增不删）；AMBIGUOUS_DOMAIN_REF 的 candidates 增量携带 scope_type/domain_key/slug 字段。
7. **Given** 请求以 domain_scope 寻址一个 project 类型知识域，**When** 检索执行，**Then** 结果与以等价 project_scope 引用检索一致（同一 scope 集合决定检索范围，结构轴不改变隔离语义）。

---

### User Story 3 - 知识域发现：list_knowledge_domains (Priority: P2)

外部 Agent 在不检索任何知识内容的前提下发现可用知识域：调用新的只读工具 list_knowledge_domains，获得活跃知识域的 ID、slug、名称、scope_type、domain_key 与能力摘要（支持格式、是否有图）。该工具只暴露域元数据、绝不返回知识内容——发现域 ≠ 检索知识，不构成宪法 I 禁止的隐式全库检索。

**Why this priority**: domain_scope/slug 寻址的前提是调用方知道有哪些域、如何引用（蓝图 §3.6）。它是 US2 的可用性配套而非检索能力本身，交付形态小而独立（单一只读工具），故 P2。

**Independent Test**: 调用 list_knowledge_domains，断言返回的每个条目仅含域元数据字段（ID/slug/name/scope_type/domain_key/能力摘要），不含 chunk、证据、摘录或任何知识正文；再断言仅活跃知识域出现，archived/deleting 域不出现。

**Acceptance Scenarios**:

1. **Given** 混合知识域集合（project/public × se-project/generic，含至少一个 archived 域），**When** 调用 list_knowledge_domains，**Then** 仅活跃域返回，每条含 ID、slug、名称、scope_type、domain_key 与能力摘要（支持格式集、是否有图），全部条目 100% 通过该工具输出 Schema 校验。
2. **Given** 任一 list_knowledge_domains 响应，**When** 审计其内容，**Then** 知识内容出现次数 = 0（无 chunk 正文、证据摘录、来源片段；能力摘要来自域档案声明而非知识内容）。
3. **Given** 无任何活跃知识域的实例，**When** 调用 list_knowledge_domains，**Then** 返回空列表与成功状态，不报错。

---

### User Story 4 - 三处 public/project 残留修复 (Priority: P2)

1.0 遗留的三处 public 域断链/错标在 007 修复（2.0 蓝图 §2.2#4 审计确认）：get_evidence 可展开以 public 作用域检索到的证据（evidence 侧引用解析不支持 public 域的断链）；agentic 路径证据携带真实 knowledge_scope_type 而非硬编码 "project"；图三元组不再强制 Project 行——knowledge_scope_id 成为唯一图隔离键，public 域具备图检索资格。

**Why this priority**: 三处残留是 1.0 已知缺陷——public 域"可创建/可上传/可检索"差这三处闭环（检索侧已支持数字 public scope ID 寻址，但证据展开断链、agentic 错标、图路径被 Project 行门槛排除）。它们阻塞 public/generic 域成为一等公民，但属正确性修复而非新能力主干，故 P2。

**Independent Test**: 在 public 域上传含可解析内容的材料并发布后：search_knowledge（project_scope 以数字 public scope ID 寻址）返回证据，get_evidence 以同一作用域展开该证据成功且来源可定位；开启 agentic 路径检索 public 域，返回证据的 knowledge_scope_type 为 "public"；对已声明 graph_ready 的 public 域发起图增强检索，图路径不再因缺 Project 行而不可用。

**Acceptance Scenarios**:

1. **Given** public 域已发布知识版本，**When** 以其 scope ID 检索并展开证据（search_knowledge → get_evidence 同作用域链路），**Then** 证据展开成功、含完整内容与来源定位，不再因 evidence 侧引用解析仅经 Project 表而断链（现状缺陷定位：evidence_service.py:328-372）。
2. **Given** agentic 检索路径检索 public 域，**When** 证据条目（含父级上下文条目）构造，**Then** knowledge_scope_type 为该域真实 scope_type（"public"），不再硬编码 "project"（现状缺陷定位：retrieval_pipeline.py:451,468）；project 域证据不受影响。
3. **Given** public 域的知识版本声明 graph_ready（硬边 > 0），**When** 图增强检索执行，**Then** 图路径对该域可用（不再要求存在 Project 行；现状缺陷定位：retrieval_service.py:1114-1122）；knowledge_scope_id 是图隔离唯一键，跨域图边泄漏 = 0。
4. **Given** 修复后的全部检索路径，**When** 001–006 既有验收套件执行，**Then** 全部保持通过（修复只拆除 public 断链/错标，不改变 project 域既有行为）。

---

### User Story 5 - 硬性约束、兼容性与无回归验收 (Priority: P2)

007 交付后，宪法 v1.3.0 硬约束（检索必须显式知识域引用、跨知识域串库为零、MCP Schema 合法率 100%、来源可定位率 100%、list_knowledge_domains 无知识内容）在混合知识域验收集上成立；001–006 既有评测全集与验收套件无回归；旧客户端兼容性以逐字节判据固化。除合规、非回归与功能验收外，本 Feature 无对照评测要求（对照评测声明：无——架构泛化，非检索质量）。

**Why this priority**: 这是宪法与蓝图 §24.2（语义扩展为知识域）对任何交付的强制发布闸口，也是"兼容扩展零破坏"（ADR-1）的唯一可证伪验收。作为门禁而非用户可见价值，定为 P2；其结果决定 US1–US4 是否可发布。

**Independent Test**: 在混合知识域（≥2 个 project + ≥1 个 public，跨 se-project/generic 档案）部署上运行：宪法硬约束验收集（含仅 project_scope、仅 domain_scope、双参数混用与两参数皆空场景）、001–006 既有验收套件、旧客户端逐字节兼容测试；验证泄漏 = 0、Schema 合法率 = 100%、定位率 = 100%、既有套件全绿、兼容判据全过。

**Acceptance Scenarios**:

1. **Given** 混合知识域验收测试集，**When** 全部验收请求执行（含仅 project_scope、仅 domain_scope、双参数混用、两参数皆空/为空），**Then** 跨知识域泄漏事件数为零；两参数皆空的请求被拒绝（错误码按双轨规则），绝无全库回退。
2. **Given** 验收集全部 Tool 成功响应，**When** 逐条校验，**Then** search_knowledge / get_evidence / list_knowledge_domains 输出 100% 通过各自声明 Schema 校验；返回证据 100% 携带可定位来源（ID、版本、位置）。
3. **Given** 001–006 既有评测全集与验收套件，**When** 在 007 后的系统上按各自口径重跑，**Then** 全部通过；非延迟指标在 1% 相对容差内一致（延迟与成本标注环境敏感）。
4. **Given** 仅传 project_scope 的兼容测试请求集（覆盖成功、歧义、缺失、非法输入形态），**When** 与 1.0 响应逐字节比对，**Then** 一致（错误码、错误消息、candidates 结构、输出结构均不变）。
5. **Given** 不含任何知识域引用的检索请求，**When** 请求执行，**Then** 被拒绝且不执行任何检索（宪法 v1.3.0 原则 I：project_scope 或 domain_scope 任一形式均可，但必须显式）。

### Edge Cases

- 两参数皆空/缺失（project_scope 与 domain_scope 均缺失或为空数组）：MUST 拒绝；错误码按双轨规则裁决（请求形态仅含 project_scope → MISSING_PROJECT_SCOPE；含 domain_scope → MISSING_KNOWLEDGE_SCOPE）。
- 空串/纯空白引用条目（任一参数内）：MUST 跳过（沿用 1.0 引用解析既有语义）；跳过后若无任何引用可解析，按缺失作用域拒绝。
- 同一知识域被两参数重复引用（如 domain_scope 数字 ID 与 project_scope 数字 ID 指向同一域，或条目字面重复）：并集去重后该域只参与一次，不产生重复结果放大。
- slug 不存在或指向非活跃（archived/deleting）域：该条目按不可解析跳过（对齐 1.0 "仅当全部引用不可解析才失败"语义）；绝不因跳过而放宽为无约束检索。
- type:name 引用命中多个同名同类型活跃域：MUST 停止检索并以 AMBIGUOUS_DOMAIN_REF 返回候选（scope 名称不唯一；slug 为无歧义按名寻址形式）。
- type:name 的 type 非法（非 project/public）：按不可解析处理，错误消息给出合法取值提示。
- 混合双参数请求中 project_scope 条目歧义但 domain_scope 非空：按"涉及 domain_scope 发新码"规则以 AMBIGUOUS_DOMAIN_REF 返回候选（双轨以请求形态而非条目归属决定，保证旧请求形态的旧码字节不变）。
- 新建 slug 与既有 slug 冲突：MUST 被全局唯一约束拒绝；已创建知识域的 slug 变更请求 MUST 被拒绝（创建后不可变，澄清 Q2）。
- 删除仍被知识域引用的自定义域档案：MUST 被拒绝；domain_key 引用完整性不悬空。
- 内置档案种子数据漂移（数据库行与进程内注册表不一致）：启动同步 MUST 修复漂移；同步失败 MUST 显式失败启动，不得静默降级为硬编码行为。
- 存量图数据在隔离键变更（删除 project_id 列、隔离索引重建为仅 knowledge_scope_id 键，澄清 Q4）下：MUST 保持可检索且无数据损失（004 图集回归为证）。
- get_evidence 以 domain_scope 寻址展开证据：证据归属校验按统一解析后的 scope 集合执行；证据不属于任何请求域时拒绝（沿用 1.0 作用域校验语义）。
- 升级部署中既有 project_scope 寻址形态（project_id/scope_id/alias/repo_path）：MUST 全部保持不变可用（slug 是新增寻址面，不取代既有形式）。

## Requirements *(mandatory)*

### Functional Requirements

**双轴知识域模型（蓝图 §3.1、ADR-2、1.0 §4）**

- **FR-001**: knowledge_scope MUST 保留为唯一隔离单元，其结构轴 scope_type 沿用闭合二元 {project, public}（语义与寻址规则沿用 1.0 §4：public 域无 Project 行、不参与 alias/repo_path 寻址；project 域反之）；MUST 新增开放语义轴 domain_key（引用 domain_profiles.domain_key）；两轴正交、可自由组合；存量 scope_id/scope_type/隔离键与既有寻址形态零迁移破坏。
- **FR-002**: 系统 MUST 在升级迁移中为全部存量知识域（project 与 public）赋 domain_key，默认 se-project（保证 1.0 行为逐项一致）；新建知识域 MUST 支持声明 domain_key，未声明时按默认档案赋值（与存量口径一致）。

**域档案注册表（蓝图 §3.2、ADR-3）**

- **FR-003**: 系统 MUST 提供域档案注册表（domain_profiles），字段至少包含：domain_key（主键）、name、description、supported_formats（格式集声明）、chunk_type_extensions（命名空间扩展词表）、graph_relations（该域可用的关系词表及方向）、prompt_overrides（planner 提示词注入片段）、default_capabilities（默认能力声明）、is_builtin（内置标记）。
- **FR-004**: 内置域档案 MUST 随系统交付并种子化：se-project（8 种 1.0 原生格式；calls/called_by/fk_references/fk_referenced_by 图关系词表；现 SE planner 提示词内容；1.0 既有默认能力）与 generic（通用文档格式集：转换层格式 + markdown/word/pdf；无图关系；域中立提示词；通用默认能力）；se-project 档案下系统行为与 1.0 完全一致。
- **FR-005**: 应用启动时数据库 domain_profiles 行 MUST 与进程内注册表同步；内置档案 MUST 受只读保护——任何修改与删除均被拒绝（含字段级修改：supported_formats/graph_relations/prompt_overrides/default_capabilities 等均不可写，澄清 Q1）；管理面 MUST 提供自定义域档案 CRUD，删除 MUST 校验无知识域引用。
- **FR-006**: 域档案声明 MUST 仅为配置数据（格式集、词表、提示词片段、能力声明），MUST NOT 含知识内容。007 交付注册表与两内置档案；格式接受性、chunk_type 词表校验、planner 提示词注入、图关系词表四个消费点的注册表接线分别属 008/009/010——007 MUST NOT 改变这四层的既有行为（保证 se-project 等价与旧客户端不变）；007 自身对档案的消费仅限 list_knowledge_domains 能力摘要与知识域 domain_key 赋值。

**MCP 兼容扩展（蓝图 §3.6、ADR-1、1.0 §16.5/§16.7）**

- **FR-007**: search_knowledge 与 get_evidence MUST 新增可选参数 domain_scope（字符串数组），与 project_scope 取并集去重后进入统一引用解析器；两参数至少一个非空——契约 schema 以 anyOf 表达（放宽 required: ["project_scope"]），服务入口层显式校验并集非空补位；违反时拒绝，MUST NOT 回退默认或全库搜索。
- **FR-008**: domain_scope 条目解析顺序 MUST 为：数字 knowledge_scope_id（任意 scope_type，限活跃域）→ scope slug（全局唯一按名寻址）→ type:name 限定引用（scope_type + 精确名称，首期交付非后置项，澄清 Q3）；alias/repo_path/project_id 仍是 project_scope 专属引用形态。
- **FR-009**: 旧客户端兼容性（硬验收）：仅传 project_scope 的请求行为 MUST 逐字节不变——解析路径、错误码（MISSING_PROJECT_SCOPE / AMBIGUOUS_PROJECT_REF）、错误消息、candidates 字段集与输出契约均与 1.0 一致；007 对既有检索路径的行为修改仅限三处残留修复（FR-016~FR-018）。
- **FR-010**: 错误码双轨制：请求仅含 project_scope 形态（domain_scope 缺失或为空）→ 沿用旧码；请求涉及 domain_scope（非空）→ 发新码 MISSING_KNOWLEDGE_SCOPE / AMBIGUOUS_DOMAIN_REF。契约 schema 错误码枚举 MUST 收录新旧全集且只增不删；candidates 模式 MUST 增量添加可选字段 scope_type/domain_key/slug——新码响应携带扩展字段，旧码（仅 project_scope 形态）响应的 candidates 字节级保持 1.0 形态。
- **FR-011**: 输出契约稳定性：两核心 Tool 成功路径的输出结构（evidence 的 knowledge_scope_id/knowledge_scope_type 等域中立字段）MUST 零改动；007 对外契约变更仅限——输入 schema 新增可选 domain_scope 与 anyOf 放宽、错误码枚举扩展、candidates 可选字段扩展、新增 list_knowledge_domains 契约（宪法 VII）。

**scope slug 全局按名寻址（蓝图 §3.6）**

- **FR-012**: 知识域 MUST 支持全局唯一 slug：跨 project/public 全局唯一（唯一约束，冲突拒绝）；创建时分配（管理面指定或按名称生成；生成规则与存量回填规则由 plan.md 固化，存量回填 MUST 为全部既有域生成唯一 slug 且不改变既有寻址形态）；创建后不可变更（澄清 Q2：保证 domain_scope 引用可重放）。slug 与既有 project 寻址形态 MUST 命名空间隔离：slug 仅在 domain_scope 参数内解析；alias/repo_path/project_id 为 project_scope 专属引用形态，不与 slug 交叉匹配；数字 knowledge_scope_id 双参数皆可（同一域被两参数引用时并集去重，见 FR-007）。
- **FR-013**: slug 寻址 MUST 覆盖 public 与任意域知识域（public 域由此获得第一种非数字引用形态）；type:name 限定引用按 scope_type + 精确名称在活跃域中解析，命中多个时停止检索并以 AMBIGUOUS_DOMAIN_REF 返回候选（含 scope_type/domain_key/slug）。

**list_knowledge_domains（蓝图 §3.6）**

- **FR-014**: 系统 MUST 新增只读 MCP 工具 list_knowledge_domains：返回活跃知识域的 ID、slug、名称、scope_type、domain_key 与能力摘要（支持格式、是否有图）；MUST 只暴露域元数据、绝不返回知识内容（chunk、证据、摘录、来源片段均为禁止输出）——发现域 ≠ 检索知识，不构成宪法 I 禁止的隐式全库检索。
- **FR-015**: list_knowledge_domains 响应 MUST 100% 通过其输出 Schema（新增 list-domains 输出契约）；无活跃域时返回空列表与成功状态；首期全量返回活跃域、无过滤/分页参数（澄清 Q5：响应偏好参数后置为未来兼容扩展，只增不改）。

**三处 public/project 残留修复（蓝图 §2.2#4、§5-007）**

- **FR-016**: get_evidence 的作用域解析 MUST 支持 public 知识域引用展开（修复 evidence_service.py:328-372 断链）：evidence 侧引用解析与检索侧统一解析器口径一致（数字 public scope ID 直达 public 域，不经 Project 表）；public 证据展开链路（search_knowledge → get_evidence 同作用域）端到端可用。
- **FR-017**: agentic 检索路径的证据条目（含父级上下文条目）MUST 携带真实 knowledge_scope_type（按 scope 实际类型），MUST NOT 硬编码 "project"（修复 retrieval_pipeline.py:451,468）；project 域行为不变。
- **FR-018**: 图三元组 MUST 拆除 Project 行强制依赖：knowledge_scope_id 成为唯一图隔离键，图检索资格不再要求存在 Project 行（修复 retrieval_service.py:1114-1122）；存量图数据在新隔离键下 MUST 保持可检索且无数据损失（004 图集回归为证）；graph_edge 与 soft_relation 的存量 project_id 列 MUST 随迁移删除（澄清 Q4），隔离索引重建为仅 knowledge_scope_id 键；project_id 可经 scope→Project 联查派生且图数据可重建（宪法 VIII），无检索信息损失。

**硬性约束（宪法 v1.3.0、1.0 §24.2 语义扩展）**

- **FR-019**: 知识检索 MUST 携带显式知识域引用（project_scope 或 domain_scope 任一形式，二者至少一个非空）；缺失时 MUST 拒绝，MUST NOT 推断隐式活动域、MUST NOT 默认全库搜索；引用无法唯一解析时 MUST 停止检索并返回候选域（宪法 v1.3.0 原则 I）。
- **FR-020**: 跨知识域泄漏 MUST 为零：任一检索结果、证据、图关系或 Chunk 不得从一个知识域出现在另一域的检索中，除非显式多域引用（project_scope/domain_scope 并集）包含该域；混合域验收集中断言泄漏事件数 = 0。
- **FR-021**: 契约工件集 MUST 同步扩展且合法率 100%：mcp-search-input / mcp-get-evidence 输入 schema（domain_scope 可选参数与 anyOf 放宽）、新增 list_knowledge_domains 输出契约、公共契约的知识域引用与候选结构定义、错误码枚举新旧全集；验收集全部 Tool 成功响应 100% 通过声明 Schema 校验，全部返回证据 100% 携带来源 ID、版本与位置（宪法原则 IV、硬约束）。
- **FR-022**: list_knowledge_domains MUST NOT 返回任何知识内容（宪法 I 的发现/检索边界，用户硬性约束）；验收集审计其全部响应的知识内容出现次数 = 0。

**对照评测声明（无）与非回归（蓝图 §6、§24.3 范式）**

- **FR-023**: 本 Feature 相对既有基线的检索质量对照评测要求为 **无（架构泛化，非检索质量）**：MUST NOT 设置质量提升阈值、MUST NOT 执行质量对照评测、MUST NOT 作质量提升声明；research.md 基线声明固化为此口径（沿用 006 工程硬化特例范式）。
- **FR-024**: 作为替代义务，007 的通过判定为三项全过：（1）既有评测全集（001/002 基线 11/18 条、003 格式集、004 图集 37 条、005 agentic 44 条、006 冒烟 11 条）按各自 Feature 既有口径重跑，非延迟指标在 1% 相对容差内一致——任一非延迟指标相对基线下降超过 1% 即判定回归，高于基线的漂移记录为环境敏感、不作质量声明（延迟与成本标注环境敏感）；（2）001–006 既有 pytest 验收测试集全部通过；（3）宪法硬约束在混合知识域验收集上成立（FR-019~FR-022）。回归重跑不构成质量对照。
- **FR-025**: se-project 档案行为等价性 MUST 以既有全集验收：se-project 域上的检索、图扩展与 agentic 编排行为与 1.0 逐项一致（004 图集与 005 agentic 数据集回归为闸口）。

**管理面与前端（蓝图 §5-007）**

- **FR-026**: 管理面（REST 管理 API + Web 前端）MUST 支持：域档案 CRUD（内置只读保护）、知识域创建时的 domain_key 声明与 slug 分配/展示；前端知识域展示 MUST 泛化（呈现 scope_type 与 domain_key/slug 维度）；不引入新的检索入口。

### Key Entities *(include if feature involves data)*

- **域档案（DomainProfile）**: 知识域领域属性的声明式配置中枢：domain_key（主键）、name、description、supported_formats、chunk_type_extensions、graph_relations、prompt_overrides、default_capabilities、is_builtin。内置 {se-project, generic}；自定义档案可增删改（内置只读）。"一处声明、四层消费"——007 建表与种子，四个消费点（摄入/切片/图/编排）接线分别由 008–010 交付。
- **知识域（KnowledgeScope，双轴扩展）**: 唯一隔离单元。结构轴 scope_type {project, public}（闭合，沿用 1.0 语义与寻址规则）× 语义轴 domain_key（开放，引用域档案）；新增全局唯一 slug（按名寻址标识）。
- **scope slug**: 知识域的全局唯一按名寻址标识（跨 project/public）；创建时分配、创建后不可变更（澄清 Q2）；仅在 domain_scope 参数内解析——与 project 专属 alias/repo_path/project_id 属不同命名空间且互不交叉匹配，数字 knowledge_scope_id 为双参数共有的引用形态。
- **知识域引用（Knowledge-Domain Reference）**: 检索请求的显式作用域形式：旧形式 project_scope（project_id/scope_id 数字、alias、repo_path、数字 public scope ID）与新形式 domain_scope（数字 scope ID、slug、type:name）；两形式并集去重后由统一引用解析器解析为活跃知识域集合。
- **统一引用解析器（Unified Scope Resolver）**: 将 project_scope ∪ domain_scope 引用集合解析为活跃知识域集合的唯一裁决入口；双轨错误码与候选结构在此产生。
- **域元数据摘要（Domain Metadata Summary）**: list_knowledge_domains 返回的活跃域条目：ID、slug、名称、scope_type、domain_key、能力摘要（支持格式、是否有图）；仅元数据、无知识内容。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 旧客户端零破坏：仅传 project_scope 的兼容测试请求集（覆盖成功、歧义、缺失、非法输入形态）在 007 前后响应逐字节一致（错误码、错误消息、candidates、输出结构）；001–006 既有验收套件全绿。
- **SC-002**: domain_scope 功能验收：数字 scope ID、slug、type:name 三种形态各自寻址任一活跃知识域（含 public 域与 project 域）检索成功率 100%（通过输出 Schema 校验）；双参数混用并集去重正确（重复引用不放大结果集）。
- **SC-003**: 跨知识域串库为零：混合知识域验收集（≥2 个 project + ≥1 个 public，跨 se-project/generic 档案，含双参数混用与边界形态）中泄漏事件数 = 0。
- **SC-004**: Schema 合法率 100%：验收集全部 Tool 成功响应（search_knowledge / get_evidence / list_knowledge_domains）100% 通过声明 Schema 校验。
- **SC-005**: 来源可定位率 100%：验收集全部返回证据携带来源 ID、版本与位置且可解析回源。
- **SC-006**: 域发现无知识内容：list_knowledge_domains 全部响应中知识内容出现次数 = 0；仅活跃域返回；空实例返回空列表成功状态。
- **SC-007**: 三处残留修复行为验收：public 域证据展开（search_knowledge → get_evidence 同作用域链路）成功率 100%；agentic 路径 public 域证据 knowledge_scope_type 错标数 = 0；graph_ready 的 public 域图路径可用（不再因缺 Project 行被排除）。
- **SC-008**: 域档案治理有效：内置档案修改/删除拒绝率 100%；自定义档案 CRUD 全链路可用且被引用时删除被拒绝；启动同步后数据库行与进程内注册表一致（漂移 = 0）。
- **SC-009**: 无回归三项判定全过（沿用 006 SC-009 范式）：（1）既有评测全集五套（001/002 基线、003 格式集、004 图集、005 agentic、006 冒烟）非延迟指标在 1% 相对容差内一致；（2）001–006 既有 pytest 验收测试集全部通过；（3）硬性指标保持（SC-003~SC-005）。不设质量阈值、不作质量声明（对照评测要求：无）。
- **SC-010**: 错误码双轨正确：仅 project_scope 形态的缺失/歧义场景 100% 返回旧码且 candidates 字节级不变；涉及 domain_scope 的对应场景 100% 返回新码且候选携带 scope_type/domain_key/slug；契约枚举含新旧全集。
- **SC-011**: slug 全局唯一且寻址无串扰：重复 slug 创建拒绝率 100%、已创建域 slug 变更尝试拒绝率 100%（澄清 Q2 不可变）；slug 与 type:name 寻址对同名不同域能正确区分（歧义场景按 AMBIGUOUS_DOMAIN_REF 返回候选）；slug 字符串出现在 project_scope 参数内时不改变 project_scope 既有解析结果（命名空间隔离，旧客户端逐字节不变不受影响）。
- **SC-012**: 显式作用域强制：无任何知识域引用的请求拒绝率 100%，验收集中全库回退事件数 = 0。

## 范围内 / 范围外

### 范围内（007）

- 双轴知识域模型：knowledge_scopes.domain_key 语义轴 + 存量回填迁移（默认 se-project）。
- 域档案注册表：domain_profiles 表与字段、内置 se-project/generic 档案种子、应用启动同步、管理面 CRUD 与内置只读保护。
- MCP 兼容扩展：search_knowledge / get_evidence 可选 domain_scope 参数、anyOf 放宽 + 入口显式校验、统一引用解析器（双参数并集去重）、错误码双轨与候选结构扩展、契约 schema 变更集。
- scope slug 全局按名寻址与 type:name 限定引用（含存量 slug 回填）。
- 新只读工具 list_knowledge_domains 及其输出契约。
- 三处 public/project 残留修复（public 证据断链、agentic scope_type 硬编码、图三元组 Project 强制依赖拆除）。
- 管理面与前端：域档案管理、知识域 domain_key/slug 管理与展示泛化。
- 宪法 v1.3.0 合规验收、既有全集无回归、新功能验收（对照评测声明：无——架构泛化，非检索质量）。

### 范围外（不重复 001–006，且属 008–011 或演进触发条件）

- project/public 知识域创建、上传、解析切片、检索、版本发布等既有能力（001–006 已实现；007 仅扩展作用域引用形式与域属性维度）。
- FormatHandler 注册表、markitdown 转换层、首批新格式接入、chunk_type 两级词表与 CHECK 放宽（008；007 的档案 supported_formats 仅为声明数据，不做格式分发与接受性接线）。
- query_planner 域中立提示词重写、prompt_overrides 运行时注入、task_context 泛化、动态关系词表、gaps/错误文案中立化（009）。
- GraphExtractor 插件接口、relation_type CHECK 放宽、交叉引用提取器、public/generic 域图路径端到端验证（010；007 仅拆除 Project 强制依赖并保障 004 图集无回归）。
- 新验证域语料、通用/法律域评测集与域基线报告（011）。
- domain_scope 正名与双参数收敛为单一参数（蓝图 §9 触发条件：客户端生态迁移完成后 MAJOR 版本统一）。
- 认证与多用户权限、自动内容同步、Neo4j、MCP Tasks（1.0 §26 触发条件未满足，不在本期）。

## Clarifications

### Session 2026-09-05

- Q: 内置域档案（se-project/generic）是否允许用户修改或删除？ → A: 只读保护——内置档案的任何修改与删除（含字段级：supported_formats/graph_relations/prompt_overrides 等）均被拒绝；自定义域档案可增删改（仍被知识域引用时删除被拒绝）。
- Q: scope slug 的冲突与稳定性规则（全局唯一、创建后可否变更、与既有 alias/repo_path 寻址的关系）？ → A: 唯一+不可变+命名空间隔离——slug 跨 project/public 全局唯一（唯一约束，冲突拒绝）、创建时分配、创建后不可变更（保证引用可重放）；slug 仅在 domain_scope 参数内解析，alias/repo_path/project_id 仍是 project_scope 专属引用形态，数字 knowledge_scope_id 双参数皆可；两类引用互不交叉匹配，无优先级裁决问题。
- Q: domain_scope 的 type:name 限定引用是否首期必须，还是 slug 寻址足够（type:name 可后置）？ → A: 首期交付——type:name 限定引用按蓝图 §3.6 解析顺序随 007 落地（数字 scope ID → slug → type:name），非后置项。
- Q: 图三元组去 Project 依赖后的存量 graph_edge.project_id 列处置（保留列停止写入 vs 迁移删除）？ → A: 迁移删除列——graph_edge 与 soft_relation 的 project_id 列随迁移删除，隔离索引重建为仅 knowledge_scope_id 键；project_id 可经 scope→Project 联查派生且图数据可重建（宪法 VIII），无检索信息损失。
- Q: list_knowledge_domains 是否需要响应偏好参数（如按 domain_key 过滤），还是首期全量返回？ → A: 首期全量返回活跃域——无过滤/分页参数；响应偏好参数后置为未来兼容扩展（只增不改）。

## Assumptions

- 宪法 v1.3.0 已按 ADR-7 批准生效（`.specify/memory/constitution.md`，2026-09-05，含原则 XI 与双参数显式作用域措辞）；007 以其为合规基线，不修改宪法。
- 存量知识域（project 与 public）迁移默认赋 domain_key=se-project，新建域缺省同此（蓝图 §3.1 "se-project 默认档案"）；管理面创建时可显式选择任意档案。澄清会话未改变该蓝图缺省口径（存量 public 域亦赋 se-project，保证 1.0 行为逐项一致）。
- slug 口径已由澄清 Q2 固化：全局唯一（跨 project/public）、创建时分配（指定或按名称生成）、创建后不可变更、与 project_scope 专属引用形态命名空间隔离（slug 仅在 domain_scope 内解析）；slug 生成与存量回填的具体规则仍由 plan.md 固化。
- "旧客户端逐字节不变"的可证伪判据 = 001–006 既有验收套件全绿 + 显式兼容测试集（仅 project_scope 请求在升级前后逐字节比对）；三处残留修复改变的是当前已损坏/错标的 public 路径行为（以新增功能测试验收），project 域行为以既有套件验收不变。
- 空串/纯空白引用条目跳过、全部引用不可解析才拒绝的解析语义沿用 1.0（`resolve_project_refs` 既有行为），domain_scope 条目同口径。
- domain_scope 条目数上限沿用 project_scope 既有契约口径（maxItems 10），双参数各自上限独立计数。
- generic 档案的 supported_formats 为前瞻性声明（转换层格式的实际解析能力 008 交付）；007 不因此接入任何新格式解析路径。
- 验收参考客户端沿用 006 SC-001 惯例：DeepSeek Harness 为唯一必过参考客户端（新增 domain_scope 调用形态与 list_knowledge_domains 须在其 MCP 端点端到端完成并通过 Schema 校验）；ChatGPT App 与 Claude Code 记录兼容性状态、不作验收阻塞项。
- 前端泛化仅限展示与管理（知识域列表/详情呈现 domain_key/slug、域档案管理）；不新增检索 UI。
- 评测与验收所用知识库沿用 001–006 已发布版本 + 少量新建 public/generic 域功能验收夹具；不建设新评测语料集（011 义务），评测集只增不破坏既有条目。
- graph 边表存量 project_id 列处置已由澄清 Q4 固化为迁移删除（隔离索引重建为仅 knowledge_scope_id 键）；slug 生成与回填的具体规则、统一解析器与入口校验的实现位置属 plan.md / research.md 决策；本规格约束语义、唯一性与验收断言。
