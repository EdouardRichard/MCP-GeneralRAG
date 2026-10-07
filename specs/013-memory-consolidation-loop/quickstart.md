# Quickstart: 013 记忆巩固回路验收

Phase 1 (T001-T017) has executed evidence below. Later-phase commands remain planned until their tasks and review gates are complete. 契约见 [contracts/README.md](contracts/README.md)，策略/模型见 [data-model.md](data-model.md)。所有数据库写入验收串行，使用隔离数据库/Qdrant/data_root，不清空正式数据。

## 1. 环境与证据目录

### Phase 1 audited setup (2026-10-06)

Implementation checkout: `C:/Users/Richard/.codex/worktrees/013-memory-consolidation-loop/docsToCode`,
branch `codex/013-memory-consolidation-loop`. Python is 3.12.9. `alembic heads` confirmed
`0094_memory_management_audit`; the additive successor is
`backend/alembic/versions/0095_memory_consolidation_loop.py`. Deployed migrations remain immutable.

The isolated PostgreSQL database is `memory_consolidation_013_82b4db551fd04836`, a populated
independent clone on the configured PostgreSQL server. Both PostgreSQL URL variables must
name this database. The isolated Qdrant endpoint is `http://127.0.0.1:16333`; `DATA_ROOT` is
`C:/Users/Richard/AppData/Local/Codex/013-isolation-20261006/data-root`. Never run these writes
using the original `.env` database identity. The local, ignored runner loads credentials in
memory and applies all overrides without printing credentials:

Review fix round 1 encountered a full D: volume. The isolated Qdrant data was copied,
preserving its D: source, to `C:/.codex-013q`; the test service now uses that short C: storage
path on the same loopback ports (HTTP 16333, gRPC 16334). `isolation_runner.py check`
verified the database identity, head and Qdrant health after restart. Original stores were
not changed. The D: copy is retained for recovery and is no longer the active service root.

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py check
python .superpowers/sdd/013-tasks/isolation_runner.py alembic upgrade head
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/contract/test_consolidation_schemas.py -q
```

The clone initially contains 132596 authority events and starts at 0094. Its historical
manifests reference the original file root and Qdrant history, which is not copied. Tests
create independent scopes or perform legitimate isolated rebuilds; direct manifest edits
are prohibited. Database test runs are serial. The runner clears inherited proxy variables
and sets `NO_PROXY=127.0.0.1,localhost` for loopback fake providers.

Reuse audit: `MemoryEventStore` owns append-only events; `reduce_events` seals immutable
state for `MemoryProjectionStore`. The existing six outputs are relational entries, dense,
links, summary, files, and salience; publication requires all six verified outputs and a
transaction-bound receipt. `MemoryService.apply_event` refuses raw callers. `AgentBase.run`
already performs Schema validation and fallback, but a fallback may be `{}` and must be
revalidated before later Distiller wiring. `server._ttl_cleanup_loop` and
`maintenance_service.run_memory_maintenance` are the existing maintenance boundary.
`api.knowledge_sources.upload_knowledge_source` is the current upload entry; promotion will
reuse the source/ProcessingRun registration boundary in its later phase. Phase 1 does not
wire LLMs, automatic triggers, or memory-changing consolidation commands.

Phase 1 evidence is recorded in `.superpowers/sdd/013-tasks/phase1-report.md`; preflight
policy/reducer/AgentBase baseline: 15 focused tests passed. T017 initial verification on
2026-10-06: 77 Phase 1 tests passed in 55.32s; 71 affected legacy memory/domain tests
passed in 5.11s. Review fix round 1 verification: 81 Phase 1 tests passed in 67.16s;
71 affected legacy tests passed in 5.15s. No tests were skipped. Run the Phase 1 suite
from the worktree root:

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/contract/test_consolidation_schemas.py tests/unit/test_consolidation_policy.py tests/unit/test_consolidation_selection.py tests/integration/test_013_consolidation_admission.py tests/integration/test_013_consolidation_audit.py tests/integration/test_013_consolidation_migration.py tests/integration/test_013_consolidation_windows.py -q --tb=short
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/unit/test_memory_policy_defaults.py tests/unit/test_domain_profile_sync.py tests/unit/test_domain_profile_seed.py tests/unit/test_memory_projection_equivalence.py tests/unit/test_memory_trajectory_authority.py tests/unit/test_memory_event_constraints.py tests/unit/test_memory_transaction.py tests/unit/test_memory_supersede.py tests/unit/test_memory_rollback.py tests/unit/test_migration_012_memory.py tests/contract/test_memory_schemas.py tests/contract/test_domain_profile_schema.py -q --tb=short
```

The fixture guards require a nonempty `CONSOLIDATION_ISOLATED_DATABASE` matching the
database in the configured URL; the runner supplies this explicit opt-in. The populated
upgrade test creates a fresh temporary 0094 database with legacy events, source/version/chunk,
entry and link projections, then upgrades and verifies preserved authority/defaults.
It now publishes an actual 0094 manifest through the six-projection implementation from
Git baseline `6796c0c` before upgrading; that Git object is required by the fixture.
It verifies unchanged saved manifest data, compatible read-only normalization, and rejection
of corrupt fingerprint/state or unknown legacy verification version. It does not depend on
the disposable clone's current schema. Retained authority with no complete manifest requires
recovery; only scopes with no authority can produce a verified empty snapshot. Selection
scans for fitting entries in stable order and reports `input_budget_excluded` when every
eligible episode exceeds the input budget; excluded versions remain unconsumed.

The disposable clone now contains v2 control grants, so destructive downgrade is refused.
The still-unreleased 0095 draft was synchronized there by the ignored
`.superpowers/sdd/013-tasks/phase1_schema_sync.py`: observation sequence high water,
explicit unknown usage default, and the strengthened window guard. Future migration edits
must synchronize only the isolated clone or use a freshly prepared database.
Runtime control commands own their transaction and reject any existing session transaction;
callers must explicitly finish their reads or writes before admission, heartbeat, release,
takeover, observation, purge, or commit fencing. Pending window publication raises an error
while retaining recovery material and the previous complete manifest.

Python≥3.12及backend依赖、PostgreSQL/Qdrant、已有embedding与可选真实LLM配置；DATABASE_URL/QDRANT_URL/DATA_ROOT指向隔离实例。至少一个合法可编辑域，不能修改内置档案绕过限制。当前writer/reader服务停止后运行lease测试；loopback请求不经代理。

以下所有命令从隔离 worktree 的仓库根目录执行。runner 的环境覆盖仅对其自身及子进程有效，每个测试、迁移、评测和服务进程均经此入口启动；新终端也先运行 check。

```powershell
$consolidationRunName = '013-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$consolidationEvidenceDir = Join-Path (Resolve-Path eval).Path ('runs/' + $consolidationRunName)
New-Item -ItemType Directory -Path $consolidationEvidenceDir
$env:CONSOLIDATION_EVIDENCE_DIR = $consolidationEvidenceDir
python .superpowers/sdd/013-tasks/isolation_runner.py check
python .superpowers/sdd/013-tasks/isolation_runner.py alembic upgrade head
```

新目录不能覆盖。迁移验证当前head后运行：从非空012库升级，旧flat consolidate/evidence/supersedes/历史revision仍可重放；typed列与authority一致，两scope资格独立，context默认无值，默认开关false。存在v2事件时禁止破坏性downgrade。

## 2. 契约与独立阶段

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/contract/test_consolidation_schemas.py tests/contract/test_consolidation_management_api.py -q
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/unit/agents/test_memory_distiller.py tests/unit/test_consolidation_selection.py tests/unit/test_consolidation_adjudicator.py -q
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/unit/test_consolidation_policy.py tests/unit/test_consolidation_fallback.py -q
```

检查四action/附件、unknown权限字段拒绝、finite confidence与阈值等于/低于边界、硬保护effect全矩阵、域中立提示、不可信JSON、所有新增文本净化。fallback再校验，畸形fallback不得产生事件。同clock/policy下模型正常/故障/无模型的确定规则产出一致；TTL独立运行。

覆盖同批proposal_ref指向获批输出、未知/自引用/循环/驳回输出拒绝；共享来源或输出依赖的原子组超max_events_per_group整组拒绝、不消费输入，不能拆组规避。

## 3. 数据库资格、窗口、恢复

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/integration/test_013_consolidation_admission.py tests/integration/test_013_consolidation_windows.py -q
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/integration/test_013_consolidation_commit.py tests/integration/test_013_consolidation_recovery.py -q
```

三触发在DB冲突处只有一个活动资格，其余明确busy+existing run；不同scope可独立执行。过期接管/进程崩溃/旧holder后到结果成功提交0。窗口start包含/end排除，稳定event排序，预算不是新窗口，检查点推进不吞掉驳回/失败/未处理；清理7天run后从window grants/完成结果恢复待处理资格。reference独立，quarantined/retired/superseded/expired/incomplete进入两集合均0。

关闭开关/缺普通配置时，idle/manual/volume仍拒绝或跳过；可信writer必要支持失效钩子可通过同一资格/fence执行受裁决invalidate，报告support_maintenance/deterministic_propagation、window=null/input_event_ids=[]与完整历史来源/失效proof。断lease、旧token、支持proof变化仍不得提交；REST/模型伪造维护上下文被拒，Distiller调用、create/merge/link/context/candidate及源消费均0。

注入scope/证据/配额/政策/词表变化于propose和commit之间，最终再裁决；relational/link/context失败rollback，Qdrant/file失败pending不可读且旧complete可读。恢复相同result key不得重复输出或提前消费输入。

## 4. 派生投影、依赖与语境

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/integration/test_013_consolidation_projection_rebuild.py tests/integration/test_013_consolidation_dependencies.py -q
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/unit/test_consolidation_context_visibility.py tests/unit/test_consolidation_link_expansion.py -q
```

先生成非空高级边和context/keywords，保存逐字段/来源/scope/六投影指纹；只在隔离副本清空投影和到期审计，full与snapshot+delta重建一致。rollback恢复上一批准context/link具体版本，模型/transport调用0；SQL与Python每步一致。

historical源正常TTL/归并/purge不使有效结论失效；必要支持被明确否定/live依赖退场时过时结论不再消费。association不传播，环/扇出预算终止，soft不通过间接merge/retract推翻hard。context有无A/B候选、排序、embedding输入完全一致，仅最终显示字段不同。扩展默认关；增强故障原直接合法结果可用且预算不增加。

## 5. 人工晋升与管理面

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/integration/test_013_consolidation_promotion.py tests/integration/test_013_consolidation_e2e.py -q
```

合法hard-anchored semantic标候选；无corpus的soft procedure有完整源链但无候选。任何模型/维护/量阈值自动创建正身source=0。POST promote显式人工、同域复验，创建原上传链pending任务且保留memory；并发重复candidate_version只一个稳定task/source/initial run。调度前崩溃可恢复，失败重试同task/source，未发布不能报published。

数据库写入测试结束后，在独立终端启动writer管理服务（端口已占用改用空闲端口，并同步调整请求地址）：

```powershell
$env:INSTANCE_MODE = 'writer'
python .superpowers/sdd/013-tasks/isolation_runner.py check
python .superpowers/sdd/013-tasks/isolation_runner.py eval -m uvicorn rag_mcp.server:app --host 127.0.0.1 --port 18000
```

使用现有scope列表选择可编辑测试scope并遵循原POST policy管理流程，提交显式consolidation配置后opt-in；缺配置拒绝、禁用拒绝要分别记录。按 [management-api.md](contracts/management-api.md) 手动触发202并轮询报告，阻塞运行后第二触发409带run_id。配置启用不直接授予扩展三闸许可。reader实例调用写操作沿MEMORY_WRITE_UNAVAILABLE拒绝，不注册新MCP工具。

## 6. 012八项、五不变量与全集

停止验收服务再串行执行：

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/integration/test_012_memory_e2e.py tests/integration/test_012_aoep_obligations.py tests/integration/test_013_consolidation_aoep.py -q
$env:MEMORY_DIAGNOSTICS_OUTPUT = Join-Path $consolidationEvidenceDir 'read-diagnostics.json'
python .superpowers/sdd/013-tasks/isolation_runner.py pytest -vv --tb=short --durations=30 -p memory_pytest_evidence --memory-evidence="$consolidationEvidenceDir/memory-trace.json" --junitxml="$consolidationEvidenceDir/backend-pytest.xml"
python .superpowers/sdd/013-tasks/isolation_runner.py eval eval/run_regression_011.py --output-dir "$consolidationEvidenceDir/regression"
```

013证据fixture读取CONSOLIDATION_EVIDENCE_DIR，导出consolidation-trace.json、authority-snapshot.json和冻结data/版本清单；新路径契约见evaluation-contract。测试不能只输出预设pass。012八项维持原口径；AOEP权威边界、范围不扩张、来源保留、删除传播、可追溯rollback各至少2例。001–012其余评测/target-host/已有frontend checks按 [012 quickstart](../012-memory-foundation-write-read-loop/quickstart.md) 和eval/README.md补齐，生成新的012 acceptance与完整旧集证据。skip/missing不得算通过。

## 7. 受益首轮记录与次轮严格重放

沿 [evaluation-contract.md](contracts/evaluation-contract.md) 在调用前冻结至少六条实域query/相关性/时钟/模型/版本，同一原始authority snapshot复原到两个隔离副本。runner负责复原与校验，不从已经巩固的库开始次轮。以下runner/fixture接口由实施交付：

```powershell
$env:AGENTIC_LLM_CACHE_PATH = Join-Path $consolidationEvidenceDir 'llm-cache'
python .superpowers/sdd/013-tasks/isolation_runner.py eval eval/run_consolidation_comparison.py --dataset eval/consolidation_eval_dataset.json --snapshot "$consolidationEvidenceDir/authority-snapshot.json" --mode record --cache-manifest "$consolidationEvidenceDir/cache-manifest.json" --gate-variant consolidated_candidate_expansion --suite "$consolidationEvidenceDir/backend-pytest.xml" --trace "$consolidationEvidenceDir/consolidation-trace.json" --memory-acceptance "$consolidationEvidenceDir/012-acceptance.json" --regression "$consolidationEvidenceDir/regression/012_regression_summary.json" --output "$consolidationEvidenceDir/consolidation-record.json"
python .superpowers/sdd/013-tasks/isolation_runner.py eval eval/run_consolidation_comparison.py --dataset eval/consolidation_eval_dataset.json --snapshot "$consolidationEvidenceDir/authority-snapshot.json" --mode replay --cache-manifest "$consolidationEvidenceDir/cache-manifest.json" --gate-variant consolidated_candidate_expansion --suite "$consolidationEvidenceDir/backend-pytest.xml" --trace "$consolidationEvidenceDir/consolidation-trace.json" --memory-acceptance "$consolidationEvidenceDir/012-acceptance.json" --regression "$consolidationEvidenceDir/regression/012_regression_summary.json" --output "$consolidationEvidenceDir/consolidation-replay.json"
```

追加其他旧组报告到--regression参数；单一六组summary不是整个001–012证据。两轮保存各query三path指标/来源/失败、成本/延迟。K5、MRR与nDCG均相对≥3%，HitRate/Recall/Precision非降；相对零基线不可计算不能pass。次轮缓存成功/失败一致100%、真实网络0、非延迟漂移≤1%，硬安全零容差。损坏/miss/version mismatch不能回源补齐后宣称过闸。

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/unit/test_consolidation_comparison_report.py tests/integration/test_013_consolidation_llm_faults.py -q
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/unit/test_consolidation_gate.py tests/unit/test_consolidation_link_expansion.py tests/contract/test_consolidation_recall_extensions.py -q
```

报告质量/安全/回归全pass才default_enable_eligible；报告不发布policy。质量未过/证据缺失两个默认开关false，能力保留；任一hard失败阻断发布。规划检查通过不能代替上述运行证据。

## Phase 3 verification (2026-10-06, T029-T037)

