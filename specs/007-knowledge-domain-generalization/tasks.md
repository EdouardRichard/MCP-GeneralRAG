# Tasks: Knowledge Domain Generalization (007)

**Input**: Design documents from `/specs/007-knowledge-domain-generalization/`

**Prerequisites**: [plan.md](./plan.md) · [spec.md](./spec.md) · [research.md](./research.md) · [data-model.md](./data-model.md) · [contracts/](./contracts/)

**Tests**: TDD（先红后绿）——每个 Phase 先写测试（确保 FAIL），再写实现使其通过。隔离测试与目标宿主测试显式纳入。

**Organization**: 按用户指定的 5 个技术阶段组织（宪法与迁移基座 → 引用解析泛化 → MCP 契约扩展 → 管理面与前端 → 无回归与验收）。每个任务标注 `[US#]`（映射 spec 用户故事）与 FR 引用，保证 FR/US 可追溯。

## Format: `- [ ] [ID] [P?] [Story] Description with file path`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 映射的用户故事（US1~US5）
- 描述含精确文件路径与 FR 引用

## 用户故事 → 阶段映射

| 用户故事 | 优先级 | 主要阶段 |
|----------|--------|----------|
| US1 双轴知识域与域档案管理 | P1 | Phase 1（模型/迁移/种子）+ Phase 4（CRUD/前端） |
| US2 domain_scope 兼容检索与统一寻址 | P1 | Phase 2（解析器）+ Phase 3（MCP 签名/错误码） |
| US4 三处 public/project 残留修复 | P2 | Phase 2（每处独立任务 + 行为测试） |
| US3 list_knowledge_domains | P2 | Phase 3（新工具 + 无泄露契约） |
| US5 硬性约束、兼容性与无回归 | P2 | Phase 5（既有全集 + 硬指标 + quickstart） |

---

## Phase 1: 宪法与迁移基座（Constitution & Migration Base）

**Goal**: domain_profiles 表 + knowledge_scopes.domain_key/slug 列 + 内置 se-project/generic 种子 + 启动同步（宪法 XI/ADR-3 的地基）。

**Independent Test**: 迁移后 domain_profiles 有两内置行、存量 scope 全部获得 domain_key=se-project 与唯一 slug；启动同步修复漂移、失败显式失败。

### Tests（先写，确保 FAIL）

- [ ] T001 [P] [US1] 契约测试：校验 domain-profiles.management.schema.json 的 profile 记录与 scope_assignment 结构，及内置种子内容形状 → backend/tests/contract/test_domain_profile_schema.py（FR-003/FR-004/FR-021）
- [ ] T002 [P] [US1] 集成测试（RED）：迁移创建 domain_profiles 两内置行 + knowledge_scopes.domain_key/slug 回填（domain_key=se-project、slug 全局唯一）→ backend/tests/integration/test_migration_007.py（FR-002/FR-004）
- [ ] T003 [P] [US1] 单元测试（RED）：内置种子内容——se-project 8 原生格式 + 4 图关系词表；generic 空图关系 + 域中立提示词 → backend/tests/unit/test_domain_profile_seed.py（FR-004）
- [ ] T004 [P] [US1] 单元测试（RED）：启动同步修复内置行漂移 + 同步失败显式失败启动 → backend/tests/unit/test_domain_profile_sync.py（FR-005/SC-008）

### Implementation

