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
python eval/run_multi_domain_acceptance.py --output eval/runs/011-rerun/multi_domain_core_report.json

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

### 012 记忆写读闭环最终验收

最终串行后端回归和真实 DSH `temp` 双实例证据登记如下；报告路径使用新文件，
不覆盖历史评测产物：

```bash
python -m pytest -vv --tb=short --durations=30 \
  --junitxml=eval/runs/012-20261005-final-regression-h/backend-pytest.xml
python eval/run_memory_acceptance.py \
  --suite eval/runs/012-20261005-final-regression-h/backend-pytest.xml \
  --trace eval/runs/012-20261005-final-regression-h/memory-trace.json \
  --host eval/runs/012-20261005-final-regression-h/host-evidence.json \
  --diagnostics eval/runs/012-20261005-final-regression-h/read-diagnostics.json \
  --output eval/runs/012-20261005-final-regression-h/final-memory-report-verified.json \
  --regression \
    eval/runs/012-20261005-final-regression-f/retrieval/012_regression_summary.json \
    eval/runs/012-20261005-final-regression-f/retrieval/012_002_regression_report.json \
    eval/runs/012-20261005-final-regression-f/retrieval/012_004_regression_report.json \
    eval/runs/012-20261005-final-regression-f/012_generic_domain_report.json \
    eval/runs/012-20261005-final-regression-f/012_legal_domain_report.json \
    eval/runs/012-20261005-final-regression-f/012_multi_domain_core_report.json
```

验收目录 `eval/runs/012-20261005-final-regression-h/` 保存 JUnit、memory trace、
read diagnostics、DSH writer/reader 原始会话日志、host evidence 和 schema 校验后的
最终报告。最终套件为 2142 passed、0 failed、0 skipped，SC-001–SC-017 全部通过。

### 013 记忆巩固回路评测与证据索引

013 的评测面完全复用上表原有 runner（001–012 口径不变），新增巩固专属的
真实 E2E/AOEP/故障证据导出、冻结数据集、六路独立还原 runner 与
record→replay 对照 runner。**发布结论仍为 `incomplete`**：真实对照已执行，
但部署闸门不授予任何权限（报告 `incomplete`、`default_enable_eligible=false`、
`gate_binding=null`，T103 证明即使被安装也只得到 `GATE_VARIANT_NOT_AUTHORIZED`），
`consolidation_enabled` 与 `link_expansion_enabled` 保持 `false`，未向任何生产
gate registry 安装登记。

已执行的命令、逐条计数与限制见
[013 quickstart](../specs/013-memory-consolidation-loop/quickstart.md)
“Phase 8 verification (2026-10-07, T090–T104)”；本节只登记**新证据路径**，
全部为新文件，未覆盖任何历史产物：

