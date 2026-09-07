# Feature Specification: Retrieval Orchestration Domain Neutralization（检索编排域中立化）

**Feature Branch**: `009-domain-neutral-retrieval`

**Created**: 2026-09-06

**Status**: Delivered

**Input**: User description: "检索编排域中立化：query_planner 基础系统提示词重写为域中立（信号选择规则以标识符/定义/关系抽象表述，SE 举例与关系词表全部移入 se-project 域档案 prompt_overrides，运行时按请求 scope 域档案注入；se-project 档案下规划行为与 1.0 一致，用 005 数据集回归验证）；relation_directions 枚举动态化（由域档案 graph_relations 词表生成，query_planner.py:25-26,44-48,97-102 的硬编码 4 值词表移入 se-project 档案，无图档案返回空词表）；task_context 契约泛化（current_file/current_symbol/work_phase 保留为编码域约定字段兼容存量客户端，新增可选自由字符串 activity 供任意域描述当前工作，schema 描述整体域中立化）；SourcePosition 契约描述更新（common.schema.json:34-37 以定位前缀规范表替换 Java 符号单例描述，get_evidence parent_context 措辞域中立化）；gaps 与错误文案去 project 措辞（retrieval_service.py:947-949 等）；evidence_analyst/context_orchestrator/injection_detector 确认已中立并回归。范围依据：2.0 蓝图 §3.7/§3.5/§5-009，1.0 蓝图 §11/§15。硬性约束：显式知识域引用；跨域串库为零；Schema 合法率与来源可定位率 100%；提示注入防护边界不变（域档案注入内容属可信配置、与证据内容结构隔离，宪法 V/1.0 §15）。对照评测：005 agentic 数据集（44 条）与确定性评测集（37 条）无回归（se-project 档案提示词等价性闸口）；无新增检索质量对照义务（编排泛化沿用 006 工程特例范式）。不重复 007 已交付的域档案基础设施与 008 已交付的摄入通道。输入材料：001–008 代码、005 agentic_comparison_report.json、docs/通用RAG演进蓝图.md。"

**Scope Basis**: 2.0 蓝图《通用RAG演进蓝图.md》§3.7（检索编排域中立化：query_planner 基础提示词域中立重写 + prompt_overrides 运行时注入 + relation_directions 动态词表 + 三 Agent 中立性确认 + gaps/错误文案去 project）、§3.5（证据定位前缀规范：source_position 前缀表于 009 写入契约描述）、§3.6（task_context 泛化：activity 字段 + 描述域中立化）、§5-009（009 数据与契约变更清单：query_planner.py / mcp-search-input.schema.json / common.schema.json / retrieval_service.py / config/ 注入接线）、§6（评估策略：无回归义务 + 硬指标三件套 + 007/009 以功能与无回归验收为主）、§7（Feature 划分：009 domain-neutral-retrieval，35–45 任务，005 agentic 44 条 + 确定性 37 条无回归）、§8（风险：planner 提示词重构回退 → se-project 档案逐句保留 1.0 规则 + 005 数据集回归闸口）；1.0 蓝图《蓝图.md》§11（Agent 编排三角色与确定性控制）、§15（提示注入防护）。支撑：宪法 v1.3.0（原则 XI 领域中立——编排与契约不得预设特定知识域、域差异经 DomainProfile 声明式表达；原则 V 数据与控制分离——不可信内容不得控制提示词）。**前置已满足**：域档案基础设施（DomainProfile 表、内置 se-project/generic 档案、graph_relations 与 prompt_overrides 字段）由 007 交付；定位前缀规范表由 008 交付（specs/008-universal-ingestion-channel/contracts/locator-prefixes.md）。本 Feature 不重建二者，仅接线消费。

## 对照评测声明（无新增检索质量对照——编排泛化）

本 Feature 相对既有基线的检索质量对照评测要求为 **无（编排泛化，非检索质量）**，沿用 006 工程硬化特例范式（2.0 蓝图 §6："007/009 以功能与无回归验收为主"）。

理由：009 交付的是检索编排与契约描述的域中立化——query_planner 提示词从硬编码 SE 规则改为域档案驱动、relation_directions 词表动态派生、task_context/SourcePosition 契约描述泛化、gaps/错误文案去 project 措辞。它不新增检索信号、不改变召回/融合/排序/图扩展的算法语义、不修改既有检索路径的默认行为；se-project 档案下的规划行为必须与 1.0 逐项等价（这是等价性闸口，不是质量增量）。进入 plan.md 前，research.md 中的相对基线声明固化为"**无（编排泛化，非检索质量）**"。

替代的评测义务（仅合规、非回归与功能验收，不构成质量对照）：

