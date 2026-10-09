# Feature Specification: Generic Domain Evaluation & Multi-Domain Acceptance（通用域评测与多域验收）

**Feature Branch**: `011-generic-domain-evaluation`

**Created**: 2026-09-07

**Status**: Delivered

**Input**: User description: "通用域评测与多域验收：建设两个验证域的语料与固定评测集——个人/团队通用知识库域（markdown/txt/html/csv 格式语料 + personal/generic 域档案）与法律合规域（合同/法规 Word/PDF 语料 + legal 域档案，条文结构检索与交叉引用受益验证），各 ≥10 条评测查询（AI 生成 + 人工审核入库，沿用固定集纪律，含中文）；产出域基线报告（generic_domain_baseline_report.json 与 legal_domain_baseline_report.json：dense/hybrid 双路径 Recall@K/MRR/nDCG + P50/P95 延迟，沿用 001/002 方法论与 run_eval/run_comparison 运行器）；多域端到端验收（MCP 双工具以 domain_scope/slug 寻址跨个人域+法律域+SE 项目域混合检索；list_knowledge_domains 发现流程；硬指标三件套全量验证：跨域串库=0/Schema 合法率 100%/定位率 100%）；既有全集回归（001/002/003/004/005/006 全部报告按各自口径重跑确认无回归）；文档债清理（docs/1.0-iteration-roadmap.md 更新至 2.0 状态、根 README 纠正"尚无业务实现代码"等过时陈述、001–006 spec.md Status 更新）；2.0 版本定稿（演进目标逐项核销）。范围依据：2.0 蓝图 §1.3/§6/§7-011/§9，1.0 蓝图 §24。硬性约束：显式知识域引用；跨域串库为零；Schema 合法率与来源可定位率 100%；评测集一经入库不得破坏既有条目。对照评测：本 Feature 即对照基线的建立者——两个域基线报告成为后续通用域优化的对照锚点。不重复 001–010 已实现能力（仅新增语料/评测集/报告/文档与验收，无新检索路径）。输入材料：001–010 代码与报告、docs/通用RAG演进蓝图.md、目标域样例语料（用户提供或构造）。"

## Scope Basis

2.0 蓝图《通用RAG演进蓝图.md》§1.3（演进目标 1——外部 Agent 以 domain_scope 通用知识域引用检索任意知识域；目标 4——两个验证域（个人/团队通用知识库、法律合规）各自建立 ≥10 条固定评测集并产出域基线报告、1.0 全部既有评测集无回归；目标 5——硬性验收指标在混合域验收集上全部成立）、§6（评测策略：011 域基线——个人知识库域与法律域各 ≥10 条、AI 生成 + 人工审核入库、沿用固定集纪律，产出 dense/hybrid 域基线报告作为后续通用域优化的对照锚点；硬指标三件套跨域语义；无回归义务按各 Feature 既有口径重跑、非延迟指标 1% 相对容差内一致）、§7-011（Feature 划分：generic-domain-evaluation——两验证域语料与评测集、域基线报告、多域端到端验收、文档债清理、2.0 定稿，30–40 任务规模，对照义务 = 域基线建立 + 硬指标全量 + 全集回归）、§9（演进触发条件：定稿后新演进仍须触发条件门槛；蓝图批准即冻结为目标架构基线——定稿核销为独立工件、不隐藏在蓝图内）；1.0 蓝图《蓝图.md》§24（评估策略：§24.1 离线检索评估指标——Recall@K/MRR/nDCG；§24.2 硬性验收指标三件套；§24.3 基线对照指标——基线建立后，后续 Feature 进入 plan.md 前必须在 research.md 中声明相对基线目标，增强只有在固定评测集上证明收益且未违反硬性指标时才进入默认检索路径）。支撑：宪法 v1.3.0（原则 X 评测驱动优化——真实领域语料含软件工程域与通用域、增强须对照固定基线证明收益；原则 IV 来源可定位；原则 I 显式知识域引用；原则 XI 领域中立；五硬约束——跨域泄漏 = 0 / 无引用拒检 / Schema 合法率 100% / 定位率 100%）。**前置已满足**：007 双轴知识域 + 域档案注册表 + domain_scope/slug 寻址 + list_knowledge_domains 已交付；008 FormatHandler 注册表 + markitdown 转换层 + 首批 9 通用格式已交付；009 域中立检索编排已交付；010 GraphExtractor 插件注册表 + cross_reference 提取器 + legal 内置域档案已交付（空图词表，R11 声明式补救——交叉引用受益闸口在 010 初步语料上未达标：MRR −11.1% / nDCG −6.3%，报告如实记录）；001–006 评测全集与历史报告在库。

## 对照评测声明（本 Feature 即对照基线的建立者）

011 在对照评测体系中的角色与 001–010 相反：**它不宣称任何检索质量改进，而是为通用域建立对照基线本身**（宪法 X / 1.0 §24.3 基线对照纪律向通用域的延伸）。同时作为 2.0 收官 Feature，它承担既有全集的无回归义务与硬指标三件套的全量终验。

### 域基线建立义务（对照锚点）

- `eval/generic_domain_baseline_report.json`：个人/团队通用知识库域（personal + generic 档案 scope、markdown/txt/html/csv 语料）的 dense/hybrid 双路径 Recall@K / MRR / nDCG + P50/P95 延迟基线（001/002 方法论）。
- `eval/legal_domain_baseline_report.json`：法律合规域（legal 档案、Word/PDF 合同法规 + markdown 交叉引用语料）的同款双路径基线，附交叉引用受益对照测量（Q1=A 决议：沿用 010 FR-030 双分支闸口，见 FR-011）。
- 两份报告一经产出即为**非约束性对照锚点**：不含 enters_default_path 类路径决策字段（检索路径决策闸口已由 002 混合 / 004 图增强 / 005 agentic 完成）；后续通用域优化 Feature 进入 plan.md 前的 research.md 必须相对本基线声明目标（1.0 §24.3 纪律延伸至通用域）。

### 无回归义务（001–006 既有全集，按各自口径重跑）

| Feature | 报告 | 回归口径 |
|---------|------|----------|
| 001 | `baseline_report.json` | Dense 基线 11 条 |
| 002 | `hybrid_comparison_report.json` | 混合对照 18 条（`--limit 18`） |
| 003 | `regression_report.json` / `format_expansion_report.json` | 格式集 37 条 + 逐格式对照 |
| 004 | `graph_enhanced_comparison_report.json`（010 先例 `--limit 37`） | 图集 37 条（per_query 索引 0–36） |
| 005 | `agentic_comparison_report.json` | 组合数据集全量（`eval_dataset.json` + `agentic_eval_dataset.json`，当前 56 + 7 = 63 条） |
| 006 | `instance_form_smoke_report.json` | writer/reader 双形态各 11 条冒烟 |

非延迟指标（Recall@K/MRR/nDCG）在 1% 相对容差内与历史报告一致（沿用 006/007 SC-009 无回归判定范式）；延迟指标环境敏感、仅记录。重跑产物 MUST NOT 覆盖历史报告（历史产物勿覆盖纪律）。011 对 legal 档案的扩展与法律域语料的新增 MUST NOT 影响 001–010 任何既有口径；010 交叉引用对照口径（`cross_reference_comparison_report.json`，其 runner 经注册表显式触发提取器）显式复跑确认行为不变。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 两验证域语料与域档案建设 (Priority: P1)

