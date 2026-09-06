# Contract: GraphExtractor 插件接口与图关系注册表

**Branch**: `010-graph-relation-registry` | **Date**: 2026-09-06 | **Spec**: [spec.md](../spec.md) | **Research**: R1–R3, R8–R9

本契约为 010 的内部架构契约（非对外 MCP 契约，宪法 VII）：定义 GraphExtractor 插件接口、图关系注册表发现语义、提取器边 dict 契约与失败降级语义。实现与测试以本契约为准。

## 1. 插件接口（`graph/extractors/base.py`）

```text
class GraphExtractor(ABC):
    format: str                          # 消费的源格式名（与 FormatHandler/域档案 supported_formats 同一命名空间）
    relation_pairs: Mapping[str, str]    # 成对关系声明，正反映射互逆，如 {"calls": "called_by"}
    chunk_scope: Literal["source", "scope"] = "source"
                                         # source = 仅当前知识源 chunk dicts（java/ddl）
                                         # scope  = 当前 scope 全量 chunk dicts（cross_reference，跨文件相对链接）
                                         #          每条 chunk dict 额外携带 filename 键（orchestration 注入）

    @abstractmethod
    def extract(self, source: str, chunks: list[dict], scope: GraphScope) -> list[dict]:
        """确定性提取硬关系边。MUST 无 LLM/网络调用；MAY 在内部失败时 raise
        （由 orchestration 降级，见 §5）；不可确定的关系 MUST 不产出。"""
```

**注册校验（build 时，失败 = 启动失败，沿用 008 §5）**：
- `format` 不与既有注册重复声明冲突（同 format 多提取器允许——发现按词表交集）。
- `relation_pairs` 每对 (k, v) MUST 互为逆（`pairs[v] == k`）；不同提取器的 pairs 键不得冲突。
- `relation_pairs` 键 MUST 匹配 `^[a-z][a-z0-9_]{0,62}$`（宽模式 pattern，与 DB CHECK 同源）。
- 只声明单侧关系（无逆）的提取器 MUST 拒绝注册（对称性是接口契约，澄清 Q2）。

**内置提取器（010 交付 3 个）**：

| 提取器 | format | relation_pairs | chunk_scope | 产出（行为） |
|--------|--------|----------------|-------------|--------------|
| `JavaCallGraphExtractor` | java | `{calls: called_by}` | source | 004 逐条不变（FR-005） |
| `DdlFkExtractor` | ddl | `{fk_references: fk_referenced_by}` | source | 004 逐条不变（FR-005） |
| `CrossReferenceExtractor` | markdown | `{references: referenced_by}` | scope | 见 cross-reference-extraction.md |

## 2. 边 dict 契约（extract 返回元素）

9 字段规范结构（收编 duck-typing 现状）：`source_chunk_id` / `target_chunk_id` / `relation_type` / `direction`（恒 `"out"`）/ `is_hard`（恒 `true`）/ `version`（orchestlation 统一盖知识源版本戳）/ `knowledge_scope_id` / `index_version`（取自 `GraphScope`）/ `parse_evidence`。

- `parse_evidence` 恒 3 字段 `{source_format, extractor, locator}`（与 graph-relations.schema.json 的 additionalProperties:false 一致）；结构化细节编码进 locator（见 cross-reference-extraction.md §4）。
- `relation_type` MUST ∈ 调用方域词表（发现已保证交集；store 写入层兜底校验，越界整批拒绝）。
- 成对关系（如 references/referenced_by）MUST 同时产出两条边（各自 direction=out，共享 locator，去重键独立）。

## 3. 注册表发现语义（`GraphExtractorRegistry`）

```text
registry.discover(format: str, graph_relations: dict) -> list[GraphExtractor]
# 返回其 relation_pairs 键集与 graph_relations 词表键集有交集的提取器，按注册声明序；
# 空词表或无交集 → []（正常跳过，非失败，不产边不报错）。
# 同一输入 MUST 返回同一结果（确定性，宪法 VI）。

registry.inverse_relation_map() -> dict[str, str]
# 全部提取器 relation_pairs 的正反聚合；供反向遍历 CTE 与注册校验消费。
```

**发现调用序（ingestion 与 rebuild 统一）**：`scope_id → KnowledgeScope.domain_key → DomainProfile.graph_relations → discover(source.format, graph_relations)` → 对每个提取器（声明序）extract → 合并去重（唯一键 `(knowledge_scope_id, index_version, source_chunk_id, target_chunk_id, relation_type, direction, version)`，ON CONFLICT DO NOTHING）→ `store.write_edges(edges, scope, allowed_relation_types=词表键集)`。

## 4. 与 008 FormatHandlerRegistry 的关系（supersession）

- 本契约 **supersede** `format-handler-registry.md`（008）§1 的 `graph_extractor` 字段、§3 的 `graph_extractor(fmt)` 查询与 §4 的"图提取分派"行：图提取分派的单一事实源自 010 起为本注册表（format + 域词表双轴；008 钩子为单值 Callable，结构性无法表达多提取器与域轴）。
- FormatHandlerRegistry 仍是格式检测 / 解析分派 / 二进制声明三分发的单一事实源（008 契约其余部分不变）。
- 两个既有调用点（`ingestion_service.py:841`、`postgres_graph_store.py:225` rebuild）改经本注册表；004 行为等价由 SC-001 回归闸口实证。

## 5. 失败降级语义（沿用 004/008 既有模式）

- 提取器内部失败（解析异常等）MAY raise → orchestration catch（`ingestion_service.py:858-863` 同款）→ 记 `hard_degraded_reason = "<ExcType>: <msg>"` → 该知识源产 0 边 → **入库链继续**（不阻断发布、不伪造边，宪法 III）。
- 词表校验失败（提取器产出越界 relation_type）→ `write_edges` raise ValueError（列出越界值与合法集）→ 同上降级路径；fail-loud 使提取器声明 bug 显式暴露。
- 无匹配提取器 = 正常跳过（0 边、无 reason、无错误日志级别提升）。
- rebuild 路径同语义：失败降级、不阻断重建流程。

## 6. 查询侧消费（词表兼容，research R6）

- 反向遍历 CTE 的关系类型重标注 CASE 由 `inverse_relation_map()` 生成（新提取器新对自动生效）。
- 图扩展 `relation_types` 过滤经 SQL 数组参数绑定（`ANY(:rts)`），元素先过宽模式 pattern 校验（词表键可来自用户自定义档案）。
- `GraphExpansionEngine` 不再持硬编码默认关系集：`relation_types=None` → 不过滤（写侧词表校验已保证 scope 内类型合法；se-project scope 行为逐边等价，SC-001 实证）。
- `retrieval_pipeline.map_graph_params` 空/全非法方向回退 = 请求域词表全量（非 None：写侧词表校验只覆盖硬边写入，active 软关系经联合 CTE 参与扩展，None 回退会扩大其参与面、破坏与 004 的逐边等价，research R6.2）。
