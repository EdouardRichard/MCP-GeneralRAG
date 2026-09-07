# Evaluation Suite

固定评测集与对照评测运行器（蓝图 §24，宪法原则 X：评测驱动优化）。

## 数据集

- **`eval_dataset.json`** — 唯一固定评测集（37 条，JSON 数组）。每条含
  `query` / `project_scope` / `expected_evidence_ids`；003 起新增条目带
  `format`；004 起结构性受益条目带 `is_structural_benefit: true`。
  - 前 11 条：001 Dense 基线（Markdown + Java），对照
    `baseline_report.json`。
  - 前 18 条：002 混合检索基线集合，对照 `hybrid_comparison_report.json`。
  - 004 新增 ≥6 条结构性受益查询（Java 调用链 / DDL 外键链路，含 ≥1 条中文，
    `is_structural_benefit` 标记，共 7 条）；原既有查询全部保留，保证与
    基线逐条可比（FR-021）。
- **generic_domain_eval_dataset.json** — 011 个人/团队通用知识库域固定评测集
  （13 条，独立文件）。每条含 query / domain_scope（slug 寻址）/
  expected_heading（跨环境稳定结构锚点）/ format / language /
  _meta.review（人工审核记录）；覆盖 markdown/txt/html/csv 每格式 ≥2 条
  （≥1 自然语言 + ≥1 结构定位）+ ≥2 条中文。
- **legal_domain_eval_dataset.json** — 011 法律合规域固定评测集（11 条）。
  条文结构子集 ≥4 条（Word「第X条」标题路径 + PDF「X.Y」数字编号定位）+
  交叉引用受益子集 ≥6 条（is_structural_benefit: true，含中文条文引用查询）。
- 约定：查询由 AI 生成、人工审核后入库；字段结构不得破坏既有条目；
  011 数据集为独立文件，不追加进 eval_dataset.json /
  agentic_eval_dataset.json（零破坏，SC-001）。

## 基线报告（历史产物，勿覆盖）

| 报告 | Feature | 说明 |
|------|---------|------|
| `baseline_report.json` | 001 | Dense-only 确定性基线（11 条） |
| `hybrid_comparison_report.json` | 002 | Dense+Sparse+RRF+Rerank 混合基线（18 条；硬指标实测 + original_subset_gate，见下） |
| `format_expansion_report.json` | 002/003 | 逐格式对照（由 run_comparison.py 一并产出） |
| `quickstart_001_report.json` | 001 | quickstart VS-001~VS-013 验收记录（T057 工件，由 test_quickstart_001_report.py 落盘） |
| `regression_report.json` | 003 | 格式扩展回归 |
| `graph_enhanced_comparison_report.json` | 004 | 图增强对照评测（37 条，见下） |
| `agentic_comparison_report.json` | 005 | 三 Agent 编排对照评测（44 条，数据集 `agentic_eval_dataset.json`） |
| `instance_form_smoke_report.json` | 006 | writer/reader 双形态冒烟对照（各 11 条，单侧非回归判定） |
| `010_graph_regression_report.json` | 010 | 004 图集 37 条无回归重跑（`--limit 37`，不覆盖历史报告） |
| `cross_reference_comparison_report.json` | 010 | 交叉引用受益对照（法律域语料 + ≥6 条受益子集） |
| `generic_domain_baseline_report.json` | 011 | 个人/团队域基线（非约束性对照锚点，dense/hybrid 双路径 13 条，历史产物勿覆盖） |
| `legal_domain_baseline_report.json` | 011 | 法律域基线（同构 + cross_reference_benefit 块，11 条，历史产物勿覆盖） |
| `legal_benefit_result.json` | 011 | 交叉引用受益再验证记录（闸口未达标 → kept_empty_r11 处置） |
| `multi_domain_acceptance_report.json` | 011 | 多域端到端验收记录（场景清单 + 硬指标三件套逐条实测 + 参考客户端结论） |
| `011_00*_regression_report.json` + `011_regression_summary.json` | 011 | 001–006 六组口径无回归重跑（011 前缀新文件，历史报告零覆盖） |

## 运行器

