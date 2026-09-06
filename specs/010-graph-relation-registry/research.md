# Research: 图关系注册表（010）

**Branch**: `010-graph-relation-registry` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)

> Phase 0 决策记录。每条含 Decision / Rationale / Alternatives considered。行号引用以 2026-09-06 工作树为准（008/009 合入后）：`ingestion_service.py:839-842`（图提取分派）、`:858-863`（降级）、`:491-509`（graph_ready 门控）、`graph/models.py:45-49`（CHECK 约束）、`graph/expansion.py:29-31,74-75`、`postgres_graph_store.py:49-52,254-275`、`retrieval_pipeline.py:38-39,87-101`。

---

## R0 基线声明（宪法 X 前置）

**Decision**: 本 Feature 双档对照：
1. **无回归档**：004 图增强评测集 37 条（`eval/graph_enhanced_comparison_report.json` 索引 0–36）重跑，非延迟指标（Recall@K/MRR/nDCG）相对该报告在 **1% 相对容差**内一致（沿用 006/007 SC-009 判定范式）；重跑产物落新文件 `eval/010_graph_regression_report.json`，不覆盖历史报告（eval/README"基线报告勿覆盖"约定，沿 007 先例 `007_graph_report.json`）。运行口径：`run_graph_comparison.py` 由 010 增补 `--limit N` 参数（截取数据集前 N 条，沿 eval 既有 `--limit` 先例 `run_comparison.py`），004 图集回归以 `--limit 37` 运行（索引 0–36）。
2. **受益档**：交叉引用受益子集 ≥6 条（法律域、含 ≥1 中文条文引用查询）上，"混合检索（无交叉引用扩展）vs 图增强（含交叉引用扩展）"对照，子集 MRR/nDCG 均值相对提升 ≥3% + Recall 非降（SC-001 闸口形式沿用，适配见 R12）。

**Rationale**: 插件化是纯重构（java/ddl 行为逐条不变），须以无回归证明；交叉引用是非 SE 新能力，须以受益闸口证明（ADR-8"仅抽象不验证=未证明的接口"）。

**Alternatives**: 只做功能验收不做对照（否决：违反宪法 X 与 spec FR-028/FR-030）；覆盖 004 历史报告（否决：破坏基线可追溯性）。

---

## R1 GraphExtractor 插件接口（`graph/extractors/base.py`）

**Decision**: 接口契约为 ABC + 类属性声明：

```text
class GraphExtractor(ABC):
    format: str                    # 消费的源格式（"java"/"ddl"/"markdown"）
    relation_pairs: Mapping[str, str]   # 成对关系声明 {"calls": "called_by", ...}（R9）
    chunk_scope: Literal["source", "scope"] = "source"
                                   # source=仅当前知识源 chunk（java/ddl，行为不变）
                                   # scope=当前 scope 全量 chunk（cross_reference，跨文件相对链接）

    @abstractmethod
    def extract(self, source, chunks, scope) -> list[dict]: ...
```

- **边 dict 契约**（收编现 java/ddl duck-typing 产出结构，FR-003）：`source_chunk_id/target_chunk_id/relation_type/direction("out")/is_hard(true)/version/knowledge_scope_id/index_version/parse_evidence`；orchestration 层统一盖 version 戳（沿用 `ingestion_service.py:850-851`）。
- **parse_evidence 契约**：恒为 3 字段 `{source_format, extractor, locator}`（与 004 契约 schema 的 additionalProperties:false 一致）；交叉引用的结构化细节（引用种类/锚点/条文号/行号）编码进 locator 字符串（R7.4），**不改 parse_evidence 形状**。
- **失败降级语义**（用户约束）：提取器内部失败 MAY raise；orchestration（ingestion 与 rebuild 两调用点）catch → 记 `hard_degraded_reason`、产 0 边、入库链不断（沿用 `ingestion_service.py:858-863` 既有模式，004 AST 降级同款）；无匹配提取器 = 正常跳过（非失败）。

