# 通用 RAG 演进 · SpecKit 迭代提示词全集（007–011）

**配套蓝图**：《docs/通用RAG演进蓝图.md》（下称"2.0 蓝图"）；1.0 蓝图指根目录 `蓝图.md`。
**适用工作流**：SpecKit v1.0.1（specify → clarify → plan → checklist → tasks → analyze → implement → converge；宪法凌驾全部工件）。
**使用纪律**：

1. 按 007 → 008 → 009 → 010 → 011 顺序串行执行；前一个 Feature 完成 /speckit-converge 收敛后，才启动下一个的 /speckit-specify。
2. 每个 Feature 的提示词按本文档给出的阶段顺序使用；每阶段结束经人工确认后再进入下一阶段（沿用 001–006 的评审闸门习惯）。
3. 所有提示词均可直接复制使用；`<FEATURE_DIR>` 占位符在使用时替换为实际目录（如 `specs/007-knowledge-domain-generalization`）。
4. 硬性验收指标（1.0 §24.2，语义扩展为知识域）贯穿每个 Feature：跨域串库 = 0、MCP Schema 合法率 = 100%、来源可定位率 = 100%。
5. 提示词中的"范围依据/对照基线/不重复"三段式是 003/006 确立的房风，勿删。

---

# Feature 007：knowledge-domain-generalization（知识域泛化）

## 7.0 宪法修订（先行，独立于 Feature 生命周期）

```text
/speckit-constitution 按《docs/通用RAG演进蓝图.md》§3.1/§3.2/ADR-7 修订宪法 v1.2.0 → v1.3.0（MINOR）：
1. 原则 I（Explicit Knowledge Scope）：主语从 project-knowledge retrieval 泛化为 knowledge-domain retrieval——"每次知识检索必须携带显式知识域引用（project_scope 或 domain_scope 任一形式），缺失即拒绝、绝不默认全库；无法唯一解析时返回候选域；public 知识用独立公共域、不得伪装为项目域"。project_scope 保留为兼容引用形式。
2. 原则 II（Project Facts Take Priority → 域事实优先）：措辞域中立化——"公共/共享知识不得静默覆盖专属域知识；冲突时两者并返且各留域身份"，原"项目知识回答本项目如何使用该能力"的表述改为"专属域知识回答本域如何使用该能力"。
3. 原则 X（Evaluation-Driven Optimization）："real-project corpora" 扩为 "真实领域语料（含软件工程域与通用域）"。
4. 新增原则 XI（Domain Neutrality 领域中立）：系统的摄入、检索、编排与契约不得预设特定领域；领域差异必须通过域档案（DomainProfile）声明式表达，不得硬编码在代码路径中；软件工程域是首个内置档案而非默认假设。
5. 硬约束第 1/2 条措辞同步域中立化（"跨项目泄漏"→"跨知识域泄漏"，project_scope → 知识域引用）；交付工作流第 2 条的历史陈述标注为 1.0 历史记录。
版本递增理由：语义扩展 + 新增原则，无原则删除或重定义 → MINOR。输出 Sync Impact Report（含旧→新原则映射）， governance 流程完整走一遍。
```

## 7.1 Specify

```text
/speckit-specify 知识域泛化：双轴知识域模型（scope_type 结构轴沿用 project/public × 新增 domain_key 语义轴）、域档案 DomainProfile 注册表（domain_profiles 表：supported_formats/chunk_type_extensions/graph_relations/prompt_overrides/default_capabilities，内置 se-project 与 generic 两档案，se-project 行为与 1.0 完全一致）、MCP 兼容扩展（search_knowledge 与 get_evidence 新增可选 domain_scope 参数，与 project_scope 并集去重进统一解析器，二者至少一个非空，旧客户端逐字节不变；新增只读工具 list_knowledge_domains 只返回域元数据绝不返回知识内容）、scope slug 全局按名寻址（含 type:name 限定引用）、修复三处 public/project 残留（get_evidence 无法展开 public 证据的断链 evidence_service.py:328-372；agentic 证据硬编码 knowledge_scope_type="project" retrieval_pipeline.py:451,468；图三元组强制 Project 行 retrieval_service.py:1114-1122）、错误码双轨制（仅 project_scope 沿用旧码，涉及 domain_scope 发 MISSING_KNOWLEDGE_SCOPE/AMBIGUOUS_DOMAIN_REF 新码）。范围依据：2.0 蓝图 §1/§3.1/§3.2/§3.6/§5-007/§7/ADR-1/ADR-2/ADR-3/ADR-7，1.0 蓝图 §4/§16。硬性约束：检索必须显式知识域引用（project_scope 或 domain_scope）；跨知识域串库为零；MCP Schema 合法率与来源可定位率 100%；list_knowledge_domains 不得返回任何知识内容。对照评测：无检索质量对照（架构泛化，沿用 006 工程硬化特例范式）；既有评测全集（001/002 基线、003 格式集、004 图集、005 agentic、006 冒烟）无回归；新 domain_scope/slug/list_knowledge_domains 功能验收。不重复 001–006 已实现能力（project/public scope 创建、上传、检索均已有）。输入材料：001–006 代码与契约、docs/通用RAG演进蓝图.md。前置：宪法 v1.3.0 修订已批准。
```