| 证据 | 路径 | 说明 |
|---|---|---|
| 冻结评测数据集 | `eval/consolidation_eval_dataset.json`（入库） | 6 条真实 query 绑定真实语料 chunk 与 10 条真实 memory event（scope `366084747748704256`），含合法 lineage、等价组与冻结版本 |
| 权威快照 | `…/phase8-evidence/t095-20261007/authority-snapshot.json` | 可重建 authority 导出（digest `9b05336c…`）、已发布 policy、冻结 clock |
| 六路独立还原 | `…/phase8-evidence/t097-20261007/` | capsule 索引、两份 restore receipt、run identities 与还原日志 |
| 013 E2E/AOEP/故障导出 | `…/phase8-evidence/t099-20261007/` | `consolidation-trace.json`（19 条真实 nodeid + 服务调用）、`authority-snapshot.json`（6 scope）、`dataset-manifest.json`；未观测硬指标保持 `null`，绝不伪造成 0 |
| 013 资格/依赖/恢复/晋升/非空重建 | `…/phase8-evidence/t099-qualification-20261007/` | 8 个 013 集成文件 51 passed 的日志；这些文件不请求 013 证据 fixture，故导出清单如实为空 |
| 012 acceptance 复跑 | `…/phase8-evidence/t100-012-20261007-clean/` | `backend-pytest.xml`、`memory-trace.json`、`read-diagnostics.json`、`host-evidence.json`（`not_verified`）、`012-acceptance.json`（`failed`） |
| 001–006 六组回归 | `…/phase8-evidence/t101-20261007/regression/`（原始输出在 worktree `eval/runs/013-20261007-t101-retrieval/`） | `012_regression_summary.json` + `012_001`…`012_006` 分组报告与 runner 日志 |
| 后端 unit/contract 全集 | `…/phase8-evidence/t101-20261007/unit-contract.log` | `tests/unit tests/contract`：2389 passed，1 处 CRLF 环境失败 |
| 后端 integration 全集 | `…/phase8-evidence/t101-20261007/integration/` | `tests/integration` 853 例（839 passed / 13 failed / 1 error）+ JUnit + 进度日志 |
| 011/012 域组 | `…/phase8-evidence/t101-20261007/domains/`（原始输出在 worktree `eval/runs/013-20261007-t101-domains/`） | generic/legal 基线、legal benefit、multi-domain core |
| **T102 record/replay 真实报告（2026-10-07，已被下表取代）** | `…/phase8-evidence/t102-20261007/` | 历史证据：`comparison-record.json`、`cache-manifest-record.json`、`llm-cache/strict-v1/`、`run-record/`。其中的 +14.3 %/+18.5 % "受益" 与 "42 KB 提示" 已确认是仪器缺陷产物，见下 |
| **T102 最终 record/replay（2026-10-08，修复四个确定缺陷后）** | `…/phase8-evidence/t102-20261008-final/` | `comparison-record.json` + `comparison-replay.json`（两轮均 `failed`、`validation accepted`）、`cache-manifest-record.json`（2 key：1 成功 + 1 失败）、`cache-manifest-record.json.cache/strict-v1/`、`run-record/`、`run-replay/`、`record.log`、`replay.log`；`llm_calls 2 / prompt_chars 42 223 / completion_chars 8 072`、重放真实调用 0、非延迟漂移 0.0、`relative_gains` 0.0/0.0、`schema_validity_rate 0.5` |
| **T103 部署闸门模拟** | `…/phase8-evidence/t103-20261007/t103-install-simulation.json` | 纯离线 JSON 证据：真实 `incomplete` 报告被安装后 `GATE_VARIANT_NOT_AUTHORIZED`；fixture 正路径证明撤销/篡改/过期/绑定变更分别拒绝 |

013 专属 runner：

```powershell
# 冻结数据集（真实隔离 scope/语料/policy/history，仅真实定位，不伪造 id）
python .superpowers/sdd/013-tasks/isolation_runner.py eval eval/freeze_consolidation_dataset.py --scope-slug <slug> --domain-key <key> --corpus <md> --output eval/consolidation_eval_dataset.json
# 六路独立还原（seal / allocate / restore / verify / status / stop / drop）
python .superpowers/sdd/013-tasks/isolation_runner.py eval eval/restore_consolidation_arm.py seal --source-database <isolated> --source-data-root <root> --capsule-dir <dir> --scopes <scope> --token <token>
# 对照 runner（契约 CLI：--dataset --snapshot --mode --cache-manifest --gate-variant --suite --trace --memory-acceptance --regression --output）
python .superpowers/sdd/013-tasks/isolation_runner.py eval eval/run_consolidation_comparison.py --dataset eval/consolidation_eval_dataset.json --snapshot <snapshot> --mode record --cache-manifest <manifest> --gate-variant consolidated_candidate_expansion --suite <junit> --trace <trace> --memory-acceptance <012-acceptance> --regression <summary> --output <unique report>
```