用户（系统负责人/检索工程师）为两个验证域建设评测语料并落地配套域档案：个人/团队通用知识库域——个人知识库 scope（public + personal 档案，011 落地的第四内置档案）与团队共享知识库 scope（public + generic 档案），语料覆盖 markdown/txt/html/csv 四格式；法律合规域——public + legal scope，合同/法规 Word/PDF 语料承载条文结构检索，markdown 语料承载交叉引用形态（沿用/扩充 010 虚构法规语料），legal 内置档案的 supported_formats 扩展至 word/pdf。全部语料经 007–010 全链路入库（域档案格式校验、FormatHandler 注册表分发、转换层/原生切片、凭据脱敏、版本发布），成为固定评测集的物理基础。

**Why this priority**: 语料与档案是 011 一切交付物的地基——评测集锚定语料、基线报告锚定评测集、多域验收锚定 scope 集合；蓝图 §1.3 目标 4 的"两个验证域"与 §3.1 的"legal/personal 等域档案由 011 评测语料建设时落地"均以此为承载。

**Independent Test**: 构造/接入两域语料并完成入库与版本发布，验证：个人域四格式全部可上传、可切片、可检索、证据可定位；法律域 Word 语料以标题路径定位（含"第X条"中文标题形态）、PDF 语料以 page:N §X.Y 数字编号路径定位；list_knowledge_domains 正确列出各 scope 的 domain_key（personal/generic/legal）与能力摘要；内置档案修改/删除被拒。

**Acceptance Scenarios**:

1. **Given** personal 内置域档案已落地（第四内置档案，is_builtin 只读保护，声明为纯配置数据），**When** 创建个人知识库 scope（public + personal）与团队共享 scope（public + generic）并上传 markdown/txt/html/csv 语料，**Then** 四格式全部经 008 注册表分发完成上传、结构切片（转换层/txt 原生路径）、脱敏与嵌入，发布知识版本，证据可定位。
2. **Given** legal 内置档案 supported_formats 已扩展至 markdown/word/pdf，**When** 上传合同/法规 Word/PDF 语料至 public + legal 域，**Then** 入库成功，Word 证据定位为标题路径（Word 标题结构 → # 标题切片），PDF 证据定位为 page:N §编号路径（数字编号标题形态）。
3. **Given** 两域语料入库并发布，**When** 调用 list_knowledge_domains，**Then** 个人/团队/法律各 scope 以真实 domain_key 与能力摘要列出，返回条目仅含域元数据、无任何知识内容（沿用 007 口径）。
4. **Given** 内置档案 personal/legal/se-project/generic，**When** 管理面尝试修改或删除内置档案，**Then** 被拒绝（007 内置只读保护）。
5. **Given** 任一语料文件解析/转换失败（毒文件/空产物），**When** 入库执行，**Then** fail-loud 记录失败原因并中断该源入库，不静默跳过导致评测锚点悬空（沿用 008 转换层失败语义）。

---

### User Story 2 - 两域固定评测集（各 ≥10 条，LLM 生成 + 人工审核入库） (Priority: P1)

为两个验证域各建一套固定评测集：查询由 LLM 生成、人工审核后入库（沿用固定集纪律与既有字段形态），每域 ≥10 条、含中文查询。个人/团队域集覆盖四格式的自然语言与结构定位查询（沿用 008 每格式 ≥2 条范式）；法律域集覆盖条文结构检索（Word/PDF 承载）与交叉引用受益查询（markdown 承载，沿用 010 SC-002 受益子集形态）。两套评测集为独立数据集文件，期望证据采用跨环境稳定的结构锚点，且一经入库不得破坏既有条目（含既有全部数据集文件零改动）。

**Why this priority**: 固定评测集是域基线报告的直接输入与"对照锚点"的本体（蓝图 §6）；没有固定集，基线不可重复、后续优化无从对照（宪法 X）。

**Independent Test**: 完成两域评测集的生成与人工审核入库，审计：条数（各 ≥10）、中文覆盖（每域 ≥2 条）、格式/结构覆盖（个人域四格式 × ≥2；法律域条文结构 ≥4 + 交叉引用受益 ≥6 含 ≥1 条中文条文引用查询）、独立文件、结构锚点期望、审核记录随库；再校验既有数据集文件（eval_dataset.json / agentic_eval_dataset.json / cross_reference_eval_dataset.json）逐字节不变。

**Acceptance Scenarios**:

1. **Given** 两域语料已入库发布，**When** 评测查询生成与人工审核执行，**Then** `eval/generic_domain_eval_dataset.json` 与 `eval/legal_domain_eval_dataset.json` 各 ≥10 条入库，每条含查询文本、知识域引用（domain_scope 寻址形态）、期望证据锚点、语言标记与人工审核记录（沿用 agentic 数据集 _meta.review_status 形态）。
2. **Given** 个人/团队域评测集，**When** 审计覆盖结构，**Then** markdown/txt/html/csv 每格式 ≥2 条（≥1 自然语言 + ≥1 结构定位，如 sheet:/path:/msg:/标题路径锚定查询），且含 ≥2 条中文查询。
3. **Given** 法律域评测集，**When** 审计覆盖结构，**Then** 条文结构检索子集 ≥4 条（Word/PDF 语料承载，含"第X条/X.Y 条款"类查询与 ≥2 条中文）+ 交叉引用受益子集 ≥6 条（markdown 语料承载，is_structural_benefit 标记，含 ≥1 条中文条文引用查询，可在 010 七条基础上扩充但为独立入库条目），总数 ≥10。
4. **Given** 既有全部固定评测集文件，**When** 新评测集入库，**Then** 既有文件逐字节不变（零破坏）；新条目仅入新数据集文件，MUST NOT 追加进 eval_dataset.json / agentic_eval_dataset.json（避免污染 001–006 各自回归口径，沿用 cross_reference_eval_dataset.json 先例）。
5. **Given** 评测集一经入库，**When** 后续任何变更发生，**Then** 既有条目逐条保持不变（字段结构只增不改不删）——"评测集一经入库不得破坏既有条目"约束同样约束 011 自身及后续 Feature。

---

### User Story 3 - 域基线报告（dense/hybrid 双路径） (Priority: P1)

以 001/002 方法论与 run_eval/run_comparison 运行器（最小扩展）对两域评测集运行 dense 与 hybrid 双路径评测，产出两份域基线报告：Recall@K / MRR / nDCG + P50/P95 延迟、逐查询明细、硬指标实测与可重复性检查（非延迟指标 1% 容差）。报告为非约束性对照锚点：不设最低水位门槛、不含路径决策字段；后续通用域优化以此为对照基线。

**Why this priority**: 域基线报告是 011 的核心交付物与"对照基线建立者"义务的载体（蓝图 §1.3 目标 4、§6）；两份契约 schema 使报告成为可校验的固定工件而非一次性数字。

**Independent Test**: 运行域基线评测（同会话 dense + hybrid 双臂，沿用 002 FR 同会话纪律），验证两份报告产出且 100% 通过各自新契约 schema 校验、指标与延迟字段齐全、可重复性检查通过；审计报告无 enters_default_path 类字段；报告一经产出不被覆盖重写。

**Acceptance Scenarios**:

1. **Given** 两域评测集与运行器扩展就绪，**When** 域基线评测运行（同会话先 dense 后 hybrid），**Then** 每域报告含双路径 Recall@K/MRR/nDCG、P50/P95 延迟、逐查询明细（查询、期望锚点、双路径排名/命中）与硬指标实测记录（串库/Schema/定位逐条测量）。
2. **Given** 两份域基线报告，**When** 契约校验执行，**Then** 100% 通过新增的两份域基线报告契约 schema；报告结构与既有对照报告 schema 同源（沿用其字段语义）。
3. **Given** 同一环境连续两次运行，**When** 可重复性检查执行，**Then** 非延迟指标在 1% 相对容差内一致（沿用 001 SC-009 范式）；延迟指标标注环境敏感、不进容差判定。
4. **Given** 域基线报告的角色约束，**When** 报告内容审计，**Then** 无 enters_default_path / 路径决策字段；dense 与 hybrid 的相对差仅作信息性记录；报告明确标注"非约束性对照锚点"语义。
5. **Given** 基线报告一经产出，**When** 后续重跑或对照发生，**Then** 历史报告文件不被覆盖（重跑产物写入新文件或附属对照记录，沿用历史产物勿覆盖纪律）。

---

### User Story 4 - 多域端到端验收与硬指标三件套全量验证 (Priority: P1)

在混合域环境（public + personal、public + generic、public + legal、project + se-project 并存）中以 MCP 客户端走完整闭环：list_knowledge_domains 发现知识域 → 以 domain_scope 三种形态（数字 scope ID / slug / type:name）寻址 → search_knowledge 混合检索 → get_evidence 展开证据。混合域验收集上硬指标三件套全量实测：跨域串库 = 0、MCP Schema 合法率 = 100%、来源可定位率 = 100%（含 Word 标题路径与 PDF page:N §编号前缀证据）；writer/reader 双实例形态各冒烟一轮。

**Why this priority**: 硬指标三件套是宪法硬约束与 2.0 蓝图 §1.3 目标 5 的终验（"在混合域验收集上全部成立"）；多域闭环是 domain_scope/slug/list_knowledge_domains 交付价值的首次全链路实证。

**Independent Test**: 以 DeepSeek Harness 为必过参考客户端执行闭环（发现 → 三形态寻址 → 检索 → 展开），对全部响应逐条实测三件套并落盘验收记录；无引用请求被拒、仅 project_scope 旧码不变、双参数混用并集正确（沿用 007 验收口径）；双形态冒烟按 006 单侧非回归判定。

**Acceptance Scenarios**:

1. **Given** 混合域环境（≥4 个活跃知识域，覆盖 project/public 结构轴与 personal/generic/legal/se-project 语义轴），**When** 以 list_knowledge_domains 为入口发现知识域，**Then** 全部活跃域以 ID/slug/名称/scope_type/domain_key/能力摘要列出，无任何知识内容泄露。
2. **Given** 发现返回的 slug 与 ID，**When** 分别以 domain_scope 三种形态（数字 ID / slug / type:name）经 search_knowledge 检索、get_evidence 展开证据，**Then** 三种形态均返回对应域证据并走通闭环，证据的 knowledge_scope_id/type 与请求域一致。
3. **Given** 混合域验收集全部 Tool 成功响应（search_knowledge / get_evidence / list_knowledge_domains），**When** 逐条实测，**Then** 跨域串库事件数 = 0（单域引用不返回他域证据；多域引用时各证据归属正确且各留域身份）、Schema 合法率 = 100%、来源可定位率 = 100%（每条证据携带来源 ID、版本与可定位位置，含 Word 标题路径与 PDF page:N §编号前缀）。
4. **Given** 不含任何知识域引用的检索请求，**When** 请求执行，**Then** 被拒绝且不执行任何检索（宪法 I）；仅 project_scope 请求沿用旧码、双参数混用并集去重（沿用 007 口径）。
5. **Given** writer/reader 双实例形态，**When** 混合域验收集冒烟执行，**Then** 双形态各自通过、单侧非回归判定成立（沿用 006 instance form 口径）。

---

### User Story 5 - 既有全集回归（001–006 全部报告重跑） (Priority: P2)

001–006 六个 Feature 的全部历史报告按各自既有口径重跑，确认 011 的语料/档案/运行器扩展未引入任何回归：001 Dense 基线 11 条、002 混合对照 18 条、003 格式集 37 条 + 逐格式对照、004 图集 37 条、005 agentic 组合全集 63 条、006 双形态冒烟各 11 条；非延迟指标 1% 相对容差内一致，历史报告零覆盖。

**Why this priority**: 无回归义务是每个 Feature 的既定纪律（蓝图 §6）；对 011 尤其关键——它改 legal 档案、扩评测语料与运行器，是 2.0 定稿前最后一道全量回归闸口。

**Independent Test**: 依次按各报告口径重跑并对照历史值（1% 相对容差），全部一致且历史文件未被覆盖；010 交叉引用口径显式复跑确认提取器行为不变。

**Acceptance Scenarios**:

1. **Given** 001–006 各自口径的评测集与运行器，**When** 全部重跑，**Then** 各报告非延迟指标（Recall@K/MRR/nDCG）与历史报告在 1% 相对容差内一致；se-project 域行为不受 011 变更影响。
2. **Given** 重跑产物，**When** 落盘，**Then** 写入新文件（不覆盖 baseline_report.json 等历史报告），重跑命令与口径在 eval/README.md 登记（缺失的登记随文档债补齐）。
3. **Given** 011 对 legal 档案的扩展与法律域新语料，**When** 影响面核对，**Then** 010 交叉引用对照口径复跑行为不变（其 runner 经注册表显式触发提取器，不依赖 legal 档案词表）；008 通用格式回归与 009 双回归口径不受影响。

---

### User Story 6 - 文档债清理与 2.0 版本定稿 (Priority: P2)

清理三处文档债——docs/1.0-iteration-roadmap.md 更新至 2.0 收官状态（现停留在"002 Delivered"，003–011 交付缺失）；根 README 纠正"尚无业务实现代码"等与事实相反的过时陈述（001–010 已交付完整检索系统）；001–006 spec.md Status 更新为已交付状态（现 Draft/Specified 与"全部交付收敛"事实不符），007–010 一并核对。最后产出 2.0 演进目标逐项核销记录：对蓝图 §1.3 五项目标逐项给出达成判定、证据工件指针与未达成项处置。

**Why this priority**: 2.0 定稿要求"演进目标逐项核销"，而定稿记录的可信度依赖文档与事实一致；文档债是 011 明确列名的交付物（蓝图 §5-011），但相对基线与验收属收尾性质，故 P2。

**Independent Test**: 逐项核对文档债清单与实际过时陈述一一对应（roadmap 状态行/交付记录、README 边界陈述、spec Status 行）；核销记录对 §1.3 五项目标逐项可追溯到证据工件（报告/验收记录路径）。

**Acceptance Scenarios**:

