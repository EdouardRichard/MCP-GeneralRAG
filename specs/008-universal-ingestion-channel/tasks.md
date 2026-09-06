---
description: "Task list for feature implementation: 通用摄入通道（FormatHandler 注册表 + 转换层）"
---

# Tasks: 通用摄入通道（FormatHandler 注册表 + 转换层）

**Input**: Design documents from specs/008-universal-ingestion-channel/

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: 本特性显式要求测试先行——Phase 1 行为等价测试先行（存量 8 格式零迁移无回归）、Phase 2 转换层契约测试（markitdown 版本锁定）、Phase 4 每格式解析测试 + ≥2 评测查询。故各阶段均包含测试任务，且相关实现任务的测试先写并期望 FAIL 后再落地实现。

## 说明

任务按用户指定的五阶段组织（注册表基座 → 转换层基座 → DB 约束放宽 → 首批格式落地 → 前端与验收），与 spec 的 5 个用户故事映射如下：

| Phase | 用户故事 | 内容 |
|-------|----------|------|
| Phase 1 | US1 (P1) | 单一 FormatHandler 注册表收敛四处 if/elif 分发 + 错误消息重构 |
| Phase 2 | US2 (P1, 基座) | 可插拔转换器接口 + markitdown 适配器 + 脱敏顺序接线 + 契约测试 |
| Phase 3 | US3 (P2) | DB 枚举约束放宽为宽模式 + String(32) + 存量 18 值遗留合法 |
| Phase 4 | US2 + US4 (P1/P2) | 首批 9 格式按风险低→高分批落地 + 定位前缀落地 |
| Phase 5 | US5 (P3) + 验收 | 前端 accept/types/文案泛化 + 003 回归 + 硬指标 + quickstart |

**实现修正提示**：plan.md 与 research.md 将宽模式迁移记为 0070_expand_format_and_chunk_type_wide.py（down_revision=0062），但该编号已被 Feature 007 占用，当前迁移链 head 为 0072_drop_graph_project_id.py。本任务清单统一采用 0073_expand_format_and_chunk_type_wide.py（down_revision=0072）。

**许可证修正提示**：spec 输入将 markitdown 记为 "Apache-2.0"，research §1 已指出实际为 MIT；实现阶段应核实并更正文档标注（收尾任务 T049）。

---

## Phase 1: 注册表基座（FormatHandler + 四处分发点收敛 + 错误消息重构）— US1

**Purpose**: 建立单一 FormatHandler 注册表作为格式分发唯一事实源，收敛四处 if/elif 分发点（格式检测 _detect_format、解析分派 _parse_content、二进制声明 BINARY_FORMATS、图提取分派），错误消息由注册表统一生成。原生 8 解析器冻结不动、以条目登记。行为等价测试先行，确保存量 8 格式零迁移无回归（SC-002）。

**Independent Test**: 以存量 8 格式（markdown/java/openapi/ddl/go/python/word/pdf）各上传一份，验证格式检测、解析切片、二进制提取、图提取器分派均经注册表产生且结果与 1.0 一致；随后仅登记一个新条目（不触碰任何 if/elif），验证四处分发点均能通过该条目解析该格式。

### 行为等价测试（先行，期望 FAIL）

- [x] T001 [P] [US1] 为存量 8 格式编写行为等价测试于 backend/tests/unit/test_parsers/test_registry.py：断言 registry.detect_format/is_binary/graph_extractor/parse_content 对 markdown/java/openapi/ddl/go/python/word/pdf 的判定与 1.0 逐项一致（格式名、扩展名、tier、binary 布尔值、图挂钩存在性、解析工厂产出等价 chunk）。先写测试，期望在注册表实现前 FAIL。

### 注册表实现

- [x] T002 [US1] 创建 FormatHandler 不可变 dataclass（字段 format/extensions/tier/binary/parser_factory/converter_spec/graph_extractor/locator_prefix）+ LocatorPrefix 枚举（sheet/path/msg/heading/page/symbol）+ ConverterSpec dataclass + RegistryFormatError 异常于 backend/src/rag_mcp/parsers/registry.py（对齐 contracts/format-handler-registry.md §1/§2 与 data-model.md §1）。

- [x] T003 [US1] 实现 FormatHandlerRegistry.build() 类方法（构建失败/重复 format/重复扩展名/导入错误 MUST 抛异常）+ detect_format/parse_content/is_binary/graph_extractor 四个查询 API + 统一错误消息生成（RegistryFormatError 含可接受格式清单）于 backend/src/rag_mcp/parsers/registry.py；登记原生 8 格式条目（markdown/java/openapi/ddl/go/python/word/pdf），parser_factory 指向既有冻结解析器工厂，不改动解析器实现（FR-008）。构建后使 T001 行为等价测试转绿。