T102 真实观测（wall 202.2 s，exit 2 = incomplete）：MRR 0.5833 → 0.6667、
nDCG 0.6488 → 0.7540、HitRate 0.8333 → 1.0、Recall@5 0.8333 → 1.0、
Precision@5 0.2333 → 0.2667，`relative_gains{mrr 0.1429, ndcg 0.1621}` 均过 3%
且三项非降；唯一变化来自 `q_extract_fact_01`。报告仍为 **incomplete**，原因如实
登记：安全计数 `quarantined_inputs`/`schema_validity_rate` 未被本轮观测（两次
`PROVIDER_TIMEOUT` 真实失败回执），`hard_metrics` 保持 `null`；replay 虽以
`response_match_rate=1.0` 消费了真实成功与失败缓存，但仍有真实 provider 调用，
故 `replay_real_network_calls≠0`、`max_non_latency_relative_drift=null`（底层
相对漂移为 `inf`，绝不写成有限值）；数据集中 `q_correct_01`/`q_correct_02` 的
历史/当前两个 relevance unit 在本权威里解析为同一真实 memory，报告记
`RELEVANCE_UNIT_COLLISION`，不伪造第二个 alias。两个 consolidated arm 在本轮
相等，因为链接扩展仍未获授权。

沿用口径与限制（不得把规划/Schema 通过写作功能验收通过）：

- 013 报告只写独立报告：runner 不安装登记、不改域策略、不自动晋升；只有
  `candidate_expansion` 且真实 `passed` 才可能授权，本轮不存在。
- 012 八项与 AOEP 各≥2 维持原断言；`skip`/`missing` 一律不计 pass。
- 本轮 012 acceptance 为 `failed`：历史 `eval/runs/012-20261005-final-regression-a/*`
  在本 worktree 不存在，另有一处旧断言正则与当前守卫文案不符（守卫本身仍拒绝）；
  未削弱任何断言以掩盖。integration 全集的其余失败原因（未构建前端、
  isolated store 中 `013-…` 非法 domain_key、缺失真实 MCP 服务、一次
  Windows PG 连接掉线）逐条登记在 013 quickstart 与 `.superpowers/sdd/013-tasks/phase8-progress.md`。
- 后端 unit/contract 单例失败是本 worktree `core.autocrlf=true` 造成的行尾差异
  （`agentic_eval_dataset.json` / `cross_reference_eval_dataset.json` 的 LF SHA256
  才与 pin 值一致）；改写为 LF 后该文件 14 passed，但 `git checkout` 会再转换，
  持久修复为 `git config core.autocrlf false`（跨 checkout 策略，留待 Lead 决定）。
- 目标 host（`127.0.0.1:3080` 既有 DSH）未执行真实工具调用：18080/18081 无服务监听，
  既有 preset 仍报初始同步失败，故 SC-001/SC-009 记 `not_verified`，不启动替代 host。
- 单次 `tests/unit tests/contract tests/integration` 全量运行在本环境会于约 10% 死锁
  （pytest 进程 957 线程、一条 PG 连接 `idle in transaction` 无阻塞者），因此一律分块串行执行。
- 前端旧 checks（`pnpm build` / `pnpm exec playwright test`）本轮未执行，记为未运行而非通过。
- record→replay 的“次轮真实模型网络 0”本轮**未达成**：封存清单只覆盖 record 轮
  真正落盘的 2 个 key，payload 变动的窗口在 replay 轮只能回源。缺失即记不完整，
  不回填、不修 manifest、不悄悄 LLM 回源。

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

## 013 consolidation benefit gate: current measured state (2026-10-08)

`eval/run_consolidation_comparison.py` runs the frozen six-query comparison with
six independent restorations (own PostgreSQL database, private data root, private
Qdrant process) and a strict record -> replay cache. On the frozen dataset
(`eval/consolidation_eval_dataset.json`) the honest measured state is:

