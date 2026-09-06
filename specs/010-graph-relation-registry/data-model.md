# Data Model: 图关系注册表（010）

**Branch**: `010-graph-relation-registry` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

> 010 不新增任何物理表：变更面 = `graph_edge` 一条 CHECK 约束的宽模式化（迁移 0074）、`domain_profiles` 一行 legal 内置种子（007 启动同步，无 DDL）、以及提取器/注册表两份**代码级数据契约**（插件边 dict、inverse map）。图节点仍为虚拟（= Chunk）、软关系/图扩展路径表零改动（R14）。下列为模型级草图，完整迁移与实现属 tasks 阶段。

---

## 1. 实体总览（变更面）

| 实体 | 物理载体 | 变更 | 来源 FR |
|------|----------|------|---------|
| 图边（Graph Edge，硬关系） | `graph_edge` 表 | relation_type CHECK：闭合 5 值枚举 → 宽模式 pattern（drop/add）；ORM validates pattern 化 + other_hard 退役；写入前应用层词表校验（store chokepoint） | FR-008/FR-009/FR-010 |
| 域档案（DomainProfile） | `domain_profiles` 表 | 新增 legal 内置行（种子，is_builtin=true，只读） | FR-016（澄清 Q4） |
| GraphExtractor（图提取器插件） | 代码级（`graph/extractors/base.py`） | 新增：ABC + format/relation_pairs/chunk_scope 声明 | FR-001 |
| 图关系注册表（Graph Extractor Registry） | 代码级（同上） | 新增：按 format 注册、按域词表交集发现、inverse map 聚合 | FR-002 |
| 插件边 dict（extract 返回值） | 代码级数据契约 | 新增/收编：9 字段规范结构（duck-typing 显式化） | FR-003 |
| inverse map（关系逆映射） | 代码级（注册表聚合） | 新增：反向遍历 CASE 的数据来源 | FR-013（Q2） |
| 交叉引用评测集 | `eval/cross_reference_eval_dataset.json` | 新增：≥6 条法律域受益子集 | FR-029 |

零改动面（回归闸口对象）：`soft_relation`、`graph_expansion_path`、`knowledge_versions.capabilities/graph_ready` 门控、Chunk/Qdrant payload。

---

## 2. graph_edge 约束变更

### 2.1 迁移 0074（drop/add，沿用 0073 范式）

```sql
-- 前置断言（非零即 raise 阻断，要求显式回填；004 提取器从未产出，验收环境恒 0）
SELECT count(*) FROM graph_edge WHERE relation_type = 'other_hard';
-- 放宽（宽模式 pattern，与 0073 三列放宽同形态）
ALTER TABLE graph_edge DROP CONSTRAINT IF EXISTS chk_graph_edge_relation_type;
ALTER TABLE graph_edge ADD CONSTRAINT chk_graph_edge_relation_type
  CHECK (relation_type ~ '^[a-z][a-z0-9_]{0,62}$');
```

- **存量零重写**（澄清 Q3）：calls/called_by/fk_references/fk_referenced_by 原值保留（已与 se-project 词表键一致）；relation_type 保持裸词表键，**不引入域前缀命名空间**——域隔离由 `knowledge_scope_id` 唯一承担。
- 列类型 TEXT 不变（pattern 上界 63 字符 ≤ TEXT）；索引与唯一键零改动。
- downgrade：恢复闭合枚举 CHECK（other_hard 值若已由 010 后写入则回滚断言同样阻断）。

### 2.2 校验分层（合法性来源 = 域档案词表，唯一权威）

| 层 | 位置 | 规则 | 失败行为 |
|----|------|------|----------|
| DB CHECK | `chk_graph_edge_relation_type` | `^[a-z][a-z0-9_]{0,62}$` | INSERT/UPDATE 拒绝（最后防线） |
| ORM validates | `graph/models.py`（替换 45-49 枚举与 `_HARD_RELATION_TYPES`） | pattern + 禁 `inferred`（归 soft_relation）+ 禁 `other_hard`（退役） | ValueError（构造期） |
| 词表校验（权威） | `PostgresGraphStore.write_edges(edges, scope, allowed_relation_types)` 必填参数 | relation_type ∈ 该域 `graph_relations` 键集 | 整批 ValueError → 调用方降级（记 `hard_degraded_reason`、0 边、不断链，沿用 `ingestion_service.py:858-863`） |
| 注册表发现（预防） | `registry.discover(format, graph_relations)` | 提取器 relation_pairs 键集 ∩ 词表 ≠ ∅ 才调用 | 无交集跳过（0 边，非失败） |

软关系不变：`soft_relation.relation_type` 恒 `inferred` CHECK 保留（FR-011，宪法 III 硬/软区分）；宽模式仅作用于硬边取值域。

---

## 3. legal 内置域档案（domain_profiles 种子行）