| 脚本 | 用途 |
|------|------|
| `run_eval.py` | 单路径评测（dense/hybrid），产出指标 + 可重复性检查；hybrid 模式接入 Reranker（对齐生产路径） |
| `run_comparison.py` | 002：Dense vs Hybrid 对照（硬指标逐条实测；enters_default_path 按原 11 条子集严格正增量判定，报告含 original_subset_gate 明细） |
| `run_graph_comparison.py` | 004：混合基线同会话重跑 + 图增强对照（FR-022/023/025） |
| `run_agentic_comparison.py` | 005：确定性基线 vs 三 Agent 编排对照（独立数据集） |
| `reindex_eval_qdrant.py` | 004：从 PG 已持久化 Chunk 重建评测语料的 Qdrant 混合向量（派生数据重建，蓝图 §8.4/FR-016）；chunk_id 不变，评测集期望证据 ID 保持有效 |
| `ingest_domain_corpora.py` | 011：两域语料幂等入库（public+personal/generic/legal 每文件一 scope，域档案格式族校验；`--dry-run` 仅校验） |
| `run_domain_baseline.py` | 011：域基线薄入口（复用 run_eval/run_comparison 内核；dense 走 hybrid 集合命名向量，hybrid 全路径；报告经契约 schema 校验，拒覆盖已有报告） |
| `run_legal_benefit.py` | 011：交叉引用受益再验证（注册表显式触发提取器；Q1=A 双分支闸口；产出 vocabulary_disposition 记录） |
| `run_multi_domain_acceptance.py` | 011：多域端到端验收（发现 → 三形态寻址 → 检索 → 展开 + 硬指标三件套实测；落盘验收记录） |
| `run_regression_011.py` | 011：001–006 六组口径无回归重跑编排（011 前缀新文件；单侧非回归判定 + 双侧容差记录） |

### 002 固定验收集约定

数据集会随后续 Feature（003/004）追加条目；002 的验收记录固定为**前 18 条**
（001 原 11 条 + 002 新增 7 条词汇精确查询）。重跑 002 对照报告必须携带
`--limit 18`：

```bash
python eval/run_comparison.py \
    --dataset eval/eval_dataset.json \
    --output eval/hybrid_comparison_report.json \
    --limit 18
```

`enters_default_path` 仅在前 11 条（001 基线子集）上判定（**相对口径**，
research.md §0.2/§0.6 2026-09-04 修订）：MRR/nDCG 相对同会话 Dense 基线
严格正增量 + Recall 非降 + 实测硬指标全过；绝对水位仅作参考记录、不作门禁。
2026-09-04 重跑终态：原 11 条 MRR +2.0% / nDCG +1.45% 相对提升
（0.7576→0.7727、0.8203→0.8322）、Recall 1.0 持平、硬指标实测全过
（泄漏=0 / Schema=1.0 / 定位=1.0，70 条证据逐条测量）、validateToken
rank 3→2、非延迟可重复通过，**enters_default_path=true**——混合检索进入
默认检索路径（SC-001/FR-021 达成）。报告含 `original_subset_gate` 审计明细
（含相对提升百分比），并通过契约 schema 校验。

### 004 图增强对照评测

```bash
# （如 Qdrant 中评测语料向量缺失）先重建向量：
python eval/reindex_eval_qdrant.py --dataset eval/eval_dataset.json

# 运行对照评测：同会话先重跑混合基线（FR-025），再跑图增强路径
python eval/run_graph_comparison.py \
    --dataset eval/eval_dataset.json \
    --output eval/graph_enhanced_comparison_report.json
```

产出 `graph_enhanced_comparison_report.json`，符合
`specs/003-structured-asset-expansion/contracts/eval-graph-comparison-report.schema.json`：

- `baseline_metrics` / `graph_metrics`：Recall@K、MRR、nDCG@K、P50/P95 延迟；
- `structural_subset_metrics`：结构性受益子集相对提升（SC-001 闸口，≥3%）；
- `three_gate_pass`：SC-001 提升 + SC-002 001 非劣（Recall 精确、MRR/nDCG 1%
  容差）+ SC-013 002 非结构性非劣 + 硬性指标（泄漏=0 / Schema 100% / 定位 100%）；
- `per_query_comparison`：逐查询基线排名 vs 图增强排名 + Dense/Sparse/融合
  分数 + 图扩展路径分数（关系类型/跳数/结构权重，FR-023/SC-008）；
- `reproducibility`：非延迟指标 1% 容差可重复（SC-007）；延迟环境敏感；
- `enters_default_path`：仅当三段 + 硬性指标全过为 `true`（FR-024）。

### 010 图关系注册表评测（004 图集无回归 + 交叉引用受益）

```bash
# 004 图集 37 条无回归重跑（插件化纯重构，1% 相对容差）
python eval/run_graph_comparison.py \
    --dataset eval/eval_dataset.json \
    --output eval/010_graph_regression_report.json \
    --limit 37

# 交叉引用受益对照（法律域语料 + ≥6 条受益子集，SC-002 ≥3% 闸口）
python eval/run_cross_reference_comparison.py \
    --dataset eval/cross_reference_eval_dataset.json \
    --output eval/cross_reference_comparison_report.json
```