- `quarantined_inputs = 0` (the two superseded memories of the scope stay recorded
  as `excluded_nonactive_ids`), `cross_scope_leaks = 0`, `soft_overturns_hard = 0`,
  `automatic_promotions = 0`, `invalid_outputs_applied = 0`,
  `stale_holder_commits = 0`, `incomplete_outputs_consumed = 0`,
  `rebuild_llm_calls = 0`, `source_chain_complete_rate = 1.0`,
  `projection_integrity_rate = 1.0`;
- replay makes **0** real provider transport calls (`response_match_rate = 1.0`)
  and the sealed cache holds both recorded outcomes (1 success + 1 failure);
- **no retrieval benefit is observed**: baseline and both consolidated arms return
  the same ranking for all six queries, so `relative_gains` are 0.0/0.0 and the
  quality gate fails with `RELATIVE_GAIN_BELOW_THRESHOLD`. Both consolidated arms
  committed nothing (`no_change`); the model package that did arrive was rejected
  by adjudication with `EVIDENCE_UNAVAILABLE`, so consolidation had no effect on
  this authority. (The +14.3 %/+18.5 % gain reported on 2026-10-07 was an artifact:
  `warm_up()` never awaited the async `embed_query`, so the baseline's first
  recorded query paid the model load, hit the reader budget and scored `mrr 0`.
  That defect is fixed and the gain is withdrawn.)
- the blocking observation is `schema_validity_rate = 0.5`: the frozen policy
  bounds the model at `llm_timeout_seconds: 30`, the real provider answered one
  arm (schema-valid package, 8 072 completion chars) and timed out on the other
  (`PROVIDER_TIMEOUT`, cache `output: null`). A `MODEL_SCHEMA_INVALID` entry with
  `output: null` means the provider *did* answer and the package failed the
  contract — the strict client never persists an unvalidated body — so "returned
  nothing" and "returned an invalid package" must not be conflated. Either way the
  zero-tolerance safety gate counts the attempt as not usable.

Consequence: the report stays `failed`, `default_enable_eligible=false`,
`gate_binding=null`, and both `consolidation_enabled` / `link_expansion_enabled`
remain `false`. Reaching `passed` needs a provider that answers the ~21 KB frozen
distiller payload within the frozen 30 s bound (and produces a package the
adjudicator can support with real corpus evidence); nothing is fabricated and the
runner never installs a gate entry or changes policy.

Instruments fixed on 2026-10-08 (all with regression tests in
`backend/tests/unit/test_consolidation_comparison_runner.py`): the report's
`environment.model_version` and the cache manifest now name the model under test
pinned by the gate binding, the safety gate emits the `hard_metrics_zero` check the
shared production validator requires (both previously made `status=passed`
unreachable), one real transport attempt is credited once (a `call_id` distinguishes
the started/settled receipts), and the warm-up is awaited with one discarded real
recall per arm so the first timed query measures retrieval instead of a cold start.

### 015 记忆评测治理与 3.0 定稿（数据集 / 报告 / 运行器）

015 在既有评测面上**只增不破坏**：不改动 001–014 的任何数据集、报告、运行器或测试
断言，新增两份冻结数据集（投毒防护子集、AOEP 状态义务用例）、一份基准报告契约族、
两个薄入口运行器（`run_memory_baseline.py`、`run_regression_015.py`）与一个只读统计
端点。本节登记 015 的数据集、报告与运行器用法及重跑口径，供后续运行者按同一口径复核。

#### 015 基准报告：数据集、报告、运行器与重跑口径（T027–T037 / T070–T071）

**登记的数据集与产物**

