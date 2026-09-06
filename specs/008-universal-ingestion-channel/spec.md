# Feature Specification: 通用摄入通道（FormatHandler 注册表 + 转换层）

**Feature Branch**: `008-universal-ingestion-channel`

**Created**: 2026-09-06

**Status**: Draft

**Input**: User description: "通用摄入通道：FormatHandler 注册表收敛四处 if/elif 分发（api/knowledge_sources.py:305-351 _detect_format、services/ingestion_service.py:582-631 _parse_content、parsers/text_extractor.py:16 BINARY_FORMATS、ingestion_service.py:833-842 图提取器分发）为单一注册表（条目声明 format 名/扩展名集/tier native|converter/binary 声明/解析器工厂或转换器规格/可选图提取器挂钩/定位前缀，错误消息由注册表生成）；新增转换层：可插拔转换器接口 + markitdown 适配器（微软 markitdown，MIT），任意通用格式转 Markdown IR 后经凭据脱敏再由 MarkdownParser 切片（通用 chunk_type：heading/paragraph/list/table），原生 8 解析器冻结不动、存量格式零迁移；首批格式 9 种：html/txt/csv/json/yaml/xml/xlsx/pptx/eml（txt 为极轻量原生处理器空行分段，其余走转换层）；DB CHECK 放宽：knowledge_sources.format 与 chunks.chunk_type 与 retrieval_runs.format（String(8)→String(32)）改为宽模式约束 + 应用层注册表校验，chunk_type 两级词表（L1 通用闭合集 section/heading/paragraph/list/table + L2 命名空间扩展 ^域:类型$，存量 18 值遗留合法）；证据定位前缀规范（sheet:/path:/msg: 新增，存量 page:/标题路径/符号路径沿用）；前端 accept 与文案及 types 泛化。范围依据：2.0 蓝图 §1.2/§3.3/§3.4/§3.5/§5-008/ADR-4/ADR-5/ADR-6，1.0 蓝图 §7/§8。硬性约束：显式知识域引用；跨域串库为零；Schema 合法率与来源可定位率 100%（转换层格式的定位为转换后表示的标题路径粒度，须在契约中显式声明）；凭据脱敏顺序不变（转文本之后切片之前）；宪法 V 数据与控制分离对转换产物同样生效。对照评测：003 格式扩展范式沿用——每新格式 ≥2 条评测查询（≥1 自然语言 + ≥1 结构定位，如 sheet:SheetName/path:/json/key）加入固定评测集；003 既有格式集无回归；转换层契约测试固化 markitdown 行为（版本锁定）。不重复 003 已交付的 8 格式原生解析。输入材料：001–007 代码、docs/通用RAG演进蓝图.md、markitdown 官方文档。"

**Scope Basis**: 2.0 蓝图《通用RAG演进蓝图.md》§1.2（2.0 核心主张：检索质量自研、解析广度外包；原生 8 解析器冻结、新格式默认走转换层）、§3.3（两层摄入架构与 FormatHandler 注册表：条目字段、四处分发收敛、凭据脱敏顺序、转换层证据定位语义=转换后标题路径）、§3.4（chunk_type 两级词表：L1 通用闭合集 + L2 命名空间扩展 + 存量 18 值遗留合法）、§3.5（证据定位前缀规范：sheet:/path:/msg: 新增、存量沿用）、§5-008（文件级变更清单：registry.py/converter.py/txt_parser.py、三模型 CHECK 放宽、markitdown 依赖、前端泛化）、ADR-4（转换层优先 + 原生冻结 + 新格式默认转换层）、ADR-5（FormatHandler 注册表收敛 4 处 if/elif）、ADR-6（两级 chunk_type 词表 + 存量 18 值不迁移）；1.0 蓝图 §7（格式切片规则）与 §8（检索与证据可定位）。支撑：宪法 v1.3.0（原则 I 显式知识域引用、IV 可定位证据、V 数据与控制分离、VIII 版本不混用、X 评测驱动、XI 领域中立；五硬约束跨域语义版）。

## Clarifications

### Session 2026-09-06

