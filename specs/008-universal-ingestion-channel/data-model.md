# Data Model: 008 通用摄入通道

**Branch**: `008-universal-ingestion-channel` | **Date**: 2026-09-06

本文描述 008 引入/修改的数据结构与数据库变更。既有实体（KnowledgeSource/Chunk/RetrievalRun/ProcessingRun/DomainProfile）仅列变更点。

## 1. FormatHandler 注册表条目（新增，内存态，非 DB）

注册表为进程内确定性结构（宪法 VI），不落库。每条目声明一个格式的完整摄入能力（FR-002）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `format` | str | 规范化格式名（如 `xlsx`、`markdown`） |
| `extensions` | tuple[str, ...] | 扩展名集（如 xlsx→`.xlsx`） |
| `tier` | enum | `native` 或 `converter` |
| `binary` | bool | 是否二进制（决定文本提取/直接转换路径） |
| `parser_factory` | Callable 或 None | native tier 的解析器工厂（冻结既有解析器） |
| `converter_spec` | ConverterSpec 或 None | converter tier 的转换器规格 |
| `graph_extractor` | Callable 或 None | 可选图提取器挂钩；None 则不参与图提取 |
| `locator_prefix` | enum | 证据定位前缀（sheet:/path:/msg:/#/page:/符号） |

**ConverterSpec**（converter tier）：
- `converter`：Converter 实例（MarkitdownConverter / YamlAdapter / 未来 pandoc/tika）。
- `chunk_slicer`：切片器（CSV 行窗口 / JSON 键路径 / 默认 MarkdownParser 通用切片）。
- `locator_prefix`：该格式定位前缀。

## 2. Converter 接口（新增）

```text
class Converter(Protocol):
    def convert(self, raw_bytes: bytes, format: str, filename: str) -> str:
        """任意通用格式原始字节 → Markdown 中间表示（IR）。"""
        ...
```

- `MarkitdownConverter`：包装 markitdown `MarkItDown.convert()`。
- `YamlAdapter`：pyyaml 解析 → dict → 复用 JSON 转换路径（markitdown 无原生 YAML 转换器）。
- `NoopConverter`：无挂钩占位（未来等价转换器替换预留）。

## 3. 转换层 chunk dict 契约（输出到 IngestionService）

转换层切片后产出 chunk dict，与既有解析器输出对齐（IngestionService 消费同一 schema）：

| 键 | 类型 | 说明 |
|----|------|------|
| `content_text` | str | 凭据脱敏后的 chunk 正文 |
| `position_path` | str | 定位标识（`sheet:Sheet1` / `path:/a/b` / `msg:Subject` / `# 标题`） |
| `chunk_type` | str | L1：section/heading/paragraph/list/table |
| `start_line` | int | 1-based 起行（转换后 IR 内） |
| `end_line` | int | 1-based 止行 |
| `token_count` | int | 估算 token 数 |
| `parent_position_path` | str 或 None | 父 chunk 定位（父子索引，FR-013） |

> IngestionService 现有逻辑以 `section_path`/`symbol_path`/`structure_path` 三键取 position_path；008 转换层可直接产出 `position_path` 键，或复用 `section_path`（`# 标题路径`）并在写入侧映射。实现阶段统一为单一 `position_path` 入口。

## 4. chunk_type 两级词表（FR-020/FR-021/FR-022）

| 层级 | 定义 | 值 |
|------|------|-----|
| L1 通用闭合集 | 转换层/通用切片产出 | `section` / `heading` / `paragraph` / `list` / `table` |
| L2 命名空间扩展 | 域档案声明 | `^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$`（如 `legal:article`） |
| 存量遗留 18 值 | 003 已交付，不迁移 | section/symbol/endpoint/schema/table/column/constraint/index/view/procedure/function/method/type/interface/class/heading/paragraph/list |

约束：
- 转换层格式 chunk_type 限定 L1 闭合集（FR-023），不引入 SE 专属类型。
- `table` 撞名（Word 表格 vs DDL 表）通过“格式 + 域档案”上下文消歧（FR-022）。
- 应用层校验：L1/L2 词表 + 域档案 `chunk_type_extensions`（FR-019）。

## 5. 数据库列变更（FR-018/FR-019）

| 表.列 | 现状 | 目标 | CHECK 变化 |
|-------|------|------|-----------|
| `knowledge_sources.format` | String(16)，8 值枚举 | String(32) | 宽模式 `'^[a-z][a-z0-9_]{0,31}$'` |
| `chunks.chunk_type` | String(16)，18 值枚举 | String(32) | 宽模式（L1 + L2 + 存量） |
| `retrieval_runs.format` | String(8)，8 值枚举 | String(32) | 宽模式 `'^[a-z][a-z0-9_]{0,31}$'` |

迁移：Alembic `0070_expand_format_and_chunk_type_wide.py`（down_revision=`0062`），沿用 a1b2c3d4e5f6 的 `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` + `ALTER COLUMN TYPE VARCHAR(32)` 模式。存量数据零迁移。

## 6. ProcessingRun stages 变更

转换层格式在 `stages` 有序列表中于 `parsing` 前插入：

```json
{"stage":"conversion","status":"completed","started_at":"...","completed_at":"...",
 "details":{"converter":"markitdown","format":"xlsx","input_bytes":12345}}
```

- 失败：任一阶段异常 → run/source 置 `failed`，语义与原生层一致。
- TXT 极轻量原生处理器不产生 `conversion` 阶段（走 `parsing`）。

## 7. 实体关系

```text
FormatHandlerRegistry (内存态) ──登记──> FormatHandler 条目 (17 条：8 native + 9 新)
FormatHandler 条目 ──tier=native──> 解析器工厂 (冻结 8 解析器 + TxtParser)
FormatHandler 条目 ──tier=converter──> ConverterSpec (MarkitdownConverter/YamlAdapter + 切片器)
FormatHandler 条目 ──graph_extractor──> 图提取器 (可选, None 则跳过)
Converter.convert → Markdown IR → credential_redactor → 切片器 → chunk dict → Chunk(1:1 Qdrant Point)
```

## 8. 关键不变式（对齐宪法）

- 凭据脱敏顺序不变：转文本之后、切片之前（FR-016）；脱敏规则扩展至新格式形态（FR-017）。
- Markdown IR 在脱敏前为不可信数据（宪法 V）。
- 跨域串库 = 0（FR-027）；无显式 scope 引用拒绝（FR-026）。
- 转换层格式检索仍复用既有 index_version 派生与 `dense_ready`/`lexical_ready` 能力（FR-031），Qdrant payload 结构不变。