1. **硬性验收指标保持**（宪法 v1.3.0 硬约束）：检索必须显式知识域引用（project_scope 或 domain_scope 任一形式，缺失即拒绝）、跨知识域串库 = 0、MCP Schema 合法率 = 100%、来源可定位率 = 100%，在混合知识域验收测试集上成立。
2. **se-project 档案提示词等价性闸口**：se-project 档案下的 query_planner 规划行为与 1.0 等价，以 005 agentic 数据集（44 条）回归验证为闸口。
3. **确定性评测集无回归**：004 图集（37 条）按既有口径重跑，非延迟指标在 1% 相对容差内一致。
4. **新契约功能验收**：task_context.activity、SourcePosition 前缀规范表、动态 relation_directions 词表、去 project 措辞各有独立功能验收（见 Success Criteria）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - query_planner 基础提示词域中立化与运行时档案注入 (Priority: P1)

系统对任意知识域执行检索编排时，query_planner 使用域中立的基础系统提示词规划查询：信号选择规则以抽象概念（"标识符/定义"对应 dense/sparse 精确召回，"关系"对应 graph 遍历）表述，不含任何软件工程专属举例或关系词表。当一个请求的作用域解析到 se-project 域档案时，运行时注入该档案 prompt_overrides 中的 SE 规划规则，使规划行为与 1.0 完全一致；解析到无图档案（如 generic）时，使用域中立提示词且不规划 graph 信号。

**Why this priority**: 这是 2.0 演进目标 1 在编排层的落地（蓝图 §3.7、宪法 XI）：消除 query_planner.py 中硬编码的 SE 假设，使"新增域"从改代码降为建档案（ADR-3）。它同时必须保证 se-project 行为逐项等价（宪法 XI 明确"软件工程域是首个内置档案，而非系统默认假设"），否则会稀释 005 已交付的编排质量，故为 P1 且以等价性闸口验收。

**Independent Test**: 分别以 se-project 域与 generic 域各发起一次 agentic 检索，断言 se-project 域下 query_planner 产出的 sub_problems（signals、relation_directions）与 1.0 等价（005 数据集回归全绿）；generic 域下 planner 不产出 graph 信号与任何关系词表条目；再静态审计基础系统提示词，断言零 SE 专属举例（"method call edges / foreign-key edges / class / table / column / constraint" 等均不出现）。

**Acceptance Scenarios**:

1. **Given** query_planner 基础系统提示词（域中立版），**When** 静态审计其文本，**Then** 信号选择规则仅以抽象概念（标识符/定义/关系）表述，不出现任何 SE 专属举例与硬编码关系词表（calls/called_by/fk_references/fk_referenced_by 不内嵌于基础提示词）。
2. **Given** se-project 域档案的 prompt_overrides（query_planner_system_prompt 覆盖片段），**When** 该片段被读取，**Then** 其逐句保留 1.0 DECOMPOSE_SYSTEM_PROMPT 的 SE 规划规则（dense/sparse 用于精确符号/定义/列/类型/约束、graph 用于方法调用/外键/遍历关系、relation_directions 词表），使 se-project 规划行为与 1.0 等价。
3. **Given** 请求作用域解析到 se-project 域档案，**When** query_planner 执行，**Then** 运行时注入该档案的 query_planner_system_prompt（而非域中立基础提示词），规划产出与 1.0 等价。
4. **Given** 请求作用域解析到无 prompt_overrides 覆盖的域档案（或回退场景），**When** query_planner 执行，**Then** 使用域中立基础提示词，规划不引入任何域假设。
5. **Given** 请求作用域解析到无图档案（graph_relations 为空，如 generic），**When** query_planner 执行，**Then** 不产出 graph 信号、不产出 relation_directions（图信号不可规划）。

---

### User Story 2 - relation_directions 枚举动态化 (Priority: P1)

query_planner 的 relation_directions 允许值与确定性双向默认不再硬编码在代码中，而是由请求作用域域档案的 graph_relations 词表动态生成。se-project 档案下词表为 1.0 的 4 值（calls/called_by/fk_references/fk_referenced_by）；无图档案返回空词表，graph 信号不可规划。无效方向选择仍回退到域档案默认词表（沿用 004/FR-033 语义）。

**Why this priority**: relation_directions 的 4 值硬编码（query_planner.py:25-26,44-48）是编排层最核心的域假设——它把"关系词表"固化成了 SE 调用图/外键图（宪法 XI 明令禁止）。动态化是"图关系词表由域档案声明"（ADR-3）在编排层的唯一正确落点，且必须保证 se-project 词表逐字节等价（005 回归闸口），故与 US1 同为 P1。

