# 记忆巩固需求评审检查清单

**Purpose**: 评审 013 巩固回路要求的完整性、清晰度、一致性、可测量性与异常/恢复覆盖，聚焦确定性控制、安全边界、可重建轨迹和发布闸口。
**Created**: 2026-10-06
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) · [data-model.md](../data-model.md) · [contracts](../contracts/README.md)
**Audience / Timing**: 规格与实现规划评审者；用于任务拆分前及实现前的需求质量评审。
**Depth**: 深入，覆盖用户指定的 12 类风险。

**Review Ownership**: 本清单由评审者维护。只有评审者认定要求质量满足该项时才标记 `[x]`；新生成项全部保持 `[x]`。
**Marker Semantics**: `[x]` 表示该要求已被明确、完整且可客观评审，不表示代码已实现或验收已通过。本文不提供实施通过声明。

## 确定性控制权

- [x] CHK001 是否明确裁决器是模型与确定性提案的唯一批准路径，并将正文、状态变更、候选、链接、语境及依赖传播的所有 effect 纳入该边界？[Completeness, Spec §FR-011/013/020, SC-005; Data Model §6/11; Pipeline Contract §1/5]
- [x] CHK002 是否明确裁决器纯函数的输入快照、固定时钟、策略/词表/配额、输出决定与驳回无 effect 契约，以及提交边界重新取快照并调用同一裁决器的要求？[Clarity, Spec §FR-012/016, SC-005; Data Model §6/12; Pipeline Contract §1/4]
- [x] CHK003 是否明确 Distiller 无直写通道的评审证据要求，包括其依赖/导入、写事件或投影调用、知识源与策略写入口的 grep/rg 检索范围、零允许命中定义及调用路径说明，避免只凭 Agent 输出 Schema 推定权限隔离？[Measurability, Gap, Spec §FR-007/009/011, SC-003/005; Research §5; Pipeline Contract §1]
- [x] CHK004 是否区分 Schema 合法、裁决接受、事务提交和完整发布四种状态，并明确 fallback 二次 Schema 校验、非法模型整包降级及迟到模型结果无生效权限？[Consistency, Spec §FR-008/010/016/017/028, SC-004/011; Data Model §4/6; Pipeline Contract §2/4]

## 硬记忆保护

- [x] CHK005 是否明确新软证据、新硬证据和人工处置三路径的判定矩阵，并规定高置信、硬锚定 distilled、频次及模型自称权限均不构成 hard 替代授权？[Clarity, Spec §FR-013/014, SC-005/006; Research §6; Pipeline Contract §5]
- [x] CHK006 是否完整涵盖替代、失效、隐藏、有效期缩短、降级、归并及传播间接推翻 hard 的效果，并明确其拒绝理由和裁决审计材料？[Coverage, Spec §FR-011/013/017/020, SC-005; Research §6; Data Model §6/11]
- [x] CHK007 是否客观定义软提案推翻 hard 成功次数为 0、全部接受/驳回可定位规则与依据，同时区分既有政策授权的自然 TTL、合法 hard 替代与显式人工处置？[Measurability, Spec §FR-010/013/017, SC-005; Research §6; Pipeline Contract §2/5]

## 投毒纵深

- [x] CHK008 是否明确 quarantined 的两个排除点，即窗口/独立参考集选取与裁决/提交前当前状态复验，并给出 active、quarantined、retired、superseded 四态及到期、未完成、已消费来源的资格要求？[Completeness, Spec §FR-004/005/012, SC-003; Research §4; Pipeline Contract §1/4]
- [x] CHK009 是否明确输入正文及生成摘要、关键词、链接描述、理由均是不可信数据，并规定净化、注入隔离、引用白名单和不得控制 scope/权限/策略/工具/晋升的要求？[Coverage, Spec §FR-009/018/022/025, SC-003; Research §5; Data Model §6/7]
- [x] CHK010 是否明确运行中发生隔离或状态变更时的再复验、拒绝和旧合法状态保留要求，以及审计不得持久化原凭据或其他 scope 失败正文的边界？[Coverage, Exception/Recovery, Spec §FR-009/012/017/027, SC-003/011; Research §5; Pipeline Contract §4/7]