| 产物 | 路径 | 口径 |
|---|---|---|
| 投毒防护子集 | `eval/memory_poisoning_eval_dataset.json`（`dataset_version 015.eval.1`） | **19 例**（11 例首次冻结 + convergence 追加 8 例，`amendment` 记录追加与既有用例逐字节不变）：16 例 `role=primary`（覆盖检测器全部 11 条规则面与 4 类变种 `015.variants.1`），3 例 `role=control`（含 `jailbreak_marker`）；硬水位 = 可判 primary 例全数被标记且隔离；`known_misses` 公开登记当前检测器确实漏检的真实同义改写（不进入冻结子集） |
| AOEP 义务用例 | `eval/memory_aoep_obligation_dataset.json`（`015.eval.1`） | 13 例，五条不变量各 ≥2（`traceable_rollback`/`deletion_propagation`/`authority_monotonicity`/`provenance_preservation`/`scope_non_expansion`）；逐例证据携带 `role`/`criterion`/`expected`/`observed`/`scoring`/`sample_sizes`，反例显式 `negative_control` |
| 连续性数据集 | `eval/memory_continuity_eval_dataset.json`（**014** 冻结集，`014.eval.1`） | 16 查询；水位沿 014 冻结判据（`completed_with_memory ≥ 12` 且四类各 ≥1） |
| 受益数据集 | `eval/consolidation_eval_dataset.json`（**013**） | 记录口径；巩固默认关闭时基线不可比，相对收益记 `not_measurable` |
| 逐例结果（本 Feature 实跑） | `eval/runs/015-20261010020241/evidence/poisoning-cases.json`（20 条，含检测器故障注入）、`.../aoep-cases.json`（13 条） | 运行器只读这两个文件，不手抄任何计数 |
| 基准报告（追踪路径） | `eval/memory_baseline_report.json` | **仅首次播种**，为 015-20261009205637 的历史种子；此后由运行器写 `eval/runs/<RUN_ID>/memory_baseline_report*.json` |
| 基准报告（**权威路径**，convergence） | `eval/runs/015-20261010020241/memory_baseline_report.r5.json` | `status = incomplete`；权威性以同目录 `memory_baseline_report.index.json` 为准（其中逐条列出被取代的报告与理由）。契约 `specs/015-memory-evaluation-governance/contracts/memory-baseline-report.schema.json`（与共享 `$defs` 合并后校验） |
| 原始实测载荷 | `eval/runs/015-20261010020241/hard-metrics-measurements.r2.json` | 逐工具校验错误、**六条**跨域路径分母与可探测性控制、五处隔离计数、六投影/六轴逐条样本、延迟样本 |
| 重跑可复现证据 | `eval/runs/015-20261009205637/evidence/baseline_reproducibility.json`、`eval/runs/015-20261010020241/evidence/reproducibility_convergence.json` | 两次**真实实测**的逐指标 `relative_delta`（延迟除外）：7 项超出 1% 容差；同载荷装配两次（182/182 一致）**不是**该口径 |

**运行器用法与重跑口径**

```powershell
$env:RUN_ID='015-<YYYYMMDDHHMMSS>'
python eval/run_memory_baseline.py `
    --output eval/runs/$env:RUN_ID/memory_baseline_report.json `
    --poisoning eval/memory_poisoning_eval_dataset.json `
    --aoep eval/memory_aoep_obligation_dataset.json `
    --aoep-results D:\Project_new\docsToCode\eval\runs\$env:RUN_ID\evidence\aoep-cases.json `
    --poisoning-results D:\Project_new\docsToCode\eval\runs\$env:RUN_ID\evidence\poisoning-cases.json `
    --runs-dir eval/runs/$env:RUN_ID `
    --continuity-report eval/runs/015-20261009205637/continuity-replay/memory-replay.json `
    --continuity-criterion-met --continuity-completed 16 `
    --regression-map eval/runs/015-20261009205637/regression/regression_group_map.json `
    --measurements eval/runs/$env:RUN_ID/hard-metrics-measurements.json
```

- **不在同一台共享库上并发跑多个写评测**：多个套件同时争用全局 writer lease 会造成
  `idle in transaction` 持锁 + `UPDATE writer_lease` 永久等待（本项目实测到 481 秒死锁），
  必须串行执行；本轮 convergence 因此按 AOEP → 投毒 → 治理 → 全集回归 的顺序单进程运行。
