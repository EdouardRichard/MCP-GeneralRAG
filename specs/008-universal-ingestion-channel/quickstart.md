# Quickstart: 008 通用摄入通道验证指南

**Branch**: `008-universal-ingestion-channel` | **Date**: 2026-09-06

本指南给出可运行的端到端验证场景，证明 008 的注册表收敛、转换层摄入、DB 宽模式、定位前缀与前端泛化均生效。契约与数据模型细节见 [contracts/](./contracts/) 与 [data-model.md](./data-model.md)，不在此重复。

## 前置条件

1. 后端依赖就绪（含新增 `markitdown[xlsx,pptx]`，版本锁定）。
2. 数据库迁移到位：`alembic upgrade head`（含 `0070_expand_format_and_chunk_type_wide.py`）。
3. 服务启动成功（注册表初始化失败 = 启动失败，须无异常启动）。
4. 样例文件（9 新格式 + 8 原生回归）就位于 `backend/tests/fixtures/samples/`。

## 环境准备

```bash
cd backend
python -m pip install -e ".[dev]"
alembic upgrade head
# 启动后端（FastAPI + MCP），确认无注册表初始化异常
```

## 验证场景

### S1 注册表单一事实源 + 原生零回归

- 上传存量 8 格式各一份（markdown/java/openapi/ddl/go/python/word/pdf）。
- **期望**：格式检测、解析切片、二进制提取、图提取分派均经注册表，产出与 1.0 一致（SC-002）。
- 命令：`pytest backend/tests/integration/test_format_expansion.py -q`（既有回归集）。

### S2 转换层 9 格式端到端

- 逐一上传 html/txt/csv/json/yaml/xml/xlsx/pptx/eml。
- **期望**：每种格式经「转换/处理 → 凭据脱敏 → MarkdownParser 切片 → 嵌入」产生 L1 chunk_type 的 Chunk，可检索、证据可定位。
- 命令：`pytest backend/tests/integration/test_format_expansion_008.py -q`。

### S3 定位前缀契约

- 对每种新格式断言 `source_position` 符合定位前缀表（`sheet:`/`path:`/`msg:`/`#`）。
- 命令：`pytest backend/tests/contract/test_format_locators_008.py -q`。

### S4 DB 宽模式 + 应用层校验

- 写入一个转换层格式的 `knowledge_source` 行与新 L2 chunk_type（如 `legal:article`）不触发 DB 约束；非法值被应用层拒绝。
- 命令：`pytest backend/tests/unit/test_migration_008_wide.py -q`。

### S5 凭据脱敏扩展

- 上传含凭据的新格式样例（JSON `api_key`、YAML `password`、EML 头部凭据），断言凭据值不出现在索引/MCP 证据正文（SC-007）。
- 命令：`pytest backend/tests/unit/test_parsers/test_credential_redaction_new_formats.py -q`（扩展后）。

### S6 边界语义（fail-fast）

- 上传 >20MB 文件、损坏 xlsx、空 CSV、扩展名/内容不匹配 → 均须在检测/上传阶段拒收或报告失败（无空 Chunk）。
- 命令：`pytest backend/tests/integration/test_format_boundaries_008.py -q`。

### S7 转换层契约测试（markitdown 版本锁定）

- 每种格式的「给定输入 → 期望 Markdown IR / chunk_type / 定位标识」固化，防版本漂移。
- 命令：`pytest backend/tests/unit/test_parsers/test_converter.py -q`。

### S8 硬指标三件套 + 003 无回归

- 混合评测集（8 原生 + 9 新）：跨域串库 = 0、Schema 合法率 = 100%、来源可定位率 = 100%（FR-037）。
- 003 既有格式集无回归（FR-035）。
- 命令：`pytest backend/tests/contract/test_hard_metrics.py -q` + `python eval/run_eval.py`。

### S9 前端泛化

- 浏览器上传界面 accept 覆盖 9 新扩展名；来源列表格式字段正确显示。
- 命令：`cd frontend && npm test`（或手工验证）。

## 期望结果总览

| 验证 | 通过标准 |
|------|----------|
| S1 | 存量 8 格式经注册表路径无回归 |
| S2 | 9 新格式可上传/切片/检索/定位 |
| S3 | 定位前缀符合契约表 |
| S4 | DB 宽模式通过、应用层校验拒绝非法值 |
| S5 | 新格式凭据值不泄漏 |
| S6 | 超限/损坏/空/不匹配 fail-fast |
| S7 | markitdown 行为契约固化 |
| S8 | 硬指标三件套 100% / 0 / 100%，003 无回归 |
| S9 | 前端 accept/types/文案泛化 |

> 实现细节（迁移脚本、注册表/转换器具体实现、完整测试套件）属于 `tasks.md` 与实现阶段，本指南不包含实现代码。
