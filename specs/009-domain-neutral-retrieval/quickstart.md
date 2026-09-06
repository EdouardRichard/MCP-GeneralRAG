# Quickstart: 检索编排域中立化（009）验证指南

**Branch**: `009-domain-neutral-retrieval` | **Date**: 2026-09-06

本文档给出 009 的可运行验证场景：se-project 提示词等价性闸口、动态 relation_directions 词表、task_context.activity、SourcePosition 前缀规范表、去 project 措辞、提示注入防护边界、以及三 Agent 回归。回归闸口接线以既有 eval 运行器为准（005 agentic 44 条 + 004 确定性 37 条）。

## 0. 前置条件

- PostgreSQL 已迁移（含 007 的 domain_profiles / knowledge_scopes.domain_key）。
- 已发布知识版本（沿用 001–006 语料 + 至少一个 generic 域功能夹具）。
- Qdrant 索引就绪。
- 后端依赖已安装（backend/ 下 venv）。
- eval 数据集：eval/eval_dataset.json（确定性集，004 图集 37 条）、eval/agentic_eval_dataset.json（005 agentic 44 条）。

## 1. 回归闸口：005 agentic（44 条）

```
python eval/run_agentic_comparison.py \
    --dataset eval/eval_dataset.json \
    --agentic-dataset eval/agentic_eval_dataset.json \
    --output eval/agentic_comparison_report.json
```

**预期**：报告三闸门通过（SC-001/SC-002/SC-015）+ 硬约束（串库=0、Schema 合法率=100%、定位率=100%）；相对基线非延迟指标（recall/mrr/ndcg）在 1% 相对容差内一致。se-project 域下规划行为与 1.0 等价。

## 2. 回归闸口：确定性集（004 图集 37 条）

```
python eval/run_graph_comparison.py \
    --dataset eval/eval_dataset.json \
    --output eval/graph_enhanced_comparison_report.json
```

**预期**：图增强路径三闸门通过，非延迟指标 1% 相对容差内一致（动态 relation_directions 词表不改变 se-project 图扩展行为）。

## 3. se-project 提示词等价性（分层，research R5）

3a. **文本层（静态断言）**：单测断言 se-project 覆盖片段（config/domain_profiles.py 的 SE_PLANNER_PROMPT）与 1.0 DECOMPOSE_SYSTEM_PROMPT 全文逐句等价。

3b. **结构输出层（逐条比对）**：设置 AGENTIC_LLM_CACHE_PATH 启用响应缓存，先后录 1.0 与 009 的 005 agentic 44 条规划输出，断言每条 signals / relation_directions 一致（temperature=0.0 + 缓存字节级复现）。

3c. **终态指标层**：见 §1 回归闸口（recall/mrr/ndcg 1% 容差）。

## 4. 动态 relation_directions 词表（功能验收）

- **se-project 单域**：relation_directions 词表 = [calls, called_by, fk_references, fk_referenced_by]；signals 枚举含 graph。
- **generic（无图）单域**：词表为空；NODE_SCHEMA 省略 relation_directions/graph_hop；signals 枚举仅 [dense, sparse]；graph 信号产出数 = 0。
- **异构（se-project + generic）**：词表取并集（4 值）；系统提示词回退域中立基础模板（不用 SE 覆盖片段）。

对应单测：backend/tests/unit/test_query_planner_*.py（_build_node_schema、_validate_directions、fallback 省略、提示词解析）。

## 5. task_context.activity（契约验收）

- 仅传 current_file/current_symbol/work_phase 的旧请求：字段名/类型/枚举逐字节不变，行为不变。
- 传 activity 的新请求：被接受、进入 task_context、不改变检索行为。

契约校验：backend/tests/contract/（mcp-search-input.schema.json 含 activity、当前工作字段标注编码域约定）。

## 6. SourcePosition 前缀规范表 + 去 project 措辞（契约/文案验收）

- common.schema.json SourcePosition 描述含定位前缀规范表（标题路径/page:N/符号路径/sheet:/path:/msg:），不再以 Java 符号为单例。
- evidence_service.py SCOPE_MISMATCH、retrieval_service.py gaps suggested_action 去 project 措辞；仅 project_scope 旧客户端错误码/消息逐字节不变。

## 7. 提示注入防护边界不变（research R3）

- 恶意上传不能改变控制流/工具选择/提示词脚手架（沿用 006/001 §15 验收集）。
- 域档案 prompt_overrides 注入内容不经 InjectionDetector、不与证据内容结构混同。
- evidence_analyst / context_orchestrator / injection_detector 既有 pytest 回归全绿。

## 8. 一键回归命令汇总

```
# 单测 + 契约
cd backend && python -m pytest tests/unit tests/contract -q

# 005 agentic 44 条
python eval/run_agentic_comparison.py --dataset eval/eval_dataset.json --agentic-dataset eval/agentic_eval_dataset.json --output eval/agentic_comparison_report.json

# 004 确定性 37 条
python eval/run_graph_comparison.py --dataset eval/eval_dataset.json --output eval/graph_enhanced_comparison_report.json
```
