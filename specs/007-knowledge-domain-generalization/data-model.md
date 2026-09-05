# Data Model: Knowledge Domain Generalization (007)

**Branch**: `007-knowledge-domain-generalization` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)

> Phase 1 产出。数据模型变更范围：**新增 1 张表**（`domain_profiles`）与 **`knowledge_scopes` 扩展 2 列**（`domain_key`、`slug`）；**`graph_edge` / `soft_relation` 各删除 1 列**（`project_id`，澄清 Q4）。Qdrant 不变；知识源/版本/Chunk/005 agentic 表零改动。域档案为配置数据、不进向量库（蓝图 §3.2/ADR-3）；slug 为按名寻址标识、仅在 `domain_scope` 参数内解析（FR-012）。

## 1. 实体总览

| 实体 | 类型 | 职责 | 生命周期 |
|------|------|------|----------|
| domain_profiles | 新表（配置） | 域档案注册表：格式集/chunk_type 词表/图关系词表/提示词覆盖/默认能力的"一处声明"（ADR-3） | 迁移种子化内置行 → 启动同步 → CRUD（内置只读） |
| knowledge_scopes（扩展） | 既有表加列 | 唯一隔离单元：新增语义轴 domain_key + 全局唯一 slug 按名寻址标识 | 既有（active/archived/deleting） |
| graph_edge / soft_relation（收缩） | 既有表删列 | 图隔离键收敛为唯一 `knowledge_scope_id`（去 Project 依赖，FR-018） | 既有 |
| scope slug | 知识域标识 | 跨 project/public 全局唯一、创建后不可变的按名寻址标识（Q2） | 创建分配 → 不可变更 |
| 知识域引用（Knowledge-Domain Reference） | 解析器输入 | 检索请求的显式作用域形式（project_scope ∪ domain_scope） | 请求级，无持久化 |
| 域元数据摘要（Domain Metadata Summary） | list 输出 | `list_knowledge_domains` 返回的活跃域元数据（无知识内容） | 请求级派生 |

**关系**：`knowledge_scopes.domain_key` → `domain_profiles.domain_key`（FK，缺省 se-project）；`graph_edge.knowledge_scope_id` / `soft_relation.knowledge_scope_id` → `knowledge_scopes.scope_id`（既有 FK 不变）；`project_id` 不再落图，可经 `scope_id → Project.knowledge_scope_id`（UNIQUE FK）联查派生（宪法 VIII）。

## 2. domain_profiles（域档案注册表）

### 2.1 字段

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| domain_key | VARCHAR(64) | PK | 域档案稳定标识（`se-project`、`generic`、`legal`…） |
| name | VARCHAR(255) | NOT NULL | 显示名 |
| description | TEXT | NULL | 描述 |
| supported_formats | JSONB（字符串数组） | NOT NULL | 该域可接受的格式集声明 |
| chunk_type_extensions | JSONB | NULL | 命名空间扩展词表（`^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$` 形态） |
| graph_relations | JSONB | NOT NULL（generic 为空对象/数组） | 该域可用 relation_type 词表及方向 |
| prompt_overrides | JSONB | NULL | planner 提示词注入片段（关系词表、检索示例） |
| default_capabilities | JSONB | NOT NULL | 默认能力声明 |
| is_builtin | BOOLEAN | NOT NULL，DEFAULT false | 内置标记（只读保护依据，Q1） |
| created_at | TIMESTAMPTZ | NOT NULL，DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL，DEFAULT NOW() | 更新时间 |

### 2.2 索引与约束

- `PRIMARY KEY (domain_key)`。
- 无其他唯一约束；`is_builtin` 只读保护由服务层 + API 层双重校验（内置行拒绝 update/delete，含字段级；Q1 决议），DB 不依赖触发器。

### 2.3 种子与同步（FR-004/FR-005）

- **种子行（迁移内置）**：
  - `se-project`（is_builtin=true）：supported_formats = [markdown, java, openapi, ddl, go, python, word, pdf]；graph_relations = {calls, called_by, fk_references, fk_referenced_by}（含 out/in 方向）；prompt_overrides = 现 SE planner 提示词内容（`agents/query_planner.py` 逐句冻结）；default_capabilities = 1.0 既有默认能力。
  - `generic`（is_builtin=true）：supported_formats = [转换层格式（008 前瞻声明）…, markdown, word, pdf]；graph_relations = 空；prompt_overrides = 域中立提示词；default_capabilities = 通用默认能力。
- **启动同步**：进程内注册表与 DB 行比对，内置行字段漂移则回写种子；同步失败显式失败启动（不静默降级为硬编码，SC-008）。

### 2.4 消费点（007 边界）

