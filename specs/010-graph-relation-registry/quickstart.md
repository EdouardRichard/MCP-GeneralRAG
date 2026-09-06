# Quickstart: 图关系注册表验证指南（010）

**Branch**: `010-graph-relation-registry` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)

端到端验证场景（VS-01~VS-10），证明本 Feature 各交付面成立。前置环境与命令为可运行验证指引；实现细节见 [contracts/](./contracts/) 与 [data-model.md](./data-model.md)。

## 前置

- 依赖服务（PostgreSQL/Qdrant/嵌入模型）按 001 quickstart 就绪；后端 venv 激活。
- 评测前完成：004 图集语料与法律域语料（`eval/corpora/legal/`）已入库并发布（VS-09/VS-10 各自的运行器负责 scope 创建/入库/重建，见各场景）。
- 全部场景的数据库断言经既有 pytest 夹具（`backend/tests/` 三层）执行；命令均在仓库根运行。

## VS-01 注册表发现正确性（FR-002/SC-007）

`python -m pytest backend/tests/unit/test_graph_extractor_registry.py -v`

预期：se-project 词表对 (java) 命中 java_call_graph、对 (ddl) 命中 ddl_fk、对 (markdown) 不命中 cross_reference；legal 词表对 (markdown) 命中 cross_reference；generic 空词表对全部格式返回空；发现结果确定（同输入同序）；单侧 pairs 注册被拒；inverse map 含三对六键。

## VS-02 迁移与词表校验（FR-008~FR-010/SC-006）

`python -m pytest backend/tests/unit/test_migration_graph_edge.py backend/tests/unit/test_graph_models_wide.py -v`

预期：迁移 0074 后 CHECK 为宽模式 pattern；other_hard 存量断言（构造非零夹具 → 迁移阻断）；ORM 拒绝 other_hard/inferred；词表外值（如 `arbitrary_edge`）经 `write_edges` 整批 ValueError；se-project 词表下 `calls` 与 legal 词表下 `references` 写入成功；存量 4 值零重写。

## VS-03 交叉引用提取端到端（FR-013~FR-015/SC-012）

`python -m pytest backend/tests/unit/test_cross_reference_extractor.py backend/tests/integration/test_cross_reference_e2e.py -v`

预期：法律语料三类引用形态（内部锚点 / 跨文件相对链接 / 中文条文引用"依据第X条"与"参见X.Y"）各产出 references+referenced_by **成对**硬边；parse_evidence 3 字段且 locator 按 `xref:*` 编码（契约 §4）；行号区间归属与标题匹配正确；同语料重建后边集稳定（确定性）。

## VS-04 防误报（research R7.3/契约 §1 排除项）

随 VS-03 单测断言：叙述性提及（无触发词）、范围引用（第X条至第Y条）、相对指代（前条/本条）、目标不在语料——四类输入产边数为 0，且不记为提取失败。

## VS-05 legal 内置域档案（FR-016/SC-008 前置）

`python -m pytest backend/tests/unit/test_domain_profile_seed.py backend/tests/unit/test_domain_profile_sync.py -v`

预期：BUILTIN_DOMAIN_PROFILES 含 legal（markdown 格式集、references/referenced_by 词表、is_builtin）；启动同步插入/修复漂移；修改/删除内置 legal 被拒；se-project/generic 种子逐字段不变（007 等价不回归）。

## VS-06 public+legal 图路径端到端（FR-019/US4/SC-008）

`python -m pytest backend/tests/integration/test_public_legal_graph_path.py -v`

预期：public 类型 + legal 档案域（无 Project 行）上传法律语料、发布 graph_ready 版本（硬边>0）后，以 `domain_scope` 寻址图增强检索成功；证据 `knowledge_scope_type="public"`、可定位；并发另一图域检索互不泄漏（泄漏事件数=0）；public+generic 域不可声明 graph_ready（SC-009）。

## VS-07 graph_ready 门控与软关系不变（FR-020/FR-021/SC-009/SC-010）

`python -m pytest backend/tests/integration/test_us5_graph_ready_lifecycle.py backend/tests/unit/test_soft_relation_inference.py -v`

预期：硬边=0 声明 graph_ready 被拒；软关系五项元数据/四态/硬软区分标注与 004 一致（既有测试零修改通过即证）。

## VS-08 查询侧词表兼容（FR-018/research R6/SC-004）

`python -m pytest backend/tests/unit/test_graph_expansion_vocab.py backend/tests/contract/test_graph_relations_schema.py backend/tests/contract/test_eval_graph_comparison_schema.py -v`

预期：expansion 默认不再硬编码 SE 关系集（None=不过滤，se-project 逐边等价）；map_graph_params 空/全非法方向回退请求域词表全量（active 软关系参与面与 004 一致）；反向 CTE 重标注含 references↔referenced_by（inverse map 生成）；relation_types SQL 参数化；两份契约 schema 的 relation_type 宽 pattern 生效（references 合法、other_hard 非法、硬边 inferred 非法）。

## VS-09 004 图集 37 条无回归（FR-028/SC-001）

`python eval/run_graph_comparison.py --dataset eval/eval_dataset.json --output eval/010_graph_regression_report.json --limit 37`
（运行前按 004 既有流程重建评测语料索引；口径见 research R0）

预期：非延迟指标（Recall@K/MRR/nDCG）相对 `graph_enhanced_comparison_report.json` 在 1% 相对容差内一致；硬指标三件套通过；java/ddl 提取产边与迁移前逐条一致（插件化纯重构实证）。

## VS-10 交叉引用受益对照（FR-029~FR-031/SC-002）

`python eval/run_cross_reference_comparison.py`
（运行器负责：建 legal 域 scope → 入库 `eval/corpora/legal/` → 触发重建并发布 graph_ready 版本 → 同会话先混合基线后图增强对照，research R12）

预期：受益子集（≥6 条，含中文条文引用查询）MRR/nDCG 均值相对混合基线提升 ≥3%、Recall 非降、硬指标全过 → `enters_default_path=true`；逐查询记录图扩展路径（references/referenced_by、跳数、结构权重）；双跑非延迟指标一致（SC-011）。未达阈值 → legal 档案以空词表形态交付（research R11 声明式补救），报告如实记录。

## 汇总闸口

| 闸口 | 场景 | 判定 |
|------|------|------|
| 插件化无回归 | VS-01/VS-09 | 37 条 1% 容差一致 + 产边逐条等价 |
| 受益闸口 | VS-10 | 子集 ≥3% + Recall 非降 + 硬指标 |
| 硬指标三件套 | VS-06/VS-09/VS-10 | 泄漏=0 / Schema=100% / 定位=100% |
| 不变面 | VS-02/VS-05/VS-07 | 门控/软关系/SE 等价零回归 |