## 7.2 Clarify

```text
/speckit-clarify 对 specs/007-knowledge-domain-generalization/spec.md 执行澄清，重点解决（≤5 问，答案回写 spec）：
Q1 domain_profiles 的变更治理：内置档案（se-project/generic）是否允许用户修改/删除？（建议：只读保护，自定义档案可增删改）
Q2 slug 冲突与稳定性规则：slug 全局唯一、创建后是否可改、与既有 alias/repo_path 寻址的优先级顺序？
Q3 domain_scope 的 type:name 限定引用是否首期必须，还是 slug 寻址足够（type:name 可后置）？
Q4 图三元组去 Project 依赖后的存量 graph_edge.project_id 列处置（保留列停止写入 vs 迁移删除）？
Q5 list_knowledge_domains 是否需要响应偏好参数（如按 domain_key 过滤），还是首期全量返回？
```

## 7.3 Plan

```text
/speckit-plan 为 specs/007-knowledge-domain-generalization 执行实现规划。技术上下文要点：Python 3.12 / FastAPI / SQLAlchemy async / FastMCP（签名即 schema，参数扩展注意 anyOf 约束需入口显式校验补位）；新表 domain_profiles + knowledge_scopes.domain_key 迁移（alembic）；统一引用解析器改造点 retrieval_service.py:432-529（双参数并集 + slug/type:name）；三处残留修复点位见 spec 输入段；契约 schema 变更集（mcp-search-input anyOf 放宽 required、错误码枚举扩展、新 list-domains 契约、common.schema.json 知识域引用定义）。Constitution Check 以 v1.3.0 为准（先跑 /speckit-constitution 完成 v1.3.0 修订）。research.md 必须覆盖：双参数并集解析的边界（空串/重复/混合新旧引用）、slug 唯一性约束实现、graph_edge project_id 列处置决策、se-project 档案与 1.0 行为等价性的验证口径、005 agentic 数据集回归闸口。
```

## 7.4 Checklist

```text
/speckit-checklist 基于 specs/007-knowledge-domain-generalization 的 spec/plan 生成评审检查清单。必须包含类别：宪法合规（v1.3.0 十一原则 + 五硬约束，特别是 XI 领域中立与 I 的双参数显式作用域）、双参数兼容性（旧客户端逐字节不变的证据性判据）、三处残留修复的行为验证判据、list_knowledge_domains 无知识内容泄露判据、隔离测试（跨域串库=0 的多域场景）、既有全集无回归判据、契约 schema 合法率 100%。
```

## 7.5 Tasks

```text
/speckit-tasks 基于 specs/007-knowledge-domain-generalization 的 spec/plan/data-model/contracts 生成 tasks.md。TDD 先红后绿；Phase 结构建议：Phase 1 宪法与迁移基座（domain_profiles 表 + domain_key 列 + 内置档案种子）→ Phase 2 引用解析泛化（统一解析器双参数并集 + slug 寻址 + 三处残留修复，每处残留一个独立任务并附行为验证测试）→ Phase 3 MCP 契约扩展（search/get_evidence 签名 + 错误码双轨 + list_knowledge_domains 新工具）→ Phase 4 管理面与前端（域档案 CRUD + scope 域属性展示）→ Phase 5 无回归与验收（既有全集重跑 + 硬指标 + quickstart）。每个任务映射 FR/US；含隔离与目标宿主测试。
```

## 7.6 Analyze

