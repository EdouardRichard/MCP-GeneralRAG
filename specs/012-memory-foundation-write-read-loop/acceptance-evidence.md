# 012 Acceptance Evidence

Date: 2026-10-04

- DSH token endpoint: HTTP 200 from `http://127.0.0.1:3080/?token=...`.
- Database migration: `alembic upgrade head` completed; current/head `0080_memory_foundation`.
- Quickstart focused unit/contract/integration set: 30 passed.
- Phase 8 012 tests (E2E/AOEP/hard metrics/compat/frontend): 37 passed.
- Legacy compatibility subset after migration: 41 passed.
- Frontend `tsc -b` and `vite build`: passed.
- Full backend collection: 1925 tests collected.
- Full backend run remains open: legacy `test_011_corpus_ingest.py` and `test_011_multidomain_acceptance.py` enter long external model/ingestion flows without completing in the validation window. No pass claim is made for the full suite.

## Acceptance correction: 2026-10-05

The focused test counts above are historical execution results, not feature acceptance.
The quickstart, six projections, real evidence revalidation, management REST,
MCP contract signatures and frontend integration were not demonstrated by those
tests. T001-T087 completion claims are withdrawn pending task-level verification.
T088 remains open; passing historical retrieval does not close the missing memory work.

Stall root cause: a captured Python stack stopped in
`huggingface_hub.utils._detect_agent._fetch_registry` during model loading,
before embedding or Qdrant retrieval. These loading paths were unchanged by the
initial 012 commits. Real cached model snapshots now avoid the network probe.
Evaluation model-loading errors propagate; synthetic hash vectors are removed.

- Cached model TDD: 4 red, then 22 provider/reranker tests passed.
- Artifact safety TDD: 4 red, then 8 artifact/cache tests passed.
- New authority/trajectory tests: 11 failed, 1 passed before repair. Failures
  include live PostgreSQL UPDATE/DELETE acceptance, missing relation columns,
  absent live provenance validator, incomplete projections and wrong rollback.
- Full backend pytest and real historical eval reruns are in progress.
- New evaluation output: `eval/runs/012-20261005-regression/`; historical
  report paths are preserved by the rerun directory option.
