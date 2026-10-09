# 评测治理评审检查清单：记忆评测治理与 3.0 定稿

**Purpose**: 对 015 的需求文本本身做"需求质量单测"——核查评测集质量、投毒防护、AOEP 状态义务、硬指标全量测量、治理 UI、统计端点、基准报告、全集回归、文档债与 3.0 七项目标核销等领域的**完整性、清晰性、一致性、可度量性与覆盖边界**，而非核查实现行为。
**Created**: 2026-10-09
**Feature**: [spec.md](../spec.md)｜[plan.md](../plan.md)｜[contracts/README.md](../contracts/README.md)

**Note**: 本清单由 `/speckit-checklist` 依据用户指定的十二类评审领域生成。
**Review Ownership**: 本清单为评审者所有的需求质量评审工件。仅当评审者判定该需求质量判据已满足时，才将条目标记 `[x]`。
**Marker Semantics**: `[x]` 表示该判据已经评审且需求质量达标，**不表示实现工作已完成**。
**Traceability**: 条目以 `[Spec §FR-0xx / §SC-0xx / §Edge Cases / §Assumptions]`、`[Plan §…]`、`[Constitution §…]`、`[contracts/…]` 或 `[Gap]`/`[Ambiguity]`/`[Conflict]`/`[Assumption]` 标注来源；标记 `[Gap]` 的条目指向需求缺位。

## 一、评测集质量（人工审核记录、固定集纪律、中文覆盖、不破坏既有条目）

- [x] CHK001 三份子集的**逐条人工审核记录**（审核状态、审核说明、审核者与时刻）是否作为强制字段统一要求，而非仅对新建投毒子集要求？是否定义了历史遗留 `pending` 记录必须如何校正？[Completeness, Spec §FR-009, §FR-013]
- [x] CHK002 014 连续性数据集 `source.human_review` 标注 "pending T053" 与逐条 `reviewed` 状态**互相矛盾**的处置口径是否写明（以何者为准、如何留证）？[Consistency, Gap, Spec §依据与依赖]
- [x] CHK003 "含中文/语言覆盖"是否被量化为可判定的口径（覆盖哪些语言、各子集最低条数、`zh` 如何计数），而非仅以"含中文"表述？[Clarity, Spec §FR-011, §FR-013, §SC-001]
- [x] CHK004 "只增不破坏"是否给出**机器可复核判据**（既有条目指纹/哈希不变、原地改写与删除次数为 0、新增走纯追加路径），而非仅作文字禁止？[Measurability, Spec §FR-010, §SC-001, Plan §Validation 1]
- [x] CHK005 当既有条目判据被证明有误时，修订路径是否闭合（追加新条目或显式变更并保留原条目可复算、须记变更理由），且两条路径的适用条件与记录字段明确？[Clarity, Spec §FR-010, §Edge Cases]
- [x] CHK006 冻结记录的必需字段（版本与标识、语料与快照指纹、判据来源、冻结时刻、逐条审核、语言与类别覆盖）是否对三份子集一致要求（含投毒子集 `freeze` 块），且复核冻结不得静默改变 013/014 既有预冻结判据？[Consistency, Spec §FR-002, §FR-009, §FR-011, §FR-012]
- [x] CHK007 评测登记所需内容（用例覆盖的模式与变种、构造方式、变种字典版本、公开数据集触发条件状态、报告与运行器用法与重跑口径）是否逐项列明，使"已登记"可判定？[Completeness, Spec §FR-007, §FR-023]

## 二、投毒防护（≥5 条全链路拦截证据）

