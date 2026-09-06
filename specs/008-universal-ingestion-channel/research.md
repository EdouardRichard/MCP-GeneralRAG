# Research: 008 通用摄入通道（FormatHandler 注册表 + 转换层）

**Branch**: `008-universal-ingestion-channel` | **Date**: 2026-09-06

本文解决 Technical Context 与 spec 中的所有 NEEDS CLARIFICATION，并为 Phase 1 设计（data-model.md / contracts/ / quickstart.md）提供依据。每条结论以 **Decision / Rationale / Alternatives** 形式固化。

## 0. 决策汇总

| # | 决策点 | 结论 |
|---|--------|------|
| D1 | 转换器依赖 | `markitdown[xlsx,pptx]` 核心依赖（非 `[all]`），版本锁定 |
| D2 | YAML 无原生 markitdown 转换器 | 008 提供薄 YAML→JSON 等价适配器（复用 pyyaml + JSON 转换路径） |
| D3 | 转换器接口 | 可插拔 `Converter` 协议 + markitdown 适配器 + pandoc/tika 替换预留 |
| D4 | 注册表布局 | `parsers/registry.py` + `parsers/converter.py` + `parsers/txt_parser.py` |
| D5 | 分发改造顺序 | 注册表→检测→解析→二进制→图提取；注册表初始化失败 = 启动失败 |
| D6 | DB 宽模式 | 三列 String(32) + 宽模式 CHECK（pattern），沿用 drop/add 模式 |
| D7 | 定位前缀 | sheet:/path:/msg: 新增，# 标题路径/page:N/符号路径沿用 |
| D8 | CSV/JSON 切片 | CSV 50 行窗口；JSON/YAML/XML 顶层键路径切片 |
| D9 | 边界语义 | 转换失败/空产物/超限文件 fail-fast 拒收，无 Chunk 则失败 |

---

## 1. markitdown 版本锁定与可插拔转换器接口（D1/D2/D3）

### Decision
- **依赖形态**：`markitdown[xlsx,pptx]` 作为核心运行时依赖加入 `backend/pyproject.toml`，并**锁定具体版本**（pin 到 `==` 精确版本，实现阶段解析当前稳定版本并写入 `deps_baseline.txt`）。
- **extras 选择**：仅 9 格式所需 —— `xlsx`（依赖 pandas + openpyxl）与 `pptx`（依赖 python-pptx）。html/txt/csv/json/xml/eml 由 markitdown **基础包**覆盖（beautifulsoup4 + markdownify + defusedxml + charset-normalizer + magika + requests），无需额外 extras。**不装 `[all]`**（`[all]` 会拉入 pdf/pdfplumber、docx/mammoth、音视频转录、Azure Document Intelligence 等无关依赖，违反 FR-014 与宪法 VIII 依赖最小化）。
- **YAML 例外**：markitdown **没有原生 YAML 转换器**。008 在转换层内提供薄 **YAML 适配器**：用已存在的 `pyyaml` 将 YAML 解析为 Python 字典，再喂给 markitdown 的 JSON 转换路径（或直接产出与 JSON 一致的结构化 Markdown IR），使 YAML 与 JSON 共享 `path:/key` 定位与切片语义。
- **接口形态**：定义 `Converter` 协议（见 contracts/format-handler-registry.md）：`convert(raw_bytes, format, filename) -> str`（返回 Markdown IR）。主实现 `MarkitdownConverter` 包装 markitdown 的 `MarkItDown.convert()`；接口允许以**等价转换器**（pandoc、tika 等）替换，替换行为由契约测试（FR-036）把关。
- **版本漂移防护**：转换层契约测试（FR-036）对每种格式录制“给定输入 → 期望 Markdown IR / chunk_type / 定位标识”，锁定 markitdown 版本；升级须先通过契约测试（SC-009）。
- **许可证修正**：spec 输入将 markitdown 记为 “Apache-2.0”，实际 markitdown 许可证为 **MIT**。实现阶段应核实并更正文档标注（MIT 比 Apache-2.0 更宽松，不影响采用）。