**Independent Test**: 以 se-project 域检索，断言 relation_directions 词表为 4 值且与 1.0 一致、图扩展行为等价；以 generic（无图）域检索，断言 relation_directions 词表为空、graph 信号不产出、图扩展不触发；单元测试断言 NODE_SCHEMA 的 relation_directions enum 随域档案词表动态生成（se-project → 4 值、generic → 空）。

**Acceptance Scenarios**:

1. **Given** 请求作用域解析到 se-project 域档案，**When** query_planner 构造 NODE_SCHEMA 与校验方向，**Then** relation_directions 允许值 = {calls, called_by, fk_references, fk_referenced_by}（与 1.0 硬编码 4 值一致）。
2. **Given** 请求作用域解析到无图档案（graph_relations 为空），**When** query_planner 构造 NODE_SCHEMA 与校验方向，**Then** relation_directions 词表为空、NODE_SCHEMA 省略 relation_directions 与 graph_hop 字段且 signals 枚举去除 graph（仅 dense/sparse）；graph 信号不可规划、不产出 relation_directions 或 graph_hop。
3. **Given** 模块级硬编码常量（BIDIRECTIONAL_DEFAULT / VALID_DIRECTIONS）被移除，**When** 代码审计，**Then** query_planner.py 中不再存在硬编码 4 值关系词表；默认方向集由域档案 graph_relations 词表派生。
4. **Given** graph 信号存在且 direction 缺失/为空，**When** 校验执行，**Then** 回退到域档案默认词表（se-project 下 = 4 值全量，沿用 004 双向默认语义）；无图档案无默认词表、不启用图扩展。
5. **Given** 任一 direction 无效，**When** 校验执行，**Then** 回退到域档案默认词表（沿用 FR-033）；产出仍 schema_valid=true。

---

### User Story 3 - task_context 契约泛化 (Priority: P2)

外部 Agent 向检索请求传递当前工作上下文时，契约既保留编码域（软件工程）约定字段 current_file/current_symbol/work_phase（存量客户端零破坏），又新增可选自由字符串 activity 供任意知识域描述当前工作；schema 整体描述域中立化（编码域字段明确标注为"编码域约定字段"而非系统唯一定义框架）。

**Why this priority**: task_context 是把"当前在做什么"这一编排信号交给外部 Agent 的契约（蓝图 §3.6）。其 current_file/current_symbol/work_phase 字段名与 work_phase 枚举是 SE 专属假设，activity 是通用域的出口。它不改变检索语义、只扩展契约表面，且必须向后兼容，故 P2。

**Independent Test**: 用 MCP 客户端分别发送仅含 current_file/current_symbol/work_phase 的旧请求（断言逐字节不变）、含 activity 的新请求（断言被接受、进入 task_context 且不影响检索）、含任意自由文本 activity 的通用域请求（断言契约校验通过）；静态审计 schema 描述，断言编码域字段被标注为兼容约定、activity 描述为任意域通用。

**Acceptance Scenarios**:

1. **Given** task_context 契约，**When** 存量客户端仅传 current_file/current_symbol/work_phase，**Then** 字段名、类型、work_phase 枚举逐字节不变，请求行为与 1.0 一致（向后兼容）。
2. **Given** task_context 契约新增 activity 字段，**When** 客户端传入任意自由字符串 activity（描述当前工作），**Then** 该字段被接受并通过 schema 校验，不改变检索执行行为。
3. **Given** task_context schema 描述，**When** 静态审计，**Then** 编码域字段（current_file/current_symbol/work_phase）明确标注为"编码域约定字段（向后兼容）"，activity 描述为任意域通用当前工作描述，整体描述不再以软件工程为唯一定义框架。
4. **Given** 未传 task_context 或未传 activity 的请求，**When** 执行，**Then** 行为不变（activity 为可选字段，缺失不报错）。

---

### User Story 4 - 契约描述与文案域中立化 (Priority: P2)

共享契约 SourcePosition 的描述由 Java 符号单例（"Markdown 为章节路径，Java 为全限定符号路径"）替换为完整定位前缀规范表（标题路径 / page:N / 符号路径 / sheet: / path: / msg: 等）；get_evidence 路径中引用"project scopes / the correct project"的措辞域中立化；检索 gaps 输出与错误文案中作为"知识域"泛化概念的 "project" 措辞去化。上述均为文档/措辞级变更，不改契约结构、不破坏兼容。

**Why this priority**: 契约描述是外部 Agent 与维护者理解字段语义的界面，其 SE 单例（"Java 符号"）会误导非 SE 域使用（蓝图 §3.5）；gaps/错误文案的 "project" 措辞在 domain_scope 双轨下已语义过时。它们不改检索语义、只修正语义表达，故 P2。