- [x] CHK008 "≥5 条"的计数单位（用例/查询/场景）与**六道全链路断言**是否逐条以可机器判定的形式写明（写入标记、隔离态、默认召回不可见、巩固不消费、附加记忆与工作集不携带、控制面变更计数为 0）？[Clarity, Spec §FR-001, §FR-004]
- [x] CHK009 单条通过判据是否明确为"被标记为高风险"**且**"落库为隔离态"的合取，并显式禁止"仅标记未隔离即记通过"与"未识别即记已拦截"两条伪通过路径？[Clarity, Spec §FR-001, §Edge Cases]
- [x] CHK010 六道断言各自的**分母**是否被要求非零且可独立观测（默认召回命中数、巩固窗口输入集合、附加记忆与工作集条目集合、控制面变更计数），还是只要求一个总通过结论？[Measurability, Gap, Spec §FR-004, §SC-002]
- [x] CHK011 已知高危模式的覆盖是否逐模式量化（角色劫持含中文变体、身份覆盖、工具调用操纵各 ≥1），且"变种"由**已冻结、带版本的变种字典**定义（同义改写/分隔符或编码扰动/分片拼接/混合语言）？[Clarity, Spec §FR-002]
- [x] CHK012 变种条目"控制面不被内容改变"这一断言是否明确要求**独立于检测命中**成立，且未被识别时如实判为未通过？[Consistency, Spec §FR-003, §Edge Cases]
- [x] CHK013 检测不可用/失败（异常、超时、未知模式）的要求是否完整（不崩溃、不放宽 provenance/范围/配额/隔离校验、可观测、不得记为"已拦截"）？[Edge Case, Completeness, Spec §FR-006]
- [x] CHK014 投毒内容"不获权威"的四条计数（成为硬记忆、进入晋升候选、自动晋升正身、经巩固获得生效权威）是否各自给出分母与计数口径？[Measurability, Spec §FR-005, §SC-002]
- [x] CHK015 首次冻结的时点规则是否无歧义（构造期仅在已冻结变种字典范围内迭代、全部用例"既标记又隔离"后才写首次冻结、冻结后失败如实判定并阻止定稿、补救仅追加或另立 Feature），且投毒写入被限定的落域边界是否写明？[Clarity, Coverage, Spec §FR-002, Clarifications Q6, Plan §Constraints]

## 三、AOEP 状态义务（五不变量各 ≥2 用例 + 机器判定判据）

- [x] CHK016 不变量集合是否与宪法 XIII 的**五不变量**（权威单调、范围不扩张、删除传播、provenance 保全、回滚可溯）对齐？FR-014 仅列四条（回滚可溯、删除传播、权威边界、范围不扩张），**provenance 保全**是缺位还是被显式排除在范围外？[Coverage, Conflict, Constitution §XIII, Spec §FR-014, §FR-056]
  - **已处置（2026-10-09）**：五不变量已全部落入 FR-014/FR-056 与两份契约枚举——（1）`authority_boundary` 更名为 `authority_monotonicity`；（2）新增 `provenance_preservation`；（3）五条不变量（`traceable_rollback`/`deletion_propagation`/`authority_monotonicity`/`provenance_preservation`/`scope_non_expansion`）与《宪法》XIII 第三条逐字对应，AOEP 数据集 `invariants` 键集与报告 `aoep.by_invariant` 键集恰为五项齐全。
