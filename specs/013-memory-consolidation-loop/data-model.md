# Data Model: 013 记忆巩固回路

本文描述待实现模型，不替代012基座。日志为永久事实authority；可变资格与摄入运行是控制状态；链接、语境、候选、消费和晋升指针均从日志派生。决策来源见 [research.md](research.md)。

## 1. 标识与版本

- event/memory/scope/lease/task/ProcessingRun内部为正BigInteger，REST为十进制字符串；consolidation run_id/eligibility_id为UUID v4。
- memory_id与immutable creation source_event_id不变；新增state_event_id列为最近状态/派生authority事件，用于并发复验。rollback恢复旧值后将受影响条目的state_event_id设为该rollback事件，creation身份/原文不改，合法重试因此使用新版本。
- content_hash沿012净化正文哈希；context/link改变不能改正文哈希。
- 策略、词表、提示、Schema、模型各有版本/内容指纹；当前版本用于批准，捕获版本用于重放。标签不能替代实际材料。
- 时间为UTC带时区；window按系统observed_at，不允许模型回填；有效期沿012 valid timeline。

## 2. 域配置

MemoryPolicy保留旧键与strict extra-forbid，新增 `consolidation: ConsolidationPolicy | null=null`、`link_expansion_enabled: StrictBool=false`。已有consolidation_enabled保留false默认；启用必须有配置。所有键/默认/上限见research§2，候选阈值≥提炼阈值；缺配置不自动启用。原TTL治理独立运行，内置档案治理不绕过。

DomainProfile新增 `memory_link_vocabulary` JSONB默认[]，独立于graph_relations，版本沿档案版本+内容指纹。每类型：

| 字段 | 校验 |
|---|---|
| key | 唯一 `^[a-z][a-z0-9_]{0,62}$`，不覆盖evidence/supersedes |
| from_kinds/to_kinds | 非空episodic/semantic/procedural列表 |
| category | live_dependency/historical_lineage/association |
| propagation | live_dependency固定to_to_from，其余none |
| recall_direction | from_to_to/to_to_from/both/none |
| allow_self | 首期false |
| description | 净化受信声明，≤512字符 |

to_to_from表示沿原边to失效影响from；不是从名字猜语义。旧基础边不受空高级词表影响。管理更新仍遵守档案权限。

## 3. 可变资格表 consolidation_eligibilities

| 字段 | 类型/约束 |
|---|---|
| eligibility_id | UUID PK；每次admission/接管新值 |
| knowledge_scope_id | BigInteger FK knowledge_scopes，非空 |
| run_id | UUID，非空，不FK到审计 |
| holder_instance_id/writer_lease_id | holder UUID/lease BigInteger |
| eligibility_version | BigInteger>0，同scope单调generation |
| state | active/released/expired |
| acquired_at/renewed_at/expires_at | 带时区；TTL120秒/心跳20秒 |
| released_at | 可空退出时间 |

索引：UNIQUE(scope) WHERE state='active'；UNIQUE(scope,eligibility_version)；活动expires索引。不能在索引用now()。短scope串行事务分配generation，不清理仍承担fencing高水位的资格历史；未来压缩需保留高水位。

active→released/expired；心跳只延长未过期active，不变generation，不复活旧资格。恢复同run分配新完整token。释放匹配token，旧任务不能释放新资格。提交锁住资格到commit，前后使用clock_timestamp()检查；审计TTL不释放资格。

## 4. 追加式观察表 consolidation_runs

PK=(run_id,observation_seq)。每行是不可改累计观察快照，查询最新seq或完整历史；旧窗口/输入/提案/裁决/状态从不UPDATE。

字段：scope、trigger(idle/manual/volume/support_maintenance)、execution_context(distiller_window/deterministic_propagation)、request_id、actor、status、window、input_event_ids、reference_versions、historical_source_refs、propagation_trigger/proof、净化proposals、adjudications、output_memory_ids、output_event_ids、pending_result_keys、provider_usage、degradation_reasons、policy/vocabulary/model/prompt/schema版本、资格身份、created_at/ttl_expires_at。

