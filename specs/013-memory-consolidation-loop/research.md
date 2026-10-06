# Research: 013 记忆巩固回路

日期：2026-10-06。依据当前 [spec.md](spec.md)、宪法 v1.4.0、001–012 代码与两份记忆蓝图。本文完成 Phase 0 技术决策；不是运行验收证据。

## 1. 复用边界与四段管线

**Decision**：延伸 012 权威日志/六投影、005 AgentBase/LLMClient、006 maintenance、007 域治理、008 净化、009 域中立提示纪律。新增 `MemoryDistiller` 和独立离线管线，不加入检索状态机。四段为 `select_window`、`propose`、`adjudicate`、`commit_approved`；裁决只接受冻结数据与显式时钟，返回不可变决定，无数据库、模型或网络依赖。服务提供当前状态快照，并在提交事务中再次调用同一裁决器。

**Rationale**：`MemoryService.apply_event` 禁止原始直写；`memory_reducer.py` 封装唯一投影输入。巩固应复用此边界，而不是建第二套可写记忆仓库。`AgentBase.run()` 对异常降级，但 `_safe_fallback()` 可能返回空对象，因此管线还必须校验 fallback。`LLMClient.chat_json()` 使用同步 httpx；通过有界线程执行，避免阻塞 FastAPI 事件循环。线程超时后的迟到输出一律丢弃，不能继续持有数据库会话或提交资格。

**Alternatives considered**：把 Distiller 放进 005 状态图会增加前台等待；新增队列/多 writer 改造超出范围；直接沿 `record()` 写输出不能表达裁决后的归并、上下文和多源消费。采用现有单 writer 内的有界后台执行器，每次任务创建独立数据库会话。

证据：`backend/src/rag_mcp/agents/base.py`、`agents/llm_client.py`、`services/memory_service.py`、`services/memory_reducer.py`、`server.py`。

## 2. 显式策略、资源上限和默认关闭

**Decision**：在 `MemoryPolicy` 中增加可空的 `consolidation` 配置和 `link_expansion_enabled=false`。旧档案缺少配置时不会激活自动巩固；手动返回配置缺失。现有 `consolidation_enabled=false` 保持原默认。合法 opt-in 必须同时提交显式配置；内置档案仍遵守 `assert_not_builtin`。候选扩展的正式读取还要核验三重闸证据。

下表是首次实现的工程默认值，不声称经过质量校准。评测前冻结，修改后重新评测；绝不按模型输出调整。

| 配置键 | 默认 | 合法范围/约束 |
|---|---:|---|
| `volume_threshold` | 100 | 整数 1–5000；未巩固合格 episodic 数 |
| `batch_size` | 32 | 整数 1–64；一次运行处理一批，窗口不变 |
| `reference_limit` | 64 | 整数 0–128；同域 semantic/procedural 参考集 |
| `max_sources_per_proposal` | 16 | 整数 1–32 |
| `max_chain_depth` | 32 | 整数 1–32；沿 012 源链深度上限 |
| `max_proposals` | 64 | 整数 1–128；超量响应整包降级 |
| `max_events_per_group` | 128 | 整数1–128；共享来源/批准输出依赖的原子组不可拆分，超限整组拒绝 |
| `min_confidence` | 0.80 | 有限数 `[0,1]`；等于下限通过 |
| `candidate_min_confidence` | 0.95 | 有限数 `[min_confidence,1]` |
| `max_links_per_proposal` | 8 | 整数 0–16 |
| `max_context_chars` | 512 | 整数 0–1024；0 禁止新生成 |
| `max_keywords` | 8 | 整数 0–16；每个 1–64 字符 |
| `max_input_chars` | 32000 | 整数 4000–64000；含参考集和元数据 |
| `llm_timeout_seconds` | 30 | 整数 1–60；httpx 与外层一致 |
| `max_llm_calls` | 1 | 整数 0–2；0 为确定性模式 |
| `run_timeout_seconds` | 300 | 整数 30–600；终止新模型调用和新提交 |
| `idle_seconds` | 60 | 整数 1–600；自动工作需前台空闲 |
| `expansion_max_hops` | 1 | 整数 1–2 |
| `expansion_max_nodes` | 8 | 整数 1–16；仍受原读取总预算限制 |

运行资格 TTL 固定 120 秒、心跳 20 秒；单次提交事务超时上限 30 秒。进程最多两个 scope 后台任务、两个模型线程；满额返回资源忙碌而不排队。已有读取预算/超时不增加。所有整数排除 bool，所有浮点拒绝 NaN/Infinity。审计保留复用 `retrieval_ttl_days`，缺省 7 天。