**Rationale**: 收编而非新造：现 `JavaCallGraphExtractor.extract(source_code, chunks, scope)` 与 `DdlFkExtractor` 已是该签名，ABC 只将其显式化 + 增加声明面（format/relation_pairs/chunk_scope），使注册表可按声明发现。chunk_scope 双档保住 java/ddl 行为逐条不变（FR-005），又给 cross_reference 跨文件解析留出数据面（R10.3）。

**Alternatives**: (a) Protocol/duck-typing + 运行时 hasattr 校验（否决：正是要收编的现状，无编译期契约）；(b) extract 返回 (edges, degraded_reason) 元组（否决：降级语义留在 orchestration 层，与 004 既有 try/except 模式一致，接口最小）；(c) parse_evidence 扩结构化字段（否决：触发两份契约 schema 的 additionalProperties:false 修改，locator 字符串编码已满足可定位性且 java/ddl 先例如此）。

---

## R2 图关系注册表：独立注册表并 supersede 008 图钩子

**Decision**: `GraphExtractorRegistry` 与 ABC 同置 `graph/extractors/base.py`：按 `format` 注册提取器类（声明序确定），`discover(format, graph_relations) -> list[GraphExtractor]` 返回其 relation_pairs 键集与该域词表有**交集**的提取器（声明序，确定性）；`inverse_relation_map() -> dict[str, str]` 聚合全部提取器的成对声明（R9）。进程内只读单例，`build()` 失败（重复 format+声明冲突、接口未实现）= 启动失败（沿用 008 §5 启动失败契约）。**退役** `FormatHandlerRegistry.graph_extractor(fmt)` 钩子与 `parsers/registry.py` 的两个工厂：两个调用点（`ingestion_service.py:841`、`postgres_graph_store.py:225` rebuild）改经图层注册表；008 契约文档 `format-handler-registry.md` 增 supersession 附注（图提取分派行移交 010 契约 `graph-extractor-registry.md`）。

**Rationale**: 008 钩子是**单值 Callable**（`graph_extractor: Callable | None`），结构性无法表达"一个格式多提取器"（spec Edge Case：格式+词表命中多个提取器须确定性合并）与 domain_key 轴；图层自有注册表消除 parsers→graph 反向依赖（分层正确：格式分派归 parsers，图提取归 graph）。迁移本身受 SC-001 004 回归闸口保护。

**Alternatives**: (a) 扩展 FormatHandlerRegistry 加域轴与多值（否决：parsers 层持有图提取分派是分层倒置，且 008 契约冻结"17 条目单值钩子"语义改动更大）；(b) 保留 008 钩子作 delegate 转发（否决：双分派路径违反 008"单一事实源"原则，留长期漂移面）。

---

## R3 发现语义与域档案词表联动（007 基础设施复用）

**Decision**: 摄入/rebuild 两路径统一发现序：`scope_id → KnowledgeScope.domain_key → DomainProfile.graph_relations → registry.discover(source.format, graph_relations)`；对返回的每个提取器（声明序）依次 `extract`、合并产边、按唯一键 `(knowledge_scope_id, index_version, source_chunk_id, target_chunk_id, relation_type, direction, version)` 去重（ON CONFLICT DO NOTHING 沿用）。空词表/无交集 → 0 提取器 → 0 边 → graph_ready 自然不可声明（FR-020 语义不变，`ingestion_service.py:495-501` 既有 hard_edges_written>0 门控零改动）。域档案读取复用 007 `DomainProfileService`（新增按 domain_key 取 profile 的内部查询，或直接 session select，plan 细节）。

**Rationale**: 词表是唯一合法关系类型来源（宪法 XI）；发现=声明∩词表，使"新域启用交叉引用"=建档案声明词表，零代码。空交集静默跳过与 spec US1 场景 2 对齐。

**Alternatives**: (a) 注册表键直接为 (format, domain_key) 二元组、提取器逐域注册（否决：提取器是领域中立的，逐域注册把域假设写回代码，违反 FR-016；交集发现让 cross_reference 服务任何声明词表的域）；(b) 词表校验只做在注册表发现处、写入不再校验（否决：见 R5，store 是覆盖全部写入方的 chokepoint）。

---

## R4 relation_type CHECK 放宽迁移（0074，drop/add 模式）

**Decision**: 新迁移 `0074_widen_graph_edge_relation_type`（head 0073 顺延）：
1. **前置断言**：`SELECT count(*) FROM graph_edge WHERE relation_type='other_hard'` > 0 → **raise 阻断迁移**（要求显式回填策略；004 提取器从未产出，验收环境恒为 0）。
2. **drop/add**（沿用 0073 范式）：`DROP CONSTRAINT IF EXISTS chk_graph_edge_relation_type` + `ADD CONSTRAINT chk_graph_edge_relation_type CHECK (relation_type ~ '^[a-z][a-z0-9_]{0,62}$')`。
3. **存量零重写**：calls/called_by/fk_references/fk_referenced_by 原值保留（已与 se-project 词表键一致，澄清 Q3）；不引入命名空间前缀——域隔离由 knowledge_scope_id 承担，relation_type 保持裸词表键。
4. ORM 同步：`models.py` 的 `_HARD_RELATION_TYPES` frozenset 与 `CheckConstraint`（45-49）删除/替换为 pattern 常量；`@validates("relation_type")` 改为：禁 `inferred`（软关系归 soft_relation 表）、禁 `other_hard`（退役）、匹配宽 pattern；词表校验不在 ORM（模型无域上下文）而在 store 写入层（R5）。

**Rationale**: 宽 pattern 沿用 0073 三列放宽的既有形态（同库先例、测试范式可复用）；`^[a-z][a-z0-9_]{0,62}$` 同时充当 SQL 片段拼接的 sanitize 白名单（R6.3）与 DB 层最后防线。other_hard 阻断式断言而非静默改写，符合宪法 III/IV（不静默丢弃/映射，spec Edge Case）。

**Alternatives**: (a) 直接 DROP 约束不加新 pattern（否决：失去 DB 层最后防线，垃圾值可入库）；(b) 存量 other_hard 静默映射为某具体类型（否决：伪造关系类型，宪法 III）；(c) 枚举扩为 6 值含 references/referenced_by（否决：每加一个域词表都要再改 DB 枚举，宽模式才是宪法 XI 的正确形态）。

---

## R5 应用层词表校验位置：store 写入 chokepoint

**Decision**: `GraphStore.write_edges(edges, scope, allowed_relation_types: list[str])` 增**必填**词表参数（ABC 签名演进）：任何 relation_type ∉ 词表 → `ValueError`（列出越界值与合法集）→ 调用方（ingestion/rebuild）既有 try/except 捕获 → 降级记 reason 产 0 边。ingestion 与 rebuild 在调用前各自解析域词表（R3 同源）。写入层无条件拒绝保留字 `{other_hard, inferred}`（硬边 relation_type 永不等于保留字，即便自定义档案词表声明了它们——裸 SQL INSERT 不经 ORM validates，故保留字黑名单须在 store chokepoint 重复兜底，FR-010/宪法 III）。ORM validates 只做 pattern + 禁用值（R4.4）。

**Rationale**: store 是全部写入方（ingestion、rebuild、未来扩展）的单一咽喉，必填参数让"绕过词表校验写入"在类型层面不可能；fail-loud（整批拒绝而非逐条过滤）使提取器声明 bug 在评测/验收中显式暴露，不被静默降级掩盖。词表必填不破坏 004 行为：se-project 词表 = 既有 4 值，java/ddl 产边全部合法。

**Alternatives**: (a) 校验放 ingestion 一处（否决：rebuild 路径绕过）；(b) 越界边静默丢弃（否决：掩盖提取器 bug，违反 VI 确定性可观测）；(c) 可选参数 None=跳过（否决：默认路径即弱化路径）。

---

## R6 图扩展查询侧词表兼容（三处 SE 硬编码清除）

**Decision**:
1. **`expansion.py:29-31,74-75`**：删除 `_BIDIRECTIONAL_PAIRS` 硬编码默认；`relation_types=None` 且 bidirectional 时**不过滤**（store 的 rt_filter 为空 = 该 scope 全部硬边 + active 软关系）。行为等价性论证：010 写侧词表校验保证 scope 内 graph_edge 的 relation_type ∈ 该域词表，故"不过滤"在 se-project scope 上与"过滤为 4 值+inferred"**逐边等价**（SE scope 不存在第 5 种硬边值），004 回归闸口实证。
2. **`retrieval_pipeline.py:38-39,87-101`**：`map_graph_params(signals, relation_directions, valid_directions)`——合法集由调用方传入（= 请求域词表，来自 `entry.py:180-182` 已解析的 `domain_planner_config.relation_vocab`，经 state_machine → retrieve_round → _recall_one 穿线）；planner 方向过滤为合法子集，空/全非法 → 回退合法集全量（= 请求域词表，非 None——rt_filter 同时作用于含 active 软关系的联合 CTE，None 回退会使软关系在 planner 缺省方向时新混入扩展，破坏与 004 的逐边等价；se-project 域合法集恰为既有 BIDIRECTIONAL_DEFAULT 4 值，回退语义逐边等价）。删除模块级 `BIDIRECTIONAL_DEFAULT/VALID_DIRECTIONS`。
3. **`postgres_graph_store.py:254-275` 反向 CTE**：CASE 硬编码映射改由 `registry.inverse_relation_map()` 聚合生成（calls↔called_by、fk_references↔fk_referenced_by、references↔referenced_by 自动并入；未来提取器新对自动生效）；键拼接前经 R4 pattern 校验（代码内声明 + 防御性 sanitize 双保险）。
4. **SQL 参数化**：`postgres_graph_store.py:49-52` 的 `rt_list` 字符串拼接改为 `relation_type = ANY(:rts)` 数组绑定——词表键现可来自用户自定义域档案（007 CRUD），拼接即注入面；relation_types 全部元素先过 pattern 校验。

**Rationale**: 查询侧三处硬编码是 SE 假设在检索路径的残留（宪法 XI 违例点），且**不加修复则法律域图路径直接不可用**：expansion 默认过滤会排除 references/referenced_by；pipeline VALID_DIRECTIONS 会把 planner 的 legal 方向判非法回退 SE 默认；反向 CASE 使 references 反向遍历标注错误。"不过滤"默认 + 写侧词表保证，是把合法性判断移回唯一权威来源（域档案）的最小改动。

**Alternatives**: (a) `_BIDIRECTIONAL_PAIRS` 追加 references/referenced_by（否决：仍是硬编码，下个域再改一次，违反 XI）；(b) expansion 默认改为"传入域词表"（否决：需要 expansion 层取档案，引入 service 依赖；写侧校验已使过滤冗余）；(c) 反向 CASE 保留硬编码仅加新对（否决：与 (a) 同病；注册表聚合是零成本自动化）。

---

## R7 交叉引用正则规则集（中英文）

**Decision**: 规则集分两层——**结构化链接**（语法级，近零误报）与**条文引用**（文本模式，查准优先）：

**R7.1 Markdown 链接（结构化，markdown-it AST/正则均可，实现取正则+行号）**：
- 内部锚点：`[text](#anchor)` → 目标 = 同文档标题归一化匹配（R10.2）。
- 相对链接：`[text](./path.md)` / `[text](path.md#anchor)` / `[text](../dir/path.md)` → 目标 = scope 级文件索引按文件名（basename）解析（R10.3）。
- 排除：外部链接（`http(s)://`）、纯锚点空文本、mailto 等非引用协议。