## 轨迹治理

- [x] CHK011 是否明确仅获批 effect 才产生版本化 consolidate 事件、一个事件一个 aggregate、六轴与完整重放材料，并保留 012 旧 flat consolidate 与单指针纠正链兼容性？[Consistency, Spec §FR-014/015/016, SC-006/011; Data Model §7; Pipeline Contract §4/5]
- [x] CHK012 是否清晰界定关系/链接/语境的同事务物化与跨存储 verified manifest 发布边界，规定共享来源/批内输出依赖的原子组、组预算、失败不可见和旧 complete 状态可读，而不将跨存储描述为分布式 ACID？[Clarity, Spec §FR-005/016/017, SC-011; Data Model §5/12; Pipeline Contract §4]
- [x] CHK013 是否完整定义非空 full/snapshot+delta 重建、审计 TTL 后重建、删除传播与 rollback 的一致性口径，以及失败/驳回/未处理来源永久可恢复、仅完整成功结果消费来源的要求？[Coverage, Recovery, Spec §FR-005/020/023/033, SC-007/011; Data Model §5/11/12; Pipeline Contract §4/5]

## 溯源完备

- [x] CHK014 是否明确 distilled 五元元数据的来源、置信度、模型或规则版本、时间、支撑证据字段，并区分原始 LLM 自评、确定性规则依据、政策下限以及 hard 来源 confidence=NULL？[Clarity, Spec §FR-008/012/014, SC-005/006; Data Model §7; Pipeline Contract §1/5]
- [x] CHK015 是否明确源记忆、创建/状态事件、内容哈希与原 episode 的永久定位链，定义完备率 100% 的统计对象和必要字段，同时区分多源历史溯源、单指针 supersede 与实时依赖？[Measurability, Spec §FR-014/015/020, SC-006/007; Data Model §1/5/7/11; Pipeline Contract §5]
- [x] CHK016 是否明确合法软来源无 corpus 锚时非空记忆/事件源链、显式空 evidence_refs、推断标记与禁止候选的要求，并规定历史来源正常归并/TTL/purge 不自动否定永久派生结论？[Consistency, Spec §FR-014/020/024, SC-006/008; Data Model §7/11; Pipeline Contract §5]

## 知识候选治理

- [x] CHK017 是否完整定义 active、高置信、semantic、同域 published 硬锚逐条位置/内容归因的候选资格及候选版本，明确标记不改变 provenance、不等于知识发布？[Completeness, Spec §FR-024/026, SC-006/009; Data Model §10; Management API §GET /promotion-candidates]
- [x] CHK018 是否明确自动入知识库正身次数为 0，以及 writer 管理面人工显式晋升的行动者、理由、当前候选/证据/权限复验；普通 MCP、Distiller、维护和量阈值不能发起晋升？[Measurability, Spec §FR-002/025, SC-002/009; Data Model §10; Management API §POST /promote]
- [x] CHK019 是否完整定义原记忆保留、永久晋升指针、稳定任务/来源/版本与 ProcessingRun attempt 的关系，以及同候选版本幂等、事务/调度失败恢复、失败重试和未发布不报 published 的要求？[Coverage, Recovery, Spec §FR-026/029, SC-009/010; Data Model §10; Management API §POST /promote / GET /promotions/{task_id}]

## 链接图

- [x] CHK020 是否明确 typed 边字段、来源标记、置信度、运行身份和同域端点校验，区分独立记忆词表与文档图词表，并将三元组唯一性限定在 scope/complete revision 内以保留历史与 012 evidence/supersedes 基础边？[Consistency, Spec §FR-018/019, SC-007; Data Model §2/8; Pipeline Contract §6]
- [x] CHK021 是否明确 live_dependency、historical_lineage、association 的语义分类与传播方向，涵盖必要支持撤销、历史来源自然退场、环/高扇出预算和继续前沿，且状态变化仍经裁决与权威事件？[Clarity, Spec §FR-020, SC-008; Data Model §2/11; Pipeline Contract §5]
- [x] CHK022 是否明确链接为可无模型重建的只读投影、正常扩展默认关，正式启用需客户端 opt-in、域许可与当前版本三闸证据，并规定失效端点过滤、原预算内降级及隔离评测不授予正式许可？[Completeness, Spec §FR-021/023/032/035, SC-001/007/012; Data Model §8; Pipeline Contract §6; Recall Extensions v2]

