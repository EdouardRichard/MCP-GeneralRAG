# Implementation Plan: 记忆基座与写读回路（G2+ 权威层）

**Branch**: `012-memory-foundation-write-read-loop` | **Date**: 2026-10-04 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/012-memory-foundation-write-read-loop/spec.md`

## Summary

以 append-only `memory_events` 作为唯一权威，在 PostgreSQL 单事务中追加事件并 UPSERT 当前态关系投影；六类投影（关系、dense、链接图、摘要树、文件镜像、显著性）均为 reducer-only、runtime read-only 的派生视图，任何写入口都必须拒绝事实旁路。服务层实现九步可信写入、四模式读取、scope binding、衰减显著性与六投影 rebuild；MCP 以 FastMCP 签名定义 schema，并按 writer/reader mode 注册三项新工具；Qdrant 保存版本化 dense 投影，召回只下推 scope/kind/session，状态与时间条件由 PG 后置核验。管理面提供治理、回滚和 rebuild，前端增加最小记忆浏览页。

## Technical Context

**Language/Version**: Python 3.12+；前端 TypeScript 5.6+。

**Primary Dependencies**: FastAPI、SQLAlchemy 2 async、Alembic、FastMCP (`mcp>=1.2`)、Qdrant client、Pydantic 2、React 18、Ant Design 5；复用 `credential_redactor` 与 `injection_detector`。

**Storage**: PostgreSQL 为事件日志、关系投影、scope/session/salience/recall audit 权威事务载体；Qdrant `memories_dense_{index_version}` 为可重建向量投影；文件镜像/DIGEST/INDEX 是可重建投影。

**Testing**: pytest 分层 `backend/tests/unit`、`contract`、`integration`；Alembic migration helper/DDL parity；JSON Schema contract tests；MCP 双模式工具注册测试；真实 PostgreSQL/Qdrant 与文件系统隔离 E2E；前端 `pnpm build` 与页面/API 测试。

**Target Platform**: Python backend，FastAPI 管理面与 Streamable HTTP/stdio MCP；writer/reader 双实例；React 管理 UI。

**Project Type**: Web service + MCP server + management frontend。

**Performance Goals**: `start_work` ≤2s；`recall_memory` ≤3s；start_work 包体 standard/compact/minimal ≤2000/800/300 字；recall 总预算 ≤6000 字，excerpt ≤300 字；新旧三工具既有响应逐字节兼容。

**Constraints**: 单写者/多读者；事件和 PostgreSQL 投影同事务；Qdrant status 不下推；scope 必须显式且任何解析失败拒绝；脱敏先于落库；hard 锚定与 provenance 完备率 100%；quarantined 默认召回/巩固泄漏为 0；MCP rollback 禁止；CHECK 使用宽模式，精确枚举/条件关系由独立应用校验器覆盖；评测失败不得覆盖历史报告。

**Scale/Scope**: 首期每 scope quota 5000；4 个内置 domain profile 同一 memory_policy 默认值；六类投影都必须在 012 提供最小非空、可运行、可重建实现，并由 reducer-only 写入口和逐类 integrity 测试保护；在线一致事务覆盖 PG 权威日志与关系投影，向量投影按同一写请求的成功边界同步写入并在失败时明确失败/恢复；链接、摘要、文件投影的高级消费、抽取和异步刷新由 013/014 负责。012 预计 60–75 个实现任务，依赖 007/008/006 已交付骨架。

## Constitution Check

*GATE: Must pass before Phase 0 research and re-check after Phase 1 design.*

### Pre-Research Gate (v1.4.0)

| Principle / constraint | Result | Evidence / plan guard |
|---|---|---|
| I Explicit Knowledge Scope | PASS | 所有 MCP 记忆读写要求显式 scope；path 解析失败/歧义拒绝；不回落。 |
| II Domain Facts Take Priority | PASS | 记忆与 canonical knowledge 分离；记忆通道不覆盖域事实。 |
| III Expose Uncertainty | PASS | hard/soft/distilled provenance 明示；召回返回 gaps/completion 状态。 |
| IV Locatable Evidence | PASS | hard evidence_refs 逐条复验存在/同域/published；外部 evidence 契约不改。 |
| V Data and Control Separation | PASS | 复用脱敏与 injection detector；quarantined 双排除；内容不控制权限/工具。 |
| VI Deterministic Control First | PASS | 写入校验、排序、状态迁移、预算、rollback/rebuild 均确定性。 |
| VII Independent Interface Evolution | PASS | DB model、服务内部 DTO、MCP/REST schemas 分层并由 contracts 固化。 |
| VIII Knowledge Version Non-Mixing | PASS | Qdrant collection 名含 index_version，重嵌入/重建按版本隔离。 |
| IX Synchronous Results First | PASS | 三个新 MCP tools 同步返回确定性结果和四态/失败信息；不依赖 Tasks/Resources。 |
| X Evaluation-Driven Optimization | PASS | salience 默认低权重且必须衰减；015 调优前无收益宣称；全套回归作为发布门。 |
| XI Domain Neutrality | PASS | memory_policy 归 domain_profiles；不硬编码领域记忆语义。 |
| XII External Memory Loop | PASS | hard 锚证据；soft/distilled 元数据；supersede；不自动写 canonical KB；复用安全边界。 |
| XIII Governed Trajectory | PASS | append-only log 唯一权威；六投影可重建只读；五不变量和管理面 rollback。 |
| Hard constraints | PASS | 四路径隔离、schema 100%、provenance/硬锚 100%、projection integrity 100% 都转为 E2E/发布门。 |
| Architecture / deployment | PASS | Python/FastAPI/Postgres/Qdrant/React；writer/reader 保持 006 单写者治理。 |

### Post-Design Gate

Phase 1 设计仍符合上述原则。同步一致性定义为：事件与关系投影必须处于同一个 PostgreSQL 事务；六类投影的写入均只能由 reducer 产物驱动，runtime、repository 和数据库权限三层均拒绝事实旁路；向量、链接、摘要、文件和显著性等外部投影处于该 MCP 写请求的同步成功边界，任一投影失败必须不返回成功、保留可恢复状态并在全部投影补齐及校验通过前屏蔽所有读路径；纯 Qdrant 与 PostgreSQL 不具备跨库 ACID，因此不将其描述为分布式单事务。六类业务投影固定为 relation、dense vector、typed links、summary tree、file mirror、salience；metadata/status registry 不计入六类。每类均验证非空状态、状态变更、删除传播、provenance 保全、rollback 和 fingerprint。无 Constitution exception。

## Phase 0: Research Summary

研究结论、替代方案和需要的实证矩阵见 [research.md](research.md)。重点裁决了 PG 原子物化与外部投影同步边界、等价性验证、status 后置核验、显著性正反馈风险、path binding 规范化、截断恢复和 rollback 仲裁。

## Phase 1: Design & Contracts

- [data-model.md](data-model.md)：事件、六投影、memory policy、生命周期、双时态、snapshot/rebuild、rollback 数据模型。
- [contracts/](contracts/)：MCP 三工具输入/输出、记忆 entry/event 共享定义、错误码和管理 REST schema。
- [quickstart.md](quickstart.md)：迁移、writer/reader 双形态、契约/unit/integration/E2E 运行与验收步骤。

### Implementation Boundaries

1. **Schema & persistence**：在 `backend/alembic/versions/` 新增单个 012 migration；在 `backend/src/rag_mcp/models/` 增 event/projection/scope-binding/session/salience/recall-run 模型；`domain_profiles.memory_policy` 追加列；CHECK 使用宽模式，强校验集中到独立 validators。
2. **Pure logic & services**：新增 `services/memory_service.py`、`scope_binding_service.py`、`salience_service.py`、`runtime/projection_rebuild.py` 与 `fusion/rrf.py` 向后兼容扩展；先交付可单测纯函数/校验器，再接数据库。
3. **MCP surfaces**：新增 `mcp/record_memory.py`、`recall_memory.py`、`start_work.py`；`create_mcp_server(..., mode=...)` 由 FastMCP 签名产生 JSON schema，writer 暴露既有三工具+新三工具共六项，reader 暴露既有三只读+新两只读共五项；注册模式与 006 runtime instance identity 对齐。
4. **External projections**：新增 `memories_dense_{index_version}` collection support；scope 必须在 Qdrant filter；status/valid_to/agent/阈值 PG 后置核验。文件、摘要、链接 rebuild adapter 由 projection registry 驱动，按 scope 隔离并带版本/指纹。
5. **Management & UI**：FastAPI 新增 `api/memory.py` router，限定 writer 管理面；React 增加记忆浏览/状态/来源摘要最小页，不提供未经要求的自动晋升/巩固 UI。
6. **Validation**：unit→contract→integration→E2E 逐层执行；八项记忆 E2E、AOEP 四状态义务、五不变量逐项断言、六投影逐类 integrity、四路径串库实测（event log/relation/vector/file）、hard evidence 逐条 attribution re-verification、soft 五元 metadata、distilled source-chain、旧三工具 byte compatibility 和 001–011 回归为发布门。五不变量映射固定为：权威单调→T004/T079，范围不扩张→T004/T079，删除传播→T015/T068/T079，provenance 保全→T015/T043/T079，回滚可溯→T015/T068/T079；任一失败阻止发布。SC-001–SC-017 必须在最终验收中逐项收口。

## Project Structure

### Documentation (this feature)

```text
specs/012-memory-foundation-write-read-loop/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── mcp-record-memory.input.schema.json
│   ├── mcp-record-memory.output.schema.json
│   ├── mcp-recall-memory.input.schema.json
│   ├── mcp-recall-memory.output.schema.json
│   ├── mcp-start-work.input.schema.json
│   ├── mcp-start-work.output.schema.json
│   ├── memory-event.schema.json
│   ├── memory-entry.schema.json
│   ├── memory-management.schema.json
│   └── error-codes.json
└── checklists/requirements.md
```

### Source Code (repository root)

```text
backend/
├── alembic/versions/0080_memory_foundation.py
├── src/rag_mcp/
│   ├── models/memory_event.py
│   ├── models/memory_projection.py
│   ├── models/scope_binding.py
│   ├── models/session.py
│   ├── models/memory_recall_run.py
│   ├── services/memory_service.py
│   ├── services/scope_binding_service.py
│   ├── services/salience_service.py
│   ├── runtime/projection_rebuild.py
│   ├── indexing/memory_vectors.py
│   ├── fusion/rrf.py
│   ├── mcp/record_memory.py
│   ├── mcp/recall_memory.py
│   ├── mcp/start_work.py
│   ├── api/memory.py
│   └── server.py / mcp/__init__.py / config/domain_profiles.py
└── tests/
    ├── unit/test_memory_*.py
    ├── contract/test_memory_*.py
    └── integration/test_012_memory_*.py
frontend/src/
├── api/memories.ts
├── pages/MemoriesPage.tsx
└── App.tsx
```

**Structure Decision**: 沿用现有 `backend/src/rag_mcp` Python 包、Alembic 和分层 pytest 结构，以及 `frontend/src` React 管理应用。规范中列出的 migration 名称表示建议编号；实施前按当前 Alembic head 选择唯一后继 revision，不覆盖现有 migration。`fusion/rrf.py` 为既有文件增量扩展，旧 dense/sparse/graph 调用行为保持兼容。

## Complexity Tracking

无 Constitution Check 例外；无需复杂度豁免。