- Q: markitdown 转换器应作为核心依赖还是可选 extra 安装，且转换器依赖缺失时上传应如何表现？ → A: 核心依赖（仅锁 9 格式所需 extras，非 `[all]`）；转换器不可用时在格式检测/上传阶段拒收该格式（fail fast，注册表错误消息）。
- Q: CSV 大文件应如何切片以满足单 chunk 的 token 上限，且空数据集（0 行）应失败还是允许空源？ → A: 按行窗口切片（每 50 行一个 table chunk，超长再自然边界二次切分）；空数据集沿用"无 Chunk 则失败"（拒收）。
- Q: 通用 `.json`/`.yaml` 格式与 OpenAPI 文档的判定顺序应如何确定？ → A: 内容嗅探优先（检测 `openapi`/`swagger` 版本字段），命中走 openapi native，未命中回落通用 json/yaml 转换层。
- Q: 通用 `json`/`yaml`/`xml` 文件应切片到何种粒度？ → A: 顶层键作为标题路径切片（`path:/key`），嵌套键作为更深路径（`path:/a/b/c`），超长叶子值在自然边界二次切分。
- Q: `.eml` 邮件应走 markitdown 还是另写 Python 标准库 email 专用适配器，附件/内联如何处理？ → A: 走 markitdown EmailConverter（`.eml` 内部即 stdlib `email`）；附件/内联图片忽略，仅保留头部字段名 + 正文，`msg:` 定位前缀取 Subject。
- Q: 对于没有"工作表"概念的 CSV 文件，`sheet:` 定位前缀中的 sheet 名应解析为什么？ → A: 使用文件名（不含扩展名）作为 sheet 名，如 `report.csv` → `sheet:report`（xlsx 仍用真实工作表名）。
- Q: TXT 空行分段后，超长段落（两个空行之间）超过 token 上限时如何处理？ → A: 沿用 512–1024 Token 目标，超长段落按自然边界（句子/换行）二次切分。
- Q: 转换层格式是否设文件大小上限，超限如何表现？ → A: 统一上限（默认 20MB，可配置），超限在检测/上传阶段拒收（fail fast，注册表错误消息）。
- Q: 现有冻结的 001 脱敏规则若无法识别转换层新格式凭据形态，008 如何保证 SC-007？ → A: 008 扩展脱敏规则覆盖新格式形态（EML 头、JSON/YAML/CSV 值），顺序不变，并更新"范围外"条款。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 单一 FormatHandler 注册表收敛四处格式分发 (Priority: P1)

系统维护者与摄取流水线不再面对四处各自为政的 if/elif 格式分发（格式检测、解析分派、二进制声明、图提取器分派）。所有格式的能力（名称、扩展名、tier、二进制属性、解析/转换规格、图提取器挂钩、定位前缀）在单一注册表中声明，四处分发点全部委托注册表；错误消息由注册表统一生成。已交付的原生 8 解析器冻结不动，存量格式与数据零迁移。

**Why this priority**: 这是整个通用摄入通道的地基。只有四处分发收敛为单一事实源，"新增格式边际成本 ≤ 2 个文件、不再出现格式税"（蓝图 §1.3 目标 2）才成立，后续转换层与 DB 放宽都建立在其上。同时它本身可独立验证：存量 8 格式经注册表路径行为与 1.0 完全一致，即零迁移无回归。

**Independent Test**: 以存量 8 格式（markdown/java/openapi/ddl/go/python/word/pdf）各上传一份，验证其格式检测、解析切片、二进制提取、图提取器分派与错误消息均经注册表产生且结果与 1.0 一致；随后在注册表中登记一个新条目（不触碰任何 if/elif 代码），验证四处分发点均能通过该条目解析该格式。

**Acceptance Scenarios**:

1. **Given** 一份存量格式（如 Java）文件上传，**When** 摄取流水线做格式检测/解析/图提取器分派，**Then** 四处分发均委托注册表条目，产出与 1.0 相同的 Chunk 结构、来源位置与图关系，无行为回归。
2. **Given** 注册表新增一个格式条目（声明格式名/扩展名/tier/解析器或转换器规格/定位前缀），**When** 该格式文件上传，**Then** 系统仅凭该条目即可完成检测、解析与定位，无需修改任何 if/elif 分发代码。
3. **Given** 上传一个不受支持的格式或未识别扩展名，**When** 系统检测格式，**Then** 系统返回由注册表生成的错误消息，其中列出可接受格式清单，且该消息与任何其他入口的错误文案一致（单一事实源）。
4. **Given** 一个二进制格式（如 xlsx），**When** 摄取流水线判断是否需要文本提取，**Then** 系统依据注册表条目的 binary 声明决定提取路径，不再依赖散落的 `BINARY_FORMATS` 常量。

---

### User Story 2 - 转换层摄入首批 9 种通用格式 (Priority: P1)

用户上传 HTML、TXT、CSV、JSON、YAML、XML、XLSX、PPTX、EML 九种通用文档格式，系统通过可插拔转换层（markitdown 适配器）将其转为 Markdown 中间表示，经凭据脱敏后由已交付的 MarkdownParser 切分为通用结构单元（heading/paragraph/list/table），随后可被检索且证据可定位。TXT 走极轻量原生处理器（空行分段，chunk_type=paragraph），其余八种走转换层。