- `--limit 37`：`run_graph_comparison.py` 自 010 增补的 `--limit N` 参数
  （沿 `run_comparison.py` 先例），004 图集口径 = `eval_dataset.json` 索引
  0–36 共 37 条；不覆盖 `graph_enhanced_comparison_report.json` 历史报告。
- `cross_reference_eval_dataset.json`：法律域受益子集 ≥6 条（含中文条文引用
  查询），独立数据集文件（不追加进 `eval_dataset.json`，避免污染 004 37 条
  回归口径）。
- `corpora/legal/`：虚构法规语料（主法规 `## 第X条` 结构 + 实施细则 +
  引用性文件，覆盖内部锚点 / 跨文件相对链接 / 中文条文引用三类形态）。

### 011 通用域评测与多域验收

```bash
# 1. 两域语料幂等入库（personal/generic/legal；--dry-run 仅做格式族校验）
python eval/ingest_domain_corpora.py

# 2. 交叉引用受益再验证（Q1=A 双分支闸口；产出 legal_benefit_result.json）
python eval/run_legal_benefit.py

# 3. 两份域基线报告（历史产物，一经产出不得覆盖重写）
python eval/run_domain_baseline.py \
    --dataset eval/generic_domain_eval_dataset.json \
    --output eval/generic_domain_baseline_report.json \
    --domain-key personal
python eval/run_domain_baseline.py \
    --dataset eval/legal_domain_eval_dataset.json \
    --output eval/legal_domain_baseline_report.json \
    --domain-key legal --benefit-report eval/legal_benefit_result.json

# 4. 多域端到端验收记录（硬指标三件套逐条实测）
python eval/run_multi_domain_acceptance.py

# 5. 001–006 全集回归（六组口径重跑，单侧非回归判定）
python eval/run_regression_011.py
```

要点：

- **scope 布局**：系统知识版本模型每 scope 仅保留一个活跃快照（重入库
  supersede 会清除先前 chunk），011 遵循 001/008 每文件一 scope 先例
  （scope slug 见 ingest_domain_corpora.py 的 SCOPE_SPECS）。
- **域基线为非约束性对照锚点**：不含 enters_default_path、不设最低水位
  门槛；后续通用域优化 Feature 进 plan 前须在 research.md 相对本基线
  声明目标（宪法 X / 1.0 §24.3 纪律延伸）。
- **受益再验证结论（2026-09-07）**：法律域富化语料上 MRR −9.09% /
  nDCG −6.55%，闸口未达标 → legal 档案维持空图词表（kept_empty_r11），
  cross_reference 仍可由自定义档案显式启用。
- **回归比对语义**：单侧非回归门禁（重跑不得比历史差超 1% 容差；改善
  超容差记录为 within_tolerance=false 但 no_regression=true，006 冒烟
  先例——001 口径的既有漂移源于 008 语料重入库，非 011 引入）。

### 可配置开关与默认路径

图增强检索是**可配置开关**，不替换 001/002 确定性默认路径：

- 环境变量 `GRAPH_ENHANCED_RETRIEVAL_ENABLED`（默认 `false`）。
- 仅当对照评测 `enters_default_path=true`（三段通过 + 硬性指标全过）后，
  运维方可启用该开关使图增强进入默认检索路径；未达阈值则图扩展作为可选
  检索路径保留（宪法原则 X / FR-024）。
- 其余图护栏均可经环境变量覆盖且不超过上限（`GRAPH_HOP_DEFAULT`=2/
  `GRAPH_HOP_MAX`=3、`GRAPH_CANDIDATE_BUDGET`=10/上限 20、
  `GRAPH_SUB_TIMEOUT_MS`=3000、`GRAPH_TOTAL_TIMEOUT_MS`=30000、
  `GRAPH_DIRECTION_DEFAULT`=bidirectional、结构权重与软关系阈值，见
  `backend/src/rag_mcp/config.py` GraphConfig）。

## 环境说明

- 数据库与 Qdrant 为共享开发环境（`DATABASE_URL` / `QDRANT_URL`）。
  评测语料的 PG Chunk 持久存在；Qdrant 向量如被清空，用
  `reindex_eval_qdrant.py` 重建（chunk_id 不变）。
- 评测前会为数据集作用域内的 Java/DDL 已发布版本执行图关系重建并声明
  `graph_ready`（等价用户触发重建，FR-027；幂等）。