- [x] CHK017 "每条不变量 ≥2 用例"是否配合固定的不变量标识与**用例→不变量映射表**，使"每类 ≥2"可审计而非事后归类？[Completeness, Spec §FR-014, §SC-004]
- [x] CHK018 "回滚可溯"的机器判定是否写明三项合取（权威日志回滚事件存在且事件链闭合含前后水位与事件序号、逐投影指纹比对可复算、影响面计数一致），并显式排除"仅有审计记录或请求标识即判可溯"？[Clarity, Spec §FR-015, §SC-005]
- [x] CHK019 "序号链无缺口"是否有可判定的定义（回放序列与权威日志逐项相等、无缺失、无重复），而非会被雪崩式稀疏 ID 恒否定的字面数值连续？[Ambiguity, Spec §FR-015, Plan §Complexity Tracking]
- [x] CHK020 删除传播是否对关系/向量/链接/摘要/文件**五投影各自独立断言**，并同时要求各投影分母非零、分母为零记"不可测量"而非传播达标？[Measurability, Spec §FR-016, §Edge Cases, §SC-006]
- [x] CHK021 删除传播的五投影（关系/向量/链接/摘要/文件）与系统六投影视图（含显著性）之间的关系是否调和，是否存在同一概念两套清单的冲突？[Conflict, Spec §FR-016, §Assumptions, Plan §Complexity Tracking]
- [x] CHK022 权威边界用例是否为**封闭枚举**（声明超出权威、非写实例、只读实例、经 MCP 改写绑定表）且每类都要求被拒 + 留审计？范围不扩张是否同时覆盖"歧义/不可解析一律拒绝并给候选"与"回落最近域/全库次数 = 0"两个分支？[Completeness, Clarity, Spec §FR-017, §FR-018, §SC-007, §SC-008]
- [x] CHK023 每条用例的必备证据字段（请求标识、状态、前后指纹、影响面、可复现记录、`isolated_scope_id`）是否在各不变量间一致要求；破坏性操作是否限定为"每次运行新建的专用隔离域与隔离身份"，并给出既有冻结集依赖域的禁入清单与运行后处置记录要求？[Completeness, Measurability, Spec §FR-019, §SC-004, Clarifications Q8]
- [x] CHK024 载体决议是否作为需求写明（评测数据集 JSON 用例声明为唯一真相源 + 专用运行器执行留证，禁用散落集成断言替代已登记声明）；任一用例失败是否明确使报告总判定不通过并阻断定稿，且逐不变量得分聚合口径是否定义；同版本重跑"结论稳定"是否量化？[Consistency, Measurability, Spec §FR-014, §FR-020, §FR-019, §SC-005]

## 四、硬指标五件套 + quarantined 泄漏 = 0 的全量测量记录（四路径多域）

- [x] CHK025 "五件套 + 隔离泄漏"六项是否各自独立记分，且每项都带**分母规则**与不可测量（零分母）处置，避免总量结论掩盖单项缺测？[Completeness, Spec §FR-028–§FR-032, §SC-012]
- [x] CHK026 跨域串库是否要求事件日志、关系、向量、文件**四路径各自**给出实测样本量与结论，样例是否要求 ≥2 个真实域 + 一次显式多域请求，且样本为 0 的路径不得记达标？[Measurability, Spec §FR-028, §SC-008]
- [x] CHK027 六工具契约合法率的分母（三只读旧工具 + `recall_memory` + `start_work` + `record_memory`）是否封闭枚举，是否要求含非法输入负例拒绝且分母非零？[Clarity, Spec §FR-029]
- [x] CHK028 来源可定位率（证据路径）与记忆 provenance 完备率（软/distilled 五元数据 + 硬记忆逐条锚定复验）是否要求**两项口径分开统计、不得合并**，且各自保留分子分母？[Consistency, Spec §FR-030]
- [x] CHK029 硬记忆锚定率是否要求基于**真实硬记忆样本**，并给出被拒样本与错误码分布，同时明确不得沿用 014 的零分母结论？[Measurability, Spec §FR-031, §SC-012]
- [x] CHK030 隔离泄漏是否对默认召回、巩固窗口、附加记忆、工作集、控制面**五处独立实测且分母非零**；任一项不达是否使整体判定不通过、安全指标是否明确**零容差且不得以容差替代**、是否禁止以测试桩或预设结论替代真实运行证据？[Completeness, Measurability, Spec §FR-032–§FR-034, §SC-012, §SC-013]

## 五、治理 UI（scope 显式过滤、二次确认与审计、显式人工晋升、投影重建、memory_policy 接线）

