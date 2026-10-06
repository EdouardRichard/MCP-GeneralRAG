# Consolidation Evaluation Contract v1

## Frozen dataset

实施时创建eval/consolidation_eval_dataset.json并在调用模型前封存：dataset_version、snapshot_hash/authority cutoff、frozen_clock、scope/DomainProfile/policy/vocabulary、model/prompt/schema、recall配置、预算、K=5、六查询与相关性。至少6个不同query ID，每条一个主类别，2 extraction(semantic/procedural各1)、2 correction、2 merge；依赖/关联叠加。任何变更产生新dataset版本，保留旧失败报告。

一个可授权报告仅覆盖一个scope，六query均属该scope，多域分别冻结和出报告。冻结拟部署的完整enabled目标policy，三path开关仅由隔离runner控制。报告013.2的gate_binding采用 [gate-proof.md](gate-proof.md) 的共享backend规范，含独立data_hash及代码/召回配置绑定；snapshot_hash仍保存完整输入，不用输出投影/运行身份当当前数据版本。eval复用services/consolidation_gate.py纯校验/材料编码，backend不反向导入eval。

首期查询主题使用009通用测试域的实际可定位材料，以下是不可互相替代的覆盖槽；实施在冻结快照中为每槽绑定正文、非空expected content/位置/事件/域和相关性等价组。不能仅写六条无语料问题就通过。

| query_id | 主类 | 提问主题/必要变化 | 叠加 |
|---|---|---|---|
| extract_fact_01 | extraction/semantic | 完成导出保留规则：合法episodes提炼稳定事实 | candidate硬锚条件 |
| distill_procedure_01 | extraction/procedural | 重复账单处理步骤：合法soft经历，无corpus锚 | 无候选/完整历史链 |
| correct_01 | correction | 当前审核时限：旧soft支持撤销，新正确来源可复验 | required-support传播 |
| correct_02 | correction | 当前批准交付渠道：单指针纠正/保留历史 | 依赖撤销/回滚 |
| merge_01 | merge | 供应商续期要求：等价重复占据top5 | 哈希与元数据相容 |
| merge_02 | merge | 对账流程：同域既有procedural参考集去重 | 合法association/扩展 |

coverage slot的具体值须与真实目标域一致，不能强行套用通用示例；域差异声明在数据集，不写进生产提示。固定后不删失败query、不重复计主类别。数据集validator检查distinct IDs、2+2+2、提炼kind、非空相关性和源可定位。

## Relevance and metrics

相关性单元=fact/procedure/evidence等价组，显式expected content约束+合法源链+当前可消费状态三者同时匹配。不能只凭来源引用就把错误推断判相关。新memory ID与keeper通过authority lineage映射冻结单元；保留原物理rank，重复alias只首次给gain，其后0。过期/隔离/错误事实为0，不让“同词”掩盖纠正价值。

沿eval/run_eval.py的MRR/nDCG函数，gain严格二元{0,1}，不引入graded relevance；保留物理rank，重复alias后续gain=0，IDCG按冻结相关单元/K。一query一权重宏平均。HitRate=至少一项relevant，Recall@5=不同relevant单位/总单位，Precision@5=首次正确相关位置/5、缺位0。报baseline/direct/candidate_expansion三path和逐query差异，不隐藏direct回退；gate_variant运行前冻结。

质量门槛：MRR和nDCG各相对≥0.03，HitRate/Recall/Precision均after≥before。relative=(after-before)/before；baseline=0标not_computable/incomplete，不用epsilon/infinity。六查询只支持该固定子集，不能声称整体统计显著。模型成功响应与失败响应都进入缓存/报告，零失败不是筛选条件。

## Cache/record/replay

环境变量沿005 `AGENTIC_LLM_CACHE_PATH`。键算法保持(model,system,user_text)，user_text使用固定键序/排序来源/冻结clock/版本，不含变化的run/request ID。生成cache-manifest包含准确expected keys、success/failure、entry/body hash、版本清单和authority/data指纹。缓存正文同样脱敏，无凭据。

