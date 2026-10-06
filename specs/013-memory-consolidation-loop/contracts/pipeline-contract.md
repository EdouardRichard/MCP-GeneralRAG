# Pipeline Contract v1

## 1. 四段接口

| 阶段 | 输入 → 输出 | 副作用/权限 |
|---|---|---|
| select_window | resolved scope、policy、固定clock、eligible token → WindowSnapshot | 读complete authority，可信服务封存window grant；不消费源 |
| propose | WindowSnapshot+只读Distiller → ProposalBatch/AgentResult | 有界LLM或确定fallback；无DB/服务写能力 |
| adjudicate | proposal+CurrentSnapshot+Policy+Vocabulary+Quota+TrustedContext+now → Decision | 纯函数，无IO/隐式clock；reject无effect |
| commit_approved | 决定+资格token → CommitOutcome | scope短事务重新取快照/调用同一裁决，append/materialize/verify/publish |

WindowSnapshot包含half-open start/end、frozen_at、event high-water、input_episode_refs、独立reference_refs、明确support读集、正文数据、版本/预算、window_id。Distiller source_refs必须所选episode子集；targets从参考/输入合法集合取。local=output仅extract/distill附件可用，可信服务分配ID。另有独立deterministic_propagation上下文：无新episode也可处理必要支持失效，取原永久lineage、可复验trigger与frontier，只批准invalidate，window_id=null，不调用Distiller。二者权限不可混用。

每建议有批内唯一proposal_id（推荐p0/p1等，非永久ID）。target/link可用 `{"proposal_ref":"p0"}` 指向同批extract/distill的暂定批准输出；source_refs仍仅episodic。拓扑排序先裁决创建，再在pure provisional snapshot复验后续引用；unknown/self/cycle/拒绝输出引用拒绝，不凭标签当批准。指向同批输出的建议与被指输出必须同原子group；提交服务分配实际memory/event IDs、重裁决整个group并写永久resolved refs，不把local标签当永久溯源。

CurrentSnapshot提供来源/目标创建和状态版本、hard归因、supersede链、quota计数、同域词表和当前required_support。无法取得完整manifest/源链时显式失败，不用未验证投影替代。

Decision具有每core/link/context/candidate的子决定，accept/reject、reason codes、批准effects/affected IDs/expected versions/source outcomes/规则版本/证明。模型confidence保留原值，有限[0,1]且≥min_confidence；LLM link confidence也用min_confidence。确定规则confidence=1.0且有代码rule proof；语义近似不当确定性等价。代码赋origin=llm_self/deterministic_rule，不信模型额外声明。

## 2. 降级与确定性工作

先构建可证明的规则提案/TTL intents，再执行可选模型；normal和故障都保留同一确定性工作。模型无配置/None/timeout/exception/Schema失败要可观测degraded，不能返回schema-valid的静默fallback冒充模型成功。AgentBase返回后校验最终包；fallback仍非法则用受信空包 `{ "proposals": [] }`，记录双重故障，继续独立规则。

规则merge/invalidate也符合适用四动作Schema；TTL沿既有治理的生命周期intent，不是第五模型action。TTL前后使用同一pure状态约束/硬保护；既有政策已授权的自然TTL不等于软提案缩短hard有效期。关闭巩固/模型失败不会关闭006/012 TTL。

高风险生成内容拒绝/隔离，无批准事件。只Schema失败不允许保留合法-looking片段，整模型包降级；Schema通过后可逐core/附件拒绝。deterministic rule ID/证明来自执行上下文，不在模型可写Schema。

## 3. Admission/Fencing

普通三触发共用admit(scope,trigger,management context)，execution_context=distiller_window。检查resolved active scope、current writer lease、主开关/配置、worker容量；活动部分唯一索引决定scope至多一资格。存在活动run返回CONSOLIDATION_BUSY+run_id，不排队/合并。新run先审计admitted，后台select后报告窗口；202时window可null，不能在HTTP里等待模型或完整选取。

唯一开关/普通配置例外为可信writer维护/治理支持钩子构造的trigger=support_maintenance、execution_context=deterministic_propagation。它调用同一资格服务，验证scope/current writer/当前支持失效proof/容量，共用busy、恢复、完整token和lease fence；window=null、input_event_ids=[]，历史lineage另记。不调用Distiller，不允许create/merge/link/context/candidate或源消费，仅批准invalidate_contradiction/v2 invalidate；无效果的frontier仅可保存既定control grant。REST/MCP/模型/正文不能构造此context。普通commit重验当前开关/配置；维护commit重验可信来源、当前支持proof和效果白名单，并调用同一纯裁决器，不能以维护名义放宽硬保护或事件/投影发布纪律。

资格token=(eligibility_id,scope,run_id,holder,writer_lease_id,eligibility_version)。TTL120秒，心跳20秒，不复活到期token；新admission/接管新ID+单调version。全局worker=2；运行/模型预算见research§2。恢复同run仍必须独占资格。

scope lock→eligibility row→writer lease shared row→policy/targets/evidence固定顺序。LLM不持锁；commit事务≤30秒，DB clock_timestamp()在锁后及最终发布前复验期限，锁持到commit。发布后终态audit→匹配token释放。到期审计DELETE不能release，旧holder不能release新资格。

维护tick先旧TTL/recovery/purge，再idle检查（无前台活动、无活动摄入/重建，至少idle_seconds）。volume阈值只是离线提示，真实pending数维护重验。自动idle与volume同需idle；手动不需idle但仍有资源上限。提示不排队、不保留一次busy触发等待将来执行。

## 4. 权威events与事务边界

v2 consolidate operation=create/merge/invalidate/derive。create保留012正文顶层字段；其他不创建身份。一个事件一个aggregate，多effects同批准group；批准附件具体值永久记录，拒绝附件不写。raw/apply_event仍拒绝外部直写。

