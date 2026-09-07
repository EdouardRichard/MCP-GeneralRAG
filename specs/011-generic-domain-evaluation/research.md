# Research: 通用域评测与多域验收（011）

**Branch**: 011-generic-domain-evaluation | **Date**: 2026-09-07 | **Spec**: [spec.md](./spec.md)

> Phase 0 决策记录。每条含 Decision / Rationale / Alternatives considered。关键现状锚点（2026-09-07 工作树）：legal 内置档案现为 010 R11 交付形态（supported_formats=["markdown"]、graph_relations={}，因 010 受益闸口在最小语料上未达标 MRR −11.1%/nDCG −6.3%）；eval 运行器 run_eval.py（--mode dense/hybrid）、run_comparison.py（--limit）、run_cross_reference_comparison.py（010 受益对照，显式经注册表触发提取器）；005 agentic 组合口径 63 条 = eval_dataset 56 + agentic 7；前端 3 页面约 65 处英文硬编码、无 i18n 库、antd ConfigProvider 未挂 locale。

---

## R0 基线声明（宪法 X 前置）

**Decision**: 011 的对照义务为双重且不对称：
1. **基线建立（核心）**：两份域基线报告（generic_domain_baseline_report.json / legal_domain_baseline_report.json）为后续通用域优化的**非约束性对照锚点**——不含 enters_default_path 字段、不设最低水位门槛（宪法 X"建立锚点而非宣称改进"；路径决策闸口已由 002/004/005 完成）。报告含 dense 与 hybrid 双臂指标 + P50/P95 延迟 + 逐查询明细 + 硬指标实测 + 可重复性检查。
2. **无回归（继承）**：001–006 六项报告按各自口径重跑，非延迟指标（Recall@K/MRR/nDCG）相对历史报告在 1% 相对容差内一致（沿用 006/007 SC-009 判定范式）；重跑产物落 011 前缀新文件、历史报告零覆盖。

**Rationale**: 011 的角色与 001–010 相反——它建立对照基线本身而非宣称改进；同时作为 2.0 收官 Feature 承担全集无回归与硬指标终验。

**Alternatives**: 给域基线设最低水位门槛（如 MRR≥0.7，否决：违反"锚点而非门槛"语义与宪法 X，低水位恰是后续优化的对照起点）；覆盖历史报告（否决：破坏基线可追溯性，eval/README"历史产物勿覆盖"约定）。

---

## R1 域基线运行器：薄入口复用内核（不改 001/002 口径）

**Decision**: 新增薄入口 eval/run_domain_baseline.py，导入复用 run_eval.py 与 run_comparison.py 的内核（run_single_eval / compute_metrics / check_reproducibility / 同会话双臂纪律），不做任何修改：指标计算、可重复性检查（非延迟 1% 容差）、硬指标实测复用既有实现。薄入口只补三处差异：
1. **数据集寻址**：解析 domain_scope 条目（slug / 数字 scope ID）为 numeric scope 集合（复用后端既有 scope 解析逻辑，等价 007 统一引用解析器）。
2. **期望锚点**：expected_heading 结构锚点（而非 expected_evidence_ids），运行时按 Chunk section_path 末段标题 / 定位前缀匹配（沿用 010 cross_reference runner 的 heading 解析范式）。
3. **报告产物**：输出域基线报告（dense_metrics / hybrid_metrics / deltas / hard_constraints / per_query_comparison / reproducibility，无 enters_default_path），经新契约 schema 校验。

**Rationale**: 复用内核保证"沿用 001/002 方法论"成立且不触碰 001/002 回归口径；薄入口与 010 run_cross_reference_comparison.py 同款先例（导入复用、不另建基础设施，spec FR-008）。

**Alternatives**: 修改 run_comparison.py 直接支持域基线（否决：改动既有运行器行为有回归风险，且 002 口径以 run_comparison.py 现状为契约）；另写全新评测引擎（否决：违反 FR-008"不另建评测基础设施"）。

---

## R2 评测数据集字段决议：domain_scope + expected_heading

**Decision**: 新域数据集条目采用如下字段形态（独立文件，不触碰既有数据集）：

~~~text
{
  "query": "...",                     # 查询文本
  "domain_scope": ["<slug-or-id>"],   # 知识域引用（slug 优先，runner 解析为 scope 集合）
  "expected_heading": "...",          # 结构锚点：标题路径末段/定位前缀（跨环境稳定）
  "format": "markdown|txt|html|csv|word|pdf",  # 个人域格式覆盖审计；法律域语料格式
  "language": "zh|en",
  "is_structural_benefit": true,      # 仅法律域交叉引用受益子集条目（沿用 010）
  "_meta": { "review_status": "reviewed", "review_notes": "...", "grounded_source": "..." }
}
~~~

