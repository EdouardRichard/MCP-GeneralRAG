# 012 Task Verification

This ledger supplements tasks.md. A test filename alone is not acceptance:
the live tests listed here assert persisted state, rejected mutations, real
provenance, actual six-projection contents, and actual MCP calls.

Evidence at this checkpoint:

- Full suite d: `eval/runs/012-20261005-final-regression-d/backend-pytest.xml`,
  2107 passed, one old host test skipped, no failures. This is intermediate evidence.
- Scope supplement: 20 passed (`ebbfa5a`, `90af2ab`).
- Error registry, report and actual compatibility supplement: 26 passed
  (`8f8b296`, `7158ddb`), following three expected red failures.
- Host repair: five passed in `final-regression-d/target-host-green.xml`,
  following unreachable/skip and wrong fixture-mode failures (`a211f21`).
- Replay authority supplement: 35 passed, following two red roundtrip
  failures (`4e25753`, `45bb5a2`). Same-transaction reuse still checks the
  latest event under the scope lock; different savepoints revalidate the log.
- Read diagnostics d: `final-regression-d/read-diagnostics.json`.
- Full suite e: 2133 passed, three failed, zero skipped. Two old Agentic
  Recall@K failures used identical constant dense vectors; the old management
  lifespan failure reused a global asyncpg pool across closed test loops.
  These results are not final acceptance.
- Fixture repair (`8755ecf`, `6ca55a6`): constant-vector red assertion and
  real PostgreSQL cross-loop red reproduction, then 17 tests passed in a
  serial run (`final-regression-e/legacy-fixture-green-serial.xml`). Real BGE
  vectors/reranking retain the original Recall@K and expected-source checks.
- Full suite f is running with actual memory observations and read diagnostics.

Test locations below use U = `backend/tests/unit/`,
C = `backend/tests/contract/`, I = `backend/tests/integration/`.
Each test module has the `test_` prefix and `.py` extension.