**R7.2 中文法规条文引用（文本模式，引用标记白名单 = 防误报核心）**：
- 触发词白名单（须显式出现）：`依据 / 依据下述 / 根据 / 依照 / 按照 / 参照 / 参见 / 见 / 转致 / 援引`。
- 条文号模式（中文数字）：`第[一二三四五六七八九十百零两]+条`（可带款项 `第X条第Y款/第X条第Y款第Z项`，款项不参与定位、并入条文级目标）。
- 条文号模式（阿拉伯点号，服务"参见 X.Y"形态与编号制文档）：`参见/见 + \d+(\.\d+)*`，目标 = 标题以该编号开头的 Chunk（如 "## 4.2 xxx"）。
- **范围与相对引用不产边**：`第X条至第Y条`（范围）、`前条/本条/前款`（相对指代，无确定目标）——解析目标不确定，宪法 III 不产边（记录为规则集显式排除项，非提取失败）。

**R7.3 防误报判据（查准/查全权衡的落点）**：
1. 结构化链接：语法即证据，无叙述性误报面。
2. 条文引用**双重确认**：(a) 引用动词白名单命中 + (b) 条文号在本 scope 语料内**可解析到标题 Chunk**。二者缺一不产边——普通叙述"本法第一条确立了……"（无引用动词或目标不在语料）不产边；这正是"普通'第 X 条'叙述 vs 真引用"的判别线。
3. 查准优先的理由：硬边是"可验证证据"（宪法 III/IV），一条假硬边污染的是信任本身（蓝图 §8 风险"图词表开放后硬边可信度稀释"），而漏报只损失增量受益、由 ≥3% 受益闸口的子集设计容忍。
4. 查全率由受益子集证明：评测语料按规则集正向构造（每条查询的期望证据链路可被规则集命中），闸口过则查全足够。

**R7.4 locator 编码（parse_evidence 3 字段不动）**：
- `xref:internal:anchor=<锚点>:text=<链接文本>:line=<行号>`
- `xref:relative:file=<目标文件名>:anchor=<锚点|->:text=<链接文本>:line=<行号>`
- `xref:clause:ref=<条文号原文>:marker=<引用动词>:line=<行号>`
（值内冒号/等号做 %-转义；格式进契约 `cross-reference-extraction.md` 固化）

**Rationale**: 两层规则集把"确定可解析"作为唯一产边条件，查准由白名单+可解析性双重保证，与 spec FR-015/Edge Case（重复锚点确定性消歧）一致；中英数字与点号两套条文形态覆盖 eval 语料与真实法规文档主流写法。

**Alternatives**: (a) LLM 辅助识别引用（否决：硬关系必须确定性解析产生，宪法 III/VI）；(b) 范围引用展开为逐条边（否决：范围语义≠逐条引用，产边即伪造意图）；(c) 无白名单纯条文号匹配（否决：叙述性提及误报率高，直接稀释硬边信任）。

---

## R8 双向边对称性（澄清 Q2 落地）

**Decision**: 提取器以 `relation_pairs` 声明成对关系（`{"references": "referenced_by"}` 等）；每条可确定引用**同时产出两条边**：`references`（引用方→被引用方）与 `referenced_by`（被引用方→引用方），均 `direction="out"`，共享同一 locator（mirrored 边不另造证据位置），去重键 `(source, target, relation_type, direction, version)` 各自独立。与 `calls/called_by`、`fk_references/fk_referenced_by` 完全同构（004 既有提取器即此模式，迁移后保持）。反向遍历标注经 inverse map（R6.3）。**只声明单侧或只产单侧的提取器注册即拒**（对称性是接口契约，spec Edge Case）。

**Rationale**: 成对落库是 004 已验证的存储/遍历模型（正向 CTE 走 source→target、反向 CTE 走 target→source 并重标类型），单侧存储需要查询期推导反向，引入与 004 不同的扩展语义且 SC-001 无法逐边等价。

**Alternatives**: (a) 只存 references、反向运行时翻转（否决：反向 CASE/权重/去重语义全部要改，004 回归风险大于收益）；(b) 按 planner 方向按需补产（否决：入库期确定性 vs 查询期动态产边违反 VI）。

---

## R9 inverse map 的来源与消费