```text
/speckit-analyze 对 specs/007-knowledge-domain-generalization 执行 spec/plan/tasks 三工件一致性与宪法合规分析（v1.3.0：重点核验 XI 领域中立——新代码路径不得硬编码任何领域词；I 的双参数显式作用域语义在 spec FR、plan 契约、tasks 测试三处口径一致；五硬约束的验证任务齐全）。
```

## 7.7 Implement

```text
/speckit-implement 执行 specs/007-knowledge-domain-generalization/tasks.md 全部任务。纪律：TDD、每任务/逻辑组后 commit（信息前缀 "007 Txxx"）、checklist 复选框只读不改、宪法 v1.3.0 硬约束任何时刻不得违反、旧客户端兼容性测试（仅 project_scope 路径）必须先于新参数测试落地。
```

## 7.8 Converge

```text
/speckit-converge 以 specs/007-knowledge-domain-generalization 的 spec/plan/tasks 为准评估代码库，把残余缺口（含宪法 v1.3.0 措辞一致性、三处残留修复的回归测试盲区、list_knowledge_domains 的 MCP acceptance 测试）追加为新任务并执行至收敛。
```

---

# Feature 008：universal-ingestion-channel（通用摄入通道）

## 8.1 Specify

```text
/speckit-specify 通用摄入通道：FormatHandler 注册表收敛四处 if/elif 分发（api/knowledge_sources.py:305-351 _detect_format、services/ingestion_service.py:582-631 _parse_content、parsers/text_extractor.py:16 BINARY_FORMATS、ingestion_service.py:833-842 图提取器分发）为单一注册表（条目声明 format 名/扩展名集/tier native|converter/binary 声明/解析器工厂或转换器规格/可选图提取器挂钩/定位前缀，错误消息由注册表生成）；新增转换层：可插拔转换器接口 + markitdown 适配器（微软 markitdown，Apache-2.0），任意通用格式转 Markdown IR 后经凭据脱敏再由 MarkdownParser 切片（通用 chunk_type：heading/paragraph/list/table），原生 8 解析器冻结不动、存量格式零迁移；首批格式 9 种：html/txt/csv/json/yaml/xml/xlsx/pptx/eml（txt 为极轻量原生处理器空行分段，其余走转换层）；DB CHECK 放宽：knowledge_sources.format 与 chunks.chunk_type 与 retrieval_runs.format（String(8)→String(32)）改为宽模式约束 + 应用层注册表校验，chunk_type 两级词表（L1 通用闭合集 section/heading/paragraph/list/table + L2 命名空间扩展 ^域:类型$，存量 18 值遗留合法）；证据定位前缀规范（sheet:/path:/msg: 新增，存量 page:/标题路径/符号路径沿用）；前端 accept 与文案及 types 泛化。范围依据：2.0 蓝图 §1.2/§3.3/§3.4/§3.5/§5-008/ADR-4/ADR-5/ADR-6，1.0 蓝图 §7/§8。硬性约束：显式知识域引用；跨域串库为零；Schema 合法率与来源可定位率 100%（转换层格式的定位为转换后表示的标题路径粒度，须在契约中显式声明）；凭据脱敏顺序不变（转文本之后切片之前）；宪法 V 数据与控制分离对转换产物同样生效。对照评测：003 格式扩展范式沿用——每新格式 ≥2 条评测查询（≥1 自然语言 + ≥1 结构定位，如 sheet:SheetName/path:/json/key）加入固定评测集；003 既有格式集无回归；转换层契约测试固化 markitdown 行为（版本锁定）。不重复 003 已交付的 8 格式原生解析。输入材料：001–007 代码、docs/通用RAG演进蓝图.md、markitdown 官方文档。
```

## 8.2 Clarify

```text
/speckit-clarify 对 specs/008-universal-ingestion-channel/spec.md 执行澄清，重点解决：
Q1 markitdown 依赖形态：主依赖还是可选 extra（pip install markitdown[all] vs 按格式 extras）？转换器不可用时上传行为（显式失败 vs 拒收该格式）？
Q2 CSV 大文件策略：行数上限/行窗口切片（如每 50 行一个 table chunk）还是转换层整表单 chunk？空数据集（0 行）沿用 "No chunks produced" 失败还是允许空源？
Q3 .json/.yaml 通用化后与 OpenAPI 嗅探的关系：先嗅探 OpenAPI 再回落通用 json/yaml，还是按域档案声明？
Q4 通用 json/yaml/xml 的切片粒度：顶层键作为标题路径（path:/key）还是整文件单 chunk？
Q5 .eml 解析走 markitdown 还是 Python 标准库 email 适配器（附件忽略/内联如何处理）？
```

