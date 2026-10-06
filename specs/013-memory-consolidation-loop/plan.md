# Implementation Plan: 记忆巩固回路

**Branch**: `main`（实际Git分支；本次不创建分支） | **Date**: 2026-10-06 | **Spec**: [spec.md](spec.md)

**Feature Directory**: `specs/013-memory-consolidation-loop`

**Input**: 已澄清的013规格与用户指定模块/研究约束。setup_plan返回的逻辑Feature名与Git实际分支分开记录。

## Summary

实现仅writer管理面启动的离线巩固：维护空闲/手动/量阈值共用scope资格，稳定窗口选取合格episodic和独立参考集；第四Agent提出四类建议，纯裁决器批准effects，可信服务再复验并追加权威事件，沿012六投影发布。模型故障保留确定性去重/TTL/可证明归并。批准链接与语境永久保存，可无模型重建；候选只标记，晋升须人工显式动作并复用上传摄入。默认关闭；固定≥6条实域子集、零容差安全、001–012回归与严格缓存重放决定默认启用资格。

研究见 [research.md](research.md)，模型见 [data-model.md](data-model.md)，接口见 [contracts/README.md](contracts/README.md)，验收见 [quickstart.md](quickstart.md)。不重建012基座、005三Agent、006maintenance，不实现014检索集成或015完整UI。

## Technical Context

**Language/Version**: Python≥3.12；沿现有异步/类型模式；本期无前端新增。

**Primary Dependencies**: FastAPI≥0.115、SQLAlchemy2 async/asyncpg、Alembic、Pydantic2、jsonschema Draft202012、httpx、既有AgentBase/LLMClient、LangGraph/LangChain baseline；无新服务依赖。

**Storage**: PostgreSQL保存append-only memory_events、域策略、独立资格与7天运行观察；现有Qdrant/file/summary/salience投影；data_root保存人工晋升上传文件。跨存储沿012verified manifest协议，不声称分布式ACID。

**Testing**: pytest/pytest-asyncio、JSONSchema、真实PG/Qdrant集成、既有MCP target-host验收；eval两轮record/replay与transport阻断验证零网络。

**Target Platform**: Windows开发与现有Python服务部署；单writer/多reader；管理HTTP默认loopback；数据库写入测试串行。

**Project Type**: RAG MCP backend管理REST+离线任务；Distiller不入检索图、不增加MCP工具。

**Performance Goals**: 前台同步等待Distiller=0，原读取数量/字数/超时不增加；默认32来源/64参考/64提案，模型30秒/1次、运行300秒，最多2个scope worker。资格TTL120秒/心跳20秒，提交≤30秒；扩展默认1hop/8节点且受原总预算。

**Constraints**: scope活动唯一+完整token提交fence；quarantined输入0；软推翻hard0；自动正身写0；distilled溯源100%；裁决器唯一批准；link/context派生无模型重建；context不进检索；policy缺失/关闭不触发普通巩固。可信必要支持失效维护仅可取得同一资格执行受裁决invalidate，完整lease/fence不豁免；扩展需部署登记的当前绑定三闸证据。策略校准见research§2，证明读取见contracts/gate-proof.md。

**Scale/Scope**: 沿每scope默认5000记忆配额；一运行一个冻结窗口内有界批次；未成功/未处理源永久可恢复。新增2张运行表，迁移既有link与entry列；稳定晋升身份沿管理grant+既有ProcessingRun。

## Constitution Check

研究前：PASS，无豁免。设计后：PASS，以下契约与验证责任已定义；表示规划符合约束，不代表实现指标/测试已通过。

| 原则 | Phase0依据/Phase1落实 | 判定 |
|---|---|---|
| I Explicit Scope | admission/source/target/evidence/commit/expand/promotion同域复验，无默认域 | PASS |
| II Domain Facts | 不跨域归并，不以公共/推断替代域hard，保留冲突 | PASS |
| III Uncertainty | distilled/llm_proposed不升权，证据缺口/降级/冲突明确 | PASS |
| IV Locatable Evidence | 永久episode/event链与已有corpus位置/版本，晋升逐条归因 | PASS |
| V Data/Control | 不可信JSON、净化新增文本，Agent无写句柄 | PASS |
| VI Deterministic Control | 纯裁决、同事务重裁决、独立确定规则 | PASS |
| VII Interface Evolution | proposal/event/report独立版本，管理新增接口不改旧MCP，新增迁移 | PASS |
| VIII Version Non-Mixing | 既有embedding/version，context不入向量，派生可重建 | PASS |
| IX Synchronous Results | MCP直接返回；仅管理长任务202，前台无Distiller | PASS |
| X Evaluation | 004双指标3%+非降、005严格cache replay、安全/旧集三闸 | PASS |
| XI Domain Neutrality | 009声明prompt/独立memory词表，无领域特例/默认项目 | PASS |
| XII Memory Loop | hard矩阵、五元/源链、supersede、人工晋升 | PASS |
| XIII Trajectory | event唯一authority、六轴、SQL/Python parity、非空重建/传播/rollback | PASS |