- [ ] T005 [US1] 新增 DomainProfile ORM（domain_key PK + supported_formats/chunk_type_extensions/graph_relations/prompt_overrides/default_capabilities JSONB + is_builtin）→ backend/src/rag_mcp/models/domain_profile.py（FR-003）
- [ ] T006 [US1] 扩展 KnowledgeScope：domain_key（FK 缺省 se-project）+ slug（全局唯一）→ backend/src/rag_mcp/models/knowledge_scope.py（FR-001/FR-012）
- [ ] T007 [US1] 迁移 0070_create_domain_profiles：建表 + 种子 se-project/generic 两内置行 → backend/alembic/versions/0070_create_domain_profiles.py（FR-004）
- [ ] T008 [US1] 迁移 0071_extend_knowledge_scopes：加 domain_key+slug 列 + 存量回填（domain_key=se-project、slugify(name)+冲突后缀唯一 slug）→ backend/alembic/versions/0071_extend_knowledge_scopes.py（FR-002/FR-012）
- [ ] T009 [US1] 内置种子定义（se-project/generic JSONB 内容）+ slugify 生成器 → backend/src/rag_mcp/config/domain_profiles.py（FR-004/FR-006/FR-012）
- [ ] T010 [US1] 域档案注册表服务：进程内同步 + 内置只读保护守卫（is_builtin 拒绝修改/删除）→ backend/src/rag_mcp/services/domain_profile_service.py（FR-005）
- [ ] T011 [US1] 应用 lifespan 接入启动同步（同步失败显式失败启动，不静默降级）→ backend/src/rag_mcp/server.py（FR-005/SC-008）

**Checkpoint**: 迁移基座就绪——domain_profiles + 双轴模型落地，US1 数据面可独立验证。

---

## Phase 2: 引用解析泛化（Reference Resolution Generalization）

**Goal**: 统一解析器双参数并集 + slug/type:name 寻址 + 三处残留修复（每处独立任务 + 行为验证测试）。

**Independent Test**: 三种 domain_scope 形态各自寻址成功；三处 public 残留各以独立行为测试闭环；project_scope 路径零改动。

### Tests（先写，确保 FAIL）

- [ ] T012 [P] [US2] 单元测试（RED）：统一解析器双参数并集 + 按 scope_id 去重 + 空串/纯空白跳过 + 混合新旧引用边界 → backend/tests/unit/test_resolver_boundaries.py（FR-007/FR-008）
- [ ] T013 [P] [US2] 单元测试（RED）：slug（全局唯一命中）+ type:name（命中/命中多个→歧义/type 非法）寻址 → backend/tests/unit/test_resolver_addressing.py（FR-012/FR-013）
- [ ] T014 [P] [US4] 集成测试（RED）：public 证据展开——search_knowledge→get_evidence 同作用域链路成功率 100% → backend/tests/integration/test_public_evidence.py（FR-016/SC-007）
- [ ] T015 [P] [US4] 单元测试（RED）：agentic 证据 knowledge_scope_type = 真实 scope_type（public≠"project"、project 域不变）→ backend/tests/unit/test_agentic_scope_type.py（FR-017）
- [ ] T016 [P] [US4] 集成测试（RED）：图三元组去 Project——graph_ready 的 public 域图路径可用 + 跨域图边泄漏 = 0 → backend/tests/integration/test_graph_isolation.py（FR-018/SC-007）

### Implementation

- [ ] T017 [US2] 解析器泛化：resolve_project_refs → resolve_knowledge_scopes（双参数并集 + 去重，project_scope 旧路径零改动）→ backend/src/rag_mcp/services/retrieval_service.py（FR-007）
- [ ] T018 [US2] slug 寻址：domain_scope 内按全局唯一 slug 查找活跃域 → backend/src/rag_mcp/services/retrieval_service.py（FR-012/FR-013）
- [ ] T019 [US2] type:name 寻址：scope_type+精确名称，命中多个返回 AMBIGUOUS_DOMAIN_REF 候选（含 scope_type/domain_key/slug）→ backend/src/rag_mcp/services/retrieval_service.py（FR-013/FR-010）
- [ ] T020 [US4] 残留修复 1（独立任务）：evidence_service._resolve_scope_ids 复用统一解析器（数字 public scope ID 直达 public 域）→ backend/src/rag_mcp/services/evidence_service.py（FR-016）
- [ ] T021 [US4] 残留修复 2（独立任务）：agentic scope_type 硬编码改 scope_type_map 预取查找（:451,:468，主条目与父级条目）→ backend/src/rag_mcp/orchestration/retrieval_pipeline.py（FR-017）
- [ ] T022 [US4] 残留修复 3（独立任务）：迁移 0072_drop_graph_project_id——graph_edge/soft_relation 删 project_id + 重建复合索引 → backend/alembic/versions/0072_drop_graph_project_id.py（FR-018）
- [ ] T023 [US4] 残留修复 3：GraphScope 去 project_id + postgres_graph_store 原始 SQL（INSERT/SELECT WHERE/递归 CTE）改以 knowledge_scope_id 为唯一隔离键（依赖 T022，与 T022 原子提交）→ backend/src/rag_mcp/graph/store/postgres_graph_store.py + graph/store/base.py（FR-018）
- [ ] T024 [US4] 残留修复 3：soft_relation_inference 去 project_id（含调用方 scope 三元组；依赖 T022，与 T022 原子提交）→ backend/src/rag_mcp/graph/soft_relation_inference.py（FR-018）
- [ ] T025 [US4] 残留修复 3：_graph_scope_triple 去除"须存在 Project 行"门槛（:1114-1122；依赖 T022，与 T022 原子提交）→ backend/src/rag_mcp/services/retrieval_service.py（FR-018）