### 四处分发点收敛

- [x] T004 [US1] 将 backend/src/rag_mcp/api/knowledge_sources.py 中 _detect_format（约 305 行）委托 registry.detect_format；对 .json/.yaml/.yml 先内容嗅探 OpenAPI 特征（openapi/swagger 版本字段）命中归 openapi、未命中回落通用 json/yaml，判定顺序由注册表显式声明（FR-003）。

- [x] T005 [US1] 将 backend/src/rag_mcp/services/ingestion_service.py 中 _parse_content（约 582 行）委托 registry.parse_content，native tier 走冻结解析器工厂（FR-004）。

- [x] T006 [US1] 将 backend/src/rag_mcp/parsers/text_extractor.py 中 BINARY_FORMATS 常量（约 16 行，frozenset({"word","pdf"})）替换为 registry.is_binary；_run_pipeline 中 "if source.format in BINARY_FORMATS" 判断改为 "if registry.is_binary(source.format)"（FR-005）。

- [x] T007 [US1] 将 backend/src/rag_mcp/services/ingestion_service.py 中 _extract_graph_relations（约 786 行）的图提取分派委托 registry.graph_extractor；无挂钩格式不参与图提取（FR-006）。

- [x] T008 [US1] 在应用/服务启动时执行一次 registry.build()，构建失败即启动失败（不静默回落旧 if/elif）；将不支持格式/未识别扩展名的错误消息改为由注册表统一生成（含可接受格式清单），消除各入口手抄文案漂移（FR-001/FR-007，contracts/format-handler-registry.md §5/§6）。

### 回归验证

- [x] T009 [US1] 回归验证：既有 backend/tests/integration/test_format_expansion.py 与 backend/tests/contract/test_format_locators.py 全绿，存量 8 格式经注册表路径行为与 1.0 逐项一致（SC-002 零迁移成立）。

**Checkpoint**: 注册表成为唯一分发事实源，存量 8 格式零迁移无回归；四处分发点全部委托注册表，错误消息单一事实源成立。

---

## Phase 2: 转换层基座（转换器接口 + markitdown 适配器 + 脱敏顺序接线 + 契约测试）— US2 基座

**Purpose**: 提供可插拔 Converter 接口与 markitdown 适配器（核心依赖、非 [all]、版本锁定），接线"转文本之后、切片之前"的凭据脱敏顺序，并以转换层契约测试固化 markitdown 行为。

**Independent Test**: 对任一 converter tier 格式喂入样例，验证 MarkitdownConverter.convert 产出 Markdown IR → redact_credentials 脱敏 → MarkdownParser 切片，chunk_type 限定 L1 闭合集；契约测试在同版本下重复运行结果一致。

- [x] T010 [P] [US2] 在 backend/pyproject.toml 新增核心依赖 markitdown[xlsx,pptx] 并以 == 锁定精确版本（非 [all]，仅 xlsx/pptx 两个 extras）；更新 backend/tests/fixtures/deps_baseline.txt 与 backend/tests/unit/test_deps_unchanged.py 的基线快照（markitdown 为 FR-014 授权核心依赖，非未授权新增；保持 "no graph-specific deps" 断言不变）。

- [x] T011 [US2] 定义 Converter 协议（convert(raw_bytes, format, filename) -> str，失败/空产物 MUST 抛异常携带原因）+ MarkitdownConverter（包装 markitdown MarkItDown.convert()）+ NoopConverter（占位，供 pandoc/tika 等价替换预留）于 backend/src/rag_mcp/parsers/converter.py（FR-009，contracts/format-handler-registry.md §2）。依赖 T010。

- [x] T012 [US2] 实现 YamlAdapter（pyyaml 解析 → dict → 复用 JSON 转换路径，因 markitdown 无原生 YAML 转换器）于 backend/src/rag_mcp/parsers/converter.py（research §2.5）。依赖 T011。

- [x] T013 [US2] 转换层契约测试于 backend/tests/unit/test_parsers/test_converter.py：为 html/csv/json/xml/xlsx/pptx/eml 各录制"给定输入 → 期望 Markdown IR 结构 / chunk_type / 定位标识"，锁定 markitdown 版本行为（FR-036/SC-009）；样例 fixture 置于 backend/tests/fixtures/samples/。依赖 T011/T012。

