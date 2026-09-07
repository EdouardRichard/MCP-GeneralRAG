# Implementation Plan: 通用域评测与多域验收（两验证域语料/评测集/域基线 + 多域验收 + 前端中英文切换）

**Branch**: 011-generic-domain-evaluation | **Date**: 2026-09-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from /specs/011-generic-domain-evaluation/spec.md（含 2026-09-07 澄清 Q1=A / Q2=B 决议 + 前端 i18n 追加指示）

## Summary

为两个通用验证域建设语料与固定评测集，产出域基线报告，执行多域端到端验收、既有全集回归、文档债清理与 2.0 定稿，并在前端管理界面加入中英文切换。核心交付：个人/团队通用知识库域（markdown/txt/html/csv 语料 + personal/generic 域档案，构造虚构样例）与法律合规域（公开法规/标准合同模板 Word/PDF 语料 + markdown 交叉引用语料 + legal 域档案格式扩展）；两份固定评测集（各 ≥10 条，AI 生成 + 人工审核，含中文）；两份域基线报告（dense/hybrid 双路径 Recall@K/MRR/nDCG + P50/P95，非约束性对照锚点，沿用 run_eval/run_comparison 内核 + 新增薄入口）；法律域交叉引用受益再验证（Q1=A 沿用 010 FR-030 双分支闸口，达标启用 legal 图词表）；多域端到端验收（domain_scope 三形态寻址 + list_knowledge_domains 发现闭环 + 硬指标三件套全量实测 + writer/reader 双形态冒烟）；001–006 全集回归（各自口径、1% 容差、历史报告零覆盖）；文档债清理与 2.0 演进目标逐项核销。无新检索路径、无新检索信号，后端与 MCP 契约零变更（前端 i18n 仅改前端自产文案）。

## Technical Context

**Language/Version**: Python 3.12（eval 运行器 + 域档案种子）；TypeScript 5.6 / React 18 / antd 5（前端 i18n）

**Primary Dependencies**: 后端零新增依赖（复用 jsonschema 做报告契约校验、pytest/pytest-asyncio、SQLAlchemy）；前端零新增依赖（自建语言资源层 + antd 官方 zhCN/enUS locale，antd 已具备 locale 包，无需 i18next 类库）

**Storage**: PostgreSQL（domain_profiles 种子变更：新增 personal 内置行、legal 行 supported_formats 扩展与 graph_relations 视受益闸口结果——经 007 启动同步，无 DDL）；Qdrant（评测语料向量，沿用 reindex_eval_qdrant.py 重建）；文件系统（eval/corpora/generic 新增 + eval/corpora/legal 扩充、eval 数据集/报告/重跑记录）；前端 localStorage（语言偏好持久化）

**Testing**: pytest 三层（unit/contract/integration——域档案种子、数据集/报告 schema 校验、运行器扩展单测）+ eval 对照运行器（域基线 + 交叉引用受益 + 全集回归）；前端 i18n 以人工逐页面审计 + 可选 Playwright 快照（既有 @playwright/test devDependency）

**Target Platform**: Linux 服务器本机（loopback）后端；浏览器 Web 管理端（前端，Vite 构建）

**Project Type**: web-service + MCP server（011 主体为评测/验收/文档工程 + 前端管理面 i18n；不改任何检索路径与 MCP 契约）

**Performance Goals**: 离线评测批处理，无实时性能目标；延迟指标（P50/P95）仅记录并标注环境敏感、不进 1% 容差判定；前端语言切换即时生效（内存态 + localStorage，无网络往返）

**Constraints**: 无新检索路径/信号；评测集一经入库零破坏既有条目；历史报告零覆盖（重跑产物写 011 前缀新文件）；前端切换不改后端/MCP 契约（FR-029/FR-031）；硬指标三件套为绝对约束（FR-022~FR-026）

