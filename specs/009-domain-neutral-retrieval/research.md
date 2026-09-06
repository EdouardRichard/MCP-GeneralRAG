# Research: 检索编排域中立化（009）

**Branch**: `009-domain-neutral-retrieval` | **Date**: 2026-09-06

本文件固化解耦 009 的关键设计决策，覆盖三个必修主题（提示注入防护、多域并集注入边界、等价性验证口径）及实现路径决策。所有 NEEDS CLARIFICATION 已在 /speckit-clarify 会话解决（见 spec.md「Clarifications」）。

---

## R1. 提示词模板化与运行时档案注入模型

**Decision**: 将 QueryPlannerAgent.DECOMPOSE_SYSTEM_PROMPT 由「硬编码 SE 规则」改造为「域中立基础模板 + 运行时档案注入」。运行时按请求作用域解析到的域档案集合决定系统提示词：

- 解析域档案集合的 domain_key **唯一**（单一档案）且存在 prompt_overrides.query_planner_system_prompt → 用该覆盖片段作为**完整系统提示词**（se-project 覆盖片段 = 逐句 1.0 DECOMPOSE_SYSTEM_PROMPT；generic 覆盖片段 = 无图中立提示词）。
- 集合含**多个不同 domain_key**（异构）→ 统一回退**域中立基础模板**（不用任何单一域的 SE 覆盖片段）。
- 单一档案但**缺失**该覆盖片段 → 回退域中立基础模板。

域中立基础模板以抽象概念表述信号选择规则（dense/sparse ↔ 标识符/定义精确召回；graph ↔ 关系/遍历），并含一个**关系词表槽位**，运行时以 graph_relations 键集（见 R2 并集）填充；空词表时槽位为空、graph 信号不可规划。

**Rationale**: 对齐 spec FR-001~FR-004 与澄清 Q1。se-project 覆盖片段逐句保留 1.0 规则保证等价性闸口；异构回退域中立模板避免单一域 SE 规则支配跨域查询；基础模板的关系词表槽位使「新增域」只需建档案（ADR-3），不返工代码。

**Alternatives considered**:
- *去重并集（合并多档案覆盖片段）*: 自由文本提示词合并易产生规则冲突与臃肿，语义不可控 → 否决。
- *首个域档案*: 解析顺序有任意性，可能丢失其他域规则 → 否决。
- *拒绝混合*: 与 007 多 scope 联合检索支持冲突，引入新失败模式 → 否决。

---

## R2. NODE_SCHEMA 动态枚举实现路径（动态构造 vs 校验分层）

**Decision**: 采用**动态构造**（per-request）。新增 _build_node_schema(relation_vocab) -> dict 工厂：

- signals 枚举 = ['dense', 'sparse'] + （relation_vocab 非空时追加 'graph'）。
- relation_vocab 非空 → 含 relation_directions（items.enum = relation_vocab）与 graph_hop（integer 1–3）。
- relation_vocab 为空 → **省略** relation_directions 与 graph_hop 字段、signals 不含 graph（澄清 Q4）。

AgentBase 的 validator 由 NODE_SCHEMA 一次性构造；改为**按 frozenset(relation_vocab) 缓存**的 per-request validator（两个内置档案词表仅 2 种形态，缓存命中率 100%）。运行时 _validate_signals / _validate_directions / get_default_directions / _build_fallback_output 全部改从 per-request 词表派生（纵深防御：schema 层 + 校验层双重，fallback 无图时同样省略字段）。

**Rationale**: 澄清 Q4 已裁定「省略字段、signals 去除 graph」，这要求 schema 本体随词表变化，而非仅靠校验分层过滤。动态构造使 schema_valid 语义 = 「结构 + 域能力」双重合法；schema 精确反映域能力、自我文档化。

**Alternatives considered**:
- *校验分层（静态 permissive schema + 运行时过滤）*: 变更最小，但 NODE_SCHEMA 仍静态枚举 4 值 SE 词表或改为无枚举 permissive，与 Q4「省略字段」裁定冲突、schema_valid 不再反映域能力 → 否决。
- *FastJSONSchema（LLM 结构化输出注入 schema）*: 现 LLMClient 仅传 system_prompt + user_payload，不向 LLM 下发 JSON schema（temperature=0.0 + 文本提示词引导 + 后置 Draft202012 校验）；引入结构化输出 API 属超出本 Feature 的破坏性改造 → 否决。

---

## R3. 提示注入防护分析（档案内容与不可信证据隔离）——必修