1. **Given** docs/1.0-iteration-roadmap.md（现"Last Updated 2026-08-27 | 002 Delivered"），**When** 更新，**Then** 补齐 003–011 交付记录（含 2.0 视角迭代史）、状态行反映 2.0 收官、Remaining Gaps 与 2.0 触发条件（蓝图 §9）对齐。
2. **Given** 根 README（"仅包含规划与规格工件，尚无业务实现代码"等陈述），**When** 更新，**Then** 如实反映已交付系统（MCP 检索/混合/图增强/Agentic/多知识域/转换层摄入）与评测体系，不声称超出实际交付的能力。
3. **Given** 001–006 spec.md 的 Status 行（Implemented/Specified/Draft 与交付事实不符），**When** 更新，**Then** 与"全部交付收敛"事实一致且措辞全库统一；007–010 Status 一并核对同步（若仍为 Draft 则更新），不制造新文档债。
4. **Given** 2.0 蓝图 §1.3 五项演进目标，**When** 定稿核销执行，**Then** 逐项给出达成判定、证据工件指针（报告/验收记录路径）与未达成/部分达成项的处置记录；核销记录为独立工件（位置由 plan 决议，如 docs/2.0-finalization.md），2.0 蓝图正文保持冻结（仅在头部允许加注状态）。
5. **Given** 新增的评测资产（两域数据集/报告/运行器用法），**When** eval/README.md 同步，**Then** 新数据集、域基线报告与运行器用法按既有登记纪律登记（含口径说明），后续 Feature 可按 README 重建全部评测。

---

### User Story 7 - 前端管理界面中英文切换 (Priority: P2)

用户在 Web 管理端以语言切换器在中/英文之间切换界面语言：全部前端自产文案——页面与导航标题、表格列名、按钮、表单标签与占位符、操作反馈提示（成功/失败/进行中）、确认对话框、空状态、状态徽标文案及前端框架组件内置文案（分页、日期、模态确认等）——随切换即时呈现所选语言；语言偏好持久化（再次访问保留）。切换范围严格限于前端自产文案：后端返回的错误消息、API 响应内容与领域数据（项目名、文件名、slug、domain_key、状态码等）原样展示、不翻译、不修饰。现状不支持中英文切换（2026-09-07 第一手分析：前端源码全部硬编码英文、无 i18n 基础设施、框架组件 locale 未接线），本 Story 为用户在 specify 阶段的追加指示（见 Clarifications 追加指示记录）。

**Why this priority**: 管理端用户存在中英文使用偏好，双语界面是多知识域（含中文法律域/个人域语料）使用场景的基础可用性配套，且为用户明确指示纳入本版本。相对评测与验收主干，它不进入检索链路与 MCP 契约、交付独立、风险面小，故 P2。

**Independent Test**: 在三个管理页面（项目列表、项目详情、域档案）分别切换中/英文，断言：全部前端自产文案随语言切换、无目标语言残留（切中文后英文残留 = 0、切英文后中文残留 = 0，框架组件文案一并覆盖）；后端错误消息与领域数据不受切换影响；刷新/重开后语言偏好保留。

**Acceptance Scenarios**:

1. **Given** 管理端任一页面，**When** 用户切换语言（中↔英），**Then** 全部前端自产用户可见文案（导航/标题/列名/按钮/表单标签/占位符/提示/确认对话框/空状态/框架组件内置文案）即时呈现所选语言，无需重启后端或修改任何服务端配置。
2. **Given** 用户已选择某语言，**When** 再次访问（刷新页面/新开会话），**Then** 语言偏好保留（持久化生效），默认语言为英文（与现状一致、存量使用者零破坏）。
3. **Given** 后端返回错误（如上传失败、校验错误、作用域解析失败），**When** 错误提示展示，**Then** 后端返回的错误消息原样呈现（不翻译、不修饰）；仅前端自产的前缀/标题/按钮文案按当前语言呈现（混合语言呈现为预期形态，见 Edge Cases）。
4. **Given** 页面中的领域数据（项目名称、文件名、slug、domain_key、格式名、状态码），**When** 语言切换，**Then** 原样展示、不翻译。
5. **Given** 交付验收，**When** 两种语言下逐页面审计，**Then** 前端自产文案无目标语言残留（英文残留 = 0 / 中文残留 = 0），无绕过语言资源层的硬编码文案新增。
### Edge Cases

- 评测查询的期望锚点在语料更新后失效：语料一经评测集锚定即视为冻结资产——变更 MUST 触发评测集影响全量评审（新增语料不破坏既有锚点；既有锚点失效须显式评审处置），沿用固定集纪律。
- 语料文件解析/转换失败（毒文件、空产物、超限文件）：fail-loud 沿用 008 转换层失败语义，MUST NOT 静默跳过导致评测集锚点悬空。
- PDF 中文"第X条"标题不被数字编号启发式识别（PDF 解析器仅认数字编号标题，蓝图 §2.3 已记录、§9 列为触发条件）：法律域 PDF 语料 MUST 以数字编号标题（X.Y 形态）承载条文结构，中文"第X条"标题形态由 Word/Markdown 语料承载；MUST NOT 为此扩展解析器（触发条件未满足）。
- 交叉引用受益测量时图边为零（引用目标不可解析/语料无引用结构）：MUST 如实记录"无可测量受益"（Q1=A 闸口下按未达标分支处置），MUST NOT 伪造受益或跳过记录（宪法 III 暴露不确定性）；受益子集语料构造 SHOULD 保证存在可解析引用结构（≥3 类形态覆盖，沿用 010）。
- type:name 引用命中多个同名同类型活跃域：AMBIGUOUS_DOMAIN_REF 返回候选（沿用 007 口径）；验收语料 scope 命名保持唯一以避免歧义干扰测量。
- 公开法规/标准合同模板语料的版权与逐字转载边界（Q2=B 决议）：优先采用不受著作权保护的官方公开法律法规文本（法律法规依《著作权法》第五条不适用著作权保护）与许可宽松的标准合同模板；具体语料清单与逐字转载处置由 plan/research 固化，MUST NOT 引入版权不明的逐字长文。用户后续提供真实语料含 PII/受监管内容时：不预设广义脱敏（1.0 §26 立场），入库前由用户负责。
- 评测环境漂移（Qdrant 向量被清空/PG 重置）：沿用 reindex_eval_qdrant.py 重建纪律与语料入库幂等重放；域语料入库 MUST 可重放（环境重置后基线可重建）。
- 组合数据集口径随基数据集只增演化（005：37+7=44 → 56+7=63）：011 重跑按当前全集口径判读，历史报告以其产出时口径为准；口径演化事实在 eval/README 登记。
- 同名标题跨知识源重复（法律域多文件同名条文/个人域多笔记同名标题）：语料构造保持 scope 内标题唯一性约束（评测锚点可解析性），重复标题的消歧由 plan 固化（沿用 010 重复标题消歧纪律）。
- 延迟指标环境敏感：P50/P95 仅记录并标注环境，不进入 1% 容差判定（沿用 004 SC-007 语义）。
- writer/reader 双形态冒烟单侧失败：按 006 单侧非回归判定语义处置——记录失败并阻断 2.0 定稿，MUST NOT 放宽判定口径。
- 后端错误消息与前端前缀混合语言呈现（如英文后端 message 拼接中文前端前缀）：为用户约束下的预期形态（切换仅限前端），MUST NOT 为消除混合而修改后端文案或翻译后端消息。
- 前端语言资源缺失键：MUST 有确定性回落（如回落英文或呈现键名），不出现空白或崩溃；缺失键不得静默呈现空字符串（确定性口径，宪法 VI 精神）。
- 语言偏好持久化数据被清空/损坏：回落默认语言英文，不报错、不阻断页面加载。

## Requirements *(mandatory)*

### Functional Requirements

**两验证域语料与域档案（蓝图 §1.3-4、§3.1/§3.2）**

