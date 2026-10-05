# Quickstart: 012 记忆基座与写读回路

## Prerequisites

- Python 3.12+ and dependencies installed from `backend/pyproject.toml`.
- PostgreSQL and Qdrant running with `DATABASE_URL` and `QDRANT_URL` configured.
- `backend/` as working directory with `PYTHONPATH=src` (or editable install).
- A writer management process and a reader MCP process may run together; use distinct ports/worker identities.
- Clear proxy variables for loopback and database acceptance. Configure the real
  providers in `.env` and retain the cached model snapshots in `.models`.
- Run database-writing suites serially. Stop acceptance services before running
  lease/registry tests, and finish each test process before starting another.

## 1. Apply Schema

```powershell
cd backend
alembic upgrade head
```

Verify the new migration creates `memory_events`, `memory_entries`, `scope_bindings`, `sessions`, `memory_salience`, `memory_recall_runs`, snapshot metadata and the `domain_profiles.memory_policy` column. Check indexes and that no event update/delete repository path exists.

## 2. Run Focused Tests

```powershell
python -m pytest tests/unit/test_memory_validators.py tests/unit/test_scope_binding_service.py tests/unit/test_salience_service.py tests/unit/test_projection_rebuild.py -q
python -m pytest tests/contract/test_memory_schemas.py tests/unit/test_memory_mcp_annotations.py -q
```

These tests cover pure validators, nine-step ordering, longest-prefix resolution, salience decay, schema validity, error-code stability and writer/reader tool annotations.

## 3. Validate Event/Projection Equivalence

```powershell
pytest tests/integration/test_012_memory_projection_equivalence.py -q
pytest tests/integration/test_012_live_authority.py tests/integration/test_012_database_projection_authority.py tests/integration/test_012_projection_corruption.py -q
```

The fixture writes a mixed event stream (assert, revise, retract, access, rollback), captures the online transaction projection, replays the same events through `projection_rebuild`, and compares normalized six-projection fingerprints. Snapshot+delta must match full replay. An invalid snapshot must recover from the complete immutable log; an incomplete log must refuse a complete recovery claim.

## 4. Validate Scope Isolation and Status Staleness

```powershell
pytest tests/integration/test_012_memory_isolation.py tests/integration/test_012_memory_status_staleness.py -q
pytest tests/integration/test_012_hard_metrics.py tests/integration/test_012_live_scope_resolution.py tests/integration/test_012_read_diagnostics.py -q
pytest tests/unit/test_scope_binding_service.py tests/unit/test_scope_remote_boundary.py tests/contract/test_memory_scope_contract.py -q
```

The hard-metric and scope-resolution suites exercise persisted A/B/C scopes,
explicit unions, ID/slug/`type:name`/path/remote resolution, four-path isolation
and missing/ambiguous errors. Read diagnostics measure the real stale-status
counterexample, PG post-filtering, four read modes, three work budgets and decay.

## 5. Validate MCP Modes and Contracts

```powershell
pytest tests/unit/test_run_mcp_mode.py tests/unit/test_memory_mcp_registration.py tests/contract/test_memory_schemas.py -q
```

Inspect the generated FastMCP tool list: writer has six tools (`search_knowledge`, `get_evidence`, `list_knowledge_domains`, `record_memory`, `recall_memory`, `start_work`); reader has five read-only tools and no `record_memory`. Existing three-tool schema snapshots must remain byte-identical.

After database-writing suites finish, start these processes in separate terminals:

```powershell
# From backend/, with PYTHONPATH=src and distinct automatically assigned workers.
python -m uvicorn rag_mcp.server:app --host 127.0.0.1 --port 18000
python _run_mcp.py --mode writer --port 18080
python _run_mcp.py --mode reader --port 18081
```

The management process must hold a live writer lease before `record_memory`.
Use `eval/dsh-012-presets.patch.yml` for independent DSH writer/reader presets.
In the existing `temp` workspace, confirm the actual logged request headers
contain six writer tools and five reader tools. Run the published evidence
read/write/read/start-work loop and retain the new session logs and screenshots.
A reader write request must be rejected because its catalog has no write tool;
record that host rejection and the unchanged authority-event count explicitly.
Do not describe this as a dispatched MCP call when no tool was dispatched.

## 6. Run Eight E2E and AOEP Obligations

```powershell
pytest tests/integration/test_012_memory_e2e.py tests/integration/test_012_aoep_obligations.py -q
```

Expected gates: hard anchor round trip; no-anchor rejection; cross-scope zero leakage; supersede chain; injection quarantine; TTL/quota fail-loud; reader no-write; session timeline; plus rollback traceability, deletion propagation, authority boundary and no scope expansion.

## 7. Frontend Validation

```powershell
cd ../frontend
pnpm build
pnpm exec playwright test
```

Open the management UI and visit the memory browser route. It must show scope, kind, provenance, status, valid interval, evidence links, injection flags and projection/rebuild status without exposing raw credentials or offering MCP rollback.

## 8. Full Regression

```powershell
cd ../backend
python -m pytest -vv --tb=short --durations=30 -p memory_pytest_evidence --memory-evidence=../eval/runs/NEW-RUN/memory-trace.json --junitxml=../eval/runs/NEW-RUN/backend-pytest.xml
```

Run the existing 001–011 evaluation commands from `eval/README.md` without overwriting historical reports. The 012 report must include request IDs, projection fingerprints, four-path isolation counts, schema validity, provenance completeness, hard-anchor rate and quarantined leakage count.

Set `PYTHONPATH=src;../eval` and `MEMORY_DIAGNOSTICS_OUTPUT` to the new run's
`read-diagnostics.json` before pytest. Create a fresh `NEW-RUN` directory first.
Use `run_regression_011.py --output-dir` for new six-group retrieval reports,
then repeat generic/legal baselines and the multi-domain core acceptance in that
directory. Compare non-latency metrics against retained historical reports.
The core runner does not establish DSH acceptance. Generate the final report
with `eval/run_memory_acceptance.py` using the completed JUnit, invocation trace,
read diagnostics, actual DSH evidence and new regression reports.

Qdrant dense revisions use the `012_v2` model-versioned collection with explicit scope and revision filters. Historical `012_v1` collections remain readable until a logged rebuild produces the new completed manifest. On the Qdrant host, provision `vm.max_map_count=262144`; no historical collections or event logs are deleted during migration.