**Independent Test**: 静态审计 common.schema.json SourcePosition 描述（断言含定位前缀规范表且不再以 Java 符号为单例）、get_evidence 与 retrieval_service 的 gaps/错误文案（断言泛化知识域措辞的 project 残留为 0）；重放 project_scope-only 兼容请求（断言错误码与消息逐字节不变）；以 domain_scope 双轨请求触发 gaps/错误，断言返回域中立措辞。

**Acceptance Scenarios**:

1. **Given** common.schema.json 的 SourcePosition 定义，**When** 读取其 description，**Then** 以定位前缀规范表（标题路径、page:N、全限定符号路径、sheet:/path:/msg: 等，对齐 008 locator-prefixes.md）替换 Java 符号单例描述；type: string 结构不变、无新增 pattern 约束。
2. **Given** get_evidence 路径（evidence_service.py SCOPE_MISMATCH 等），**When** 触发作用域不匹配，**Then** 错误文案域中立（"does not belong to any of the requested knowledge domains / Ensure the correct domain is specified"），不再以 "project" 为唯一措辞。
3. **Given** 检索 gaps 输出（_infer_gaps 的 suggested_action），**When** 触发 partial 覆盖，**Then** 建议文案域中立（"broadening the knowledge domain scope or adding more knowledge sources"），去 "project scope" 措辞。
4. **Given** 仅 project_scope 的旧客户端请求，**When** 触发缺失/歧义/非法场景，**Then** 旧错误码（MISSING_PROJECT_SCOPE / AMBIGUOUS_PROJECT_REF）与消息、candidates 结构逐字节不变（去 project 措辞不作用于该兼容路径）。

---

### User Story 5 - 三 Agent 中立性确认、防护边界不变与无回归验收 (Priority: P2)

确认 evidence_analyst / context_orchestrator / injection_detector 已域中立（无 SE 专属举例/词表、无域假设），仅回归验证不改语义；确认提示注入防护边界不变——域档案 prompt_overrides 注入内容属可信配置、与不可信证据内容结构隔离；宪法 v1.3.0 硬约束（显式知识域引用、跨域串库为零、Schema 合法率 100%、来源可定位率 100%）在混合域验收集上成立；005 agentic（44 条）与确定性（37 条）无回归。除合规、等价性与非回归外无对照评测要求（对照评测声明：无——编排泛化，非检索质量）。

**Why this priority**: 这是宪法与蓝图 §6 对任何交付的强制发布闸口，也是"编排泛化不稀释 1.0 能力"（蓝图 §1）的唯一可证伪验收。作为门禁而非用户可见价值，定为 P2；其结果决定 US1–US4 是否可发布。

**Independent Test**: 静态审计三 Agent 源码（断言零 SE 专属假设）；运行提示注入验收集（断言恶意上传不能改变控制流）；在混合知识域部署上运行宪法硬约束验收集、005 agentic 44 条与 004 图集 37 条回归；断言泄漏 = 0、Schema 合法率 = 100%、定位率 = 100%、三 Agent 回归全绿、等价性闸口全过。

**Acceptance Scenarios**:

1. **Given** evidence_analyst 源码，**When** 静态审计，**Then** 无 SE 专属举例/词表、conflict_type 已含 domain_conflict；判定语义不变（仅回归）。
2. **Given** context_orchestrator 源码，**When** 静态审计，**Then** 确定性去重/多样性/binning 逻辑无 LLM 提示词、无域假设（仅回归）。
3. **Given** injection_detector 源码，**When** 静态审计，**Then** 其对不可信证据的检测与隔离语义不变；域档案 prompt_overrides 属可信配置、不经 injection_detector、不与证据内容结构混同（宪法 V/1.0 §15）。
4. **Given** 混合知识域验收测试集，**When** 全部验收请求执行，**Then** 跨域泄漏 = 0；无显式知识域引用的请求被拒绝；成功响应 100% 通过 Schema 校验、证据 100% 携带可定位来源。
5. **Given** 005 agentic 数据集（44 条）与 004 图集（37 条），**When** 按既有口径重跑，**Then** 非延迟指标在 1% 相对容差内一致；se-project 档案下规划产出与 1.0 等价。

### Edge Cases