合法组合由可信服务与DB约束固定：idle/manual/volume只能对应distiller_window；support_maintenance只能对应deterministic_propagation，window=null、input_event_ids=[]、历史lineage和可复验trigger/proof非空。support_maintenance是内部维护来源，不是第四个外部触发API。维护不调用模型，模型用量明确为实际0，未知供应商字段仍遵守null纪律。

status：admitted→selecting→proposing→adjudicating→committing→succeeded/no_change/degraded/partial/failed/interrupted。no_change含empty_window/all_rejected/approved_no_effect；每裁决还分committed/pending/failed，不以accepted冒充成功。

usage沿006字段，附actual/estimated/unavailable与cache/真实transport统计。未知token/cost=null。索引(scope,run_id,seq DESC)/expires。UPDATE禁止，DELETE仅writer maintenance到期并留RuntimeMaintenanceLog；默认7天，无有效记忆/链接cascade FK。

## 5. 永久窗口与消费

WindowSeal沿现有grant：payload_version=2、grant_type=consolidation_window、独立aggregate_id。保存window_id=event_id、start/end/high-water、所选源版本、原窗口关联、参考版本、冻结clock、策略/词表快照。可信admission控制裁决写入，不改事实、不消费输入、不算提案成功。空窗口仅运行审计。

SourceVersion：memory_id、source_event_id、state_event_id、content_hash、observed_at、original_window_id。Distiller source_refs只能引用所选episodic；reference/target独立。deterministic_propagation历史refs沿§11独立规则，不假称新episode。必要support读集显式复验，不允许任意模型ID。

sealed reducer/manifest增加consolidation_state：window_seals、potential_results、potential_source_outcomes、potential_checkpoint、unresolved_windows。纯reducer只依据日志生成潜在状态，不读取外部发布状态。选择器仅从verified complete manifest覆盖的日志前缀读此状态并确认消费；pending尾部另由服务判断，不注入reducer。不是第七检索投影，随manifest/snapshot派生；full rebuild成功发布后才开放消费。

proposal_key=SHA256(scope+action+source/target版本+批准内容/附件+rule/schema)，排除run/request。共享任何source的批准输出形成同一原子连通组，group_key=规范化全部成员hash。组根(scope,group_key)唯一，成员(scope,group_key,effect_index)唯一；proposal_key用于成员审计。pending保留整组身份不消费；complete manifest且未rollback才确认。rollback不删键，恢复条目有新的state_event_id，因此合法重试产生新group_key。

source_outcomes必须显式：extract/distill消费其完成目的的所选源；merge消费真实关闭或等价覆盖的episode，不消费参考keeper；derive仅context/link/candidate不消费；拒绝/失败/仅提冲突不消费。一个源需要的全部批准输出在一个原子group，outcome指向同group_key，不永久引用尚未追加的另组内容。部分成功只能发生在不共享来源的组之间，整组pending可由永久完整成员恢复，不依赖审计。

至少一个完成结果才推进checkpoint到window.end。未成功/未选来源从长期window与结果反连接恢复，扫描checkpoint以前未消费历史；同原窗口重试。审计过期不影响恢复。

## 6. Proposal/Adjudication

提案见 [Distiller Schema](contracts/distiller-output.schema.json)。四动作，附件不能变第五动作；模型不能赋scope/run/provenance/permission。规则origin/proof由执行器赋，不能信模型justification。

proposal_id批内唯一，target/link允许proposal_ref引用同批extract/distill暂定批准输出。模型不分配永久ID；纯裁决拓扑建立provisional snapshot，拒绝unknown/self/cycle/未批准输出。输出依赖与共享来源形成同group，服务提交分配并复验实际ID/版本。max_events_per_group默认128，超限整组拒绝且不消费，不靠拆组恢复。

纯裁决输入：proposal、immutable current snapshot、policy/vocabulary、quota counters、required support、trusted command context、固定now。输出decision_id、accept/reject、rule_version/reason_codes、affected IDs、expected_versions、approved_effects/source_outcomes、confidence来源/值/阈值、attributions、scope断言、预算占用。reject无effects。