## 语境派生列

- [x] CHK023 是否明确 context_digest/keywords 的生成、净化、Schema、长度/数量预算、逐附件裁决和版本来源，以及模型失败/驳回时保留已有合法版本的要求？[Completeness, Spec §FR-022, SC-004/008; Data Model §9; Pipeline Contract §2/6]
- [x] CHK024 是否客观定义派生语境不改变正文、事实、kind、provenance、证据、纠正链和正文哈希，且仅展示/导航、不参与 embedding、召回候选、改写、过滤、排序或 RRF 的边界？[Measurability, Spec §FR-022/035, SC-008/012; Data Model §1/9; Pipeline Contract §6; Recall Extensions v2]
- [x] CHK025 是否明确永久事件保存具体获批文本、关键词及版本，而非仅指纹/提示版本，并定义审计到期后的逐字段、scope、源链、数量与指纹重建/rollback 一致且模型调用为 0？[Clarity, Spec §FR-023/029, SC-007/008; Data Model §7/9; Pipeline Contract §4/6]

## 审计

- [x] CHK026 是否明确 consolidation_runs 的字段、累计观察序号和全部运行/局部结果状态，规定进度与终态仅追加、不 UPDATE 既有窗口/输入/提案/裁决/产出，并区分 accepted、committed、pending 与 failed？[Clarity, Spec §FR-027/028, SC-010/011; Data Model §4; Management API §GET /consolidation/runs/{run_id}]
- [x] CHK027 是否明确默认 7 天 TTL、仅 maintenance 到期清理及清理审计，禁止其删除权威源链/有效投影或释放活动资格，并保证 created_by_run 不依赖短期审计 FK？[Consistency, Spec §FR-003/027/029, SC-002/007/010; Data Model §3/4/8; Pipeline Contract §3]
- [x] CHK028 是否明确 provider_usage 的沿用口径、actual/estimated/unavailable 与缓存命中/真实 transport 区分，未知 token/cost 为缺失而非伪造零，以及报告可查率 100% 的对象和降级原因？[Measurability, Spec §FR-028/031/035, SC-001/004/010; Data Model §4; Management API §GET /consolidation/runs/{run_id}; Evaluation Contract §Cache/record/replay]

## 闸口

- [x] CHK029 是否明确冻结至少 6 个 distinct query ID 的 2 提炼/2 纠正/2 合并构成、semantic/procedural 各 1 条、真实快照和非空相关性，并定义 K=5、宏平均、等价组、重复 rank 和零基线不可计算口径？[Clarity, Spec §FR-030/031, SC-001; Evaluation Contract §Frozen dataset / Relevance and metrics]
- [x] CHK030 是否明确 MRR 与 nDCG 各相对提升 ≥3% 且 HitRate/Recall@K/Precision@K 均不下降，缓存 record/replay 冻结材料与成功/失败响应，次轮真实 LLM 网络为 0、非延迟 1% 容差与安全零容差？[Measurability, Spec §FR-031/035, SC-001; Evaluation Contract §Relevance and metrics / Cache/record/replay]
- [x] CHK031 是否明确缓存缺失/损坏/版本不符、未评测或质量未达标不得过闸，两默认开关关闭而能力保留；安全失败阻断发布，三闸全过仅产生默认启用资格且不自动修改域策略？[Consistency, Spec §FR-032/035, SC-001/013; Plan §Validation And Delivery Gates; Evaluation Contract §Triple gate and release]

## 并发