**Checkpoint**: 引用解析泛化完成——domain_scope 三种寻址可用、三处 public 残留闭环、project 域行为不变。

---

## Phase 3: MCP 契约扩展（MCP Contract Extension）

**Goal**: search_knowledge/get_evidence 签名扩展 domain_scope + 入口并集非空校验 + 错误码双轨 + list_knowledge_domains 新工具。

**Independent Test**: 仅 domain_scope 请求合法；错误码双轨正确；list_knowledge_domains 只返回元数据无知识内容；旧客户端逐字节不变。

### Tests（先写，确保 FAIL）

- [ ] T026 [P] [US2] 契约测试（RED）：mcp-search-input / mcp-get-evidence 的 anyOf 放宽 + domain_scope 属性 + 错误码枚举只增不删校验 → backend/tests/contract/test_mcp_input_007.py（FR-007/FR-010/FR-021）
- [ ] T027 [P] [US2] 集成测试（RED）：错误码双轨——仅 project_scope 形态发旧码、涉及 domain_scope 发新码（含混合请求裁决）→ backend/tests/integration/test_error_dual_track.py（FR-010/SC-010）
- [ ] T028 [P] [US2] 集成测试（RED）：旧客户端逐字节兼容——仅 project_scope 请求响应（错误码/消息/candidates/输出）升级前后逐字节一致 → backend/tests/integration/test_byte_compat.py（FR-009/FR-011/SC-001）
- [ ] T029 [P] [US3] 契约测试（RED）：list-domains.output.schema 校验 + 知识内容出现次数 = 0 断言 → backend/tests/contract/test_list_domains_schema.py（FR-014/FR-022/SC-006）

### Implementation

- [ ] T030 [US2] search_knowledge 签名扩展：domain_scope 可选参数 + 入口层两参数并集非空校验（双轨错误码）+ tool description 面向客户端声明「project_scope 与 domain_scope 至少一个非空」（消解运行时 schema 与契约 anyOf 分歧）→ backend/src/rag_mcp/mcp/search_knowledge.py（FR-007/FR-019）
- [ ] T031 [US2] get_evidence 签名扩展：domain_scope 可选参数 + 入口层并集非空校验 + tool description 声明「至少一个 scope」→ backend/src/rag_mcp/mcp/get_evidence.py（FR-007/FR-019）
- [ ] T032 [US2] 错误码双轨落地：解析器/入口新增 MISSING_KNOWLEDGE_SCOPE / AMBIGUOUS_DOMAIN_REF，旧码保留 → backend/src/rag_mcp/services/retrieval_service.py + mcp 入口（FR-010）
- [ ] T033 [US3] 新增只读工具 list_knowledge_domains：活跃域元数据 + 能力摘要（由域档案声明派生）+ 绝不返回知识内容 → backend/src/rag_mcp/mcp/list_knowledge_domains.py（FR-006/FR-014/FR-015/FR-022）
- [ ] T034 [US3] 在 MCP server 注册 list_knowledge_domains（readOnlyHint）→ backend/src/rag_mcp/server.py（FR-014）

**Checkpoint**: MCP 契约扩展完成——新参数、双轨错误码、list 工具全部可用且旧客户端兼容。

---

## Phase 4: 管理面与前端（Management & Frontend）

**Goal**: 域档案 CRUD（内置只读）+ 知识域 domain_key/slug 分配 + 前端域属性展示泛化。