**Why this priority**: 这是 2.0 蓝图 §1.3 目标 3 的直接用户价值——首批通用格式全部"可上传、可切片、可检索、证据可定位"。转换层让系统以商品能力覆盖 Office/网页/表格/邮件等通用格式，把工程投入留给检索增强质量（蓝图 §1.2）。

**Independent Test**: 逐一上传九种格式的样例文件，验证每种格式经"转换/处理 → 凭据脱敏 → MarkdownParser 切片 → 嵌入"后产生通用 chunk_type 的 Chunk，且能通过自然语言与结构定位查询检索到、证据携带来源版本与可定位位置。

**Acceptance Scenarios**:

1. **Given** 一份 XLSX 工作簿（含多 Sheet），**When** 系统转换并切片，**Then** 系统产出标题路径定位（如 `# Sheet1`）下的表格/段落 Chunk，Agent 可用 `sheet:SheetName` 结构定位检索到对应内容及其来源版本。
2. **Given** 一份 JSON/YAML/XML 结构化文件，**When** 系统转换并切片，**Then** 系统产出 `path:/json/key` 形态的定位标识，Agent 可按路径定位检索到对应字段内容。
3. **Given** 一份 EML 邮件，**When** 系统转换并切片，**Then** 系统产出 `msg:Subject` 定位标识（如 `# Inbox > Re: 合同评审`），邮件主题与正文可检索。
4. **Given** 一份 TXT 纯文本文件，**When** 系统处理，**Then** 系统按空行分段产出 `paragraph` chunk_type 的 Chunk，不经过转换器（极轻量原生路径）。
5. **Given** 一份 HTML/CSV 文件，**When** 系统转换并切片，**Then** 系统产出 heading/paragraph/list/table 通用 chunk_type 的 Chunk，证据可定位。

---

### User Story 3 - DB 枚举约束放宽为宽模式 + 应用层校验 (Priority: P2)

数据库层的 `knowledge_sources.format`、`chunks.chunk_type`、`retrieval_runs.format` 三列不再用枚举 CHECK 硬编码格式/类型清单，改为宽模式约束 + 应用层注册表校验；列宽放宽到 String(32) 以容纳更长格式名与命名空间 chunk_type。chunk_type 采用两级词表（L1 通用闭合集 + L2 命名空间扩展），存量 18 个值作为合法遗留值原样保留、不迁移。

**Why this priority**: 不放宽 DB 枚举约束，新格式与新 chunk_type 每次都要"迁移 + 改 CHECK"，这正是蓝图 §1.3 目标 2 要消灭的"格式税"。但它是使能性改造，本身不产生新的用户可见格式能力，故列 P2。

**Independent Test**: 在放宽后的库上写入一个转换层格式（如 xlsx）的 knowledge_source 行与 chunk_type 为新 L2 值（如 `legal:article`）的 chunk 行，验证不触发 DB 约束错误；同时验证应用层会拒绝一个注册表未登记或词表未声明的非法值。

**Acceptance Scenarios**:

1. **Given** 一个转换层格式（如 xlsx），**When** 系统写入 `knowledge_sources.format='xlsx'`，**Then** 该值不再被 DB 枚举约束拒绝（宽模式通过），且应用层注册表确认其为合法格式。
2. **Given** 一个 L2 命名空间 chunk_type（如 `legal:article`），**When** 系统写入 `chunks.chunk_type`，**Then** 宽模式约束通过，应用层按当前 scope 域档案的 chunk_type_extensions 校验通过。
3. **Given** 一个注册表未登记或词表未声明的非法值，**When** 系统写入，**Then** 应用层校验拒绝并给出明确错误，DB 不再承担枚举兜底。
4. **Given** 存量 18 个 chunk_type 值（如 `symbol`、`endpoint`、`table`），**When** 系统读写，**Then** 全部作为合法遗留值原样保留，无数据迁移、无行为变化。

---

### User Story 4 - 证据定位前缀规范落地 (Priority: P2)

证据的来源位置标识采用统一前缀约定：新增 `sheet:`、`path:`、`msg:` 三种前缀，存量 `page:`、`# 标题路径`、符号路径沿用。转换层格式的定位粒度统一为"转换后表示的标题路径"，在契约中显式声明，不做原文档锚点还原。

**Why this priority**: 定位前缀是可定位证据（宪法 IV 硬约束）的契约基础，也是评测集结构定位查询（`sheet:`/`path:`）可判定的依据。它依赖注册表与转换层先就位（故 P2），但直接决定 100% 来源可定位率能否成立。

**Independent Test**: 对每种新格式构造一条携带其定位前缀的证据，验证位置标识符合规范表、可解析到确定的知识源版本与内容位置，并验证契约 schema 对前缀的描述已更新。