共享任一来源的全部批准输出形成一个原子group，root持group_key唯一，成员effect_index连续[0,effect_count)，proposal_key供每提案审计。group包含全部永久批准内容，整体提交/整体pending；不引用审计中尚未追加的另一个必需结果。只有不共享来源的组才可部分成功。approved不等于committed，CommitOutcome区分completed/pending/rejected/rolled_back/failure，不能失败报成功。

group连通性同时包含批内output引用。max_events_per_group默认128、合法1–128，落库前预计算所有create/lifecycle/derive事件；超限整组拒绝GROUP_BUDGET_EXCEEDED，审计且全部相关输入保持未消费。不得拆共享源/输出依赖组规避预算；不共享的其他组可继续。

scope关系/links/context同事务；external failure沿012retain failure，旧complete可读，新pending不可读。纯reducer只算potential消费/checkpoint，不读取manifest；选择器从verified complete manifest日志前缀读同一pure registry。服务以成员是否被发布前缀覆盖判断pending/completed，避免循环publication authority。恢复取得资格/重验；变更后不满足提交约束则保持pending并报告需治理，不强行重批准旧内容。完整rebuild成功发布才开放其潜在消费。

控制grant类型：

| grant_type | 必填材料 | 改变事实/消费？ |
|---|---|---|
| consolidation_window | start/end/high-water、selected refs、original windows、reference versions、policy/vocab snapshots、token记录 | 否；只封存原窗口 |
| consolidation_propagation | 可复验trigger、历史lineage、visited/depth/frontier/continuation_key、捕获语义 | 否；只封存失效维护继续位置 |
| promotion_requested | memory/candidate/version、stable task=event_id、source/pending ProcessingRun、actor/reason/request/content hash | 不改原正文/信任；显式人工创建上传任务 |
| promotion_observed | stable task/request event、source/version/attempt/result及实际发布依据 | 只追加指针状态 |

grant也受可信管理服务/来源guards；control不是成功提案。rollback恢复registries/候选/潜在消费，并给受影响条目state_event_id盖rollback事件，保留creation身份，允许新版本合法重试。人工外部动作历史保持可追踪，不假装撤销出版。

## 5. 来源、纠正与依赖

新distilled的source_lineage非空，所有episode/event/hash可回查永久authority。inference_meta沿五元，supporting_evidence是memory:ID历史引用；evidence_refs独立是corpus锚且可[]。来源active/complete/scope/TTL在批准时复验；重建历史不要求来源永远active。空corpus不伪造证据/无候选。

被新结论用作事实锚的每条corpus evidence由裁决器生成required_support，并检查持续published/同域/归因；模型不能清空必要支持来规避传播。普通episode来源默认historical，明确要求持续有效的事实条件/依赖另作live声明。

单supersedes_memory_id不可变且无环≤32深。merge一个keeper+多个关闭输入，merge provenance不变成keeper多父纠正。hard source confidence=NULL，distilled confidence不聚合源置信度。soft/new inferred hard锚不能授权hard替代；合法hard替代和人工处置沿原可信管理路径。

必要support与历史lineage分开：依赖传播按captured语义/required support，普通retention不自动否定结论；读取时必要support不完整先过滤。预算32层/128节点，visited稳定去重，frontier永久可恢复，所有状态效应仍裁决+event。associations从不赋状态权限。

## 6. 只读投影/关联读取

typed links迁移同revision表，UNIQUE(scope,revision,from,to,relation)。evidence/supersedes不受高级词表缺省影响；advanced必须当前域key/category/direction复验，两端active complete valid same-scope；deterministic需proof，LLM始终llm_proposed。永久created_by_run不FK审计。

context仅LLM批准文本/keywords，原body/hash/kind/provenance/证据不变。fields不进embedding/query/candidate/filter/ranking/RRF；只在最终selected结果按剩余预算展示。默认旧响应不加字段，管理报告可显示。rebuild/rollback复制具体批准值，LLM调用0。

正式扩展要求客户端include_linked=true、consolidation_enabled/config/link_expansion_enabled和当前版本三闸证据；证据按 [gate-proof.md](gate-proof.md) 从受信部署指定的只读登记文件加载，只有匹配scope/绑定/有效期的candidate_expansion报告可授权。词表/域policy不是客户端opt-in。context显示需include_context=true，旧响应不添字段，见 [recall-extensions.md](recall-extensions.md)。隔离评测显式candidate扩展不改正式域。失效端点过滤，证明失效或增强失败退回原直接合法候选，不增加原预算/超时。

## 7. 稳定拒绝原因

新增REST原因与旧MCP registry分开，不改旧错误枚举。纯裁决至少覆盖：CONFIDENCE_INVALID/BELOW_THRESHOLD、SOURCE_NOT_ELIGIBLE、SOURCE_CHAIN_INCOMPLETE、TARGET_VERSION_CHANGED、EVIDENCE_UNAVAILABLE/ATTRIBUTION_FAILED、SCOPE_MISMATCH、SUPERSEDE_CHAIN_INVALID、QUOTA_EXCEEDED、HARD_MEMORY_PROTECTED、EQUIVALENCE_NOT_PROVEN、CONTRADICTION_NOT_PROVEN、LINK_TYPE_NOT_ALLOWED/LINK_DIRECTION_INVALID、DEPENDENCY_SUPPORT_INVALID、GENERATED_CONTENT_UNSAFE、CONTEXT_BUDGET_EXCEEDED、ELIGIBILITY_LOST/POLICY_CHANGED。

schema-invalid整体与纯裁决reject不同；无法确定矛盾就保留未解状态。审计记录规则/依据但不泄露另一scope正文或原凭据。