**Scale/Scope**: 两验证域各 5–15 知识源、跨 2–3 scope；两评测集各 ≥10 条（含中文）；两份报告 + 两份契约 schema；前端 3 页面约 65 处字符串 × 中英双语；规模预估 30–40 任务（蓝图 §7-011）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪法条款 | 映射 | 状态 |
|---------|------|------|
| I 显式知识域引用 | FR-022：全部评测/验收检索显式 project_scope/domain_scope，缺失拒绝、不回退全库；多域验收覆盖四类引用场景 | ✅ 通过 |
| II 域事实优先 | 多域混合检索各证据携带自身 domain identity（knowledge_scope_id/type），public 域不静默覆盖专属域证据；各域保留域身份 | ✅ 通过 |
| III 暴露不确定性 | 交叉引用受益零可测图边时记录"无可测量受益"不伪造；语料解析失败 fail-loud 不静默跳过；基线低水位如实记录 | ✅ 通过 |
| IV 可定位证据 | FR-025：定位率 100%（含 txt/html/csv 定位前缀与 word/pdf 标题路径 / page:N §编号路径）；评测集结构锚点可定位 | ✅ 通过 |
| V 数据与控制分离 | 语料经既有凭据脱敏；公开法规语料为不可信数据；前端 i18n 语言资源为可信静态配置、不消费不可信数据 | ✅ 通过 |
| VI 确定性控制优先 | 评测/验收无 LLM 控制路径；域基线运行器确定性（同会话双臂、可重复性 1% 容差）；前端语言资源缺失键确定性回落 | ✅ 通过 |
| VII 独立接口演进 | 后端与 MCP 契约零变更；两份域基线报告契约 schema 为加法（独立新 schema，不触碰既有对照报告 schema）；域档案种子为配置数据变更 | ✅ 通过 |
| VIII 版本不混用 | 语料入库走既有版本/能力门控；评测语料发布后重放可重建 | ✅ 通过 |
| IX 同步结果优先 | 域基线/受益/回归评测均同步批处理产物；前端切换为纯前端交互；无 Task/Resource 依赖 | ✅ 通过 |
| X 评测驱动优化 | 本 Feature 即对照基线的建立者（域基线 = 非约束性锚点，不宣称改进、不设最低水位）；交叉引用受益沿用 010 双分支闸口；全集无回归 | ✅ 通过 |
| XI 领域中立 | personal 域档案声明式落地（第四内置，无代码硬编码域假设）；legal 档案格式集扩展为声明式配置变更；不新增 SE 假设 | ✅ 通过 |

**硬约束（Non-Negotiable）**：跨域串库 = 0（FR-023）、无显式引用拒绝检索（FR-022）、上传内容不作控制指令（V）、Schema 合法率 100%（FR-024，契约零变更故既有合法率保持）、来源可定位率 100%（FR-025）——逐条承接，无豁免。

**结论**：无宪法违反项，无需 Complexity Tracking 豁免。需显式说明的两处"契约/配置变更"均属加法或声明式：① 两份域基线报告契约 schema 为新增独立 schema（不修改 002/003 对照报告 schema）；② domain_profiles 种子变更（新增 personal 行、legal 行 supported_formats 扩展与 graph_relations 视闸口）为配置数据声明（007 FR-006/宪法 XI）。

**Phase 1 设计后复检（post-design re-check）**：R1（薄入口运行器复用内核）不改 001/002 口径、符合 VII；R2（数据集 domain_scope + expected_heading 锚点）不触碰既有数据集、符合硬约束"评测集零破坏"；R4（AI 生成 + 人工审核）符合 X 固定集纪律；R5（非约束性基线）符合 X"建立锚点而非宣称改进"；R6（两份独立 report schema）符合 VII；R9（交叉引用受益 Q1=A 双分支）符合 X/III；R10（前端轻量 i18n 零依赖）符合 VII。**复核结论：仍无违反项，gate 维持通过。**

## Project Structure

### Documentation (this feature)

~~~text
specs/011-generic-domain-evaluation/
├── plan.md              # 本文件（/speckit-plan 输出）
├── research.md          # Phase 0 输出（R0–R13 决策记录）
├── data-model.md        # Phase 1 输出（域档案种子/数据集/报告/语言资源）
├── quickstart.md        # Phase 1 输出（VS-01~VS-10 验证场景）
├── contracts/
│   ├── domain-baseline-common.schema.json        # 域基线报告共享 $defs
│   ├── generic-domain-baseline-report.schema.json # 个人/团队域基线报告契约
│   ├── legal-domain-baseline-report.schema.json   # 法律域基线报告契约（含交叉引用受益块）
│   ├── domain-eval-dataset.schema.json            # 两域评测数据集条目契约
│   └── frontend-locale-contract.md                # 前端语言资源层契约
└── tasks.md             # Phase 2 输出（/speckit-tasks，非本命令）
~~~