**Decision**: `registry.inverse_relation_map()` = 全部注册提取器 `relation_pairs` 的聚合（正反映射双向并入）；消费者：(a) 反向 CTE CASE 生成（R6.3）；(b) 提取器注册校验（pairs 必须互为逆、不得与已注册 pairs 冲突）；(c) 契约文档的词表-配对参考表。键集 = 代码内声明（非用户输入），但仍过 pattern sanitize 后入 SQL。

**Rationale**: 配对关系是提取器级契约（"谁产出谁声明逆"），域档案只声明词表键与方向、不声明逆映射——把逆映射放档案会要求用户维护冗余且易错的对称声明。

**Alternatives**: 逆映射硬编码于 store（否决：R6 已论）；档案声明 pairs（否决：冗余易错，且内置档案只读、自定义档案错配会炸查询）。

---

## R10 混合锚定与跨文件解析（澄清 Q1 落地）

**Decision**:
1. **来源端点（引用方 Chunk）**：全文扫描定位引用出现行号 `L`（链接/条文正则均带行捕获），归属 = 唯一满足 `start_line <= L <= end_line` 的 Chunk（markdown 切片区间连续无重叠，归属唯一；区间缺口——空行带——归属前一条 Chunk 的保守规则由实现固定并测试固化）。
2. **目标端点（被引用方 Chunk）**：锚点/条文号与 Chunk 的 `section_path` **末段标题**归一化匹配。归一化：ASCII 小写、空白→`-`、剥 markdown 标记与常见标点、CJK 保留；匹配 `normalize(anchor) == normalize(heading_title)` 或锚点原文 == 标题原文。条文引用：标题**以前缀匹配**条文号（`第一条 总则` ↔ 引用 `第一条`；中文数字归一比较）。**重复命中取文档序首个**（确定性消歧，spec Edge Case）；无命中不产边。
3. **跨文件相对链接（chunk_scope="scope"）**：orchestration 预构建 scope 级索引 `filename → [(chunk_id, heading, start_line, end_line)]`（当前源 chunk + 同 scope 其余已发布源的 chunk，按 KnowledgeSource 文件名关联），作为 `chunks` 传入（每条附 `filename` 键）；提取器按 basename 匹配目标文件；basename 在 scope 内不唯一 → 视为不可解析不产边（确定性消歧，宪法 VI，查准优先 R7.3）。跨 scope 文件天然不在索引内 → 不解析 → 不产边（跨域泄漏为零的结构保证）。**首遍尽力 + 重建补全**：A 先入库时若 B 未在，A→B 边缺失，用户触发 rebuild 后补全（004 FR-027 重建语义既有；eval 流程本就先全集入库再重建，SC-002 不受影响；该顺序敏感性在契约文档显式声明）。

**Rationale**: 复用解析器既有元数据（section_path/start_line/end_line）不在提取器内重解析标题树（FR-015 澄清 Q1）；行号归属与标题匹配各取所长：链接的行是确定的，目标身份是结构化的。

**Alternatives**: (a) 两端都 position_path 前缀匹配（否决：链接不在标题路径中，来源端无解）；(b) 两端都全文正则+行号（否决：目标标题的行号区间要重建标题树，重复解析器工作且引入切片合并后的归属歧义）；(c) 跨文件链接降级为同文件锚点（否决：FR-013 明含相对链接，受益子集含跨文件查询）。

---

## R11 legal 内置域档案（澄清 Q4 落地）

**Decision**: `config/domain_profiles.py` 的 `BUILTIN_DOMAIN_PROFILES` 增第三条目：
`domain_key="legal"`、`name="Legal"`、`supported_formats=["markdown"]`（010 对齐提取器格式面；011 建语料时可扩展）、`graph_relations={"references": ["out","in"], "referenced_by": ["out","in"]}`、`prompt_overrides=None`（走 009 域中立基础模板 + 词表槽位注入，无需 legal 专属提示词）、`default_capabilities={"retrieval_modes": ["dense","hybrid","graph_enhanced","agentic"], "has_graph": true}`、`is_builtin=True`。经 007 `sync_builtin_profiles` 启动种子化（升级部署自动插入，无迁移）；内置只读保护自动生效。**受益闸口失败的声明式补救**：若 SC-002 未达 3%，legal 内置档案交付时改为**不声明 graph_relations**（空词表 → cross_reference 不为其触发 → 图路径不进入 legal 默认检索），提取器与注册表照常交付、可由自定义档案显式启用——"作为可选检索路径保留"的机制即档案声明本身，无需新增开关。

