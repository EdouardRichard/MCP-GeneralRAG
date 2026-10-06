# Read-Only Gate Proof Contract v1

本契约定义评测报告到正式关联召回的控制证据交接；不是记忆事实源，不授予写权限，也不自动启用域策略。对应 FR-021/032/035。

## 1. 部署登记与信任边界

`backend/src/rag_mcp/config/__init__.py` 的 Settings 新增可选 `consolidation_gate_registry_path`，环境变量 `CONSOLIDATION_GATE_REGISTRY_PATH`；默认 None。设置时须为部署者配置的本地绝对路径。不得从 REST/MCP、DomainProfile 自由字段、记忆/模型内容或上传目录推导路径；没有配置即无证明，默认关闭。

登记文件与报告位于仅部署者可修改的独立目录，writer/reader进程均只读；不得与DATA_ROOT或其子目录重叠。生成报告的runner没有安装登记文件或修改policy的能力。部署者审阅实际record/replay与三闸证据后，复制不可变报告，再以同目录临时文件原子替换登记文件；撤销即删除对应entry或登记文件。由部署者显式配置，不新增管理端点、数据库表或自动发布任务。

登记结构见 [gate-registry.schema.json](gate-registry.schema.json)：版本013.gate.1，entries每scope最多一项，每项含gate_binding、report_path、report_sha256、expires_at。report_path为登记目录下受限相对JSON路径，拒绝绝对路径、URL、`..`、盘符、symlink/junction/reparse逃逸；对实际打开文件的解析路径复验。SHA256固定精确文件字节，不能仅依靠mtime或报告自报hash。校验只用本地打包Schema，不加载报告中的远程引用或evidence_paths内容。

## 2. 统一绑定

报告013.2新增 `gate_binding`；passed/default_enable_eligible报告必须非null，failed/incomplete允许null。一个可授权报告仅覆盖一个scope，全部query.scope_id须等于binding.scope_id；多域分别出报告和登记。报告与登记共用benefit-report Schema的gateBinding定义，逐字段精确匹配当前可信backend计算值：

| 字段 | 当前值来源与变更失效条件 |
|---|---|
| scope_id | 已解析请求scope的十进制字符串，无隐式回退 |
| data_hash | §3当前源authority和已发布证据元数据的规范化指纹 |
| policy_hash | 完整、已校验的目标MemoryPolicy，含两个enabled开关及显式consolidation配置 |
| vocabulary_hash | 当前域独立记忆词表内容、语义与版本 |
| prompt_hash | 受信Distiller ROLE/system模板、域声明及版本；不含运行输入正文 |
| schema_hash | 打包proposal/event/report/registry四Schema的文件名及精确内容指纹 |
| model_version | 供应商限定的模型不可变版本及路由身份；仅可变alias且无法确认版本时证明不可用，确定性无模型模式使用明确身份 |
| implementation_hash | 可信构建清单的代码内容指纹，涵盖Distiller/裁决/管线/reader/reducer/validators/投影、适用SQL规则与gate模块；启动时核验实际包，不逐请求运行Git |
| recall_config_hash | 有效embedding/rerank身份、ranking/遍历配置、固定数量/内容/超时预算；排除凭据、query/run/request ID与客户端增强flags |

policy/vocabulary/prompt/schema/model字段还须与报告environment对应字段一致。评测前冻结拟部署的完整enabled目标policy；baseline/direct/候选扩展的开关差异由隔离runner控制，不改该policy身份。首轮/次轮绑定一致；随后任何实际policy变更都令旧证明失效。现有commit字段继续记录报告构建Git版本；implementation_hash提供实际代码内容身份，不能仅相信版本标签。

目标policy须已通过既有合法管理流程发布并包含在导出的authority快照中，不能只改DomainProfile投影或在报告中声明未来值；未有证明时扩展仍不可用。安装证明之后若再发布policy grant，普通源authority与policy绑定均重新核验，必要时基于新快照重评；不得重写旧报告binding来迁就部署值。

绑定只从受信配置、已校验域策略与verified complete authority获取，不能使用模型声称的版本或未验证投影。读取当前绑定失败即不可授权。缓存绑定计算只能依赖真实authority/域版本/已发布证据版本的变更标识；没有可信变更标识时重算或降级，不能把projection revision当源版本。

## 3. 数据指纹与快照的区别

environment.snapshot_hash继续标识可完整复原的冻结评测输入，projection_fingerprints继续用于输出重建核验；二者不直接用作生产当前data_hash。data_hash的版本1材料为 `{binding_version:1,scope_id,source_events,published_evidence}`：