**Acceptance Scenarios**:

1. **Given** 一份 XLSX/CSV 证据，**When** 返回来源位置，**Then** 位置标识为 `sheet:SheetName` 形态（xlsx 为工作表名、csv 为文件基名），可定位到具体工作表/文件。
2. **Given** 一份 JSON/YAML/XML 证据，**When** 返回来源位置，**Then** 位置标识为 `path:/json/key` 形态，可定位到具体字段路径。
3. **Given** 一份 EML 证据，**When** 返回来源位置，**Then** 位置标识为 `msg:Subject` 形态，可定位到具体邮件。
4. **Given** 存量 markdown/word/pdf/java/go/python 证据，**When** 返回来源位置，**Then** 其 `# 标题路径`/`page:N`/符号路径定位格式不变（存量沿用，无回归）。

---

### User Story 5 - 前端上传接受与类型泛化 (Priority: P3)

管理端上传入口的 accept 列表、提示文案与前端类型定义从"两格式时代"泛化到全格式，使用户能通过浏览器上传并看到新格式的处理状态。

**Why this priority**: 前端是摄入通道的用户入口，但不做前端泛化后端仍可通过 API 摄入，且它不改变检索质量，故列 P3。

**Independent Test**: 在浏览器上传界面选择九种新格式文件，验证文件选择器 accept 与文案已覆盖新扩展名，上传后列表正确显示格式字段与处理状态。

**Acceptance Scenarios**:

1. **Given** 用户打开上传界面，**When** 点击上传，**Then** 文件选择器接受 html/txt/csv/json/yaml/xml/xlsx/pptx/eml 扩展名，提示文案列出这些格式。
2. **Given** 一个转换层格式来源，**When** 前端渲染来源列表，**Then** 格式字段显示正确格式名（不再局限于 markdown/java）。

---

### Edge Cases

- 上传文件扩展名与实际内容不匹配（如 `.csv` 内为 HTML）时，系统必须检测到不匹配并报告失败，不得静默按扩展名错误转换（沿用 003 等价约束）。
- 转换器（markitdown）对某格式转换失败或产出空 Markdown IR 时，系统必须报告失败并说明原因，不产生空 Chunk（沿用 001/003 "无 Chunk 则失败"）。
- 转换层格式包含凭据值（如 JSON 中的 API Key、YAML 中的密码、EML 邮件头凭据）时，凭据值必须在"转文本之后、切片之前"被类型化占位符替换，字段名与结构保留，且转换产物在脱敏前被视为不可信数据（宪法 V）。
- 转换器升级导致 Markdown IR 结构漂移时，转换层契约测试必须捕获差异，阻止静默回归（版本锁定 + 行为固化）。
- 新格式 Chunk 与存量原生格式 Chunk 共存于同一知识版本时，各格式 Chunk 必须保留各自的来源位置标识格式，不互相混淆。
- `table` chunk_type 在 Word 表格与 DDL 表之间撞名时，必须通过"格式 + 域档案"上下文消歧，不在数据层面产生歧义。
- 某格式在图提取器注册表无挂钩时，该格式不得进入图提取分派（不产生图关系，也不误报图能力）。
- 扩展名对应多个格式（如 `.json` 既是通用 JSON 也可能是 OpenAPI）时，按内容嗅探优先判定：命中 OpenAPI 特征走 openapi，未命中按通用 json 处理（判定顺序由注册表显式声明）。
- CSV 空数据集（0 数据行或仅表头无数据行）时，沿用"无 Chunk 则失败"，不发布包含零数据行 table Chunk 的版本。
- `.eml` 邮件含附件（二进制或内联图片）时，附件必须忽略、不进入索引；仅头部字段名与正文可检索（附件是二进制不可信数据，宪法 V）。
- 上传/转换文件超过大小上限（默认 20MB，可配置）时，系统必须在检测/上传阶段拒收并给出注册表错误消息（fail fast），不得进入转换。

## Requirements *(mandatory)*

### Functional Requirements

**FormatHandler 注册表（单一分发点）**