### Source Code (repository root)

~~~text
backend/
├── src/rag_mcp/config/
│   └── domain_profiles.py          # 修改：新增 personal 内置档案种子（第四内置，通用格式族/
│                                   #   空词表/NEUTRAL_PLANNER_PROMPT/is_builtin）；legal 行
│                                   #   supported_formats 扩展 [markdown,word,pdf]；legal 行
│                                   #   graph_relations 视 R9 受益闸口结果（达标={references,
│                                   #   referenced_by}+has_graph，未达标=维持空词表）
├── tests/
│   ├── unit/test_domain_profile_seed.py           # 扩展：personal 行 + legal 格式扩展断言
│   ├── contract/test_domain_eval_dataset_schema.py    # 新增：两份数据集条目契约校验
│   ├── contract/test_domain_baseline_report_schema.py # 新增：两份报告契约校验（含受益块）
│   ├── integration/test_011_corpus_ingest.py          # 新增：两域语料入库定位断言（VS-02）
│   ├── integration/test_011_multidomain_acceptance.py # 新增：多域闭环 + 三件套 + 四类引用（VS-06）
│   ├── integration/test_deepseek_harness_dual_form.py # 扩展：混合域验收集 writer/reader 双形态
│   └── e2e/test_deepseek_harness_e2e.py                # 扩展：多域 domain_scope 三形态 + list_knowledge_domains 目标宿主
eval/
├── corpora/
│   ├── generic/                    # 新增：个人/团队域语料（markdown/txt/html/csv，构造虚构）
│   └── legal/                      # 扩充：公开法规/标准合同模板（Word/PDF）+ markdown 交叉引用语料
├── generic_domain_eval_dataset.json    # 新增：个人/团队域固定评测集（≥10 条）
├── legal_domain_eval_dataset.json      # 新增：法律域固定评测集（≥10 条，条文结构+交叉引用受益）
├── ingest_domain_corpora.py       # 新增：两域语料幂等入库脚本（scope 创建 + 入库 + 版本发布，R7）
├── run_domain_baseline.py         # 新增：薄入口运行器（复用 run_eval/run_comparison 内核，R1）
├── run_legal_benefit.py           # 新增：交叉引用受益再验证（R9）
├── run_regression_011.py          # 新增：001–006 全集回归重跑编排（R12）
├── generic_domain_baseline_report.json  # 新增：个人/团队域基线报告（历史产物，勿覆盖）
├── legal_domain_baseline_report.json    # 新增：法律域基线报告（历史产物，勿覆盖）
├── multi_domain_acceptance_report.json  # 新增：多域验收记录（硬指标三件套逐条实测，FR-014/SC-003）
└── 011_*_regression_report.json    # 新增：全集回归重跑产物（不覆盖历史报告）
frontend/
└── src/
    ├── i18n/
    │   ├── index.ts               # 新增：语言资源层（t()/useLocale/LocaleProvider）
    │   ├── zh.ts                  # 新增：中文资源
    │   └── en.ts                  # 新增：英文资源（现状文案迁移）
    ├── App.tsx                    # 修改：ConfigProvider 挂 locale + 语言切换器 + Provider
    └── pages/*.tsx                # 修改：硬编码字符串 → t(key)
docs/
└── 2.0-finalization.md            # 新增：2.0 演进目标逐项核销记录（FR-021）
~~~

**Structure Decision**: 单体仓库既有布局（backend / frontend / eval / docs），无新增项目。011 交付面集中在 eval/（语料、数据集、运行器、报告）与 frontend/src/i18n/（语言资源层）；backend/src/rag_mcp/config/domain_profiles.py 仅做域档案种子配置变更；docs/ 增补定稿核销记录。文档债（roadmap/README/spec Status）在既有文件上就地更新。

## Complexity Tracking

> 无宪法违反项，无需豁免记录。