**Rationale**：当前 Pydantic `MemoryPolicy` 是严格 extra-forbid 模型，不能只向 JSON 塞新字段；策略校验、管理面与档案迁移须一起演进。将“缺省关闭”与“有配置的人工 opt-in”明确区分，质量未验证时不能自动改默认策略。质量、安全和回归全过只赋予默认启用资格，报告不能直接修改用户政策。

**Alternatives considered**：从 004 数值推导巩固阈值没有证据；从源 confidence 聚合会违反规格澄清；隐式配置或模型自调预算无法审计。采用固定可配置的保守初值并在隔离数据副本校准。

## 3. Scope 资格、空闲触发与提交 fencing

**Decision**：`consolidation_eligibilities` 是可变运行控制记录，与追加式 `consolidation_runs` 完全分开。部分唯一索引 `UNIQUE(scope) WHERE state='active'`；不在索引谓词中使用 `now()`。每次新资格/接管分配新 `eligibility_id`，同 scope generation 单调递增。心跳只延长期限，不增加 generation；过期资格先显式改为 expired，再申请新资格。

维护空闲、手动、量阈值三类普通触发调用同一 admission 服务，持有当前 writer lease、核验 scope/开关/配置。§8 的可信必要支持失效维护使用同一资格服务的独立 `deterministic_propagation` 上下文，不依赖普通巩固开关/配置，只认可当前可复验失效 proof 和 invalidate 效果白名单；该上下文只能由 writer 维护/治理支持钩子构造。两类运行共用活动冲突、容量、恢复与完整 fencing；普通提交重验开关/配置，维护提交重验可信来源/当前支持 proof/效果限制。活动冲突立即返回 `CONSOLIDATION_BUSY` 与已有 run_id，不等待整次运行结束，不合并或排队。可用非阻塞 scope 事务锁区分很短的 admission/commit 竞争；该竞争返回 `CONSOLIDATION_SCOPE_WRITE_BUSY`，既有活动资格仍优先报告运行忙碌。数据库唯一冲突是最终保障。

提交锁顺序固定：scope 事务锁 → 活动资格行 → 当前 writer lease 共享锁 → 当前域策略/目标/必要证据。资格锁持有到事务结束；提交前及最终发布前使用 `clock_timestamp()` 复验 scope、active、DB 时钟未到期、eligibility_id、generation、holder、run_id 和 live writer lease，不能使用事务起始时的 `now()` 代替。所有恢复/接管遵循同一顺序；旧任务即使模型返回也不能落库。续期与运行终态不负责改变记忆事实。

maintenance 先完成既有 TTL/恢复/清理，再检查显式前台活动计数和最后活动时间。维护空闲与量阈值均要求 idle；阈值检测只设置待检查提示，下一维护 tick 重验真实计数并尝试 admission。提示不是运行队列。手动可在前台活跃时启动，但仍受资源限制。前台路径只做常数时间计数/提示，不等待 Distiller。进程取消、失去 writer lease、超过总期限都会停止后续提交、追加中断审计并尽力释放资格；进程崩溃由到期接管恢复。

**Rationale**：现有 advisory lock 只能串行单次记忆事务；既有 maintenance 仅查 INSTANCE_MODE，不能证明后台仍拥有 writer。独立资格行既提供拒绝语义，也防止审计 TTL 释放有效运行。

**Alternatives considered**：长时间持有 advisory lock会阻塞前台；进程锁无法跨重启保证唯一；在不可变审计表上放活动唯一索引会永久占用 scope。

## 4. 时间窗口、消费与长期恢复

**Decision**：选择时间为系统观察时间，窗口 `[checkpoint, frozen_at)`，同时冻结 scope 权威事件 high-water mark。初次 checkpoint 为最早合格待处理源观察时间；顺序 `(observed_at,event_id)`。排除 quarantined/retired/superseded、已过期、未完成和已消费来源版本。参考集单独选择，不受窗口约束，按稳定 ID 排序并记录版本；不能混作提炼源。

新增现有 `grant` 事件的版本化控制子类 `consolidation_window`，永久封存窗口、high-water mark、所选来源版本、原窗口关联、策略/词表指纹。它不修改事实、不确认消费、不表示提案成功；经可信 admission 控制裁决与资格检查后走原事件/发布服务。新子类的 aggregate_id 使用独立生成 ID，与既有 policy grant 一致。无输入运行只记运行审计，不生成无意义成功事件。

