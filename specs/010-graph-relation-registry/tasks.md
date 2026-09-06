---
description: "Task list for 010 graph-relation-registry implementation"
---

# Tasks: 图关系注册表（GraphExtractor 插件接口 + 交叉引用提取器）

**Input**: Design documents from `/specs/010-graph-relation-registry/`

**Prerequisites**: plan.md、spec.md、research.md（R0–R15）、data-model.md、contracts/graph-extractor-registry.md、contracts/cross-reference-extraction.md、quickstart.md（VS-01~VS-10）

**Organization**: 按实现阶段组织（5 个实现阶段 + 1 个 Polish 阶段），每阶段映射 spec User Story 与 FR/SC；任务内标注 [US*] 以维持故事可追溯。行号锚点以 2026-09-06 工作树为准（见 research.md 头部）。

**Path Conventions**: 后端 `backend/src/rag_mcp/`、测试 `backend/tests/`、评测 `eval/`、契约 `specs/003-structured-asset-expansion/contracts/`（003 起契约集中地约定）。

---

## Phase 1: 插件接口与迁移先行（US1：注册表 + java/ddl 迁移 + 004 回归）

**Goal**: 落地 GraphExtractor ABC + GraphExtractorRegistry（R1/R2），java/ddl 迁移至接口且行为逐条不变（FR-001~FR-005），并以 004 回归闸口实证（SC-001 前半）。**插件化先行**使后续阶段在已验证的框架上叠加。

**Independent Test**: `python -m pytest backend/tests/unit/test_graph_extractor_registry.py backend/tests/unit/test_java_ddl_migration_equivalence.py -v`（发现正确 + java/ddl 产边与迁移前逐条等价）；阶段末 VS-09 004 图集回归通过。

- [X] T001 [P] [US1] 新建 `backend/src/rag_mcp/graph/extractors/base.py`：`GraphExtractor` ABC（format / relation_pairs / chunk_scope 声明 + `extract(source, chunks, scope)` 抽象方法），契约见 specs/010-graph-relation-registry/contracts/graph-extractor-registry.md §1
- [X] T002 [US1] 在 base.py 实现 `GraphExtractorRegistry`：按 format 注册、`discover(format, graph_relations)` 词表交集发现（声明序确定性）、`inverse_relation_map()` 聚合、build 时注册校验（pairs 互逆、pattern 合法、单侧声明拒绝、冲突拒绝 → 启动失败，沿用 008 §5 范式），契约 §3
- [X] T003 [P] [US1] 迁移 `backend/src/rag_mcp/graph/extractors/java_call_graph.py`：`JavaCallGraphExtractor` 继承 ABC，声明 format="java"、relation_pairs={"calls": "called_by"}、chunk_scope="source"；extract 逻辑与产边结构零改动（FR-005）
- [X] T004 [P] [US1] 迁移 `backend/src/rag_mcp/graph/extractors/ddl_fk.py`：`DdlFkExtractor` 继承 ABC，声明 format="ddl"、relation_pairs={"fk_references": "fk_referenced_by"}、chunk_scope="source"；extract 逻辑与产边结构零改动（FR-005）
- [X] T005 [US1] 修改 `backend/src/rag_mcp/services/ingestion_service.py`（`_extract_graph_relations`，现 839-842 行）：图提取分派由 `FormatHandlerRegistry.instance().graph_extractor(source.format)` 改为 `GraphExtractorRegistry` 发现——`scope_id → KnowledgeScope.domain_key → DomainProfile.graph_relations → registry.discover(source.format, graph_relations)`（R3 发现序）；多提取器声明序依次 extract、合并去重（唯一键 `(knowledge_scope_id, index_version, source_chunk_id, target_chunk_id, relation_type, direction, version)`）；无匹配提取器静默跳过（0 边非失败）；降级语义不变（858-863 行 except 分支零改动）
- [X] T006 [US1] 修改 `backend/src/rag_mcp/graph/store/postgres_graph_store.py`（`rebuild_graph_edges`，现 225 行）：rebuild 路径同样改经 GraphExtractorRegistry 发现（format + 重建 scope 的域词表），失败降级不断链（契约 §5）；对 chunk_scope="scope" 提取器同样预构建 scope 级 `filename → [(chunk_id, heading, start_line, end_line)]` 索引注入 chunks（跨文件交叉引用边可重建，宪法 VIII，research R10.3）
- [X] T007 [US1] 修改 `backend/src/rag_mcp/parsers/registry.py`：退役 `FormatHandler.graph_extractor` 字段定义与 `graph_extractor(fmt)` 查询方法及 `_java_graph_extractor`/`_ddl_graph_extractor` 工厂；FormatHandler 其余契约（detect/parse/binary）零改动
- [X] T008 [US1] 更新 `specs/008-universal-ingestion-channel/contracts/format-handler-registry.md`：增 supersession 附注——图提取分派行（§1 graph_extractor 字段、§3 查询、§4 表格行）自 010 起由 specs/010-graph-relation-registry/contracts/graph-extractor-registry.md 承载（R2）
- [X] T009 [P] [US1] 新建 `backend/tests/unit/test_graph_extractor_registry.py`：发现正确性（se-project 词表×java/ddl/markdown、空词表、多提取器确定性次序）、注册校验拒绝路径（单侧 pairs/pattern 非法/冲突）、inverse map 含三对六键（VS-01）
- [X] T010 [P] [US1] 新建 `backend/tests/unit/test_java_ddl_migration_equivalence.py`：固定 Java/DDL 语料夹具上，ABC 化提取器产边与 004 既有产出逐条等价断言（relation_type/方向配对/去重键/parse_evidence locator，FR-005/SC-001 前半）
- [X] T011 [US1] 修改 `backend/tests/integration/test_us1_java_callgraph_recall.py` 等引用 008 钩子的既有测试：改经新注册表分派（other_hard 相关断言在 Phase 2 T017 一并更新，此处仅分派路径）
- [X] T012 [US1] 先为 `eval/run_graph_comparison.py` 增补 `--limit N` 参数（截取数据集前 N 条，沿 eval 既有 `--limit` 先例 `run_comparison.py`；004 图集口径 = 索引 0–36 共 37 条），再运行 VS-09 前置回归：`python -m pytest backend/tests/unit/test_graph_extractor_registry.py backend/tests/unit/test_java_ddl_migration_equivalence.py backend/tests/integration/ -k "graph or ingest" -v` 全绿后，按 research R0 重跑 004 图集（`python eval/run_graph_comparison.py --dataset eval/eval_dataset.json --output eval/010_graph_regression_report.json --limit 37`），确认 37 条非延迟指标 1% 容差一致（SC-001 前半实证；完整对照在 Phase 5 T046 复跑固化）