- [x] T014 [P] [US2] 扩展 backend/src/rag_mcp/parsers/credential_redactor.py 识别规则以覆盖转换层新格式凭据形态（EML 头字段 From/To/Subject 中的凭据、JSON/YAML 值中的 api_key/password/token、CSV 单元格值）；扩展 backend/tests/unit/test_parsers/test_credential_redaction_new_formats.py 断言凭据值被类型化占位符替换、字段名与结构保留（FR-017）。

- [x] T015 [US2] 接线脱敏顺序（FR-016/FR-017）：在 backend/src/rag_mcp/services/ingestion_service.py 的 _run_pipeline 中，将"转文本"步骤改为委托注册表——converter tier 走 registry 转换（markitdown convert → Markdown IR），native 二进制走 extract_text，native 文本走 UTF-8 解码；随后保持现有 redact_credentials 调用顺序（转文本之后、切片之前），再经 registry.parse_content 对 converter tier 走 MarkdownParser 通用切片；在 ProcessingRun.stages 中 converter tier 于 parsing 前插入 conversion 阶段（details 含 converter/format/input_bytes，data-model.md §6）。Markdown IR 在脱敏前视为不可信数据（宪法 V）。

- [x] T016 [US2] 实现转换层护栏：统一文件大小上限（默认 20MB、可配置，环境变量/常量）在检测/上传阶段拒收（fail fast、注册表错误消息）；converter 依赖不可用/导入失败时在检测/上传阶段拒收该格式并给出 converter unavailable 消息（FR-003/FR-015，research §5）。

**Checkpoint**: 转换层基座就绪——converter 接口 + markitdown 适配器 + 脱敏顺序接线 + 契约测试均落地，尚未登记具体 9 格式条目。

---

## Phase 3: DB 约束放宽迁移（宽模式 + String(32) + 存量 18 值遗留合法）— US3

**Purpose**: 将 knowledge_sources.format / chunks.chunk_type / retrieval_runs.format 三列枚举 CHECK 放宽为宽模式约束 + 应用层注册表校验，列宽放宽到 String(32)；chunk_type 采用两级词表；存量 18 值作为合法遗留值原样保留、零迁移。

**Independent Test**: 在放宽后的库上写入转换层格式（如 xlsx）的 knowledge_source 行与 L2 chunk_type（如 legal:article）的 chunk 行，验证不触发 DB 约束；同时应用层拒绝注册表未登记或词表未声明的非法值；存量 18 值读写无变化。

- [x] T017 [US3] 新增 Alembic 迁移 backend/alembic/versions/0073_expand_format_and_chunk_type_wide.py（down_revision=0072，为当前迁移链 head）：三列 ALTER COLUMN TYPE VARCHAR(32) + DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT 宽模式 CHECK（format 用 ^[a-z][a-z0-9_]{0,31}$，chunk_type 宽模式覆盖 L1 5 值 + L2 命名空间 + 存量 18 值），并提供可回滚的 downgrade()（沿用 a1b2c3d4e5f6 的 drop/add 模式，research §8/§9）。确保既有迁移链测试（backend/tests/unit/test_migrations_helper.py 等）通过。

- [x] T018 [US3] 更新 ORM 模型 backend/src/rag_mcp/models/knowledge_source.py、backend/src/rag_mcp/models/chunk.py、backend/src/rag_mcp/models/retrieval_run.py：三列 String(16)/String(8) → String(32)，枚举 CheckConstraint 改为与迁移一致的宽模式 CheckConstraint（FR-018）；同时删除 knowledge_source.py 中已无引用的 _SUPPORTED_FORMATS 死常量（格式清单由注册表单一事实源接管，避免第三份可漂移的硬编码格式清单）。

- [x] T019 [US3] 实现 chunk_type 两级词表校验模块（可置于 backend/src/rag_mcp/parsers/ 或 backend/src/rag_mcp/models/ 下，如 chunk_type_vocab.py）：L1 闭合集 section/heading/paragraph/list/table + L2 命名空间正则 ^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$ + 存量 18 值遗留集合（section/symbol/endpoint/schema/table/column/constraint/index/view/procedure/function/method/type/interface/class/heading/paragraph/list），并提供 is_valid_chunk_type 判定（FR-020/FR-021）。

