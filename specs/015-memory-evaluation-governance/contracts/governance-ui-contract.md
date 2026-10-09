# 治理 UI 契约（015）：六视图、scope 显式过滤、强确认与单条边界

**Branch**: 015-memory-evaluation-governance | **Date**: 2026-10-09 | **Spec**: [../spec.md](../spec.md) | **Research**: [../research.md](../research.md)（R10/R11）

> 本契约固定管理面治理 UI 的**可机器复核**形态。房规沿用既有前端：React 18 + antd 5（已装 5.29.3）+ `frontend/src/api/*` REST 客户端 + `hooks/useSSE`，中英文案经 `frontend/src/i18n/{en,zh}.ts`（`en` 为键集基线，缺 `zh` 键即 `tsc -b` 报错）。

## 1. 六视图 + 统计面板

| # | 视图 | 承载 FR | 必需交互 | 端点 |
|---|---|---|---|---|
| ① | 浏览 | FR-036 | 六维过滤（域/分型/状态/provenance/会话/显著性）+ 分页（每页 20） | `GET /api/memories?scope_ref=…&…` |
| ② | 治理 | FR-037 | 下线 / 显式清理（**唯一清理路径**）；影响面预览 → **强确认** → 结果 + 审计指针 | `POST /api/memories/retire`、`POST /api/memories/purge` |
| ③ | 回滚 | FR-039 | 目标选择（时间点/事件点）→ 影响面预览（受影响投影与条目计数）→ **强确认** → 结果 + 审计指针；**MCP 面不可达** | `POST /api/memories/rollback` |
| ④ | 投影重建 | FR-040 | 按投影与/或按域触发 → 重建结果 + 各投影一致性校验报告；失败显式呈现 | `POST /api/memories/rebuild`、`GET /api/memories/rebuild/audit` |
| ⑤ | 晋升 | FR-041 | 候选队列浏览 + 显式人工晋升；展示候选依据/去向/原记忆保留关系；**无自动晋升入口** | `GET /promotion-candidates`、`POST /promote`、`GET /promotions/{task_id}` |
| ⑥ | 巩固报告 | FR-042 | 运行列表与详情（运行标识/域/窗口/输入规模/提案与裁决/产出/状态/保留期/失败与拒绝原因）；域 `memory_policy` 编辑（非法值失败闭合） | `GET /consolidation/runs`、`GET /consolidation/runs/{run_id}`、`GET/POST /policy` |
| 附 | 统计面板 | FR-044/SC-016 | 域级计数与分布（**无正文**） | `GET /api/memories/stats?scope_ref=…` |

容器：`MemoriesPage.tsx` 用 antd `Tabs` 承载（仓库首次使用该组件；`App.tsx` 保持四条扁平路由不变，`/memories` 一个入口）。

## 2. scope 显式过滤交互（"无全局记忆正文视图"的机器可验契约）

1. **域选择为必选门**：未选择域时六视图与统计面板一律渲染空态（文案 `memories.noScope`），**且不发起任何返回正文的请求**。
2. **切视图不得重置域选择**：`Tabs` 切换不得清空 `scope`，避免切换瞬间出现无域请求。
3. **过滤只能收窄**：浏览视图的六维过滤参数一律与当前 `scope_ref` 同时发送；不存在"清空域以跨域浏览"的路径。
4. **双层防护**：前端 `if (!scope) return;` + 后端 `GET /api/memories` 的 `scope_ref: Query(min_length=1)`（缺省 422）——"无域正文列表"在结构上不可达。
5. **可验断言（Playwright 路由打桩）**：未选域时对 `/api/memories?**` 与 `/api/memories/stats` 的**请求次数为 0**；页面文本中不出现任何记忆正文摘录。

## 3. 强确认（`ConfirmActionModal`）

- 适用路径：`purge`、`retire`、`rollback`（FR-037/FR-039）。
- 语义：弹窗内需**逐字输入目标确认值**方使提交按钮可用——清理/下线输入 `memory_id`；回滚输入目标 `event_point`（或所选时间点字符串）。
- 弹窗同时展示影响面预览：受影响条目计数 + 受影响投影与各投影计数。
- 提交后展示结果与审计指针（回滚/清理：权威事件 `event_id` + `request_id`；重建：`request_id` 与 `GET /rebuild/audit` 可查）。
- **不得**以单次点击型确认（`Popconfirm` / `Modal.confirm`）替代；`SC-014` 对"缺强确认即可提交"计为失败。

## 4. 单条边界与批量禁止

- 首期治理动作**仅支持单条**；回滚**仅支持单次单目标**。
- MUST NOT 提供批量入口：无 `Table.rowSelection`、无 `Checkbox` 批量选择、无批量 API 调用、无"全选并清理"路径。
- 批量列为后续触发条件（spec 范围外）。

## 5. SSE 的使用边界（既有局限，如实记录）

- 复用 `hooks/useSSE`，单一 topic（`scope:<scope_id>`），任意事件即重取当前视图 REST 数据——沿 `ProjectDetailPage` 模式。
- **SSE 不作为正确性依赖**：数据正确性由"挂载时拉取 + 每次治理动作后重取 + 手动刷新按钮"保证。
- 既有局限（本 Feature 不修复、不伪称已生效）：
  1. `api/sse.py::publish_event` 在 `backend/` 内无任何调用点，当前流只发 `heartbeat`（`data: ""`，被 hook 的 `JSON.parse` 静默丢弃）；
  2. `hooks/useSSE.ts` 以重复 `topics` 参数发送，而后端以 `topics: str` + 逗号分隔解析，多 topic 只有第一个生效，故只传一个 topic；
  3. hook 的 `connect` 依赖为空数组，首挂载后不再重订阅，冷启动下 `scope:<id>` 实际未订阅。
- 为记忆治理事件接线 publisher 会改动 006 的 SSE 面与 `frontend/src/types/index.ts` 的闭合事件联合，超出"不重建已交付能力"的边界——列为后续触发条件。

## 6. 其他不可协商项

- 治理动作经服务端校验，**MUST NOT 直写权威日志或投影**（UI 只调 REST）。
- 中英文案齐备（`en.ts` 与 `zh.ts` 键集必须一致，由 `LocaleDict` 类型强制）。
- 后端错误文案与域数据**原文呈现**（FR-029 既有规则）：翻译前缀 + 原样错误正文，既有 `frontend/tests/memory.spec.ts` 对 `MEMORY_WRITE_UNAVAILABLE` 出现在 Alert 中的断言必须继续通过。
- 既有页面行为零破坏：`ProjectsPage` / `ProjectDetailPage` / `DomainProfilesPage` 不改。