- [x] CHK031 "无显式域不返回全局记忆正文视图"是否给出**默认可判定行为**（空态或仅域级汇总、零正文承载请求），并明确 MCP 面不暴露回滚或删除入口？[Clarity, Spec §FR-036, §SC-015, contracts/governance-ui-contract.md §2]
- [x] CHK032 浏览六维过滤（域/分型/状态/provenance/会话/显著性）的参数语义、显式域门与"切视图不得重置域选择"是否写明，使过滤"只能收窄"可复核？[Completeness, Spec §FR-036, §SC-014, contracts/governance-ui-contract.md §2]
- [x] CHK033 purge/retire/rollback 的"二次确认"是否被定义为**强确认**（须输入目标域与记忆标识、或回滚水位/事件序号等等价确认值方可提交），并显式禁止单次点击型确认替代？[Clarity, Spec §FR-037, §FR-039, §SC-014]
- [x] CHK034 审计指针是否以**具名字段**（权威事件 id 与 request_id）与可查回路径要求，且影响面预览（受影响投影与条目计数）是否在动作提交前强制并量化？[Clarity, Measurability, Spec §FR-037, §FR-039, §SC-015]
- [x] CHK035 晋升是否被固定为**显式人工动作**，并同时要求展示候选依据、晋升去向与原记忆保留关系、且不存在自动晋升入口？[Consistency, Spec §FR-041, Constitution §XII]
- [x] CHK036 投影重建是否覆盖触发粒度（按投影与/或按域）、各投影一致性校验报告内容与失败显式呈现？[Completeness, Spec §FR-040]
- [x] CHK037 `memory_policy` 域档案编辑是否写明读写路径、非法值失败闭合与"成功后策略生效可核验"；巩固报告页字段（运行标识/域/窗口/输入规模/提案与裁决/产出/状态/保留期/失败与拒绝原因）是否封闭枚举？[Clarity, Spec §FR-042]
- [x] CHK038 批量治理与批量回滚的禁止、以及"首期仅单条/单次单目标"边界是否表述为可计数的**零实例判据**？[Measurability, Spec §FR-037, §FR-039, §SC-014]
- [x] CHK039 SSE 的角色是否被限定为"可选增量信号、非正确性依赖"，使 UI 验收不能以未接线的推送流论证达标、也不能因推送未接线被记为未达标？[Consistency, Plan §Constraints, contracts/governance-ui-contract.md §5]

## 六、统计端点（隐私护栏）

- [x] CHK040 统计端点与 `GET /runtime/metrics` 的关系是否被写成契约级禁止（不并入、不改变其既有契约与响应形态）？[Consistency, Spec §FR-044, §SC-016]
- [x] CHK041 端点路径标识是否在 spec、plan 与契约间统一？spec 记 `GET /api/memory/stats`，plan/契约采用 `GET /api/memories/stats`，须指定唯一权威标识与兼容口径。[Conflict, Spec §FR-044, Plan §Structure Decision, contracts/README.md]
  - **已处置（2026-10-09）**：权威标识统一为 **`GET /api/memories/stats`**（挂既有 `APIRouter(prefix="/api/memories")`）。spec.md 的 Clarifications、FR-044 与 Key Entities 三处 token 均已改为统一值（`/api/memory/stats` 在 spec 中已无命中）；plan/research 中保留的旧写法均为「澄清文本旧记法 / 已否决备选」的历史陈述，非活动标识；契约与 T039/T052 打桩均为统一值。需引证时以 spec FR-044 为准。
- [x] CHK042 隐私护栏是否以**封闭键集**表述（仅计数、分布与分位，不得出现记忆正文、标题、证据正文、查询正文或任何自由文本）并可由响应契约强制？[Completeness, Spec §FR-045, contracts/memory-stats-response.schema.json]
- [x] CHK043 正文开关（`TRACE_BODY_ENABLED`）开/关两态下零正文输出是否被要求为**可判定的等价关系**，而非笼统的"不含正文"？[Measurability, Spec §FR-045, §Assumptions]
- [x] CHK044 端点是否明确仅写实例管理面可用，并定义非授权与只读实例的拒绝行为（状态与错误语义）？[Completeness, Spec §FR-045, §SC-016]
- [x] CHK045 统计与浏览/报告的口径一致性是否给出比较基准（同域、同计数规则、同时间窗），且"不得拉取正文计算分位"是否有可验证边界？[Clarity, Spec §FR-046, Plan §Performance Goals]

