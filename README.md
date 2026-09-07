# docsToCode

面向 ChatGPT App（原 Codex）、DeepSeek Harness 与 Claude Code 的多知识域 RAG MCP 检索系统。

## 已交付系统（001–011，2.0 收官）

后端（Python 3.12 / FastAPI / LangGraph / PostgreSQL / Qdrant）：

- **MCP 检索四路径**：Dense（bge-m3）/ Hybrid（BM25+jieba 稀疏 + RRF 融合 + bge-reranker-v2-m3 重排）/ Graph Enhanced（硬关系扩展 + 结构权重）/ Agentic（九步状态机编排）
- **多知识域**：双轴模型（project/public 结构轴 × se-project/generic/personal/legal 语义轴），domain_scope 三形态寻址（ID/slug/type:name）+ list_knowledge_domains 发现
- **转换层摄入**：FormatHandler 注册表统一分发，markdown/java/openapi/ddl/go/python/word/pdf 原生解析 + txt/html/csv/json/yaml/xml/xlsx/pptx/eml 九格式转换层；凭据脱敏；结构感知切片与定位前缀（标题路径/page:N/sheet:/path:/msg:）
- **图关系**：GraphExtractor 插件注册表（Java 调用图、DDL 外键、交叉引用），确定性硬关系 + 受益闸口
- **运行时**：writer/reader 双实例形态、实例注册、超时档案、目标宿主兼容（DeepSeek Harness 必过参考客户端）

前端（React 18 + TypeScript + antd 5）：Web 管理端（项目/知识源/域档案管理），中英文切换。

评测体系（eval/）：固定评测集（001–006 各口径 + 011 两域数据集）、基线与对照报告、六组全集回归口径、硬指标三件套实测（跨域串库=0 / Schema 100% / 定位 100%）、可重复性检查（非延迟指标 1% 容差）。重建与重跑方法见 [eval/README.md](./eval/README.md)。

## 治理与规格

- GitHub Spec Kit v1.0.1 脚手架（/speckit-* 工作流：clarify → plan → checklist → tasks → analyze → implement → converge）
- 项目 Constitution（v1.3.0：十一条核心原则 + 五条硬约束，含 Domain Neutrality）
- 2.0 演进蓝图（通用 RAG 演进蓝图.md，批准即冻结为架构基线）与定稿核销记录（docs/2.0-finalization.md）
- 全部 Feature 规格（specs/001–011）：spec / plan / research / data-model / quickstart / tasks / contracts

## 当前边界

- MCP 检索面只读（get_evidence / search_knowledge / list_knowledge_domains 均为只读工具）。
- 单管理员、loopback 部署（认证多用户、Neo4j、OCR 等按蓝图 §9 触发条件演进）。
- 检索质量优化按对照基线立项（后续 Feature 进 plan 前须相对基线声明目标）。

系统总蓝图位于：

`docs/superpowers/specs/2026-08-26-ai-engineering-rag-mcp-design.md`