- **寻址**：用 domain_scope（007 MCP 参数同名）而非 project_scope——域基线评测本身即成为 domain_scope 寻址的持续验证；slug 为默认形态（可读、可复现、跨环境稳定），runner 经既有解析逻辑转 numeric scope。
- **锚点**：expected_heading 结构锚点（沿用 010 cross_reference_eval_dataset.json 先例），MUST NOT 依赖运行时生成的 chunk_id（跨环境不稳定）。
- **零破坏**：新字段不进 eval_dataset.json / agentic_eval_dataset.json（避免污染 001–006 回归口径，沿用 cross_reference 先例独立文件）。

**Rationale**: 输入已定「LLM 生成 + 人工审核 + 含中文」，但未定字段；domain_scope 让域基线评测天然验证 007 寻址能力，expected_heading 让锚点跨环境可复现（SC-010）。

**Alternatives**: 沿用 project_scope + expected_evidence_ids（否决：expected_evidence_ids 依赖运行时 ID，且 project_scope 语义无法覆盖 public+personal/legal 域）；混合两种字段（否决：单形态清晰，schema 校验单一）。

---

## R3 两域语料清单与预期受益点

**Decision**:

**个人/团队通用知识库域（generic_domain，构造虚构样例）**：
- 语料：markdown/txt/html/csv 四格式，各 ≥2 个知识源，合计 5–15 个；跨 2 个 scope（个人知识库 public+personal、团队共享 public+generic）；内容为个人笔记/会议记录/清单/数据表/网页存档形态，含中文。
- 例外记录（宪法 X「real-domain corpora」）：个人知识库域天然无公开真实语料可依，故以构造虚构样例承载；样例为域形态真实的结构化文档、经真实摄入与检索链路评测（非理论假设）。失效条件：当有真实个人/团队语料（经授权脱敏）可得时，替换为真实语料并重跑基线（Governance「例外须附失效/移除条件」）。
- 预期受益点（评测集瞄准）：混合格式检索——自然语言查询（跨格式语义召回）与结构定位查询（csv 的 sheet: 前缀、html 的标题路径、txt 段落定位、markdown 标题路径）；中文词汇/语义查询。该域无图词表（personal/generic 空 graph_relations），基线为纯 dense/hybrid。

**法律合规域（legal_domain，公开法规/标准合同模板，Q2=B）**：
- 语料：合同/法规 Word（"第X条"标题样式）与 PDF（数字编号 X.Y 标题，PDF 解析器启发式仅认数字编号——中文"第X条"由 Word/Markdown 承载）+ markdown 交叉引用语料（内部锚点/跨文件相对链接/中文条文引用三类形态，沿用/扩充 010 corpora/legal）。
- 预期受益点：① 条文结构检索——"第X条规定了什么 / X.Y 条款内容"，靠 Word 标题层级与 PDF page:N §编号路径；② 交叉引用受益——"谁引用了第X条 / 第X条依据哪条制定"，靠 references/referenced_by 图扩展（Q1=A 闸口）。

**Rationale**: 两域各瞄准 2.0 的关键能力面（通用格式摄入检索、文档结构定位、非 SE 图扩展），使基线报告成为这些能力后续优化的有效对照锚点。

**Alternatives**: 法律域全用 Word/PDF 不加 markdown（否决：cross_reference 提取器 format=markdown，无 markdown 则受益验证无从进行）；个人域扩到全部 12 格式（否决：输入明列 markdown/txt/html/csv 四格式，其余格式 008 已有评测覆盖）。

---

## R4 查询生成方法决议：LLM 生成 + 人工审核（不扩 generate_dataset.py）

**Decision**: 查询由 LLM 生成、人工审核后入库（不扩展 generate_dataset.py 启发式；clarify 决议将 Input「AI 生成」界定为 LLM 生成），逐条附人工审核记录（_meta.review_status=reviewed + review_notes + grounded_source），入库前完成审核。两域结构覆盖：个人域 markdown/txt/html/csv 每格式 ≥2 条（≥1 自然语言 + ≥1 结构定位）；法律域条文结构 ≥4 + 交叉引用受益 ≥6（含 ≥1 中文条文引用）；每域 ≥2 条中文。

