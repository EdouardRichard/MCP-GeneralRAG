# Quickstart: 通用域评测与多域验收验证指南（011）

**Branch**: 011-generic-domain-evaluation | **Date**: 2026-09-07 | **Spec**: [spec.md](./spec.md)

端到端验证场景（VS-01~VS-10），证明本 Feature 各交付面成立。前置环境与命令为可运行验证指引；实现细节见 [contracts/](./contracts/)、[data-model.md](./data-model.md) 与 [research.md](./research.md)。

## 前置

- 依赖服务（PostgreSQL/Qdrant/嵌入模型）按 001 quickstart 就绪；后端 venv 激活；前端 pnpm install 就绪。
- 语料入库与评测由各运行器负责（幂等 scope 创建 + ingest + 发布），个人域语料落 eval/corpora/generic/、法律域语料落 eval/corpora/legal/。
- 全部场景的 schema/契约断言经 pytest 夹具（backend/tests/ 三层）执行；命令均在仓库根运行。

## VS-01 personal / legal 域档案种子（FR-001/FR-003）

`python -m pytest backend/tests/unit/test_domain_profile_seed.py -v`

预期：BUILTIN_DOMAIN_PROFILES 含 personal（通用格式族、空词表、NEUTRAL_PLANNER_PROMPT、is_builtin）与 legal（supported_formats=[markdown,word,pdf]）；修改/删除内置档案被拒；se-project/generic 种子逐字段不变（007 等价不回归）。

## VS-02 两域语料入库与定位（US1/FR-002/FR-004）

`python -m pytest backend/tests/integration/test_011_corpus_ingest.py -v`（或运行器自建 scope 入库后断言）

预期：个人域四格式（markdown/txt/html/csv）全部可上传/切片/检索/定位（csv=sheet: 前缀、html=标题路径、txt=段落、markdown=标题路径）；法律域 Word（"第X条"标题路径）与 PDF（page:N §编号路径）定位正确；域档案格式校验拒绝格式族外格式（如 personal 域拒 java）。

## VS-03 评测集契约与零破坏（US2/FR-005~FR-007/SC-001）

`python -m pytest backend/tests/contract/test_domain_eval_dataset_schema.py backend/tests/contract/test_domain_baseline_report_schema.py -v`

预期：generic_domain_eval_dataset.json 与 legal_domain_eval_dataset.json 各 ≥10 条、100% 通过 [domain-eval-dataset.schema.json](./contracts/domain-eval-dataset.schema.json) 校验；个人域四格式每格式 ≥2 条 + ≥2 中文；法律域条文结构 ≥4 + 交叉引用受益 ≥6（is_structural_benefit）+ 中文条文引用查询；既有 eval_dataset.json / agentic_eval_dataset.json / cross_reference_eval_dataset.json 逐字节不变。

## VS-04 域基线报告（US3/FR-008~FR-010/SC-002）

`python eval/run_domain_baseline.py --dataset eval/generic_domain_eval_dataset.json --output eval/generic_domain_baseline_report.json`（法律域同理）

预期：同会话产出 dense 与 hybrid 双路径 Recall@K/MRR/nDCG + P50/P95 延迟 + 逐查询明细 + 硬指标实测；100% 通过对应报告契约 schema 校验；无 enters_default_path 字段（非约束性锚点）；非延迟指标 1% 容差可重复；报告一经产出不被覆盖。

## VS-05 交叉引用受益再验证（US2/FR-011/SC-007，Q1=A）

`python eval/run_legal_benefit.py`（受益子集 = legal_domain_eval_dataset.json 中 is_structural_benefit 条目）

预期：同会话混合基线臂 vs 图增强臂对照，MRR/nDCG 相对提升与 Recall 非降如实记录；达标 → legal 档案 graph_relations 启用 references/referenced_by 且 has_graph=true；未达标 → 维持 R11 空词表（vocabulary_disposition 字段如实反映）；报告含 three_gate_pass 与处置记录；不覆盖 cross_reference_comparison_report.json。

## VS-06 多域端到端验收与硬指标三件套（US4/FR-012~FR-015/SC-003/SC-004）

`python -m pytest backend/tests/integration/test_011_multidomain_acceptance.py backend/tests/integration/test_deepseek_harness_dual_form.py backend/tests/e2e/test_deepseek_harness_e2e.py -v`（DeepSeek Harness 为必过参考客户端/目标宿主）

预期：list_knowledge_domains 发现 → domain_scope 三形态（数字 ID/slug/type:name）寻址 → search_knowledge 检索 → get_evidence 展开，四语义轴（personal/generic/legal/se-project）全覆盖；三件套逐条实测（串库=0/Schema=100%/定位=100%）；无引用请求被拒、仅 project_scope 旧码不变；writer/reader 双形态冒烟各通过。

## VS-07 001–006 全集回归（US5/FR-016~FR-017/SC-005）

`python eval/run_regression_011.py`

预期：六项报告按各自口径重跑（001 Dense 11 / 002 混合 18 / 003 格式集 37 / 004 图集 37 / 005 agentic 组合 63 / 006 冒烟 11×2），非延迟指标相对历史报告 1% 相对容差内一致；010 交叉引用口径复跑行为不变；重跑产物落 011 前缀新文件、历史报告零覆盖。

## VS-08 前端中英文切换（US7/FR-027~FR-031/SC-011）

`cd frontend && pnpm dev` 后人工逐页面审计（或 Playwright 快照）：

预期：Header 语言切换器切换 zh/en 即时生效；三页面全部前端自产文案随切换（含 antd 分页/日期/确认组件文案）；中文态英文残留=0、英文态中文残留=0；后端错误消息与领域数据原样不翻译；刷新后语言偏好保留；默认英文。

## VS-09 文档债核销（US6/FR-018~FR-020/SC-008）

人工审计：docs/1.0-iteration-roadmap.md 反映 003–011 交付与 2.0 收官状态；根 README 无"尚无业务实现代码"等过时陈述且不超售；001–006（及 007–010）spec.md Status 与交付事实一致；eval/README 登记两域数据集/报告/运行器用法与重跑口径。

## VS-10 2.0 演进目标逐项核销（US6/FR-021/SC-009）

人工审计 docs/2.0-finalization.md：蓝图 §1.3 五项目标逐项给出达成判定 + 证据工件指针（目标 1→007 domain_scope + VS-06 多域验收；目标 2→008 注册表边际成本记录；目标 3→008 格式集验收 + 011 个人域语料覆盖；目标 4→VS-03/VS-04 + VS-07 回归；目标 5→VS-06 三件套实测）；未达成项有明确处置；2.0 蓝图正文未被修改。