record从原始snapshot副本执行完整comparison并缓存；replay再从相同未巩固snapshot新副本开始，不能从已巩固库假装重放。eval-only guard仅阻断LLMClient/LLM供应商transport，LLM真实网络0；数据库/Qdrant与既有embedding/rerank访问仍按原配置运行并另记用量。missing/corrupt/version mismatch记不完整/确定性降级，不能过质量闸。禁止gap-fill/修改manifest/悄悄LLM回源，不使用LLMClient.calls代替真实LLM transport计数。

必须覆盖独立success与failure fixture缓存重放；主要受益批次成功/失败结果按真实记录。response match=1，replay真实调用0；非延迟指标漂移≤1%，零baseline完全相同；硬指标无容差。cache hit只计重放请求，额外供应商usage为replay_zero，首轮未报告token/cost=null+unavailable。成本估计要explicit estimated，不能套默认零价格当免费。

## Runner interface (待实现)

从repo root，支持：

```text
python eval/run_consolidation_comparison.py
  --dataset <frozen-json> --snapshot <authority-snapshot>
  --mode record|replay --cache-manifest <manifest-json>
  --gate-variant consolidated_direct|consolidated_candidate_expansion
  --suite <pytest-xml> --trace <013-trace-json>
  --memory-acceptance <012-report> --regression <report...>
  --output <unique-report-json>
```

`--snapshot`必须是隔离环境的可重建authority export，不接收正式库清空指令。record的manifest已存在就拒绝覆盖；replay要求已存在有效manifest。output已存在拒绝覆盖。所有输入/路径/版本先校验，报告仍记录incomplete，不能把环境不可运行当安全通过。

013集成证据fixture读取 `CONSOLIDATION_EVIDENCE_DIR`，输出consolidation-trace.json、authority-snapshot.json与冻结dataset manifest。trace保存真实测试nodeid、scenario、source/event/manifest/资格身份、各硬检查计数及实际transport；snapshot包含完整authority、DomainProfile/政策、published证据元数据、固定时钟和可复原索引源，不只是projection count。导出必须脱敏/同域，并拒绝覆盖已有不同内容。复用既有memory_pytest_evidence输出旧012 trace，不改其原验收口径。

退出码0=全部三闸通过且可复现；1=failed；2=incomplete/配置证据不足。Schema见 [benefit-report.schema.json](benefit-report.schema.json)。preflight incomplete可run_ids/queries为空、aggregate/hard_metrics为null、未知环境指纹null；已知信息与失败路径仍保留，不能用0冒充未测量值。只有passed必须完整六query/版本/投影/非空run与所有数值。semantic validator另验算术、query唯一、source合法、gate checks、cache计数/manifest、实际覆盖。

## Triple gate and release

quality含双指标提升/三个非降/固定覆盖/可复现证据。safety含宪法全部硬指标、source-chain100%、hard/隔离/越权/旧holder0、非空投影无模型重建100%、context排序恒等。regression含六新增E2E、012原八项、AOEP五不变量各≥2、001–012全部原口径和target host证据。skip/missing不算pass；现有1%容差不用于安全。

只有quality=safety=regression=passed才default_enable_eligible=true。报告default_configuration为建议，不发policy；否则两个默认开关false并保留能力。正式读取扩展需当前版本绑定的三闸证据加域policy；隔离评测显式candidate扩展不授予正式域许可。已有用户合法opt-in保持其原治理纪律。

passed报告必须含完整gate_binding，环境对应指纹一致、所有query同scope，record/replay绑定一致；其余未观测绑定可null。共享语义validator核验这些关系，Schema不能代替跨字段算术/身份验证。runner只写独立报告，不登记生产证明；部署者审阅后按 [gate-proof.md](gate-proof.md) 原子安装只读登记。只有candidate_expansion报告可授权链接扩展，direct报告只提供相应直接路径质量证据。缺证明/错scope/旧绑定/过期/哈希不符不授予正式增强权限，不影响原合法直接召回。
