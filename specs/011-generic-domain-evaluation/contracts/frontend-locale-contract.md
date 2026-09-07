# Contract: 前端语言资源层（frontend/src/i18n，011）

**Branch**: 011-generic-domain-evaluation | **Date**: 2026-09-07 | **Spec**: [spec.md](../spec.md) | **Research**: R10

本契约固化前端管理界面中英文切换的范围、键命名、回落语义与零残留验收口径。范围严格限于前端自产文案（FR-029）；后端错误提示与 MCP 契约零改动（FR-031）。

## 1. 范围（翻译对象）

**纳入翻译**（前端自产用户可见文案）：
- 导航与页面标题、表格列名、按钮文案、表单标签与占位符、操作反馈提示（message.success/error/info 的前缀部分）、确认对话框（okText/cancelText/title）、空状态、状态徽标文案。
- 前端框架组件内置文案（表格分页、日期选择、模态确认等），经 antd ConfigProvider locale 覆盖（zhCN / enUS）。

**排除翻译**（原样展示，FR-029）：
- 后端返回的错误消息（如 err.message、SSE 事件的 data.message、API error body）。
- API 响应内容与领域数据：项目名、文件名、slug、domain_key、格式名、状态码（KnowledgeSource.status / Project 字段等）。
- 前端自产前缀与后端消息拼接处：仅前缀部分翻译，后端片段原样（混合语言为预期形态，见 Edge Cases）。

## 2. 资源层结构

~~~text
frontend/src/i18n/
├── index.ts   # LocaleProvider（React Context）+ useLocale() + t(key) + localStorage 持久化（键 rag-mcp.locale）
├── zh.ts      # 中文资源（类型化 Record<Key, string>）
└── en.ts      # 英文资源（现状硬编码文案迁移为值）
~~~

- 键命名按页面分组：projects.* / projectDetail.* / domainProfiles.* / common.*。
- 类型化：t(key) 的 key 参数为联合类型（keyof typeof zh），编译期拦截缺失键。

## 3. 切换与持久化语义

- 默认语言英文（与现状一致、存量使用者零破坏）；浏览器语言自动检测为可选增强（默认不做）。
- 切换即时生效（内存态 Context 更新 + ConfigProvider locale 联动），无需刷新或重启后端。
- 持久化：localStorage 键 rag-mcp.locale，值 zh | en；损坏/缺失回落英文（不报错、不阻断加载）。

## 4. 回落语义（确定性，宪法 VI 精神）

- 语言资源缺失键：回落英文值（en.ts 为基线字典）；若两语言均缺该键，呈现键名字符串（绝不呈现空字符串、绝不崩溃）。
- 后端消息：原样展示（不回落、不替换、不翻译）。

## 5. 零残留验收口径（FR-030 / SC-011）

- 中文态：全页面前端自产文案英文残留 = 0；英文态：中文残留 = 0。
- 覆盖页面：ProjectsPage / ProjectDetailPage / DomainProfilesPage + App 头部。
- 框架组件文案：antd locale 随语言切换（分页、日期、确认按钮等）。
- 后端消息与领域数据：切换前后字节级不变（原样展示）。
