# Requirements Review Checklist: Knowledge Domain Generalization (007)

**Purpose**: 评审 007 的 spec/plan 在七类高风险维度上的需求质量（完整性/清晰性/一致性/可测性/覆盖度）。本清单是「需求的单元测试」——检验判据是否被清晰、可测量、完整地书写，而非验证实现行为。
**Created**: 2026-09-06
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) · [research.md](../research.md)

**Note**: 本清单由 `/speckit-checklist` 命令基于 feature 上下文与评审要求生成。
**Review Ownership**: 本清单是评审者所有的需求质量评审工件。仅当评审者判定该需求质量判据已满足时，方可勾选 `[x]`。
**Marker Semantics**: `[x]` 表示该判据经评审后满足需求质量要求；它不代表实现工作已完成。

## 1. 宪法合规（v1.3.0 十一原则 + 五硬约束）

- [x] CHK001 双参数显式作用域（project_scope OR domain_scope 任一形式、二者至少一个非空）是否以可证伪的拒绝判据明确，而非仅以"必须显式引用"一笔带过？ [Completeness, Spec §FR-007/FR-019, 宪法 I]
- [x] CHK002 "禁止推断隐式活动域 / 默认全库搜索"是否以可测断言（全库回退事件数 = 0、拒绝率 100%）量化？ [Clarity, Spec §FR-019/SC-012, 宪法 I]
- [x] CHK003 领域中立（XI）：领域差异仅经 DomainProfile 声明、代码路径禁止硬编码，是否为四层消费点（格式/切片/图/编排）分别落位并标注 007 不接线（属 008/009/010）？ [Coverage, Spec §FR-006, 宪法 XI]
- [x] CHK004 "se-project 是首个内置域档案、而非系统默认假设"（XI）是否在 spec/plan 显式表述，避免默认 SE 语义回流？ [Completeness, Spec §FR-004, 宪法 XI]
- [x] CHK005 五条硬约束是否逐条映射到专属 FR 与可测 SC（串库=0 / 显式引用拒绝 / Schema 100% / 定位 100% / list 无知识内容），而非散落无锚？ [Traceability, Spec §FR-019~FR-022/SC-003~SC-006, 宪法 硬约束]
- [x] CHK006 跨域泄漏 = 0 是否给出"结果 / 证据 / 图关系 / Chunk"四表面的泄漏定义与混合域验收集断言？ [Measurability, Spec §FR-020/SC-003, 宪法 硬约束]
- [x] CHK007 plan.md 的 Constitution Check 是否对十一原则 + 五硬约束逐条给出 PASS 依据、无违规结论与 Phase 1 设计后复核，而非仅列表占位？ [Completeness, plan.md §Constitution Check]

## 2. 双参数兼容性（旧客户端逐字节不变的证据性判据）

- [x] CHK008 "逐字节不变"是否给出可证伪判据——明确比较哪些响应字段（错误码/错误消息/candidates/输出结构）与比较方法（升级前后逐字节比对）？ [Clarity, Spec §FR-009/SC-001]
- [x] CHK009 兼容测试请求集是否枚举覆盖形态（成功/歧义/缺失/非法输入），而非仅一句"旧客户端零破坏"？ [Coverage, Spec §SC-001]
- [x] CHK010 双轨错误码是否覆盖"混合请求中 project_scope 条目歧义但 domain_scope 非空"的裁决（按请求形态发新码），该边界是否落笔？ [Clarity, Spec §FR-010, Edge Cases]
- [x] CHK011 "二者至少一个非空"的执行落点（契约 schema 以 anyOf 表达 vs 入口层显式校验并集非空补位）是否明确且二者一致？ [Clarity, Spec §FR-007, research §1.3]
- [x ] CHK012 双参数并集去重（同域被两参数重复引用/字面重复只参与一次）与空串/纯空白条目跳过语义是否分别明确？ [Completeness, Spec §FR-007, Edge Cases]
- [x] CHK013 错误码枚举"只增不删"（旧码全保留、新码追加）是否明确，以保护旧客户端 schema 校验不回退？ [Completeness, Spec §FR-010]
- [x] CHK014 candidates 增量字段（scope_type/domain_key/slug）是否明确"仅新码响应携带、旧码响应的 candidates 字节级保持 1.0 形态"？ [Clarity, Spec §FR-010]

## 3. 三处残留修复的行为验证判据

- [x] CHK015 三处修复是否各映射到独立可测验收判据，并标注缺陷定位（evidence_service.py:328-372 / retrieval_pipeline.py:451,468 / retrieval_service.py:1114-1122）供评审核实？ [Traceability, Spec §FR-016~FR-018/SC-007]
- [x ] CHK016 public 证据展开修复是否给出量化成功判据（search_knowledge→get_evidence 同作用域链路成功率 100%）而非"修复断链"？ [Measurability, Spec §SC-007]
- [x] CHK017 agentic scope_type 修复是否给出"错标数 = 0"与"project 域证据不受影响"双重判据？ [Measurability, Spec §FR-017/SC-007]
- [x] CHK018 图三元组去 Project 依赖是否给出"graph_ready 的 public 域图路径可用 + 跨域图边泄漏 = 0"双重判据？ [Measurability, Spec §FR-018/SC-007]
- [x] CHK019 三处修复是否明确"仅开启 public 路径、不改变 project 域既有行为"的边界，以杜绝污染既有路径？ [Consistency, Spec §FR-009, US4-AC4]
- [x] CHK020 修复后证据仍携带来源 ID/版本/位置（来源可定位率 100%）是否明确，避免修复以牺牲可定位性为代价？ [Completeness, Spec §SC-005/SC-007]