纯reducer只生成日志可知的潜在结果、潜在消费和潜在检查点，不查询manifest或外部发布状态。运行选择器读取verified complete manifest中该日志前缀的同一纯状态，再应用其潜在消费；pending尾部不能用于选取。服务通过批准组事件是否被complete manifest覆盖，将结果分类completed/pending/rolled_back，不把这些外部状态注入Python/SQL reducer，避免循环authority。完整重建先计算潜在状态，六投影验证/发布完成后才开放消费。

结果键不包含run/request ID，依据scope、action、来源创建/状态版本、目标版本、批准内容/附件和规则。共享任何输入来源的已批准多项输出归为同一原子组；group_key取规范化全部成员的哈希，成员只作审计proposal_key。组事件与投影整体提交或整体pending，不留下对尚未追加的另一个输出hash的永久等待。pending占group_key但不消费，恢复先完成该完整组，不新写输出。rollback保持历史键并给恢复条目盖新的state_event_id=rollback event，保留creation身份，使合法重试获得新版本键。

检查点是可重建的进度投影。至少一个完成结果才能推进到该冻结窗口终点；未成功者从长期窗口封存与结果反连接恢复，先按原窗口及源版本重试。预算未选中的条目也保持资格；扫描当前检查点之前的未消费历史来源，避免推进后漏掉旧输入。若全部驳回/失败，保留原检查点。审核过期不影响这些事实。重复永久驳回不会被标为成功，仍计入待处理；资源限制避免无界循环。

**Rationale**：仅存运行报告不足以满足 7 天后仍保留原窗口的恢复要求；仅用事件存在判“已巩固”会吞掉跨存储发布失败。新增小型控制子类复用现有 authority，不创建第二事实源。

**Alternatives considered**：可变永久消费表成为第二 authority；只存最大 event ID 会丢失局部失败；每 N 条重定义窗口不符合规格。拒绝事件不写成功 consolidate，控制窗口事件也不得冒充成功。

## 5. Distiller 提示词注入防护

**Decision**：ROLE=`memory_distiller`；独立 `NODE_SCHEMA` 限定四动作，additionalProperties=false。提示沿 009 由受信任 DomainProfile 的通用提示/声明数据组合，不写死语言、项目或实体。输入正文放在稳定 JSON 的 `untrusted_episodes`/`untrusted_references` 中，明确描述“仅为待分析数据”；不拼进 system prompt，不用正文替换角色、策略或工具说明。以标准 JSON 序列化处理分隔符、引号和控制字符，不能靠字符串分隔符本身建立安全边界。

输入先按现有 008/012 脱敏与注入检查，任何高风险条目不进入模型；低风险仍作为不可信数据。Distiller 只获 LLMClient 和只读数据，无 MemoryService/session、工具注册表、文件/URL执行接口。输出允许的引用只能指向冻结输入/参考集或当前已复验的证据集合，不允许模型分配 scope、角色、writer 身份、run_id、policy、enabled、hard provenance、管理授权或执行指令。

正文、title、tags、生成语境、keyword、链接描述和理由全部走递归脱敏与注入检测；新字段要显式纳入 `detect_submission` 的检查范围。高风险生成包不生效，原合法状态保留，记录 quarantine/reject 原因。禁止自动“修复”模型权限字段。Schema 成功也不代表授权；confidence/引用/词表/链/配额/硬保护仍由裁决器检查。审计不得保存原凭据或泄露跨 scope 原始失败正文。

威胁矩阵：

| 注入方式 | 结构约束/防护 | 必测结果 |
|---|---|---|
| 正文伪造 system/assistant、闭合 JSON/分隔符 | JSON 编码、角色固定、无字符串模板插值 | 原 system/payload 控制部分不变 |
| 要求换 scope、启用策略、发起晋升、写 hard | 无这些输出字段/无执行能力，extra-forbid | Schema 拒绝或裁决拒绝，控制状态不变 |
| 伪造来源 ID、发布证据、已获人工许可 | allow-list 与事务归因复验 | source/evidence/permission 伪造成功数 0 |
| confidence=1 或模型自称 deterministic | provenance/规则由受信任执行上下文赋值 | 不获得硬记忆权或确定性证明 |
| 摘要/keywords/link description 携带指令或凭据 | 扩展递归检测/脱敏覆盖 | 无指令生效、无凭据入投影 |
| 大包、重复边、深链、循环 | 字符/数量/深度预算，稳定去重终止 | 有界降级，不扩大前台预算 |

