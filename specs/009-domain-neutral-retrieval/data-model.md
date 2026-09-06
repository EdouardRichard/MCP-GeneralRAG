# Data Model: 检索编排域中立化（009）

**Branch**: `009-domain-neutral-retrieval` | **Date**: 2026-09-06

本 Feature **无新持久化表**（复用 007 的 domain_profiles 与 knowledge_scopes）。核心数据形态为运行时派生配置与契约扩展，均为 additive。

## 1. 运行时派生实体：DomainPlannerConfig（非持久化）

由 entry.run_agentic_search 在作用域解析后派生，注入 context，供 query_planner 解析系统提示词与动态 schema（research R7）。

| 字段 | 类型 | 说明 |
|---|---|---|
| distinct_domain_keys | list[str] | 解析作用域集合去重后的 domain_key 集（≥1） |
| relation_vocab | list[str] | 各域档案 graph_relations 键集的**排序并集**（research R4）；无图档案贡献为空 |
| prompt_override | str \| None | 单一 domain_key 且其档案存在 prompt_overrides.query_planner_system_prompt 时为该覆盖片段；异构/缺失时为 None（research R1） |

派生规则（纯函数，可单测）：
- distinct_domain_keys == 1 且 prompt_override 非空 → planner 用该覆盖片段为完整系统提示词。
- distinct_domain_keys > 1（异构）或 prompt_override 为空 → planner 用域中立基础模板（关系词表槽位以 relation_vocab 填充）。

## 2. relation_directions 词表（动态派生）

来源：domain_profiles.graph_relations 的**键集**（graph_relations 为 relation-type → 方向轴 映射，如 se-project 的 calls → [out, in]）。

| 域档案 | relation_vocab | 说明 |
|---|---|---|
| se-project | [calls, called_by, fk_references, fk_referenced_by] | 与 1.0 硬编码 4 值一致（等价性闸口） |
| generic | [] | 无图档案，空词表 → graph 不可规划 |
| 异构（se-project+generic） | [calls, called_by, fk_references, fk_referenced_by] | 排序并集（generic 贡献空） |

消费点（planner 内部，均从 relation_vocab 派生）：
- NODE_SCHEMA 动态枚举（research R2）：signals 枚举、relation_directions items.enum、graph_hop 存在性。
- 校验：_validate_signals / _validate_directions / get_default_directions。
- fallback 输出：_build_fallback_output（无图时省略 relation_directions/graph_hop）。

## 3. NODE_SCHEMA 动态工厂（非持久化）

_build_node_schema(relation_vocab) -> dict：

| relation_vocab | signals 枚举 | relation_directions | graph_hop |
|---|---|---|---|
| 非空 | [dense, sparse, graph] | 含（items.enum = relation_vocab） | 含（integer 1–3） |
| 空 | [dense, sparse] | **省略** | **省略** |

校验器按 frozenset(relation_vocab) 缓存（内置两档案仅 2 形态）。schema_valid 语义 = 结构 + 域能力双重合法。

## 4. task_context 契约（additive 扩展）

| 字段 | 类型 | 语义 | 变更 |
|---|---|---|---|
| current_file | string | 编码域约定字段（向后兼容）：当前编辑文件路径 | 保留 |
| current_symbol | string | 编码域约定字段（向后兼容）：当前关注符号 | 保留 |
| work_phase | enum {requirements, design, implementation, testing, review} | 编码域约定字段（向后兼容）：工作阶段 | 保留 |
| activity | string（自由，maxLength 4000） | 当前正在做的事的短描述（任意知识域通用，一等信号） | **新增**（澄清 Q2） |
| additional_context | string（maxLength 4000） | 补充背景兜底（约束/偏好/参考） | 保留（描述域中立化） |

语义边界（澄清 Q2）：activity = 当前活动/任务本身；additional_context = 除活动外的其他补充背景；二者可共存、不互斥。

## 5. SourcePosition 契约（description 文档级变更）

| 属性 | 值 |
|---|---|
| type | string（不变，无新增 pattern） |
| description | 定位前缀规范表（对齐 008 locator-prefixes.md） |

定位前缀规范表条目（描述内引用）：# 标题路径（markdown/word/转换层 html/pptx）、page:N [§ 编号路径]（pdf）、全限定符号路径（java/go/python）、结构路径（openapi/ddl）、sheet:（xlsx 工作表名 / csv 文件基名）、path:/key/sub（json/yaml/xml）、msg:Subject（eml）。转换层格式定位粒度为转换后表示，不做原文档锚点还原。

## 6. 状态与生命周期

无持久化状态机变更。domain_planner_config 为 per-request 派生（请求级生命周期，不入库）；NODE_SCHEMA/校验器为 per-request 构造（按词表缓存）；域档案与知识域仍由 007 管理面 CRUD（内置只读）。