## 8.3 Plan

```text
/speckit-plan 为 specs/008-universal-ingestion-channel 执行实现规划。技术上下文：markitdown 版本锁定与可插拔转换器接口设计（pandoc/tika 可替换）；注册表模块布局（parsers/registry.py + parsers/converter.py + txt_parser.py）；四处分发点的委托化改造顺序与回退安全（注册表初始化失败 = 启动失败，不静默回落）；宽模式 CHECK 的迁移脚本（沿用 a1b2c3d4e5f6 drop/add 模式）；retrieval_runs.format String(32) 扩容迁移；Qdrant payload 不变（chunk_type 值域放宽后 payload 兼容性确认）；转换层的 ProcessingRun 阶段记录与失败重试语义（与原生层一致）。research.md 必须覆盖：markitdown 各格式输出形态实证（每格式一个样例转换产物附录）、定位前缀规范全表、CSV/JSON 切片粒度决策、转换失败/空产物/超限文件的边界语义。
```

## 8.4 Checklist

```text
/speckit-checklist 基于 specs/008-universal-ingestion-channel 生成评审检查清单。必须包含类别：注册表完备性（四处分发点全部收敛的证据判据、错误消息单一事实源）、转换层安全（宪法 V：转换产物仍经脱敏与注入检测、不可信数据边界不变）、格式接受性（域档案 supported_formats 与注册表一致性）、定位规范（每新格式 position_path 前缀符合规范表）、DB 约束（宽模式 + 应用层校验双层、String 扩容）、评测义务（9 格式 × ≥2 条、003 回归、硬指标）、前端（accept/types 同步注册表）。
```

## 8.5 Tasks

```text
/speckit-tasks 基于 specs/008-universal-ingestion-channel 生成 tasks.md。Phase 建议：Phase 1 注册表基座（FormatHandler + 四处分发点收敛 + 错误消息重构，行为等价测试先行）→ Phase 2 转换层基座（转换器接口 + markitdown 适配器 + 脱敏顺序接线 + 契约测试）→ Phase 3 DB 约束放宽迁移（宽模式 + String(32) + 存量 18 值遗留合法验证）→ Phase 4 首批格式落地（9 格式按风险从低到高分批：txt→csv→html→json/yaml/xml→xlsx→pptx→eml，每格式解析测试 + ≥2 评测查询）→ Phase 5 前端与验收（accept/types + 003 回归 + 硬指标 + quickstart）。
```

## 8.6 Analyze

```text
/speckit-analyze 对 specs/008-universal-ingestion-channel 执行一致性分析。重点核验：注册表是唯一分发点（grep 验证无残留 if/elif 格式分支）；转换层与原生层在脱敏/版本/能力门控/重试语义上的对称性；chunk_type 两级词表与域档案校验的接线；评测集只增不破坏既有条目（eval/README 固定集纪律）。
```

## 8.7 Implement

```text
/speckit-implement 执行 specs/008-universal-ingestion-channel/tasks.md 全部任务。纪律：TDD、commit 前缀 "008 Txxx"、checklist 只读、转换层契约测试先于格式批量接入、markitdown 依赖锁定版本、每格式验收批次独立（照 003 批次纪律）。
```

## 8.8 Converge

```text
/speckit-converge 以 specs/008-universal-ingestion-channel 的 spec/plan/tasks 为准评估代码库，重点排查：残留的硬编码格式分支、错误消息漂移、转换层异常路径（超时/毒文件/空产物）的降级语义、评测查询覆盖缺口，追加任务执行至收敛。
```

---

# Feature 009：domain-neutral-retrieval（检索编排域中立化）

## 9.1 Specify