**Checkpoint**: 插件框架落地且 004 行为等价；FormatHandlerRegistry 图钩子退役；004 图集回归首过。

---

## Phase 2: 词表与约束（US2：relation_type 放宽 + 域档案联动 + 查询侧过滤）

**Goal**: 迁移 0074 放宽 graph_edge.relation_type CHECK（FR-008/FR-010），应用层词表校验落 store chokepoint（FR-009），legal 内置档案种子（FR-016 前半），清除查询侧三处 SE 硬编码（FR-018/研究 R6）。

**Independent Test**: `python -m pytest backend/tests/unit/test_migration_graph_edge.py backend/tests/unit/test_graph_models_wide.py backend/tests/unit/test_graph_expansion_vocab.py backend/tests/unit/test_domain_profile_seed.py -v`（VS-02/VS-05/VS-08）。

- [X] T013 [US2] 新建 `backend/alembic/versions/0074_widen_graph_edge_relation_type.py`（head 0073 顺延）：前置断言 other_hard 存量数 = 0（非零 raise 阻断）→ DROP CONSTRAINT IF EXISTS chk_graph_edge_relation_type → ADD CONSTRAINT `CHECK (relation_type ~ '^[a-z][a-z0-9_]{0,62}$')`；存量 4 值零重写；downgrade 恢复闭合枚举（data-model §2.1，R4）
- [X] T014 [US2] 修改 `backend/src/rag_mcp/graph/models.py`：删除 `_HARD_RELATION_TYPES` frozenset 与 45-49 行闭合枚举 CheckConstraint，替换为宽模式 pattern 常量；`@validates("relation_type")` 改为 pattern 校验 + 禁 inferred + 禁 other_hard（R4.4；soft_relation 约束零改动，FR-011）
- [X] T015 [US2] 修改 `backend/src/rag_mcp/graph/store/base.py`：`GraphStore.write_edges` 签名增必填参数 `allowed_relation_types: list[str]`（ABC 与 docstring 同步，R5）
- [X] T016 [US2] 修改 `backend/src/rag_mcp/graph/store/postgres_graph_store.py` `write_edges`：写入前词表校验（relation_type ∈ allowed_relation_types，越界整批 ValueError 列出越界值与合法集 → 调用方降级，R5）；写入前无条件拒绝保留字 {other_hard, inferred}（硬边 relation_type 永不等于保留字，即便自定义档案声明了它们——裸 SQL INSERT 不经 ORM validates，FR-010/宪法 III 兜底）；同时将 `expand` 的 relation_types SQL 过滤（现 49-52 行字符串拼接）改为 `relation_type = ANY(:rts)` 数组参数绑定 + 元素 pattern 校验（R6.4）
- [X] T017 [US2] 更新 `backend/tests/unit/test_migration_graph_edge.py`：宽模式断言（references 合法、other_hard 拒绝、越界 pattern 拒绝）+ other_hard 非零阻断夹具；新建 `backend/tests/unit/test_graph_models_wide.py`：ORM validates 新规则断言；增 write_edges 保留字拒绝断言（other_hard/inferred 即便在词表内也拒绝，VS-02）
- [X] T018 [US2] 修改 `backend/src/rag_mcp/graph/expansion.py`：删除 `_BIDIRECTIONAL_PAIRS` 硬编码（29-31 行）与 74-75 行默认赋值；`relation_types=None` → 不过滤（写侧词表已保证 scope 内类型合法；SE 逐边等价由 Phase 5 VS-09 实证，R6.1）
- [X] T019 [US2] 修改 `backend/src/rag_mcp/orchestration/retrieval_pipeline.py`：`map_graph_params` 增参数 `valid_directions`（合法集 = 请求域词表），删除模块级 `BIDIRECTIONAL_DEFAULT/VALID_DIRECTIONS`（38-39 行）；`_recall_one` 接收并穿线；空/全非法方向回退合法集全量（非 None——rt_filter 作用于含 active 软关系的联合 CTE，None 回退会改变软关系参与面、破坏 004 逐边等价，R6.2）
- [X] T020 [US2] 修改 `backend/src/rag_mcp/orchestration/state_machine.py`：将 `domain_planner_config.relation_vocab`（entry.py:180-182 已解析）穿线至 `retrieve_round → _recall_one → map_graph_params` 的 valid_directions（R6.2）
- [X] T021 [US2] 修改 `backend/src/rag_mcp/graph/store/postgres_graph_store.py` 反向 CTE（254-275 行）：CASE 硬编码映射改由 `GraphExtractorRegistry.inverse_relation_map()` 生成（calls↔called_by、fk_references↔fk_referenced_by、references↔referenced_by 自动并入；键过 pattern sanitize，R6.3/R9）
- [X] T022 [US2] 修改 `backend/src/rag_mcp/config/domain_profiles.py`：`BUILTIN_DOMAIN_PROFILES` 增第三条目 legal（domain_key="legal"、supported_formats=["markdown"]、graph_relations={"references": ["out","in"], "referenced_by": ["out","in"]}、prompt_overrides=None、default_capabilities 同 se-project 图能力、is_builtin=True；R11）；se-project/generic 条目逐字段不动
- [X] T023 [P] [US2] 扩展 `backend/tests/unit/test_domain_profile_seed.py`：legal 档案断言（词表/格式集/is_builtin）+ se-project/generic 等价不回归断言（VS-05）；扩展 `backend/tests/unit/test_domain_profile_sync.py`：legal 种子插入与漂移修复
- [X] T024 [P] [US2] 新建 `backend/tests/unit/test_graph_expansion_vocab.py`：expansion 无默认关系集（None=不过滤）、ANY(:rts) 参数化、inverse map 反向标注含 references↔referenced_by、map_graph_params 空/全非法方向回退 = 请求域词表全量（se-project 等价 004 默认，active 软关系不因缺省方向混入）（VS-08）
- [X] T025 [P] [US2] 修改 `specs/003-structured-asset-expansion/contracts/graph-relations.schema.json`：`RelationType` enum → pattern `^[a-z][a-z0-9_]{0,62}$`（description 记录内置词表全集），硬关系 allOf 分支 enum 同步 pattern 化 + not enum [other_hard, inferred]（宪法 III：硬边不得为 inferred，保住 004 契约编码）；不触碰 project_id required 字段（007 遗留债，research R13 记录）（VS-08 契约面）
- [X] T026 [P] [US2] 修改 `specs/003-structured-asset-expansion/contracts/mcp-search-output.graph-annotation.schema.json`：`relation_type` enum → 同 pattern + type=hard 分支 not enum [other_hard, inferred]（other_hard 契约面退役 FR-010、宪法 III；soft 分支 relation_type 恒 inferred 不变）（SC-004 先决条件，R13）
- [X] T027 [P] [US2] 更新 `backend/tests/contract/_graph_schema_helper.py` 与 `backend/tests/contract/test_graph_relations_schema.py`：pattern 断言 + 新值样本（references 合法、other_hard 非法、越界 pattern 非法、硬边 relation_type=inferred 非法（宪法 III 样本））（VS-08）

