# 013 Contracts

以下契约互相独立版本化，不能将LLM输出Schema当数据库写入或管理权限契约。

| 契约 | 用途 |
|---|---|
| [distiller-output.schema.json](distiller-output.schema.json) | Agent NODE_SCHEMA四动作/附件，Draft202012 |
| [consolidate-event.schema.json](consolidate-event.schema.json) | 可信服务生成的v2永久批准payload，旧v1沿012 |
| [pipeline-contract.md](pipeline-contract.md) | 四段、纯裁决、资格fence、策略、event/grant语义 |
| [management-api.md](management-api.md) | writer管理触发/运行报告/候选/人工晋升REST |
| [recall-extensions.md](recall-extensions.md) | 既有recall显式只读增强选择与旧响应兼容 |
| [benefit-report.schema.json](benefit-report.schema.json) | 固定子集/缓存/三闸机器报告 |
| [gate-registry.schema.json](gate-registry.schema.json) | 部署者安装的只读域/报告哈希/有效期登记 |
| [gate-proof.md](gate-proof.md) | 正式reader加载、绑定复验、撤销及默认拒绝授权 |
| [evaluation-contract.md](evaluation-contract.md) | 数据集冻结、等价相关性、统计/CLI/严格重放 |

内部ID正整数，REST snowflake为十进制字符串；run/eligibility UUID。JSON Schema验证结构，纯规则和DB验证finite/scope/来源/当前状态/authority/组完整性/闸口算术。所有输出新字段须净化，extra控制字段拒绝。

已发布MCP工具/旧管理请求保持原契约；本Feature不新增巩固或晋升MCP工具。新读字段需opt-in，旧字节兼容测试继续运行。