```text
/speckit-specify 检索编排域中立化：query_planner 基础系统提示词重写为域中立（信号选择规则以标识符/定义/关系抽象表述，SE 举例与关系词表全部移入 se-project 域档案 prompt_overrides，运行时按请求 scope 域档案注入；se-project 档案下规划行为与 1.0 一致，用 005 数据集回归验证）；relation_directions 枚举动态化（由域档案 graph_relations 词表生成，query_planner.py:25-26,44-48,97-102 的硬编码 4 值词表移入 se-project 档案，无图档案返回空词表）；task_context 契约泛化（current_file/current_symbol/work_phase 保留为编码域约定字段兼容存量客户端，新增可选自由字符串 activity 供任意域描述当前工作，schema 描述整体域中立化）；SourcePosition 契约描述更新（common.schema.json:34-37 以定位前缀规范表替换 Java 符号单例描述，get_evidence parent_context 措辞域中立化）；gaps 与错误文案去 project 措辞（retrieval_service.py:947-949 等）；evidence_analyst/context_orchestrator/injection_detector 确认已中立并回归。范围依据：2.0 蓝图 §3.7/§3.5/§5-009，1.0 蓝图 §11/§15。硬性约束：显式知识域引用；跨域串库为零；Schema 合法率与来源可定位率 100%；提示注入防护边界不变（域档案注入内容属可信配置、与证据内容结构隔离，宪法 V/1.0 §15）。对照评测：005 agentic 数据集（44 条）与确定性评测集（37 条）无回归（se-project 档案提示词等价性闸口）；无新增检索质量对照义务（编排泛化沿用 006 工程特例范式）。不重复 007 已交付的域档案基础设施与 008 已交付的摄入通道。输入材料：001–008 代码、005 agentic_comparison_report.json、docs/通用RAG演进蓝图.md。
```

## 9.2 Clarify

```text
/speckit-clarify 对 specs/009-domain-neutral-retrieval/spec.md 执行澄清，重点解决：
Q1 多 scope 跨域请求的提示词注入策略：取哪（几）个域档案的 prompt_overrides（去重并集/首个/拒绝混合）？
Q2 activity 字段与 task_context.additional_context 的语义区分（活动描述 vs 附加上下文）？
Q3 planner 提示词等价性的验证口径：005 数据集逐条 sub_problems/signals 输出比对，还是终态指标容差比对？
Q4 动态 relation_directions 为空词表时 planner 的 NODE_SCHEMA 行为（省略字段 vs 显式空数组）？
```

## 9.3 Plan

```text
/speckit-plan 为 specs/009-domain-neutral-retrieval 执行实现规划。技术上下文：query_planner.py 提示词模板化改造（基础域中立模板 + 档案注入槽位）；NODE_SCHEMA 动态枚举的实现路径（FastJSONSchema 动态构造 vs 校验分层）；llm_client/能力路由不涉及领域假设确认；契约 schema 变更（mcp-search-input.activity、common.schema.json SourcePosition 描述表）；回归闸口接线（005 agentic 44 条 + 确定性 37 条进 quickstart）。research.md 必须覆盖：提示词注入的提示注入防护分析（档案内容如何与不可信证据隔离）、多域并集注入的边界、等价性验证口径决议。
```

## 9.4 Checklist

```text
/speckit-checklist 基于 specs/009-domain-neutral-retrieval 生成评审检查清单。必须包含类别：域中立完备性（grep planner 提示词无 SE 专属词残留于基础模板）、档案注入安全（注入内容来源仅限域档案可信配置）、se-project 等价性（005/确定性双回归判据）、契约兼容（旧 task_context 客户端不变、schema 枚举只增不删）、文案中立化（gaps/错误消息全量复查）。
```

## 9.5 Tasks

```text
/speckit-tasks 基于 specs/009-domain-neutral-retrieval 生成 tasks.md。Phase 建议：Phase 1 提示词模板化（基础域中立模板 + se-project 档案注入 + 等价性测试先行）→ Phase 2 动态词表（relation_directions 接域档案 + 空词表行为 + 005 回归）→ Phase 3 契约与文案（activity 字段 + SourcePosition 描述表 + gaps/错误文案中立化 + schema 校验）→ Phase 4 验收（双回归闸口 + 硬指标 + quickstart）。
```

## 9.6 Analyze

```text
/speckit-analyze 对 specs/009-domain-neutral-retrieval 执行一致性分析。重点核验：宪法 VI（LLM 判断不拥有控制权——提示词重构不得改变确定性控制器边界）与 XI（基础编排路径无领域硬编码）；契约变更的非破坏性；等价性闸口在 spec/plan/tasks 三处口径一致。
```

## 9.7 Implement