Phase 3 implementation evidence is in `.superpowers/sdd/013-tasks/phase3-report.md`.
This is component and isolated-store verification; Phase 4 publication and Phase 7
automatic triggers are not implemented by this phase. Root owns independent review.
Both default switches remain false and checklist bytes are unchanged.

Run serially from the repository root:

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/unit/agents tests/unit/test_consolidation_fallback.py tests/unit/test_consolidation_injection_boundary.py tests/integration/test_013_consolidation_llm_faults.py tests/integration/test_013_consolidation_audit.py tests/integration/test_013_consolidation_admission.py tests/unit/test_consolidation_adjudicator.py tests/unit/test_consolidation_hard_protection.py tests/unit/test_consolidation_proposal_graph.py tests/unit/test_consolidation_deterministic_rules.py tests/unit/test_consolidation_policy.py tests/unit/test_consolidation_selection.py tests/contract/test_consolidation_schemas.py tests/unit/test_memory_validators.py -q --tb=short -p no:cacheprovider
python .superpowers/sdd/013-tasks/phase3_lint_delta.py
rg -n 'session|MemoryService|governance|upload|tool|commit|flush|record' backend/src/rag_mcp/agents/memory_distiller.py
```

Observed: **749 passed in 25.53s**, no skips; Ruff delta against `d5ef80f`:
zero new findings, 14 pre-existing findings. The `rg` command has no matches
(exit 1 is expected). The injection suite also performs AST/import/call checks,
checks the retrieval factory, and spies on AsyncSession, MemoryService,
MemoryGovernance, MemoryEventStore, upload/reprocessing/ingestion entry points.
Zero calls were observed on success and fault paths. String absence alone is
not the boundary evidence.

Reviewed call path: MemoryDistiller -> fixed prompt/canonical JSON + stateless
redaction/detection -> LLMClient strict whole-response parser -> AgentBase
validation/fallback -> propose final whole-package validation -> immutable
ProposalBatch. The packaged schema is checked against the exact contract.
Validators import ORM types for older provenance services, but this path calls
only their pure sanitizers; it never constructs the session-bearing validator.
The only resource read in the agent is its packaged schema; model text cannot
supply a path or execute a tool. No retrieval graph edits were made.

DistillerProvider receives only the agent, immutable window, and call-local
accounting. A process-wide two-slot semaphore is released by the synchronous
worker's finally block. Tests block the underlying httpx call, time out/cancel
waiters, reject a third call, release one real call, and admit the next. The
event loop keeps progressing and late outputs are not delivered. Receipts are
call-local snapshots, not deltas of shared client counters; cached success and
failure report zero transport. Unknown tokens/cost remain null.

Injection uses recursive input/output checks, exact-schema rejection of unknown
authority fields, pure adjudicator safety rejection of schema-valid text, and
scope-aware audit withholding. Normal/fault comparisons preserve concrete
deterministic merge decisions and natural TTL intents. These are proposals and
approved effects, not a claim of Phase 4 publication or input consumption.

## Phase 4 verification (2026-10-07, T038-T052)

Phase 4 implementation evidence is in `.superpowers/sdd/013-tasks/phase4-report.md`;
the independent review verdict (PASS) is in `.superpowers/sdd/013-tasks/phase4-review.md`.
Implementation commit `61c1c57` adds migrations 0096_consolidation_authority,
0097_consolidation_publish_fence and 0098_consolidation_integrity (0095-0098 are
deployed and byte-frozen; later SQL corrections require 0099+ successors).
Applied migration SHA256: 0096 `254F3F7891E946B1043270043E57861AFE1527F1782D4241055513D87C966DE2`,
0097 `3FCC689F0D1D30C2742ADB44925C5CFA2D052C7DBC26E59CA2CABCB19BE03426`,
0098 `B1D3A45102ED321661EF0DB81F7ACC3A210B332BCBFA65885C248A990204FC0E`.

Root final verification: full isolated coverage collected 2069 tests, 2068 passed;
the sole failure is the pre-existing unrelated
`tests/unit/orchestration/test_agentic_metrics.py::test_record_agentic_retrieval_run_writes_row`.
The Phase 4 focused command collected 734 tests: 734 passed in 742.60s, exit 0.

Independent re-verification of the Phase 4 matrix (this session, serial, isolated
runner; commit/parity/recovery/rebuild/context plus all Phase 4 matrix files and
the populated 012 upgrade):

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/integration/test_013_consolidation_commit.py tests/integration/test_013_consolidation_complete_matrix.py tests/integration/test_013_consolidation_final_review.py tests/integration/test_013_consolidation_hash_matrix.py tests/integration/test_013_consolidation_history_matrix.py tests/integration/test_013_consolidation_lawful_merge.py tests/integration/test_013_consolidation_live_boundaries.py tests/integration/test_013_consolidation_observation_matrix.py tests/integration/test_013_consolidation_operation_matrix.py tests/integration/test_013_consolidation_permanent_matrix.py tests/integration/test_013_consolidation_phase4_boundaries.py tests/integration/test_013_consolidation_projection_rebuild.py tests/integration/test_013_consolidation_recovery.py tests/integration/test_013_consolidation_remaining_matrix.py tests/integration/test_013_consolidation_replay_parity.py tests/integration/test_013_consolidation_migration.py tests/unit/test_consolidation_context_visibility.py tests/unit/test_consolidation_equivalence_normalization.py -q --tb=short -p no:cacheprovider
```

Observed: **159 passed in 748.49s**, exit 0, no skips. Environment note: the
isolation runner now passes `env=dict(os.environ)` to child processes because
Windows child processes otherwise inherit the stale process environment block
(NO_PROXY containing `[::1]` broke httpx proxy-mount parsing for the Qdrant
client); the runner remains a local ignored tool.

## 8. 只读闸口登记与撤销（实施后）

按 [gate-proof.md](contracts/gate-proof.md) 在评测前冻结拟部署的完整enabled目标policy与当前gate_binding；baseline/direct/expansion只改隔离runner路径选择。一个013.2报告覆盖一个scope的六查询。首轮/重放的gate_binding及环境字段须一致；当前data_hash含普通源authority和published证据，013内部效果/rebuild不自使其失效，snapshot_hash仍是完整评测输入。

仅在T103隔离目录验收：真实candidate_expansion报告passed且当前绑定匹配时，审阅真实三闸/record-replay证据，将报告放入DATA_ROOT之外的部署者控制目录，按gate-registry.schema.json建立scope唯一entry，固定report_path/精确SHA256/gate_binding/expires_at，并原子安装登记。部署者在writer/reader启动环境显式设置CONSOLIDATION_GATE_REGISTRY_PATH为登记绝对路径，服务只读；缺省None仍无证明。runner不自动登记或修改policy，未经过真实闸口的fixture不得安装为生产证明。

真实failed/incomplete或仅direct过闸时，不安装扩展许可；验收拒绝授权、合法直接召回与默认关闭，保留报告结论。T055显式fixture仍验证loader正向逻辑，不能替代真实通过报告。拟部署policy必须已沿合法管理流程发布并进入冻结authority快照；随后再发policy grant或改变源材料须重新核验/重评，不改旧报告binding凑匹配。

验证include_linked=true在域许可+当前合法证明下增强；direct-only报告、缺配置/登记、错scope/绑定、坏hash、同mtime篡改、过期/删除登记/换policy或源证据均下一请求not_available/disabled并保留原合法直接候选。记录新增IO≤100ms计入原3秒预算、无网络/模型/生产写入、旧flags=false不读取文件。撤销由部署者原子删entry或登记文件完成，不保留缓存授权；无需清理记忆或改变派生投影。

## Phase 5 verification (2026-10-07, T053-T064)

Phase 5 added typed-link adjudication, deterministic_propagation support
maintenance, the read-only gate proof loader, and the additive recall v2
flags. Migrations 0095-0098 stayed byte-frozen; two successors were applied to
the isolated database: `0099_consolidation_propagation` (SHA256
`23A84EB355D029705FB1AD6531CAEC9D528AE7CCF6847E8D0D435D4BB297595B`) and
`0100_propagation_guard_fix` (SHA256
`808BDEDE9F56F2CCD827C679C6BC8DB40CD55F7967DBD835DC49716A788E8C34`), which
repairs one text/jsonb comparison inside the 0099 trigger guard without
editing the deployed file. Isolated head is `0100_propagation_guard_text_fix`.

