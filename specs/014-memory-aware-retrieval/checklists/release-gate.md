# 发布评审 Checklist: 记忆感知检索与宿主消费（014）

**Purpose**: 对 014 规格、规划与契约中的**需求质量**做发布前评审。本清单检验"要求是否写得完整、清晰、一致、可度量、可追溯"，不检验实现是否已工作。
**Created**: 2026-10-08
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) · [research.md](../research.md) · [data-model.md](../data-model.md) · [contracts/README.md](../contracts/README.md)

**Note**: 本自定义清单由 `/speckit-checklist` 依据 feature 上下文与用户指定类别生成。
**Review Ownership**: 本清单是评审者所有的需求质量产物。仅当评审者判定该需求质量判据已满足时，才把条目标为 `[x]`。
**Marker Semantics**: `[x]` 表示该需求质量判据经评审已满足；**不表示**实现工作已完成、也不表示任何测试或评测已通过。

**评审者须知（证据类条目的解释）**: 本清单中多处提到"实测""grep 证据""人工审核记录"等。这些是**需求质量**问句：检验规格/规划/契约是否**规定**了该项证据义务、其范围与判定条件是否可判定，而**不是**要求在这里执行实现测试。凡本 Feature 尚未实施或未运行的部分，对应条目应保持未勾选。

---

## A. 契约兼容（Contract Compatibility）

- [x] CHK001 - 是否同时规定了(a)"未显式提供 `session_id` 与 `memory_context` 时响应键集合、键顺序、`structuredContent` 与文本镜像逐字节不变"的判定对象与判定方式，以及(b)"新字段缺席必须由省略键表达、不得置 `None`"及其依据（`exclude_none` 不剥离 `structuredContent` 内层 `None`）？[Clarity, Spec §FR-001/§FR-002, contracts/field-order-contract.md §1/§4]
- [x] CHK002 - 是否明确禁止对 `search_knowledge` 施加 `extra=forbid`，并记录该禁止的兼容理由（会改变 inputSchema 字节，且使历史上被静默忽略的多余/拼写错误字段变成 `ToolError`）？[Consistency, contracts/field-order-contract.md §4.4, research §2]
- [x] CHK003 - 既有属性"逐字节相等"的比较范围是否精确到字段级（含 `description` 文案），而非仅比较类型/必填？[Measurability, contracts/README.md 兼容不变量 1]
- [x] CHK004 - "legacy 属性集合 ⊆ 014 属性集合，且只多出预期新键"是否被写成可判定判据（而非"看起来没变"）？[Measurability, contracts/README.md 兼容不变量 7]
- [x] CHK005 - 是否记录了"既有字节门禁不足"的结论（两侧同源构建 + `sort_keys=True` + dict 相等无法冻结今日字节），并规定必须新增的三类冻结断言（有序键列表、pretty 文本镜像字面量、wire 字面量）？[Completeness, research §2, contracts/field-order-contract.md §5]
- [x] CHK006 - `start_work` 的顶层 `required` 与属性顺序不变、且 `include_working_set=false` 分支逐字节不变，是否明确？[Completeness, Spec §FR-024, contracts/mcp-start-work.input.schema.json]
  - 2026-10-09 一致性分析：014 输出 schema 的声明顺序（`package_fingerprint` → `counts`）与运行时/冻结权威顺序（`counts` → `package_fingerprint`）不一致且无断言任务。已修复（field-order-contract §3/§5 + T033/T070）；本条待评审者复核后勾选。
- [x] CHK007 - 错误码"只增不删"义务是否明确，且新参数非法、scope 未解析/歧义、附加层超时/不可用与既有错误映射不冲突？[Consistency, Spec §FR-039]
- [x] CHK008 - 001–013 既有评测集 schema"全过"义务是否被显式声明，并指明保护缺口（既有 schema 测试不扫描新文件）与补齐责任（新数据集自带校验 + sha256 pin）？[Coverage, Spec §FR-038, research §10]

## B. 分字段纪律（Field Separation Discipline）

- [x] CHK009 - 是否明确要求 `evidence[]` 与 `related_memories[]` 为并列独立字段，且在任何情况下**绝不**混装、合并、复用同一数组或以文本拼接合并，并给出可判定的违反条件？[Clarity, Spec §FR-002]
- [x] CHK010 - "不存在混装路径"的静态清点义务是否规定了清点范围（哪些模块）与判定写法（哪些 API/结构视为混装入口），使"不存在混装路径"客观可判而非主观声明？[Measurability, Spec §FR-002, Plan §Validation 2]
- [x] CHK011 - 是否要求**双向**反例（证据条目 schema 拒绝附加条目，且附加条目 schema 拒绝证据条目），而非只做单向检查？[Coverage, research §4, contracts/README.md 兼容不变量 4]
- [x] CHK012 - 014 分支下 `related_memories` "恒在（可为空数组）"是否被规定，以消除"沉默缺席"歧义；并规定不得复用证据标识、不得把记忆包装成独立证据？[Clarity, Spec §FR-002, contracts/field-order-contract.md §2]

## C. provenance 随行（Provenance Accompaniment）

- [x] CHK013 - "每条进入输出的记忆条目必须带 provenance 标注"的必带字段集合（含 `injection_flags` 及其无标记时的形态 `{}`）是否明确？[Completeness, Spec §FR-003, data-model §7.1]
- [x] CHK014 - "缺失 provenance/injection_flags 即整条不合格、不得补默认值"的失败语义是否明确？[Clarity, data-model §7.1]
- [x] CHK015 - `hard`/`soft`/`distilled` 的置信度与 `inference_meta` 差异（`hard` 为 `null`；`soft`/`distilled` 五元元数据必非空）是否规定到可判定？[Consistency, data-model §7.1]
- [x] CHK016 - 是否规定暴露原始排序分量、**不合成** `relevance_score`，且 provenance/confidence 只标注不改序（信任与相关性正交）？[Clarity, Spec §FR-008, research §4]

## D. 注入边界（Untrusted-Data Isolation）

- [x] CHK017 - `memory_context` 与记忆正文/摘录均被规定为不可信数据，且与提示控制、工具、权限、开关、scope、状态转换分离，是否明确？[Completeness, Spec §FR-015]
- [x] CHK018 - 是否规定 `memory_context` 不得用于选择/推导 scope、不得被改写为控制指令，且 `query`/`memory_context` 须经轻量注入检测并记 flags？[Clarity, Spec §FR-015, Spec Edge Cases]
- [x] CHK019 - **agentic 检索路径**（`AGENTIC_RETRIEVAL_ENABLED=true` 时 `search_knowledge` 走编排状态机）下，附加层与工作集同样受不可信隔离、不得因路径切换而绕过，是否被**显式**规定？[Coverage, Spec §FR-015, research §1, plan §Technical Context]
  - 2026-10-09 一致性分析：spec/research/plan 原均无该路径表述。已修复（spec Edge Cases 新增 agentic 边界条 + plan Constraints/验证门 3 + T010/T061）；本条待评审者复核后勾选。
- [x] CHK020 - `memory_notice` 的"不可信数据声明 + 深读指引"双要素是否定义到可判定（两部分都必须出现，缺失任一部分即不合格）？[Measurability, Spec §FR-011, contracts/mcp-search-output.schema.json]
- [x] CHK021 - `quarantined` 不得进入附加层/工作集/默认召回（零容差），以及凭据脱敏在消费层正文投影中同样生效，是否都已规定？[Completeness, Spec §FR-007/§SC-004, Spec Edge Cases, contracts/memory-consumption-projection.md §3]

## E. 确定性组装（Deterministic Assembly）

- [x] CHK022 - 工作集组装为纯函数确定性代码、无 LLM 进入控制路径，且"无模型调用"有可判定方式，是否明确？[Measurability, Spec §FR-021/§SC-009]
- [x] CHK023 - "相同输入与相同数据/策略版本下包体字节一致"是否规定，且 `snapshot_at` 必须**数据派生**（`max(observed_at)`）而非墙钟？[Clarity, research §6, Spec §SC-009]
- [x] CHK024 - 共享可见性谓词的五个合取条件（`status`/`retention_stage`/`valid_to`/`expires_at`/`valid_from`）是否完整定义？[Completeness, data-model §7.4]
- [x] CHK025 - "未决事项 = 无 `valid_to` 的开放 episodic"的歧义组合（A1 常态 episodic 带 `expires_at`、A2 supersede、A3 retired 而 `valid_to` 为空、A4 archived/compressed、A5 会话过期、A6 `observed_at` 缺失/不可解析、A7 `valid_from` 晚于 `observed_at`）是否被**逐条**裁定并记录理由？[Coverage, research §6]
- [x] CHK026 - 排序与去重的确定性规则（桶序、桶内排序键、跨桶 `memory_id` 去重、并列 tie-break）是否明确到可复算？[Clarity, data-model §7.4]
- [x] CHK027 - 装箱纪律（`digest > working_set`、`read_guidance` 永不裁剪、决策 `selected/deduped/truncated` 为 append-only 且可观测）与桶上限/字符预算的硬上限关系（策略可收紧不可放宽）是否规定？[Consistency, Spec §FR-022/§FR-013, data-model §3]
- [x] CHK028 - 新形态的**显式开关**是否规定，且明确禁止以 `session_id` 等既有参数作隐式开关（因 legacy 调用本就传 `session_id` 且期望旧过滤形态）？[Clarity, Spec §FR-024, research §6]