## 七、基准报告（契约 schema + 历史产物不覆盖）

- [x] CHK046 报告的必需块与根键（三子集指标、AOEP 义务得分、硬指标五件套、隔离泄漏、P50/P95 延迟、逐条目、可复现性、配置、判定、目标核销）是否封闭枚举，使 schema 校验可判定；共享 `$defs` 的合并与引用解析方式是否写明？[Completeness, Clarity, Spec §FR-021, §FR-022, contracts/README.md §1]
- [x] CHK047 不可测量项的编码是否对比率型与数值型分别定义（含 `value: null`/`rate: null` 与原因字段），并显式禁止记为 0 或 100%？[Clarity, Spec §FR-024, §SC-011, contracts/README.md §3]
- [x] CHK048 "历史产物不覆盖重写"是否被操作化（输出路径已存在即拒绝、多次运行落带运行标识的独立工件或 `runs/<RUN_ID>/`），且是否点名纠正既有无条件重写行为（`eval/hard_metrics_014.py:435`）？[Measurability, Spec §FR-023, §SC-010, Plan §Complexity Tracking]
- [x] CHK049 非延迟指标的可复现性（同快照同版本、既定容差、重跑次数）是否量化，且延迟是否明确只记录分位、环境敏感标注、不设通过门、不参与容差判定；"基线锚点而非改进"与不含 `enters_default_path` 的表述是否一致？[Clarity, Consistency, Spec §FR-021, §FR-026, §FR-027, §FR-055, §SC-023]
- [x] CHK050 报告的达成判定与未达成项处置是否与独立核销工件同源（避免两处结论各说一套），且评测登记是否要求覆盖数据集、报告与运行器用法与重跑口径？[Consistency, Spec §FR-023, §FR-025, research.md R4/R13]

## 八、全集回归（001–014 逐组重跑）

- [x] CHK051 回归范围是否以**封闭组清单**表述（1.0 六组、2.0 两组、012–014 各组及其 E2E、AOEP 与宿主证据），使漏测可被检出？[Completeness, Spec §FR-054, §SC-020]
- [x] CHK052 "按各自口径"是否逐组指向权威判据来源（既有报告、预冻结判据或既有套件），而非留待实现期自行解释？[Clarity, Gap, Spec §FR-054]
- [x] CHK053 依赖模型的组是否完整要求 record + replay 两轮（记录轮冻结模型响应与缓存指纹；重放轮真实网络调用 = 0；重放轮为唯一过闸依据；实时调用不得过闸）？[Completeness, Spec §FR-054, §SC-020]
- [x] CHK054 容差制度是否区分明确（非延迟 1% 相对容差、安全指标零容差且不得替代），且未执行项是否要求以 `not_executed` 表示、不得记为通过？[Measurability, Consistency, Spec §FR-054, §FR-055, Plan §Validation 6]
- [x] CHK055 回归证据是否要求逐组登记 `mode`（取值域固定）、缓存指纹/manifest 哈希与重放网络调用计数？[Clarity, Spec §FR-054, contracts/README.md §6]
- [x] CHK056 FR-054 的 record + replay 正文与 plan 中"规格同步项"所述"正文尚未补录"是否已调和为同一义务；历史回归报告零覆盖是否作为界内约束写明？[Conflict, Completeness, Plan §Validation 6, Spec §FR-054, §SC-020]
  - **已处置（2026-10-09）**：实测 **spec.md 的 FR-054 正文已含 record + replay**（记录轮冻结模型响应与缓存指纹、重放轮真实网络调用 MUST 为 0、非延迟指标以重放轮判定、实时调用不得过闸、缓存指纹与重放调用计数随证据登记）。因此 plan.md Validation Gate 6 的"规格同步项"已删除，替换为"已核验 FR-054 正文含 record+replay（T061 负责核验登记，不再编辑正文）"；quickstart.md VS-13 的对应段落已改为核验结论；tasks.md T061 已从"补齐表述"改为**只读核验、MUST NOT 追加**。历史回归报告零覆盖由 FR-054 正文、SC-020 与 T058–T060 三重约束。