```text
/speckit-implement 执行 specs/009-domain-neutral-retrieval/tasks.md 全部任务。纪律：TDD、commit 前缀 "009 Txxx"、checklist 只读、提示词重构必须先落地 se-project 等价性测试再动基础模板、双回归闸口不过不得合并默认路径。
```

## 9.8 Converge

```text
/speckit-converge 以 specs/009-domain-neutral-retrieval 的 spec/plan/tasks 为准评估代码库，重点排查：基础模板 SE 词残留、其他 Agent（evidence_analyst 等）与 orchestration 文案的 project 措辞遗漏、等价性回归的容差边界，追加任务执行至收敛。
```

---

# Feature 010：graph-relation-registry（图关系注册表）

## 10.1 Specify

```text
/speckit-specify 图关系注册表：GraphExtractor 插件接口正式抽象（extract(source, chunks, scope) -> list[edge] 收编现 duck-typing 契约，注册表按 format + domain_key 发现提取器）；java_call_graph 与 ddl_fk 迁移至插件接口（行为不变，004 数据集回归）；relation_type CHECK 放宽（graph/models.py:45-49 枚举改宽模式 + 应用层按域档案 graph_relations 词表校验，other_hard 逃生口退役）；文档交叉引用提取器作为非 SE 验证提取器（Markdown 内部链接 [x](#anchor)/相对链接、法规条文"依据第 X 条/参见 X.Y"引用 → references/referenced_by 硬边，产 parse_evidence，服务 legal 域档案）；图路径对 public/generic 域可用（007 已拆 Project 依赖，010 验证端到端）；graph_ready 门控语义不变（硬边 > 0 方可声明，无图档案自然不可声明）；软关系推断框架与格式无关确认回归。范围依据：2.0 蓝图 §3.8/§5-010/ADR-8，1.0 蓝图 §10/§8.2。硬性约束：显式知识域引用；跨域串库为零（图边以 knowledge_scope_id 为唯一隔离键）；Schema 合法率与来源可定位率 100%；硬/软关系区分不变（宪法 III），提取器必须产 parse_evidence。对照评测：004 图增强评测集（37 条，graph_enhanced_comparison_report.json）无回归；新增交叉引用受益子集 ≥6 条（法律域语料，含中文条文引用），结构性受益 ≥3%（沿用 004 SC-001 闸口）证明插件抽象与非 SE 图能力成立。不重复 004 已交付的 Java/DDL 硬关系与软关系推断、007 已交付的图三元组去 Project 依赖。输入材料：001–009 代码、eval/graph_enhanced_comparison_report.json、docs/通用RAG演进蓝图.md。
```

## 10.2 Clarify

```text
/speckit-clarify 对 specs/010-graph-relation-registry/spec.md 执行澄清，重点解决：
Q1 交叉引用提取器的 chunk 定位语义：引用边如何锚定到 chunk（position_path 前缀匹配 vs 全文正则 + 行号区间归属）？
Q2 references/referenced_by 双向边的生成规则（何时产出反向边，与 calls/called_by 的对称性约定）？
Q3 存量 graph_edge 数据的 relation_type 迁移：旧 5 值保持原值（遗留合法）还是规范化入词表命名空间？
Q4 legal 域档案是否在本 Feature 落地（为交叉引用提取器提供挂载域），还是仅用 se-project+generic 语料验证抽象？
```

## 10.3 Plan

```text
/speckit-plan 为 specs/010-graph-relation-registry 执行实现规划。技术上下文：graph/extractors/base.py 插件接口（含 parse_evidence 契约与失败降级语义——失败记 reason 产 0 边不断链，沿用 ingestion_service.py:856-861）；注册表与域档案 graph_relations 词表的联动（007 基础设施复用）；CHECK 放宽迁移（沿用 drop/add 模式）；图扩展查询侧的词表过滤（expansion.py 兼容性）；交叉引用正则的中英文规则集。research.md 必须覆盖：交叉引用提取的查准/查全权衡（防误报——普通"第 X 条"叙述 vs 真引用）、双向边对称性决策、004 回归闸口口径（SC-001 ≥3% 在新子集上的适配）。
```

## 10.4 Checklist

```text
/speckit-checklist 基于 specs/010-graph-relation-registry 生成评审检查清单。必须包含类别：插件接口完备性（新提取器零改动 ingestion 分发即可接入的判据）、行为等价（java/ddl 迁移后 004 数据集逐条回归）、硬边可信度（parse_evidence 必填、误报控制）、隔离（跨域图边泄漏=0 多域场景）、词表治理（relation_type 值域=注册表 ∪ 遗留 5 值）、受益闸口（新子集 ≥3% 判据）。
```