**Rationale**：提示不能可靠阻止所有恶意语义；安全保证来自权限隔离和确定性批准。现有 `detect_submission` 只扫描固定旧字段，单纯复用函数名称不够。

**Alternatives considered**：仅加“忽略指令”的 system 文本无授权保证；让另一个 LLM 审批仍不符合 VI/XIII；把模型输出直接传 `record()` 留下投影/候选旁路。

## 6. 硬记忆保护判定矩阵

**Decision**：按“目标信任等级 × 证据路径 × 操作后果”判定，涵盖显式替代、retract、merge 隐藏、降低有效期、候选误升权和传播导致退出。置信度与重复频率不是 hard 授权。模型提炼即便硬锚定仍为 distilled，hard confidence 始终 NULL。

| 目标/新依据 | 提炼/关联 | 替代或失效目标 | 唯一合法路径 |
|---|---|---|---|
| hard + 新软证据/模型提案/高置信 distilled | 可保存合法 distilled 结论与不确定性；不能改 hard | 拒绝，包括间接 merge/retract/传播 | 记录 HARD_MEMORY_PROTECTED |
| hard + 新硬证据，只有模型声称或原始证据引用 | 可以提出冲突 | 尚不足以批准 hard 变化 | 新证据逐条归因复验，并走既有合法 hard 替代 |
| hard + 已经可信服务批准的合法新 hard 替代命令 | 保留来源/纠正链 | 可用单指针 revise/supersede | 既有 hard 写入治理，裁决核验授权凭据；Distiller 不能产生凭据 |
| hard + writer 管理面显式人工处置 | 保留全文/历史 | 可按既有管理命令 retire/rollback | 活跃 writer、明确对象/reason/actor、权威管理事件 |
| soft/distilled + 新软依据 | 可按阈值提炼 | 仅有语义矛盾不足以失效 | 可复验等价规则或已批准支持撤销/纠正依据 |
| soft/distilled + 经复验的新硬依据/必要支持撤销 | 可提炼且仍 distilled | 可确定性批准更正/失效 | 记录支持证明、单纠正指针或显式失效，不伪造多父链 |

013 离线模型提案默认没有 hard 替代授权；即使包含新 hard evidence，仍不能自己创建 hard 输出或单方处置 hard。合法 hard 替代沿既有可信写入路径，人工处置沿管理面。若支持失效触达 hard 目标，保持读取时原有证据过滤并生成需人工处置报告，不能自动追加 retire。

确定性等价只覆盖规范化正文哈希且 kind、provenance、证据及关键元数据相容的条目；同正文不同元数据按冲突处理。确定性矛盾只覆盖权威纠正/支持撤销等可证明依据，不从自由文本“理解”冲突。已批准软归并采用一个 keeper，其他输入显式退场并保存 merge lineage，不向 keeper 添加第二 supersede 父指针。

**Rationale**：现有 reducer 的 `retract` 分支无 hard guard；复用其低层能力不能视为新自动管线已有授权。保护必须检查 effect 全集。

**Alternatives considered**：LLM confidence、多数票、新证据文本本身不等于合法 hard 替代；以同哈希忽略 provenance 会隐藏有效 hard 事实。

## 7. 事件版本与 Python/PostgreSQL 双重重放

**Decision**：保留旧 flat consolidate 创建语义，新增 `payload_version=2`、`operation=create|merge|invalidate|derive`。每个事件仍只有一个 memory aggregate；多影响结果使用同事务的事件组，组记录批准 effect 集、proposal_key 和成员顺序。`create` 顶层保留 012 正文/kind/provenance/inference 字段，不原地修改 memory 内容。`merge`/`invalidate` 对现有目标记录状态效果；`derive` 仅追加链接/语境/候选材料，不进入创建分支。

成功事件永久保存原始action、来源创建/状态版本、目标版本、window grant、各生成/治理版本、confidence/阈值、归因、裁决、具体links/context、六轴与运行身份。Agent的content经可信canonicalization转换为012的content_text，同时生成submission_meta、provenance_validation、injection_flags、created_at/updated_at、decay_rate和可空session/agent/task字段；事件Schema检验真实持久payload，不能把Agent字段当事件字段。人工晋升指针使用管理grant，不是第五模型action。