### Rationale
markitdown 将“解析广度外包”（2.0 蓝图 §1.2），以商品能力覆盖 Office/网页/表格/邮件，把工程投入留给检索增强质量；锁定版本 + 契约测试使转换行为可复现，避免依赖升级造成 Markdown IR 结构漂移。

### Alternatives considered
- **`[all]` extras**：引入无关重依赖，违反依赖最小化与宪法 VIII，拒绝。
- **自研每格式解析器**：重复 003 已冻结的原生解析投入，违背 ADR-4（转换层优先），拒绝。
- **pandoc/tika 为主实现**：需外部二进制 + 更多平台假设，拒绝为主选（保留为可替换备选）。

---

## 2. markitdown 各格式输出形态（每格式样例附录）

> 以下为**期望输出形态**（依据 markitdown 各 converter 实现约定）。精确字节级输出由**转换层契约测试（FR-036）在实现阶段录制固化**。样例仅示意“转换后 Markdown IR”结构，供切片与定位设计参考。

### 2.1 HTML（HtmlConverter）
输入 `report.html`（含 h1/h2/ul/table）→ Markdown IR：
```markdown
# 季度报告
正文段落……

## 销售明细
- 华东
- 华南

| 产品 | 数量 |
| --- | --- |
| A | 100 |
```
- 切片：heading/paragraph/list/table；定位：`# 季度报告 > ## 销售明细`。

### 2.2 TXT（极轻量原生处理器，不走 markitdown）
输入 `notes.txt`（空行分段）→ 直接按空行切段：
```text
第一段内容……

第二段内容……
```
- 切片：paragraph（空行分段）；定位：文档级（无标题，section_path 为空，靠 filename + 行区间定位）。

### 2.3 CSV（CsvConverter）
输入 `report.csv`：
```csv
name,amount
alpha,10
beta,20
```
→ Markdown IR（pipe 表格）：
```markdown
| name | amount |
| --- | --- |
| alpha | 10 |
| beta | 20 |
```
- 切片：每 50 行一个 table chunk；定位：`sheet:report` + 行区间。

### 2.4 JSON（JsonConverter）
输入 `config.json` → Markdown IR（结构化 JSON 文本，实现阶段确认是否包 code fence）：
```text
{
  "service": { "host": "x", "port": 1 },
  "users": [ ... ]
}
```
- 切片：顶层键作为标题路径（`path:/service`、`path:/users`），嵌套键更深路径；定位：`path:/...`。

### 2.5 YAML（008 薄适配器，等价 JSON 路径）
输入 `config.yaml`：
```yaml
service:
  host: x
  port: 1
```
→ 经 YAML→dict→JSON 等价 Markdown IR（与 2.4 同构）。切片/定位与 JSON 一致。

### 2.6 XML（XmlConverter）
输入 `catalog.xml` → Markdown IR（元素/文本序列化，实现阶段确认形态）。切片：元素路径；定位：`path:/root/item/name`。

### 2.7 XLSX（XlsxConverter，需 [xlsx]）
输入 `book.xlsx`（多 Sheet）→ Markdown IR：
```markdown
# Sheet1

| 列1 | 列2 |
| --- | --- |
| ... |
```
- 切片：table；定位：`sheet:Sheet1`（真实工作表名）+ 行区间。

### 2.8 PPTX（PptxConverter，需 [pptx]）
输入 `deck.pptx`（多幻灯片）→ Markdown IR：
```markdown
# Slide 1

标题/正文……

# Slide 2

……
```
- 切片：heading/paragraph/list；定位：`# Slide 1`（幻灯片标题路径）。

### 2.9 EML（EmailConverter，内部 stdlib email）
输入 `msg.eml` → Markdown IR（头部字段 + 正文）：
```markdown
# Inbox > Re: 合同评审
From: a@example.com
To: b@example.com
Subject: Re: 合同评审

正文……
```
- 切片：heading/paragraph；定位：`msg:Re: 合同评审`（取 Subject）；附件/内联图片忽略。

---

## 3. 定位前缀规范全表（D7）