## 10.5 Tasks

```text
/speckit-tasks 基于 specs/010-graph-relation-registry 生成 tasks.md。Phase 建议：Phase 1 插件接口与迁移（base.py + java/ddl 迁移 + 004 回归先行）→ Phase 2 词表与约束（relation_type 放宽迁移 + 域档案联动 + 查询侧过滤）→ Phase 3 交叉引用提取器（规则集 + 单测 + 防误报测试）→ Phase 4 受益验证（法律语料受益子集 ≥6 条 + ≥3% 闸口 + public/generic 域图路径端到端）→ Phase 5 验收（004 全量回归 + 硬指标 + quickstart）。
```

## 10.6 Analyze

```text
/speckit-analyze 对 specs/010-graph-relation-registry 执行一致性分析。重点核验：宪法 III（软硬关系区分不被词表开放稀释）与硬约束跨域图边隔离；提取器注册与域档案词表两处口径一致；004 既有闸口语义在新结构下的等价表述。
```

## 10.7 Implement

```text
/speckit-implement 执行 specs/010-graph-relation-registry/tasks.md 全部任务。纪律：TDD、commit 前缀 "010 Txxx"、checklist 只读、java/ddl 迁移的行为等价测试必须先红后绿、交叉引用提取器误报用例与正常用例同批落地。
```

## 10.8 Converge

```text
/speckit-converge 以 specs/010-graph-relation-registry 的 spec/plan/tasks 为准评估代码库，重点排查：图路径残留 Project 假设、词表校验遗漏路径（直接 ORM 写入绕过注册表）、受益子集闸口报告完整性，追加任务执行至收敛。
```

---

# Feature 011：generic-domain-evaluation（通用域评测与多域验收）

## 11.1 Specify

```text
/speckit-specify 通用域评测与多域验收：建设两个验证域的语料与固定评测集——个人/团队通用知识库域（markdown/txt/html/csv 格式语料 + personal/generic 域档案）与法律合规域（合同/法规 Word/PDF 语料 + legal 域档案，条文结构检索与交叉引用受益验证），各 ≥10 条评测查询（AI 生成 + 人工审核入库，沿用固定集纪律，含中文）；产出域基线报告（generic_domain_baseline_report.json 与 legal_domain_baseline_report.json：dense/hybrid 双路径 Recall@K/MRR/nDCG + P50/P95 延迟，沿用 001/002 方法论与 run_eval/run_comparison 运行器）；多域端到端验收（MCP 双工具以 domain_scope/slug 寻址跨个人域+法律域+SE 项目域混合检索；list_knowledge_domains 发现流程；硬指标三件套全量验证：跨域串库=0/Schema 合法率 100%/定位率 100%）；既有全集回归（001/002/003/004/005/006 全部报告按各自口径重跑确认无回归）；文档债清理（docs/1.0-iteration-roadmap.md 更新至 2.0 状态、根 README 纠正"尚无业务实现代码"等过时陈述、001–006 spec.md Status 更新）；2.0 版本定稿（演进目标逐项核销）。范围依据：2.0 蓝图 §1.3/§6/§7-011/§9，1.0 蓝图 §24。硬性约束：显式知识域引用；跨域串库为零；Schema 合法率与来源可定位率 100%；评测集一经入库不得破坏既有条目。对照评测：本 Feature 即对照基线的建立者——两个域基线报告成为后续通用域优化的对照锚点。不重复 001–010 已实现能力（仅新增语料/评测集/报告/文档与验收，无新检索路径）。输入材料：001–010 代码与报告、docs/通用RAG演进蓝图.md、目标域样例语料（用户提供或构造）。
```

## 11.2 Clarify

```text
/speckit-clarify 对 specs/011-generic-domain-evaluation/spec.md 执行澄清，重点解决：
Q1 语料来源与规模：两个验证域各需多少知识源（建议每域 5–15 个文件、跨 2–3 个 scope）？法律语料用公开法规/标准合同模板还是用户提供？
Q2 评测查询生成方式：沿用 generate_dataset.py 启发式（扩展通用 chunk_type 分支）还是引入 LLM 生成 + 人工审核？
Q3 域基线的验收水位：仅建立基线不作门槛，还是设最低可接受水位（如 MRR ≥0.7）？
Q4 legal 域档案（chunk_type_extensions/legal:article、graph_relations/references）在本 Feature 落地还是仅用 generic 档案？
```