**Checkpoint**: 宽模式 + 词表校验 + 查询侧词表兼容 + legal 档案就绪；VS-02/VS-05/VS-08 可全绿。

---

## Phase 3: 交叉引用提取器（US3：规则集 + 防误报）

**Goal**: 交付 `CrossReferenceExtractor`（format=markdown，references/referenced_by 成对硬边，混合锚定，中英文规则集，防误报双重确认），单测覆盖全规则分支（FR-013~FR-017，契约 cross-reference-extraction.md）。

**Independent Test**: `python -m pytest backend/tests/unit/test_cross_reference_extractor.py -v`（VS-03/VS-04：三类引用形态成对产边 + 四类排除项 0 边）。

- [X] T028 [US3] 新建 `backend/src/rag_mcp/graph/extractors/cross_reference.py`：`CrossReferenceExtractor` 继承 ABC（format="markdown"、relation_pairs={"references": "referenced_by"}、chunk_scope="scope"），注册进 GraphExtractorRegistry
- [X] T029 [US3] 在 cross_reference.py 实现结构化链接规则（契约 §1.1）：内部锚点 `[text](#anchor)`、相对链接 `[text](path.md#anchor)`/`[text](./path.md)`（basename 解析，无锚点→目标文件首个标题 Chunk）；排除外链/图片/代码块内语法；相对链接目标 basename 在 scope 内不唯一 → 视为不可解析不产边（确定性消歧，宪法 VI）
- [X] T030 [US3] 在 cross_reference.py 实现条文引用规则（契约 §1.2）：触发词白名单（依据/根据/依照/按照/参照/参见/见/转致/援引）+ 中文数字条文 `第[一二三四五六七八九十百零两]+条`（款项并入条文级目标）+ 点号编号 `\\d+(\\.\\d+)*`；范围引用（第X条至第Y条）与相对指代（前条/本条/前款）确定性排除
- [X] T031 [US3] 在 cross_reference.py 实现混合锚定（契约 §2）：来源端点行号区间归属（start_line <= L <= end_line，缺口归前条 Chunk）；目标端点 section_path 末段标题归一化匹配（ASCII 小写/空白→-/剥 markdown 标记/CJK 保留；锚点原文宽松分支；条文号前缀匹配）；重复命中取文档序首个；basename 多文件冲突视为不可解析；无命中不产边
- [X] T032 [US3] 在 cross_reference.py 实现产边与 locator（契约 §3/§4）：成对 references+referenced_by（各自 direction=out、共享 locator）；自引用/自环不产边；locator 三态编码 `xref:internal/xref:relative/xref:clause`（值 %-转义）；parse_evidence 3 字段
- [X] T033 [US3] 修改 `backend/src/rag_mcp/services/ingestion_service.py` `_extract_graph_relations`：chunk_scope="scope" 提取器的 orchestration 支持——预构建 scope 级 `filename → [(chunk_id, heading, start_line, end_line)]` 索引（当前源 + 同 scope 其余已发布源，按 KnowledgeSource 文件名 basename 关联）注入 chunks（每条附 filename 键，R10.3）；首遍尽力 + rebuild 补全语义注释显式化
- [X] T034 [P] [US3] 新建 `backend/tests/unit/test_cross_reference_extractor.py`：规则集全分支断言——三类引用形态各产成对边（含跨文件相对链接经 scope 索引解析）、locator 编码、行号归属、标题归一化（中英文锚点）、条文号前缀匹配（中文数字归一）、重复标题文档序消歧、同名 basename 多文件不产边（唯一性消歧）（VS-03）
- [X] T035 [P] [US3] 在 test_cross_reference_extractor.py 增防误报断言（VS-04，契约 §1 排除项）：叙述性提及（无触发词）、范围引用、相对指代、目标不在语料——四类输入产边数为 0 且不记为提取失败
- [X] T036 [US3] 新建 `backend/tests/integration/test_cross_reference_e2e.py`：legal 域夹具上入库→提取→边落库（词表校验通过）→同语料重建边集稳定（确定性，含跨文件相对链接边完整，rebuild scope 索引数据面）（VS-03 集成面）