## 4. list_knowledge_domains 无知识内容泄露判据

- [x] CHK021 "无知识内容"是否以穷举禁止输出清单（chunk 正文/证据摘录/来源片段）明确界定，而非"绝不返回内容"的空泛表述？ [Clarity, Spec §FR-014/FR-022]
- [x] CHK022 零泄露是否量化（全部响应中知识内容出现次数 = 0）且可审计？ [Measurability, Spec §SC-006]
- [x ] CHK023 能力摘要的来源（由域档案声明派生、而非知识内容）是否明确，以封死经 capabilities 字段泄露正文的路径？ [Clarity, Spec §FR-014, research §1.7]
- [x] CHK024 仅活跃域返回与空实例返回空列表 + 成功状态是否明确（archived/deleting 不出现）？ [Completeness, Spec §FR-015, US3-AC3]
- [x] CHK025 "发现域 ≠ 检索知识、不构成宪法 I 禁止的隐式全库检索"的边界是否显式表述？ [Clarity, Spec §FR-014, 宪法 I]

## 5. 隔离测试（跨域串库 = 0 的多域场景）

- [x] CHK026 混合域验收集构成（≥2 project + ≥1 public，跨 se-project/generic 档案）是否明确，避免隔离验收只在单域上自证？ [Completeness, Spec §SC-003/US5]
- [x] CHK027 泄漏定义是否覆盖结果/证据/图关系/Chunk 四表面，且"泄漏事件数 = 0"可断言？ [Completeness, Spec §FR-020, 宪法 硬约束]
- [x] CHK028 唯一图隔离键（knowledge_scope_id）与 project_id 经 scope→Project 联查派生、图数据可重建（宪法 VIII）是否明确，避免图路径隔离语义退化？ [Clarity, Spec §FR-018, research §1.4]
- [x] CHK029 双参数混用与边界形态（空串/重复/歧义）下的隔离场景是否纳入验收集，而非仅覆盖单参数正常路径？ [Coverage, Spec §SC-003, Edge Cases]

## 6. 既有全集无回归判据

- [x] CHK030 无回归义务是否枚举全部套件与各自口径（001/002 基线 11/18、003 格式集、004 图集 37、005 agentic 44、006 冒烟 11）？ [Completeness, Spec §FR-024/SC-009, research §0.1]
- [x] CHK031 "1% 相对容差"是否定义为单侧非回归下界（下降 >1% 判回归、上升记环境敏感漂移、不作质量声明）？ [Clarity, Spec §SC-009, research §0.3]
- [x] CHK032 "无对照评测"声明是否明确禁止质量提升阈值 / 质量对照评测 / 质量提升声明？ [Clarity, Spec §FR-023, research §0.4]
- [x] CHK033 se-project 行为等价性验证口径（004 图集 + 005 agentic 回归闸口）是否明确，而非仅"与 1.0 一致"？ [Completeness, Spec §FR-025, research §1.6]
- [x] CHK034 通过判定三项（既有全集无回归 + pytest 全绿 + 硬指标保持）是否完整枚举为发布闸口？ [Completeness, Spec §FR-024, research §0.3]

## 7. 契约 schema 合法率 100%

- [x] CHK035 契约工件集（mcp-search-input / mcp-get-evidence 输入、list-domains 输出、common 知识域引用与候选定义、错误码枚举）是否完整枚举？ [Completeness, Spec §FR-021, plan.md §契约变更]
- [x] CHK036 输入 anyOf 放宽（`required:["project_scope"]` → anyOf 至少一个）是否在 search-input 与 get-evidence 两 schema 一致表达？ [Consistency, Spec §FR-007, contracts/]
- [x] CHK037 契约是否以独立 `$id`（/schemas/007/）分版本演进、`$ref` 复用 007 common.schema.json 共享定义（宪法 VII 接口独立演进）？ [Traceability, Spec §FR-011, plan.md §契约变更]
- [x] CHK038 100% Schema 合法率是否覆盖 search_knowledge / get_evidence / list_knowledge_domains 三工具全部成功响应并量化？ [Measurability, Spec §SC-004]
- [x] CHK039 输出契约零改动（evidence 的 knowledge_scope_id/knowledge_scope_type 等域中立字段）是否明确为硬约束，防止借道改输出？ [Clarity, Spec §FR-011]

## Notes

- 仅当评审确认对应需求质量判据已满足时勾选 `[x]`；未勾选表示仍需澄清、修正或评审者评估。
- `/speckit-implement` 读取本清单勾选状态作为闸口，且不得修改标记。
- `checklists/requirements.md` 是 `/speckit-specify` 与 `/speckit-clarify` 维护的独立内置规格质量清单，与本清单（评审所有）职责不同。
- 条目按顺序编号（CHK001–CHK039）便于引用；可在条目下追加评审发现。
- 相关文档：[spec.md](../spec.md) · [plan.md](../plan.md) · [research.md](../research.md) · [contracts/](../contracts/)