- [x] T020 [US3] 应用层校验接管（FR-019）：format 由 FormatHandler 注册表校验、chunk_type 采用"L1 闭合集 ∪ 存量 18 值 ∪ (L2 命名空间 ∩ 域档案 chunk_type_extensions 声明)"两层语义——L2 值（如 legal:article）仅当当前 scope 域档案显式声明该命名空间扩展时才合法（本 Feature 不预设任何域扩展值）；在写入 knowledge_source/chunk/retrieval_run 的应用层路径接入校验并在非法时拒绝（DB 不再承担枚举兜底）。同时文档化 table 撞名（Word 表格 vs DDL 表）按"格式 + 域档案"上下文消歧（FR-022）。

- [x] T021 [US3] 迁移测试于 backend/tests/unit/test_migration_008_wide.py：区分 DB 层与应用层两层验证——(a) DB 宽模式 CHECK 按 pattern 放行 xlsx 格式与 legal:article chunk_type（命中 L2 正则）、拒绝非法值、放行存量 18 值、downgrade() 可回滚；(b) 应用层在构造一个声明 chunk_type_extensions 含 legal:* 的测试域档案后 legal:article 校验通过，未声明时被拒绝（两层语义不混淆）（FR-018/FR-019/FR-021，quickstart S4）。依赖 T017/T018/T019/T020。

- [x] T022 [P] [US3] 扩展 backend/tests/unit/test_retrieval_run_format.py：新增 xlsx/pptx/eml 等新格式名参数化用例，验证宽模式通过、非法值被拒绝（research §9）。依赖 T018。

**Checkpoint**: 三列 DB 约束放宽为宽模式 + 应用层校验，存量 18 值零迁移，新增格式/chunk_type 不再触发"迁移 + 改 CHECK"的格式税。

---

## Phase 4: 首批 9 格式落地（风险低→高：txt→csv→html→json/yaml/xml→xlsx→pptx→eml）— US2 + US4

**Purpose**: 逐一在注册表登记 9 格式条目（extensions/tier/binary/converter_spec + 切片器/locator_prefix），落地转换/处理、切片与定位；每格式解析测试 + ≥2 评测查询。txt 走极轻量原生处理器（空行分段），其余 8 种走转换层。

**Independent Test**: 逐一上传九种格式样例，验证每种经"转换/处理 → 凭据脱敏 → MarkdownParser 切片 → 嵌入"产生 L1 chunk_type 的 Chunk，且能通过自然语言与结构定位查询（sheet:/path:/msg:）检索到、证据携带来源版本与可定位位置。

> 登记任务均修改 registry.py 同一文件，须按风险顺序串行执行；各格式的解析测试在独立测试文件，登记完成后可并行。

### txt（极轻量原生处理器）

- [x] T023 [US2] 创建 TxtParser 于 backend/src/rag_mcp/parsers/txt_parser.py：按空行分段、chunk_type=paragraph、512–1024 Token 目标、超长段落按自然边界（句子/换行）二次切分；在 registry.py 登记 txt 条目（extensions=.txt、tier=native、binary=False、parser_factory=TxtParser、locator_prefix=文档级行区间），不进转换器（FR-010/FR-011/FR-012）。同时新增样例 fixture backend/tests/fixtures/samples/notes.txt。

- [x] T024 [P] [US2] txt 解析测试于 backend/tests/unit/test_parsers/test_txt_parser.py：空行分段产出 paragraph chunk、超长段落二次切分、文档级定位（空 section_path + start/end_line）、无 Chunk 则失败。依赖 T023。

### csv

- [x] T025 [US2] 在 registry.py 登记 csv 条目（extensions=.csv、tier=converter、binary=False、MarkitdownConverter + CSV 行窗口切片器、locator_prefix=sheet:）：每 50 行一个 table chunk、定位 sheet:<文件基名> + 行区间、超长窗口自然边界二次切分、空数据集拒收（FR-011，research §2.3/§4）。同时新增样例 fixture backend/tests/fixtures/samples/report.csv。

- [x] T026 [P] [US2] csv 解析测试于 backend/tests/unit/test_parsers/test_csv_parser.py：50 行窗口切片、sheet:report 定位、>50 行二次切分、空数据集（仅表头/0 行）拒收。依赖 T025。

### html

- [x] T027 [US2] 在 registry.py 登记 html 条目（extensions=.html/.htm、tier=converter、binary=False、MarkitdownConverter + 默认 MarkdownParser 通用切片、locator_prefix=# 标题路径）：产出 heading/paragraph/list/table chunk（FR-010/FR-011，research §2.1）。同时新增样例 fixture backend/tests/fixtures/samples/report.html。

- [x] T028 [P] [US2] html 解析测试于 backend/tests/unit/test_parsers/test_html_parser.py：heading/paragraph/list/table 产出、# 标题路径定位。依赖 T027。

### json / yaml / xml