- **FR-001**: 系统 MUST 提供单一 FormatHandler 注册表，作为格式分发唯一事实源，收敛四处 if/elif 分发点：格式检测（`_detect_format`）、解析分派（`_parse_content`）、二进制声明（`BINARY_FORMATS`）、图提取器分派。新增/修改格式只改注册表，不再出现散落的分发代码。
- **FR-002**: 注册表条目 MUST 至少声明：format 名、扩展名集、tier（`native` | `converter`）、binary 声明（是否二进制）、解析器工厂（native tier）或转换器规格（converter tier）、可选图提取器挂钩、定位前缀。
- **FR-003**: 格式检测 MUST 委托注册表按扩展名（并可选内容嗅探）判定 `format` 字段值，检测到不受支持格式时 MUST 拒绝处理并说明原因（沿用 001 FR-004 等价约束）。对 `.json`/`.yaml`/`.yml`，MUST 先内容嗅探 OpenAPI 特征（`openapi`/`swagger` 版本字段）——命中归为 `openapi`（走 native），未命中回落为通用 `json`/`yaml`（走转换层）；判定顺序由注册表显式声明，不得依赖隐式优先级。converter-tier 格式的转换器适配器不可用（依赖缺失或导入失败）时，系统 MUST 在检测/上传阶段拒收该格式（fail fast），并给出注册表生成的错误消息。
- **FR-004**: 解析/切片分派 MUST 委托注册表条目：native tier 走冻结的解析器工厂，converter tier 走转换器规格 → Markdown IR → MarkdownParser。
- **FR-005**: 二进制声明 MUST 由注册表条目提供（取代 `BINARY_FORMATS` 常量），二进制文本提取分派同样委托注册表。
- **FR-006**: 图提取器分派 MUST 委托注册表条目的可选图提取器挂钩；无挂钩的格式不参与图提取。
- **FR-007**: 不支持格式与未识别扩展名的错误消息 MUST 由注册表统一生成（含可接受格式清单），消除各处手抄文案漂移。
- **FR-008**: 原生 8 解析器（markdown/java/openapi/ddl/go/python/word/pdf）MUST 冻结不动、以注册表条目登记，存量格式行为与存量数据零迁移（不重复 003 已交付的 8 格式原生解析）。

**转换层（可插拔转换器 + markitdown）**

- **FR-009**: 系统 MUST 提供可插拔转换器接口（任意通用格式 → Markdown 中间表示），主选 markitdown 适配器（微软 markitdown，MIT），并允许以等价转换器（如 pandoc/tika）替换。
- **FR-010**: 首批格式 MUST 为 9 种：html、txt、csv、json、yaml、xml、xlsx、pptx、eml。其中 txt 走极轻量原生处理器（空行分段，chunk_type=paragraph，不进转换器；超长段落按自然边界二次切分，长度目标同 FR-012）；其余 8 种走转换层。eml MUST 走 markitdown 的 EmailConverter（`.eml` 内部即 Python 标准库 `email`），附件（含内联图片）默认忽略、不进入索引，仅保留邮件头字段名（From/To/Subject/Date）与正文。
- **FR-011**: 转换产物（Markdown IR）MUST 复用已交付并验证的 MarkdownParser 做结构切片，通用 chunk_type 为 `heading`/`paragraph`/`list`/`table`（`section` 作文档级父上下文，沿用 003 粒度约定）。CSV 大文件 MUST 按行窗口切片（每 50 行一个 `table` chunk，定位到 `sheet:<文件基名>` + 行区间（CSV 无工作表名，以文件基名充当 sheet 名）），超长窗口在自然边界二次切分。通用 `json`/`yaml`/`xml` MUST 按键路径切片：顶层键作为标题路径（`path:/key`），嵌套键作为更深路径（`path:/a/b/c`），超长叶子值在自然边界二次切分。
- **FR-012**: 转换层格式与 TXT 原生处理器的 Chunk MUST 控制目标长度在约 512–1024 Token，超长结构单元在自然边界二次切分（沿用 003 FR-007）。
- **FR-013**: 转换层格式的 Chunk MUST 建立父子索引，子 Chunk 用于精确召回、父 Chunk 用于恢复结构上下文（沿用 003 FR-008）。
- **FR-014**: markitdown MUST 作为核心依赖引入（仅锁定 9 格式所需 extras，不装 `[all]`）并锁定版本；其转换行为 MUST 由转换层契约测试固化，防版本漂移（蓝图 §8 风险缓解）。
- **FR-015**: 转换器对无法解析、损坏、无可提取文本或超过大小上限（默认 20MB，可配置）的文件 MUST 报告失败并说明原因，不产生空 Chunk 或伪造内容（沿用 001/003 失败保护）；超限文件在检测/上传阶段即拒收（fail fast，注册表错误消息）。

**凭据脱敏顺序（跨两层一致）**

- **FR-016**: 凭据脱敏顺序 MUST 保持不变：转换层格式在"转文本（转换/提取）之后、切片之前"执行凭据脱敏；native 层保持既有顺序；两层一致（宪法 V 不变）。
- **FR-017**: 宪法 V 数据与控制分离 MUST 对转换产物同样生效：转换产物（Markdown IR）在脱敏前视为不可信数据，不得控制提示词、工具选择、权限、能力门控或状态机；凭据值 MUST 替换为类型化占位符（`<api-key>`/`<password>`/`<token>`/`<secret>`），字段名、结构、来源位置保留可检索；凭据识别规则 MUST 扩展以覆盖转换层新格式形态（EML 头字段、JSON/YAML/CSV 值），替换顺序不变（FR-016）。