新增迁移在当前 `0094` 后，同步修改 Python reducer、PostgreSQL `memory_log_state()`、immutable-source 校验、`verify_memory_log_projection()`、投影 bypass guards 和已验证 publication receipt。旧迁移不编辑。JSON规范化、事件序、空值、金额/数值、有向边键在两端保持一致；采用同一 fixture 比对每步状态，不只比较最终 count。

同批提案有唯一proposal_id；引用 `proposal_ref` 只指extract/distill的暂定批准输出，不能创造ID/权限。确定性引用图拓扑裁决，未知/自引用/循环/被驳回输出的引用拒绝；互相依赖输出与共享来源一起形成同原子组。提交前分配实际ID、逐项复验/重新裁决。effect总数超过max_events_per_group整组GROUP_BUDGET_EXCEEDED拒绝，不拆组或消费源。

**Rationale**：现有Python与SQL都将consolidate当创建，SQL会拒绝只改Python的投影。012 publication验证六份输出；跨存储没有分布式ACID。同批引用/原子组预算必须显式，否则Schema允许的多duplicate会越过事件组上限。

关系/链接/语境事务失败整体回滚批准组；外部投影失败沿 012 retained-pending protocol：保留可恢复事件，不发布 incomplete manifest，继续暴露上一个 complete 版本。pending 不报告成功、不消费输入，恢复有同样资格 fencing。rollback 恢复高级链接/语境/消费/候选状态，不只恢复 entries/bindings；不能撤销已经执行的外部知识摄入，原晋升任务历史须永久可追踪。

**Alternatives considered**：新增可写 link/context 表形成第二事实源；直接对旧 consolidate 加任意字段不解决创建语义；全局 triple 唯一索引破坏 revision 保留。

## 8. 类型词表与 GEM C3 依赖传播

**Decision**：DomainProfile 新增独立 `memory_link_vocabulary`，缺省空列表，带内容版本。不能复用 `graph_relations`。键为 `^[a-z][a-z0-9_]{0,62}$`；012 内建 evidence/supersedes 继续独立生成与重放。下表是可编辑测试档案的种子提议，不自动填充所有域；裁决按当前域声明，事件捕获批准时语义。

| 种子键 | from → to | category | propagation | recall traversal |
|---|---|---|---|---|
| `depends_on` | dependent → required support | live_dependency | to→from；支持失效传播给依赖者 | from→to |
| `derived_from` | conclusion → historical source | historical_lineage | none；普通源 TTL/归并/purge 不传播 | from→to，仅端点可见时 |
| `elaborates` | detail → general item | association | none | from→to |
| `relates_to` | subject → related item | association | none | both；每边仅存一个声明方向 |
| `contradicts` | claim → conflicting claim | association | none；不授予失效权限 | both |

每个类型还声明允许 from/to kind、是否允许 self-link（首期都 false）。live_dependency 只能声明 to→from 的影响方向，其他 category 必须 propagation=none。模型建议不能改变 category 或传播方向。`deterministic` 必须由代码验证证明；所有 LLM 建议标为 llm_proposed，不能通过一个字段自证。

历史来源证明保存在永久 `source_lineage`，不是默认读取端点。必要事实/证据另用 `required_support`，捕获 fact/evidence 身份、支持角色及撤销语义；必要支持明确被否定或撤销、或者 live_dependency 端点失效时，纯裁决器计算影响。普通历史源 retention 不是事实撤销。显式 live_dependency 的目标已经明确声明“需持续有效”，其过期/退场会传播；未声明的 derived_from 不会。

传播breadth-first按ID排序/visited去重，每轮32层/128节点。它是受信任deterministic propagation上下文，不是新的Distiller调用：可在无合格episode时由维护/治理支持失效挂钩获得同一scope资格并裁决，沿invalidate_contradiction action写v2 invalidate事件，source_refs取永久历史lineage而非新输入，window_id=null，必须有可复验trigger（authority event或证据版本/到期证明）。永久传播材料含visited/depth/frontier/continuation_key；无变更但剩余前沿用受信control grant consolidation_propagation保存，不写空成功事件。

环不改变权限，超预算先记录恢复前沿；读取递归验证必要支持，不等下一轮隐藏陈旧结论。传播维护属于已有删除/有效性纪律，在巩固开关关闭或普通配置缺失时仍做安全过滤/合法失效，不允许create/merge/link/context/candidate/源消费，不调用模型。内部run记录trigger=support_maintenance、execution_context=deterministic_propagation、window=null、input_event_ids=[]，历史refs/proof另存；外部请求及模型不能指定该来源。状态变化仍唯一裁决+日志，完整资格/writer lease/token fencing仍适用，hard目标自动变化被拒。词表变更不改历史；重建捕获语义，当前读取按当前许可过滤。

**Rationale**：GEM C3 是依赖语义，不是关系名字黑名单。把每条 derived_from 都当实时依赖，会因源 episode TTL 错误失效永久知识。

**Alternatives considered**：全局闭合枚举违背 010 纪律；以 relation 名称猜传播不确定；关联边自动 retract 会扩大模型权限。

读取兼容决策：recall_memory添加可选include_linked/include_context，均默认false；客户端显式增强和域/三闸授权同时满足才应用。旧请求原响应/排序不变，三个知识工具byte契约不变；不触及014 search_knowledge/work包组装。

## 9. 链接迁移与语境重建一致性

**Decision**：当前 `memory_links` 位于 `models/memory_views.py`，结构是 `(row_id,scope,revision,node_key,data JSONB)`。将其映射迁入 `models/memory_link.py`，旧 import 保持兼容；同表新增 typed columns，保留 data/node_key/revision。`from_id` 规范化为 string；`to_id` 为 string，`to_kind=memory|evidence`，不能给所有 to_id 加 memory FK。高级边索引唯一 `(scope,revision,from_id,to_id,relation_type)`；每个 complete revision 中恰好实现三元组唯一，历史 revision 允许相同边重复。

新增条目投影列 `context_digest`、`keywords`、`context_version`、`context_source_event_id` 与候选/晋升指针；摘要 projection 保存相同已批准语境记录。生成 payload 必须保存具体 digest、按批准顺序去重的 keywords、源链、模型/提示/Schema版本。digest 为空表示无已批准值，不能用 fallback 文本冒充模型生成。生成语境不改 body hash；dense 的 embedding 输入仍为原正文，context 不得进入检索 metadata filter、query rewrite、RRF 或候选选择。上下文只能在最终选择后按剩余响应预算追加，不得挤掉已选结果。

一致性测试：先生成非空链接/语境 → 记录逐字段、scope、来源和六投影规范化指纹 → 清空隔离副本派生数据/清理过期 run 审计 → full replay → snapshot+delta replay → rollback 到上一批准版本再恢复。Python/SQL、在线/重建、升级前/后均对照；模型/LLM transport 调用严格为 0。词表后改、源正常 TTL、必要支持撤销、关联环、多 scope 各测，不允许空表重建冒充成功。

**Rationale**：只存 prompt/model/hash 不能重建随机生成文本；审计 FK cascade 会丢永久链接。`created_by_run` 仅保留标量身份，无指向到期审计的外键。

**Alternatives considered**：给 revision 表加全局三元组唯一破坏旧历史；把 context 放 embedding 改变排序，违反 Q38 澄清；重建时再调用 LLM 无法逐字段一致。

## 10. 候选与人工晋升恢复

**Decision**：裁决仅为 active semantic、confidence≥candidate_min_confidence、逐条归因复验的同域 published 硬锚标候选，候选 provenance 仍 distilled/原值。无 corpus evidence 的软经验保留 `evidence_refs=[]`，历史 `source_lineage` 非空；与 012 的 `inference_meta.supporting_evidence=['memory:ID']` 兼容，它表示来源记忆引用，绝不能伪称 corpus anchor。

仅 `/api/memories/promote` 的显式管理动作可以创建任务。抽取现有 upload 的公共“受净化内容 → raw source → uploaded KnowledgeSource → ingestion 调度”服务，上传与晋升共用；不从后台合成 HTTP 自调用。稳定 promotion task_id 使用管理 pointer grant 的 event_id，任务身份在永久事件与其投影中保存；同事务预建现有 `ProcessingRun(pending)`，`IngestionService.ingest` 支持验证并使用这个已有 run，而非再建一次。唯一 `(scope,memory_id,candidate_version)`；同一版本请求返回原 task/source/initial processing run。摄入失败沿现有 reprocess 重试，可增加有记录的 execution attempt，但不得增加稳定 promotion task 或知识源。

raw 文件先以稳定安全名称原子写入，事务内复验候选并创建 source/task 与管理 grant pointer，提交成功后调度；残留未引用文件由既有清理纪律回收。pointer 事件永久保存 task/source/版本标识和申请者，任务状态变化再追加 pointer result；崩溃可从任务/source 和 pointer 重建/补记状态。只有既有 publication 确认才返回 published，uploaded/processing/failed 均明确显示。rollback 保留外部动作轨迹，不宣称撤销已出版知识。