| 格式 | tier | 定位前缀 | 定位粒度 | 示例（position_path） |
|------|------|----------|----------|------------------------|
| markdown | native | `# 标题路径` | 标题层级 | `# 安装 > ## 配置` |
| word | native | `# 标题路径` | 标题层级 | `# 1. 概述` |
| pdf | native | `page:N [§ 路径]` | 页 + 段落 | `page:3 § 2.1` |
| java | native | 全限定符号路径 | 符号 | `com.example.Foo#bar()` |
| go | native | 全限定符号路径 | 符号 | `mypkg.Func` |
| python | native | 全限定符号路径 | 符号 | `module.Class.method` |
| openapi | native | 结构路径 | endpoint/schema | `GET /pets` |
| ddl | native | 结构路径 | table/column | `schema.table` |
| html | converter | `# 标题路径` | 转换后标题 | `# 季度报告 > ## 销售明细` |
| txt | native(轻量) | 文档级（行区间） | 段落 | （section_path 空，靠 filename + start/end_line） |
| csv | converter | `sheet:<文件基名>` | 表 + 行区间 | `sheet:report` |
| json | converter | `path:/key/sub` | 键路径 | `path:/service/host` |
| yaml | converter | `path:/key/sub` | 键路径 | `path:/service/host` |
| xml | converter | `path:/elem/sub` | 元素路径 | `path:/root/item/name` |
| xlsx | converter | `sheet:<工作表名>` | 工作表 + 标题 | `sheet:Sheet1` |
| pptx | converter | `# 标题路径` | 幻灯片标题 | `# Slide 1` |
| eml | converter | `msg:<Subject>` | 邮件主题 | `msg:Re: 合同评审` |

**规则**：
- 新增前缀 `sheet:`（xlsx/csv）、`path:`（json/yaml/xml）、`msg:`（eml）；存量 `# 标题路径`、`page:N`、符号路径沿用不变（FR-024）。
- 转换层定位粒度统一为**转换后表示的标题路径**（FR-025），不做原文档锚点还原（docx 段 ID、PDF 坐标等）。
- CSV 无工作表概念，以**文件基名**充当 sheet 名（澄清 Q1：`report.csv` → `sheet:report`）；xlsx 用真实工作表名。
- 定位前缀规范须在 MCP 契约 `source_position` 描述中显式声明（FR-024/FR-025）。

---

## 4. CSV/JSON/XML 切片粒度决策（D8）

### Decision
- **CSV**：按**行窗口**切片，**每 50 行一个 `table` chunk**，定位 `sheet:<文件基名>` + 行区间；超长窗口在自然边界二次切分（FR-011 + 澄清 Q2）。空数据集沿用“无 Chunk 则失败”拒收。
- **JSON/YAML/XML**：按**键/元素路径**切片。顶层键作为标题路径（`path:/key`），嵌套键作为更深路径（`path:/a/b/c`）；超长叶子值在自然边界二次切分（FR-011 + 澄清 Q4）。
- **TXT**：空行分段，`chunk_type=paragraph`；超长段落沿用 512–1024 Token 目标、按自然边界（句子/换行）二次切分（澄清 Q3，FR-012 覆盖 TXT）。
- **通用 chunk_type**：转换层一律产出 L1 闭合集 `section`/`heading`/`paragraph`/`list`/`table`（FR-023），`section` 作文档级父上下文。
- **长度目标**：转换层与 TXT 的 Chunk 目标 512–1024 Token，超长二次切分（FR-012）。

### Rationale
按行窗口/键路径切片既满足单 chunk token 上限，又保留可定位结构（行区间/键路径），支撑 `sheet:`/`path:` 结构定位评测查询（FR-034）。

### Alternatives considered
- **按字符固定窗口**：丢失表头/键语义，定位粒度退化，拒绝。
- **整文件单 chunk**：超大 CSV/JSON 超 token 上限，拒绝。

---

## 5. 转换失败/空产物/超限文件边界语义（D9）

### Decision
统一采用 **fail-fast + “无 Chunk 则失败”** 语义，与 001/003 一致：