六硬约束逐项复核：跨域泄漏0；未解析scope拒绝；上传/记忆不控制执行；MCP schema100%；证据可定位100%；六投影重建/删除/来源/rollback一致100%。设计无违反；实现任一不满足阻断发布，不能以默认关闭豁免。

## Project Structure

### Documentation (this feature)

```text
specs/013-memory-consolidation-loop/
  spec.md
  plan.md
  research.md
  data-model.md
  quickstart.md
  tasks.md
  checklists/requirements.md
  contracts/
    README.md
    distiller-output.schema.json
    consolidate-event.schema.json
    benefit-report.schema.json
    gate-registry.schema.json
    gate-proof.md
    management-api.md
    recall-extensions.md
    pipeline-contract.md
    evaluation-contract.md
```

tasks.md已按用户指定的八个Phase生成；本轮一致性修复只更新契约与任务描述，不执行实现任务。

### Source Code (repository root)

```text
backend/src/rag_mcp/
  agents/memory_distiller.py                    # 第四Agent
  orchestration/consolidation_pipeline.py      # 四段协调
  services/consolidation_adjudicator.py        # 纯规则/effect矩阵
  services/consolidation_runtime.py            # admission/fence/recovery
  services/consolidation_gate.py               # 只读登记加载/共享报告与绑定校验
  models/consolidation_run.py                  # 资格/append-only观察
  models/memory_link.py                        # 迁移既有模型映射
  models/memory_views.py                       # 兼容re-export
  models/memory_projection.py                  # context/candidate/pointer列
  models/domain_profile.py                     # 独立记忆词表
  services/memory_service.py                   # 批准event group提交/恢复
  services/memory_reducer.py                   # v2/派生registries
  services/memory_projection_store.py          # typed link/context/六投影
  services/memory_validators.py                # 历史链/live support/净化
  services/memory_policy.py                    # 显式策略
  services/memory_reader.py                    # gated扩展/显示context
  runtime/projection_rebuild.py                # full/snapshot/delta
  services/maintenance_service.py              # 挂钩/恢复/清理
  services/knowledge_source_registration.py    # 共享现有上传步骤
  services/ingestion_service.py                # 使用预建ProcessingRun
  services/memory_governance.py                # 晋升pointer grants
  api/memory.py                               # 管理运行/候选/晋升
  api/knowledge_sources.py                     # 共享注册/重试指针
  mcp/recall_memory.py                         # 显式只读增强flags，旧默认兼容
  config/domain_profiles.py                    # 009通用prompt/声明
  config/__init__.py                           # Settings的可选闸口登记路径
  server.py                                   # idle计数/有界worker
backend/alembic/versions/
  0095_memory_consolidation_loop.py            # 当前0094后新增SQL/迁移
backend/tests/
  unit/test_consolidation_*.py
  unit/agents/test_memory_distiller.py
  contract/test_consolidation_*.py
  integration/test_013_*.py
eval/
  run_consolidation_comparison.py
  consolidation_eval_dataset.json             # 实施时冻结真实快照/标签
  consolidation_eval_support.py               # 等价adapter/replay/report
  runs/<unique-run>/consolidation-*.json
```

**Structure Decision**: 保持backend ownership；Agent/纯规则/服务边界分开，无新仓库/检索引擎。typed模型沿用户路径、旧表/导入兼容；upload helper只抽取必需共享步骤。实施时复核migration head，不重写部署历史。

## Phase 0: Research Decisions

research已覆盖注入§5、hard矩阵§6、词表/依赖§8、重建§9、六查询统计/缓存§11、故障注入§12；并固化策略/资格/fence、永久窗口、双重reducer、晋升幂等。台账原文缺失不杜撰，用户约束与蓝图可核验部分已采用。

## Phase 1: Implementation Groups

以下为供tasks阶段拆分的单元/依赖，不是实施完成声明。

| 单元 | 产出 | 依赖 | 独立验证 |
|---|---|---|---|
| A 契约/域配置 | policy、memory词表、typed输入、净化字段 | 012/007/009 | 四动作/unknown/finite、旧默认/内置治理 |
| B Authority/投影 | v2 consolidate/grant、双重replay、links/context/潜在消费、原子组/rollback版本 | A | populated迁移、逐步parity、非空full/delta、pending |
| C Runtime/选择 | 资格唯一、DB clock fence、window seal/retry、三触发 | A,B | DB竞争/两scope、接管/旧holder0、边界/预算 |
| D Distiller/裁决 | ROLE/NODE_SCHEMA、通用prompt、有界模型/规则、hard/confidence/quota | A | 无DB纯矩阵、注入、fallback二次校验、无模型故障对照 |
| E Pipeline/落库 | 四段接线、事务再裁决、event group/六投影、追加审计 | B,C,D | 前四类新增E2E、治理变更barrier、投影失败不可见 |
| F 派生/晋升 | 客户端opt-in扩展/context、无新episode的纯失效维护、人工上传/稳定任务 | B,E | 旧默认字节/排序、live/history、无自动正身、幂等晋升 |
| G Eval/发布 | 固定六query、等价adapter、record/replay、三闸/旧全集 | E,F | 双指标3%、zero-net失败重放、012八项、AOEP≥2各项、旧全集 |