- [x] T029 [US2] 在 registry.py 登记 json/yaml/xml 条目（json→.json、yaml→.yaml/.yml、xml→.xml；tier=converter、binary=False；json/xml 走 MarkitdownConverter、yaml 走 YamlAdapter；键/元素路径切片器、locator_prefix=path:）：顶层键作标题路径 path:/key、嵌套键 path:/a/b/c、超长叶子值自然边界二次切分（FR-011，research §2.4/§2.5/§2.6/§4）。json/yaml 与 OpenAPI 的内容嗅探判定顺序沿用 T004。同时新增样例 fixture config.json、config.yaml、catalog.xml 于 backend/tests/fixtures/samples/。

- [x] T030 [P] [US2] json/yaml/xml 解析测试于 backend/tests/unit/test_parsers/test_structured_parser.py：顶层/嵌套键路径切片、path:/ 定位、超长叶子值二次切分、OpenAPI 特征嗅探命中走 openapi 未命中回落通用 json/yaml。依赖 T029。

### xlsx

- [x] T031 [US2] 在 registry.py 登记 xlsx 条目（extensions=.xlsx、tier=converter、binary=True、MarkitdownConverter[xlsx] + 表格切片器、locator_prefix=sheet:）：多 Sheet 产出 # Sheet 标题 + table chunk、定位 sheet:<真实工作表名>（FR-011，research §2.7）。同时新增样例 fixture backend/tests/fixtures/samples/book.xlsx。

- [x] T032 [P] [US2] xlsx 解析测试于 backend/tests/unit/test_parsers/test_xlsx_parser.py：多 Sheet 切片、sheet:Sheet1 定位、table chunk 产出。依赖 T031。

### pptx

- [x] T033 [US2] 在 registry.py 登记 pptx 条目（extensions=.pptx、tier=converter、binary=True、MarkitdownConverter[pptx] + 默认 MarkdownParser 切片、locator_prefix=# 幻灯片标题）：产出 heading/paragraph/list、定位 # Slide N（FR-011，research §2.8）。同时新增样例 fixture backend/tests/fixtures/samples/deck.pptx。

- [x] T034 [P] [US2] pptx 解析测试于 backend/tests/unit/test_parsers/test_pptx_parser.py：幻灯片标题定位、heading/paragraph/list 产出。依赖 T033。

### eml

- [x] T035 [US2] 在 registry.py 登记 eml 条目（extensions=.eml、tier=converter、binary=False、MarkitdownConverter EmailConverter、locator_prefix=msg:）：仅保留头部字段名（From/To/Subject/Date）+ 正文、附件与内联图片忽略、定位 msg:<Subject>（FR-010，research §2.9）。同时新增样例 fixture backend/tests/fixtures/samples/msg.eml。

- [x] T036 [P] [US2] eml 解析测试于 backend/tests/unit/test_parsers/test_eml_parser.py：msg:Subject 定位、头部字段名 + 正文保留、附件忽略。依赖 T035。

### 跨格式收尾

- [x] T037 [US4] 定位前缀契约测试于 backend/tests/contract/test_format_locators_008.py：断言 9 格式 source_position 符合定位前缀表（sheet:/path:/msg:/# 标题路径、txt 文档级行区间），并更新 MCP 契约 source_position 描述以显式声明转换层定位粒度（FR-024/FR-025，contracts/locator-prefixes.md）。依赖 Phase 4 全部登记任务。

- [x] T038 [US2] 更新 backend/src/rag_mcp/config/domain_profiles.py 的 generic 档案 supported_formats 增补 9 新格式（csv/json/yaml/xml/xlsx/pptx/eml/html/txt），se-project 档案保持 8 格式不变（research §12）。依赖 Phase 4 全部登记任务。

- [x] T039 [US2] 端到端集成测试于 backend/tests/integration/test_format_expansion_008.py：9 格式逐一"上传 → 转换/处理 → 脱敏 → 切片 → 嵌入 → 检索"，断言 L1 chunk_type、父子索引、可检索且证据可定位（FR-011/FR-013/FR-029）；并断言 converter 版本 capabilities 仅含 dense_ready/lexical_ready（+可选 graph_ready）无新增能力标志（FR-031）、派生索引可自 PG 持久化 Chunk 重建且 chunk_id 不变（FR-030）；补一条 converter reprocess 用例：失败时旧版本保持 published、成功时新版本发布（research §11 重试语义）。依赖 T037/T038。

