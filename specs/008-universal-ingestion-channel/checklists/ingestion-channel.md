# Ingestion Channel Review Checklist: 通用摄入通道（FormatHandler 注册表 + 转换层）

**Purpose**: 评审 008 通用摄入通道的需求质量（完整性/清晰性/一致性/可测性/覆盖度），覆盖注册表完备性、转换层安全（宪法 V）、格式接受性、定位规范、DB 约束、评测义务、前端泛化七类关键面。

**Created**: 2026-09-06

**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) · [research.md](../research.md) · [data-model.md](../data-model.md) · [contracts/](./contracts/)

**Review Ownership**: 本清单为评审者持有的需求质量评审工件。仅当评审者判定该条需求质量标准已满足时方可勾选 `[x]`。

**Marker Semantics**: `[x]` 表示该条需求质量准则已经评审并满足；不代表实现工作已完成。

---

## 1. 注册表完备性（四处分发点收敛 + 错误消息单一事实源）

- [x] CHK001 四处分发点（格式检测 `_detect_format`、解析分派 `_parse_content`、二进制声明 `BINARY_FORMATS`、图提取分派）是否在 spec 中逐一点名并要求全部委托注册表？ [Completeness, Spec §FR-001]
- [x] CHK002 注册表条目必填字段（format 名/扩展名集/tier/binary 声明/解析器工厂或转换器规格/可选图提取器挂钩/定位前缀）是否完整列明，并与 plan/data-model 的 FormatHandler 定义一致？ [Consistency, Spec §FR-002, data-model §1]
- [x] CHK003 「注册表初始化失败 = 启动失败、不静默回落旧 if/elif」是否在 spec 中显式声明，而非仅在 plan 技术上下文中存在？ [Gap]
- [x] CHK004 错误消息「单一事实源」（由注册表统一生成、含可接受格式清单）是否明确到可判定四处入口文案一致？ [Clarity, Spec §FR-007, US1 AS3]
- [x] CHK005 新增格式「边际成本 ≤ 2 个文件」（SC-008）是否有可测定义——哪些文件计入、可选小适配器是否计入？ [Clarity, Spec §SC-008]
- [x] CHK006 图提取器「无挂钩格式不参与图提取」是否对 17 种格式逐一说明哪些有/无挂钩？ [Coverage, Spec §FR-006, Edge Cases]

## 2. 转换层安全（宪法 V：脱敏 + 注入检测 + 不可信数据边界）

- [x] CHK007 转换产物（Markdown IR）在脱敏前视为不可信数据、不得控制提示词/工具选择/权限/能力门控/状态机，是否在 spec 中明确且覆盖转换层路径？ [Completeness, Spec §FR-017]
- [x] CHK008 凭据脱敏顺序「转文本之后、切片之前」是否对转换层与原生层一致声明、无冲突？ [Consistency, Spec §FR-016]
- [x] CHK009 脱敏规则扩展至新格式凭据形态（EML 头/JSON/YAML/CSV 值）是否在 spec 中明确，且与「范围外：复用不修改规则」原条款不产生矛盾（范围外条款已同步更新）？ [Conflict, Spec §FR-017 vs 范围外]
- [x] CHK010 转换层内容是否明确进入既有**注入检测**（prompt injection defense）路径？spec 中是否有条款保证转换产物同样受注入检测而非仅脱敏？ [Gap, 宪法 V]
- [x] CHK011 「上传内容不得作为控制指令」硬约束是否对转换层格式显式映射（而非仅对原生层）？ [Traceability, Spec §FR-017, 宪法硬约束]

## 3. 格式接受性（域档案 supported_formats 与注册表一致性）

- [x] CHK012 域档案 `supported_formats`（generic 增补 9 新格式、se-project 保持 8 格式）是否在 spec 中声明，且与注册表 17 条目一致？ [Consistency, Gap, research §12]
- [x] CHK013 格式合法性的「注册表校验 + 域档案 supported_formats」双层关系是否明确，且两层不一致时的行为有定义？ [Clarity, Spec §FR-019]
- [x] CHK014 se-project 域是否允许摄入通用 9 格式——是仅 generic 域开放，还是 SE 域也开放？ [Ambiguity, research §12]
- [x] CHK015 `.json`/`.yaml`/`.yml` 的 OpenAPI 内容嗅探优先 vs 通用 json/yaml 回落，其判定顺序是否在 spec 中显式且可测？ [Clarity, Spec §FR-003, Assumptions]