- **FR-001**: 系统 MUST 落地 personal 内置域档案（第四内置档案，domain_key=personal）：supported_formats 至少含 markdown/txt/html/csv（与验证域语料格式集一致）、graph_relations 为空（无图词表）、域中立提示词、default_capabilities 声明检索模式、is_builtin=true 受 007 内置只读保护；档案声明 MUST 仅为配置数据（沿用 007 FR-006 口径，无知识内容）。
- **FR-002**: 个人/团队通用知识库域语料 MUST 建设并入库：≥5 个知识源、跨 ≥2 个 scope（个人知识库 scope = public + personal 档案；团队共享 scope = public + generic 档案；可选第 3 个 scope），覆盖 markdown/txt/html/csv 四格式（每格式 ≥1 个知识源），全部经 007–009 全链路入库（域档案格式校验 + FormatHandler 注册表分发 + 转换层/txt 原生切片 + 凭据脱敏）并发布知识版本。规模基线为每域 5–15 个知识源（建议默认，随语料冻结资产纪律生效）；来源为构造虚构样例（个人笔记/团队文档形态——个人/团队域无公开文本可依，Q2 决议范围未覆盖，属合理默认，见 Assumptions）。
- **FR-003**: legal 内置域档案的 supported_formats MUST 由 [markdown] 扩展至 [markdown, word, pdf]（承载合同/法规 Word/PDF 语料）；扩展为域档案声明式配置变更，MUST NOT 引入新解析器或新检索路径（word/pdf 原生解析器 003 已交付，011 仅消费）；graph_relations 的处置由交叉引用受益再验证闸口结果决定（Q1=A 决议，沿用 010 FR-030 双分支，见 FR-011）；chunk_type_extensions MUST 保持 None（不落地 legal:article 条文 chunk 类型，条文结构由通用标题/章节 chunk 承载——clarify Session chunk_type 决议）。
- **FR-004**: 法律合规域语料 MUST 建设并入库（public + legal scope）：≥5 个知识源（规模基线同 FR-002），以合同/法规 Word/PDF 语料为主（承载条文结构：数字编号 X.Y 与中文"第X条"标题形态），辅以 markdown 交叉引用语料（内部锚点/跨文件相对链接/中文条文引用三类形态，沿用或扩充 010 corpora/legal）。语料来源采用公开法规/标准合同模板（Q2=B 决议：官方公开发布的法律法规文本与标准合同模板；优先采用不受著作权保护的官方公开法律法规文本，版权与逐字转载边界处置见 Edge Cases）。Word/PDF 语料证据定位分别为标题路径与 page:N §编号路径（宪法 IV）。

**固定评测集（蓝图 §6、eval/README 固定集纪律）**

- **FR-005**: 两域固定评测集 MUST 各 ≥10 条：`eval/generic_domain_eval_dataset.json`（个人/团队通用知识库域）与 `eval/legal_domain_eval_dataset.json`（法律合规域）；查询由 LLM 生成、人工审核后入库（审核记录随库，沿用 agentic 数据集 _meta 形态）；每域 MUST 含 ≥2 条中文查询。
- **FR-006**: 评测集覆盖结构 MUST 满足：个人/团队域——markdown/txt/html/csv 每格式 ≥2 条（≥1 自然语言 + ≥1 结构定位，沿用 008 每格式评测范式）；法律域——条文结构检索子集 ≥4 条（Word/PDF 语料承载，含中文条款查询）+ 交叉引用受益子集 ≥6 条（markdown 语料承载，is_structural_benefit 标记，含 ≥1 条中文条文引用查询，沿用 010 SC-002 子集形态，可在 010 七条基础上扩充但为独立入库条目、不修改 010 数据集文件）。
- **FR-007**: 固定集纪律 MUST 成立：两域评测集为独立数据集文件（MUST NOT 追加进 eval_dataset.json / agentic_eval_dataset.json，避免污染 001–006 回归口径，沿用 cross_reference_eval_dataset.json 先例）；期望证据锚定 MUST 采用跨环境稳定机制（结构锚点，如 expected_heading / slug+定位前缀，沿用 010 先例），MUST NOT 依赖运行时生成的 ID；评测集一经入库，后续变更 MUST NOT 破坏既有条目（字段结构只增不改不删，既有条目逐字节保持；硬约束权威表述见 FR-026）。

**域基线报告（蓝图 §6、1.0 §24.1/§24.3、宪法 X）**

- **FR-008**: 域基线评测 MUST 沿用 001/002 方法论与 run_eval / run_comparison 运行器：指标计算、同会话双臂纪律（先 dense 后 hybrid）、可重复性检查（非延迟指标 1% 相对容差）全部复用既有实现；运行器扩展 MUST 最小化（域数据集寻址 + 结构锚点期望解析 + 域基线报告产物），允许新增薄入口脚本（沿用 run_cross_reference_comparison.py 导入复用先例），MUST NOT 另建一套评测基础设施。
- **FR-009**: 系统 MUST 产出 `eval/generic_domain_baseline_report.json` 与 `eval/legal_domain_baseline_report.json`：dense/hybrid 双路径 Recall@K / MRR / nDCG + P50/P95 延迟、逐查询明细（查询、期望锚点、双路径排名/命中）、硬指标实测（串库/Schema/定位逐条测量）、可重复性检查记录；MUST 新增两份域基线报告契约 schema（沿用既有对照报告 schema 字段语义），两份报告 100% 通过各自契约校验。
- **FR-010**: 域基线报告 MUST 为非约束性对照锚点：不含 enters_default_path 类路径决策字段、不设最低水位门槛（宪法 X——建立锚点而非宣称改进；dense/hybrid 基线的路径决策闸口已由 002/004/005 完成）；dense 与 hybrid 相对差仅作信息性记录；报告一经产出 MUST NOT 被覆盖重写（重跑产物写新文件或附属记录，沿用历史产物勿覆盖纪律）。
- **FR-011**: 法律域评测 MUST 附带交叉引用受益再验证（011 唯一继承的路径进入闸口，区别于 FR-010 的非约束性基线锚点），沿用 010 FR-030 双分支闸口语义（Q1=A 决议）：同会话混合检索基线臂 vs 图增强臂（混合 + 交叉引用图扩展），闸口 = MRR 与 nDCG 均值相对提升 ≥3% + Recall 非降 + 硬指标全过。达标分支：legal 内置档案 graph_relations 启用 references/referenced_by（交叉引用图扩展进入 legal 默认检索路径，legal 档案 default_capabilities/has_graph 相应更新）；未达标分支：维持 R11 空词表现状（cross_reference 不为 legal 默认触发、可由自定义档案显式启用）。两分支的结果与判定依据 MUST 如实记录于法律域基线报告或其附属工件（零可测图边时记录"无可测量受益"，宪法 III）。受益测量的图边提取沿用 010 runner 的注册表显式触发机制（不改变 cross_reference 提取器行为）。

**多域端到端验收（蓝图 §1.3-1/5、宪法硬约束）**