| 边界情形 | 行为 |
|----------|------|
| 转换器依赖缺失/导入失败 | 检测/上传阶段拒收该格式（fail fast），注册表生成错误消息（FR-003） |
| 转换失败（损坏/无法解析/无可提取文本） | 报告失败并说明原因，不产生空 Chunk、不伪造内容（FR-015） |
| 转换产出空 Markdown IR | 报告失败（“无 Chunk 则失败”），不发布空版本 |
| 文件超过大小上限（默认 20MB） | 检测/上传阶段拒收（fail fast，注册表错误消息），不进入转换（澄清 Q3/FR-015） |
| 扩展名/内容不匹配 | 检测到不匹配并报告失败，不按扩展名静默错误转换 |
| CSV 空数据集 | 沿用“无 Chunk 则失败”拒收 |
| EML 附件/内联图片 | 忽略、不进入索引，仅头部字段名 + 正文（附件为不可信二进制，宪法 V） |
| 转换超时（30s 护栏内） | 超时行为在实现阶段明确，纳入护栏评估 |

### Rationale
fail-fast 避免把损坏/超大/空内容带入索引，保护 30s 护栏与检索质量；“无 Chunk 则失败”是 001/003 既有不变式，转换层必须延续。

### Alternatives considered
- **空产物静默跳过**：会隐藏上游错误，违反“暴露不确定性”（宪法 III），拒绝。
- **超限文件继续处理**：拖垮护栏，拒绝（澄清 Q3 选 fail-fast）。

---

## 6. 注册表模块布局（D4）

### Decision
- `backend/src/rag_mcp/parsers/registry.py`：`FormatHandler` 条目 dataclass + `FormatHandlerRegistry` 单例 + 四类查询 API（`detect_format`/`parse_content`/`is_binary`/`graph_extractor`）+ 统一错误消息生成。
- `backend/src/rag_mcp/parsers/converter.py`：`Converter` 协议 + `MarkitdownConverter` + `YamlAdapter`（YAML→JSON 等价）+ `NoopConverter`。
- `backend/src/rag_mcp/parsers/txt_parser.py`：`TxtParser`（空行分段、chunk_type=paragraph、自然边界二次切分）。
- 条目字段（对齐 FR-002）：format 名、扩展名集、tier（`native`|`converter`）、binary 声明、解析器工厂（native）或转换器规格（converter）、可选图提取器挂钩、定位前缀。
- 原生 8 解析器仅以**条目登记**（指向既有冻结工厂），不改动解析器实现（FR-008）。

### Rationale
注册表作为解析器模块的单一事实源，与既有 `parsers/` 同层；`txt_parser.py` 与 converter 并列，语义清晰。

### Alternatives considered
- **注册表放 `services/`**：解析关注点与编排耦合，拒绝。
- **每个格式独立模块文件**：9 个新格式拆散，边际成本上升，拒绝。

---

## 7. 四处分发点委托化改造顺序与回退安全（D5）

### Decision
改造顺序（每步可独立验证、可回退）：

1. **新增注册表**（registry.py + converter.py + txt_parser.py），登记原生 8 格式 + 新 9 格式。
2. **格式检测委托**：`api/knowledge_sources.py::_detect_format` → 注册表 `detect_format`（含 OpenAPI 内容嗅探优先、converter 依赖缺失 fail-fast）。
3. **解析分派委托**：`ingestion_service.py::_parse_content` → 注册表 `parse_content`。
4. **二进制声明委托**：`text_extractor.py::BINARY_FORMATS` → 注册表 `is_binary`。
5. **图提取分派委托**：`ingestion_service.py::_extract_graph_relations` → 注册表 `graph_extractor`（无挂钩格式不参与图提取）。

**回退安全**：
- 注册表**初始化失败 = 启动失败**（在应用/服务启动时构建注册表，导入或构建异常直接抛出，**不静默回落**到旧的 if/elif）。
- 每一步改造后，存量 8 格式行为与 1.0 逐项一致（SC-002），任一回归即回退该步。
- 注册表是纯内存确定性结构，无外部副作用；委托点仅替换查找逻辑，不改调用方其余流程。

### Rationale
“注册表初始化失败 = 启动失败”保证单一事实源不会被静默绕过（宪法 VI）；分步改造使每处委托可独立测试、可独立回退。

### Alternatives considered
- **一次性全量替换**：回归面大、定位难，拒绝。
- **注册表失败静默回落旧 if/elif**：引入双事实源，违反 FR-001 单一事实源，拒绝。