- 请求作用域跨多个不同域档案（如 project_scope 指向 se-project 域 + domain_scope 指向 generic 域）：提示词注入回退域中立基础提示词（澄清 Q1），relation_directions 词表取并集（保证任一请求域可用的关系不被静默丢弃）；跨域泄漏仍由 scope 隔离保证。
- 域档案 graph_relations 键集为空但 default_capabilities.has_graph=true（不一致声明）：以 graph_relations 词表为准——空词表即图信号不可规划（蓝图 §3.7 明确"无图档案返回空词表"）。
- 域档案 prompt_overrides 缺失 query_planner_system_prompt 键：回退到域中立基础提示词，不得报错或静默注入 SE 规则。
- relation_directions 传入值不在动态词表内（含空串/未知词）：回退到域档案默认词表；无图档案下任何 direction 均无效 → 无默认词表、不启用图扩展。
- 动态词表为空时 NODE_SCHEMA 省略 relation_directions 与 graph_hop 字段（非空枚举数组）、signals 枚举去除 graph：graph 信号不产出即无该字段，schema 校验不得因字段省略而崩溃（澄清 Q4）。
- 域档案行与进程内注册表漂移（007 启动同步覆盖）：planner 注入以进程内同步后的注册表为准，漂移修复失败显式失败启动（007 FR-005 承接）。
- 旧客户端仅传 project_scope 触发 gaps 输出：gaps 建议文案去 project 措辞后是否影响旧客户端逐字节判定——gaps 字段为后增输出面，其文案变更不改变旧客户端兼容判据（见 Assumptions）。
- 恶意知识内容含 SE 关系词表字符串（如 "calls"）：经 injection_detector 隔离、不得进入 planner 提示词（宪法 V）；其作为证据内容与域档案词表结构隔离，不构成关系词表污染。

## Requirements *(mandatory)*

### Functional Requirements

**query_planner 基础提示词域中立化与运行时档案注入（蓝图 §3.7、宪法 XI）**

- **FR-001**: query_planner 基础系统提示词 MUST 重写为域中立：信号选择规则 MUST 以抽象概念表述——dense/sparse 对应"标识符/定义"的精确召回，graph 对应"关系/遍历"；基础提示词 MUST NOT 内嵌任何 SE 专属举例（方法调用边、外键边、类/方法/表/列/约束/索引/视图名等）或硬编码关系词表。
- **FR-002**: 1.0 的 SE 规划规则与关系词表 MUST 全部移入 se-project 域档案的 prompt_overrides（query_planner_system_prompt 覆盖片段），该片段 MUST 逐句保留 1.0 DECOMPOSE_SYSTEM_PROMPT 的规则，使 se-project 档案下规划行为与 1.0 等价（005 数据集回归闸口）。
- **FR-003**: query_planner 运行时 MUST 按请求作用域解析到的域档案注入系统提示词：解析域档案集合的 domain_key 唯一（单一档案）且存在 prompt_overrides.query_planner_system_prompt 时使用之；集合含多个不同 domain_key（异构）时 MUST 统一回退到域中立基础提示词（不用任何单一域的 SE 覆盖片段），relation_directions 词表仍取并集；解析档案缺失该覆盖片段时回退到域中立基础提示词；注入 MUST 发生在确定性控制器管线内，注入内容属可信配置（宪法 V 边界内的配置注入，非不可信数据）。
- **FR-004**: 无图档案（graph_relations 为空）的域 MUST 使用无图规划语义：不规划 graph 信号、不产出 relation_directions 或 graph_hop。

**relation_directions 枚举动态化（蓝图 §3.7）**

- **FR-005**: relation_directions 允许值与默认方向集 MUST 由请求作用域域档案的 graph_relations 词表动态生成（词表 = graph_relations 键集）；query_planner.py:25-26（BIDIRECTIONAL_DEFAULT / VALID_DIRECTIONS 常量）与 44-48（NODE_SCHEMA 枚举）的模块级硬编码 4 值词表 MUST 移除，改为从域档案派生。
- **FR-006**: se-project 档案下 relation_directions 词表 MUST 为 {calls, called_by, fk_references, fk_referenced_by}（与 1.0 硬编码一致）；无图档案 MUST 返回空词表——graph 信号不可规划，planner MUST NOT 产出 graph 信号或 relation_directions。
- **FR-007**: 004 确定性双向默认语义 MUST 保持：graph 信号存在且 direction 缺失/为空时回退到当前域档案默认词表（se-project 下 = 4 值全量），无图档案无默认词表、不启用图扩展；任一无效 direction MUST 回退到域档案默认词表（沿用 FR-033）。
- **FR-008**: 无图档案（relation_directions 词表为空）时 NODE_SCHEMA MUST 省略 relation_directions 与 graph_hop 字段、signals 枚举 MUST 去除 graph（仅 {dense, sparse}）——schema 精确反映无图能力，LLM 不被要求产出图相关字段；产出 MUST 保持 schema_valid=true；Schema 合法率 100%（硬约束）。

**task_context 契约泛化（蓝图 §3.6）**