**DB 枚举约束放宽与两级 chunk_type 词表**

- **FR-018**: `knowledge_sources.format`、`chunks.chunk_type`、`retrieval_runs.format` 三列的枚举 CHECK 约束 MUST 放宽为宽模式约束（pattern），列宽 MUST 放宽到 `String(32)`（`format` 自 8/16 加宽、`chunk_type` 自 16 加宽），并配套迁移脚本。
- **FR-019**: 放宽后的合法性 MUST 由应用层注册表校验：`format` 由 FormatHandler 注册表校验，`chunk_type` 由 L1/L2 词表 + 域档案 `chunk_type_extensions` 校验，不再依赖 DB 枚举兜底。
- **FR-020**: chunk_type 词表 MUST 采用两级：L1 通用闭合集 `section`/`heading`/`paragraph`/`list`/`table`；L2 命名空间扩展 `^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$`（由域档案声明）。
- **FR-021**: 存量 18 个 chunk_type 值（`section`/`symbol`/`endpoint`/`schema`/`table`/`column`/`constraint`/`index`/`view`/`procedure`/`function`/`method`/`type`/`interface`/`class`/`heading`/`paragraph`/`list`）MUST 作为合法遗留值原样保留，不做数据迁移；SE 专属类型在 se-project 档案下继续使用。
- **FR-022**: `table` 撞名（Word 表格 vs DDL 表）MUST 通过"格式 + 域档案"上下文消歧并在文档中显式记录。
- **FR-023**: 转换层格式产出的 chunk_type MUST 限定在 L1 闭合集（`heading`/`paragraph`/`list`/`table`/`section`），不引入 SE 专属类型。

**证据定位前缀规范**

- **FR-024**: 证据定位前缀规范 MUST 落地：新增 `sheet:SheetName`（xlsx=真实工作表名；csv=文件基名，如 `report.csv`→`sheet:report`）、`path:/json/key`（json/yaml/xml）、`msg:Subject`（eml）；存量 `# 标题路径`（markdown/word/转换层）、`page:N [§ 路径]`（pdf）、全限定符号路径（java/go/python）沿用不变。
- **FR-025**: 转换层格式的来源定位语义 MUST 为"转换后表示的标题路径"粒度（如 `# Sheet1`、`# Inbox > Re: 合同评审`），与 Word 粒度一致，满足宪法 IV 人可定位要求；该定位粒度 MUST 在契约中显式声明，不做原文档锚点还原（docx 段 ID、PDF 坐标等）。

**作用域与硬约束继承**

- **FR-026**: 转换层格式的检索 MUST 继承显式知识域引用要求（`project_scope` 或 `domain_scope` 至少一个非空），缺少显式引用 MUST 被拒绝，不得回退全库（宪法 I）。
- **FR-027**: 转换层格式的检索 MUST 保证跨知识域串库为零：其 Chunk、Dense/Sparse 召回、融合与 Rerank 结果均不含作用域外知识域的 Chunk（宪法硬约束）。
- **FR-028**: 转换层格式的 Tool 响应 MUST 100% 通过 `search_knowledge` 与 `get_evidence` 输出 Schema 校验（宪法硬约束）。
- **FR-029**: 转换层格式返回的每条证据 MUST 携带来源 ID、版本与可定位位置（按 FR-024/FR-025 定位语义），来源可定位率在验收测试集中为 100%（宪法硬约束）。

**版本与重建**

- **FR-030**: 转换层格式的派生索引（Dense 向量 + Sparse/BM25 词法索引）MUST 可自原始知识源与版本信息重建（沿用 001/002/003 重建能力）。
- **FR-031**: 转换层格式发布的知识版本 MUST 声明与既有格式相同的 `dense_ready`/`lexical_ready` 能力，不引入新能力标志；格式支持是知识源属性、不是版本能力属性（沿用 003 FR-022）。

**前端泛化**

- **FR-032**: 前端上传 accept 列表与提示文案 MUST 泛化至首批 9 格式的扩展名（html/txt/csv/json/yaml/xml/xlsx/pptx/eml），替换硬编码的 11 扩展名列表。
- **FR-033**: 前端类型定义的 `format` 联合类型 MUST 泛化至全格式，不再停留在 `'markdown' | 'java'` 两格式时代。

**对照评测与契约测试**