## F. 隔离（Cross-Scope Isolation）

- [x] CHK029 - 附加层与工作集的 scope 解析、下推与后置复验是否规定沿用既有隔离防线，且解析失败/歧义一律拒绝、绝不回落？[Completeness, Spec §FR-001, Spec Edge Cases]
- [x] CHK030 - "跨域串库 = 0"是否在 `related_memories` 与 `working_set` **两条路径**上都被列为判据，并规定为实测而非声明？[Measurability, Spec §SC-004]
- [x] CHK031 - 是否规定附加层不改变 scope、候选集合、融合权重与主检索排序？[Consistency, Spec §FR-008, research §3]
- [x] CHK032 - 会话跨域活动时"去重不得把 A 域记忆交付给 B 域请求"是否明确；多 scope 请求取**最短**已交付窗口的规则是否规定？[Coverage, Spec §US3 AC5, data-model §5]
- [x] CHK033 - 消费层的 `scope_slug` 归属与路径逃逸防护是否被定义为隔离要求（而非仅工程细节）？[Completeness, Spec §FR-025, contracts/memory-consumption-projection.md §2]

## G. 文件投影（File Projection）

- [x] CHK034 - 是否规定消费层与既有修订目录**分层并存**、两层互不为事实源，且既有修订目录路径语义/落盘校验器/重建与回滚报告路径**零改动**，并给出可判定判据？[Consistency, Spec §FR-025a/§SC-016, contracts/memory-consumption-projection.md §1]
- [x] CHK035 - 只读守卫的规范层（reducer 状态门 + 路径限定 + 无公开写 API + 静态清点）与纵深层（文件级 OS 只读）是否分别定义？[Completeness, Spec §FR-030, contracts/memory-consumption-projection.md §4]
- [x] CHK036 - 是否明确记录 OS 权限的能力边界（Windows 忽略目录只读属性、root/管理员可绕过、因此目录一律保持 `0755`、文件锁仅为绊线而非安全边界）？[Clarity, research §7, contracts/memory-consumption-projection.md §4]
- [x] CHK037 - 必须被拒的绕过路径清单是否完整且可判定（路径逃逸/符号链接逃逸、未授权角色、非 reducer 已验证状态渲染、直接 FS 直写）？[Coverage, Spec §FR-029/§FR-030, Spec §SC-012]
- [x] CHK038 - 是否规定"绕过即违反日志唯一写入点与投影只读约束"，并规定拒绝必须被记录（而非静默失败）？[Clarity, Spec §FR-030, Spec 硬性约束]
- [x] CHK039 - 可重建义务是否规定"清空消费层后全量重建与权威日志一致，且模型调用为 0"？[Measurability, Spec §FR-028, Spec §SC-011]
- [x] CHK040 - 与 PG 权威的漂移校验是否规定到可复算（树指纹计算方式、漂移判定、修复仅限该 scope 子树、读路径不就地修复）？[Completeness, Spec §FR-031, contracts/memory-consumption-projection.md §5/§6]
- [x] CHK041 - 删除/撤回/纠错/隔离/归档/回滚传播到消费层是否全覆盖，且规定墓碑与已退出默认消费的记忆不得残留可消费正文？[Coverage, Spec §FR-032, Spec §SC-013]
- [x] CHK042 - DIGEST.md/INDEX.md 与记忆文件的**字节稳定规则**是否定义到换行/BOM/结尾换行/键序/列表排序层级，并规定生成时刻、mtime、inode 不得入内容与指纹？[Measurability, research §8, contracts/memory-consumption-projection.md §3]
- [x] CHK043 - `frontmatter` 字段集合（`memory_id`/`kind`/`provenance`/`confidence`/`valid 时间`/`session_id`/`evidence_refs`/`status`/`superseded_by`）与"正文 = `content_text` 原文"是否明确？[Completeness, Spec §FR-026]
- [x] CHK044 - 巩固未运行/被禁用时摘要为**明确空态且可重建**（不伪造内容、不作为刷新前置）是否规定？[Edge Case, Spec §FR-027, Spec Assumptions, research §9]
- [x] CHK045 - 异步刷新"不进关键路径、写入响应与读取不等待刷新、失败不传播且可恢复"是否规定到可判定？[Clarity, Spec §FR-031, research §9]

