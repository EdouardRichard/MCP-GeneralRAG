# Contract: 交叉引用提取规则（cross_reference 提取器）

**Branch**: `010-graph-relation-registry` | **Date**: 2026-09-06 | **Spec**: [spec.md](../spec.md) | **Research**: R7, R10

本契约固化 cross_reference 提取器（format=markdown，relation_pairs=`{references: referenced_by}`，chunk_scope=scope）的确定性提取规则、混合锚定语义与 locator 编码。规则集目标是**查准优先**（硬边=可验证证据，宪法 III/IV；查全由受益子集证明，research R7.3）。

## 1. 提取范围（产边的引用形态）

### 1.1 结构化链接（语法级证据，近零误报）

| 形态 | 模式（示意） | 目标解析 |
|------|--------------|----------|
| 内部锚点链接 | `[text](#anchor)` | 同文档标题归一化匹配（§2.2） |
| 相对链接（带锚点） | `[text](./path.md#anchor)`、`[text](../dir/path.md#anchor)` | scope 文件索引按 basename 解析目标文件 → 锚点匹配；无锚点则目标文件首个标题 Chunk |
| 相对链接（无锚点） | `[text](path.md)` | 目标文件首个标题 Chunk |

**排除**：外部链接（`http://`、`https://`）、`mailto:` 等非引用协议、图片 `![...]()`、代码块/行内代码内的链接语法（fenced block 内不扫描——确定性排除项）。
- **basename 唯一性**：相对链接目标文件按 basename 在 scope 级索引内解析；scope 内同名（basename）文件不唯一时，该链接视为不可解析、不产边（确定性消歧，宪法 VI；唯一性优先于查全，对齐 research R7.3 查准优先）。

### 1.2 条文引用（文本模式，引用动词白名单 = 防误报核心）

- **触发词白名单**（引用动词 MUST 显式出现）：`依据`、`根据`、`依照`、`按照`、`参照`、`参见`、`见`、`转致`、`援引`。
- **中文数字条文**：`第[一二三四五六七八九十百零两]+条`（可附款项/项号，款项不参与目标定位、并入条文级 Chunk）；标题前缀匹配（如 `## 第一条 总则` ↔ 引用 `第一条`，中文数字归一比较）。
- **点号编号（服务"参见 X.Y"与编号制文档）**：触发词 + `\d+(\.\d+)*`；目标 = 标题以该编号开头的 Chunk（如 `## 4.2 适用范围`）。

**确定性排除（不产边，记录为规则集显式排除项而非提取失败）**：
- 范围引用：`第X条至第Y条` / `第X条-第Y条`（范围语义 ≠ 逐条引用）。
- 相对指代：`前条`、`本条`、`前款`、`同条`（无确定目标）。
- 无触发词的叙述性提及（"本法第一条确立了……"）——**这正是"普通叙述 vs 真引用"的判别线**：白名单动词 + 可解析目标，二者缺一不产边。
- 目标不在本 scope 语料（含跨 scope 文件）——不解析、不产边、不跨域补全（跨域泄漏为零）。

## 2. 混合锚定语义（澄清 Q1）

### 2.1 来源端点（引用方 Chunk）——行号区间归属

全文扫描定位引用出现行号 `L`（链接与条文正则均携带行号捕获）→ 归属唯一满足 `start_line <= L <= end_line` 的 Chunk。markdown 切片区间连续无重叠；区间间空行缺口归属前一条 Chunk（实现固定 + 测试固化）。

### 2.2 目标端点（被引用方 Chunk）——标题路径匹配

- **归一化函数**：ASCII 小写；空白 → `-`；剥 markdown 标记（`#`/`*`/`_`/```）与常见标点；CJK 字符保留。
- **匹配规则**：`normalize(anchor) == normalize(heading_title)` 或锚点原文 == 标题原文（宽松分支，覆盖中文锚点未 slug 化的常见写法）；条文引用走 §1.2 前缀匹配（条文号归一比较）。
- **消歧**：重复命中取**文档序首个**（确定性，spec Edge Case）；无命中不产边。
- 匹配对象 = Chunk `section_path` 的**末段标题**（复用解析器元数据，不在提取器内重建标题树）。

### 2.3 跨文件解析（chunk_scope=scope）

orchestration 预构建 scope 级索引 `filename → [(chunk_id, heading, start_line, end_line)]`（当前源 + 同 scope 其余已发布源，按 KnowledgeSource 文件名 basename 关联；basename 不唯一 → 不产边，见 §1.1）注入 `chunks`（每条附 `filename` 键）。**首遍尽力 + 重建补全**：目标文件尚未入库时该边缺失，用户触发 rebuild 后补全（004 FR-027 语义；eval 流程先全集入库再重建，故 SC-002 不受顺序影响；该语义在本文档显式声明为实现契约）。

## 3. 产边与对称性（澄清 Q2）

每条可确定引用**同时产出两条硬边**：

```text
references:    source_chunk_id=引用方, target_chunk_id=被引用方, direction="out"
referenced_by: source_chunk_id=被引用方, target_chunk_id=引用方, direction="out"
```

- 共享同一 locator（mirrored 边不另造证据位置）；去重键各自独立（`(scope, version, source, target, relation_type, direction)`）。
- 自引用（引用方 = 被引用方同一 Chunk）不产边；同文档锚点指向自身所在 Chunk 亦然（沿用 004 DDL 无自环约定）。
- 与 `calls/called_by`、`fk_references/fk_referenced_by` 完全同构；反向遍历重标注经注册表 inverse map。

## 4. locator 编码（parse_evidence 3 字段契约不变）

结构化细节编码进 locator 字符串（值中 `:`/`=` 做 %-转义）：

```text
xref:internal:anchor=<锚点>:text=<链接文本>:line=<行号>
xref:relative:file=<目标文件basename>:anchor=<锚点或->:text=<链接文本>:line=<行号>
xref:clause:ref=<条文号原文>:marker=<触发词>:line=<行号>
```

parse_evidence 恒为 `{source_format: "markdown", extractor: "cross_reference", locator: <上述编码>}`（与 graph-relations.schema.json / MCP 图标注 schema 的 3 字段 additionalProperties:false 一致——**不改 parse_evidence 形状**，research R13）。

## 5. 验收断言映射

| 契约条款 | Spec 映射 |
|----------|-----------|
| §1 排除项（叙述/范围/相对指代不产边） | FR-015、Edge Cases、US3 场景 4 |
| §1.2 白名单 + 可解析双重确认 | research R7.3、SC-002（受益子集正向构造） |
| §2 混合锚定 | FR-015（澄清 Q1）、SC-005 |
| §2.2 文档序首个消歧 | Edge Cases（重复锚点） |
| §2.3 scope 限域 | FR-023/FR-025（跨域泄漏为零）、SC-003 |
| §3 成对对称 | FR-013（澄清 Q2）、SC-012（成对缺失率=0） |
| §4 locator | FR-014、SC-012（parse_evidence 完备） |