- **FR-034**: 每种新格式 MUST 在固定评测集新增 ≥ 2 条查询（≥ 1 条自然语言 + ≥ 1 条结构定位，如 `sheet:SheetName`、`path:/json/key`），沿用 003 的 AI 生成、人工审核、JSON 格式约定（003 FR-024 范式）。
- **FR-035**: 003 既有 8 格式评测集 MUST 无回归：在既有固定集上重跑，非劣判定沿用 003 口径（Recall@K 精确、MRR/nDCG 1% 相对容差）。
- **FR-036**: 转换层契约测试 MUST 固化 markitdown 行为（版本锁定），记录给定输入下 Markdown IR 结构、切片 chunk_type 与定位标识的期望输出。
- **FR-037**: 在包含存量 8 格式 + 新 9 格式的混合评测集上 MUST 验证硬指标三件套：跨域串库 = 0、Schema 合法率 = 100%、来源可定位率 = 100%。
- **FR-038**: 本 Feature MUST NOT 重复 003 已交付的 8 格式原生解析：不重写 markdown/java/openapi/ddl/go/python/word/pdf 解析器，仅以注册表登记并新增转换层与 9 种新格式。

### Key Entities *(include if feature involves data)*

- **FormatHandler 注册表条目（FormatHandler Registry Entry）**: 描述一个格式的完整摄入能力，包含 format 名、扩展名集、tier、binary 声明、解析器工厂或转换器规格、可选图提取器挂钩、定位前缀。是格式分发的唯一事实源。
- **转换器（Converter）/ 转换器适配器（Converter Adapter）**: 可插拔组件，将一种通用格式的原始内容转换为 Markdown 中间表示；markitdown 适配器为主选实现，接口允许等价转换器替换。
- **Markdown 中间表示（Markdown IR）**: 转换层产物，在凭据脱敏前为不可信数据；经脱敏后交由 MarkdownParser 切分为通用 chunk_type 结构单元。
- **转换层 Chunk（Converter Chunk）**: 自转换产物产生的检索单元，携带 L1 通用 chunk_type 与"转换后标题路径"定位标识，保留父子上下文。
- **证据定位前缀（Source Locator Prefix）**: 来源位置标识的统一前缀约定（`sheet:`/`path:`/`msg:` 新增，`page:`/标题路径/符号路径沿用），是可定位证据的契约基础。
- **chunk_type 两级词表（Two-Level Chunk-Type Vocabulary）**: L1 通用闭合集（section/heading/paragraph/list/table）与 L2 命名空间扩展（`^域:类型$`，由域档案声明）的组合，叠加存量 18 值作为合法遗留值。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 首批 9 种格式（html/txt/csv/json/yaml/xml/xlsx/pptx/eml）均可通过浏览器或 API 上传，并看到完整处理状态与正确的格式字段（沿用 003 SC-001 可用性）。
- **SC-002**: 存量 8 格式经注册表路径的格式检测、解析切片、二进制提取、图提取器分派行为与 1.0 逐项一致（既有 1509 项测试通过、003 格式集无回归），证明零迁移成立。
- **SC-003**: 新增格式查询（每种 ≥ 2 条，共 ≥ 18 条）在固定评测集上产生 Recall@K、MRR、nDCG 指标，并与基线对照记录；首轮记录指标数值，不预设通过阈值（沿用 003 "首轮记录基线"策略）。
- **SC-004**: 在包含存量 8 格式 + 新 9 格式的混合评测集上，跨知识域串库事件数为零。
- **SC-005**: 在混合评测集上，所有 Tool 成功响应 100% 通过 `search_knowledge` 与 `get_evidence` 输出 Schema 校验。
- **SC-006**: 在混合评测集上，所有返回证据 100% 可定位到确定的知识源版本与内容位置（转换层格式为转换后标题路径粒度）。
- **SC-007**: 转换层格式材料中包含的测试凭据值不会出现在检索索引或 MCP 证据正文，配置字段名与结构仍可检索（凭据安全，沿用 001/003 SC-007）。
- **SC-008**: 新增一个通用格式的边际成本 ≤ 2 个文件（注册表条目 + 可选小适配器），不再出现"4 处 if/elif + 3 个 DB CHECK + 1 次迁移"的格式税（蓝图 §1.3 目标 2）。
- **SC-009**: 转换层契约测试锁定 markitdown 版本后，同版本下重复运行结果在容差内一致；转换器升级须先通过契约测试方可采纳（行为固化）。

## 范围内 / 范围外

### 范围内（008）

