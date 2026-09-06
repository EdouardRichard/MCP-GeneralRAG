# Implementation Plan: Retrieval Orchestration Domain Neutralization（检索编排域中立化）

**Branch**: `009-domain-neutral-retrieval` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-domain-neutral-retrieval/spec.md`

## Summary

将检索编排（query_planner）从硬编码软件工程（SE）假设改造为域中立：基础系统提示词重写为域中立模板（信号选择规则以"标识符/定义/关系"抽象表述），SE 举例与关系词表移入 se-project 域档案 prompt_overrides，运行时按请求作用域解析到的域档案注入；relation_directions 允许值与默认方向集由域档案 graph_relations 词表动态派生（无图档案省略字段）；task_context 契约新增可选自由字符串 activity 并整体域中立化；SourcePosition 契约描述由 Java 符号单例替换为定位前缀规范表；gaps/错误文案去 project 措辞；evidence_analyst/context_orchestrator/injection_detector 确认已中立并仅回归。硬约束（显式知识域引用、跨域串库=0、Schema 合法率=100%、来源可定位率=100%、提示注入防护边界不变）与对照评测（005 agentic 44 条 + 确定性 37 条无回归、se-project 提示词等价性闸口）全程保持。

## Technical Context

**Language/Version**: Python 3.11+（后端编排/契约）；前端 TypeScript/React（本期不涉及）

**Primary Dependencies**: jsonschema（Draft202012Validator 动态 Schema 构造）、SQLAlchemy（async，domain_profiles/knowledge_scopes）、httpx（LLMClient，无域假设）、FastMCP（工具契约）、LangGraph/LangChain（编排基线，宪法架构约束，本期不改）

**Storage**: PostgreSQL（domain_profiles、knowledge_scopes 既有表，无新表）；Qdrant（不变）

**Testing**: pytest（unit + contract：backend/tests/unit、backend/tests/contract）；eval 运行器（eval/run_agentic_comparison.py = 005 agentic 44 条；eval/run_graph_comparison.py = 004 确定性 37 条）

**Target Platform**: Linux server（Python MCP 后端）

**Project Type**: MCP server 后端服务（检索编排域中立化，无新前端）

**Performance Goals**: 无新增检索质量对照义务；005 agentic 与确定性集非延迟指标在 1% 相对容差内一致（等价性闸口，非质量提升）

**Constraints**: 跨知识域串库 = 0；MCP Schema 合法率 = 100%；来源可定位率 = 100%；提示注入防护边界不变（域档案注入属可信配置、与证据内容结构隔离，宪法 V/1.0 §15）；project_scope-only 旧客户端逐字节不变（007 FR-009 承接）

**Scale/Scope**: 2 个内置域档案（se-project/generic）+ 自定义档案；请求作用域可跨多域（异构回退）；回归集 005 agentic 44 条 + 004 图集 37 条

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则/约束 | 判定 | 说明 |
|---|---|---|
| XI 领域中立 | ✅ | 本 Feature 即该原则的编排层落地：移除 query_planner.py 硬编码 SE 假设，域差异经 DomainProfile 声明式表达 |
| V 数据与控制分离 | ✅ | 域档案 prompt_overrides 属可信配置（内置只读 + 管理面自定义），注入走确定性控制器可信通道，与不可信证据内容结构隔离；injection_detector 继续只处理证据（research.md R3） |
| VI 确定性控制优先 | ✅ | planner 输出仍为 schema 校验后的 INPUT，状态机拥有跳转权；动态词表/提示词由确定性控制器组装 |
| I 显式知识域引用 | ✅ | 承接 007（project_scope/domain_scope 任一形式，缺失拒绝），009 不改变解析语义 |
| IV 可定位证据 | ✅ | SourcePosition 描述更新为前缀规范表（文档级，不改结构）；来源可定位率保持 100% |
| VII 接口独立演进 | ✅ | 契约变更全部 additive（activity 可选字段、SourcePosition description 文档级、错误文案），无破坏性 Schema 结构变更 |
| 硬约束：跨域串库=0 | ✅ | 动态词表/提示词不改变 scope 隔离；检索仍按 scope_ids 隔离（research.md R4） |
| 硬约束：Schema 合法率/定位率=100% | ✅ | 动态 NODE_SCHEMA 仍为合法 JSON Schema；MCP 输出契约零结构改动 |
| 硬约束：上传内容不得为控制指令 | ✅ | 域档案注入属可信配置而非上传内容；证据经 injection_detector 隔离（research.md R3） |

**Gate 结论**: 无违宪项，无需 Complexity Tracking 豁免。

## Project Structure

### Documentation (this feature)

```text
specs/009-domain-neutral-retrieval/
├── plan.md              # 本文件
├── research.md          # Phase 0 输出（提示注入防护/多域并集边界/等价性口径决议）
├── data-model.md        # Phase 1 输出（动态词表/提示词解析/契约实体）
├── quickstart.md        # Phase 1 输出（回归闸口接线：005 agentic 44 + 确定性 37）
├── contracts/           # Phase 1 输出（common.schema.json、mcp-search-input.schema.json）
└── tasks.md             # Phase 2 输出（/speckit-tasks，本命令不生成）
```

### Source Code (repository root)

```text
backend/src/rag_mcp/
├── agents/
│   ├── query_planner.py          # 提示词模板化 + NODE_SCHEMA 动态构造 + 词表派生（核心改造）
│   ├── llm_client.py             # 已域中立，仅确认（不改）
│   ├── capability_router.py      # 已域中立，仅确认（不改）
│   ├── evidence_analyst.py       # 已中立，仅回归（不改）
│   ├── context_orchestrator.py   # 已中立，仅回归（不改）
│   └── injection_detector.py     # 已中立且边界不变，仅回归（不改）
├── config/
│   └── domain_profiles.py        # SE_PLANNER_PROMPT 升级为逐句 1.0 全文；新增中性基础模板 + 词表派生助手
├── services/
│   ├── domain_profile_service.py # 新增 resolve_planner_config(scope_ids) 助手
│   ├── retrieval_service.py      # gaps 文案去 project 措辞
│   └── evidence_service.py       # SCOPE_MISMATCH 文案域中立化
├── orchestration/
│   └── entry.py                  # 作用域解析后解析域档案 → 注入 context（domain_planner_config）
└── mcp/
    └── search_knowledge.py       # task_context 描述域中立化 + activity 透传说明

backend/tests/
├── unit/          # query_planner 动态词表/提示词解析单测；fallback 无图省略
└── contract/      # mcp-search-input（activity）、common（SourcePosition 表）契约校验
```

**Structure Decision**: 单后端 Python 项目（沿用 001–008 既有 layout）。无新模块目录——改造集中在 agents/query_planner.py 与 config/domain_profiles.py，注入接线在 orchestration/entry.py 与 services/domain_profile_service.py；契约快照落在 specs/009-*/contracts/。

## Complexity Tracking

> 无违宪项，本节不适用。