**Rationale**: 输入「AI 生成 + 人工审核」经 clarify 决议即 LLM 生成；generate_dataset.py 的 SE 域 chunk_type 二分启发式无法表达通用域语义与结构锚点（csv sheet:/html 标题路径/法律条文），LLM 生成 + 人工审核是更可靠且与 agentic 数据集 _meta.review 惯例一致的方式。固定集纪律（一经入库不破坏既有条目）由 R2 独立文件 + schema 校验保证。

**Alternatives**: 扩展 generate_dataset.py 启发式（否决：启发式难覆盖中文与结构锚点，且 SE 域启发式职责应保持单一）；LLM 批量生成无审核（否决：违反固定集纪律与人工审核入库要求）。

---

## R5 基线水位的非约束性说明（宪法 X 对照义务）

**Decision**: 域基线报告为**非约束性对照锚点**：不含 enters_default_path 字段、不设任何最低可接受水位门槛（不设 MRR≥0.7 之类）；dense 与 hybrid 的相对差仅作信息性记录。报告的规范性判据仅为：指标/延迟/逐查询/硬指标字段齐全、通过契约 schema 校验、非延迟指标 1% 容差可重复。异常低水位（如 ingestion 缺陷导致空检索）属缺陷，须先修复再定基线；因语料/查询质量导致的低水位如实记录为优化空间（不阻断 Feature）。

**Rationale**: dense/hybrid 已是默认检索路径（002 闸口已过），011 无路径决策义务；宪法 X 要求增强对照基线证明收益，而基线本身无需门槛——后续优化 Feature 在 research.md 相对本基线声明目标即可（1.0 §24.3 纪律延伸至通用域）。

**Alternatives**: 设 MRR≥0.7 门槛（否决：混淆"锚点"与"闸口"，且会迫使在锚点阶段做优化——违反 011"不宣称改进"边界）；给报告加 enters_default_path 判定（否决：路径决策非 011 职责）。

---

## R6 报告契约 schema：两份独立（加法，不触碰既有）

**Decision**: 新增两份域基线报告契约 schema + 一份共享 $defs：
- contracts/domain-baseline-common.schema.json：共享 metricBlock / latencyBlock / hardConstraintsBlock / domainQueryEntry（per_query 条目：domain_scope + expected_heading 替换 project_scope + expected_evidence_ids）。
- contracts/generic-domain-baseline-report.schema.json：report_type=generic_domain_baseline；dense_metrics + hybrid_metrics + deltas + hard_constraints + per_query_comparison + reproducibility，无 enters_default_path。
- contracts/legal-domain-baseline-report.schema.json：同构，report_type=legal_domain_baseline，额外含 cross_reference_benefit 块（baseline_metrics/graph_metrics/mrr_improvement_pct/ndcg_improvement_pct/recall_non_decreasing/vocabulary_disposition——沿用 010 cross_reference_comparison_report 结构）。

字段语义复用 002 eval-comparison-report.schema.json（metricBlock/latencyBlock/hard_constraints/reproducibility 结构一致）。

**Rationale**: 加法新 schema 不修改 002/003 既有报告契约（宪法 VII）；generic 与 legal 两份独立（legal 多一个受益块），按 spec FR-009"两份"忠实落地。

**Alternatives**: 复用 002 schema 加可选字段（否决：additionalProperties:false 会拒绝新字段，且 report_type const 需改）；一份 schema 用枚举 report_type（否决：spec 明言"两份"，且 legal 受益块使结构分化）。

---

## R7 语料入库全链路（007–010 复用）

**Decision**: 语料入库走既有链路，无新摄入代码：域档案格式校验（personal/generic/legal 的 supported_formats）→ FormatHandler 注册表分发（markdown/txt/html/csv 走 008 转换层/原生路径；word/pdf 走 003 原生解析器）→ 凭据脱敏 → 切片 → 版本发布。入库由运行器脚本负责（沿用 run_cross_reference_comparison.py 的幂等 scope 创建 + ingest + 发布模式），语料落 eval/corpora/generic/（新增）与 eval/corpora/legal/（扩充）。

**Rationale**: 011 不新增摄入路径（输入硬约束）；运行器自建 scope + 幂等入库保证评测可重放（SC-010）。

**Alternatives**: 经管理面上传语料（否决：不可脚本化重放，且需手动 scope 配置）；新写入库脚本绕过注册表（否决：违反 008 单一事实源）。

---

## R8 personal 内置域档案落地（第四内置）