**Independent Test**: 内置档案修改/删除被拒、自定义档案 CRUD 可用、slug 分配/不可变、前端展示 scope_type/domain_key/slug。

### Tests（先写，确保 FAIL）

- [ ] T035 [P] [US1] 集成测试（RED）：域档案 CRUD + 内置只读保护（含字段级修改拒绝）+ 被引用档案删除拒绝 → backend/tests/integration/test_profile_crud.py（FR-005/SC-008）
- [ ] T036 [P] [US1] 集成测试（RED）：知识域创建 domain_key 声明 + slug 分配（重复 slug 拒绝、创建后不可变）→ backend/tests/integration/test_scope_slug.py（FR-012/SC-011）

### Implementation

- [ ] T037 [US1] 域档案 CRUD 服务 + 内置只读守卫 + 知识域 slug 分配/不可变守卫 → backend/src/rag_mcp/services/project_service.py（FR-005/FR-012/FR-026）
- [ ] T038 [US1] REST 路由：域档案 CRUD + 知识域 domain_key/slug 管理端点 → backend/src/rag_mcp/api/projects.py（FR-026）
- [ ] T039 [US1] Pydantic 模式：域档案 + scope 分配（domain_key/slug）请求/响应 → backend/src/rag_mcp/schemas/project.py（FR-026）
- [ ] T040 [US1] 前端：知识域列表/详情呈现 scope_type/domain_key/slug 维度 → frontend/src/pages/（FR-026）
- [ ] T041 [US1] 前端：域档案管理页（CRUD + 内置只读态）→ frontend/src/pages/（FR-026）
- [ ] T042 [US1] 前端 API client：域档案 CRUD + scope 分配接口对接 → frontend/src/api/（FR-026）

**Checkpoint**: 管理面与前端完成——域档案治理与域属性展示闭环。

---

## Phase 5: 无回归与验收（No-Regression & Acceptance）

**Goal**: 既有全集无回归 + 硬指标保持 + 目标宿主验证 + quickstart 全量验证。

**Independent Test**: 五套既有评测在 1% 单侧容差内一致；硬指标（串库=0/Schema=100%/定位=100%）；DeepSeek Harness 端到端过 Schema。

### Tests / 验收

- [ ] T043 [US5] 无回归评测闸口：重跑 001/002（`--limit 18`）、004 图集、005 agentic、006 冒烟，1% 单侧非回归判定 + se-project 等价性（004/005 为闸）→ backend/src/rag_mcp/eval/（FR-024/FR-025/SC-009）
- [ ] T044 [US5] 硬指标验收套件：混合域验收集断言五硬约束——跨域串库=0、无显式引用拒绝、MCP Schema 合法率=100%、来源可定位率=100%、上传内容不得作控制指令（HC3：断言 domain_profiles 仅管理面/迁移写入、上传摄入路径零写）→ backend/tests/integration/test_hard_metrics.py（FR-019/FR-020/FR-021/FR-022；SC-003/SC-004/SC-005）
- [ ] T045 [US5] 逐字节兼容回归闸口：仅 project_scope 兼容测试集升级前后逐字节比对 → backend/tests/contract/test_byte_compat.py（FR-009/SC-001）
- [ ] T046 [US5] 目标宿主验证：DeepSeek Harness 经 MCP 端到端完成 domain_scope 三形态 + list_knowledge_domains 并通过 Schema 校验 → quickstart.md 场景 4/8（SC-001/SC-002）
- [ ] T047 [US5] 运行 quickstart.md 全部 10 场景验证并记录结果 → specs/007-knowledge-domain-generalization/quickstart.md（SC-001~SC-012）
- [ ] T048 [P] [US5] 复核 spec 状态与 review.md 评审清单（FR/SC 全映射无遗漏）→ specs/007-knowledge-domain-generalization/spec.md + checklists/review.md（FR-023/FR-024）