**Checkpoint**: 提取器规则完备、防误报实证；VS-03/VS-04 可全绿。

---

## Phase 4: 受益验证（US3/US4：法律语料受益子集 + ≥3% 闸口 + public/generic 图路径端到端）

**Goal**: 法律域语料与受益子集数据集、对照运行器与 ≥3% 闸口判定（FR-029~FR-031/SC-002/SC-011），public+legal 图路径端到端（FR-019/SC-008）。

**Independent Test**: `python eval/run_cross_reference_comparison.py` 产出报告并闸口判定（VS-10）；`python -m pytest backend/tests/integration/test_public_legal_graph_path.py -v`（VS-06）。

- [X] T037 [P] [US3] 新建法律域评测语料 `eval/corpora/legal/`（2–4 个虚构法规 markdown：主法规按 `## 第X条` 结构 + 实施细则/引用性文件；覆盖内部锚点、跨文件相对链接、中文条文引用三类形态与全部规则分支；虚构文本，R12.1）
- [X] T038 [P] [US3] 新建 `eval/cross_reference_eval_dataset.json`：≥6 条（query/project_scope/expected_evidence_ids/is_structural_benefit:true；≥1 中文条文引用查询、≥1 锚点导航、≥1 跨文件相对链接；沿 005 独立数据集先例，R12.2）
- [X] T039 [US3] 新建 `eval/run_cross_reference_comparison.py`：建 legal 域 scope → 入库语料 → 触发 rebuild + graph_ready 发布（硬边>0）→ 同会话先混合基线（graph 关闭）后图增强（开启）对照 → 复用 `GraphComparisonRunner` 报告器产出 `eval/cross_reference_comparison_report.json`（三段闸口/硬指标/双跑可重复性，R12.3；SC-002 ≥3% + Recall 非降判定）
- [X] T040 [US3] 执行受益对照并记录：运行 T039 运行器，判定结论写入 ${BT}eval/cross_reference_comparison_report.json${BT}（enters_default_path 字段）；≥3% 达标 → ${BT}backend/src/rag_mcp/config/domain_profiles.py${BT} 的 legal 词表维持声明（图扩展进默认路径）；未达 → legal 档案 graph_relations 改空词表交付（research R11 声明式补救）（SC-002/FR-030）
- [X] T041 [US4] 新建 `backend/tests/integration/test_public_legal_graph_path.py`：public + legal 域（无 Project 行）上传/发布 graph_ready（硬边>0）→ domain_scope 寻址图增强检索成功 → 证据 knowledge_scope_type="public"、可定位 → 并发另一图域检索互不泄漏（=0）→ public+generic 域不可声明 graph_ready 且图路径不启用（US4 全场景/SC-008/SC-009）
- [X] T042 [US4] 回归 US5 不变面：运行 `python -m pytest backend/tests/integration/test_us5_graph_ready_lifecycle.py backend/tests/unit/test_soft_relation_inference.py backend/tests/integration/test_us5_isolation_cleanup.py -v` 确认门控语义/软关系五项元数据四态/硬软区分与 004 一致（FR-020/FR-021/SC-009/SC-010，零改动即回归通过）