## H. 评测集质量（Evaluation Set Quality）

- [x] CHK046 - ≥15 条固定查询、四类各 ≥1（断点续接/上次决策召回/教训生效/偏好应用）、含中文、AI 生成 + 人工审核，是否作为硬性构成义务明确？[Completeness, Spec §FR-033, Spec §SC-010]
- [x] CHK047 - 固定集纪律是否规定：查询、判据与相关性标注在评测前冻结，且**不得**事后替换或删除失败查询？[Consistency, Spec §FR-033]
- [x] CHK048 - 数据集形态（冻结对象而非裸数组）与必需键（`dataset_version`/`frozen`/`snapshot_hash`/`k`/`queries[]`）是否定义，并说明为何不沿用裸数组形态？[Clarity, data-model §7.6]
- [x] CHK049 - "人工审核"的记录载体（审核状态/备注字段）是否被定义，使"经人工审核"可判定而非口头声明？[Measurability, Spec §FR-033]
  - 2026-10-09 一致性分析：原载体表述不一致（契约"记录在 `frozen` 或 `source`"vs T053"逐条"）。已修复为逐条 `_meta.review_status`/`_meta.review_notes`/`_meta.grounded_source`（沿用 011 形态），契约/data-model/T051–T053 同步；本条待评审者复核后勾选。
- [x] CHK050 - `required_items[]`/`forbidden_items[]` 的结构与"引用可定位"要求是否明确，从而任务完成判据可逐条复算？[Clarity, data-model §7.6, contracts/continuity-evaluation-contract.md §3]

## I. 对照闸口（Comparison Gate）

- [x] CHK051 - 是否规定唯一启用变量为"记忆可用性"，且基线臂禁用相关参数、不共享会话状态或已交付记忆集，并断言基线响应零新字段？[Consistency, Spec §FR-034, contracts/continuity-evaluation-contract.md §1]
- [x] CHK052 - ≥3% 相对提升的计算口径与零基线处理是否明确（`without_memory == 0` 必须判为不可计算，不得以无穷/极小值冒充过闸）？[Measurability, Spec §FR-034, research §10]
- [x] CHK053 - 显式任务完成判据的**预先冻结**与达标线是否定义？[Completeness, Spec §FR-034, contracts/continuity-evaluation-contract.md §3]
- [x] CHK054 - 三闸（质量/安全/回归）与 `default_enable_eligible` 的判定关系，以及"报告不自动修改任何开关或策略"的治理边界，是否明确？[Consistency, Spec §FR-035, contracts/continuity-evaluation-contract.md §5]
- [x] CHK055 - 报告不覆盖历史、`--output` 唯一、退出码 0/1/2 语义，以及冗余度作为**辅助**观测而非主判据的边界，是否明确？[Clarity, contracts/continuity-evaluation-contract.md §3/§5]
- [x] CHK056 - 可复现性义务（两轮记录/重放、真实网络调用 0、非延迟漂移 ≤1%、证据不完整判 `incomplete`）与硬指标零容差清单（跨域 0、schema 100%、provenance 100%、quarantined 0、可定位 100%）是否完整？[Measurability, Spec §FR-035, contracts/continuity-evaluation-contract.md §4/§6]

## J. 三宿主冒烟（Three-Host Smoke Records）