- source_events取verified complete日志前缀中同域普通权威事件，按event_id排序，保留原事件身份、类型、observed_at及规范化payload。包含旧v1 consolidate、普通record/revise/governance/rollback/purge、人工promotion grants；普通处置即便针对013产出也必须纳入。
- 仅排除已通过可信来源/Schema/authority guards确认的013 v2 consolidate效果与grant_type=consolidation_window/consolidation_propagation控制封存。不得根据用户payload自贴标签、任意action名或目标kind排除事件；run/audit/资格、派生投影与登记文件从不参与数据材料。
- published_evidence取当前同域知识源/版本/chunk的稳定身份、内容hash、scope、发布/撤销状态、位置和可用能力/版本元数据，按规范身份排序；摄入发布/撤回/证据内容或能力变化均使旧证明失效，未发布处理中运行状态不参与。

规范化沿012 authority export的JSON值规则：ID为十进制字符串、UTC时间固定格式、禁止非有限数、固定对象键排序与集合排序、有语义顺序的数组保序；以UTF-8标准JSON编码（ensure_ascii=true、sort_keys=true、separators=(',', ':')、allow_nan=false）取SHA256。评测和backend调用同一纯材料编码/校验函数。测试须证明baseline/direct/expansion与缓存两轮data_hash一致，013产出或重建不自使证明失效，而普通源/治理/rollback/promotion或已发布证据变化会失效。

此证明的质量结论仍限于冻结结构子集及其源authority/算法身份；新增013产出的安全、合法性与端点支持仍逐项裁决及读取复验。排除013效果不代表报告为所有输出质量作保证，也不能代替六投影完整性验证。

## 4. 生产加载接口与生命周期

`services/consolidation_gate.py` 拥有纯 `validate_report`、`validate_gate_binding`、数据材料指纹函数，以及只读 `load_gate_proof(scope_id,current_binding,now,remaining_budget)`。返回不可变GateProof（available、reason_code、scope、report_sha256、gate_variant、binding、expires_at），不持writer/session/上传句柄；backend不导入eval。eval/consolidation_eval_support.py复用其纯校验/编码，不能自建一套较宽规则。

加载先检查部署路径和登记Schema/唯一scope，选同域entry，验证有效期、路径和精确报告SHA256，再验证013.2报告Schema及完整语义（指标重算、六查询覆盖、三闸checks、缓存/安全/回归证据完整性），最后校验entry/report/current三份binding一致。status=passed、default_enable_eligible=true、quality/safety/regression全passed且gate_variant=consolidated_candidate_expansion才可授权链接扩展；direct报告不能授权未评测的扩展。

每次显式include_linked请求重验当前绑定、有效期和登记/报告内容hash；仅缓存按字节hash键控的解析/纯校验结果，不缓存授权结果。文件缺失、撤销、替换或相同mtime篡改下一次读取即不可授权，不保留最后成功许可。实际读取/解析同一份已校验字节；原子替换可使用读取时的完整版本，随后的请求读取新版本。运行审计TTL不会删除部署证明，expires_at由部署者显式选择，过期时间以可信UTC now判定且必须晚于report.generated_at。

资源上限：登记≤256KiB、≤128 entries、单报告≤8MiB，拒绝重复JSON键/非有限数/超量嵌套；固定IO执行器最多2个实际在途读取。磁盘/hash/解析不阻塞事件循环，新增等待≤min(100ms,remaining_budget)，完全计入原3秒超时；超时/IO容量忙立即退回直接结果，底层读取结束才释放槽，迟到证明不可应用。旧flags=false路径不加载文件或添加字段；无模型/网络/动态Schema下载。

原因代码至少覆盖GATE_NOT_CONFIGURED、GATE_MISSING、GATE_INVALID、GATE_HASH_MISMATCH、GATE_SCOPE_MISMATCH、GATE_BINDING_STALE、GATE_EXPIRED、GATE_VARIANT_NOT_AUTHORIZED、GATE_IO_BUDGET_EXCEEDED。均映射enhancement.link_expansion_status=not_available并给确定性degradation_reasons；policy或客户端未许可仍为disabled，证明合法时才进入原受预算的逐端点扩展。原直接结果同样遵守scope/状态/必要支持过滤。

## 5. 实施与验证责任

T002负责四Schema结构与引用；T055先写部署路径/绑定/变更/撤销/过期/哈希/错variant/坏JSON/IO预算与只读测试，使用显式fixture覆盖正向加载但不把fixture当真实闸口证据；T061交付配置、共享backend模块与reader加载；T090/T098将报告绑定、环境一致性与语义校验接入runner；T103仅在真实candidate_expansion报告passed且当前绑定匹配时，在隔离验收目录演示人工登记后增强、篡改/变更即失效。若真实报告failed/incomplete或只有direct通过，T103验证不授权、直接召回及默认关闭，保留实际结论，不伪造正向证据。T104记录部署及撤销操作。仅Schema或fixture通过不能宣称真实三闸通过。
