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

## 8. 只读闸口登记与撤销（实施后）

按 [gate-proof.md](contracts/gate-proof.md) 在评测前冻结拟部署的完整enabled目标policy与当前gate_binding；baseline/direct/expansion只改隔离runner路径选择。一个013.2报告覆盖一个scope的六查询。首轮/重放的gate_binding及环境字段须一致；当前data_hash含普通源authority和published证据，013内部效果/rebuild不自使其失效，snapshot_hash仍是完整评测输入。

仅在T103隔离目录验收：真实candidate_expansion报告passed且当前绑定匹配时，审阅真实三闸/record-replay证据，将报告放入DATA_ROOT之外的部署者控制目录，按gate-registry.schema.json建立scope唯一entry，固定report_path/精确SHA256/gate_binding/expires_at，并原子安装登记。部署者在writer/reader启动环境显式设置CONSOLIDATION_GATE_REGISTRY_PATH为登记绝对路径，服务只读；缺省None仍无证明。runner不自动登记或修改policy，未经过真实闸口的fixture不得安装为生产证明。

真实failed/incomplete或仅direct过闸时，不安装扩展许可；验收拒绝授权、合法直接召回与默认关闭，保留报告结论。T055显式fixture仍验证loader正向逻辑，不能替代真实通过报告。拟部署policy必须已沿合法管理流程发布并进入冻结authority快照；随后再发policy grant或改变源材料须重新核验/重评，不改旧报告binding凑匹配。

验证include_linked=true在域许可+当前合法证明下增强；direct-only报告、缺配置/登记、错scope/绑定、坏hash、同mtime篡改、过期/删除登记/换policy或源证据均下一请求not_available/disabled并保留原合法直接候选。记录新增IO≤100ms计入原3秒预算、无网络/模型/生产写入、旧flags=false不读取文件。撤销由部署者原子删entry或登记文件完成，不保留缓存授权；无需清理记忆或改变派生投影。