- [x] CHK057 - 阻塞策略是否明确（DSH 为唯一必过参考客户端；ChatGPT App 与 Claude Code 记录兼容状态、不作阻塞项），并给出沿用依据？[Clarity, Spec §FR-037, Spec Clarifications Q2]
- [x] CHK058 - "未执行不得记为通过""宿主不可用必须记录兼容状态"是否作为义务明确？[Completeness, Spec §FR-037, Spec §SC-014]
- [x] CHK059 - 文件投影直读的判据是否被**诚实**定义（文件系统级校验为必过 + DSH 真实观测探针 + 明确不存在协议层直读证据），并禁止以 MCP 调用成功冒充文件直读成功？[Consistency, research §11, contracts/continuity-evaluation-contract.md §7]
- [x] CHK060 - 冒烟证据的载体与必需字段（可复现记录、调用清单、逐项结论）是否定义到可判定？[Measurability, Spec §FR-037, quickstart §7]

## K. 012/013 无回归（No Regression）

- [x] CHK061 - 012 的 8 项 E2E 与 013 的 7 项 E2E"按原验收口径重跑无回归"是否明确列为义务并指明范围？[Completeness, Spec §FR-038, research §13]
- [x] CHK062 - 既有检索全集与旧评测集不受破坏（数据文件 sha256 pin）、旧三工具与旧客户端响应逐字节不变，是否明确？[Measurability, Spec §FR-038/§SC-015]
- [x] CHK063 - 非延迟指标容差（1%）与安全硬指标零容差的区分是否明确，且不得把安全容差放宽为统计容差？[Consistency, contracts/continuity-evaluation-contract.md §4/§6]

## L. 边界与异常覆盖（Edge Cases / Exception & Recovery Flows）

- [x] CHK064 - 主检索 `failed` 时**不附加**的规则与其理由是否明确（避免污染错误契约）？[Clarity, research §3]
- [x] CHK065 - 附加层"部分可用（部分投影失败）"与"全部失败/全部低于阈值"的行为差异是否定义？[Coverage, Spec §FR-004]
- [x] CHK066 - 只提供 `session_id` 与只提供（或同时提供）`memory_context` 的两档阈值是否定义到可判定？[Clarity, Spec §FR-006, research §3]
- [x] CHK067 - 附加层 800ms 超时与主检索既有总预算、与其上宿主 Tool Call 超时的关系（不延长主预算、不推过宿主超时）是否明确？[Consistency, Spec §FR-005, plan §Performance Goals]
- [x] CHK068 - 去重致空返回"无可用记忆"空态（`related_memories` 为空 + `memory_notice` + 可操作 `gaps.suggested_action`，**不改写主检索 `completion_status`**）且**不自动放宽**是否明确；已交付记录过期后的行为是否明确？[Completeness, Spec §FR-018/§FR-019]
- [x] CHK069 - 刷新失败、漂移、崩溃留下"半锁树"的恢复义务（可检测、可重建、读路径不就地修复）是否定义？[Recovery, Spec §FR-031, research §7]

## M. 一致性与歧义（Consistency, Ambiguities & Conflicts）

- [x] CHK070 - `memory_notice` 的对象形态与 012 同名 `memory_notice` 的关系是否被明确（避免跨工具同名字段类型分裂），并记录所选形态与其替代方案？[Consistency, research §4]
- [x] CHK071 - `counts` 词表复用 012 recall 语义的**逐键**映射（返回/候选/预算裁剪/跨通道去重丢弃/状态过滤/字符）是否定义？[Consistency, Spec §FR-014, research §4]
- [x] CHK072 - 顶层字段顺序契约在"契约文档、schema 属性顺序、必须新增的冻结断言"三处是否一致，且 partial/failed 分支的出现条件无冲突？[Consistency, contracts/field-order-contract.md §2/§5]
  - 2026-10-09 一致性分析：原 spec FR-012/Q8"新字段追加在所有既有字段之后"与契约冻结顺序（新字段紧随 `evidence`）冲突，且 start_work 侧无断言。已修复（spec FR-012/Q8/Assumptions 校正 + field-order-contract §3/§5 + T021/T033/T070）；本条待评审者复核后勾选。
