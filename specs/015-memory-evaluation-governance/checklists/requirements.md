# Specification Quality Checklist: 记忆评测治理与 3.0 定稿

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-09
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Items marked incomplete require spec updates before `$speckit-clarify` or `$speckit-plan`

### Validation log (2026-10-09)

Iteration 1 — all items pass. Evidence and judgment details for the two items
that need a convention note in this repository:

- **No implementation details**: the spec contains no code structure, class,
  module or query design. It does name contract-level identifiers that this
  repository's ratified 001–014 convention treats as externally observable
  outcomes (artifact path `memory_baseline_report.json`, the six tool names,
  `docs/1.0-iteration-roadmap.md`, `TRACE_BODY_ENABLED`, `spec.md` Status).
  Per constitution §Specification and Delivery Workflow and the 011/014 spec
  precedents, these identify *what must exist and be verifiable*, not *how it is
  built*; the report schema itself is deferred to plan (FR-022).
- **Success criteria are technology-agnostic**: SC-001…SC-027 are stated as
  counts, rates, zero-tolerance violations and coverage of scenarios. Latency is
  the only quantitative technology-neutral outcome (P50/P95, SC-023), matching
  the 001/002/011 methodology the user mandated.
- **Requirements traceability**: FR-001…FR-007 (poisoning), FR-008…FR-013
  (three-subset freeze discipline), FR-014…FR-020 (AOEP obligations),
  FR-021…FR-027 (baseline report), FR-028…FR-034 (hard-metric quintet),
  FR-035…FR-043 (governance UI), FR-044…FR-046 (statistics endpoint),
  FR-047…FR-050 (documentation debt), FR-051…FR-055 (3.0 finalization and full
  regression), FR-056 (five-invariant AOEP coverage per Constitution XIII),
  FR-057 (projection reproducibility and runtime read-only measurement),
  FR-058 (six-axis state-metadata completeness), FR-059 (regression group→test
  mapping), FR-060 (explicit host/cost evaluation scope decision).
  Every FR maps to at least one SC and to at least one user story; SC-025…SC-027
  cover the state-obligation, contract-enforcement and finalization-ledger
  obligations added by the 015 consistency analysis (2026-10-09).
- **No [NEEDS CLARIFICATION] markers**: the user input fixed the five hard
  constraints (eval-set immutability, non-overwritten baseline report, no
  unscoped global memory body view, poisoning + AOEP all-pass as finalization
  preconditions, management-plane-only audited rollback) and the deliverable
  list; remaining detail was resolved by informed defaults recorded in
  `## Assumptions` (notably: the iteration roadmap and architecture
  specification documents are absent from the workspace and are therefore
  re-established at their canonical paths, and the consolidation capability
  stays default-off without weakening any assertion).

### Validation log (2026-10-09, iteration 2 — `$speckit-analyze` remediation)

The consistency analysis found two CRITICAL constitution-alignment defects and a
set of enforcement gaps. Spec-side remediation applied in the same session:

- **Constitution XIII clause 3 (five mandatory invariants)** — FR-014 previously
  declared four invariant names and substituted `authority_boundary` for
  *authority monotonicity*, dropping *provenance preservation*; the closed
  enums in the AOEP dataset and report contracts made five-invariant coverage
  inexpressible. Remediation: FR-014 renamed `authority_boundary` →
  `authority_monotonicity`, re-added `provenance_preservation`, restored the
  five-invariant set aligned to Constitution XIII, raised the AOEP case floor
  from ≥8 to ≥10, and added **FR-056** to bind the dataset and report key sets
  to exactly five. The constitution was **not** diluted or reinterpreted.
- **Constitution XIII clause 2 (six-axis state metadata)** — the
  `authority`/`scope`/`mutability`/`provenance`/`recoverability`/
  `actionability` tuple appeared nowhere. Remediation: added **FR-058** with a
  non-zero-denominator measurement obligation.
- **Constitution XIII clause 1 / hard constraint 6 (projection integrity)** —
  rebuild was UI-verified with route stubs and had no rate or denominator.
  Remediation: added **FR-057** requiring real per-projection measurement
  (`examined ≥1`, `drift = 0`) and prohibiting stub substitution.
- **Constitution X (target MCP hosts, cost)** — neither was discharged.
  Remediation: added **FR-060**, an explicit honest-boundary scope decision
  recording both as out of scope with trigger conditions, plus the real-corpus
  caliber clarification. Recorded rather than claimed as achieved.
- **Constitution XII clause 1 / clause 6** — unscoped memory writes and
  desensitization were unobserved; FR-006's no-relaxation list silently omitted
  desensitization. Remediation: FR-006 now enumerates 脱敏, and the AOEP scope
  case set gains an unscoped-write case.
- **Contract enforcement gaps** (relocated to FR/SC so they are buildable):
  **FR-036** now requires an endpoint-level 422 test for scope-less browse,
  **FR-037** requires an explicit domain reference in strong confirmation,
  **FR-044** endpoint token unified to `GET /api/memories/stats` (the divergence
  from plan/contracts is resolved in favour of the existing `/api/memories`
  router prefix), **FR-055** clarifies that `3%` is goal-statement wording and
  not a new watermark, and SC-026/SC-027 make the zero-denominator guard and the
  seven-goal 1:1 ledger correspondence mandatory.
- **FR-059** requires an explicit regression group→test mapping so MUST-level
  clauses relocated into the 001–014 regression are enumerated rather than
  presumed.

Residual items intentionally left as recorded decisions, not silently dropped:
target-MCP-host and cost evaluation (FR-060), and the supersede/adjudication/
canonical-write clauses that 015 verifies only through the FR-054 regression of
012/013 deliverables.