**Decision**: config/domain_profiles.py 的 BUILTIN_DOMAIN_PROFILES 新增 personal 行：
- domain_key=personal；name="Personal Knowledge"；description 定位个人/团队知识库域。
- supported_formats = 通用格式族全集（markdown/word/pdf/html/txt/csv/json/yaml/xml/xlsx/pptx/eml，与 generic 一致）——评测语料仅用其中 4 格式。
- graph_relations={}（空词表，无图）；prompt_overrides 用 NEUTRAL_PLANNER_PROMPT（与 generic 一致）；default_capabilities={retrieval_modes:["dense","hybrid"], has_graph:false}；is_builtin=true（007 只读保护 + 启动同步）。

**Rationale**: 蓝图 §3.1 明言"legal/personal 等域档案由 011 评测语料建设时落地"；personal 是 generic 同族的个人知识库语义档案（格式集全集保证"个人知识库可持有任意通用文档"语义自洽），其价值在 domain_key 语义轴（list_knowledge_domains 语义区分 + 未来 prompt_overrides/chunk_type 扩展挂载点），符合宪法 XI（域差异经档案声明、不硬编码）。

**Alternatives**: 不落地 personal、个人域直接用 generic（否决：蓝图明确要求 personal 落地，且丢失去 personal 域语义挂载点）；personal 格式集仅 4 格式（否决：档案语义应自洽，评测语料覆盖≠档案能力面）。

---

## R9 交叉引用受益再验证（Q1=A 双分支闸口）

**Decision**: 新增 eval/run_legal_benefit.py（或参数化复用 010 run_cross_reference_comparison.py），在 011 富化法律语料上重运行"同会话混合基线臂 vs 图增强臂（混合 + 交叉引用扩展）"对照，闸口沿用 010 FR-030：MRR 与 nDCG 均值相对提升 ≥3% + Recall 非降 + 硬指标全过。受益子集 = legal_domain_eval_dataset.json 中 is_structural_benefit 条目（≥6，含 ≥1 中文条文引用）。图边提取沿用 010 runner 的注册表显式触发机制（不改变 cross_reference 提取器行为）。
- **达标分支**：更新 legal 内置档案 graph_relations={references,referenced_by} + default_capabilities.has_graph=true + retrieval_modes 增 graph_enhanced（与 se-project 同构）——交叉引用图扩展进入 legal 默认检索路径。
- **未达标分支**：维持 R11 空词表现状（cross_reference 不为 legal 默认触发、可由自定义档案显式启用），如实记录。
- **零可测图边**：记录"无可测量受益"（宪法 III），按未达标分支处置。

**Rationale**: 010 的失败仅在 3 文件最小语料上测得；蓝图把"交叉引用受益验证"明确列入 011 法律域职责，且 010 FR-030 已定义双分支语义（Q1=A 决议回写）。受益测量独立于域基线的 dense/hybrid 部分（基线=dense vs hybrid；受益=hybrid vs hybrid+graph）。

**Alternatives**: 仅记录不处置词表（否决：Q1=A 决议明确带闸口后果）；重新实现提取器（否决：提取器 010 已交付，011 仅消费）。

---

## R10 前端中英文切换：轻量自建资源层（零依赖）

**Decision**: 前端 i18n 采用轻量自建方案，不引入 react-i18next/i18next：
- frontend/src/i18n/{index.ts, zh.ts, en.ts}：类型化双语字典（zh/en）+ LocaleProvider（React Context）+ t(key) hook + localStorage 持久化（键如 rag-mcp.locale）。
- App.tsx：ConfigProvider 挂 locale（antd 官方 zhCN / enUS）随语言切换；Header 增语言切换器。
- 三页面硬编码字符串迁移为 t(key)，约 65 处 × 2 语言。
- 默认语言英文（现状零破坏）；浏览器语言自动检测为可选增强（plan 已预留，默认不做）。
- 范围约束：后端错误消息（err.message）与领域数据（项目名/文件名/slug/domain_key/状态码）原样展示不翻译（FR-029）。

**Rationale**: 规模仅 3 页面 ~65 字符串，i18next 过重且引入新依赖；antd 官方 locale 已覆盖框架组件文案（分页/日期/模态确认）；自建资源层满足 spec FR-027~FR-031 全部判据（切换/持久化/默认英文/零残留/后端零改动）。

**Alternatives**: react-i18next（否决：65 字符串规模不匹配 + 新依赖 + 无翻译后台需求）；仅 ConfigProvider 挂 zhCN 无切换器（否决：正是要补的"切换"缺口）；后端文案一并多语言化（否决：用户明确排除）。