**Rationale**: 内置档案是交叉引用提取器的一等挂载域（非一次性测试夹具），011 直接在其上建语料/基线；声明式补救复用"词表=开关"的既有语义，零新增机制。

**Alternatives**: (a) 经 007 CRUD 建运行时档案（否决：非内置则升级部署不自动获得、种子漂移修复不覆盖，验证域地位不稳固）；(b) 新增 per-domain graph 开关配置（否决：与 has_graph/词表语义重复）。

---

## R12 评测设计与 SC-001 ≥3% 闸口在新子集上的适配

**Decision**:
1. **语料**：`eval/corpora/legal/` 虚构法规 markdown 集（2–4 个文件：一部主法规按 `## 第X条` 结构 + 一部实施细则/引用性文件，含内部锚点链接、跨文件相对链接、`依据第X条/参见X.Y` 中文引用；虚构条文避免真实法律文本版权问题，沿用 001 语料虚构约定）。
2. **数据集**：`eval/cross_reference_eval_dataset.json` ≥6 条（沿 005 独立数据集先例而非追加 eval_dataset.json——避免污染 004 37 条回归口径的字段结构）；每条含 query / project_scope（legal 域 scope id，运行时建）/ expected_evidence_ids / `is_structural_benefit: true`；≥1 中文条文引用查询（"谁引用了第X条"）、≥1 锚点导航查询、≥1 跨文件相对链接查询。
3. **运行器**：`eval/run_cross_reference_comparison.py`——同会话先跑"混合基线（graph 开关关闭）"再跑"图增强（开启）"，复用 `GraphComparisonRunner` 报告器（三段闸口/硬指标/可重复性结构原样），产出 `eval/cross_reference_comparison_report.json`。004 回归由 `run_graph_comparison.py` 既有口径重跑产出 `010_graph_regression_report.json`（R0）。
4. **SC-001 ≥3% 适配口径**：闸口形式逐字沿用（受益子集 MRR/nDCG 均值**相对**提升 ≥3% + Recall 非降 + 硬指标全过），对照基线 = **同会话法律域混合基线**（非 002 报告——语料与 scope 均不同，004 当年也是同会话混合基线，形式同源）；小样本（n≥6）相对提升的噪声由可重复性检查（SC-011 双跑一致）对冲；`enters_default_path` 判定 = 三段闸口 + 硬指标，失败走 R11 声明式补救。验收前流程：建 legal scope → 入库语料 → 触发 rebuild + graph_ready 发布（硬边>0）→ 对照运行。

**Rationale**: 与 004 完全同构的对照设计使闸口可比、报告器零改动；独立数据集文件保护 004 回归口径（37 条）与 002 前 18 条口径互不干扰；中文条文查询直接命中 ADR-8"非 SE 验证"的价值主张。

**Alternatives**: (a) 追加进 eval_dataset.json 加 domain 标记（否决：004 runner 无域过滤概念，37 条口径会被新条目稀释/破坏 --limit 语义）；(b) 沿用 002 报告为基线（否决：语料不同不可比）；(c) 绝对水位闸口（否决：004 SC-001 即相对口径，沿用避免发明新标准）。

---

## R13 契约放宽波及面（两份 schema 加法演进）