- FormatHandler 注册表（单一分发点）收敛四处 if/elif 分发，错误消息由注册表生成。
- 原生 8 解析器冻结并以注册表条目登记，存量格式零迁移。
- 可插拔转换器接口 + markitdown 适配器（核心依赖、非 `[all]`、版本锁定）；Markdown IR → 凭据脱敏 → MarkdownParser 通用切片。
- 首批 9 格式：html/txt/csv/json/yaml/xml/xlsx/pptx/eml（txt 走极轻量原生处理器，其余走转换层）。
- `knowledge_sources.format`/`chunks.chunk_type`/`retrieval_runs.format` 三列 CHECK 放宽为宽模式 + 列宽 String(32) + 迁移；应用层注册表校验。
- chunk_type 两级词表（L1 闭合集 + L2 命名空间扩展），存量 18 值遗留合法。
- 证据定位前缀规范落地（`sheet:`/`path:`/`msg:` 新增，存量沿用），转换层定位粒度在契约中显式声明。
- 前端 accept/文案/types 泛化。
- 对照评测：每新格式 ≥ 2 条查询 + 003 回归 + 转换层契约测试 + 硬指标三件套。

### 范围外（不重复既有 Feature，且不属于 008）

- markdown/java/openapi/ddl/go/python/word/pdf 原生解析器（001/003 已交付；008 仅登记，不重写）。
- 凭据规范化核心逻辑（001 已实现；008 复用其顺序与类型化占位符机制，并扩展识别规则以覆盖转换层新格式凭据形态：EML 头字段、JSON/YAML/CSV 值等）。
- Dense 嵌入、Sparse/BM25、RRF 融合与 Rerank 检索路径（001/002 已实现；008 复用）。
- MCP `search_knowledge`/`get_evidence` 对外契约结构（001/007 已确立；008 仅新增定位前缀语义并在契约描述中声明，不改契约结构）。
- 图关系注册表与提取器插件化（蓝图 §3.8，属 Feature 010）；008 仅将图提取器分派收敛到 FormatHandler 注册表的可选挂钩，不抽象 GraphExtractor 插件接口。
- `relation_type` 枚举放宽（`graph/models.py:45-49`，属 Feature 010）。
- 检索编排域中立化（query_planner/relation_directions/task_context，属 Feature 009）。
- 两个验证域语料与域基线报告（属 Feature 011）。
- 原文档锚点定位（docx 段 ID、PDF 坐标还原）、OCR 通道、原生解析器替换评估（蓝图 §9 触发条件，均不在本 Feature）。

## Assumptions

- 原生 8 格式的完整清单为 markdown/java/openapi/ddl/go/python/word/pdf（与 003 交付一致），008 以注册表条目登记、冻结不改。
- 首批 9 格式的扩展名集按业界默认：html→`.html`/`.htm`，txt→`.txt`，csv→`.csv`，json→`.json`，yaml→`.yaml`/`.yml`，xml→`.xml`，xlsx→`.xlsx`，pptx→`.pptx`，eml→`.eml`；具体扩展名映射在 plan/research 阶段精确定义。
- `.json`/`.yaml`/`.yml` 同时可能是 OpenAPI 文档；判定顺序已定：先内容嗅探 OpenAPI 特征（`openapi`/`swagger` 版本字段），命中走 openapi native，未命中回落通用 json/yaml 转换层。
- markitdown 作为转换层主选适配器以**核心依赖**引入（仅锁 9 格式所需 extras，非 `[all]`）并锁定版本；可插拔转换器接口允许未来以 pandoc/tika 替换，替换行为由契约测试把关。转换器依赖缺失时在检测/上传阶段拒收该格式（fail fast）。
- 转换层格式的定位粒度为"转换后标题路径"，与 Word 一致；不做原文档锚点还原，此约束已在契约中显式声明。
- 转换层 chunk_type 限定 L1 闭合集（section/heading/paragraph/list/table）；L2 命名空间扩展由域档案 `chunk_type_extensions` 声明，本 Feature 提供机制、不预设具体域扩展值。
- 存量 18 个 chunk_type 值作为合法遗留值保留，不做数据迁移；`table` 撞名通过"格式 + 域档案"消歧并文档化。
- 三列宽放宽到 `String(32)`：`retrieval_runs.format` 自 String(8)、`knowledge_sources.format` 与 `chunks.chunk_type` 自 String(16) 加宽；具体迁移策略在 plan/data-model 阶段精确定义。
- 对照评测沿用 003 范式与既有固定集（`eval/eval_dataset.json`）；新增查询遵循 AI 生成、人工审核、JSON 格式约定，原条目保留以保证与基线逐条可比。
- 008 面向单用户、本机部署环境；并发隔离沿用 001/002 的请求级隔离，不引入多实例或分布式协调。
- 服务端总超时沿用 30s 护栏（蓝图 §19）；转换层引入的转换耗时纳入该护栏评估，超时行为在 plan 阶段明确。
- 上传大小上限默认 20MB、可配置（环境变量/常量）；超限在检测/上传阶段拒收（fail fast）。具体配置方式在 plan 阶段精确定义。