007 仅消费：`list_knowledge_domains` 能力摘要 + 知识域 `domain_key` 赋值。格式接受性/chunk_type 校验/planner 提示词注入/图关系词表四个消费点的注册表接线分别属 008/009/010（FR-006）。

## 3. knowledge_scopes 扩展（domain_key + slug）

### 3.1 新增字段

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| domain_key | VARCHAR(64) | NOT NULL，FK→domain_profiles.domain_key，DEFAULT 'se-project' | 语义轴：声明该域领域属性（FR-001/FR-002） |
| slug | VARCHAR(255) | NOT NULL，UNIQUE（全局，跨 project/public） | 按名寻址标识（FR-012） |

### 3.2 索引与约束

- `UNIQUE (slug)` —— 全局唯一（跨 project/public 单一命名空间）；冲突创建被 DB 拒绝（SC-011 重复 slug 拒绝率 100%）。
- `FK (domain_key)` → domain_profiles；删除仍被知识域引用的自定义档案被服务层拒绝（引用完整性不悬空，Edge Case）。
- slug 不可变（应用层约束）：服务/API 层拒绝任何 slug 更新；DB 唯一约束只仲裁冲突、不仲裁不可变。

### 3.3 回填与默认（FR-002，research §1.8）

- 迁移为全部存量 scope（project 与 public）赋 `domain_key='se-project'`，并生成唯一 slug（slugify(name) + 冲突数字后缀）。
- 新建 scope 未声明 domain_key 时默认 se-project；slug 由管理面指定或按名称生成（冲突追加后缀）。

## 4. graph_edge / soft_relation 收缩（删除 project_id）

### 4.1 变更（FR-018，research §1.4）

| 对象 | 变更 |
|------|------|
| graph_edge.project_id | **删除列**（原 BigInteger NOT NULL） |
| soft_relation.project_id | **删除列**（原 BigInteger NOT NULL） |
| idx_graph_edge_source | 重建：键位移除 project_id → (knowledge_scope_id, index_version, source_chunk_id, relation_type, direction) |
| idx_graph_edge_target | 重建：键位移除 project_id → (knowledge_scope_id, index_version, target_chunk_id, relation_type, direction) |
| idx_soft_relation_active | 重建：键位移除 project_id → (knowledge_scope_id, index_version, lifecycle_state) WHERE lifecycle_state='active' |
| uniq_graph_edge | 不变（本就以 scope_id 为键） |
| idx_soft_relation_pair | 不变（本就以 scope_id 为键） |

### 4.2 隔离语义

`knowledge_scope_id` 成为**唯一图隔离键**（跨域图边泄漏 = 0，SC-007/SC-003）；图检索资格不再要求存在 Project 行（`_graph_scope_triple` 去除 Project 门槛）；`project_id` 可经 `scope_id → Project.knowledge_scope_id` 联查派生，图数据可从源对象 + 版本元数据重建（宪法 VIII），无检索信息损失。

## 5. scope slug（按名寻址标识）

- **标识**：知识域的全局唯一按名寻址标识，跨 project/public（Q2 决议）。
- **词法**：`^[a-z0-9][a-z0-9-]*$`，长度 ≤255；由名称 slugify 生成或管理面指定。
- **不可变**：创建时分配、创建后不可变更（保证 domain_scope 引用可重放）。
- **命名空间**：仅在 `domain_scope` 参数内解析；与 `project_scope` 专属 alias/repo_path/project_id 属不同命名空间、互不交叉匹配（FR-012）。

## 6. 知识域引用（Knowledge-Domain Reference，解析器输入）

统一引用解析器（`RetrievalService.resolve_knowledge_scopes`）输入，两形式并集去重：

| 形式 | 条目形态 | 解析顺序 |
|------|----------|----------|
| project_scope（旧） | 数字 project_id / alias / repo_path / 数字 public scope ID | 沿用 1.0（零改动） |
| domain_scope（新） | 数字 knowledge_scope_id（任意 scope_type，限活跃域）→ slug（全局按名）→ type:name 限定引用（`scope_type:精确名称`） | 数字 → slug → type:name |

输出：活跃知识域 scope_id 集合（去重）+ 可选的歧义候选（`AMBIGUOUS_DOMAIN_REF` 携带 scope_type/domain_key/slug）。

## 7. 域元数据摘要（Domain Metadata Summary，list 输出）

`list_knowledge_domains` 返回的活跃域条目（仅元数据、无知识内容，FR-014/FR-022）：

| 字段 | 说明 |
|------|------|
| id | scope_id（Snowflake 字符串形式） |
| slug | 全局唯一按名寻址标识 |
| name | 知识域名称 |
| scope_type | project / public |
| domain_key | 引用域档案 |
| capabilities | {supported_formats, has_graph}，由域档案声明派生（has_graph = graph_relations 非空） |
