# Research: 012 记忆基座与写读回路

**Date**: 2026-10-04  
**Scope**: Resolve implementation and validation decisions required by `plan.md`. 研究不改变 `spec.md` 已批准的行为；任何性能或权重优化仍须经过 015 评测门。

## Decision 1: 同事务物化边界

**Decision**: `memory_events` INSERT 与 PostgreSQL 关系投影 UPSERT 使用同一 `AsyncSession`/数据库事务；服务只在事务成功提交后返回成功。Qdrant vector upsert 属于同一写请求的同步成功边界：向量失败不返回成功，记录可恢复失败并由 rebuild/补偿路径恢复。链接图、摘要树、文件镜像通过投影 registry 记录版本/完成状态并可从日志重建，不成为当前态事实源。

**Rationale**: PG 内部可获得真正的 ACID 原子性，满足同事务物化和“无最终一致性窗口”的关系投影要求。Qdrant/文件系统不能参加同一个 PG 事务，因此把跨存储部分明确成同步成功边界并提供失败闭合与可重建语义，避免虚假的分布式事务承诺。

**Alternatives considered**:

- 异步 outbox/worker 投影：吞吐和故障隔离较好，但会暴露事件已成功、投影未到位的窗口，违反本 Feature 的同事务关系投影与读后立即可见要求。
- 直接把关系表作为事实源：实现简单，但无法满足 G2+ 日志唯一权威、回滚重放和投影等价性。
- 分布式事务协调 PG+Qdrant：当前依赖没有可靠 2PC，复杂度和故障面高于首期收益；以幂等 upsert、失败状态和 rebuild 替代。

**Evidence plan**: integration test 在同一事务中注入关系 UPSERT 异常，断言事件也回滚；注入 Qdrant 异常，断言不返回成功、审计 failed path、重试/rebuild 后恢复。

## Decision 2: 事件-投影等价性验证

**Decision**: 将事件 reducer 定义为纯函数/可测试适配器：给定有序事件流和快照，输出关系当前态、salience、向量/文件/摘要/link 的 projection intents。在线写路径和 rebuild 都调用同一 reducer/validator；integration test 对同一事件批次比较在线物化与离线回放的规范化 JSON、状态、scope 分布、supersede 链和指纹。

**Rationale**: 共享 reducer 直接消除“在线逻辑”和“回放逻辑”漂移；规范化比较排除时间戳、request_id 等信封易变字段，同时保留事件顺序、内容 hash、状态和投影版本。

**Alternatives considered**:

- 只对最终行做抽样对比：无法覆盖 retract、supersede、rollback、跨 scope 和空投影边界。
- 在线路径和 rebuild 各自实现：短期灵活，长期容易产生不可重建状态，违反宪法 XIII。
- 只比较数量：不能发现 scope 串库、provenance 丢失或字段覆盖错误。

**Evidence plan**: property-style fixtures 覆盖 assert/revise/retract/access/rollback、并发失败、snapshot+delta，比较六类 projection fingerprints；失败输出第一条 event_id/aggregate_id 差异。

## Decision 3: Qdrant status 不下推与假阴性实验

**Decision**: Qdrant 只下推显式 scope（以及可证明不变的 kind/session），永不下推 status；PG 后置核验 status、valid_from/valid_to、agent_id、include_superseded 和阈值。建立陈旧 payload 实验：先写入 active point，再在 PG 追加 retract/retire/revise，不更新 Qdrant payload，分别运行 status 下推和不下推两臂；不下推臂必须由 PG 过滤出正确结果/无假阴性，并记录候选、过滤和延迟。

**Rationale**: status 是事件驱动的当前态，向量 payload 可能滞后；将 status 下推会把已恢复/重新激活或 payload 陈旧的有效条目错误丢弃，形成假阴性。scope 是隔离边界，必须下推以防候选跨域。

**Alternatives considered**:

- 每个状态事件同步更新 Qdrant payload：减少 PG 后置结果，但外部写失败会扩大一致性窗口，且仍无法保证历史回放期间 payload 完整。
- status 和 scope 都不下推：安全但候选量和跨域风险不可接受。

**Evidence plan**: `test_memory_status_payload_staleness_no_false_negative` 构造陈旧 payload，断言 status 后置路径返回应见条目；同 scope、kind/session filter 的 payload 校验覆盖隔离和过召回下限。

## Decision 4: 显著性冷启动、衰减与排序自锁风险

**Decision**: 新 memory 初始 `salience=0`；首期 β=0.05/day、γ=1.0/access，从 `memory_policy.decay_rate` 派生并可由管理面覆盖；RRF salience 权重启用但保守为 0.2，只有完成强制衰减才进入排序。研究测试构造两臂：无衰减的 access 正反馈臂与带衰减臂，重复访问 top 条目，比较 top-k 集中度、长尾覆盖、旧条目复苏和排序熵；无衰减臂必须被标记为不合规，带衰减臂供 015 调优。

**Rationale**: salience 能表达真实使用反馈，但无衰减会形成“越召回越访问、越访问越召回”的自锁。零冷启动避免未使用条目获得人为优势；低权重让 dense/recency 主导首期结果。

**Alternatives considered**:

- 初始 salience=1：所有条目获得相同但非必要的热度，掩盖 access 信号并复杂化衰减基线。
- 首期不参与排序：更保守，但无法验证 Q45 已批准的排序路径和自锁防护。
- 固定代码常量且禁止域覆盖：可重复但不符合 DomainProfile 配置中枢原则。

**Evidence plan**: `test_salience_decay_monotonic`、`test_salience_cold_start`、`test_salience_no_decay_disables_rank_signal`；评测报告同时记录访问分布、top-k overlap、coverage、entropy 和 P50/P95。