**Rationale**：当前 upload 提交 uploaded source 后调用 `_schedule_ingestion`，并无适合晋升幂等性的稳定 task ID。任务创建与知识发布必须区分。外部文件、数据库和摄入没有一个跨系统事务，需稳定身份和恢复协议。

**Alternatives considered**：直接写 chunks/knowledge_versions 绕过上传治理；把候选设为 published 违反人工晋升；仅用 request_id 幂等会让重复候选请求生成多份知识。

## 11. 六条受益子集的统计口径与缓存

**Decision**：冻结至少六个独立 query ID：S1 semantic 提炼、S2 procedural 提炼、C1 支持撤销/纠正、C2 单指针纠正、M1 等价 episodic 归并、M2 同域参考集去重；每条只计一个主类。依赖和关联覆盖叠加 C1/M2 等，不另占配额。采用真实目标域语料的固定来源快照，标注非空的“有效事实/操作/证据等价组”，新 ID 必须保留合法源链才能映射，错误/失效事实不因为词相同被视为相关。不能只用合成 fixture 的通过结果宣称实域质量过闸。

K=5，宏平均。MRR沿004首个相关结果reciprocal rank；nDCG沿eval/run_eval.py的二元gain∈{0,1}与log2(rank+1) discount，不引入分级gain。HitRate为至少一项relevant；Recall@5为不同relevant等价组/标注组；Precision@5为前五首次正确相关位置/5。duplicate alias只首次gain=1，其他保持物理rank且gain=0；缺位0。IDCG按冻结binary相关单元和K计算。

质量通过要求 MRR、nDCG 均 `(after-before)/before >= 0.03`，以及 HitRate/Recall@5/Precision@5 非下降。before=0 时该相对项标 not_computable，不能用 infinity 或 epsilon 凑通过；必须重新冻结有可计算对照的新数据版本，不在原报告删行。六条只能支持该固定结构子集的门槛判断，不宣称总体统计显著；报告给每条差异及可选区间，不以显著性测试替代既定阈值。

三条对照路径：baseline（未巩固/无扩展）、consolidated_direct（巩固/无扩展）、consolidated_candidate_expansion（隔离评测显式扩展）；分别报 direct 和 expansion 指标，报告声明 gate_variant，不能掩盖直接路径回退。其他查询、读取预算、配置、时钟、模型/提示/Schema、政策/词表一致；只有巩固输出及声明的扩展开关不同。语境 A/B 有无必须证明候选和排序完全相同。

复用005缓存原键，生产行为不改；payload固定键序/冻结版本，排除变化run/request。sidecar保存全部预期键、内容hash与版本。record→replay只阻断LLMClient的供应商transport，Qdrant/数据库/其他既有provider访问单独记用量，不全局patch httpx。LLM cache缺失/损坏/manifest不一致/额外LLM请求或真实LLM调用均evidence_complete=false；ok=false失败也重放，不沿005 gap-fill补齐后说复现成功。

报告分 cached_requests、recorded_success/failure、replayed_success/failure、missing/corrupt/version_mismatch、真实 transport 请求和实际供应商 usage；现有 `LLMClient.calls` 在未配置供应商时也加计数，不可当真实网络数。无法获取 token/cost 为 null+unavailable，不能伪造 0。次轮非延迟指标相对变化≤1%；0基线用绝对相同判定；硬指标、响应成功/失败重放一致率和零网络要求无容差。质量、硬安全、001–012 回归全过才给 default_enable_eligible=true；报告不执行策略发布。

**Rationale**：004 的结构子集方法可复用，旧报告数值不能作 013 基线。六条样本较小，因此必须预冻结，保留失败并限制结论范围。现有缓存是 read-through，不能直接提供零网络证据。

**Alternatives considered**：只报 recall 或 3 个百分点不是用户选定口径；重复查询/事后筛样虚增质量；仅统计缓存命中忽略真实 transport 无法证明重放。

## 12. LLM 故障注入与轨迹测试

**Decision**：同一快照/策略/时钟下对比 normal、max_llm_calls=0 和故障版本，确定性结果键/有效状态相同。模型失败不得阻止既有 TTL，也不得把故障输出当 deterministic。