## 九、文档债核销

- [x] CHK057 四类文档工件是否以规范路径与必需章节列出（迭代路线至 3.0、根 README 记忆能力章、技术架构说明书 3.0 章、001–014 status），并明确两份当前不在工作区的文档按同一路径重建？[Completeness, Spec §FR-047–§FR-050, §SC-017]
- [x] CHK058 "路径被版本控制忽略仍 MUST 产出"是否显式写明，使交付判定不依赖版本控制状态、也不得以"未纳入版本控制"降级？[Clarity, Spec §Edge Cases, §FR-047, §Assumptions]
- [x] CHK059 技术架构说明书的**最小增量**范围是否被界定（新增"记忆回路"章 + 仅 §6/§7 消除矛盾的最小修订、其余骨架与结论不动、修订须留可核查变更说明）？[Clarity, Spec §FR-049, §SC-017]
- [x] CHK060 "不得超售"是否给出可判定的反例清单（如把默认关闭的巩固描述为已默认开启）与零实例判据；001–014 状态更新规则（011–014 草稿→已交付、001–010 复核一致、未达成发布结论零改写）与蓝图仅头部加注的冻结边界是否同时写明？[Measurability, Consistency, Spec §FR-048, §FR-050, §FR-052, §SC-017, §SC-018]

## 十、3.0 七项目标逐项核销判据

- [x] CHK061 实施蓝图 §1 的七项目标是否以唯一 ID 与目标陈述封闭枚举，判定取值域（achieved/partial/not_achieved）与"恰好七项"的完备性判据是否定义？[Completeness, Spec §FR-051, contracts/finalization-ledger.schema.json]
- [x] CHK062 每项目标是否绑定**机器可复核判据**与证据指针，且证据指针被要求指向本次运行的真实产物路径（不得指向规划文档或未运行的口径）？[Measurability, Spec §FR-051, research.md R13]
- [x] CHK063 partial/not_achieved 项是否强制携带处置（含触发条件），且该约束以结构方式强制而非仅文字要求？[Completeness, contracts/finalization-ledger.schema.json allOf]
- [x] CHK064 已知未达成目标（巩固受益）是否被要求记为 not_achieved/不可计算并给出触发条件，同时 013 的既有结论（incomplete、`default_enable_eligible=false`、开关默认关闭）零改写？[Consistency, Spec §FR-025, §SC-021, research.md R13]
- [x] CHK065 定稿硬门四项（投毒全过、AOEP 全过、硬指标五件套与隔离泄漏全过、全集回归无回归）是否表述为**合取**，且任一项不满足都必须判不通过、不得以"部分达成"含糊通过？[Clarity, Spec §FR-053, §SC-019]
- [x] CHK066 核销记录的**独立工件属性**与既定位置是否写明，且与报告 `goal_ledger` 的关系（同源、避免双真相）是否定义？[Consistency, Gap, Spec §FR-051, §Assumptions, contracts/finalization-ledger.schema.json]

## 十一、跨类别一致性、边界与可追溯性

- [x] CHK067 是否建立了需求与验收判据的 ID 追溯规则，使每个 FR 至少映射一个 SC 与一个用户故事，并覆盖新增的 FR-055 与 SC-024（既有 requirements.md 验证日志仅追到 FR-054/SC-023）？[Traceability, Gap, Spec §Requirements, §Success Criteria]
  - **已处置（2026-10-09）**：追溯范围已更新为 **FR-001–FR-060 / SC-001–SC-027**——plan.md Requirement Coverage 补齐 FR-056–FR-060 并映射到 US3/US5/US8 与 T068–T074；spec 的 FR-056–FR-060 与 SC-025–SC-027 均已建立；checklists/requirements.md 的验证日志已同步追到 FR-060/SC-027。