Lead final acceptance (serial, isolated runner, `-q --tb=short -p no:cacheprovider`,
no concurrent writer; writer leases must be free — two concurrent DB runs
reclaim each other's fixture lease and produce spurious
`WRITER_LEASE_LOST`/`CONSOLIDATION_COMMIT_TIMEOUT`):

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/unit/test_consolidation_links.py tests/unit/test_consolidation_gate.py tests/unit/test_consolidation_link_expansion.py tests/contract/test_consolidation_recall_extensions.py tests/unit/test_consolidation_context_visibility.py tests/unit/test_consolidation_adjudicator.py tests/unit/test_consolidation_hard_protection.py tests/unit/test_consolidation_proposal_graph.py tests/unit/test_consolidation_deterministic_rules.py tests/integration/test_013_consolidation_projection_rebuild.py tests/integration/test_013_consolidation_dependencies.py tests/integration/test_012_live_reader.py tests/integration/test_012_reader_boundaries.py tests/integration/test_012_memory_recall_observability.py tests/unit/test_memory_reader_budgets.py -q --tb=short -p no:cacheprovider
```

Observed: **458 passed in 325.87s**, exit 0, no skips. Supporting runs on the same
final bytes: T054 dependency suite alone **7 passed in 140.89s**; Phase 1-4
regression (22 contract/unit/integration files) **236 passed in 765.88s**; Phase 5
focused unit/contract batch **427 passed in 46.06s** (before the last three Lead
edits below).

Lead corrections applied on top of the phase implementation:

- `tests/integration/test_013_consolidation_dependencies.py`: `admit()` renews the
  fixture's 300s writer lease through `PostgresLeaseWriteCoordinator.renew(...)`.
  A real writer renews its lease; this environment builds dependency fixtures
  slower than 300s, and the runtime correctly refused the expired lease. No
  assertion was weakened.
- `test_frontier_recorded_and_resumed_on_real_persisted_path` restores the
  frontier-record and frontier-resume coverage on the **real persisted path**
  (admission, fence, adjudication, publication, continuation grant, registry
  replay) by patching the planner depth budget to an environment-sized value.
  The exact 32-depth/128-node budgets remain proven against the real planner in
  `tests/unit/test_consolidation_links.py`.
- `services/memory_reader.py`: `_live_support_nodes` revalidates the necessary
  `must_remain_active` evidence of expansion endpoints before they are added, so a
  withdrawn corpus fact cannot be resurrected through link expansion; unreadable
  support is fail-closed for the enhancement and leaves direct results untouched.
  `tests/unit/test_consolidation_link_expansion.py` covers live/withdrawn/version
  mismatch/content mismatch/missing/unreadable. The read role can select
  chunks/knowledge_versions/knowledge_sources (verified in the isolated clone).
- `services/consolidation_gate.py`: the implementation fingerprint now covers every
  applied consolidation migration from `0095_` onward by numeric prefix, so the
  applied `0100` guard repair (and any successor) invalidates an existing gate
  binding instead of being ignored by a frozen prefix tuple.

Known scope limits carried forward (not acceptance failures): the full-scale
32-depth integration cascade cannot be built inside the fixed 30s commit fence in
this environment (super-linear publish path, ~34s per record at 40 entries); the
exact budgets are unit-proven and the integration proof uses the patched budget.
A publish-hot-path performance follow-up is recommended before Phase 8 hard
evidence. `recover_consolidation` keeps a pending maintenance group as pending
(no dedicated null-window retry) — Phase 7 scope.

## Phase 6 verification (2026-10-07, T065-T076)

Phase 6 added candidate marking plus the explicit human promotion loop. 0095-0100
stayed byte-frozen; three successors were applied to the isolated database:
`0101_promotion_pointer` (permanent `promotion_requested`/`promotion_observed`
grants, the `memory_log_state` pointer projection, `guard_promotion_event()` and
the partial unique index `uq_promotion_request`), `0102_promotion_guard_identity`
(conditions the guard's task-identity check so an observation keeps the original
stable task while appending its own event id) and `0103_promotion_guard_skip`
(makes the guard's early return explicit for ordinary management grants whose
payload has no `grant_type`, which SQL three-valued logic previously let fall
through into the promotion shape checks). Isolated head is
`0103_promotion_guard_skip`.

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/unit/test_consolidation_candidates.py tests/contract/test_consolidation_management_api.py tests/integration/test_013_consolidation_promotion.py tests/unit/test_consolidation_adjudicator.py tests/unit/test_consolidation_links.py tests/unit/test_consolidation_policy.py tests/integration/test_013_consolidation_commit.py tests/integration/test_013_consolidation_live_boundaries.py tests/integration/test_013_consolidation_migration.py tests/integration/test_013_consolidation_history_matrix.py tests/integration/test_013_consolidation_projection_rebuild.py tests/integration/test_013_consolidation_audit.py tests/contract/test_knowledge_sources_api.py -q --tb=short -p no:cacheprovider
```

Observed (serial, no concurrent writer): RED first —
`tests/unit/test_consolidation_candidates.py` **18 failed, 2 passed in 0.15s**
(behavior failures, not import errors); then GREEN on the same bytes:
`tests/unit/test_consolidation_candidates.py tests/unit/test_consolidation_adjudicator.py`
**206 passed in 0.66s**; `tests/integration/test_013_consolidation_promotion.py`
**8 passed in 77.82s**; `tests/contract/test_consolidation_management_api.py`
**3 passed in 18.88s**; the combined acceptance batch above **331 passed, 1 failed
in 376.59s**, where the single failure was the populated-012 upgrade test asserting
the `cannot downgrade` refusal text — the new migrations now say
`cannot downgrade promotion authority; use compatible forward deployment`, and the
migration file alone re-ran **2 passed in 10.57s**.

