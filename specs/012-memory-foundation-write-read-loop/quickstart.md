# Quickstart: 012 记忆基座与写读回路

## Prerequisites

- Python 3.12+, project virtual environment and dependencies installed from `backend/pyproject.toml`.
- PostgreSQL and Qdrant running with `DATABASE_URL` and `QDRANT_URL` configured.
- `backend/` as working directory with `PYTHONPATH=src` (or editable install).
- A writer management process and a reader MCP process may run together; use distinct ports/worker identities.

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
```

The fixture writes a mixed event stream (assert, revise, retract, access, rollback), captures the online transaction projection, replays the same events through `projection_rebuild`, and compares normalized six-projection fingerprints. Snapshot+delta must match full replay. An invalid snapshot must recover from the complete immutable log; an incomplete log must refuse a complete recovery claim.

## 4. Validate Scope Isolation and Status Staleness

```powershell
pytest tests/integration/test_012_memory_isolation.py tests/integration/test_012_memory_status_staleness.py -q
```

The isolation test writes A/B scope entries and exercises ID, slug, `type:name`, absolute path and Git remote references. It expects zero four-path leakage and explicit missing/ambiguous errors. The staleness test leaves an active Qdrant payload after a PG retract/revise and proves status is post-filtered without a false negative.

## 5. Validate MCP Modes and Contracts

```powershell
pytest tests/unit/test_run_mcp_mode.py tests/unit/test_memory_mcp_registration.py tests/contract/test_memory_schemas.py -q
```

Inspect the generated FastMCP tool list: writer has six tools (`search_knowledge`, `get_evidence`, `list_knowledge_domains`, `record_memory`, `recall_memory`, `start_work`); reader has five read-only tools and no `record_memory`. Existing three-tool schema snapshots must remain byte-identical.

## 6. Run Eight E2E and AOEP Obligations

```powershell
pytest tests/integration/test_012_memory_e2e.py tests/integration/test_012_aoep_obligations.py -q
```

Expected gates: hard anchor round trip; no-anchor rejection; cross-scope zero leakage; supersede chain; injection quarantine; TTL/quota fail-loud; reader no-write; session timeline; plus rollback traceability, deletion propagation, authority boundary and no scope expansion.

## 7. Frontend Validation

```powershell
cd ../frontend
pnpm build
```

Open the management UI and visit the memory browser route. It must show scope, kind, provenance, status, valid interval, evidence links, injection flags and projection/rebuild status without exposing raw credentials or offering MCP rollback.

## 8. Full Regression

```powershell
cd ../backend
pytest -q
```

Run the existing 001–011 evaluation commands from `eval/README.md` without overwriting historical reports. The 012 report must include request IDs, projection fingerprints, four-path isolation counts, schema validity, provenance completeness, hard-anchor rate and quarantined leakage count.

Qdrant dense revisions use the `012_v2` model-versioned collection with explicit scope and revision filters. Historical `012_v1` collections remain readable until a logged rebuild produces the new completed manifest. On the Qdrant host, provision `vm.max_map_count=262144`; no historical collections or event logs are deleted during migration.