- **FR-009**: task_context 契约 MUST 保留 current_file / current_symbol / work_phase 作为编码域约定字段（字段名、类型、work_phase 枚举 {requirements, design, implementation, testing, review} 逐字节不变，兼容存量客户端）。
- **FR-010**: task_context 契约 MUST 新增可选自由字符串字段 activity，语义为"当前正在做的事"的短描述（域中立一等信号，任意知识域通用）；MUST 为可选、缺失不报错、不改变既有请求行为。与既有 additional_context 语义区分：activity = 当前活动/任务本身，additional_context = 除活动外的其他补充背景（约束/偏好/参考）兜底；二者可共存、不互斥。
- **FR-011**: task_context schema 整体描述 MUST 域中立化：编码域字段 MUST 明确标注为"编码域约定字段（向后兼容）"，activity MUST 描述为任意域通用当前工作描述，整体不得再以软件工程为唯一定义框架。

**SourcePosition 契约描述更新（蓝图 §3.5）**

- **FR-012**: common.schema.json 的 SourcePosition description MUST 由 Java 符号单例描述（"Markdown 为章节路径，Java 为全限定符号路径"）替换为完整定位前缀规范表（对齐 008 locator-prefixes.md：标题路径、page:N、全限定符号路径、sheet:、path:、msg: 等）。
- **FR-013**: get_evidence 路径措辞 MUST 域中立化：evidence_service.py:148-149（SCOPE_MISMATCH "requested project scopes / the correct project"）等引用 "project" 作为泛化知识域概念的文案 MUST 改为域中立措辞（"requested knowledge domains / the correct domain"）；parent_context 描述保持域中立。
- **FR-014**: SourcePosition 契约结构 MUST 不变（type: string，无新增 pattern 约束），仅 description 文档级变更，不破坏兼容（宪法 VII）。

**gaps 与错误文案去 project 措辞（蓝图 §3.7）**

- **FR-015**: 检索 gaps 输出与域泛化错误文案中作为"知识域"泛化概念使用的 "project" 措辞 MUST 去化：_infer_gaps 的 suggested_action（"Consider broadening the project scope…"，retrieval_service.py 现状约 1138 行）MUST 改为域中立措辞（"broadening the knowledge domain scope or adding more knowledge sources"）；domain_scope 双轨路径的错误消息同口径。
- **FR-016**: 旧客户端逐字节兼容 MUST 保持：仅 project_scope 形态的旧错误码（MISSING_PROJECT_SCOPE / AMBIGUOUS_PROJECT_REF）与其消息文本、candidates 结构沿用 007 FR-009 口径逐字节不变——去 project 措辞仅作用于域泛化路径与共享 gaps 输出，不得改变 project_scope-only 兼容路径的既有字节。

**evidence_analyst / context_orchestrator / injection_detector 中立性确认与回归（蓝图 §3.7）**

- **FR-017**: evidence_analyst MUST 确认已域中立（无 SE 专属举例/词表，conflict_type 已含 domain_conflict），仅回归验证、不改判定语义。
- **FR-018**: context_orchestrator MUST 确认已域中立（确定性去重/多样性/binning，无 LLM 提示词、无域假设），仅回归验证。
- **FR-019**: injection_detector MUST 确认已域中立且防护边界不变：其对不可信证据内容的检测与隔离语义 MUST 保持不变；域档案 prompt_overrides 注入内容属可信配置、与证据内容结构隔离，MUST NOT 经过 injection_detector、MUST NOT 授予不可信内容控制权（宪法 V / 1.0 §15）。

**硬性约束与无回归（宪法 v1.3.0、蓝图 §6）**

- **FR-020**: 显式知识域引用 MUST 保持（project_scope 或 domain_scope 任一形式，缺失即拒绝，MUST NOT 推断隐式域或回退全库；007 FR-019 承接）。
- **FR-021**: 跨知识域串库 MUST 为零（007 FR-020 承接；混合域验收断言泄漏事件数 = 0）。
- **FR-022**: Schema 合法率与来源可定位率 MUST 保持 100%（007 FR-021 承接；动态词表与契约描述变更后仍须全绿）。
- **FR-023**: 对照评测要求为 **无（编排泛化，非检索质量）**：MUST NOT 设置质量提升阈值、MUST NOT 执行质量对照评测、MUST NOT 作质量提升声明（沿用 006 工程特例范式）；替代义务为 005 agentic（44 条）与确定性（004 图集 37 条）无回归 + se-project 提示词等价性闸口。

### Key Entities *(include if feature involves data)*