Final serial acceptance on the final bytes — the union of every 013 unit, contract
and integration suite plus the Phase 6 files, the memory contract tests and the
legacy upload contract test:

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/unit/test_consolidation_candidates.py tests/unit/test_consolidation_adjudicator.py tests/unit/test_consolidation_links.py tests/unit/test_consolidation_policy.py tests/unit/test_consolidation_selection.py tests/unit/test_consolidation_context_visibility.py tests/unit/test_consolidation_deterministic_rules.py tests/unit/test_consolidation_equivalence_normalization.py tests/unit/test_consolidation_fallback.py tests/unit/test_consolidation_gate.py tests/unit/test_consolidation_hard_protection.py tests/unit/test_consolidation_injection_boundary.py tests/unit/test_consolidation_link_expansion.py tests/unit/test_consolidation_proposal_graph.py tests/contract/test_consolidation_management_api.py tests/contract/test_consolidation_schemas.py tests/contract/test_consolidation_recall_extensions.py tests/contract/test_memory_management_api.py tests/contract/test_memory_schemas.py tests/contract/test_memory_byte_compat.py tests/contract/test_memory_error_registry.py tests/contract/test_memory_scope_contract.py tests/contract/test_knowledge_sources_api.py tests/integration/test_013_consolidation_promotion.py tests/integration/test_013_consolidation_commit.py tests/integration/test_013_consolidation_live_boundaries.py tests/integration/test_013_consolidation_migration.py tests/integration/test_013_consolidation_history_matrix.py tests/integration/test_013_consolidation_projection_rebuild.py tests/integration/test_013_consolidation_audit.py tests/integration/test_013_consolidation_admission.py tests/integration/test_013_consolidation_complete_matrix.py tests/integration/test_013_consolidation_dependencies.py tests/integration/test_013_consolidation_final_review.py tests/integration/test_013_consolidation_hash_matrix.py tests/integration/test_013_consolidation_lawful_merge.py tests/integration/test_013_consolidation_llm_faults.py tests/integration/test_013_consolidation_observation_matrix.py tests/integration/test_013_consolidation_operation_matrix.py tests/integration/test_013_consolidation_permanent_matrix.py tests/integration/test_013_consolidation_phase4_boundaries.py tests/integration/test_013_consolidation_recovery.py tests/integration/test_013_consolidation_remaining_matrix.py tests/integration/test_013_consolidation_replay_parity.py tests/integration/test_013_consolidation_windows.py -q --tb=short -p no:cacheprovider
```

Observed **943 passed in 1127.62s (18:47)**, exit 0, no skips. That run carried the
eight-case promotion file; the ninth case (audit-TTL purge and projection rebuild)
was added immediately after and `tests/integration/test_013_consolidation_promotion.py`
re-ran **9 passed in 87.39s**. Regression after the guard fix:
`tests/integration/test_012_live_maintenance.py tests/integration/test_012_memory_rest.py`
plus the Phase 6 candidates/management/promotion/migration files **42 passed in
181.19s**. No assertion was weakened.

What the Phase 6 evidence establishes:

- Candidate marking is an adjudicated attachment: only an active semantic
  distilled entry at or above the configured threshold whose every same-scope
  published corpus anchor re-verifies (position, content hash, source/version
  identity) is marked, `candidate_version` binds memory creation, approved
  content hash, anchor fingerprints and the approval decision, and a withdrawn or
  changed anchor leaves the marked candidate visible but not promotable. Marking
  changes no provenance/confidence and creates zero `KnowledgeSource` rows and
  zero promotion tasks.
- Only the explicit writer management request `POST /api/memories/promote`
  (with actor/reason/scope/candidate_version) creates the stable promotion task.
  Consolidation, maintenance (`run_memory_maintenance`, `resume_promotions`) and
  the volume/threshold hint paths created 0 automatic promotion sources in the
  acceptance run.
- Registration is shared with upload: sanitized markdown raw object, uploaded
  `KnowledgeSource`, exactly one pending `ProcessingRun(initial)`, permanent
  `promotion_requested` pointer with `task_id = request grant event_id` and the
  partial unique `(scope, memory, candidate_version)` index; upload keeps its 201
  response, size/hash/format fields, raw path convention, empty/oversized/
  unsupported-format errors, and the prebuilt run is consumed rather than
  duplicated (`IngestionService.ingest(processing_run_id=...)`).
- Duplicate and concurrent identical requests converge on the same
  task/source/initial run (`reused=true`, no second attempt); a crash between
  registration and scheduling is recovered by `resume_promotions`, which
  revalidates scope and candidate first, resumes only already human-authorized
  pointers, and records `failed` + `MEMORY_CANDIDATE_NOT_ELIGIBLE` without
  dispatching when the candidate is no longer eligible.
- Status only ever reflects actual facts: uploaded/processing/failed never report
  published; a real ingestion publishes and appends `promotion_observed` with the
  published version id; an explicit retry adds a new attempt run while the stable
  task and source stay identical and the original request pointer is never
  mutated; a memory rollback keeps the external publication history and never
  claims it was undone. Audit TTL purge (`purge_expired_observations`) deletes only
  expired run observations, and a full projection rebuild re-materialises the same
  `candidate_version`, anchor attributions and promotion pointer from the permanent
  log. No MCP promotion tool is registered.

Lint on the changed files: `phase3_lint_delta.py 42fddb1` reports
`{"new_findings": [], "preexisting_findings": 71}`.

Applied migration hashes (SHA256):
`0101_promotion_pointer` =
`68A9BDEC8849BD3434947791BA746516027F017E89540C0B78DD293EBB04301D`;
`0102_promotion_guard_identity` =
`14CFE0F713CD94DA80F0B5907690BC1FE980A15594CB7B2354A64FA5746D0D65`;
`0103_promotion_guard_skip` =
`9593E16A692A035F8F1DCD61D9C267BDBFA1BDB42ADDF85420725BD4818F082F`.
`0103`'s hash was taken after a cosmetic import-order fix (`phase3_lint_delta`);
its executed `upgrade()` body is unchanged from the applied one.

Pre-existing failure observed while regression-testing (not a Phase 6 defect; fixed
by the Phase 6 downgrade fix below):
`tests/integration/test_012_migration_roundtrip.py::test_retention_migration_empty_database_roundtrip`
downgrades a fresh database to `0088_memory_db_replay`, but `0096_consolidation_authority`
(committed with Phase 3, present at `42fddb1`) already raises unconditionally in
its `downgrade()`, so that path cannot succeed for any head at or above `0096`.
Phase 6 only changes which refusal message is reached first.

### Phase 6 downgrade fix (2026-10-07, T007 regression)

`0096`–`0103` had made `downgrade()` unconditionally refuse, which is stricter than
T007 ("no *destructive* downgrade **while** 013 authority is retained") and blocked
both the 012 roundtrip above and the Phase 8 "001–012 do not downgrade" acceptance.
Only `downgrade()` changed; every `upgrade()`, `revision` and `down_revision` stayed
byte-identical (8/8 `upgrade()` SHA256 unchanged, see the evidence note for hashes).

- New shared guard `backend/alembic/_consolidation_downgrade.py`
  (`assert_no_consolidation_authority(stage)`) is the first statement of each
  downgrade and refuses only while 013 authority survives: a v2
  `payload_version='2'` event, a `promotion_requested`/`promotion_observed` grant,
  a `consolidation_eligibilities`/`consolidation_runs` row, or a
  `memory_entries.promotion_pointer`/`candidate_version`. Probes use
  `to_regclass`/`pg_attribute`, so they are safe anywhere in the reverse chain.
  The module sits next to `versions/` on purpose: alembic 1.19.1 loads every
  `*.py` under `alembic/versions` as a revision script and aborts on one that does
  not declare `revision`/`down_revision`.
- `0103 → 0102 → 0101 → 0100 → 0099 → 0098 → 0097 → 0096` now really unwind:
  reversed `replace_function`/`.replace` fragments (machine-checked as the exact
  inverse of each frozen `upgrade()`), the promotion pointer projection branch, the
  propagation grant branch, the 0098 publication/canonical/hash guards, the
  restored `uq_memory_entries_scope_hash` constraint and the exact 0097
  `verify_consolidation_publication()` body, plus the matching trigger/function
  drops. `0095` was left untouched.
- Evidence (serial, no concurrent writer): `tests/integration/test_012_migration_roundtrip.py`
  **1 passed in 10.12s** (was 1 failed in 6.62s);
  `tests/integration/test_013_consolidation_migration.py` **2 passed in 11.44s**
  (including the refusal assertion); `alembic upgrade head` twice **exit 0** with
  current/head `0103_promotion_guard_skip`; a direct check refused the downgrade
  with `cannot downgrade consolidation authority at 0103_promotion_guard_skip:
  database still retains v2 consolidation events` while one v2 event was retained,
  and let the same downgrade reach `0094_memory_management_audit` once it was
  removed. Per-migration detail and full before/after hashes:
  `.superpowers/sdd/013-tasks/phase6-downgrade-fix.md`.

### Lead final verification of Phase 6 (2026-10-07)

Independently re-run by the Lead on the final bytes, serial, no concurrent
writer, isolated head `0103_promotion_guard_skip`:

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/unit/test_consolidation_candidates.py tests/contract/test_consolidation_management_api.py tests/integration/test_012_migration_roundtrip.py tests/integration/test_013_consolidation_migration.py -q --tb=short -p no:cacheprovider
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/integration/test_013_consolidation_promotion.py tests/unit/test_consolidation_adjudicator.py tests/unit/test_consolidation_links.py tests/unit/test_consolidation_policy.py tests/integration/test_013_consolidation_commit.py tests/integration/test_013_consolidation_live_boundaries.py tests/integration/test_013_consolidation_history_matrix.py tests/integration/test_013_consolidation_projection_rebuild.py tests/integration/test_013_consolidation_audit.py tests/contract/test_knowledge_sources_api.py -q --tb=short -p no:cacheprovider
```

