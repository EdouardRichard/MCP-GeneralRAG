# 连续性对照闸门与报告契约 v1（014）

本契约定义多会话连续性评测集、对照臂、判据、可复现性与报告。对应 FR-033/FR-034/FR-035/FR-036、SC-010/SC-014/SC-015。

## 1. 闸门对象与唯一变量

- **闸门对象**：跨会话续接能力（工作集续接 + 附加层记忆）。判据为**任务结果**而非排名。
- **对照臂**：`without_memory`（基线）与 `with_memory`（启用记忆可用性）。两臂必须使用**同一**冻结输入快照、同一查询集、同一预算、同一环境。
- **唯一启用变量**：记忆**可用性**。基线臂必须：
  - 不传 `session_id` / `memory_context`（禁用相关参数）；
  - 不共享会话状态与已交付记忆集（各自独立恢复）；
  - 不通过更换语料、策略、K 值或提示制造差异；
  - 并断言基线响应**零新字段**（`related_memories`/`memory_notice`/`counts` 均不出现）。
- 库内容一致性必须由快照摘要证明，不能只靠口头声明。

## 2. 数据集

`eval/memory_continuity_eval_dataset.json` 为冻结对象，键：`dataset_version`（如 `014.eval.1`）、`frozen{budget, clock, implementation, model, policy, prompt, recall, schema, snapshot, vocabulary}`（本 Feature 无 LLM，`model` 显式为 `"none"`）、`snapshot_hash`、`source`、`k=5`、`queries[]`。

`queries[]` 每条：

| 键 | 约束 |
|---|---|
| `query_id` | 唯一 |
| `category` | `resume_after_break` \| `recall_last_decision` \| `lesson_effective` \| `preference_applied` |
| `language` | `zh` \| `en` |
| `question` | 自然语言任务描述 |
| `scope_id` | 已解析作用域 |
| `required_items[]` | 非空；每项 `{locator, memory_id?, require_citation: bool}`；`locator` MUST 为跨环境稳定锚点（作用域 slug + 定位前缀/结构锚点，沿用 011 FR-007 与 010 先例），`memory_id` 仅作同快照内一致性校验，MUST NOT 作为唯一锚点 |
| `forbidden_items[]` | 越域/禁止项（可为空数组，但键必须存在） |
| `criterion` | 该条显式任务完成判据（人类可读、可判定） |
| `_meta` | 人工审核记录：`review_status`（`reviewed`）、`review_notes`、`grounded_source`（沿用 011/agentic 数据集形态） |

**规模与覆盖**：查询数 ≥15；四类各 ≥1；`zh` ≥2（目标为多数）；AI 生成 + 人工审核，审核记录以逐条 `_meta.review_status`/`_meta.review_notes`/`_meta.grounded_source` 随数据集入库。查询、判据与标注在评测前冻结，**不得**事后替换或删除失败查询。锚点稳定性与审核记录形态沿用 **011 固定集纪律**（[011 spec.md FR-005/FR-007](../../011-generic-domain-evaluation/spec.md)）与 `eval/README` 固定集纪律；不得追加进既有数据集文件。

**保护缺口（必须补齐）**：既有 `backend/tests/contract/test_domain_eval_dataset_schema.py` 只钉住 3 个既有数据集的 sha256，**不扫描新文件**，因此本数据集既无继承义务也无保护。014 必须自带校验测试（查询数、四类覆盖、中文、`required_items` 结构、`frozen` 键完整、`query_id` 唯一）并把本文件的 sha256 纳入 pin。

## 3. 判定

- 每条二元：`task_complete = (全部 required 命中且可定位引用) AND (零 forbidden/越域/非法项)`。
- `completion_rate = completed / queries`（两臂各自计算）。
- **相对提升**：`relative_gain = (with_memory − without_memory) / without_memory`。
- **基线为零**：`without_memory == 0` ⇒ `BASELINE_ZERO_NOT_COMPUTABLE`，此时**不得**以无穷、极小值或"显著更好"等措辞宣称过闸；改用预冻的显式判据（默认 ≥12/15 且四类各 ≥1）。
- **冗余度**：`redundancy = 1 − distinct_items / total_items`（确定性、可逐条重算）；作为辅助观测，不得替代主判据。
- **达标**：相对提升 ≥3% **或**显式任务完成判据达标；两者都必须在报告中给出可复算依据。

