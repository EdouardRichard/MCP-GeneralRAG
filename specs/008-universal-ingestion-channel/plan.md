# Implementation Plan: 通用摄入通道（FormatHandler 注册表 + 转换层）

**Branch**: `008-universal-ingestion-channel` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/008-universal-ingestion-channel/spec.md`

## Summary

将四处各自为政的格式分发（格式检测 `_detect_format`、解析分派 `_parse_content`、二进制声明 `BINARY_FORMATS`、图提取器分派）收敛为单一 `FormatHandler` 注册表，新增可插拔转换层（markitdown 适配器，任意通用格式 → Markdown IR → 凭据脱敏 → MarkdownParser 通用切片），首批 9 种通用格式（html/txt/csv/json/yaml/xml/xlsx/pptx/eml；txt 走极轻量原生处理器，其余 8 种走转换层）。原生 8 解析器冻结不动、存量格式零迁移。同时放宽三列 DB 枚举 CHECK 为宽模式 + 应用层校验（String(8/16)→String(32)），落地证据定位前缀规范（`sheet:`/`path:`/`msg:` 新增），并泛化前端 accept/文案/types。目标：新增格式边际成本 ≤ 2 个文件，消除"4 处 if/elif + 3 个 DB CHECK + 1 次迁移"的格式税。

## Technical Context

**Language/Version**: Python 3.12（后端）、TypeScript/React（前端）

**Primary Dependencies**: FastAPI、SQLAlchemy 2.0（asyncpg）、Alembic、Qdrant、LangGraph/LangChain、tree-sitter、markdown-it-py、python-docx、pdfplumber、pyyaml；**新增** `markitdown[xlsx,pptx]`（核心依赖，非 `[all]`，锁定版本）

**Storage**: PostgreSQL（控制面：knowledge_sources/chunks/retrieval_runs/processing_runs/domain_profiles）+ Qdrant（Dense + Sparse 混合向量，payload 不变）

**Testing**: pytest + pytest-asyncio + jsonschema（contract/integration/unit 三层；沿用 001–007 既有测试约定）

**Target Platform**: Linux 服务器（本机部署，local CPU/GPU/remote API 均可，loopback 默认绑定）

**Project Type**: web-service（FastAPI 后端 + React 管理端）+ MCP server（Streamable HTTP）

**Performance Goals**: 服务端总超时 30s 护栏（蓝图 §19）；转换耗时纳入护栏评估；单文件上传大小上限 20MB（可配置）

**Constraints**: 单写入者/多读取者；原生 8 解析器冻结；注册表初始化失败 = 启动失败（不静默回落）；转换层定位粒度为"转换后标题路径"；凭据脱敏顺序不变（转文本之后、切片之前）；`markitdown` 版本锁定 + 契约测试固化

**Scale/Scope**: 单用户本机；8 原生格式 + 9 新格式（共 17）；chunk_type L1 闭合集 5 值 + L2 命名空间扩展 + 存量 18 值遗留

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪法条款 | 映射 | 状态 |
|---------|------|------|
| I 显式知识域引用 | FR-026：转换层格式检索 MUST 继承显式 scope 引用，缺失拒绝 | ✅ 通过 |
| II 域事实优先 | 摄入路径不涉及跨域证据融合；公共/域专属证据并发返回由检索层保证 | ✅ 通过（不适用摄入） |
| III 暴露不确定性 | FR-015：转换失败/空产物/损坏 MUST 报告原因，不伪造内容 | ✅ 通过 |
| IV 可定位证据 | FR-024/FR-025/FR-029：定位前缀规范 + 转换后标题路径粒度 + 100% 可定位 | ✅ 通过 |
| V 数据与控制分离 | FR-017：Markdown IR 脱敏前为不可信数据；凭据识别规则扩展至新格式形态 | ✅ 通过 |
| VI 确定性控制优先 | 注册表为确定性声明；格式检测/切片/图提取分派无 LLM 介入 | ✅ 通过 |
| VII 独立接口演进 | DB 宽模式 vs MCP 契约 vs 注册表内部状态分版本演进 | ✅ 通过 |
| VIII 版本不混用 | FR-030/FR-031：转换层派生索引可重建，复用既有 `dense_ready`/`lexical_ready` | ✅ 通过 |
| IX 同步结果优先 | 转换层同步完成于 30s 护栏内，不引入 Task/Resource 依赖 | ✅ 通过 |
| X 评测驱动优化 | FR-034–FR-037：每新格式 ≥2 查询 + 003 无回归 + 契约测试 + 硬指标三件套 | ✅ 通过 |
| XI 领域中立 | 注册表按格式声明、不硬编码领域；chunk_type L2 由域档案声明 | ✅ 通过 |

**硬约束（Non-Negotiable）**：跨域串库 = 0（FR-027）、无显式引用拒绝检索（FR-026）、上传内容不得作为控制指令（FR-017）、Schema 合法率 100%（FR-028）、来源可定位率 100%（FR-029）——全部在设计中被逐条承接，无豁免。

**结论**：无宪法违反项，无需 Complexity Tracking 豁免记录。`markitdown` 作为核心依赖由 FR-014 明确授权（仅锁 9 格式所需 extras，非 `[all]`），非违反项；须同步更新 `backend/tests/fixtures/deps_baseline.txt` 与 `backend/tests/unit/test_deps_unchanged.py` 的基线快照。

## Project Structure

### Documentation (this feature)

```text
specs/008-universal-ingestion-channel/
├── plan.md              # 本文件
├── research.md          # Phase 0 输出
├── data-model.md        # Phase 1 输出
├── quickstart.md        # Phase 1 输出
├── contracts/           # Phase 1 输出
│   ├── format-handler-registry.md
│   └── locator-prefixes.md
└── tasks.md             # Phase 2 输出（/speckit-tasks，非本命令）
```

### Source Code (repository root)

```text
backend/
├── src/rag_mcp/
│   ├── parsers/
│   │   ├── registry.py           # 新增：FormatHandler 注册表（单一分发点）
│   │   ├── converter.py          # 新增：可插拔转换器接口 + markitdown 适配器
│   │   ├── txt_parser.py         # 新增：TXT 极轻量原生处理器（空行分段）
│   │   ├── markdown_parser.py    # 复用：通用切片（heading/paragraph/list/table）
│   │   ├── credential_redactor.py # 修改：扩展新格式凭据形态识别规则
│   │   ├── text_extractor.py     # 修改：BINARY_FORMATS → 注册表 binary 声明
│   │   └── {java,go,python,openapi,ddl,word,pdf}_parser.py  # 冻结不动
│   ├── api/knowledge_sources.py  # 修改：_detect_format 委托注册表
│   ├── services/ingestion_service.py # 修改：_parse_content + 图提取分派委托注册表
│   └── models/{knowledge_source,chunk,retrieval_run}.py  # 修改：宽模式 CHECK + String(32)
├── alembic/versions/0073_expand_format_and_chunk_type_wide.py    # 新增：宽模式迁移（沿用 a1b2c3d4e5f6 drop/add 模式）
├── tests/
│   ├── unit/test_parsers/test_registry.py           # 新增
│   ├── unit/test_parsers/test_converter.py          # 新增
│   ├── unit/test_parsers/test_txt_parser.py         # 新增
│   ├── unit/test_parsers/test_credential_redaction_new_formats.py # 扩展
│   ├── contract/test_format_locators_008.py         # 新增
│   ├── integration/test_format_expansion_008.py     # 新增
│   └── fixtures/deps_baseline.txt                   # 更新：加入 markitdown
└── pyproject.toml                                   # 修改：加入 markitdown[xlsx,pptx]

frontend/src/
├── types/index.ts                 # 修改：format 联合类型泛化
├── api/knowledgeSources.ts        # 修改：accept 扩展名 + 文案泛化
└── pages/*                        # 修改：上传界面文案
```

**Structure Decision**: 单仓库、`backend/`（Python FastAPI + MCP）与 `frontend/`（React/Vite）双端。新增的注册表与转换层落在 `backend/src/rag_mcp/parsers/` 下，与既有解析器同层；注册表作为解析器模块的单一入口，不引入新的顶层包。迁移沿用 Alembic（`backend/alembic/versions/`），版本号顺延至 0073（自当前迁移链 head 0072 顺延，0070–0072 已被 Feature 007 占用）。

## Complexity Tracking

> 无宪法违反项，本表留空。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | | |
