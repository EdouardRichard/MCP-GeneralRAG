# Contract: 证据定位前缀规范（source_position）

**Branch**: `008-universal-ingestion-channel` | **Date**: 2026-09-06

本契约定义 008 证据 `source_position` 的定位前缀规范，对齐 FR-024/FR-025 与 003 既有 `format-locators.schema.json` 模式。MCP `get_evidence` 返回的每条证据 MUST 携带符合本表模式的 `source_position`。

## 1. 定位前缀全表

| 格式 | tier | 定位前缀 | 正则（source_position） | 示例 |
|------|------|----------|--------------------------|------|
| markdown | native | `# 标题路径` | `^#.*$（标题层级）` | `# 安装 > ## 配置` |
| word | native | `# 标题路径` | `^#.*$（标题层级）` | `# 1. 概述` |
| pdf | native | `page:N [§ 路径]` | `^page:\d+( \[§.*\])?$` | `page:3 § 2.1` |
| java/go/python | native | 全限定符号路径 | 003 既有符号路径模式 | `com.example.Foo#bar()` |
| openapi | native | 结构路径 | 003 既有 endpoint/schema 模式 | `GET /pets` |
| ddl | native | 结构路径 | 003 既有 table/column 模式 | `schema.table` |
| html | converter | `# 标题路径` | `^#.*$（标题层级）` | `# 季度报告 > ## 销售明细` |
| txt | native(轻量) | 文档级（行区间） | 空 section_path（filename + start/end_line 定位） | （空） |
| csv | converter | `sheet:<文件基名>` | `^sheet:[A-Za-z0-9_\-]+$` | `sheet:report` |
| json | converter | `path:/key/sub` | `^path:/.*$（键路径）` | `path:/service/host` |
| yaml | converter | `path:/key/sub` | `^path:/.*$（键路径）` | `path:/service/host` |
| xml | converter | `path:/elem/sub` | `^path:/.*$（元素路径）` | `path:/root/item/name` |
| xlsx | converter | `sheet:<工作表名>` | `^sheet:.+$` | `sheet:Sheet1` |
| pptx | converter | `# 标题路径` | `^#.*$（幻灯片标题）` | `# Slide 1` |
| eml | converter | `msg:<Subject>` | `^msg:.+$` | `msg:Re: 合同评审` |

## 2. 新增前缀语义（FR-024）

- `sheet:` —— xlsx 用**真实工作表名**；csv 用**文件基名**（澄清 Q1：`report.csv` → `sheet:report`）。
- `path:` —— json/yaml/xml 用**键/元素路径**（顶层键 `path:/key`，嵌套 `path:/a/b/c`）。
- `msg:` —— eml 用**邮件 Subject**（`msg:Subject`）。
- 存量 `# 标题路径`（markdown/word/转换层 html/pptx）、`page:N`（pdf）、全限定符号路径（java/go/python）沿用不变。

## 3. 转换层定位粒度（FR-025）

- 转换层格式定位粒度统一为**转换后表示的标题路径**，与 Word 一致，满足宪法 IV 人可定位要求。
- **不做原文档锚点还原**（docx 段 ID、PDF 坐标、Excel 单元格坐标等）。
- 该粒度 MUST 在 MCP 契约 `source_position` 描述中显式声明。

## 4. chunk dict 定位键映射

转换层切片器产出 chunk dict，IngestionService 写入 `Chunk.position_path`（String(1024)）与 Qdrant payload `position_path`：

```text
# 转换层 chunk dict 定位键（与既有 section_path/symbol_path/structure_path 对齐）
{
  "content_text": "...",
  "position_path": "sheet:Sheet1",   # 或 "path:/a/b" | "msg:Subject" | "# 标题"
  "chunk_type": "table",
  "start_line": 1, "end_line": 50,
  "token_count": 512,
  "parent_position_path": "# Sheet1"  # 父子索引（FR-013）
}
```

- 实现阶段统一以单一 `position_path` 键进入写入侧，`# 标题路径` 格式可复用 `section_path` 键并在写入侧映射（见 data-model.md §3）。

## 5. 评测结构定位查询（FR-034）

每种新格式的结构定位查询示例（加入固定评测集）：

| 格式 | 结构定位查询示例 |
|------|------------------|
| xlsx | `sheet:Sheet1` |
| csv | `sheet:report` |
| json | `path:/service/host` |
| yaml | `path:/services/db` |
| xml | `path:/root/item` |
| eml | `msg:Re: 合同评审` |
| html/pptx | `# 标题` 结构定位 |
| txt | 自然语言（无结构前缀） |