**Decision**: 域档案 prompt_overrides 属**可信配置**（内置只读 + 管理面自定义，007 FR-005 只读保护），其注入 planner 系统提示词走**确定性控制器可信通道**，与不可信证据内容**结构隔离**；提示注入防护边界（宪法 V / 1.0 §15）不变。

**隔离结构**（三个结构层，物理上不混同）：

1. **系统提示词层（可信）**: 仅由域中立基础模板 + 域档案 prompt_overrides 片段组装（均来自配置，非请求数据）。planner 的 chat_json(system_prompt, user_payload) 的 system_prompt 永不包含 query/证据/上传内容。
2. **请求数据层（不可信）**: query、task_context 仅进入 user_payload（LLM user 消息），不进入 system prompt。
3. **证据内容层（不可信）**: 证据文本进入 user_payload 的 evidence 字段，且继续经 InjectionDetector.sanitize_for_prompt 隔离高危片段（005 已交付，009 不改其语义）。

**边界不变量**（009 必须保持，验证见 quickstart）：
- 上传文档/代码不可改变控制流、工具选择、提示词脚手架（宪法 V）。
- 域档案注入内容不经过 InjectionDetector（它是配置而非证据），也不授予不可信内容任何控制权。
- InjectionDetector 对证据的检测/隔离语义不变（仅回归）。
- 恶意知识内容含 SE 关系词表字符串（如 'calls'）时，其作为证据内容与域档案词表结构隔离，不污染 graph_relations 派生的词表（词表只来自 domain_profiles 配置，永不来自证据）。

**Rationale**: 宪法 V 的「数据与控制分离」要求不可信内容不得控制提示词；域档案是管理面声明的配置（与上传内容性质不同），其注入是「声明式配置消费」（ADR-3），而非「不可信数据控制」。保持边界不变是 009 的硬约束（spec FR-019）。

**Alternatives considered**:
- *将档案注入内容也送 injection_detector*: 混淆配置与证据的信任边界，且会让可信配置被误标/隔离 → 否决。
- *允许证据进入 system prompt 以携带域线索*: 直接违反宪法 V → 否决。

---

## R4. 多域并集注入的边界——必修

**Decision**: relation_directions 词表 = 解析作用域集合所有域档案 graph_relations **键集的排序并集**；无图档案对并集贡献为空。系统提示词仍按 R1 裁决（异构 → 域中立模板），**不**因词表并集而注入任何域的 SE 覆盖片段。

**边界语义**：
- 并集词表**仅用于** relation_directions 的允许值校验与默认方向集派生，以及域中立模板中关系词表槽位的填充（文字化列出可用的关系名）。
- 跨域**串库隔离**仍由检索层的 scope_ids 过滤保证（动态词表/提示词不改变检索隔离逻辑）；词表并集不产生任何跨域数据混合。
- se-project 单域请求词表 = 4 值（等价性闸口）；generic 单域 = 空；异构 = 并集（se-project 的 4 值，因 generic 为空）。

**Rationale**: 澄清 Q1 已裁定「relation_directions 词表仍取并集（保证任一请求域可用的关系不被静默丢弃）」，同时「异构不用任何单一域 SE 覆盖片段」。并集只作用于词表（结构化枚举），不作用于提示词（自由文本），二者边界清晰、可测试。

**Alternatives considered**:
- *词表取交集*: 异构时交集为空 → 图信号不可规划，静默丢弃 se-project 的图能力，与「不静默丢弃」原则冲突 → 否决。
- *词表取首个域*: 任意性 + 丢失其他域关系 → 否决。

---

## R5. se-project 提示词等价性验证口径——必修

**Decision**: 采用**分层等价**（澄清 Q3），三层共同构成等价性闸口：

1. **文本层（静态断言）**: se-project 覆盖片段 == 1.0 DECOMPOSE_SYSTEM_PROMPT 全文（逐句等价）。1.0 提示词逐句迁入 SE_PLANNER_PROMPT，保留全部 SE 举例与关系词表。
2. **结构输出层（逐条比对）**: 005 agentic 数据集 44 条每条结构化规划输出（signals、relation_directions、sub_problems 结构）与 1.0 逐条一致。可行性前提：LLMClient 已固定 temperature=0.0（llm_client.py:211），且 AGENTIC_LLM_CACHE_PATH 响应缓存（T070）使同会话两次运行字节级可复现——先录 1.0 基线输出，再录 009 输出，逐条 diff。
3. **终态指标层（容差兜底）**: recall/mrr/ndcg 在 1% 相对容差内一致（沿用 006 SC-009 判定范式）。

