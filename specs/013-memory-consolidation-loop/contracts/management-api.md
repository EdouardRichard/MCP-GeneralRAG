# Writer Management API v1

基路径 `/api/memories`，新增操作仅管理REST，不注册MCP工具。新写API复用require_writer并核验live writer lease；后台每次提交独立复验。新报告/候选接口属于writer管理应用，reader不暴露这些控制接口。显式scope不能默认/回退；旧管理请求/错误形状保持。

## POST /consolidation

请求：`{"scope_id": 123, "reason": "manual review"}`。沿现有ScopeCommand接收内部正整数scope_id，拒绝bool/未知键；reason非空≤4000字符。trigger只由服务设manual，execution_context固定distiller_window；客户端不能传idle/volume/support_maintenance、execution_context/propagation/proof、run/holder/权限/策略或提案。

202：schema_version、run_id UUID、scope_id十进制字符串、request_id、trigger=manual、execution_context=distiller_window、status=admitted、window=null、report_url。短admission事务先建立资格与审计，后台选择后window更新于追加报告；无需在HTTP等待选择或模型。run受理不代表产出成功。

| HTTP | detail.code | 意义 |
|---|---|---|
| 400/422 | 现有scope/请求校验码 | 缺失/无效/歧义scope；无隐式扩域 |
| 403 | CONSOLIDATION_DISABLED | 当前域主开关false，未调用模型/写巩固事实 |
| 409 | CONSOLIDATION_CONFIG_REQUIRED | 主开关有值但配置不完整；不得自动猜配置 |
| 409 | CONSOLIDATION_BUSY | 已活动资格；detail.run_id为现存UUID |
| 409 | CONSOLIDATION_SCOPE_WRITE_BUSY | admission短事务竞争，未排队 |
| 429 | CONSOLIDATION_CAPACITY_EXCEEDED | worker/预算满；无待执行运行队列 |
| 503 | MEMORY_WRITE_UNAVAILABLE | reader/无active writer lease；沿旧码 |

idle/volume自动触发调用同admission，以运行/维护审计记录disabled/idle不足/busy/capacity等跳过或拒绝；不得伪造HTTP受理记录。可信writer支持失效维护仅由内部钩子构造support_maintenance/deterministic_propagation，开关关闭仍执行窄权限invalidate；与普通运行共用资格/fence，无对应外部触发端点。

## GET /consolidation/runs

参数：scope_ref必填，经MemoryScopeResolver；limit默认20(1–100)、offset≥0。响应schema_version、scope_id、items、total；items是每run最新累计观察，按created_at/run_id稳定降序。不得把历史seq重复计为多个run。

## GET /consolidation/runs/{run_id}

scope_ref必填；include_history默认false。跨scope/不存在返回404 CONSOLIDATION_RUN_NOT_FOUND，不返回其他scope元数据。已TTL清理可返回410 CONSOLIDATION_RUN_EXPIRED，前提存在同域长期run身份证明，否则404；不依赖审计保留永久结果。

运行报告字段：

| 字段 | 语义 |
|---|---|
| schema_version/run_id/scope_id/request_id/trigger/execution_context | 身份、普通触发或内部support_maintenance来源；不伪称人工请求 |
| status/observation_seq/window | 最新状态、冻结窗口/边界/原窗口关联 |
| input_event_ids/reference_versions | 实际episode源与独立参考；ID对外字符串 |
| historical_source_refs/propagation_trigger/proof | 支持维护的永久来源与当前失效依据；维护window=null、input_event_ids=[] |
| proposals/adjudications | 净化后的模型/规则建议与逐core/附件理由 |
| counts | proposed/accepted/rejected/committed/pending/failed/unprocessed，accepted≠committed |
| output_memory_ids/output_event_ids | 仅完整发布产出；pending另列 |
| provider_usage/cache/degradation_reasons | actual/estimated/unavailable、真实调用与缓存命中分开 |
| versions/eligibility_history | 政策/词表/模型/规则版本及取得/释放/接管轨迹 |
| created_at/ttl_expires_at | 默认7天，清理不丢authority/projection |
| history | include_history=true时追加观察按seq，旧记录不可变 |

终态succeeded/no_change/degraded/partial/failed/interrupted。全驳回no_change+all_rejected；空窗口no_change+empty_window；失去资格interrupted；部分完成须列具体成功/未完成。仍运行但资格过期要显示stale/interrupted证明，不能误报成功。

## GET /promotion-candidates

scope_ref必填；limit默认50(1–100)、offset≥0。返回scope_id/items/total；每项memory_id、kind、provenance、confidence、promote_candidate_at、candidate_version、evidence_attributions（source/version/position）、promotable、ineligibility_reasons、现有promotion_pointer。

候选从权威批准派生，读取再查active/semantic/threshold/同域published硬锚归因。保留已标记但现在不可晋升的项目用于审计，不称它们仍可晋升。不泄露原凭据或另一域正文。

## POST /promote

请求：`{"scope_id":123,"memory_id":456,"candidate_version":"<64 hex>","reason":"approved by operator"}`。scope/memory正整数，reason1–4000；候选版本必填，拒绝未知键，不能指定任意正文/source/task/status/hard权限。

接受202：schema_version、scope_id、memory_id（字符串）、candidate_version、task_id（pointer grant event_id字符串）、source_id、initial_processing_run_id、status=uploaded/accepted、version_id=null、request_id、reused=false。源内容来自净化候选与完整来源包；人工动作重验当前scope/候选/anchors，创建稳定raw source、pending ProcessingRun和永久pointer；走原摄入与发布。

重复同候选版本返回200+reused=true，原task/source/initial run及当前实际状态，不另调度一次新attempt。任务未完成不报published。candidate_version变了返回409 MEMORY_CANDIDATE_VERSION_CHANGED；失效/无锚返回409 MEMORY_CANDIDATE_NOT_ELIGIBLE；无writer沿503。并发重复唯一冲突后读取原同域任务。

首次事务失败没有任务时返回503 MEMORY_PROMOTION_UNAVAILABLE，不伪造accepted。raw残留按原清理纪律；如果pointer/source已commit而调度失败，返回已持久任务并status=uploaded，maintenance恢复同任务。调度前重验候选；失效则记录失败且不发摄入。失败重试沿既有知识源reprocess；稳定task/source不增加，ProcessingRun attempts可增且指针追加其身份。

## GET /promotions/{task_id}

scope_ref必填。返回稳定task_id/memory_id/candidate_version/source_id、initial_processing_run_id、attempt_run_ids、status、published_version_id或null、result/reason、authority_event_ids。跨scope返回404 MEMORY_PROMOTION_NOT_FOUND；status仅来源实际状态和版本发布证明。原记忆保留。外部知识出版后记忆rollback不会宣称已撤销知识。

## Policy/词表配置与兼容

现有POST /policy继续管理MemoryPolicy，新增字段见research§2；配置null时不能enabled=true。域词表通过现有DomainProfile管理边界版本化，不在任一巩固请求正文设置。built-in限制保持。通过三闸只是default_enable_eligible，不自动改内置/管理员选择。

原MCP schema/错误枚举保持；新增错误属管理REST，错误detail仍为object(code/message/request_id可选)，新字段不注入旧Tool响应。报告/候选包含inference说明，不能把distilled或llm_proposed展示成published hard事实。