- **重新执行的 001–014 全集回归**：`eval/runs/015-20261010032500/regression/regression_group_map.json`
  （31 组登记、**30 组实执行**、1 组未执行：`013_consolidation_comparison` 的 record 轮产出 0 条缓存清单，
  replay 以 `cache evidence incomplete: matched=0/0` 拒绝）。该 map 另记录：host 的 `NO_PROXY` 括号 IPv6 条目
  会让每个 caliber 在建 Qdrant 客户端时抛 `InvalidURL: Invalid port ':1]'`（首轮 31 组全部 exit 1、无产物），
  编排器已对自身与全部子进程归一化该变量并记录 original → normalized；以及"多套件不得并发"的串行纪律。
  每次执行按 `--timeout 1800` 一轮预算，超时记 not_executed、绝不记通过。
- **回归编排的两处缺陷（重跑期间发现并修复）**：① `eval/run_regression_011.py` 的聚合把"本次实际选择"的 5 个确定性组
  与模块级 6 组清单比较，使被 015 刻意收窄的调用**永远不可能通过**（现按 selected 集合判定，并在摘要中记录
  `selected_groups`）；② 同一 runner 用 `create_subprocess_exec` 起子进程时未传 `env`，导致 Windows **机器级**的
  畸形 `NO_PROXY` 穿透到孙进程（实测：父进程已归一化，子 `cmd /c set NO_PROXY` 仍显示畸形值），子进程全部在构造
  Qdrant 客户端时崩溃（现改为传净化后的显式 env）。修复后 `011_regression_011` 的真实产物 `all_passed = true`
  （5/5 子组），该组已由 failed 重分类为 passed；前一版产物与状态逐字保留在 `regression/011_regression.pre-fix/`
  与状态文件的 `superseded_outcome` 中。
- **Phase 11 收敛轮（关闭"全集回归无回归"）**：`eval/runs/015-20261010100500` —— 单一 run id 全量重跑
  001–014，**31/31 组实执行、31/31 组 `outcome = passed`**，4 个 record+replay 组 replay 真实网络调用均为 0；
  权威报告 `eval/runs/015-20261010100500/memory_baseline_report.json`（`status = passed`，四项硬门全真），
  索引 `.../memory_baseline_report.index.json`，逐条修复与证据见 `evidence/convergence_closure.json`。本轮新增/修正：
  - `--isolated-database` / `--isolated-template` / `--keep-isolated-database` 与逐组 `requires_isolated_database`：
    写入 013 巩固状态的 caliber（`013_e2e`、`014_contract`）以"胶囊库原生模板副本"执行，运行前 drop+template-copy
    刷新并落证 `evidence/isolated_database.json`；隔离口径实测 `013_e2e` 7 passed、`tests/contract` 601 passed 0 failed。
  - `012_acceptance` 的命令补传 `--regression`（该 runner 的 `SC-012` 规则在无回归证据时记 `not_verified`，会使
    验收报告恒为 `status=incomplete`）；现报告 `status=passed`、17/17 判据含 `SC-012` 全过。
  - `eval/run_consolidation_comparison.py` 的冻结标识种子下界改为 `max(sha256 派生值, authority_cutoff + WINDOW_ID_STRIDE)`：
    原实现可能给出**低于**被恢复权威 high-water 的封窗事件 id，被 0095 的
    `guard_consolidation_window_event()` 正当地拒绝为 `invalid consolidation window prefix`（实测
    `015REGRESSION013234bd726` → 273118229010885578 < cutoff 366085522273075200），导致两臂首条写入即失败、
    strict cache manifest 为空、replay 拒绝启动；修复后两臂 6/6 查询无错、清单 2 条、replay 计数 0。
  - 4 组超容差比较的既有漂移处置（`pre_existing_corpus_drift` / `inherited_between_historicals`）落为**逐指标机器
    校验**的 `outcome_reason`（`DRIFT_DISPOSITIONS` + `_disposition_for`，1e-6 容差，且不得含未登记漂移）；
    `regression_gate` 只在"无处置"时判不通过，并在 detail 中列出带处置的组。
  - 013 对照的 replay 步骤声明 `allow_nonzero_exit`（其退出码承载 013 自身 `status=failed` 的已发布结论，而非执行
    失败）与 `resume_existing_artifact`：仅当既有 replay 产物自身记录的 `replay_real_network_calls` **恰为 0** 时才
    采纳为 pass basis，否则拒绝采纳并记未执行；`run-summary.json` 的失败态摘要改为 `superseded-N` 旁置后再写。