- [x] T040 [US2] 边界语义测试于 backend/tests/integration/test_format_boundaries_008.py：>20MB 文件、损坏 xlsx、空 CSV、扩展名/内容不匹配、converter 不可用均 fail-fast 拒收、不产生空 Chunk（FR-015，research §5）。依赖 T016 + Phase 4 登记任务。

- [x] T041 [US2] 对照评测查询：为每新格式在 eval/eval_dataset.json 新增 ≥2 条查询（≥1 自然语言 + ≥1 结构定位，如 sheet:Sheet1、path:/service/host、msg:Re: 合同评审），共 ≥18 条；新条目带 format 字段（沿用 003 约定）且每格式 ≥1 条结构定位查询；沿用 003 的 AI 生成 + 人工审核 + JSON 格式约定，原 37 条全部保留且字段结构不变以与基线逐条可比，并确保 backend/tests/unit/test_eval_dataset.py 通过（FR-034，contracts/locator-prefixes.md §5，eval/README.md 固定集纪律）。依赖 Phase 4 全部登记任务。

**Checkpoint**: 9 格式全部可上传、可切片、可检索、证据可定位；定位前缀规范落地；每格式解析测试与评测查询就绪。

---

## Phase 5: 前端泛化与验收（accept/types + 003 回归 + 硬指标 + quickstart）— US5 + 验收

**Purpose**: 泛化前端上传 accept/文案/types 至首批 9 格式；完成 003 回归、硬指标三件套与 quickstart 端到端验证。

**Independent Test**: 浏览器上传界面选择九种新格式文件，验证文件选择器 accept 覆盖新扩展名、来源列表格式字段正确显示；混合评测集硬指标达标。

### 前端泛化

- [x] T042 [US5] 泛化 frontend/src/types/index.ts 中 format 联合类型至全格式（8 原生 + 9 新，不再停留 'markdown' | 'java'）（FR-033）。

- [x] T043 [US5] 泛化 frontend/src/pages/ProjectDetailPage.tsx 中 accept 列表（约 276 行的硬编码 11 扩展名）与上传提示文案至首批 9 格式扩展名（.html/.htm/.txt/.csv/.json/.yaml/.yml/.xml/.xlsx/.pptx/.eml 及既有扩展名），并更新 frontend/src/api/knowledgeSources.ts 中相关类型/文案（FR-032）。依赖 T042。

- [x] T044 [P] [US5] 前端测试：验证上传 accept 覆盖 9 新扩展名、来源列表渲染 format 字段正确显示（不再局限于 markdown/java）（quickstart S9）。依赖 T042/T043。

### 对照评测与验收

- [x] T045 003 回归：在既有 8 格式固定评测集上重跑 eval/run_eval.py，断言无回归（Recall@K 精确、MRR/nDCG 1% 相对容差，FR-035）。依赖 Phase 1–4 完成。

- [x] T046 硬指标三件套：构建混合评测集（8 原生 + 9 新），运行 backend/tests/contract/test_hard_metrics.py（或等价评测脚本），断言跨知识域串库 = 0、search_knowledge/get_evidence 输出 Schema 合法率 = 100%、来源可定位率 = 100%（FR-037，SC-004/005/006）。依赖 T041/T045。

- [x] T047 全量测试套件：运行 backend 全量 pytest（含既有 1509 项）与 frontend 测试全绿，证明存量零迁移无回归（SC-002/SC-007）。依赖 Phase 1–5 全部实现任务。

- [x] T048 quickstart 端到端验证：按 specs/008-universal-ingestion-channel/quickstart.md 的 S1–S9 场景逐一跑通（alembic upgrade head、9 格式端到端、定位前缀契约、宽模式、脱敏、边界、契约测试、硬指标、前端）。依赖 T045/T046/T047。

**Checkpoint**: 前端泛化完成；003 无回归、硬指标三件套达标、quickstart 全场景通过，特性可交付。

---

## Phase 6: 收尾与交叉关注（Polish）

**Purpose**: 文档与许可证修正、评测基线记录、硬约束终审。

- [x] T049 [P] 文档交叉引用与许可证修正：更正 spec/plan/research 中 markitdown 许可证标注（MIT 非 Apache-2.0），并确保 backend/tests/unit/test_docs_crossrefs.py 通过。

- [x] T050 [P] 记录 008 评测基线：运行混合评测集并记录各新格式 Recall@K、MRR、nDCG 首轮指标数值（不预设阈值，沿用 003 "首轮记录基线"策略，SC-003）。