Observed: **26 passed in 40.31s** (candidates, management-API contract, 012
migration roundtrip, 013 migration including the refusal assertion) and **308
passed in 353.62s** (Phase 6 promotion integration plus the 013/012 regression
slice), both exit 0, no skips. After these edits the file hashes of the eight
repaired migrations changed (only `downgrade()` bodies; `upgrade()` bytes
verified unchanged) — the applied `upgrade()` hashes above remain the authority
for what the isolated database actually ran.

## Phase 7 verification (2026-10-07, T077-T089)

Phase 7 wired the three triggers (manual/idle/volume), the bounded worker and
provider capacity, real request-activity tracking and the same-scope run reports.
0095-0103 stayed byte-frozen; one successor was applied to the isolated database:
`0104_runtime_activity_signals` (bounded cross-process request-activity signals;
`down_revision = 0103_promotion_guard_skip`, SHA256
`F19143FF951D79A73D97C6A3BFAB26CB0FD881CEE475A499EEDA025835CB70F4`). Isolated head
is now `0104_runtime_activity_signals`.

RED first (behaviour failures, not import/collection errors — all four files
collect 30 tests cleanly):

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/contract/test_consolidation_run_api.py -q --tb=line -p no:cacheprovider
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/integration/test_013_consolidation_triggers.py -q --tb=line -p no:cacheprovider
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/integration/test_013_consolidation_concurrency.py tests/integration/test_013_consolidation_foreground.py -q --tb=line -p no:cacheprovider
```

Observed: **6 failed in 6.93s** (4 × `{"detail":"Not Found"}` for the absent
consolidation routes, 1 × supervisor `NotImplementedError`, 1 ×
`TRUSTED_CONTEXT_REQUIRED` reached by an invalid trigger kind);
**10 failed in 4.61s** (T081 supervisor / T082 activity / T084 gate shells);
**11 failed, 3 passed in 23.05s** (the two provider-pool cases already passed:
the Phase 3/4 `DistillerProvider` capacity is pre-existing).

GREEN, per file:

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/contract/test_consolidation_run_api.py tests/integration/test_013_consolidation_triggers.py tests/integration/test_013_consolidation_concurrency.py tests/integration/test_013_consolidation_foreground.py tests/integration/test_013_consolidation_audit.py -q --tb=line -p no:cacheprovider
```

Observed (serial, no concurrent writer, run from the repository root; the runner
executes pytest with `cwd=<repo>/backend`):

- `tests/contract/test_consolidation_run_api.py` **6 passed in 36.72s**
- `tests/integration/test_013_consolidation_triggers.py` **10 passed in 205.14s**
- `tests/integration/test_013_consolidation_concurrency.py` **9 passed in 43.86s**
- `tests/integration/test_013_consolidation_foreground.py` **5 passed in 21.94s**
- `tests/integration/test_013_consolidation_audit.py` **10 passed in 81.01s**
- combined T088 acceptance batch (all five Phase 7 files, one serial run) **40 passed in
  401.51s (6:41)**, exit 0, no skips; final re-run on the final bytes after the
  lint cleanup, adding the server-mode unit file,
  `pytest tests/unit/test_server_mode.py tests/contract/test_consolidation_run_api.py
  tests/integration/test_013_consolidation_triggers.py
  tests/integration/test_013_consolidation_concurrency.py
  tests/integration/test_013_consolidation_foreground.py
  tests/integration/test_013_consolidation_audit.py` →
  **47 passed in 413.83s (6:53)**, exit 0, no skips

Regression on the same bytes (serial): `tests/unit` plus
`tests/contract/test_consolidation_management_api.py`,
`tests/contract/test_012_actual_tool_surface.py`,
`tests/integration/test_013_consolidation_promotion.py`,
`tests/integration/test_013_consolidation_windows.py`,
`tests/integration/test_013_consolidation_commit.py`,
`tests/integration/test_012_memory_e2e.py`,
`tests/integration/test_runtime_reader_independence.py` — **2075 passed, 3 failed
in 350.13s**. All three failures were re-run at the Phase 7 base commit
`2fc9610` in a detached worktree:
`tests/unit/orchestration/test_agentic_metrics.py::test_record_agentic_retrieval_run_writes_row`
and
`tests/contract/test_012_actual_tool_surface.py::test_generated_memory_schema_exposes_contract_inputs_only`
fail **identically at the base commit** (Phase 5 gaps: the T062 additive
`include_linked`/`include_context` flags were never reflected in the 012 schema
contract test, and the agentic-metrics unit case predates this phase). The third,
`tests/unit/test_server_mode.py::test_lifespan_runs_ttl_loop_after_lease`, was a
Phase 7 regression caused by the new writer-identity binding in `lifespan`; the
test doubles were updated to mirror the real callables
(`LeaseAcquisition.holder_instance_id`, `_ttl_cleanup_loop(..., *, supervisor=None,
owner=None)`) with no assertion changed, and the file re-ran **7 passed in 12.99s**.

What the Phase 7 evidence establishes:

- `POST /api/memories/consolidation` is a short admission: the 202 carries
  `run_id`/`request_id`/`trigger=manual`/`execution_context=distiller_window`/
  `status=admitted`/`window=null`, the admitted row is durable before the
  response, and no window selection or model call happens while the request is in
  flight (verified with a blocked `select_and_seal`). Disabled,
  configuration-required, same-scope busy (with the live `run_id`), contested
  scope-write lock and full capacity are distinct outcomes; bool/string scope,
  every unknown control field (`trigger`, `execution_context`,
  `propagation_trigger`, `proof`, `run_id`, `holder_instance_id`, `policy`,
  `proposals`, `actor`, `request_id`) reject with 422.
- Manual, idle and volume share one DB admission: losers get
  `CONSOLIDATION_BUSY` with the live run id, no second run row or queue entry is
  created, and at most two scope workers run at once with independent sessions
  (the third is refused and only succeeds after a slot is freed).
- Real provider capacity is separately bounded at two: a timed-out or cancelled
  waiter keeps its slot until the synchronous call actually returns, a third real
  call is refused boundedly (no executor backlog), and cancellation, worker
  faults, total-deadline expiry and lease loss all append an honest terminal
  observation, release exactly the matching eligibility and free the slot. A
  late old-generation result cannot commit, release or mask a newer generation
  (takeover allocates a new eligibility id and a larger version).
- Automatic admission requires *current* evidence: foreground/ingestion/rebuild
  activity (own process and fresh peers), a stale peer observation, an
  insufficient idle window, a disabled/unconfigured domain, a busy scope or a
  below-threshold volume hint each produce a reasoned skip with zero model,
  selection and commit work; a rejected hint is discarded and never replayed,
  while a later tick may independently observe the still-current pending work as
  an idle trigger. The volume hint is re-verified against the real eligible
  unconsumed episodic count, not raw projection rows (a +400-day clock with two
  raw rows reports `eligible: 0`).
- Request activity is constant-time and honest: only `/api/**` and `/mcp`
  dispatch counts (health, OpenAPI, SSE and static assets are passive), the count
  is released on success, error and cancellation, real MCP tool dispatch is
  instrumented in both writer and reader forms, and the reader surface exposes no
  consolidation/management control. Foreground search/recall/record/start_work
  keep their call path and budget while a consolidation run is blocked in the
  real provider thread, `MemoryDistiller.run` is never invoked from the
  foreground, and the activity count returns to zero.
- Promotion resumption now dispatches through the single activity-visible
  scheduling path (`rag_mcp.runtime.scheduling.schedule_ingestion`), counted from
  the moment the task is created and released in a `finally`; the maintenance
  tick also recovers missing real promotion outcomes (`recover_promotion_observations`,
  and once more during shutdown while the lease is still valid) so a completed
  attempt is never reported as merely `uploaded`.
- Reports are same-scope and honest: 404 without proof and for a foreign scope
  (no metadata leak), 410 only when a retained same-scope eligibility proves the
  run existed, one item per run in the list, append-only `history` ordered by
  sequence, and `counts` derived from the adjudication trail
  (`accepted ≠ committed`, accepted-but-pending never listed as output). Real
  end-to-end cases verify `succeeded`, `no_change`+`all_rejected`,
  `degraded`, `partial` (one independent group committed, one pending) and
  `failed` (rolled-back group publishes nothing) against the actual published
  authority prefix, with cache hits, actual transport and unknown token/cost
  kept separate.