- **每组 outcome 的判定口径**：JUnit 产物（failures/errors）→ 无 JUnit 时与各组声明的 `historical` 产物做
  **结论比对**（`enters_default_path`/`three_gate_pass`/`all_passed`/`default_enable_eligible`/`status` 相同即
  无回归；gate/constraint 与 metric 块按 1% 容差比对，**延迟项不参与**）→ 编排器 `_derive_outcome`。
  非延迟比较超出 1% 容差且 map 未记处置的组一律判 `failed`（即使进程 exit 0）。

- `--output` 必填且**唯一写入路径**；`--poisoning`/`--aoep`/`--aoep-results`/`--poisoning-results` 必填；
  `--runs-dir` 供装配 `regression` 块（读 T058 的 `regression_group_map.json`，映射缺失或未执行的组
  记入 `not_executed`，**绝不记为通过**）；`--continuity-report` + `--continuity-criterion-met` +
  `--continuity-completed` 提供连续性水位的真实来源（014 replay 报告）。
- **运行标识规则**：`RUN_ID=015-<YYYYMMDDHHMMSS>`；015 首轮冻结 `015-20261009205637`，convergence
  轮为 `015-20261010020241`（权威报告与索引在该目录）。运行器读取 `RUN_ID` 环境变量（未设置时默认
  首轮值），且所有 015 产物只写 `eval/runs/<RUN_ID>/`。
- **回归块的可判定性（convergence T078）**：`regression.groups[]` 每项必须带 `outcome`
  （`passed|failed|not_measured`，由 `regression_group_map.json` 的 outcome、JUnit 产物或
  非延迟比较结果派生），`regression_gate` 在任一已执行组 `outcome != passed` 或任一非延迟比较
  超出 1% 容差且无处置时判**不通过**；未执行/未判定 MUST NOT 记为通过。
- **零覆盖纪律**：目标路径已存在且字节不同 → 拒绝写入并 `exit 2`；字节相同 → 幂等成功（`exit 0`）。
  `eval/memory_baseline_report.json` 仅在不存在时播种（`--seed-tracked-report`）。运行器**不**复制
  `eval/hard_metrics_014.py:435` 的无条件重写行为，`hard_metrics_014` 的 `main()` 从不被调用；该模块
  无 CLI，故由本运行器在导入前显式设置 `RUN_ID`/`RUN_DIR`。
- **零分母纪律**：比率块 `total == 0` → `{rate: null, value: "not_measurable", reason}`；`leakPath`/
  `countBlock`/`projectionIntegrityView`/`metadataAxis` 的 `examined == 0` → `state`/`value =
  "not_measurable"` + `reason`。四个比率块的 `passed` 是**整数通过条数**（014 口径），"全过"写
  `passed ≥ 1` 且 `rate == value == 1`，绝不写布尔。
- **安全类零容差**：跨域串库/隔离泄漏/硬锚定/provenance 不用 1% 非延迟容差代替；任何一项未达标即整体
  不通过。1% 容差**只**用于同快照同版本的重跑比对，且延迟不参与（`latency.env_sensitive = true`）。