---

## 8. 宽模式 CHECK 迁移脚本（D6）

### Decision
- 新增 Alembic 迁移 `backend/alembic/versions/0073_expand_format_and_chunk_type_wide.py`（down_revision 指向 0072，当前迁移链 head；0070–0072 已被 Feature 007 占用），**沿用 a1b2c3d4e5f6 的 drop/add 模式**：
  - `knowledge_sources.format`：`String(16)→String(32)`，CHECK 由 8 值枚举 → 宽模式（pattern，如 `format ~ '^[a-z][a-z0-9_]{0,31}$'`）。
  - `chunks.chunk_type`：`String(16)→String(32)`，CHECK 由 18 值枚举 → 宽模式（覆盖 L1 5 值 + L2 `^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$` + 存量 18 值）。
  - `retrieval_runs.format`：`String(8)→String(32)`，CHECK `chk_retrieval_run_format` 由 8 值枚举 → 宽模式。
- **应用层校验接管**（FR-019）：`format` 由 FormatHandler 注册表校验；`chunk_type` 由 L1/L2 词表 + 域档案 `chunk_type_extensions` 校验；DB 不再做枚举兜底。
- 迁移须**向后兼容**：存量 `markdown`/`java`/… 与 18 个 chunk_type 值在新宽模式下仍合法，**零数据迁移**。
- 用 `ALTER TABLE ... ALTER COLUMN ... TYPE VARCHAR(32)` 扩列 + `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` 宽模式（参照 a1b2c3d4e5f6 风格）。

### Rationale
宽模式 + 应用层校验消灭“新格式/新 chunk_type 每次都要迁移 + 改 CHECK”的格式税（蓝图 §1.3 目标 2）；drop/add 模式已被 a1b2c3d4e5f6 验证，可复现、可回滚。

### Alternatives considered
- **继续扩展枚举 CHECK**：每加格式都要迁移，正是要消灭的格式税，拒绝。
- **完全移除 CHECK**：失去 DB 层最小合法性护栏，拒绝（保留宽模式 pattern 作兜底）。

---

## 9. retrieval_runs.format String(32) 扩容（D6 延伸）

### Decision
- `retrieval_runs.format` 自 `String(8)` 扩为 `String(32)`，CHECK `chk_retrieval_run_format` 自 8 值枚举改为宽模式（`format IS NULL OR format ~ '^[a-z][a-z0-9_]{0,31}$'`）。
- 该列语义不变：top-1 evidence 命中的格式（内部审计，不进入 MCP 契约），新增 xlsx/pptx/eml 等格式名。
- ORM 模型 `retrieval_run.py` 的 `format` 字段同步改 `String(32)` 与宽模式 CheckConstraint。
- 既有单测 `test_retrieval_run_format.py` 扩展：新增 xlsx/pptx/eml 等格式名参数化用例，验证宽模式通过、非法值被拒绝。

### Rationale
与 knowledge_sources.format / chunks.chunk_type 一起统一到 String(32)，避免三列宽度不一致造成未来再迁移。

### Alternatives considered
- **仅扩到 String(16)**：L2 chunk_type 命名空间可达 32 字符，为一致性统一到 32，拒绝 16。

---

## 10. Qdrant payload 兼容性（chunk_type 值域放宽）

### Decision
- **Qdrant payload 结构不变**：继续包含 `knowledge_scope_id`/`source_id`/`version_id`/`chunk_id`/`chunk_type`/`position_path`/`start_line`/`end_line`/`index_version`/`embedding_model`（见 ingestion_service.py payload 构造）。
- `chunk_type` 值域放宽（新增 L2 命名空间值）**不改变 payload 字段类型**（仍为字符串），Qdrant 无 schema 约束，**天然兼容**。
- `position_path` 承载 `sheet:`/`path:`/`msg:` 新前缀，仍是字符串（String(1024)），无 schema 变更。
- 唯一需验证点：**写入侧契约测试**确认新格式 chunk 的 payload 与既有 chunk 结构一致（字段名/类型不变），读取侧过滤不受影响。

