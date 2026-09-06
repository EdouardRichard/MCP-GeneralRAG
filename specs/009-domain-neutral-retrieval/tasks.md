# Tasks: Retrieval Orchestration Domain Neutralization（检索编排域中立化）

**Input**: Design documents from `/specs/009-domain-neutral-retrieval/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/
**Tests**: 等价性闸口与回归为硬验收；采用「测试先行」（Phase 1 等价性文本层测试先行、Phase 2 动态词表行为测试、Phase 3 契约/文案测试、Phase 4 回归 + 隔离 + 目标宿主测试）。
**Organization**: 按用户指定 4 阶段（Phase 1 提示词模板化 → Phase 2 动态词表 → Phase 3 契约与文案 → Phase 4 验收）；每任务映射到用户故事（US1~US5）与 FR。

## Format: `- [ ] [ID] [P?] [Story] Description with file path`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 任务归属用户故事（US1~US5，见 spec.md）
- 描述含精确文件路径与 FR 引用

---

## Phase 1: 提示词模板化 + se-project 档案注入（US1, P1）🎯 MVP

**Goal**: 基础系统提示词域中立化（抽象「标识符/定义/关系」）+ se-project 覆盖片段逐句保留 1.0 + 运行时按请求 scope 档案注入（单一档案用覆盖片段、异构/缺失回退域中立模板）。等价性文本层测试先行。

**Independent Test**: 单测断言 se-project 覆盖片段与 1.0 DECOMPOSE_SYSTEM_PROMPT 逐句等价；单测断言域中立基础模板零 SE 举例/词表；单测断言提示词解析三态（单一/异构/无覆盖）。

### Tests (先写，预期 FAIL) ⚠️

- [X] T001 [P] [US1] 编写文本等价性测试：断言 SE_PLANNER_PROMPT 与 1.0 DECOMPOSE_SYSTEM_PROMPT 逐句等价（先 FAIL）于 backend/tests/unit/test_query_planner_prompt.py（FR-002, SC-003, research R5 文本层）
- [X] T002 [P] [US1] 编写域中立审计测试：断言域中立基础模板零 SE 举例（method call/foreign-key/class/table/column/constraint）与零关系词表（calls/called_by/fk_references/fk_referenced_by）（先 FAIL）于 backend/tests/unit/test_query_planner_prompt.py（FR-001, SC-003）

### Implementation

- [X] T003 [US1] 将 1.0 DECOMPOSE_SYSTEM_PROMPT 逐句迁入 SE_PLANNER_PROMPT（保留全部 SE 举例与关系词表）于 backend/src/rag_mcp/config/domain_profiles.py（FR-002, research R5；使 T001 转绿）
- [X] T004 [US1] 新增域中立基础模板 + 关系词表槽位填充助手于 backend/src/rag_mcp/config/domain_profiles.py（FR-001, research R1；使 T002 转绿）
- [X] T005 新增 DomainProfileService.resolve_planner_config(session, scope_ids) -> dict（查 knowledge_scopes.domain_key → domain_profiles → 派生 distinct_domain_keys / relation_vocab / prompt_override）于 backend/src/rag_mcp/services/domain_profile_service.py（research R7）
- [X] T006 在 entry.run_agentic_search 解析 scope_ids 后调用 resolve_planner_config 并注入 context 键 domain_planner_config 于 backend/src/rag_mcp/orchestration/entry.py（research R7）
- [X] T007 [US1] 实现提示词解析（单一档案有覆盖 → 用覆盖片段；异构/无覆盖 → 域中立基础模板 + 词表槽位填充）于 backend/src/rag_mcp/agents/query_planner.py（FR-003, research R1）
- [X] T008 [P] [US1] 编写提示词解析单测（单一 se-project / 单一 generic / 异构 se-project+generic / 无覆盖自定义档案）于 backend/tests/unit/test_query_planner_prompt.py（FR-003, SC-003）

**Checkpoint**: se-project 提示词等价性文本层成立、域中立基础模板零 SE、提示词解析三态正确。

---

## Phase 2: relation_directions 动态词表（US2, P1）

**Goal**: relation_directions 允许值/默认方向集由域档案 graph_relations 键集动态派生（移除模块级硬编码 4 值）；无图档案空词表 → NODE_SCHEMA 省略 relation_directions/graph_hop、signals 去除 graph；005 结构等价层回归。

**Independent Test**: 单测断言 se-project 词表=4 值、generic 词表=空、异构词表=并集；单测断言空词表省略字段且 fallback 省略；005 agentic 44 条 signals/relation_directions 逐条与 1.0 一致。

### Implementation

- [X] T009 [US2] 实现 _build_node_schema(relation_vocab) 动态工厂（词表非空含 relation_directions enum + graph_hop；空则省略二者且 signals 仅 [dense, sparse]）+ 按 frozenset(vocab) 缓存的 per-request 校验器于 backend/src/rag_mcp/agents/query_planner.py（FR-005/FR-008, research R2）
- [X] T010 [US2] 移除模块级硬编码 BIDIRECTIONAL_DEFAULT / VALID_DIRECTIONS 常量与静态 NODE_SCHEMA relation_directions 枚举（改为从 domain_planner_config.relation_vocab 派生）于 backend/src/rag_mcp/agents/query_planner.py（FR-005, SC-005）
- [X] T011 [US2] 使 _validate_signals / _validate_directions / get_default_directions 从 per-request relation_vocab 派生（无图时 graph 不可规划、方向回退域档案默认词表）于 backend/src/rag_mcp/agents/query_planner.py（FR-006/FR-007）
- [X] T012 [US2] 更新 _build_fallback_output：无图档案省略 relation_directions 与 graph_hop（fallback 输出与 schema 一致）于 backend/src/rag_mcp/agents/query_planner.py（FR-008, 澄清 Q4）

### Tests

- [X] T013 [P] [US2] 编写动态词表单测（se-project=4 值 / generic=空 / 异构=排序并集；signals 枚举与 graph_hop 存在性随词表）于 backend/tests/unit/test_query_planner_schema.py（FR-006, SC-004, research R4）
- [X] T014 [P] [US2] 编写空词表行为单测（NODE_SCHEMA 省略 relation_directions/graph_hop、signals 不含 graph、fallback 省略、产出 schema_valid=true）于 backend/tests/unit/test_query_planner_schema.py（FR-008, 澄清 Q4）
- [ ] T015 [US2] 运行 005 agentic 结构等价回归（44 条 signals/relation_directions 逐条与 1.0 一致；AGENTIC_LLM_CACHE_PATH + temperature=0.0 字节复现）于 eval/run_agentic_comparison.py（SC-001, research R5 结构层）

**Checkpoint**: 动态词表正确、无图档案省略字段、005 结构等价层通过。

---

## Phase 3: 契约与文案域中立化（US3 + US4, P2）

**Goal**: task_context 新增 activity + 描述域中立化（US3）；SourcePosition 描述替换为定位前缀规范表、get_evidence/gaps 去 project 措辞（US4）；契约与文案测试 + schema 校验。

**Independent Test**: 契约测试断言 activity 被接受、旧字段逐字节不变；契约测试断言 SourcePosition 含前缀规范表、无 Java 符号单例；单测断言 gaps/错误文案域中立且 project_scope-only 兼容路径逐字节不变。

### US3 task_context（FR-009~FR-011）

- [X] T016 [US3] 更新 search_knowledge.py 的 task_context 描述（新增 activity、current_file/current_symbol/work_phase 标注「编码域约定字段（向后兼容）」、additional_context 标注「补充背景兜底」、整体域中立）于 backend/src/rag_mcp/mcp/search_knowledge.py（FR-009~FR-011, 澄清 Q2）
- [X] T017 [P] [US3] 编写契约测试（activity 可选自由字符串被接受且不改变检索；current_file/current_symbol/work_phase 字段名/类型/枚举逐字节不变）于 backend/tests/contract/test_mcp_search_input.py（FR-009/FR-010, SC-006）

### US4 SourcePosition 与文案（FR-012~FR-016）

- [X] T018 [US4] 定稿 SourcePosition 描述为定位前缀规范表（标题路径/page:N/符号路径/sheet:/path:/msg:）于 specs/009-domain-neutral-retrieval/contracts/common.schema.json（FR-012/FR-014）
- [X] T019 [US4] 域中立化 get_evidence SCOPE_MISMATCH 文案（requested project scopes → requested knowledge domains）于 backend/src/rag_mcp/services/evidence_service.py（FR-013）
- [X] T020 [US4] 域中立化 gaps suggested_action 文案（broadening the project scope → broadening the knowledge domain scope）于 backend/src/rag_mcp/services/retrieval_service.py（FR-015）
- [X] T021 [P] [US4] 编写契约测试（SourcePosition 描述含前缀规范表、type: string 结构不变、无 Java 符号单例）于 backend/tests/contract/test_common_009.py（FR-012/FR-014）
- [X] T022 [P] [US4] 编写文案单测（gaps/错误文案泛化知识域措辞 project 残留=0；仅 project_scope 旧错误码/消息/candidates 逐字节不变）于 backend/tests/unit/test_retrieval_wording.py（FR-015/FR-016, SC-007/SC-008）

**Checkpoint**: task_context.activity 契约成立、SourcePosition 前缀规范表成立、文案去 project 且兼容路径字节不变。

---

## Phase 4: 验收（US5, P2）——双回归闸口 + 硬指标 + quickstart

**Goal**: 三 Agent 中立性确认与回归、双回归闸口（005 agentic 44 条 + 004 确定性 37 条）、硬指标三件套（串库=0 / Schema=100% / 定位率=100%）、提示注入边界不变、目标宿主 + quickstart 端到端。

**Independent Test**: 三 Agent 既有 pytest 全绿；双回归闸口非延迟指标 1% 容差；混合域验收集硬指标成立；恶意上传不能改变控制流；DeepSeek Harness 端到端通过 Schema 校验。

- [ ] T023 [US5] 静态审计 + 回归：evidence_analyst / context_orchestrator / injection_detector 已域中立（无 SE 假设）、判定语义不变，既有 pytest 全绿于 backend/tests/unit/（FR-017~FR-019, SC-011）
- [ ] T024 [US5] 运行全量 pytest（unit + contract）于 backend/（SC-011）
- [ ] T025 [US5] 运行 005 agentic 回归闸口（44 条）于 eval/run_agentic_comparison.py --dataset eval/eval_dataset.json --agentic-dataset eval/agentic_eval_dataset.json --output eval/agentic_comparison_report.json（SC-001）
- [ ] T026 [US5] 运行 004 确定性回归闸口（37 条）于 eval/run_graph_comparison.py --dataset eval/eval_dataset.json --output eval/graph_enhanced_comparison_report.json（SC-002）
- [ ] T027 [US5] 硬指标三件套验收（混合知识域验收集上跨域串库=0、MCP Schema 合法率=100%、来源可定位率=100%）于 backend/tests/contract/（SC-009, FR-020~FR-022）
- [ ] T028 [US5] 提示注入防护边界验收（恶意上传不能改变控制流/工具选择/提示词脚手架；域档案注入不经 InjectionDetector、与证据结构隔离）于 backend/tests/unit/（SC-010, FR-019）
- [ ] T029 [US5] 目标宿主端到端测试（DeepSeek Harness MCP 端点：se-project + generic 两域 agentic 检索 + activity 字段，通过输出 Schema 校验）于 backend/tests/（SC-006/SC-012, 006 SC-001）
- [ ] T030 [US5] 运行 quickstart.md 端到端验证（§1~§8 全场景）并确认 SC-001~SC-012 全过（SC-001~SC-012）

**Checkpoint**: 全部硬验收通过，009 可发布。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1（US1）**: 无外部依赖，立即开始；T005/T006（resolve_planner_config + entry 接线）为 US1/US2 共同前置。
- **Phase 2（US2）**: 依赖 Phase 1 的 T005~T007（档案解析接线 + 提示词解析基建）；动态词表消费 domain_planner_config.relation_vocab。
- **Phase 3（US3+US4）**: 与 Phase 1/2 基本独立（契约/文案文件与 planner 改造文件不重叠），可在 Phase 1 完成后并行。
- **Phase 4（US5）**: 依赖 Phase 1~3 全部完成（回归/硬指标需完整实现）。

### User Story Dependencies

- **US1（P1）**: 无其他故事依赖，MVP。
- **US2（P1）**: 依赖 US1 的档案解析接线（T005/T006）与提示词基建（T007）。
- **US3（P2）**: 独立（仅 search_knowledge.py + 契约文件）。
- **US4（P2）**: 独立（evidence_service.py / retrieval_service.py / contracts）。
- **US5（P2）**: 依赖 US1~US4 全部完成。

### Within Each Phase

- Phase 1：测试先行（T001/T002 先 FAIL）→ 实现（T003~T007）→ 补测试（T008）。
- Phase 2：实现（T009~T012）→ 测试（T013/T014）→ 回归（T015）。
- Phase 3：实现/定稿（T016/T018~T020）→ 测试（T017/T021/T022）。
- Phase 4：验收顺序 T023/T024 → T025/T026 → T027/T028 → T029/T030。

### Parallel Opportunities

- Phase 1：T001 与 T002 并行（不同测试关注点，同文件但可先后合并）；T003 与 T004 依赖各自测试。
- Phase 2：T013 与 T014 并行（同文件不同测试函数）。
- Phase 3：US3（T016/T017）与 US4（T018~T022）可并行；T021/T022 并行。
- Phase 4：T025（005 agentic）与 T026（004 确定性）可并行（不同 runner）；T027/T028 可并行。
- 跨阶段：Phase 3（契约/文案）与 Phase 2（动态词表）在 Phase 1 完成后可并行（文件不重叠）。

---

## Parallel Example: Phase 1

    # 并行 A：等价性测试（先 FAIL）
    Task: "编写文本等价性测试于 backend/tests/unit/test_query_planner_prompt.py"
    Task: "编写域中立审计测试于 backend/tests/unit/test_query_planner_prompt.py"

    # 并行 B：基础模板 + 档案接线（不同文件）
    Task: "新增域中立基础模板于 backend/src/rag_mcp/config/domain_profiles.py"
    Task: "新增 resolve_planner_config 于 backend/src/rag_mcp/services/domain_profile_service.py"

## Parallel Example: Phase 4

    # 两个回归闸口并行（不同 runner）
    Task: "005 agentic 回归闸口 eval/run_agentic_comparison.py"
    Task: "004 确定性回归闸口 eval/run_graph_comparison.py"

---

## Implementation Strategy

### MVP First（US1 = Phase 1）

1. 完成 Phase 1（提示词模板化 + 档案注入 + 等价性文本层）。
2. **STOP and VALIDATE**：T001~T008 全绿、se-project 文本等价成立。
3. 可独立交付 US1（编排域中立化的提示词层）。

### Incremental Delivery

1. Phase 1（US1）→ 文本等价成立（MVP）。
2. Phase 2（US2）→ 动态词表 + 005 结构等价层。
3. Phase 3（US3+US4）→ 契约/文案中立化。
4. Phase 4（US5）→ 双回归闸口 + 硬指标 + 目标宿主，可发布。

### Parallel Team Strategy

1. Phase 1 完成 T005/T006（档案接线）后：
   - Developer A：Phase 2（动态词表，query_planner.py）。
   - Developer B：Phase 3（契约/文案，search_knowledge/evidence_service/retrieval_service + contracts）。
2. 二者汇合后共同完成 Phase 4 验收。

---

## Notes

- [P] 任务 = 不同文件/无未完成依赖，可并行。
- [Story] 标签映射任务到用户故事（可追溯，宪法 §Specification 第 5 条）。
- 每任务含精确文件路径与 FR/SC 引用，可直接执行。
- 等价性/回归为硬验收，不设质量阈值、不作质量声明（对照评测：无——编排泛化）。
- 契约/隔离/目标宿主测试已覆盖（Phase 3 契约测试、Phase 4 T027 隔离、T029 目标宿主）。
- 提交粒度：每任务或逻辑组一次提交；Phase 末尾 checkpoint 独立验证。