- The 7-day audit TTL purge runs through the guarded live-maintenance role and
  audit log, deletes only expired observation rows (the report names that unit
  honestly as `purged_consolidation_observations`), keeps authority, published
  output, retained eligibility history and a still-explainable report, never
  releases active eligibility, and ordinary-role UPDATE/DELETE/TRUNCATE stay
  rejected.
- Trusted support maintenance still runs end-to-end while the ordinary switch is
  false: a real `support_maintenance`/`deterministic_propagation` wave with
  `window=null`, empty new inputs, nonempty historical lineage and a current
  proof, zero Distiller calls, and the same eligibility/lease/fence/capacity
  path; REST cannot fabricate the trigger.
- Defects found and recorded (no assertion weakened): `observe_result` now
  records the sanitized proposals it considered so `counts.proposed` matches the
  adjudication trail; test-double shapes in `tests/unit/test_server_mode.py` were
  aligned with the real callables; the remaining edits are test-side hygiene
  documented in `.superpowers/sdd/013-tasks/phase7-progress.md`.
- Known bounded caveat: one best-effort log line
  (`consolidation terminal release failed`) was observed once in an early run
  where a test failed while its worker was still mid-flight; it appears in **no**
  passing acceptance run (re-checked with a filtered re-run of the two largest
  Phase 7 files: **20 passed in 312.20s**, no such line). It never changes a run's
  public status, and every acceptance assertion on released eligibility passes;
  it is reported rather than hidden.

### Lead final verification of Phase 7 (2026-10-07)