## Decision 5: scope binding 最长前缀边界

**Decision**: 仅接受绝对路径或规范化 Git remote；相对路径直接 `MISSING_KNOWLEDGE_SCOPE`。路径先 `resolve()`/统一分隔符并保留大小写策略：Windows 盘符和路径比较大小写不敏感，Git remote canonicalize host/尾斜杠/`.git`，binding kind 仍决定规则。匹配按最长前缀，再 priority，再唯一命中；同前缀同 priority 多绑定返回 `AMBIGUOUS_DOMAIN_REF`。软链接按 resolved realpath 匹配，并记录原始输入和规范化值，避免绕过绑定。

**Rationale**: 规范化在匹配前执行，能阻止大小写、分隔符、软链接和 `..` 变体绕过 scope；最长前缀使 monorepo 子目录绑定可覆盖根绑定，同时不依赖隐式默认域。

**Alternatives considered**:

- 字符串前缀直比：会误判 `/repo/a` 与 `/repo/abc`，且软链接/大小写可绕过。
- 只按 priority：无法表达嵌套目录的最具体绑定。
- 相对路径按当前工作目录补全：把宿主 cwd 变成隐式授权源，违反 scope 显式性。

**Evidence plan**: matrix 覆盖 root/subdir、同前缀多 binding、大小写、尾斜杠、软链接、相对路径、Git remote 等价写法，检查唯一命中/歧义/缺失码和 candidates。

## Decision 6: 日志快照、截断与 rebuild

**Decision**: 权威事件快照按 10,000 个权威事件或 24 小时先到者生成，包含快照 event_id、created_at、六类 projection fingerprints、schema/index/policy 版本。access 段按 90 天 TTL 独立清理；权威段只允许截断已被完整快照覆盖且不属于 revise/retract/consolidate/grant/rollback 或依赖链的普通 assert。rebuild 从最近有效快照载入，再按 occurred_at/event_id 重放增量；快照缺失、版本不兼容或指纹校验失败必须 fail-loud。

**Rationale**: 数量阈值限制高流量场景增长，时间阈值限制低流量 scope 的恢复时间；保留修订/撤回/回滚链保证历史语义与审计可追溯。快照+增量重放让截断不会改变当前态和回滚边界。

**Alternatives considered**:

- 仅按时间快照：流量峰值期间单个快照过大。
- 仅按容量：低流量 scope 可能长时间没有恢复锚点。
- 任意截断旧事件：破坏纠正链、rollback 和 provenance；不可接受。

**Evidence plan**: 生成超过阈值的事件流，在截断前后分别全量 replay 与 snapshot+delta rebuild，比较六类指纹；模拟缺快照、schema 版本不兼容和依赖链被截断，均应失败闭合。

## Decision 7: rollback 场景矩阵与仲裁

**Decision**: rollback 只接受单 scope；目标为 valid/observed 明确的时间点或单一 event_id，且仅管理面可调用。默认重放权威状态事件，不撤销/删除 access；文件、摘要、向量、链接等派生投影从目标点重建。supersede 冲突按目标 event_id 的日志顺序仲裁：目标点前的 revise/retract 生效，目标点后的链在回滚视图中隐藏但保留日志；再次 rollback 只能指向当前 scope 的更早事件点并新增 rollback 事件，不能把之前的 rollback 事件物理删除。

**Rationale**: 单 scope 防止跨域状态扩张；access 是使用审计，不是事实状态，保留它可分析回滚前后的使用轨迹。事件点顺序是确定性仲裁，不引入人工/LLM 竞争裁决。

**Alternatives considered**:

- 跨 scope rollback：可能把域 A 的历史投影复制到 B，违反硬隔离。
- 回滚 access：丢失审计并使 salience 重放不可解释。
- 让最新 supersede 永远胜出：无法表达时间旅行，且与 event-point rollback 定义冲突。
- 删除回滚后的事件：破坏 append-only 与审计，禁止。

**Evidence plan**: matrix 覆盖时间点、event point、目标前后 revise/retract、跨 scope、回滚后再次回滚、access 保留和文件刷新；断言 rollback 事件、影响面、前后指纹和 scope 均正确。

## Decision 8: Schema/DDL 宽模式与应用校验

**Decision**: Alembic/SQLAlchemy CHECK 仅约束宽枚举、非空隔离键、时间/唯一索引和不可变事件入口；精确 provenance、scope、evidence published、supersede active、policy 范围、四态输出和 rollback 权限由独立纯校验器负责，单元测试覆盖每个错误码。事件表不暴露 UPDATE/DELETE repository method，投影写入只能经 reducer/transaction service。

**Rationale**: 宽 CHECK 允许未来只增事件/策略字段，避免迁移把业务矩阵硬编码在数据库；应用校验可给出稳定 MCP 错误和可测试的跨表条件。代码层+测试层双防守仍保证当前闭合枚举。

**Alternatives considered**:

- 所有业务规则放 CHECK/trigger：迁移耦合、错误映射不稳定、跨表 evidence/published 检验难维护。
- 完全不设 CHECK：数据库可接受非法事件，违反宽模式房规和投影完整性。

## Open Risks and Planned Measurements

- Qdrant 同步写入无法与 PG 原子提交：以失败闭合、幂等 point id、audit failed paths 和 rebuild 演练作为风险控制。
- 5000 quota 与单事务投影可能放大写延迟：记录写事务耗时、scope quota 命中、Qdrant P95，超过预算时仍 fail-loud，不静默异步化。
- salience 可能造成长尾退化：015 运行衰减/无衰减双臂并以 coverage/entropy/任务完成判据调权。
- 六类投影中文件/摘要/链接的刷新时序：本 Feature 强制版本和指纹，可重建，不允许消费面把 partial 当 complete。