**Checkpoint**: 全部验收闸口通过——007 可发布。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1（宪法与迁移基座）**: 无前置依赖，可立即开始。
- **Phase 2（引用解析泛化）**: 依赖 Phase 1（domain_key/slug 列与模型、内置种子先存在）。
- **Phase 3（MCP 契约扩展）**: 依赖 Phase 2（统一解析器 + 双轨错误码先就绪）。
- **Phase 4（管理面与前端）**: 依赖 Phase 1（域档案服务/模型），可与 Phase 2/3 并行（不同文件面）。
- **Phase 5（无回归与验收）**: 依赖 Phase 1–4 全部完成。

### 用户故事依赖

- **US1（P1）**: Phase 1 + Phase 4；无其他故事依赖。
- **US2（P1）**: Phase 2 + Phase 3；依赖 US1 的 domain_key/slug 数据面。
- **US3（P2）**: Phase 3；依赖 US1 的域档案（能力摘要来源）。
- **US4（P2）**: Phase 2；依赖 US1 的 knowledge_scope_id 隔离键收敛。
- **US5（P2）**: Phase 5；依赖 US1–US4。

### Within Each Phase（TDD）

- 测试先写并确认 FAIL，再写实现使其通过。
- 迁移 → 模型 → 服务 → 端点/工具 → 前端（数据面先于行为面）。

### Parallel Opportunities

- 每 Phase 的 `[P]` 测试任务可并行（不同测试文件）。
- Phase 2 的三处残留修复任务（T020~T025）跨不同文件，可并行；但共享图隔离键的 T022/T023/T024/T025 必须原子提交（迁移删列与图代码去 project_id 不可分开发布，否则中间态图 SQL 报错）。
- Phase 4 可与 Phase 2/3 并行（REST/前端 vs 检索/MCP 不同文件面）。

---

## Parallel Example: Phase 2 引用解析泛化

```bash
# 三个残留修复各自独立任务，可并行（不同文件）：
Task: "T020 残留修复 1 evidence_service.py public 展开"
Task: "T021 残留修复 2 retrieval_pipeline.py scope_type 硬编码"
Task: "T022 残留修复 3a alembic 0072 删 project_id 列"
```

---

## Implementation Strategy

### MVP First（US1 + US2，两者均 P1）

1. 完成 Phase 1（迁移基座）→ 双轴模型 + 域档案落地。
2. 完成 Phase 2（引用解析泛化）→ domain_scope 三种寻址 + 三处残留修复。
3. 完成 Phase 3（MCP 契约扩展）→ 新参数 + 双轨错误码 + list 工具。
4. **STOP 并验证**: US1 + US2 + US3 + US4 独立可测（Phase 5 的逐字节兼容 + 硬指标先行冒烟）。
5. 再交付 Phase 4（管理面）与 Phase 5（全量验收）。

### Incremental Delivery

1. Phase 1 → 迁移基座可独立验收（US1 数据面）。
2. Phase 2 → 检索泛化 + 残留修复可独立验收（US2/US4）。
3. Phase 3 → MCP 契约 + list 工具可独立验收（US2/US3）。
4. Phase 4 → 管理面/前端可独立验收（US1 治理面）。
5. Phase 5 → 无回归 + 硬指标全过（发布闸口）。

### Parallel Team Strategy

- 开发者 A：Phase 1 迁移基座（数据层）。
- 开发者 B：Phase 4 管理面/前端（依赖 Phase 1 模型后并行）。
- 开发者 C：Phase 2/3 检索与 MCP（依赖 Phase 1 后并行）。
- 全部完成后进入 Phase 5 联合验收。

---

## Notes

- `[P]` = 不同文件、无未完成依赖；`[Story]` 映射 spec 用户故事以追溯 FR/US。
- TDD 铁律：每个 Phase 的测试任务先写并确认 FAIL，再实现；每处残留修复配独立行为验证测试。
- 隔离测试（T012/T013/T016/T044）与目标宿主测试（T046）为硬性纳入。
- 契约 schema 文件已在 plan Phase 1 产出，任务引用之做契约测试（T001/T026/T029），不再重建。
- 迁移链从既有 head（0062）续接 0070/0071/0072；迁移仅由 writer 管理进程执行。
- 每完成一个 Phase 在 Checkpoint 独立验证；提交每个任务或逻辑组。
- 避免：模糊任务、同文件冲突、跨阶段破坏独立可测性的依赖。