**Decision**:
1. `specs/003-.../graph-relations.schema.json`（内部数据契约）：`RelationType` enum → `pattern ^[a-z][a-z0-9_]{0,62}$`（description 记录内置词表全集：SE 4 + references/referenced_by + inferred）；硬关系 allOf 分支的 enum 同步 pattern 化 + `not enum [other_hard, inferred]`（保住 004 契约对宪法 III 的编码：硬边 relation_type 不得为 inferred）；软关系分支 inferred 恒值不变；parse_evidence 3 字段不动。
2. `mcp-search-output.graph-annotation.schema.json`（MCP 输出图标注）：`relation_type` enum → 同 pattern；type=hard 分支增 `not enum [other_hard, inferred]`（other_hard 契约面退役 FR-010、宪法 III 硬边编码），soft 分支 relation_type 恒 inferred 不变。**这是 SC-004 的先决条件**：法律域图增强响应携带 `references` 标注，枚举不放宽则 Schema 合法率 100% 不可能成立。加法兼容：既有 6 值全部继续合法，001 基线响应不受影响（无 relation 字段路径不变）。
3. 008 `format-handler-registry.md` 增 supersession 附注（R2）；010 新契约两份（registry / extraction）。
4. 契约测试：`_graph_schema_helper.py`/`test_graph_relations_schema.py` 更新为 pattern 断言 + 新值样本（references 合法、other_hard 非法、越界 pattern 非法）。

**Rationale**: 宪法 VII 允许加法演进（"不 imposing breaking change"）；relation_type 取值域与 DB CHECK 同步放宽是同一决策的两面；parse_evidence 不动使 MCP 标注面零形状变化。

**Alternatives**: (a) MCP 枚举只追加 references/referenced_by 两值（否决：自定义档案词表键仍会越界，pattern 才与"词表开放"同构）；(b) 不动 MCP schema 指望不触发（否决：法律域图增强一开即违约，自相矛盾）。**遗留观察**（不在 010 处理）：graph-relations.schema.json 仍列 `project_id` 为 required，而 007 已删该列——属 007 契约债，010 编辑该文件时不触碰此字段、在 tasks 中记录待 011 或专项清理。

---

## R14 软关系格式无关回归与 graph_ready 门控不动面

**Decision**: `soft_relation_inference.py`、`capabilities.py`、`ingestion_service.py:491-509`（graph_ready 门控）**零改动**；FR-021/FR-022/FR-020 以 004 既有软关系测试集 + graph_ready 生命周期集成测试（`test_us5_graph_ready_lifecycle.py` 等）回归为闸口。软关系 relation_type 恒 inferred 的 ORM 约束保留（FR-011）。

**Rationale**: 插件化只动"硬关系从哪来、类型允许哪些值"；推断框架与门控是 004 已评测行为，改即违规。零改动 + 回归测试是最便宜的合规。

**Alternatives**: 无（不改动即决策）。

---

## R15 风险与缓解（承接蓝图 §8"图词表开放后硬边可信度稀释"）

| 风险 | 缓解 |
|------|------|
| 条文引用误报污染硬边信任 | R7.3 双重确认（动词白名单 + 可解析性）；受益子集正向构造验证；locator 全量留痕可审计 |
| 查询侧三处硬编码清理引发 SE 域回归 | R6.1 行为等价性论证（写侧词表保证 scope 内类型集）+ SC-001 004 图集 37 条回归闸口 |
| 自定义档案词表键注入 SQL | R6.4 ANY(:rts) 参数化 + R4 pattern sanitize 双保险 |
| 跨文件链接首遍缺失 | R10.3 首遍尽力 + rebuild 补全语义显式化；eval 流程先全集入库再重建 |
| legal 档案种子与 007 等价测试冲突 | 种子扩展只增不改 se-project/generic；test_domain_profile_seed 增 legal 断言；007 同步机制自动修复漂移 |
| other_hard 存量非零 | R4.1 迁移阻断 + 显式回填（不静默） |

---

## R0.1 相对基线目标（research 固化，宪法 X/蓝图 §24.3）

进入 `plan.md` 执行前固化：**无回归档**（004 图集 37 条，1% 相对容差，非延迟指标）+ **受益档**（交叉引用子集 ≥6 条，MRR/nDCG 相对提升 ≥3% + Recall 非降 + 硬指标全过）。两档全过 = 交叉引用图扩展随 legal 档案词表声明进入默认检索路径；受益档未过 = legal 档案不声明词表（R11 声明式补救），插件框架照常交付。