### Rationale
Qdrant 是无 schema 向量库，payload 为自由 JSON；放宽 chunk_type 值域与新增定位前缀均不触及 payload 结构，无需迁移。写入侧契约测试兜底防回归。

### Alternatives considered
- **新增 payload 字段**：无必要，拒绝（定位信息已由 position_path 承载）。

---

## 11. ProcessingRun 阶段记录与失败重试语义

### Decision
- 转换层在 `ProcessingRun.stages`（JSONB 有序列表）中新增/复用阶段：
  - 既有阶段：`text_extraction` → `credential_scan` → `parsing` → `chunking` → `embedding` → `sparse_index` → `graph_relations`。
  - 转换层格式：在 `parsing` 前插入 `conversion` 阶段（`{"stage":"conversion","status":"completed","details":{"converter":"markitdown","format":"xlsx"}}`）；TXT 原生处理器仍走 `parsing`。
  - 每阶段记录 started_at/completed_at/status/details，与既有格式一致。
- **失败语义与原生层一致**：任一阶段异常 → `ProcessingRun.status='failed'` + `error_message` + 记录到失败为止的 stages，同时 `KnowledgeSource.status='failed'` + `processing_error`；事务逻辑沿用 `_run_pipeline` 现有 except 分支。
- **重试语义**：用户触发 reprocess（`run_type='retry'`）与原生层一致，重新走完整流水线（含转换），旧版本保持 published 直到新版本发布成功（FR-009）。

### Rationale
转换层不引入新的状态机或失败语义，复用 ProcessingRun stages 既有机制，保证 SSE 反馈与可审计性一致。

### Alternatives considered
- **独立转换状态机**：重复 001/003 机制，违反“同步结果优先”与最小改动，拒绝。

---

## 12. 域档案 supported_formats 更新

### Decision
- `backend/src/rag_mcp/config/domain_profiles.py` 中两个内置档案的 `supported_formats` 更新：
  - `generic` 档案：`markdown/word/pdf/html/txt` → 增补 `csv/json/yaml/xml/xlsx/pptx/eml`（通用格式全集）。
  - `se-project` 档案：保持 8 格式（SE 专属）不变（本 Feature 提供机制，默认仅 generic 档案开放 9 新格式）。
- `chunk_type_extensions` 仍为 `None`（本 Feature 提供 L2 机制，不预设具体域扩展值）。

### Rationale
域档案的 `supported_formats` 是应用层格式校验的一环（与注册表校验叠加）；更新 generic 档案使通用格式在对应域可摄入，保持宪法 XI 领域中立。

### Alternatives considered
- **不改域档案**：新格式无法通过域层校验，拒绝。

---

## 13. deps_baseline 更新与依赖治理

### Decision
- 更新 `backend/tests/fixtures/deps_baseline.txt`：加入 `markitdown`（以及基础依赖 beautifulsoup4/markdownify/magika/defusedxml/charset-normalizer/requests 与 extras pandas/openpyxl/python-pptx 中实际加入运行时依赖集的部分）。
- `test_deps_unchanged.py` 的基线快照随 008 重新录制（markitdown 是 FR-014 授权的核心依赖，非“未授权新增依赖”）。
- 该测试的“no graph-specific deps”断言保持不变。

### Rationale
依赖快照防漂移；markitdown 是 spec 明确授权的核心依赖，须更新快照而非绕过测试。

### Alternatives considered
- **绕过测试**：违反依赖治理，拒绝。

---

## 14. 未决/留待实现阶段确认项

- markitdown **精确锁定版本号**：实现阶段解析当前稳定版本并 pin（`==`），写入 pyproject.toml + deps_baseline.txt。
- markitdown 各格式**字节级输出形态**：由契约测试（FR-036）用真实样例录制固化（第 2 节为期望形态）。
- **JSON/XML 是否包 code fence**：实现阶段以真实转换产物为准，契约测试锁定。
- **TXT 定位粒度**（文档级空 section_path 是否需 `# <文件名>` 兜底）：实现阶段结合 100% 可定位约束定稿。
- **超时具体行为**（30s 护栏内转换超时的错误码/文案）：实现阶段明确（spec Assumptions 已标注）。