- [x] T051 硬约束终审：核对 SC-008（新增格式边际成本 ≤ 2 个文件，不再出现 4 处 if/elif + 3 个 DB CHECK + 1 次迁移）、注册表初始化失败 = 启动失败、转换层 chunk_type 限定 L1 闭合集、EML 附件不进入索引等硬约束均已满足。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1（注册表基座）**: 无前置依赖，可立即开始；T001 行为等价测试先行。
- **Phase 2（转换层基座）**: 依赖 Phase 1（registry.parse_content 的 converter 分支建立在注册表之上）；T010 依赖安装可先行。
- **Phase 3（DB 放宽）**: 依赖 Phase 1（应用层 format 校验用注册表），但与 Phase 2 无强依赖，可在 Phase 2 进行中并行推进。
- **Phase 4（9 格式落地）**: 依赖 Phase 1 + Phase 2（converter/切片器就绪）+ Phase 3（宽模式写入合法）；登记任务按 txt→csv→html→json/yaml/xml→xlsx→pptx→eml 顺序。
- **Phase 5（前端与验收）**: 依赖 Phase 1–4 全部完成。
- **Phase 6（收尾）**: 依赖 Phase 1–5 完成。

### User Story Dependencies

- **US1 (P1)**: Phase 1，无依赖，是后续全部的地基。
- **US2 (P1)**: Phase 2（基座）+ Phase 4（9 格式），依赖 US1。
- **US3 (P2)**: Phase 3，依赖 US1（注册表校验），可与 US2 并行。
- **US4 (P2)**: Phase 4 的 T037，依赖 US1/US2（格式与定位前缀均先就位）。
- **US5 (P3)**: Phase 5 前端，依赖 US1–US4。

### Within Each Phase

- Phase 1：测试先行（T001）→ 注册表实现 → 四处分发委托 → 回归验证。
- Phase 2：依赖安装 → 接口/适配器 → 契约测试 → 脱敏接线 → 护栏。
- Phase 4：登记条目（同文件串行）→ 解析测试（可并行）→ 跨格式收尾（契约/集成/边界/评测）。

### Parallel Opportunities

- Phase 1：T001 可独立先行编写。
- Phase 2：T010（依赖安装）、T014（脱敏规则扩展）与 T011/T012/T013 分属不同文件，可并行；T011→T012→T013 串行。
- Phase 3：T022（retrieval_run_format 扩展）与 T017–T021 主链并行。
- Phase 4：每个格式的解析测试（T024/T026/T028/T030/T032/T034/T036）在独立测试文件、登记完成后可并行；T037/T038/T039/T040/T041 在全部登记完成后可并行。
- Phase 5：T044（前端测试）与 T045（003 回归）可并行。
- 多开发者可流水线分工：一人主 registry.py 登记（串行），其余人并行写各格式解析测试。

---

## Parallel Example: Phase 4 格式落地

各格式解析测试（在对应登记任务完成后）可并行启动：

- Task: "csv 解析测试于 backend/tests/unit/test_parsers/test_csv_parser.py"
- Task: "html 解析测试于 backend/tests/unit/test_parsers/test_html_parser.py"
- Task: "json/yaml/xml 解析测试于 backend/tests/unit/test_parsers/test_structured_parser.py"
- Task: "xlsx 解析测试于 backend/tests/unit/test_parsers/test_xlsx_parser.py"
- Task: "pptx 解析测试于 backend/tests/unit/test_parsers/test_pptx_parser.py"
- Task: "eml 解析测试于 backend/tests/unit/test_parsers/test_eml_parser.py"

---

## Implementation Strategy

### MVP First（Phase 1 + Phase 2 基座 + 一个最小格式）

1. 完成 Phase 1（注册表基座 + 存量 8 格式零回归）→ 立即可验证单一事实源。
2. 完成 Phase 2 转换层基座（接口 + markitdown + 脱敏顺序 + 契约测试）。
3. 完成 Phase 3 DB 放宽（宽模式 + String(32)）。
4. 落地 txt（极轻量、零转换器依赖）作为首个新格式端到端验证。
5. **STOP and VALIDATE**：验证 txt 可上传/切片/检索/定位，确认转换层管线连通。

### Incremental Delivery

1. Phase 1 完成 → 存量 8 格式经注册表无回归（第一交付增量）。
2. Phase 2 + Phase 3 完成 → 转换层与 DB 放宽就绪（第二交付增量）。
3. Phase 4 按风险从低到高逐步落地 9 格式，每批均可独立验证（txt → csv → html → json/yaml/xml → xlsx → pptx → eml）。
4. Phase 5 前端泛化 + 003 回归 + 硬指标 + quickstart 全通过 → 可交付。
5. 每批格式落地不破坏此前格式，增量叠加价值。