core与每link/context/candidate附件分别裁决；只复制获批effects。所有effects覆盖hard矩阵。函数无DB、网络、模型、系统时间。

## 7. Consolidate v2

无版本/v1 flat consolidate保持创建。v2 operation：

| operation | aggregate_id | 效果 |
|---|---|---|
| create | 新memory ID | semantic/procedural distilled，012正文顶层字段 |
| merge | 被关闭duplicate ID | keeper/来源关系，旧正文与创建事件保留 |
| invalidate | 被失效ID | 经证明退出，有replacement沿单指针纪律 |
| derive | 已有ID | 仅批准link/context/candidate，不改正文/kind/provenance |

永久字段：payload_version/action/proposal_key/group_key/group_id/effect_index/effect_count/created_by_run/execution_context/window_id/propagation/source_refs/target_refs/source_outcomes/各版本与captured policy/vocabulary/adjudication/approved_effect。每event单memory aggregate，同来源多输出组同事务；组完整性由DB/服务复验。create从Agent content转换为012 content_text，填入submission_meta/provenance_validation/injection_flags/tags/decay_rate/created_at/updated_at/session_id/agent_id/task_context/supersedes_memory_id；不把API正文名当持久字段。见 [Event Schema](contracts/consolidate-event.schema.json)。

create confidence=原始获批模型自评；inference_meta.confidence必须相等，origin=llm_self。确定规则记录deterministic_rule及rule/proof，不冒充模型；hard来源confidence=NULL，输出不自动hard。

source_lineage非空，记录memory/create event/hash/历史归因，批准时复验当前源合格；重放不要求历史源永远active。inference_meta.supporting_evidence保留012 memory:ID来源兼容；evidence_refs是corpus anchor且可[]，无anchor无候选。required_support单独描述必要事实/证据与live依赖。

获批具体link/context/candidate材料、六轴永久保存；只有版本/hash不够。净化所有文本，禁止payload覆盖authority。人工晋升pointer使用管理grant，不是第五LLM action。

## 8. TypedMemoryLink

迁移同memory_links表到models/memory_link.py映射，memory_views保持re-export。原row_id/scope/revision/node_key/data保留；增加：

| 列 | 约束 |
|---|---|
| from_id/to_id | 规范ID string；from memory、to按to_kind解释 |
| to_kind | memory/evidence，旧evidence是chunk，不能全加memory FK |
| relation_type | 旧relation或获批高级key |
| provenance | deterministic/llm_proposed；旧基础边deterministic |
| confidence | 有限[0,1]；旧基础边可NULL+规则依据 |
| created_by_run | UUID可空，永久标量，不FK短审计 |
| source_event_id | 永久批准event，旧边从memory来源派生 |
| vocabulary_version/semantic_category/propagation | 高级必填；基础用内建规则 |

UNIQUE(scope,revision,from_id,to_id,relation_type)，每complete revision内三元组唯一，历史revision可同边。typed列与data/authority一致，guards禁止手写。additive→backfill/parity→enforce，不删历史或变旧node_key。

registry保存历史批准；默认图过滤端点status/valid/TTL，扩展再查当前词表。基础evidence/supersedes沿012；live传播用捕获语义。rollback恢复具体registry，审计TTL不删边。

## 9. Context/Entry列

新增context_digest text nullable、keywords JSONB []、context_version、context_source_event_id、promotion_pointer JSONB、candidate_version、candidate_basis JSONB。已有promote_candidate_at继续使用。

Context包含具体摘要/有序去重keywords、源refs、model/prompt/schema、净化/裁决；版本批准event+hash。只有LLM生成获批才新建，无模型保留旧合法值，不以fallback造摘要。summary展示同值；正文hash/dense输入/过滤/改写/RRF不引用context。最终选中后按剩余预算显示，不挤掉已选记忆。

full/snapshot+delta/rollback逐字段和六投影hash一致，测试非空版本与审计过期，模型调用0。