- **FR-012**: 混合域验收环境 MUST 覆盖 ≥4 个活跃知识域（public + personal、public + generic、public + legal、project + se-project——SE 项目域复用既有评测语料环境）；MCP 双工具（search_knowledge / get_evidence）MUST 以 domain_scope 三种形态（数字 scope ID / slug / type:name）寻址完成跨域混合检索与证据展开，三种形态全覆盖验收。
- **FR-013**: list_knowledge_domains 发现流程 MUST 作为验收入口走通闭环：发现 → 以返回的 slug/ID 构造 domain_scope → search_knowledge 检索 → get_evidence 展开；返回条目仅含域元数据（无知识内容，沿用 007 口径）。
- **FR-014**: 硬指标三件套 MUST 在混合域验收集上全量实测并落盘验收记录：跨域串库事件数 = 0（单域引用不返回他域证据；多域引用各证据归属正确且各留域身份）、三工具（search_knowledge / get_evidence / list_knowledge_domains）Schema 合法率 = 100%、来源可定位率 = 100%（含 Word 标题路径与 PDF page:N §编号前缀证据）；验收记录为独立工件（路径由 plan 决议）。
- **FR-015**: 混合域验收集 MUST 在 writer/reader 双实例形态下各冒烟一轮（沿用 006 instance form 纪律与单侧非回归判定）；DeepSeek Harness 为必过参考客户端（MCP 双工具 + list_knowledge_domains 端到端），ChatGPT App 与 Claude Code 记录兼容性状态、不作阻塞项（沿用 006/007/010 惯例）。

**既有全集回归（蓝图 §6 无回归义务）**

- **FR-016**: 001–006 全部报告 MUST 按各自口径重跑：001 Dense 基线 11 条、002 混合对照 18 条（--limit 18）、003 格式集 37 条 + 逐格式对照、004 图集 37 条（--limit 37，010 先例）、005 agentic 组合数据集全量（当前 63 条）、006 双形态冒烟各 11 条；非延迟指标 MUST 在 1% 相对容差内与历史报告一致；重跑产物 MUST NOT 覆盖历史报告；各口径重跑命令 MUST 在 eval/README.md 登记（缺失登记随文档债补齐）。
- **FR-017**: 011 的全部变更（legal 档案扩展、法律域/个人域新语料、运行器扩展）MUST NOT 影响 001–010 任何既有口径：010 交叉引用对照口径 MUST 显式复跑确认行为不变（其 runner 经注册表显式触发提取器，不依赖 legal 档案词表）；008 通用格式回归、005/009 双回归口径 MUST 在影响面核对中确认不受影响；若复跑发现口径漂移，MUST 修复至一致而非放宽口径。

**文档债清理与 2.0 定稿（蓝图 §5-011、§7-011）**

- **FR-018**: docs/1.0-iteration-roadmap.md MUST 更新至 2.0 收官状态：补齐 003–011 交付记录、状态行更新（现"002 Delivered"过时）、Remaining Gaps 与 2.0 触发条件（蓝图 §9）对齐；eval/README.md MUST 同步登记两域数据集、域基线报告与运行器用法（沿用既有登记纪律，含口径说明）。
- **FR-019**: 根 README MUST 纠正过时陈述："仅包含规划与规格工件，尚无业务实现代码"、"当前仓库处于规格设计阶段"、"首个纵向 Feature：001"等 MUST 更新为如实反映已交付系统（MCP 检索四路径、多知识域、转换层摄入、评测体系）；文档变更 MUST NOT 声称超出实际交付的能力（如实陈述）。
- **FR-020**: 001–006 spec.md 的 Status MUST 更新为与"全部交付收敛"事实一致的已交付状态（现 001=Implemented、002=Specified、003–006=Draft 均与事实不符），措辞全库统一；007–010 的 Status MUST 一并核对同步（若仍为 Draft 则更新），不制造新文档债。
- **FR-021**: 2.0 版本 MUST 定稿：对蓝图 §1.3 五项演进目标逐项核销——每项给出达成判定、证据工件指针（报告/验收记录路径）与未达成/部分达成项的处置记录；核销记录为独立工件（位置由 plan 决议，如 docs/2.0-finalization.md）；2.0 蓝图正文保持冻结（架构基线纪律），仅在头部允许加注定稿状态。

**硬性约束（宪法 v1.3.0）**

- **FR-022**: 全部检索 MUST 继承显式知识域引用要求：project_scope 或 domain_scope 至少一个非空，缺失即拒绝、绝不回退全库；验收覆盖仅 project_scope（旧码不变）、仅 domain_scope、双参数混用、两参数皆空四类场景（沿用 007 验收口径）。
- **FR-023**: 跨知识域串库 MUST 为零：任一证据、Chunk、图关系不得从一域出现在另一域检索中，除非显式多域引用包含该域；混合域验收集断言泄漏事件数 = 0。
- **FR-024**: 验收集全部 Tool 成功响应 MUST 100% 通过 search_knowledge / get_evidence / list_knowledge_domains 输出 Schema 校验（对外契约零变更——011 不修改任何 MCP 契约）。
- **FR-025**: 验收集全部返回证据 MUST 100% 携带来源 ID、版本与可定位位置（含转换层格式与 word/pdf 定位前缀），来源可定位率 = 100%。
- **FR-026**: 评测集一经入库 MUST NOT 破坏既有条目：011 新增数据集入库前后，既有全部数据集文件（eval_dataset.json / agentic_eval_dataset.json / cross_reference_eval_dataset.json）逐条保持不变；该约束同样约束 011 自身新增数据集的后续演进与后续 Feature。

**前端管理界面中英文切换（用户 2026-09-07 追加指示；范围严格限于前端，见 Clarifications 追加指示记录）**

- **FR-027**: 前端管理界面 MUST 提供中英文（zh/en）切换：全部前端自产用户可见文案经统一语言资源层管理，切换即时生效；语言偏好 MUST 持久化（再次访问保留）；默认语言为英文（与现状一致、存量使用者零破坏），浏览器语言自动检测为可选增强（由 plan 决议）。
- **FR-028**: 语言切换 MUST 覆盖前端框架组件内置文案（表格分页、日期选择、模态确认等组件默认文案），经组件库官方 locale 机制随所选语言同步切换。
- **FR-029**: 切换范围 MUST 严格限于前端自产文案：后端返回的错误消息、API 响应内容与领域数据（项目名/文件名/slug/domain_key/格式名/状态码等）MUST 原样展示、不翻译、不修饰（用户约束：不修改后端错误提示等）。
- **FR-030**: 交付时前端 MUST 无遗漏：全部页面（项目列表、项目详情、域档案）的前端自产文案在两种语言下完整覆盖——切至中文后英文残留 = 0、切至英文后中文残留 = 0（框架组件文案与语言资源层一并验收）。
- **FR-031**: 前端语言切换 MUST NOT 影响后端行为与对外契约：不修改任何后端错误提示、API 响应文案或 MCP 输出（MCP 契约零变更，FR-024 口径不因前端变更而放宽）；前端语言切换验收不进入检索链路。
### Key Entities *(include if feature involves data)*