**Rationale**: signals / relation_directions 是低熵、schema 约束的结构化字段，逐条比对能精确捕获「提示词是否等价」；终态指标作为检索质量无回归的最终防线；文本层断言保证「迁移动词未丢规则」。三层互补、可证伪。

**Alternatives considered**:
- *仅逐条输出比对*: 最严格但受 LLM 非确定性影响（需缓存固化）；且不覆盖检索质量回归 → 作为主闸口保留，但不单用。
- *仅终态指标容差*: 间接、不直接验证提示词等价（可能指标不变但规划已漂移）→ 作为兜底保留，不单用。

---

## R6. llm_client / 能力路由域中立确认

**Decision**: **确认无需改动**。LLMClient.chat_json(system_prompt, user_payload) 是厂商/域无关的 OpenAI 兼容调用（system_prompt 由调用方传入）；CapabilityRouter 仅按 Agent role → 模型路由（query_planner/evidence_analyst/context_orchestrator → 各自模型），不含任何域假设。009 的提示词/词表解析全部发生在 planner 内部，最终把解析好的 system_prompt 传入既有 chat_json。

**Rationale**: 领域假设集中在 query_planner 的提示词与词表常量（009 改造点），llm_client 与 capability_router 本就域中立，改造它们属越界。

---

## R7. 域档案解析接线（作用域 → 域档案 → planner 配置）

**Decision**: 在 entry.run_agentic_search 解析出 scope_ids 之后、构造 context 之前，新增异步域档案解析步骤，产物注入 context（键 domain_planner_config）：

1. 查 knowledge_scopes.domain_key（scope_ids → domain_key 集，去重）。
2. 查 domain_profiles（domain_key 集 → 档案行）。
3. 派生 domain_planner_config = {distinct_domain_keys, relation_vocab(并集, R4), prompt_override(单一档案的 query_planner_system_prompt 或 None)}。
4. _step_query_planning 将其随 context 传给 planner；planner 据 R1/R2 解析系统提示词与动态 schema。

在 DomainProfileService 新增助手 resolve_planner_config(session, scope_ids) -> dict（复用该服务对 domain_profiles 的访问口径；内置档案已在启动同步为 DB 行，故统一走 DB 读）。

**Rationale**: planner 是同步执行且无 session；域档案解析需异步 DB 访问，故放在异步入口 entry 完成，避免给 planner 引入 DB 依赖（保持 Agent 纯计算、可单测）。

**Alternatives considered**:
- *planner 内部持有 session 自行解析*: 破坏 Agent 纯计算边界、加重单测成本 → 否决。
- *启动时全局缓存档案、planner 查内存*: 与 007「DB 行为唯一事实源 + 启动同步」口径冲突，自定义档案 CRUD 后内存缓存易漂移 → 否决（内置种子仅作启动回填）。

---

## R8. 契约 schema 变更（additive，宪法 VII）

**Decision**: 契约变更全部 additive / 文档级，不改变既有 Schema 结构：

1. **mcp-search-input.schema.json**（task_context）: 新增可选 activity（type: string，自由字符串，描述「当前活动/正在做的事的短描述」）；current_file / current_symbol / work_phase 描述明确标注「编码域约定字段（向后兼容）」；additional_context 描述标注「补充背景兜底」（澄清 Q2）；对象级 description 域中立化。
2. **common.schema.json**（SourcePosition）: description 由「Markdown 为章节路径，Java 为全限定符号路径」替换为**定位前缀规范表**（对齐 008 locator-prefixes.md：# 标题路径 / page:N / 全限定符号路径 / sheet: / path: / msg: 等）；type: string 结构不变、无新增 pattern。
3. **mcp-get-evidence.schema.json**（source_position / parent_context）: 描述措辞域中立化（若有 project 措辞残留则去化；parent_context 保持域中立）。

**Rationale**: 契约是外部 Agent/维护者的语义界面；SE 单例（「Java 符号」）与 project 措辞在 domain_scope 双轨下语义过时。全部为 description/可选字段级变更，宪法 VII 合规（无破坏性 Schema 结构变更）。

---

## 结论

八条决策（R1~R8 覆盖全部 NEEDS CLARIFICATION 与关键技术路径）已固化。核心不变量：se-project 等价性（R5 三层闸口）、无图档案空词表（R2 省略字段）、异构回退域中立（R1/R4）、提示注入边界不变（R3）、契约 additive（R8）。进入 Phase 1 设计（data-model / contracts / quickstart）。