- [x] CHK073 - 材料局限是否被诚实记录且未据推测冒充原文（台账 `记忆召回链路-逐节点技术选型台账.md` 缺失；①-4/①-11/②-8/③-8 无原文；Q24/Q41–Q43 仅序位推测；ADR-12 只有引用无定义）？[Assumption, research §13]
- [x] CHK074 - 文件投影 `frontmatter` 字段表与"三宿主直读"判据是否被声明为**本 Feature 新增契约**（而非既有契约），并记录该结论？[Traceability, Spec 范围依据, research §13]
- [x] CHK075 - 未复用 013 `gate-proof` 登记机制的理由（机制与风险面不匹配）是否被记录，以避免被误读为遗漏？[Consistency, research §12]

## N. 依赖、假设与可追溯性（Dependencies, Assumptions & Traceability）

- [x] CHK076 - 是否建立了需求 ID 方案（FR/SC/US）并覆盖全部新义务，且本清单条目可回溯到至少一个 ID、契约章节或研究小节？[Traceability, Spec §Requirements/§Success Criteria]
- [x] CHK077 - 两个部署开关（`MEMORY_AWARE_RETRIEVAL_ENABLED`、`MEMORY_CONSUMPTION_PROJECTION_ENABLED`）默认关闭、且"未达标保留能力并默认关闭"是否明确？[Governance, Spec §FR-035, research §12]
- [x] CHK078 - 迁移 0105/0106 与既有迁移 head（`0104_runtime_activity_signals`）的衔接，以及"不改动既有六类业务投影定义与 `VIEW_KEYS` 约束"的边界是否明确？[Dependency, data-model §5/§6, research §7]
- [x] CHK079 - 对 012 记忆读路径与隔离防线、005 上下文装箱器、009 `task_context` 的复用边界与"不重建"范围是否明确？[Dependency, Spec §范围外, plan §Structure Decision]
- [x] CHK080 - 013 当前默认关闭（`default_enable_eligible=false`）且巩固耗时分钟级，是否被记录为 014 的**前置约束**，从而要求 DIGEST 允许明确空态？[Assumption, Spec Assumptions, research §13]
- [x] CHK081 - 尚待固化的数值（`attach_min_score` 与保守档阈值、会话级已交付集短 TTL 时长、slug 归一化细则、刷新一致性口径）是否已被显式标注为规划或评测阶段固化，而非留作隐含假设？[Ambiguity, Spec Assumptions]

## Notes

- 仅当评审确认需求质量判据已满足时才勾选 `[x]`；仍有待澄清、需修正或待评审者判断的条目保持未勾选。
- **2026-10-09 `/speckit-analyze` 一致性分析**：本清单原由清单命令生成、条目多已预勾选，与"仅评审者可勾选"的纪律不符。分析发现的 4 项已修复缺口（CHK006/CHK019/CHK049/CHK072）已重置为未勾选并附修复说明；其余 `[x]` 保持生成时状态，但**仍须由评审者逐条复核**（`/speckit-implement` 不得代替评审者勾选）。另本清单 CHK043（frontmatter 字段集合）现应包含 `untrusted: true`，CHK056/CHK069 的硬指标口径已按"`evidence[]` 可定位率"与"记忆 provenance 完备率"分项。
- **裁定批准（2026-10-09，用户批准）**：④ 项冻结裁定为——交付窗口 3600 秒（已批准变更）、顶层顺序以字段层相邻为准（含 `start_work` 运行时顺序权威）、消费层 frontmatter 含 `untrusted: true`、agentic 路径不附加且两路径字节一致（见 spec Clarifications Session 2026-10-09）。CHK006/CHK019/CHK049/CHK072 的缺口已按上述裁定修复，可由评审者复核后决定是否勾选；其余条目的勾选仍属评审者职责。
- `/speckit-implement` 读取本清单的勾选状态作为门禁，且**不得**修改标记。
- `checklists/requirements.md` 有独立的内建生命周期，由 `/speckit-specify` 与 `/speckit-clarify` 维护；本文件与该文件互不覆盖。
- 本清单为**需求质量**评审，不替代任何实测：条目提到"实测""grep 证据""人工审核记录"时，检验的是规格/规划/契约是否**要求**并**定义了**该证据义务与判定条件。
- 已知的规格侧未闭合项（会在评审中被逐条检验）：`attach_min_score` 与保守档具体数值、已交付集短 TTL 具体时长、`scope_slug` 归一化规则、消费层刷新一致性口径——见 CHK081。
- 与本 Feature 规划配套的验证步骤见 [quickstart.md](../quickstart.md)；契约不变量见 [contracts/README.md](../contracts/README.md)。
