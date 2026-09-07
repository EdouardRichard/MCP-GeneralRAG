# Data Model: 通用域评测与多域验收（011）

**Branch**: 011-generic-domain-evaluation | **Date**: 2026-09-07 | **Spec**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

> 011 不新增任何物理表。变更面 = domain_profiles 两行内置种子（personal 新增 + legal 行格式/词表扩展）、两份评测数据集 JSON、两份域基线报告 JSON、前端语言资源（代码级）与运行器薄入口。检索路径/图模型/契约/能力门控零改动。下列为模型级草图，完整实现与任务拆分属 tasks 阶段。

---

## 1. 实体总览（变更面）

| 实体 | 物理载体 | 变更 | 来源 FR |
|------|----------|------|---------|
| personal 域档案 | domain_profiles 表（种子） | 新增第四内置行（通用格式族/空词表/域中立提示词/is_builtin） | FR-001（R8） |
| legal 域档案 | domain_profiles 表（种子） | supported_formats 扩展 [markdown,word,pdf]；graph_relations 视受益闸口（Q1=A） | FR-003/FR-011（R9） |
| 个人/团队域评测集 | eval/generic_domain_eval_dataset.json | 新增：≥10 条，domain_scope + expected_heading 锚点 | FR-005~FR-007（R2） |
| 法律域评测集 | eval/legal_domain_eval_dataset.json | 新增：≥10 条，条文结构 + 交叉引用受益子集 | FR-005~FR-007（R2） |
| 域基线报告（×2） | eval/*_domain_baseline_report.json | 新增：dense/hybrid 双路径 + P50/P95 + 逐查询 + 硬指标 + 可重复性；非约束性锚点 | FR-008~FR-011（R1/R5/R6） |
| 前端语言资源 | frontend/src/i18n/{index,zh,en}.ts（代码级） | 新增：双语字典 + LocaleProvider + 持久化 | FR-027~FR-031（R10） |
| 全集回归记录 | eval/011_*_regression_report.json | 新增：001–006 重跑产物（不覆盖历史） | FR-016/FR-017（R11） |
| 多域验收记录 | eval/multi_domain_acceptance_report.json | 新增：硬指标三件套逐条实测 + 四类引用场景 + 双形态冒烟 | FR-014/SC-003（R12） |
| 2.0 定稿核销记录 | docs/2.0-finalization.md | 新增：§1.3 五项逐项核销 + 证据指针 | FR-021（R12） |

零改动面（回归闸口对象）：检索路径（dense/hybrid/graph/agentic）、graph_edge/soft_relation、MCP 契约、FormatHandler 注册表、转换层、001–006 既有评测集与报告、Chunk/Qdrant payload。

---

## 2. domain_profiles 种子变更

### 2.1 personal 内置档案（新增，第四内置，R8）

| 字段 | 值 | 依据 |
|------|-----|------|
| domain_key | personal | FR-001 |
| name / description | Personal Knowledge / 个人/团队知识库域：通用文档格式、无图关系、域中立提示词 | — |
| supported_formats | 通用格式族全集（markdown/word/pdf/html/txt/csv/json/yaml/xml/xlsx/pptx/eml，与 generic 一致） | 档案语义自洽；评测语料仅用其中 4 格式 |
| graph_relations | {}（空词表） | 无图路径（FR-001） |
| chunk_type_extensions | null | 沿用通用 chunk_type |
| prompt_overrides | NEUTRAL_PLANNER_PROMPT（与 generic 一致） | 域中立（FR-001） |
| default_capabilities | {retrieval_modes:["dense","hybrid"], has_graph:false} | 无图词表自洽 |
| is_builtin | true | 007 只读保护 + 启动同步 |

### 2.2 legal 内置档案（扩展，Q1=A 两分支，R9）

| 字段 | 达标分支 | 未达标分支（维持 R11 现状） |
|------|----------|------------------------------|
| supported_formats | [markdown, word, pdf] | [markdown, word, pdf]（格式扩展与受益闸口解耦，始终生效） |
| graph_relations | {references:["out","in"], referenced_by:["out","in"]} | {}（空词表） |
| default_capabilities | {retrieval_modes:["dense","hybrid","graph_enhanced","agentic"], has_graph:true} | {retrieval_modes:["dense","hybrid"], has_graph:false} |

- 格式扩展（[markdown]→[markdown,word,pdf]）为声明式配置变更，与受益闸口结果解耦、始终落地（承载 Word/PDF 语料必需，FR-003）。
- graph_relations 与 has_graph 仅在受益闸口达标时启用（Q1=A 双分支，FR-011/SC-007）；两分支的 default_capabilities 与空词表/词表自洽（010 T060 先例）。

---

## 3. 域评测数据集条目模型（R2）

两份数据集条目共形，契约见 [domain-eval-dataset.schema.json](./contracts/domain-eval-dataset.schema.json)。核心字段：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| query | string | 必填，非空 | 查询文本 |
| domain_scope | string[] | 必填，≥1 | slug / 数字 scope ID（slug 优先） |
| expected_heading | string | 必填 | 结构锚点：标题路径末段/定位前缀（跨环境稳定） |
| format | enum | 可选 | 个人域覆盖审计 / 法律域语料格式（markdown/txt/html/csv/word/pdf） |
| language | enum(zh,en) | 必填 | 查询语言 |
| is_structural_benefit | boolean | 可选，默认 false | 仅法律域交叉引用受益子集 true |
| _meta.review_status | string | 必填 reviewed | 人工审核标记 |
| _meta.review_notes / grounded_source | string | 建议 | 审核说明 / 锚定语料 |

- 覆盖约束（FR-006）：个人域 markdown/txt/html/csv 每格式 ≥2 条（≥1 自然语言 + ≥1 结构定位）且 ≥2 条中文；法律域条文结构 ≥4 + 交叉引用受益 ≥6（含 ≥1 中文条文引用）且 ≥2 条中文；总数各 ≥10。
- 零破坏约束（FR-007/FR-026）：独立文件，不追加进 eval_dataset.json / agentic_eval_dataset.json；条目一经入库不可破坏既有条目（字段只增不改不删）。

---

## 4. 域基线报告模型（R5/R6）

两份报告共形（generic / legal），契约见 [domain-baseline-common.schema.json](./contracts/domain-baseline-common.schema.json) 与两份报告 schema。核心结构：

~~~text
{
  report_type: "generic_domain_baseline" | "legal_domain_baseline",
  generated_at, config{domain_key, dataset_path, num_queries, embedding/reranker, modes},
  dense_metrics{recall_at_k,mrr,ndcg_at_k,latency_ms{p50,p95,mean}},
  hybrid_metrics{...同构...},
  deltas{mrr_mean_delta, ndcg_mean_delta, recall_mean_delta, latency_p50/p95_delta_ms},
  hard_constraints{cross_domain_leakage_events, schema_validity_rate, source_locatability_rate, all_passed},
  per_query_comparison[{query_index, query, domain_scope, expected_heading, dense_rank, hybrid_rank, ...分数}],
  reproducibility{non_latency_reproducible, tolerance, checks[]},
  // 仅 legal：
  cross_reference_benefit{baseline_metrics, graph_metrics, mrr_improvement_pct, ndcg_improvement_pct,
                          recall_non_decreasing, three_gate_pass, vocabulary_disposition}
}
~~~

- **非约束性锚点**：无 enters_default_path 字段；dense/hybrid 相对差仅信息性记录；不设最低水位门槛（R5）。
- 硬指标字段沿用 002 语义（泄漏事件数、Schema 合法率、定位率），但以"跨域"语义（cross_domain_leakage_events）命名。
- 可重复性：非延迟指标 1% 相对容差；延迟指标环境敏感、不进容差判定。

---

## 5. 前端语言资源模型（R10）

| 层 | 载体 | 说明 |
|----|------|------|
| 双语字典 | zh.ts / en.ts | 类型化键值：全部前端自产文案（约 65 键 × 2 语言） |
| 资源层 | index.ts | t(key) hook + LocaleProvider（React Context）+ localStorage 持久化（键 rag-mcp.locale） |
| 组件 locale | App.tsx ConfigProvider | antd zhCN / enUS 随语言切换 |
| 范围边界 | — | 后端错误消息 / API 响应 / 领域数据（项目名/文件名/slug/domain_key/状态码）原样展示不翻译（FR-029） |

- 键命名：按页面分组（projects./projectDetail./domainProfiles./common.），缺失键回落英文（确定性，不空白不崩溃）。
- 默认语言英文（现状零破坏）；浏览器语言自动检测为可选增强（R10 默认不做）。
- 零残留验收（FR-030/SC-011）：中文态英文残留 = 0、英文态中文残留 = 0。