先建立契约/迁移兼容验证，再接有权限隔离的链。质量评测使用同原始快照隔离副本。默认启用判定与合法policy发布分开，报告不自动改开关。

## Requirement Coverage

| 要求 | 设计/验证 |
|---|---|
| FR-001/002/003 | C/E runtime/token/API；SC-002/012 |
| FR-004/005/006 | A/B/C window/消费反连接/严格预算；SC-003/011 |
| FR-007/008/009/010 | A/D四动作/ROLE/注入/无模型对照；SC-004/005/006 |
| FR-011/012/013 | D/E唯一裁决/再裁决/全effect hard矩阵；SC-005 |
| FR-014/015/016/017 | B/E历史链/单指针/v2组/pending；SC-006/011 |
| FR-018/019/020/021 | A/B/F revision唯一/词表/live传播/扩展门控；SC-007/008/012 |
| FR-022/023 | B/F具体context/无LLM重建/rollback/排序恒等；SC-007/008 |
| FR-024/025/026 | F候选硬锚/人工共享上传/稳定task；SC-009 |
| FR-027/028/029 | C/E append-only/usage/TTL与资格分离；SC-010 |
| FR-030/031/032 | G 2+2+2/双指标AND/cache证据/三闸；SC-001 |
| FR-033/034/035 | E/F/G六E2E/012八项/五不变量各≥2/旧集与host；SC-013 |

US1–7由C、D/E、D/B、B/F/G、B/F、F、C/E/G覆盖。SC-001–013均有对应观测，不能以文档/mock通过替代发布/网络/host实证。

## Validation And Delivery Gates

1. 契约/纯规则：JSONSchema、引用/数量/置信边界、hard全effect、域中立/注入、fallback与normal确定性部分一致。
2. 数据库/轨迹：真实PG活动唯一/最终时钟fence；SQL/Python逐步parity；六投影receipt；非空升级/rebuild/TTL/delta/rollback；pending幂等/长链。
3. 工作流：三触发/两scope/reader拒绝；窗口边界/预算/部分失败；候选不自动正身；人工晋升重复/故障/恢复；LLM迟到0提交。
4. 读取：扩展默认关、policy+三闸；部署登记文件/报告哈希/当前绑定/有效期/扩展variant验证，坏证明或删除登记立即不授权且不增预算；合法端点/降级；context A/B候选排序恒等；历史退场不误伤、关闭时可信必要支持维护仍受完整裁决/fence。
5. 发布：真实域冻结六query、record/replay零网络、MRR/nDCG≥3%及非降、硬安全零容差、012八E2E、五不变量各≥2、001–012全部验收与host。质量/复现不完整默认关闭；安全失败阻断。

原规划交付Phase1设计，后续已生成tasks并完成一致性分析；本轮修复分析发现的I1/U1，未来实施步骤见quickstart。当前无before_plan/after_plan扩展配置。

原规划验证（历史记录，2026-10-06）：3份Draft202012 Schema结构及全部引用可解析，35个正反契约例通过，24个本地文档链接有效，FR-001–035完整覆盖，无模板待填项。独立审阅发现的持久字段兼容、纯重放/发布区分、无episode依赖维护、原子组/回滚重试、严格LLM重放、incomplete报告、同批输出引用和组预算问题已修正。该规划阶段未执行生产代码、功能E2E或受益/回归评测，当时尚未生成tasks.md。

一致性修复验证（2026-10-06）：I1统一普通开关门控与可信必要支持失效维护的窄例外、完整资格/fence及审计；U1补齐只读登记/报告哈希/当前绑定/有效期/加载责任，报告版本升为013.2。独立复核提出的T103质量失败分支矛盾亦已修正。当前4份Draft202012 Schema及116个引用有效，38个登记/绑定/报告正反样例通过，53个本地文档链接有效；104任务编号/未开始状态/31并行标记保持，依赖均指向前置任务，35 FR与13 SC覆盖100%。评审清单38个已有勾选未改动。本轮仅修正文档/Schema，未执行生产功能、E2E、真实质量或全集回归。

## Complexity Tracking

无宪法例外。必要复杂性来自已有双重重放/revision/跨存储发布；独立资格解决拒绝与接管，永久window grant解决TTL后恢复，预建ProcessingRun解决晋升幂等，未另建事实authority或摄入管线。