**Checkpoint**: 受益闸口判定完成（达标或声明式补救）；public 图路径端到端实证；VS-06/VS-07/VS-10 可全绿。

---

## Phase 5: 验收（004 全量回归 + 硬指标 + quickstart）

**Goal**: 全量验收——004 图集 37 条完整对照、硬指标三件套、quickstart VS-01~VS-10 全场景、既有测试集零回归（FR-024~FR-031 全部硬约束与对照义务闭合）。

**Independent Test**: quickstart.md 汇总闸口表全过。

- [X] T043 [US5] 硬约束验收集执行（新建 ${BT}backend/tests/integration/test_010_hard_constraints.py${BT}）：图增强检索显式 scope 缺失拒绝（FR-024）、跨域泄漏=0（含 public+legal 与 project+se-project 混合域，FR-025/SC-003）、Schema 合法率 100%（含携带 references 标注的响应，FR-026/SC-004）、来源可定位率 100%（含交叉引用硬边 locator，FR-027/SC-005）——pytest 断言 + ${BT}eval/cross_reference_comparison_report.json${BT} 硬指标字段双口径
- [X] T044 [US5] 004 图集 37 条完整回归（VS-09 终版）：按 research R0 口径重跑 `python eval/run_graph_comparison.py --dataset eval/eval_dataset.json --output eval/010_graph_regression_report.json --limit 37`，非延迟指标 1% 容差一致 + 硬指标通过 + java/ddl 产边逐条等价（SC-001 完整闭合）
- [X] T045 [US5] 既有 pytest 全量回归：`python -m pytest backend/tests/ -v`（001–009 既有测试集零回归；other_hard 引用与 008 钩子引用已在前序任务更新）
- [X] T046 [US5] 可重复性验证（SC-011）：连续两次运行 T039/T044，非延迟指标 1% 容差内一致，延迟指标标注环境敏感（沿用 004 SC-007 范式）；结果落入 ${BT}eval/cross_reference_comparison_report.json${BT} 与 ${BT}eval/010_graph_regression_report.json${BT} 的 reproducibility 字段
- [X] T047 [US5] quickstart 全场景验证：按 `specs/010-graph-relation-registry/quickstart.md` VS-01~VS-10 逐场景执行并记录结果（汇总闸口表全过：插件化无回归/受益闸口/硬指标三件套/不变面）
- [X] T048 [US5] DeepSeek Harness 端到端参考客户端验证：legal 域图增强 search_knowledge/get_evidence MCP 端到端调用 + 输出 Schema 校验通过，验证记录写入 ${BT}specs/010-graph-relation-registry/quickstart.md${BT} 验证结果注记（沿用 006/007 惯例；ChatGPT App/Claude Code 记录兼容性状态不阻塞）
- [X] T049 [US5] 更新 `eval/README.md`：新增 010 评测产物条目（cross_reference_eval_dataset/cross_reference_comparison_report/010_graph_regression_report 与运行口径 --limit 37 说明，沿 eval 既有 --limit 先例），并更新数据集与基线报告表（004 图集 37 条口径注记 + legal 语料与受益子集说明）