| 字段 | 值 | 依据 |
|------|-----|------|
| `domain_key` | `legal` | FR-016（澄清 Q4） |
| `name` / `description` | Legal / 法律文档域：条文结构 + 交叉引用图关系 | — |
| `supported_formats` | `["markdown"]` | 对齐 cross_reference 格式面；011 可扩展 |
| `graph_relations` | `{"references": ["out","in"], "referenced_by": ["out","in"]}` | FR-013 成对词表（Q2） |
| `chunk_type_extensions` | `null` | markdown 切片沿用 section 词表 |
| `prompt_overrides` | `null` | 走 009 域中立基础模板 + 词表槽位注入（R11） |
| `default_capabilities` | `{"retrieval_modes": ["dense","hybrid","graph_enhanced","agentic"], "has_graph": true}` | 与 se-project 同构 |
| `is_builtin` | `true` | 007 只读保护 + 启动同步自动生效 |

种子落 `config/domain_profiles.py::BUILTIN_DOMAIN_PROFILES`（第三条目，se-project/generic 原样不动）；`DomainProfileService.sync_builtin_profiles` 负责插行与漂移修复（升级部署零迁移）。**受益闸口失败时的交付形态**：`graph_relations = {}`（空词表 → cross_reference 不触发 → 图路径不进 legal 默认检索；提取器与注册表照常交付，自定义档案可显式启用，research R11 声明式补救）。`default_capabilities.has_graph` 维持 true：图路径可用性由 graph_ready 门控自然收敛（空词表 → 0 硬边 → 不可声明），无需新增开关。

---

## 4. 插件边 dict 契约（extract 返回元素）

收编现有 java/ddl duck-typing 产出结构为显式契约（FR-003；为 `graph-relations.schema.json` 字段面的子集（`edge_id` 写入期生成、`project_id` 属 007 遗留债不进插件边 dict），序列化层剔除 `created_at` 沿用 004 约定）：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `source_chunk_id` | int | 引用方 Chunk | 条文引用 = 含引用文本的 Chunk（行号区间归属） |
| `target_chunk_id` | int | 被引用方 Chunk | 锚点/相对路径/条文号解析到的标题 Chunk |
| `relation_type` | str | ∈ 域词表（R2.2 分层） | cross_reference 产出 references / referenced_by |
| `direction` | str | `"out"` | 成对两条边各自 out（Q2 对称约定） |
| `is_hard` | bool | `true` | 确定性解析产生 |
| `version` | int | orchestration 统一盖戳 | 沿用 `ingestion_service.py:850-851` |
| `knowledge_scope_id` | int | = scope | 唯一隔离键（007） |
| `index_version` | int | = scope | 版本隔离 |
| `parse_evidence` | dict | 3 字段 | `{source_format: "markdown", extractor: "cross_reference", locator: "xref:..."}`（locator 编码见契约 cross-reference-extraction.md §4） |

**inverse map**（注册表聚合，代码级）：`{"calls":"called_by", "called_by":"calls", "fk_references":"fk_referenced_by", "fk_referenced_by":"fk_references", "references":"referenced_by", "referenced_by":"references"}`——由三个提取器的 `relation_pairs` 声明聚合生成，供反向遍历 CTE 与注册校验消费（research R9）。

---

## 5. 注册表发现决策表（format × 域词表 → 提取器）

| format | 域词表 | discover 结果 | 语义 |
|--------|--------|---------------|------|
| java | se-project（calls/…/fk_referenced_by） | `[JavaCallGraphExtractor]` | 004 行为逐条不变 |
| ddl | se-project | `[DdlFkExtractor]` | 004 行为逐条不变 |
| markdown | se-project | `[]` | 词表无 references/referenced_by → 不命中（US1 场景 1/2） |
| markdown | legal（references/referenced_by） | `[CrossReferenceExtractor]` | 非 SE 图能力启用 |
| markdown | generic（空） | `[]` | 0 边 → graph_ready 不可声明（SC-008/SC-009） |
| 任意 | 任意（含未来自定义） | 声明序确定性合并去重 | 多提取器命中 Edge Case（spec） |

---

## 6. 评测数据产物（新增，不改既有）

| 产物 | 内容 | 约束 |
|------|------|------|
| `eval/corpora/legal/*.md` | 虚构法规语料（主法规 `## 第X条` 结构 + 实施细则，含三类引用形态） | 虚构文本；覆盖 R7 全部规则分支 |
| `eval/cross_reference_eval_dataset.json` | ≥6 条（query/project_scope/expected_evidence_ids/`is_structural_benefit:true`） | ≥1 中文条文引用、≥1 锚点导航、≥1 跨文件相对链接；AI 生成 + 人工审核入库约定 |
| `eval/cross_reference_comparison_report.json` | 法律域混合基线 vs 图增强对照（复用 004 报告器结构：三段闸口/硬指标/可重复性） | SC-002 ≥3% 闸口判定载体 |
| `eval/010_graph_regression_report.json` | 004 图集 37 条回归重跑产物 | 1% 相对容差；不覆盖 `graph_enhanced_comparison_report.json` 历史报告 |

---

## 7. 状态与生命周期（零变更声明）

- graph_ready 门控（`ingestion_service.py:491-509`，硬边 > 0 方可声明）：**语义与实现零改动**（FR-020）。
- 软关系四态（inferred/active/superseded/retired）与五项元数据：**零改动**（FR-021）。
- 图边删除/清空（mark_graph_unretrievable → delete_graph_relations）：**零改动**，词表参数仅作用于写入路径。
- 提取失败降级：raise → orchestration catch → `hard_degraded_reason` + 0 边 + 入库链不断（**语义沿用**，`ingestion_service.py:858-863`）。