### Parallel Team Strategy

多开发者时：

1. 团队共同完成 Phase 1（注册表基座）。
2. 完成后分流：开发者 A 推进 Phase 2 转换层、开发者 B 推进 Phase 3 DB 迁移（二者可并行）。
3. Phase 4 由 A 主 registry.py 登记（串行），B/C 并行写各格式解析测试。
4. Phase 5 由 B 做前端泛化、C 跑评测与回归。

---

## Notes

- [P] 任务 = 不同文件、无未完成依赖，可并行；[Story] 标签映射到 spec 用户故事以追踪溯源。
- 每个用户故事（对应 Phase）应可独立完成与独立验证。
- 测试任务先写并期望 FAIL 后再实现（Phase 1 行为等价、Phase 4 每格式解析）。
- 每完成一个任务或逻辑组后提交一次。
- 在任何 Checkpoint 停下可独立验证该 Phase。
- 避免：含糊任务、同文件冲突、跨故事依赖破坏独立性。
- 迁移编号以本清单的 0073 为准（覆盖 plan.md 中过时的 0070/0062）。

## Phase 7: Convergence

**Purpose**: 收敛 008 通用摄入通道实现与 spec/plan/tasks 的差距——残留硬编码格式分支、错误消息漂移、转换层异常路径（超时/毒文件/空产物）降级语义、评测查询覆盖与验收记录缺口。

- [x] T052 [US2] 实现 json/yaml/xml 嵌套键/元素路径切片（顶层键 path:/key、嵌套键 path:/a/b/c、超长叶子值自然边界二次切分），使结构化评测查询 path:/service/host、path:/root/item 可被切片产出满足 per FR-011 (partial)——当前 json_yaml_slicer/xml_slicer 仅产出顶层路径（path:/service、path:/item），嵌套路径不可检索。

- [x] T053 [US2] 为转换层 markitdown convert 增加超时护栏（纳入 plan 30s 总超时评估），超时降级为失败并说明原因，防毒文件（XML 实体膨胀/zip 炸弹等）挂起后台摄入 per FR-015 (missing)——当前 registry.to_text → converter.convert 同步执行且无超时。

- [x] T054 [US2] 转换层二进制格式（xlsx/pptx）损坏/毒文件在转换阶段 fail-fast 并说明"损坏/无法解析"原因，而非 markitdown 静默降级为纯文本后在切片阶段以通用 "No chunks produced" 丢失原因 per FR-015 (partial)。

- [x] T055 [US1] 将 text_extractor.extract_text 的 word/pdf if/elif 分发委托注册表（FormatHandler 增加文本提取工厂），消除残留硬编码格式分支 per FR-005 (partial)。

- [x] T056 [US1] 将 postgres_graph_store.rebuild_graph_edges 的 java/ddl if/elif 图提取分发委托 registry.graph_extractor，消除第二处图提取硬编码分支 per FR-006 (partial)。

- [x] T057 [US1] 上传大小超限错误消息改为注册表统一生成（当前硬编码 "File exceeds the maximum upload size of X bytes"），消除文案漂移 per FR-015 (partial)。

- [x] T058 [US2] 转换层切片器实现 512–1024 token 目标 + 自然边界二次切分（超长 CSV 窗口/JSON 叶子/XLSX 表/HTML 段落），当前仅 TxtParser 实现超长二次切分 per FR-012 (partial)。

- [x] T059 [US2] 转换层 chunk 建立父子索引（slicers 设置非空 parent_position_path 使 backfill_parent_chunk_ids 生效），当前全部转换层 chunk 无父引用 per FR-013 (partial)。

- [x] T060 [US2] 记录 008 评测基线并落实 FR-037 硬指标三件套实测：运行混合评测集（8 原生 + 9 新）生成含 9 新格式 Recall@K/MRR/nDCG 的基线报告，并将跨域串库=0/Schema=100%/可定位=100% 落实为混合评测集实测而非 test_hard_metrics.py 的浅层 by-design 断言（当前 format_expansion_report.json 仅覆盖 8 原生格式且早于 008） per SC-003/FR-037 (partial)。

- [x] T061 [US1] 统一注册表错误消息前缀文案（detect_format 的 "Unsupported file format." vs _by_format_or_raise 的 "Unsupported format {fmt!r}."），确保各入口文案一致 per FR-007 (partial)。

- [x] T062 [US2] 为 txt 补充结构定位查询（或文档化其无前缀行区间定位的评测口径），当前 eval 中 txt 两条查询均为自然语言 per FR-034 (partial)。