- [x] CHK032 是否明确三种触发及恢复共用独立 scope 资格、数据库活动部分唯一索引、忙碌显式拒绝并返回现有 run_id，禁止静默排队/合并；与 append-only 审计和普通写锁的职责是否区分？[Clarity, Spec §FR-001/003/027, SC-002; Data Model §3/4; Pipeline Contract §3; Management API §POST /consolidation]
- [x] CHK033 是否明确资格 TTL/心跳、持有者/lease/run/版本完整 token、接管 generation、提交原子复验与锁顺序，涵盖到期旧持有者和旧任务释放新资格成功次数为 0？[Coverage, Recovery, Spec §FR-003/012, SC-002; Data Model §3/12; Pipeline Contract §3]
- [x] CHK034 是否明确 provider 信号量的归属与并发上限、取得/等待或拒绝语义、异常释放和取消规则，并规定超时但底层调用尚未终止时仍占用 provider slot；是否区分最多 2 个 scope worker 与真实供应商调用上限？[Completeness, Gap, Spec §FR-006/010, SC-004/012; Plan §Technical Context; Research §2; Pipeline Contract §3]
- [x] CHK035 是否完整定义同步 LLM 的有界 worker/thread 运行、前台同步等待为 0、自动触发空闲判定、量阈值仅离线提示、手动容量拒绝，以及 provider/运行耗尽与迟到结果的可观察降级要求？[Coverage, Non-Functional, Spec §FR-001/006/010/028, SC-004/012; Plan §Technical Context; Pipeline Contract §2/3; Management API §POST /consolidation]

## 012 E2E 无回归

- [x] CHK036 是否明确按原口径保留并重跑 012 八项 E2E：硬锚闭环、无锚拒写、跨域隔离、supersede、注入隔离、TTL/配额、reader 无写、会话时间线，以及 001–012 既有全集，不把 skip/缺证据计为通过？[Completeness, Spec §FR-034, SC-013; Plan §Validation And Delivery Gates; Evaluation Contract §Triple gate and release]
- [x] CHK037 是否明确新增六类巩固 E2E 与 AOEP 权威边界、范围不扩张、来源保留、删除传播、可追溯 rollback 五不变量各至少 2 例，并覆盖资格接管、模型/Schema 降级、非空派生重建与 TTL 后恢复？[Coverage, Spec §FR-033/034, SC-004/007/011/013; Plan §Validation And Delivery Gates; Research §12; Evaluation Contract §Triple gate and release]
- [x] CHK038 是否明确旧 search_knowledge/get_evidence/list_knowledge_domains 与未 opt-in 客户端的契约、默认召回、预算和超时兼容要求，以及 target-host/环境证据、非覆盖报告、安全零容差和各旧组质量非劣口径？[Consistency, Spec §FR-034/035, SC-012/013; Plan §Validation And Delivery Gates; Pipeline Contract §6; Evaluation Contract §Runner interface / Triple gate and release]

## Notes

- 每项方括号首先标注要求质量维度，随后给出规格 ID 与设计引用。`Gap` 表示需评审材料是否已补齐，不表示实现已失败。
- `Data Model` 对应 [data-model.md](../data-model.md)，`Pipeline Contract` 对应 [pipeline-contract.md](../contracts/pipeline-contract.md)，`Management API` 对应 [management-api.md](../contracts/management-api.md)，`Evaluation Contract` 对应 [evaluation-contract.md](../contracts/evaluation-contract.md)，`Recall Extensions` 对应 [recall-extensions.md](../contracts/recall-extensions.md)，`Research` 对应 [research.md](../research.md)。
- grep/rg 是无直写通道要求的评审证据类型；该项评审要求是否明确，不声称已检索或已证明无通道。
- CHK034 专门审阅 provider 并发控制的明确性；现有有界 scope worker/thread 描述不能单独替代真实调用槽位、取消和迟到占用规则。
- 评审意见可追加于对应项后；生成器不替评审者修改勾选状态。
- `$speckit-implement` 读取清单状态作为入口闸口，不应修改这些标记。`checklists/requirements.md` 保留其由 specify/clarify 维护的独立生命周期。