## 4. 定位规范（每新格式 position_path 前缀）

- [x] CHK016 9 种新格式的 `position_path` 前缀是否逐一对应规范表（`sheet:`/`path:`/`msg:`/`# 标题路径`）？ [Coverage, Spec §FR-024, contracts/locator-prefixes]
- [x] CHK017 CSV 无工作表 → `sheet:` 名取文件基名（澄清 Q1），是否已落入 spec FR-024 并消除 xlsx/csv 的 sheet 名歧义？ [Clarity, Spec §FR-024]
- [x] CHK018 转换层定位粒度「转换后标题路径」且「不做原文档锚点还原」是否在 spec 中显式声明？ [Completeness, Spec §FR-025]
- [x] CHK019 定位前缀规范是否要求在 MCP 契约 `source_position` 描述中显式声明？ [Traceability, Spec §FR-024/FR-025]
- [x] CHK020 txt 的定位（文档级空 `section_path` 还是 `# <文件名>` 兜底）是否已定、不遗留？ [Ambiguity, research §14]

## 5. DB 约束（宽模式 + 应用层校验双层、String 扩容）

- [x] CHK021 三列（`knowledge_sources.format`/`chunks.chunk_type`/`retrieval_runs.format`）的 `String(32)` 扩容 + 宽模式 CHECK 是否在 spec 中逐列明确？ [Completeness, Spec §FR-018]
- [x] CHK022 应用层校验接管（注册表校验 format + L1/L2 词表 + 域档案校验 chunk_type）是否明确，且与 DB 宽模式的双层关系可测？ [Clarity, Spec §FR-019]
- [x] CHK023 存量 18 个 chunk_type 值「遗留合法、零迁移」是否明确（不迁移、不丢数据、无行为变化）？ [Completeness, Spec §FR-021, US3 AS4]
- [x] CHK024 迁移脚本沿用 `a1b2c3d4e5f6` 的 drop/add 模式、且 `downgrade()` 可回滚，是否在 spec/plan 中明确？ [Completeness, plan §Technical Context, research §8]
- [x] CHK025 L2 命名空间正则 `^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$` 是否在 spec 中明确，且与 DB 宽模式 pattern、L1 闭合集一致？ [Consistency, Spec §FR-020]

## 6. 评测义务（9 格式 × ≥2 条、003 回归、硬指标）

- [x] CHK026 每新格式 ≥2 条（≥1 自然语言 + ≥1 结构定位）是否在 spec 中量化且逐格式可判定？ [Measurability, Spec §FR-034, SC-003]
- [x] CHK027 003 既有 8 格式无回归的判定口径（Recall@K 精确、MRR/nDCG 1% 相对容差）是否明确？ [Clarity, Spec §FR-035]
- [x] CHK028 转换层契约测试固化 markitdown 行为（版本锁定）是否明确其可判定输出（Markdown IR / chunk_type / 定位标识）？ [Measurability, Spec §FR-036, SC-009]
- [x] CHK029 硬指标三件套（跨域串库 = 0、Schema 合法率 = 100%、来源可定位率 = 100%）是否在混合评测集（8 原生 + 9 新）上显式要求？ [Completeness, Spec §FR-037, SC-004/005/006]

## 7. 前端（accept/types 同步注册表）

- [x] CHK030 前端 `accept` 列表是否泛化至 9 新格式扩展名，且与注册表扩展名集一致？ [Consistency, Spec §FR-032]
- [x] CHK031 前端 `format` 联合类型是否泛化至全格式（不再停留 `'markdown' | 'java'`）？ [Completeness, Spec §FR-033]
- [x] CHK032 前端 accept/types 与注册表「单一事实源」是否建立同步机制，避免前端硬编码扩展名/类型再次漂移？ [Gap, Spec §FR-001 vs FR-032/033]

---

## Notes

- 仅当评审确认该条需求质量准则已满足时勾选 `[x]`；仍需澄清/更正/评审评估的保持未勾选。
- `/speckit-implement` 读取清单勾选状态作为门禁，且不得修改标记。
- `checklists/requirements.md` 是 `/speckit-specify` 与 `/speckit-clarify` 维护的独立内置 spec-quality 清单，与本自定义清单生命周期不同。
- 编号 CHK001–CHK032 顺序引用；发现新问题可内联追加注释或新条目。