## 11.3 Plan

```text
/speckit-plan 为 specs/011-generic-domain-evaluation 执行实现规划。技术上下文：eval 运行器扩展（run_eval/run_comparison 支持域基线报告产物与 schema 契约）；评测数据集字段沿用 query/project_scope 或新增 domain_scope 寻址形态的决议；语料入库走 007–010 全链路（域档案 + 转换层 + 交叉引用）；报告契约 schema 新增两份。research.md 必须覆盖：两域语料清单与预期受益点（法律域交叉引用/条文定位；个人域混合格式检索）、查询生成方法决议、基线水位的非约束性说明（宪法 X 对照义务）。
```

## 11.4 Checklist

```text
/speckit-checklist 基于 specs/011-generic-domain-evaluation 生成评审检查清单。必须包含类别：评测集质量（查询-证据对应人工审核记录、固定集纪律、中文覆盖）、硬指标全量验证（三件套在混合域验收集上的测量记录）、多域端到端（domain_scope/slug 寻址、list_knowledge_domains 流程、writer/reader 双形态冒烟）、全集回归（各报告按各自口径重跑的记录）、文档债核销（roadmap/README/spec Status 逐项）。
```

## 11.5 Tasks

```text
/speckit-tasks 基于 specs/011-generic-domain-evaluation 生成 tasks.md。Phase 建议：Phase 1 语料与档案（两域语料构造/入库 + personal/legal 域档案落地）→ Phase 2 评测集与运行器（查询生成 + 人工审核入库 + run_eval 域基线扩展 + 两份基线报告）→ Phase 3 多域端到端验收（混合域检索/发现流程/硬指标三件套/双形态冒烟）→ Phase 4 全集回归与文档债（既有报告重跑 + roadmap/README/spec 更新）→ Phase 5 2.0 定稿（演进目标逐项核销 + 总结）。
```

## 11.6 Analyze

```text
/speckit-analyze 对 specs/011-generic-domain-evaluation 执行一致性分析。重点核验：宪法 X（基线建立与对照义务的表述一致——本 Feature 建立锚点而非宣称改进）；评测集不破坏既有条目；硬指标验证任务覆盖全部三件套与双实例形态；文档债清单与实际过时陈述一一对应。
```

## 11.7 Implement

```text
/speckit-implement 执行 specs/011-generic-domain-evaluation/tasks.md 全部任务。纪律：TDD（运行器扩展部分）、commit 前缀 "011 Txxx"、checklist 只读、评测集入库前必须完成人工审核记录、基线报告一经产出不得覆盖重写（沿用历史产物勿覆盖纪律）。
```

## 11.8 Converge

```text
/speckit-converge 以 specs/011-generic-domain-evaluation 的 spec/plan/tasks 为准评估代码库，重点排查：硬指标测量的盲区（如 get_evidence 在混合域下的定位率）、文档残留过时陈述、2.0 演进目标未核销项，追加任务执行至收敛；输出 2.0 定稿结论。
```

---

# 附：全局执行注意事项（所有 Feature 通用）

1. **宪法版本**：007 的 /speckit-constitution 完成 v1.3.0 修订并批准之前，后续命令一律以现行宪法为准；修订后所有 plan/analyze 以 v1.3.0 十一原则 + 五硬约束核验。
2. **错误码兼容**：任何涉及 MCP 错误码的任务，枚举只增不删；旧客户端可见行为逐字节不变是 007/009 的硬验收。
3. **评测纪律**：固定评测集只增不破坏（eval/README 约定）；基线报告是历史产物，重跑产出新报告或显式版本化，不覆盖。
4. **提交规范**：commit 信息前缀 "00N Txxx"（沿用 001–006 习惯）；每 Feature 收敛时以 /speckit-converge 的追加任务清零为完成标志。
5. **文档同步**：每 Feature 交付后同步更新 docs/1.0-iteration-roadmap.md（或由 011 统一更新）；蓝图层面变更走宪法修订或 2.0 蓝图新章节，不得隐藏在 Feature 内。
6. **依赖引入**：markitdown（008）是唯一预期新第三方依赖；版本锁定 + 契约测试固化，引入理由与替换路径记入 research.md。