- [x] CHK068 零分母与"不可测量"语义是否只定义一次并在 AOEP（含逐投影）、硬指标五件套、隔离泄漏、巩固受益与报告中一致复用（不记 0、不记达标、必带原因）？[Consistency, Spec §Edge Cases, §FR-024, §FR-030, §FR-055, §SC-011]
- [x] CHK069 延迟相关要求是否在 SC-023、FR-055 与报告契约间一致（仅记录 P50/P95、标注环境敏感、不设通过门、不参与容差判定、不被用于其他指标的门限）？[Consistency, Spec §FR-055, §SC-023]
- [x] CHK070 范围外清单是否清晰到足以防止以"重建 012–014 已交付能力"充当本 Feature 的测量证据（事件日志与六投影、写读管线、检测接线、巩固裁决器、既有 E2E 与既有 AOEP 断言等）？[Clarity, Spec §范围外]
- [x] CHK071 "无对照证据不得宣称改进"是否在 FR-026、SC-021、报告与核销工件间一致表述并具有零实例判据？[Consistency, Spec §FR-026, §SC-021]
- [x] CHK072 带外部依赖的假设（台账文件缺失、两份文档缺失、cache-manifest 房规、缓存指纹口径）是否标注被推翻时的影响与替代来源，而非以假设代替需求？[Assumption, Spec §Assumptions, §依据与依赖]
- [x] CHK073 既有 001–014 契约、数据集与历史报告的**零改动**边界是否与写入范围交叉核对（字节零改动、schema 不被复用改写）？[Coverage, Spec §SC-022, Plan §Validation 1, contracts/README.md §与既有契约的关系]

## Notes