---

## R11 全集回归口径与不覆盖纪律（001–006）

**Decision**: 新增 eval/run_regression_011.py 编排六组重跑，每组按各自既有口径、产物落 011 前缀新文件（不覆盖历史报告）：

| Feature | 重跑命令（示意） | 口径 |
|---------|------------------|------|
| 001 | run_eval.py --mode dense --dataset eval/eval_dataset.json（前 11 条） | Dense 基线 11 条 |
| 002 | run_comparison.py --dataset eval/eval_dataset.json --limit 18 | 混合对照 18 条 |
| 003 | run_eval.py --mode dense（前 37 条）+ run_comparison 逐格式 | 格式集 37 条 + 逐格式 |
| 004 | run_graph_comparison.py --dataset eval/eval_dataset.json --limit 37 | 图集 37 条（索引 0–36） |
| 005 | run_agentic_comparison.py（组合数据集全量） | agentic 63 条（56+7） |
| 006 | run_instance_form_smoke.py | 双形态各 11 条 |

非延迟指标 1% 相对容差内一致；010 交叉引用口径（cross_reference_comparison_report.json 的 runner）显式复跑确认行为不变（其 runner 经注册表显式触发提取器，不依赖 legal 档案词表）。001/003 若 run_eval.py 无 --limit，则以"数据集前 N 条"通过既有的数据集截取或薄封装实现（沿用 010 为 run_graph_comparison.py 增 --limit 的同类先例，最小加法）。

**Rationale**: 无回归义务是每个 Feature 的既定纪律（蓝图 §6）；011 改 legal 档案 + 扩评测语料，是 2.0 定稿前最后一道全量回归闸口。

**Alternatives**: 覆盖历史报告（否决：破坏基线可追溯性）；仅重跑 004/010 相关（否决：spec FR-016 明列六组全量）。

---

## R12 多域验收与 2.0 定稿工件

**Decision**:
- 多域验收记录落 eval/（如 multi_domain_acceptance_report.json 或 quickstart 形态），含三件套逐条实测（串库/Schema/定位）、四类引用场景、writer/reader 双形态冒烟结果；DeepSeek Harness 为必过参考客户端。
- 2.0 演进目标逐项核销记录落 docs/2.0-finalization.md（独立工件，蓝图正文冻结），§1.3 五项目标各附达成判定 + 证据工件指针（目标 1→007 domain_scope + 011 多域验收；目标 2→008 注册表边际成本记录；目标 3→008 格式集验收 + 011 个人域语料覆盖子集；目标 4→011 两域评测集与基线 + 001–006 回归；目标 5→011 硬指标三件套实测）。
- 文档债（roadmap 至 2.0 状态、README 纠正、001–006 及 007–010 spec Status 统一为已交付态）在既有文件就地更新。

**Rationale**: 多域验收是 domain_scope/list_knowledge_domains 价值的全链路实证；核销记录独立于蓝图（蓝图批准即冻结为架构基线，§9 纪律）。

**Alternatives**: 改写 2.0 蓝图正文记录定稿（否决：违反冻结纪律）；核销记录并入 roadmap 而不立独立工件（否决：roadmap 是迭代史，核销记录是目标对账，职责分离更清晰）。
---

## R13 legal:article 条文 chunk_type 不落地（clarify 决议）

**Decision**: 011 不落地 legal:article 条文 chunk_type 扩展——legal 档案 chunk_type_extensions 保持 None，条文结构由通用标题/章节 chunk 承载（Word 标题路径 / PDF page:N §编号定位）；graph_relations/references 仍由 Q1=A 双分支闸口决定（R9）。该决议源于 clarify 阶段（spec Clarifications Session 2026-09-07 clarify 阶段）。

**Rationale**: 新增 legal:article 类型需 word/pdf 解析器产出该命名空间 chunk_type（parser 侧变更），超出 011「仅新增语料/评测集/报告/文档与验收，无新检索路径」边界；现有标题层级已满足条文结构检索定位（FR-004/SC-004）。PDF 中文「第X条」标题识别限制已记录于 spec Edge Cases（由数字编号 X.Y 承载）。

**Alternatives**: 声明 legal:article + 改造解析器（否决：parser 变更 + 无评测证明其检索收益，触发条件未满足，蓝图 §9）；声明但不产出（否决：空声明无意义，与 008 两级词表「声明即消费」语义不符）。