| Task | Verification and implementation evidence |
| --- | --- |
| T001 | U/migration_012_memory; I/012_live_authority; real schema columns and indexes. |
| T002 | U/memory_event_constraints; I/012_live_authority; actual PG UPDATE and DELETE rejection. |
| T003 | U/memory_policy_defaults; I/012_live_authority; all four actual seeded policies. |
| T004 | U/memory_projection_equivalence, memory_trajectory_authority; I/012_aoep_obligations; five separate invariant groups. |
| T005 | migrations 0080-0089; I/012_migration_roundtrip and 012_live_authority. |
| T006 | models/memory_event.py; event constraints and actual append-only PG tests. |
| T007 | models/memory_projection.py; real persisted supersede chain and relation-column checks. |
| T008 | models scope_binding/session/memory_salience/memory_recall_run; live session, salience and runtime TTL tests. |
| T009 | domain_profile memory_policy; four identical seeded defaults, custom policy audited through REST. |
| T010 | models package metadata discovery; migration helper and actual schema parity tests. |
| T011 | U/memory_projection_equivalence and memory_trajectory_authority; mixed event reducer fingerprints. |
| T012 | U/migrations_helper; I/012_migration_roundtrip, 012_live_authority; empty DB upgrade/downgrade. |
| T013 | U/memory_transaction; I/012_memory_e2e relation failure rolls back event and all visibility. |
| T014 | U/memory_read_only; I/012_write_metadata_boundary, 012_replay_roundtrips; forged and stale reducer rejection. |
| T015 | I/012_persisted_write_loop, 012_aoep_obligations, 012_projection_corruption; actual six views, transitions, deletion and rollback. |
| T016 | I/012_persisted_write_loop fault matrix, 012_memory_failure_visibility, 012_memory_e2e; failed revisions hidden until replay recovery. |
| T017 | memory_event_store append/replay; raw event/provenance rejection and immutable PG log tests. |
| T018 | memory_projection_store; exact log authority, transaction and six actual projection parity tests. |
| T019 | memory_service record savepoint/commit; relation rollback and six external-path failure/recovery tests. |
| T020 | memory_reducer; same reducer online/replay, preserved provenance, valid intervals and rollback history. |
| T021 | I/012_provenance_no_bypass AST inventory; 012_database_projection_authority real role privileges and rejected GUC forgery. |
| T022 | Full suite d plus 35 current authority tests; fault matrix, restricted roles and fail-closed recovery. |
| T023 | U/scope_binding_service; real Windows junction, path boundary, priority and equivalent Git remotes. |
| T024 | U/scope_binding_service; ambiguity candidates, disabled binding, relative/malformed refs rejected. |
| T025 | I/012_binding_escalation, 012_live_governance; C/012_actual_tool_surface; MCP cannot expose binding write tools. |
| T026 | I/012_hard_metrics four actual paths; 012_memory_e2e explicit A/B union excludes C. |
| T027 | scope_binding_service normalizers; malformed IPv6/ports return scope errors, longest-prefix resolution. |
| T028 | scope_resolver; I/012_live_scope_resolution and C/memory_scope_contract; no missing/ambiguous fallback. |
| T029 | api/memory binding routes; I/012_memory_rest lease denial and 012_live_governance event-derived binding. |
| T030 | scope_resolver in tools/readers; I/012_hard_metrics scope equality in event/relation/vector/file. |
| T031 | C/memory_scope_contract; 20 scope supplement tests and actual four-path union tests. |
| T032 | U/memory_validators, memory_validation_boundary; I/012_live_authority, 012_distilled_chain; real attribution and rejected caller published claims. |
| T033 | U/memory_redaction_injection, memory_validation_boundary; I/012_write_metadata_boundary and 012_hard_metrics raw credential assertions. |
| T034 | U/memory_supersede; I/012_persisted_write_loop and 012_reader_boundaries; same-scope active target and closed valid interval. |
| T035 | U/memory_quota_ttl; I/012_memory_e2e and 012_live_maintenance; quota refusal and distinct kind TTLs. |
| T036 | I/012_record_memory; 012_persisted_write_loop, 012_memory_e2e, 012_hard_metrics supplement full rejection/quarantine matrix. |
| T037 | memory_validators; live published source/version/position/content-hash revalidation and recursive distilled chain. |
| T038 | memory_service; I/012_provenance_no_bypass proves provenance refusal precedes injection and insertion. |
| T039 | credential redactor and injection detector; actual event/metadata/relation/vector/file redaction and quarantine exclusion. |
| T040 | validate_supersede and reducer; live two-identity success boundary, soft cannot replace hard. |
| T041 | normalized submission metadata and scoped transaction lock; I/012_memory_e2e concurrent equality, conflicts and nonactive duplicate behavior. |
| T042 | memory_service session registration and recall audit; live session timeline, timeout audit and seven-day runtime TTL. |
| T043 | I/012_provenance_no_bypass AST inventory and validation order; 012_distilled_chain and hard-metric actual attributions. |
| T044 | Full suite d; write boundary, faults, deduplication, safety and trajectory cases passed together. |
| T045 | U/salience_service; explicit forced-decay gate, zero cold start, linear beta/gamma tests. |
| T046 | U/rrf_memory and historical fusion tests; weights and deterministic tie-breaking. |
| T047 | I/012_live_reader and 012_reader_boundaries; actual by_id/timeline/filtered/semantic behavior and as_of matrix. |
| T048 | I/012_read_diagnostics; real stale Qdrant status counterexample then logged rebuild restores payload. |
| T049 | I/012_memory_recall_observability, 012_live_reader, 012_read_diagnostics; actual timeout cleanup, audit, four states and bounded excerpts. |
| T050 | salience_service and event reducer; usage only changes salience, facts/trust/time/supersede stay unchanged. |
| T051 | fusion/rrf.py; optional memory weights and unchanged dense/sparse/graph compatibility suite. |
| T052 | indexing/memory_vectors and qdrant client; I/012_dense_revision_layout; model-version collection with scope/revision filters. |
| T053 | memory_reader; real PG-only modes avoid vector-client construction; dense results intersect structural scope filters. |
| T054 | I/012_live_reader, 012_reader_boundaries; valid/observed separation, delivered and superseded permission tests. |
| T055 | memory_reader clipping and audit; timeout/partial/missing evidence and public failed-path observations. |
| T056 | read-diagnostics.json; decay feedback arms, stale-status false-negative count, actual recall/work budgets and timing. |
| T057 | C/memory_schemas, memory_error_registry, 012_actual_tool_surface; schemas and actual response validation. |
| T058 | U/memory_mcp_annotations plus C/012_actual_tool_surface; actual FastMCP annotations, strict inputs and closed schemas. |
| T059 | U/memory_mcp_registration and C/012_actual_tool_surface; writer six/reader five tools. |
| T060 | C/012_old_tool_compat fixed-request byte/schema comparison; memory_error_registry preserves old codes. |
| T061 | mcp/record_memory; I/012_live_mcp_tools actual persisted calls and live-management ownership refusal. |
| T062 | mcp/recall_memory; real MCP call structuredContent/JSON equality and scope/error envelopes. |
| T063 | mcp/start_work and memory_reader; real three-budget, stable byte/fingerprint, guidance and refreshed lifecycle packages. |
| T064 | mcp registration and _run_mcp mode; actual writer/reader tool lists and old-tool compatibility. |
| T065 | serialization memory_result; one structured body/JSON mirror, volatile request/timing outside stable package. |
| T066 | errors.py and contracts/error-codes.json; historical contract enums preserved and content-conflict included. |
| T067 | Actual generated contracts and fixed-request legacy byte suite; 26 supplement tests passed. |

Phase 7 and Phase 8 remain open at this checkpoint. Final suite, fresh historical
evaluation reports, real DSH `temp` sessions and schema-validated report are
required before T088 may be marked complete.