- 仅当评审确认该需求质量判据满足时，才将条目标记 `[x]`；仍需澄清、修正或评审判断的条目保持未勾选。
- `/speckit-implement` 读取本清单的勾选状态作为门禁，且**不得**修改标记。
- `checklists/requirements.md` 由 `/speckit-specify` 与 `/speckit-clarify` 维护，具有独立的生命周期，不受本自定义清单约束。
- 高优先风险条目（建议优先评审）：CHK016（五不变量 vs 四条 AOEP）、CHK041（统计端点路径冲突）、CHK052/CHK056（逐组口径与 FR-054 同步）、CHK067（FR-055/SC-024 追溯缺口）、CHK048（历史产物不覆盖的既有反例）、CHK030（隔离泄漏与零容差）。
- **2026-10-09 `$speckit-analyze` 处置轮**：CHK016（五不变量已全部落入 FR-014/FR-056 与两份契约枚举）、CHK041（端点统一为 `/api/memories/stats`）、CHK056（FR-054 正文已含 record+replay，陈旧"尚未补录"陈述已清除）、CHK067（追溯更新为 FR-001–060 / SC-001–027）均已给出显式处置。同轮新增判据：CHK074–CHK078（见下）。
- **CHK074–CHK080（2026-10-09 追加，源自一致性分析；均已评审并给出结论）**：
  - [x] CHK074 五不变量是否与《宪法》XIII 第三条逐字对应，且 `authority_monotonicity` / `provenance_preservation` 在数据集、报告与契约枚举中齐全（FR-014/FR-056）？[Constitution §XIII ¶3, Spec §FR-014, §FR-056]
    - **结论**：已满足。FR-014/FR-056 声明五条不变量；`aoep-obligation-dataset.schema.json` 的 `invariant` 枚举、`invariants` 五键与 `machine_criterion` R6.1–R6.6，以及 `memory-benchmark-common.schema.json` 的 `aoepCaseEntry.invariant` 与 `aoepBlock.by_invariant`（五键 `required`）均已同步；`authority_boundary` 不再作为活动不变量名。
  - [x] CHK075 `authority`/`scope`/`mutability`/`provenance`/`recoverability`/`actionability` 六轴状态元数据齐备率是否有非零分母的实测载体（FR-058/SC-025）？[Constitution §XIII ¶2, Spec §FR-058]
    - **结论**：已满足。FR-058 要求报告 `hard_metrics.state_metadata_completeness` 逐轴给出分母与结论（`metadataAxis`，`examined == 0` ⇒ `not_measurable` + 原因）；T071 承担实测。
  - [x] CHK076 投影完整率是否给出逐投影分母与 `drift = 0` 结论，且明确禁止以 route 打桩或组件测试替代实测（FR-057/SC-025，硬约束 6）？[Constitution 硬约束 6, Spec §FR-057]
    - **结论**：已满足。FR-057 + 报告 `hard_metrics.projection_integrity`（六视图 `projectionIntegrityView`，`examined`/`drift`，零分母守卫）落地；T070 承担实测并显式禁止打桩替代。
  - [x] CHK077 契约是否以结构方式强制零分母守卫（`total == 0` ⇒ `not_measurable` + 原因）与 `all_passed` 与各子指标绑定，以及七项目标 `id` 1:1 与 `goals[4].verdict = not_achieved`（SC-026/SC-027）？[Spec §SC-026, §SC-027, contracts/memory-benchmark-common.schema.json]
    - **结论**：已满足。四个比率块 `total == 0` 守卫、`hardMetricsBlock.all_passed == true` 蕴含各子指标达标、`goals` `uniqueItems` + 逐 id 恰一次 `contains`/`maxContains`、`id == 4` ⇒ `verdict = not_achieved` 均由 `allOf`/`if-then` 结构强制；独立 schema 测试以反例验证（total=0 且 rate=1.0 被拒、重复 id 被拒、目标 4 记 achieved 被拒、报告缺 `regression` 被拒）。
  - [x] CHK078 目标 MCP 宿主评测与成本评测是否被**如实登记为范围外 + 触发条件**（而非以无条件 PASS 表述），且 FR-054 回归是否登记**组→测试映射**（FR-059/FR-060）？[Constitution X, Spec §FR-059, §FR-060]
    - **结论**：已满足。FR-060 + spec「范围外」新增条目 + plan Constitution Check X 行改为 `PASS（含 FR-060 范围外登记）` + T073 范围决策登记；FR-059 要求组→测试映射登记入 `regression_group_map.json`，由 T058–T060 承担。
  - [x] CHK079 无显式 scope 的读写拒绝是否有 **spec 级要求**（FR-061/SC-028），且缺失/空引用与歧义引用是否**各自构造用例、各自给出非零样本量**（缺失 ≠ 歧义），不以「未尝试」记为 0？[Constitution 硬约束 2, Spec §FR-061, §SC-028, §Edge Cases]
    - **结论**：已满足。FR-061 与 SC-028 已建立；Edge Cases 与 US3 验收场景 4 覆盖缺失/空引用；T024（歧义）与 T075（缺失/空）分开构造并各自要求非零样本量；quickstart VS-14 独立验证。
  - [x] CHK080 报告 `regression.groups[]` 与 `regression_group_map.json` 两处形状是否分列，`command`/`test_module` 仅属映射件而不写入报告块（FR-059/SC-020）？[Spec §FR-059, contracts/memory-baseline-report.schema.json, data-model.md §5]
    - **结论**：已满足。报告块形状受契约 `additionalProperties:false` 约束，恰为 `{group, runner, mode, cache_manifest_hash?, replay_real_network_calls?, non_latency_reproducible?, artifact}`；五元组 `{group, runner, command, test_module, artifact}` 只落在映射件；T060 与 data-model §5 已分列并显式禁止混用。
- 条目编号全局递增，便于引用；新增评审轮次时在本文件末尾追加并续编 CHK 编号，不得删改既有条目。