- **域档案 graph_relations 词表（Graph Relations Vocabulary）**: 域档案声明的该域可用关系词表（relation-type → 方向轴，如 se-project 的 calls/called_by/fk_references/fk_referenced_by 各带 out/in）。009 将其键集动态派生为 query_planner 的 relation_directions 允许值与默认方向集（替代硬编码 4 值）。
- **prompt_overrides（query_planner_system_prompt 覆盖片段）**: 域档案声明的规划提示词注入片段；se-project 片段逐句保留 1.0 SE 规划规则，generic 片段为域中立无图提示词。运行时按请求 scope 注入，属可信配置。
- **relation_directions 词表（动态派生）**: query_planner 每次规划的 relation_directions 允许值/默认值，由请求作用域域档案 graph_relations 键集动态生成；se-project → 4 值，无图档案 → 空。
- **task_context 契约**: 检索请求的可选任务上下文对象：编码域约定字段 current_file/current_symbol/work_phase（向后兼容）+ 新增任意域自由字符串 activity（当前活动的短描述，域中立一等信号）+ additional_context（补充背景兜底）。
- **SourcePosition 契约**: 证据来源位置的自由字符串契约；描述由定位前缀规范表（008）替换 Java 符号单例。
- **定位前缀规范表（Locator Prefix Table）**: 008 交付的 source_position 前缀全表（标题路径、page:N、符号路径、sheet:、path:、msg: 等），009 写入 common.schema.json SourcePosition 描述。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: se-project 提示词等价性闸口（分层等价）：（1）se-project 覆盖片段与 1.0 DECOMPOSE_SYSTEM_PROMPT 提示词文本逐句等价（静态断言）；（2）005 agentic 数据集（44 条）每条结构化规划输出（signals/relation_directions）与 1.0 逐条一致（固定模型与温度）；（3）终态指标（recall/mrr/ndcg）在 1% 相对容差内一致、无回归。三者共同构成等价性闸口。
- **SC-002**: 确定性评测集无回归：004 图集（37 条）按既有口径重跑，非延迟指标在 1% 相对容差内一致。
- **SC-003**: 域中立基础提示词零 SE 专属：静态审计断言基础系统提示词中 SE 专属举例与关系词表出现次数 = 0（"method call / foreign-key / class / table / column / constraint" 及 calls/called_by/fk_references/fk_referenced_by 均不内嵌）。
- **SC-004**: relation_directions 动态词表正确：se-project 域 → 4 值词表（与 1.0 一致）；无图档案域 → 空词表、graph 信号产出数 = 0、relation_directions 产出数 = 0。
- **SC-005**: 硬编码词表移除：query_planner.py 中模块级硬编码 4 值关系词表（BIDIRECTIONAL_DEFAULT / VALID_DIRECTIONS / NODE_SCHEMA 枚举）残留数 = 0。
- **SC-006**: task_context 契约向后兼容：仅传 current_file/current_symbol/work_phase 的旧请求逐字节不变（字段名/类型/枚举不变）；含 activity 的新请求被接受且不改变检索行为。
- **SC-007**: SourcePosition 描述更新为定位前缀规范表，契约结构不变（type: string、无新增 pattern）；get_evidence 与检索 gaps/错误文案中泛化知识域措辞的 "project" 残留数 = 0。
- **SC-008**: 旧客户端逐字节兼容：仅 project_scope 形态的缺失/歧义场景 100% 返回旧码且消息/candidates 逐字节不变（去 project 措辞不作用于该路径）。
- **SC-009**: 硬指标三件套（宪法 v1.3.0）：混合知识域验收集上跨知识域串库 = 0、MCP Schema 合法率 = 100%、来源可定位率 = 100%。
- **SC-010**: 提示注入防护边界不变：提示注入验收集（恶意上传）全过，不可信内容不能改变控制流/工具选择/提示词脚手架；域档案注入内容不引入新攻击面（与证据内容结构隔离）。
- **SC-011**: 三 Agent 回归全绿：evidence_analyst / context_orchestrator / injection_detector 既有 pytest 验收测试集全部通过，判定语义不变。
- **SC-012**: 无新增检索质量对照义务：不设质量阈值、不作质量声明（对照评测要求：无——编排泛化，非检索质量）。

## 范围内 / 范围外

### 范围内（009）

- query_planner 基础系统提示词域中立重写 + 运行时域档案 prompt_overrides 注入接线（config/）。
- relation_directions 枚举动态化（由域档案 graph_relations 词表生成，移除硬编码 4 值）。
- task_context 契约泛化（新增 activity 字段 + 编码域字段兼容标注 + 描述域中立化）。
- SourcePosition 契约描述更新（定位前缀规范表）与 get_evidence 措辞域中立化。
- gaps 与错误文案去 project 措辞（域泛化路径与共享 gaps 输出）。
- evidence_analyst / context_orchestrator / injection_detector 中立性确认与回归。
- 宪法 v1.3.0 硬约束验收、se-project 提示词等价性闸口、005 agentic 44 条与 004 图集 37 条无回归、新契约功能验收。

### 范围外（不重复 007/008，且属 010/011 或演进触发条件）