## 4. 可复现性

- 两臂各自独立恢复（沿 013 的隔离身份范式，简化为 2 臂 × 2 轮）：独立数据库、独立数据根、独立向量存储；恢复后校验 authority 摘要、alembic 版本、快照哈希与投影清单，产出恢复凭证。
- 记录/重放：成功与失败响应都要记录并重放；次轮真实网络调用数为 0；缓存缺失、损坏或版本不匹配即判 `incomplete`，**不得**宣称过闸。
- 非延迟指标两轮漂移 ≤ 1%（0.01）；安全硬指标零容差。既有检索全集回归沿用 011 的全集回归口径（非延迟指标 1% 相对容差、安全硬指标零容差），且**不得**以统计容差替代安全硬指标。已批准变更（交付去重窗口 7 天 → `delivered_ttl_seconds` 默认 3600 秒）必须在报告中留证，并附 012"会话时间线与已交付过滤"E2E 按新口径通过的证据。
- Windows 编码：运行器输出对非 GBK 字符可能抛 `UnicodeEncodeError`（控制台 cp936）；运行器必须以显式 UTF-8 写文件，并在打印时使用 `PYTHONIOENCODING=utf-8` 或保持 stdout ASCII。

## 5. 报告

- 路径：`eval/runs/<unique-run>/memory-*.json`；`--output` 必须唯一，**拒绝覆盖**既有字节不同的报告。
- 顶层键：`schema_version`（`014.1`）、`report_type`、`generated_at`、`commit`、`status`、`environment`、`dataset_version`、`snapshot_hash`、`k`、`queries[]`、`aggregates{without_memory, with_memory}`、`relative_gain`、`zero_baseline`、`criteria`、`redundancy`、`reproducibility`、`hard_metrics`、`gates{quality, safety, regression}`、`default_enable_eligible`、`evidence_paths`、`failed_paths`。
- `queries[]` 每条给出两臂的命中/缺失/越域项、`task_complete` 与差异说明；失败路径不得省略。
- `default_enable_eligible = quality AND safety AND regression AND reproducibility=='passed'`；`status=passed` ⇒ `default_enable_eligible=true`。
- 退出码：`0` 通过、`1` 失败、`2` 证据不完整（数据集非法、快照/恢复失败、缓存不可用）。
- 报告**不自动修改**任何开关或域策略；它只提供是否具备默认启用资格的证据。

## 6. 硬指标

跨域（含记忆路径）泄漏 = 0；MCP schema 合法率 = 100%；隔离记忆（`quarantined`）进入默认召回/附加/工作集/巩固窗口 次数 = 0；`memory_context` 检测先行率 = 100%（检测先于任何召回/打分/排序/拼装，flags 随行；检测失败不阻塞检索且不放宽过滤与阈值）。

证据定位语义分界（宪法 IV）下的两项独立指标，MUST NOT 合并口径：

- **`evidence[]` 来源可定位率 = 100%**：每条证据携带 `source_id`/`source_version`/`source_position`（既有 001/002/003/007/008 口径，未改动）。
- **记忆 provenance 完备率 = 100%**：`provenance` 必在；`soft`/`distilled` 五元元数据（`source`/`confidence`/`model_version`/`time`/`supporting_evidence`）完备；`hard` 条目逐条归属复验通过；记忆条目 MUST NOT 携带 `source_position`/`source_version`（两套定位语义不得混写）。

硬指标零容差；任一项失败阻断发布，不以默认关闭替代修复。

## 7. 三宿主冒烟

- 策略：DSH 为唯一必过参考客户端（工作集续接与文件投影直读端到端），ChatGPT App 与 Claude Code 记录兼容状态、不作阻塞项。未执行**不得**记为通过；宿主不可用必须记录状态。
- 文件投影直读采用三层证据：文件系统级校验（存在性、frontmatter 完备、正文与权威一致、清空后重建摘要可复现）为**必过**；DSH 侧真实观测探针记录实际读取（未观测到即 `failed`）；另两宿主仅记录环境可用性与兼容状态。
- 文件投影是文件系统读取、不经 MCP，因此**不存在**协议层的"宿主直读"证据；不得以 MCP 调用成功冒充文件直读成功。