| 故障组 | 注入点 | 必须观测 |
|---|---|---|
| 缺配置、连接拒绝、HTTP 429/500、timeout | LLM transport/返回 None | 明确 provider error，合法确定性去重/TTL/归并完成 |
| exception、非 JSON、空响应、超大响应 | execute/解析 | fallback 有效；非法输出无事件 |
| 未知 action、extra 权限字段、缺 confidence、NaN/Infinity、越界 | JSON解析/Schema/纯裁决器 | 整包降级或逐项拒绝；不补 confidence |
| fallback 自身异常或返回 `{}` | AgentBase 后的二次校验 | 丢弃 fallback 包，使用受信任空提案+独立确定性规则；仍可 TTL |
| 模型线程超时后迟到、取消/失去 writer | 有界工作器/提交边界 | 后到输出 0 次提交，旧资格 fence 生效 |
| 输入/目标/证据/词表/配额变更 | propose→commit 间 barrier | 再裁决拒绝；不信第一次批准 |
| relational/link/context、Qdrant/file failure | 事务/六投影发布 | 区分 rollback/pending；旧 complete 可读、恢复不重复 |
| cache success/failure、miss/corrupt/version mismatch | record/replay guard | 重放真实网络=0；不完整不能过闸 |

验收覆盖六类新增 E2E、012 八 E2E和全旧集；AOEP 权威边界、scope 不扩张、来源保留、删除传播、可追溯 rollback 每项至少两例。重点加：非空升级/重建、审计 TTL 后重建、历史源正常 purge 不影响结论、必要支持撤销正确传播、软提案间接隐藏 hard 被拒、晋升崩溃恢复和同候选重复请求。

**Rationale**：降级“返回成功响应”不足以证明独立确定性工作完成；轨迹测试应验证实际事件、完整 manifest、源消费和供应商 transport。

**Alternatives considered**：仅 monkeypatch 一个 None 路径遗漏 Schema/fallback/迟到结果；只用 unit mocks 不能证明数据库资格和投影 guards。

## 13. 材料局限与关闭条件

**Decision**：技术台账原文当前缺失，采用用户要求和可核验蓝图；不补造 E-5/Q37/Q38/Q14 决议。本文已给出实施可用的词表种子/传播声明，若原文随后提供，按版本变更复核，不阻塞已授权规划。没有新增服务基础设施，没有宪法豁免，全部技术未知已在本文件作出可验证决策。

规划尚未运行生产回归、真实 provider 受益评测或 target host 验收。默认开关保留关闭，任何硬指标失败是发布阻断，不能用关闭功能豁免。实现必须在 tasks 与 spec/plan 一致性分析完成后开始。

## 14. 评测证明到正式读取的交接

**Decision**：选择部署者控制的本地只读登记文件，Settings可选CONSOLIDATION_GATE_REGISTRY_PATH默认None；runner只产报告，不安装登记或发布policy。一个报告绑定一个scope，报告013.2与登记013.gate.1共享gate_binding。具体路径信任、固定字节hash、当前数据/代码/策略/词表/提示/Schema/模型/召回配置绑定、有效期及加载界限见 [gate-proof.md](contracts/gate-proof.md)。只有candidate_expansion的完整当前三闸报告可授权扩展；direct报告不可替代。

**Rationale**：现有policy只能表达域许可，评测JSON存在本身不是正式许可。独立受信部署登记避免请求、正文、模型或上传数据选取证明，也无需新增管理端点或事实表。backend owns共享纯校验，eval引用它，避免生产依赖eval或两套宽严不一致规则。

数据指纹仅排除guard验证的013内部巩固效果/窗口/传播封存，覆盖普通源authority、治理/rollback/人工晋升和published证据变化；baseline/direct/expansion data_hash一致，snapshot_hash仍完整保存输入。目标enabled policy在评测前冻结，runner路径选择不修改policy，因此报告不会因随后打开同一既定策略或正常产出自失效。每请求重新核验登记/报告hash和当前绑定，不缓存授权；篡改、撤销、过期、版本变化、IO预算不足均退回原直接召回。指纹测试区分013产出/rebuild与普通源/证据变更，时间/端点合法性仍每次过滤。

**Alternatives considered**：从上传目录发现报告或相信报告自报pass缺少信任来源；数据库闸口表/新发布API增加控制面；直接绑定snapshot_hash或投影revision会被巩固自身输出破坏。采用独立源材料data_hash与显式部署登记，质量结论仍仅限冻结子集，所有新输出仍受裁决和读取验证。