- **可复现性怎么复核**：`--compare <参考报告>` 让本次与参考报告逐项比对非延迟指标，超过 1% 相对容差
  即 `exit 3` 且不落盘。实测：同一份 `hard-metrics-measurements.json` 的两次装配在 **182/182** 项上
  相对偏差 0.0；两次**独立活体实测**则在 7 项原始计数上不同（写者租约被并行流持有导致
  `record_memory` 的通过条数与拒绝错误码不同、每次运行新建探针域导致 `examined` 不同），
  **所有 rate/verdict 一致**，逐项差异见 `baseline_reproducibility.json`。
- **本报告不是提升声明**：`status=incomplete`、`hard_metrics.all_passed=false`（`tool_schema_validity`
  实测落在活体数据上 5/6：`list_knowledge_domains` 的活体响应含 3 处违反 007 契约的 `domain_key`/`slug`，
  逐条记录在原始实测载荷里），`gates.{quality,safety,regression}` 均未通过（回归组尚未执行，T058–T060 负责）。

**三处"不得声称"边界（逐字记录）**

- 测试通过 ≠ 指标实测：一次通过的测试不构成一次实测的指标；未执行的项一律记 `not_measurable` 或
  `not_executed`，绝不记为通过。
- 零分母 ≠ 0：零分母记 `not_measurable` + 原因，绝不记 0，也绝不记为达标。
- SSE 未接线不得当作 UI 未达标或正确性论据：SSE 未接线既不是 UI 未达标的证据，也不是正确性的论据。

**报告属性复核（T036 实测）**

- 首次运行在追踪路径不存在时播种；第二次运行写运行路径，追踪路径 sha256 不变；
  对已存在的不同字节路径再写 → `exit 2`。
- 巩固关闭时 `not_measurable[]` 必含 `benefit.relative_gain`；不可测量项记为 0 的次数 = 0；
  每项不可测量均带非空原因。
- 报告以"基线锚点/当前水位"表述（`notes[0]`），无对照提升证据不宣称改进；模型评审仅诊断、不参与过闸。

#### 015 运行标识与产物路径约定（T002，冻结）

- **运行标识**：`RUN_ID=015-<YYYYMMDDHHMMSS>`（本 Feature 冻结取值
  `015-20261009205637`）。凡 015 运行器产出的重跑、AOEP 逐例结果、分组回归与
  JUnit 一律写入**唯一写入路径** `eval/runs/<RUN_ID>/`（该目录已被 `.gitignore`
  忽略，与 001–014 的 `eval/runs/` 约定一致：产物留盘可复核，不入版本控制）。
- **追踪路径**：`eval/memory_baseline_report.json` **仅首次播种**——该路径不存在时
  写出首份报告，此后任何运行都只写 `eval/runs/<RUN_ID>/memory_baseline_report.json`，
  绝不再触碰追踪路径。
- **历史产物零覆盖（015 全局纪律）**：目标路径已存在且内容与本次产出逐字节不同即
  **拒绝写入并以退出码 ≠ 0 结束**；逐字节相同视为幂等成功（不算覆盖）。
- **必须避免复制的既有缺陷**：`eval/hard_metrics_014.py` **无 `argparse`**，配置只来自
  `RUN_ID`/`RUN_DIR` 环境变量；它对 `eval/runs/<RUN_DIR>/hard-metrics.json` 有"存在即
  拒绝"守卫（约 L410–414），但 L433–435 仍**无条件改写**追踪产物
  `eval/hard-metrics-014.json` —— 这是本仓库唯一违反"历史产物零覆盖"的位置。015 的
  `run_memory_baseline.py` / `run_regression_015.py` 统一采用"存在即拒绝"，并由
  `hard_metrics_014.py` 的复用方以显式参数传入产物路径（不改动该文件本身）。
- **零分母纪律**：零分母记 `{value: null, state: "not_measurable", reason: "a zero denominator is not a measured zero"}`（比率型记 `rateBlock{rate: null, value: "not_measurable"}`），MUST NOT 记 0、MUST NOT 记为达标；未执行 MUST NOT 记为通过。