## 10. Candidate/PromotionPointer

candidate_version固化memory creation/candidate approval/content hash/anchor fingerprints。active semantic、高置信、同域published硬锚逐条位置/内容归因，读取时重验promotable。不变provenance。

人工grant promotion_requested的event_id为stable task_id，记录scope/memory/candidate_version/request/actor/reason/source_id/initial_processing_run_id/content hash。raw Markdown先按安全稳定路径写；共享上传服务同事务创建uploaded source、pending ProcessingRun和pointer authority投影。永久requested事件对(scope,memory,candidate_version)唯一。

grant promotion_observed追加source/version/result/attempt引用，旧pointer不改。task是一个稳定人工请求，ProcessingRun是执行attempt；重复POST返回原task，不新建source/task/attempt；显式失败重试可增加关联attempt，不新增stable task/source。

状态accepted/uploaded/processing/failed/published从实际source/run/version及永久pointer派生，publication确认前version可空，不能报published。后台只恢复已有人工授权任务；调度前重验scope/候选，不为候选发新请求。rollback保留已执行外部动作历史，不声称撤销出版。

## 11. 依赖失效

dependent→support的live边逆向传播；required fact/evidence被否定/撤销触发support复验。执行上下文deterministic_propagation可无新episode，历史source_refs和nonempty source_lineage复原原批准来源，window_id=null；只能action=invalidate_contradiction/operation=invalidate，无create/merge/link/context/candidate/消费权限。只有可信writer维护/治理支持钩子可构造，普通开关关闭/配置缺失时仍可取得同一scope资格；完整live lease/token fence、纯裁决及权威事件/投影发布仍适用。不能由REST/MCP/正文/模型伪造成Distiller或维护来源。

propagation永久结构：trigger(kind,event_id可空,evidence_id可空,version,observed_at,proof)、visited_memory_ids、depth、frontier_memory_ids、continuation_key、vocabulary_version。至少一个可复验trigger event或evidence证明。超32层/128节点frontier由事件保存；无效应时以grant consolidation_propagation保存继续材料，不写空consolidate。snapshot/rollback重放此registry。开关false仍执行已有安全过滤/必要支持失效维护，但不做新提炼/派生。association/history自然retention不传播；自动hard变化拒绝并报告管理。

## 12. 迁移与事务

在当前0094后新增迁移：运行表/append-only guards、域词表/策略、typed link回填/索引、语境列、v2 SQL/Python/immutable/publication parity。部署后先验证populated012升级和旧flat/base边/旧客户端。实施时复核head，不编辑旧迁移。

每批准组scope短事务：完整fence→最新数据→重裁决→append→relation/link/context→六inspect→receipt→complete manifest。关系错误rollback，外部错误pending/旧complete可读，源不提前消费。存在v2事件时拒绝丢数据downgrade；回滚部署需兼容代码或管理事件，不删日志。

## 13. GateBinding/GateProof（只读控制证据）

不新增DB表/事实投影。Settings可选登记路径默认None；部署文件结构及生命周期见 [gate-proof.md](contracts/gate-proof.md) 与 [gate-registry.schema.json](contracts/gate-registry.schema.json)。报告013.2的gate_binding与登记共用定义：scope_id、data_hash、policy_hash、vocabulary_hash、prompt_hash、schema_hash、model_version、implementation_hash、recall_config_hash。passed必须完整，incomplete可null；语义validator复验环境/全部query/登记/current绑定一致。

data_hash材料含同域普通authority与published证据，排除可信guard确认的013内部效果和窗口/传播封存、全部投影/run/资格/审计，不等于snapshot_hash或六投影指纹。完整目标enabled policy先冻结，隔离三path开关不改其身份。GateProof是不带写句柄的不可变加载结果，含available/reason/scope/report_sha256/variant/binding/expires_at；不缓存授权，登记删除/内容变化/当前版本或数据变化/过期下一读取即不可用。报告与登记均不能修改记忆、域策略或人工晋升状态。