- **验证域语料（Validation-Domain Corpora）**: 服务固定评测集的两域语料集合——个人/团队通用知识库域（markdown/txt/html/csv，跨 personal/generic 档案 scope）与法律合规域（Word/PDF 合同法规 + markdown 交叉引用语料，legal 档案 scope）；入库后即为评测锚定资产，变更受固定集纪律约束。
- **personal 域档案（第四内置 DomainProfile）**: 个人知识库域的语义档案——通用文档格式集（至少 markdown/txt/html/csv）、空图关系词表、域中立提示词、is_builtin 只读保护；011 落地（蓝图 §3.1"legal/personal 等域档案由 011 评测语料建设时落地"）。
- **legal 域档案（扩展形态）**: supported_formats 扩展至 markdown/word/pdf 的法律域内置档案；chunk_type_extensions 保持 None（不落地 legal:article 条文 chunk 类型）；graph_relations 处置由受益再验证闸口结果决定（Q1=A 决议：达标启用 references/referenced_by 进 legal 默认图路径、未达标维持 R11 空词表，见 FR-011）。
- **域评测数据集（Domain Eval Dataset）**: generic_domain_eval_dataset.json / legal_domain_eval_dataset.json——独立固定集，条目含查询、domain_scope 寻址、结构锚点期望、语言标记与人工审核记录；一经入库不可破坏既有条目。
- **域基线报告（Domain Baseline Report）**: dense/hybrid 双路径 Recall@K/MRR/nDCG + P50/P95 延迟 + 逐查询明细 + 硬指标实测 + 可重复性检查的固定工件；非约束性对照锚点，后续通用域优化的对照基线。
- **混合域验收集（Mixed-Domain Acceptance Suite）**: 跨 personal/generic/legal/se-project 四语义轴 scope 的 MCP 验收请求集（发现 → 三形态寻址 → 检索 → 展开 + 引用缺失/混用场景）；硬指标三件套的测量载体，验收记录落盘。
- **2.0 定稿核销记录（Finalization Record）**: 蓝图 §1.3 五项演进目标的逐项达成判定、证据工件指针与未达成项处置的独立工件。
- **前端语言资源（UI Locale Bundle）**: 前端全部自产用户可见文案的中英双语资源集合，经统一语言资源层管理；语言切换器与持久化偏好为其消费面；后端返回文案与领域数据不在其内（范围约束见 FR-029）。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 两域固定评测集各 ≥10 条入库（个人/团队域四格式 × ≥2 条全覆盖、含 ≥2 条中文；法律域条文结构 ≥4 + 交叉引用受益 ≥6、含中文条文引用查询），LLM 生成 + 人工审核记录随库；既有全部数据集文件逐条零改动。
- **SC-002**: 两份域基线报告产出并 100% 通过各自契约 schema 校验：dense/hybrid 双路径 Recall@K/MRR/nDCG + P50/P95 延迟齐全、逐查询明细完备、可重复性检查（非延迟指标 1% 容差）通过；运行器沿用 run_eval/run_comparison 内核（最小扩展，无新建评测基础设施）。
- **SC-003**: 硬指标三件套在混合域验收集全量成立并落盘验收记录：跨域串库 = 0、三工具 Schema 合法率 = 100%、来源可定位率 = 100%（含 Word 标题路径与 PDF page:N §编号前缀证据）。
- **SC-004**: 多域端到端闭环走通：list_knowledge_domains 发现 → domain_scope 三形态（数字 ID/slug/type:name）寻址 → search_knowledge 检索 → get_evidence 展开，≥4 个知识域（personal/generic/legal/se-project 语义轴）全覆盖；无引用请求 100% 被拒；仅 project_scope 旧码逐字节不变。
- **SC-005**: 001–006 全集回归无回归：六项报告按各自口径重跑，非延迟指标 1% 相对容差内与历史报告一致；历史报告文件零覆盖；010 交叉引用口径复跑行为不变。
- **SC-006**: writer/reader 双形态冒烟通过：混合域验收集在双实例形态下各自通过，单侧非回归判定成立（006 口径）。
- **SC-007**: 交叉引用受益再验证按 010 FR-030 双分支闸口执行（Q1=A 决议）：法律域受益对照测量（同会话混合基线 vs 图增强臂）完成并记录；MRR 与 nDCG 均值相对提升 ≥3% + Recall 非降 + 硬指标全过 → legal 档案启用 references/referenced_by 并进 legal 默认图路径；未达标 → 维持 R11 空词表。两分支判定依据均有如实记录；零可测图边时记录"无可测量受益"。
- **SC-008**: 文档债清零：roadmap 反映 2.0 收官状态（003–011 交付记录补齐）；README 无过时陈述且不超售；001–006（含 007–010 核对）spec Status 与交付事实一致；eval/README 登记全部新增评测资产与重跑口径。
- **SC-009**: 2.0 演进目标逐项核销：蓝图 §1.3 五项目标各有达成判定与证据工件指针；未达成/部分达成项有明确处置记录；核销记录为独立工件、蓝图正文未被修改。
- **SC-010**: 评测资产可复现：两域语料入库幂等可重放（环境重置后基线可重建，沿用 reindex/重放纪律）；评测集期望锚点跨环境稳定（不依赖运行时生成 ID）。
- **SC-011**: 前端中英文切换验收：三个管理页面全部前端自产文案双语完整覆盖（中文态英文残留 = 0 / 英文态中文残留 = 0，框架组件文案一并覆盖），语言偏好持久化生效、默认语言为英文；后端错误消息与领域数据不受切换影响；后端与 MCP 契约零改动。

## 范围内 / 范围外

### 范围内（011）

- 两验证域语料建设与入库（个人/团队域 markdown/txt/html/csv；法律域 Word/PDF + markdown 交叉引用）。
- personal 内置域档案落地（第四内置档案）与 legal 档案 supported_formats 扩展（声明式配置变更）。
- 两域固定评测集（各 ≥10 条，LLM 生成 + 人工审核，含中文）与结构锚点期望机制、独立数据集文件。
- 两份域基线报告（dense/hybrid 双路径 + P50/P95 + 逐查询明细 + 硬指标实测 + 可重复性检查）与两份新契约 schema；run_eval/run_comparison 运行器最小扩展（含薄入口脚本先例）。
- 法律域交叉引用受益对照测量与 legal 词表处置（Q1=A 决议：010 FR-030 双分支闸口——达标启用 references/referenced_by 进 legal 默认图路径、未达标维持 R11 空词表）。
- 多域端到端验收（domain_scope 三形态寻址、list_knowledge_domains 发现闭环、硬指标三件套全量实测、writer/reader 双形态冒烟）与验收记录工件。
- 001–006 全集回归重跑（+ 011 变更影响面对 007–010 口径的核对，010 交叉引用口径显式复跑）。
- 前端管理界面中英文切换（统一语言资源层 + 切换器 + 偏好持久化 + 组件库 locale 接线；仅前端自产文案，后端错误提示与 MCP 契约零改动——用户 2026-09-07 追加指示）。
- 文档债清理（roadmap / 根 README / eval/README / 001–006 及 007–010 spec Status）与 2.0 演进目标逐项核销记录。

### 范围外（不重复 001–010）

- 任何新检索路径、检索信号、融合、排序、图扩展或 Agent 编排逻辑（001–005 已交付；011 仅测量与验收，无 enters_default_path 决策）。
- 检索质量优化本身（后续通用域优化 Feature 以两基线为对照锚点立项，进 plan 前相对基线声明目标）。
- 域基线水位门槛 / 路径决策字段（非约束性锚点；路径决策闸口 002/004/005 已完成）。
- 新解析器、新格式、PDF 中文标题启发式扩展、legal:article 条文 chunk_type 扩展（触发条件未满足/超范围，蓝图 §9；word/pdf 原生解析器与转换层 003/008 已交付，011 仅使用；条文结构由通用标题/章节 chunk 承载，clarify Session chunk_type 决议）。
- 域档案注册表基础设施、FormatHandler 注册表、转换层、交叉引用提取器与图注册表机制本身（007/008/010 已交付；011 仅声明式消费/扩展档案配置）。
- 宪法修订（v1.3.0 为合规基线，011 不修改）与 2.0 蓝图正文改写（冻结纪律；定稿为独立核销工件）。
- 后端 / REST API / MCP 错误提示与响应文案的多语言化（用户明确排除：中英文切换仅限前端页面，后端错误提示原样呈现）；前端新增页面或工作流（011 前端范围仅 i18n 化既有三页面）。
- Neo4j、自动内容同步、认证多用户、OCR、广义脱敏（触发条件未满足，蓝图 §9）。