**Checkpoint**: 全部 SC（SC-001~SC-012）与硬约束闭合；Feature 可交付。

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T050 [P] 代码清理：删除迁移过程中的死代码与过渡注释（parsers/registry.py 退役残留、expansion.py 硬编码常量残留），确认无 other_hard 文案残留（backend 全仓 grep 断言）
- [X] T051 [P] 更新 `backend/tests/fixtures/deps_baseline.txt` 快照核对（010 零新增依赖——断言基线不变，运行 `backend/tests/unit/test_deps_unchanged.py`）
- [X] T052 运行 quickstart.md 验证（若 T047 已完整执行则作为复核）

---

## Dependencies & Execution Order

### Phase Dependencies（严格顺序）

- **Phase 1 → Phase 2**：插件框架（T001/T002）与迁移等价（T003/T004）是词表校验（T015/T016 引用注册表 inverse map）与查询侧清理（T021）的载体；004 回归先行（T012）使后续阶段有等价基线。
- **Phase 2 → Phase 3**：交叉引用提取器产 references/referenced_by 依赖宽模式 CHECK（T013/T014）、legal 词表（T022）与 registry 发现（T002）。
- **Phase 3 → Phase 4**：受益对照（T039/T040）依赖提取器与 scope 索引（T028~T033）；public+legal 端到端（T041）依赖 legal 档案 + 提取器。
- **Phase 4 → Phase 5**：验收闸口以受益报告与 public 端到端为输入。
- **Phase 5 → Phase 6**：Polish 在验收后。

### User Story Dependencies

- **US1（P1，Phase 1 主体）**：无跨故事依赖——先行交付注册表 + java/ddl 等价。
- **US2（P1，Phase 2 主体）**：依赖 US1 的注册表（inverse map 消费）；词表校验/宽模式/legal 档案独立可测。
- **US3（P1，Phase 3+4 前半）**：依赖 US1 接口与 US2 词表/legal；受益闸口独立可测（VS-10）。
- **US4（P2，Phase 4 后半）**：依赖 US2（legal 档案）+ US3（提取器产边）；端到端独立可测（VS-06）。
- **US5（P2，Phase 5 主体）**：聚合验收——依赖全部前序；不变面回归（T042）仅依赖 Phase 2，可提前执行。

### Within Each Phase

- 模型/接口（base.py、models.py）先于服务层（ingestion/store）；
- 迁移（T013）先于消费其约束的测试（T017）；
- 契约 schema 修改（T025/T026）先于契约测试更新（T027）；
- 提取器实现（T028~T032）先于 e2e（T036）与评测（T039）。

### Parallel Opportunities

- Phase 1：T001/T002（base.py 单文件串行）完成后，T003/T004（两个提取器文件）+ T009/T010（两个测试文件）四任务并行 [P]。
- Phase 2：T013~T016（迁移与 store 链，串行）完成后，T023/T024/T025/T026/T027（互异文件）五任务并行 [P]。
- Phase 3：T034/T035（同文件分两任务但可合写）与 T036 在提取器完成后并行；T037/T038（语料与数据集互异文件）与 Phase 3 实现并行 [P]。
- Phase 4：T037/T038 若未提前，可与 T041（public 路径测试，不同文件）并行。
- 跨阶段：评测语料/数据集编写（T037/T038）可自 Phase 3 起随时并行。

---

## Parallel Example: Phase 2 词表与约束

```text
# T013-T016（迁移+store 链）完成后，以下五任务并行：
Task: "T023 扩展 backend/tests/unit/test_domain_profile_seed.py（legal 断言）"
Task: "T024 新建 backend/tests/unit/test_graph_expansion_vocab.py"
Task: "T025 修改 specs/003-.../graph-relations.schema.json（pattern 化）"
Task: "T026 修改 specs/003-.../mcp-search-output.graph-annotation.schema.json（pattern 化）"
Task: "T027 更新 backend/tests/contract/_graph_schema_helper.py 与 test_graph_relations_schema.py"
```

---

## Implementation Strategy

### MVP First（Phase 1 = US1 闭合）

1. 完成 Phase 1（T001~T012）→ **STOP and VALIDATE**：VS-01 单测 + 004 图集回归首过 = 插件抽象成立且零回归（SC-001 前半闭合）。
2. 此时可交付：注册表框架 + java/ddl 插件化（后续阶段全部叠加于此）。

### Incremental Delivery

1. Phase 1 → 插件框架 + 004 等价（MVP）
2. Phase 2 → 宽模式 + 词表联动 + 查询侧兼容 + legal 档案（US2 闭合，VS-02/05/08）
3. Phase 3 → 交叉引用提取器 + 防误报（US3 实现，VS-03/04）
4. Phase 4 → 受益闸口 + public/generic 端到端（US3 验证 + US4 闭合，VS-06/07/10）
5. Phase 5 → 全量验收（US5 闭合，SC-001~012 全检）
6. Phase 6 → Polish

每阶段末 Checkpoint 均为独立可验证增量；受益闸口未达阈值时 R11 声明式补救保证 Feature 仍可交付（插件框架 + 可选路径）。

---

## Notes

- 行号锚点（839-842/858-863/491-509/45-49/29-31/38-39/254-275/225）以 2026-09-06 工作树为准，实现时以符号名定位为准、行号为辅。
- 全部 [P] 标注以"互异文件 + 无未完成依赖"为前提；同文件任务串行。
- 宪法硬约束（泄漏=0/Schema 100%/定位 100%/显式 scope）散布于 T041/T043/T044/T047 验收，实现期任务不豁免。
- 每任务或逻辑组完成后提交；阶段末 Checkpoint 验证后再进下一阶段。