- 域档案注册表（domain_profiles 表、内置 se-project/generic 种子、管理面 CRUD）、domain_scope 参数、scope slug、type:name 寻址、list_knowledge_domains、错误码双轨（007 已交付；009 仅消费 graph_relations 与 prompt_overrides）。
- FormatHandler 注册表、markitdown 转换层、首批新格式接入、chunk_type 两级词表与 CHECK 放宽、定位前缀规范表本体（008 已交付；009 仅将其写入 SourcePosition 契约描述）。
- GraphExtractor 插件接口、relation_type CHECK 放宽、交叉引用提取器、public/generic 域图路径端到端验证（010）。
- 新验证域语料、通用/法律域评测集与域基线报告（011）。
- domain_scope 正名与双参数收敛为单一参数（蓝图 §9 触发条件：客户端生态迁移完成后 MAJOR 版本统一）。
- 认证与多用户权限、自动内容同步、Neo4j、MCP Tasks（1.0 §26 触发条件未满足，不在本期）。

## Clarifications

### Session 2026-09-06

- Q: 当一个检索请求的作用域跨多个不同 domain_key 的域档案时，query_planner 注入哪个（哪些）域档案的 prompt_overrides？ → A: 回退域中立基础提示词——异构档案（多个不同 domain_key）时统一回退域中立基础提示词，不用任何单一域的 SE 覆盖片段；relation_directions 词表仍取并集（保证任一请求域可用的关系不被静默丢弃）。
- Q: task_context 新增的 activity 字段与既有 additional_context 字段在语义上如何区分？ → A: 活动 vs 补充背景——activity = 当前正在做的事的短描述（域中立一等信号）；additional_context = 除活动外的其他补充背景（约束/偏好/参考）兜底；二者可共存、不互斥。
- Q: se-project 提示词等价性闸口以什么口径验证（逐条规划输出比对 vs 终态指标容差比对）？ → A: 分层等价——提示词文本逐句等价 + 结构化规划输出（signals/relation_directions）逐条比对为主 + 终态指标 1% 容差兜底。
- Q: 无图档案（relation_directions 词表为空）时 NODE_SCHEMA 应省略 relation_directions 字段还是显式空数组？ → A: 省略字段——NODE_SCHEMA 不含 relation_directions 与 graph_hop，signals 枚举去除 graph（仅 dense/sparse）。

## Assumptions

- 域档案基础设施（DomainProfile 表、内置 se-project/generic、graph_relations 与 prompt_overrides 字段、启动同步、内置只读保护）已由 007 交付且可用；009 仅接线消费，不重建、不改变 007 已固化的域档案语义。
- 定位前缀规范表以 008 交付的 specs/008-universal-ingestion-channel/contracts/locator-prefixes.md 为准；009 将其内容写入 common.schema.json 的 SourcePosition description，不改表本体。
- "se-project 提示词等价"的可证伪判据 = 005 agentic 数据集（44 条）在 009 前后 query_planner 规划产出等价（sub_problems 的 query/signals/relation_directions 等价），非延迟指标在 1% 相对容差内一致（沿用 006 SC-009 判定范式）。
- activity 字段语义为"当前正在做的事"的短描述（域中立一等信号），与 additional_context（补充背景兜底）区分、可共存（澄清 Q2）；为自由字符串、无枚举约束，长度上限取与 additional_context 同口径的合理默认（4000）；具体约束由 plan.md 固化。
- 多域混合请求（不同域档案）的规划提示词注入默认回退域中立基础提示词（澄清 Q1：异构档案不用任何单一域 SE 覆盖片段）；relation_directions 词表合并仍取并集（保证任一请求域可用的关系不被静默丢弃），跨域泄漏仍由 scope 隔离保证；无图档案参与并集时不引入 graph 能力。具体实现由 plan.md 固化，本规格约束"动态派生、se-project 等价、无图档案为空"三项语义。
- 去 project 措辞仅作用于域泛化路径与共享 gaps 输出；gaps 字段为后增输出面，其文案变更不改变旧客户端逐字节兼容判据（该判据覆盖错误码、错误消息、candidates 与输出结构，见 007 FR-009）。project_scope-only 兼容路径的错误消息字节不变。
- 域档案 prompt_overrides 属可信配置（内置只读 + 管理面自定义），注入为可信提示词脚手架，不经 injection_detector、不与证据内容结构混同（宪法 V / 1.0 §15）；提示注入防护边界不变。
- 验收参考客户端沿用 006 SC-001 惯例：DeepSeek Harness 为唯一必过参考客户端（se-project/generic 两域 agentic 检索与 task_context 新字段须在其 MCP 端点端到端完成并通过 Schema 校验）；ChatGPT App 与 Claude Code 记录兼容性状态、不作验收阻塞项。
- 评测与验收所用知识库沿用 001–006 已发布版本 + 少量 generic 域功能验收夹具；不建设新评测语料集（011 义务），评测集只增不破坏既有条目。