## Clarifications

### Session 2026-09-07（specify 阶段，用户已答复）

- **Q1: legal 域档案 graph_relations 处置与交叉引用受益再验证的闸口语义** → **A：沿用 010 FR-030 双分支闸口**。在 011 更丰富的法律语料上重跑 ≥3% 结构性受益闸口（MRR 与 nDCG 均值相对提升 ≥3% + Recall 非降 + 硬指标全过）：达标则 legal 档案启用 references/referenced_by、交叉引用图扩展进入 legal 默认检索路径；未达标维持 R11 空词表现状（cross_reference 不为 legal 默认触发、可由自定义档案显式启用）。两分支结果与判定依据如实记录（FR-011 / SC-007）。
- **Q2: 语料规模与来源基线** → **B：法律语料采用公开法规/标准合同模板**（官方公开发布的法律法规文本优先——法律法规依《著作权法》第五条不适用著作权保护；标准合同模板注意许可与逐字转载边界，见 Edge Cases）。每域知识源数量采纳建议默认（5–15 个文件、跨 2–3 个 scope）；个人/团队通用知识库域无公开文本可依，以构造虚构样例为合理默认（决议范围未覆盖个人域来源，见 Assumptions）。
- **追加指示（2026-09-07，同轮答复）**：前端管理界面纳入中英文切换（User Story 7 / FR-027–FR-031 / SC-011）。用户原话："当前前端页面是否支持中英文切换。若不支持，本版本加入中英文切换。切换范围只限于前端页面，不修改后端错误提示等。" 经第一手分析确认现状不支持：前端源码全部硬编码英文（零中文字符）、依赖中无任何 i18n 库、antd ConfigProvider 未挂 locale（框架组件文案亦固定英文）；故按用户指示纳入 011 交付，范围严格限于前端自产文案（后端错误提示与 MCP 契约零改动）。

### Session 2026-09-07（clarify 阶段，用户已答复）

- **Q（评测查询生成机制）: 沿用 generate_dataset.py 启发式扩展（扩展通用 chunk_type 分支）还是引入 LLM 生成 + 人工审核？** → **A：LLM 生成 + 人工审核**。评测查询由 LLM 生成、人工审核后入库（不扩展 generate_dataset.py 启发式 chunk_type 分支；Input 中「AI 生成」即指 LLM 生成），审核记录随库沿用 agentic 数据集 _meta 形态（FR-005 / SC-001 / Assumptions）。
- **Q（legal 域档案 chunk_type 扩展）: chunk_type_extensions/legal:article 条文类型在本 Feature 落地还是仅用通用 chunk_type？** → **A：仅用通用 chunk_type，不落地 legal:article**。legal 档案 chunk_type_extensions 保持 None，条文结构由通用标题/章节 chunk 承载（Word 标题路径 / PDF page:N § 定位）；graph_relations/references 仍由 Q1=A 双分支闸口决定（FR-003 / Key Entities / 范围外）。

## Assumptions

- 011 复用 001–010 全部已交付能力（四条检索路径、域档案基础设施、转换层、图提取器注册表、MCP 契约与寻址），交付物限于语料、评测集、报告、验收、文档与运行器最小扩展；不新增检索路径（输入硬性约束）。
- 基线非约束性已按房规固化（宪法 X、迭代提示词 11.6"建立锚点而非宣称改进"）：不设最低水位门槛（如 MRR ≥0.7 不作验收）、不含路径决策字段；后续优化 Feature 相对基线声明目标。
- 查询生成方式经澄清决议为 LLM 生成 + 人工审核入库（Input 中「AI 生成」即指 LLM 生成）；MUST NOT 扩展 generate_dataset.py 启发式 chunk_type 分支作为 011 两域新评测集的生成机制（启发式脚本仅作既有 001–006 数据集维护）；审核记录随数据集入库（沿用 agentic 数据集 _meta.review_status 形态）。
- 新域数据集以 domain_scope 形态寻址（slug/数字 scope ID），期望锚点采用跨环境稳定结构锚点（沿用 010 cross_reference 先例）；具体字段结构由 plan 固化（迭代提示词 11.3 决议项）。
- `generic_domain_baseline_report.json` 命名承载"个人/团队通用知识库域"整体（跨 personal/generic 档案 scope），按输入固定；不因命名含 "generic" 而排除 personal 档案 scope。
- scope 结构/语义组合默认：个人知识库 = public + personal；团队共享 = public + generic；法律域 = public + legal；SE 项目域复用既有评测语料环境（project + se-project）。结构/语义自由组合语义不变（蓝图 §3.1）。
- PDF 条文结构以数字编号标题（X.Y）承载（PDF 解析器启发式仅认数字编号，蓝图 §2.3/§9）；中文"第X条"标题形态由 Word/Markdown 语料承载；不为此扩展解析器。
- cross_reference 提取器维持 markdown 格式挂载（010 FR-017）；Word/PDF 语料不产交叉引用边，受益子集以 markdown 法律语料承载；受益测量的图边提取沿用 010 runner 的注册表显式触发机制（提取器行为不变）。
- 评测环境沿用共享开发环境（DATABASE_URL / QDRANT_URL）、reindex_eval_qdrant.py 重建纪律与语料幂等重放；延迟指标环境敏感、不进容差判定。
- 语料来源决议落地（Q2=B）：法律域采用公开法规/标准合同模板（版权边界处置见 Edge Cases，清单由 plan/research 固化）；个人/团队域构造虚构样例（决议范围未覆盖个人域来源的合理默认）；每域规模基线 5–15 知识源、跨 2–3 scope。
- 前端中英文切换为用户 2026-09-07 specify 阶段追加指示（见 Clarifications 追加指示记录）：默认语言英文（与现状一致、零破坏）、偏好持久化（具体存储机制由 plan 决议）；语言资源层技术选型、切换器形态与浏览器语言检测均由 plan 决议；切换仅限前端自产文案，后端错误提示与 MCP 契约零改动（用户约束，FR-029/FR-031）。
- 005 agentic 口径随基数据集只增演化（组合数据集当前 63 条 = 56 + 7）；011 重跑按当前全集判读，历史报告以其产出时口径为准。
- 001–006（及 007–010）"全部交付收敛"以蓝图 §2.1 交付基线与代码库现状为准；文档债更新为如实陈述，不追溯改写各 Feature 的历史工件内容（仅更新 Status 行等元数据）。
- 规模预估 30–40 任务（蓝图 §7-011）；TDD 纪律适用于运行器扩展部分（迭代提示词 11.7）。
- 验收参考客户端沿用惯例：DeepSeek Harness 必过，ChatGPT App / Claude Code 记录兼容状态、不作阻塞项。