Independently re-run by the Lead on the final bytes, serial, no concurrent
writer, isolated head `0104_runtime_activity_signals`:

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/contract/test_consolidation_run_api.py tests/integration/test_013_consolidation_triggers.py tests/integration/test_013_consolidation_concurrency.py tests/integration/test_013_consolidation_foreground.py tests/integration/test_013_consolidation_audit.py tests/unit/test_server_mode.py -q --tb=short -p no:cacheprovider
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/contract/test_012_actual_tool_surface.py tests/contract/test_consolidation_recall_extensions.py -q --tb=short -p no:cacheprovider
```

Observed: **47 passed in 407.34s** (T088 acceptance set: run API contract, three
triggers, concurrency, foreground, audit matrix, server mode) and **17 passed in
3.33s** after the Lead repaired the one legacy contract gap the phase reported:
`tests/contract/test_012_actual_tool_surface.py` still pinned `recall_memory`'s
exact 012 property set, so T062's additive `include_linked`/`include_context`
StrictBool flags made it fail. The Lead updated that 012 test to the
spec-sanctioned v2 shape (contracts/recall-extensions.md: the memory tool alone
gains two additive optional flags; the three historical knowledge tools stay
byte-compatible) and **strengthened** it: both flags must be optional, default
`false`, with `additionalProperties: false` still asserted. No other assertion was
weakened.

Remaining known pre-existing failure unrelated to 013:
`tests/unit/orchestration/test_agentic_metrics.py::test_record_agentic_retrieval_run_writes_row`
(expected `partial`, observed `complete`) — it failed identically at the Phase 4
head `ef51894` and at `2fc9610`; it is reported, not adjusted. The later Phase 8
continuation repaired that test's row-identity isolation (see below).

## Phase 8 verification (2026-10-07, T090–T104)

Release conclusion for this phase remains **incomplete**: no quality
(record→replay benefit) or deployment-gate result exists, T095's frozen dataset
and T097's six-way independent restoration runner were not produced, and
T102/T103 were therefore never executed. Both default switches stay `false` and
nothing was installed into a gate registry. Only the executed commands and their
real counters are recorded here; planning or Schema validation is never written
up as functional acceptance.

### Evidence indexes created by this phase (all new paths, nothing overwritten)

| Index | Path | Contents |
|---|---|---|
| T099 013 acceptance | `C:/Users/Richard/AppData/Local/Codex/013-isolation-20261006/phase8-evidence/t099-20261007/` | `consolidation-trace.json` (213430 B, 19 observed nodeids + real service calls), `authority-snapshot.json` (280279 B, 6 scopes), `dataset-manifest.json` (1957 B) |
| T099 qualification slice | `…/phase8-evidence/t099-qualification-20261007/` | promotion / dependencies / recovery / admission / windows / audit / migration / projection-rebuild run log; the 013 evidence fixture observed no records here (none of those files requests the fixture), so its exported manifest honestly carries empty scopes |
| T100 012 acceptance | `…/phase8-evidence/t100-012-20261007/` | `backend-pytest.xml` (147 cases), `memory-trace.json` (7.28 MB real invocation trace), `read-diagnostics.json`, `host-evidence.json`, `012-acceptance.json` |
| T101 retrieval regression | worktree `eval/runs/013-20261007-t101-retrieval/` | `012_regression_summary.json` + six group reports (`012_001`…`012_006`) and per-group runner logs |
| T101 unit/contract | `…/phase8-evidence/t101-20261007/unit-contract.log` | full `tests/unit tests/contract` run |
| T101 integration | `…/phase8-evidence/t101-20261007/integration/` | complete `tests/integration` run with JUnit + progress log |
| T101 domains | worktree `eval/runs/013-20261007-t101-domains/` | generic/legal baselines, legal benefit, multi-domain core report |

### T099 — 013 six-class E2E, AOEP≥2 per invariant, faults, qualification, dependency, promotion, non-empty rebuild

```powershell
$env:CONSOLIDATION_EVIDENCE_DIR = 'C:/Users/Richard/AppData/Local/Codex/013-isolation-20261006/phase8-evidence/t099-20261007'
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/integration/test_013_consolidation_e2e.py tests/integration/test_013_consolidation_aoep.py tests/integration/test_013_consolidation_llm_faults.py -q --tb=short -p no:cacheprovider
$env:CONSOLIDATION_EVIDENCE_DIR = 'C:/Users/Richard/AppData/Local/Codex/013-isolation-20261006/phase8-evidence/t099-qualification-20261007'
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/integration/test_013_consolidation_promotion.py tests/integration/test_013_consolidation_dependencies.py tests/integration/test_013_consolidation_recovery.py tests/integration/test_013_consolidation_admission.py tests/integration/test_013_consolidation_windows.py tests/integration/test_013_consolidation_audit.py tests/integration/test_013_consolidation_migration.py tests/integration/test_013_consolidation_projection_rebuild.py -q --tb=short -p no:cacheprovider
python .superpowers/sdd/013-tasks/phase8_validate_evidence.py <t099 evidence dir>
```

Observed: **74 passed in 161.19s** (six E2E classes: batch distillation, deterministic merge, support-withdrawal correction, soft-overturn-of-hard refusal, real provider/schema fault degradation, benefit-gate fail-closed, plus explicit human promotion; AOEP authority boundary / scope non-expansion / provenance preservation / deletion propagation / traceable rollback / non-empty rebuild each ≥2; fault and strict-cache suites) and **51 passed in 491.63s** (qualification, dependency, recovery, admission, window, audit, migration, projection-rebuild). Both exit 0, no skips. The exported manifest records the real observed hard counts (`cross_scope_leaks 0`, `soft_overturns_hard 0`, `automatic_promotions 0`, `invalid_outputs_applied 0`, `stale_holder_commits 0`, `incomplete_outputs_consumed 0`, `rebuild_llm_calls 0`, `source_chain_complete_rate 1.0`, `projection_integrity_rate 1.0`) and leaves `quarantined_inputs` / `schema_validity_rate` `null` because this run did not observe them; `phase8_validate_evidence.py` accepts the index and reports exactly those two unobserved checks. `null` is never rewritten as `0`.

### T100 — original 012 eight E2E and AOEP obligations with a new acceptance artifact

```powershell
$env:MEMORY_DIAGNOSTICS_OUTPUT = '<run>/read-diagnostics.json'
python .superpowers/sdd/013-tasks/isolation_runner.py pytest -vv --tb=short --durations=30 -p memory_pytest_evidence --memory-evidence=<run>/memory-trace.json --junitxml=<run>/backend-pytest.xml <27 012-scope integration/contract/unit files>
python .superpowers/sdd/013-tasks/isolation_runner.py eval eval/run_memory_acceptance.py --suite <run>/backend-pytest.xml --trace <run>/memory-trace.json --host <run>/host-evidence.json --diagnostics <run>/read-diagnostics.json --output <run>/012-acceptance.json --regression <six-group summary> <002> <004>
```

Observed: **143 passed, 4 failed, 0 skipped in 910.52s**, exit 1. The eight
original E2E gates and the AOEP obligation file are unchanged and pass. The four
failures are `test_012_regression_suite.py` (2 parametrizations) and
`test_011_multidomain_acceptance.py::test_schema_validity_100_percent`, which
read historical `eval/runs/012-20261005-final-regression-a/*` artifacts that are
not present in this worktree, plus
`test_012_distilled_chain.py::test_source_event_cannot_authorize_changed_projection_metadata`,
whose `pytest.raises(DBAPIError, match="immutable|source|facts")` no longer
matches the current guard text `completion publication requires current
verification receipt` (the guard still refuses the forged update). No assertion
was weakened to hide any of them. The resulting report is honestly **failed**:
SC-002/004/005/006/007/008/010/011/013/014/015/016/017 passed; SC-003 failed
(its `distilled_chain` evidence module has a failing case); SC-012 failed
(historical domain reports absent); SC-001/SC-009 `not_verified` because no real
DSH host tool call could be executed. `skip`/`missing` are never counted as pass.

### T101 — backend suite, 001–012 groups, target host, old frontend checks

```powershell
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/unit tests/contract -q --tb=short -p no:cacheprovider
python .superpowers/sdd/013-tasks/isolation_runner.py pytest tests/integration -vv --tb=line -p no:cacheprovider --junitxml=<run>/integration-pytest.xml
python .superpowers/sdd/013-tasks/isolation_runner.py eval eval/run_regression_011.py --output-dir eval/runs/013-20261007-t101-retrieval
```

Observed: `tests/unit tests/contract` **1 failed, 2389 passed in 217.79s**;
`tests/integration` **13 failed, 839 passed, 1 error in 3330.16s (55:30)**
(853 collected cases); `run_regression_011.py --output-dir` **all six groups
`all_passed=true`** (001 dense 11, 002 hybrid 18, 003 format 37, 004 graph 37,
005 agentic 63, 006 writer/reader smoke 11 each), exit 0, wall 650 s. The 011/012
domain groups re-ran clean: `ingest_domain_corpora.py`, `run_legal_benefit.py`,
both `run_domain_baseline.py` reports and `run_multi_domain_acceptance.py` all
exit 0 (wall 116 s).

The single unit/contract failure is an **environment line-ending artifact**, not
a 013 defect, and it is still present in the checked-out working tree:
`eval/agentic_eval_dataset.json` and `eval/cross_reference_eval_dataset.json`
are checked out CRLF by this worktree's `core.autocrlf=true`, while
`tests/contract/test_domain_eval_dataset_schema.py` pins their LF SHA256
(`eval_dataset.json` pins the CRLF form and passes). Verified by probing the
pinned hashes: the two files' LF SHA256 equal their pinned values and the JSON is
logically identical to `HEAD` (`git diff --numstat` empty). Rewriting those two
files with LF-only bytes and re-running that file gives **14 passed**, but a
later `git checkout`/`git reset` converts them back; the durable repo-level fix
is `git config core.autocrlf false` in this worktree (not applied here because it
is a cross-checkout policy choice for the Lead). The chunked backend evidence is
therefore reported as **2389 passed / 1 environment-bound failure**.

The 14 integration failures, each classified from its own JUnit output (nothing
weakened, nothing re-labelled):

- 2 × `test_012_regression_suite.py` read historical
  `eval/runs/012-20261005-final-regression-a/*` that does not exist here.
- 2 × `list_knowledge_domains` schema cases (`test_list_domains_mcp.py`,
  `test_011_multidomain_acceptance.py::test_schema_validity_100_percent`): the
  isolated store holds a scope whose `domain_key` starts with a digit
  (`013-4910367837a042bb8e23db1b84959612`), which violates the documented
  `DomainKey` pattern; this is stored data, not a 013 code path.
- 1 × `test_012_frontend_memory_page.py`: `frontend/dist/index.html` does not
  exist — the real frontend was not built (the test itself refuses to run
  without it).
- 3 × stale assertion regexes on current guard/error texts, including
  `test_012_distilled_chain.py::test_source_event_cannot_authorize_changed_projection_metadata`
  (`immutable|source|facts` vs the current `completion publication requires
  current verification receipt`); the guards still refuse the forged writes.
- 1 × `test_012_access_policy.py::test_rest_access_policy_is_immutable_and_rebuild_rollback_preserve_it`
  (projected entry map no longer matches the expected shape).
- 1 × `test_013_consolidation_triggers.py::test_automatic_admission_requires_fresh_quiet_activity`
  (plus its teardown error): infrastructure only — `OSError [WinError 121]
  信号灯超时时间已到` dropped the PostgreSQL connection during
  `SELECT clock_timestamp()`; the other cases in that file passed.
- 3 × `test_real_server_acceptance.py::TestScenario1/2/3`: they require the real
  MCP server at `127.0.0.1:8080`, which is not running.

Historical knowledge-tool compatibility:
(`tests/contract/test_012_actual_tool_surface.py`,
`tests/contract/test_012_old_tool_compat.py`, `tests/unit/test_memory_reader_budgets.py`)
ran **17 passed, 1 failed**; the single failure is
`test_012_old_tool_compat.py::test_actual_legacy_tool_schemas_and_response_bytes_survive_memory_registration[reader]`,
whose `list_knowledge_domains` response is compared for byte equality against a
second server built on the same evolving isolated store — the two catalogs differ
because the isolated database gained scopes between the two calls, and the three
tool *schemas* still compare equal (asserted before the response comparison). The
`test_agentic_metrics.py` row-identity isolation defect is repaired in the
working tree (**4 passed**) and included in the unit evidence.

Environment limits recorded rather than hidden:

1. A single `pytest tests/unit tests/contract tests/integration` run deadlocks in
   this environment around 10% (957 threads in the pytest process, one PostgreSQL
   connection `idle in transaction` with no blocker); every suite above was run in
   chunks, and the full integration chunk is retained with its own JUnit.
2. No writer/reader MCP service was listening on `127.0.0.1:18080/18081` and the
   existing DSH host presets still report initial synchronization failure, so
   `target-host` acceptance evidence was **not** obtained: the recorded host
   evidence is `not_verified` with the actual probe results, and SC-001/SC-009
   stay unverified. No substitute host was launched.
3. The old frontend checks (`pnpm build`, `pnpm exec playwright test`) require the
   frontend proxy/build toolchain against the isolated backend; they were not
   executed in this phase and are reported as not run, not as passed.

### T102–T104

T104 is the documentation/index update above plus the final re-check of the
closed-switch, no-direct-write and no-automatic-promotion invariants (the hard
counts exported by T099: `automatic_promotions 0`, `invalid_outputs_applied 0`,
`cross_scope_leaks 0`, `stale_holder_commits 0`, `incomplete_outputs_consumed 0`,
`rebuild_llm_calls 0`, plus the Phase 3 `rg`/AST/spy evidence and the promotion
acceptance in Phase 6). T102 (same-environment record→replay with the frozen ≥6
dataset) and T103 (gate-registry install simulation) were **not executed**: they
depend on T095's frozen real dataset, T097's independent six-way restoration
runner and real provider availability, none of which exist. Their honest status
is `incomplete`; the two default switches remain `false`. The step-by-step
commands, counters and limitation list for this phase are retained in
`.superpowers/sdd/013-tasks/phase8-progress.md`.


