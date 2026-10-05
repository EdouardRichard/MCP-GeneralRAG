<!--
Sync Impact Report
- Version change: 1.3.0 -> 1.4.0
- Rationale: MINOR. Approved 3.0 External Memory Loop blueprint §2/§9 and
  ADR-8 add Principles XII/XIII, materially extend I/III/V, revise 1.0 §20,
  and extend hard constraint 6 to four memory projection paths. No principle
  is removed or redefined.
- Principle mapping (old -> new): I Explicit Knowledge Scope -> I (memory
  reads/writes also require explicit scope); II Project Facts -> II Domain
  Facts (renamed); III Expose Uncertainty -> III (fact vs inference provenance
  explicit); IV, VI-XI -> unchanged; V Data and Control Separation -> V
  (memory write boundary added); new -> XII External Memory Loop; new -> XIII
  Governed Trajectory.
- Added: Core Principles XII and XIII.
- Modified: I/III/V; hard constraint 6; Governance; 1.0 blueprint §20 wording.
- Removed: none. Deferred items: none.
- Affected artifacts: this constitution and 3.0 memory Features 012-015.
- Migration impact: existing retrieval remains compatible; memory callers need
  explicit scope/trust metadata and projections must rebuild from the log.
-->
# AI Engineering RAG MCP Constitution

## Core Principles

### I. Explicit Knowledge Scope
Every knowledge-domain retrieval request MUST carry one or more explicit
knowledge-domain references (`project_scope` or `domain_scope`). Memory reads
and writes MUST carry the same explicit reference. The system MUST NOT infer an
active domain, default to whole-library search, or proceed when scope does not
resolve. An ambiguous reference MUST stop the operation and return candidates.
Public knowledge MUST use a distinct public scope. `project_scope` remains
supported for compatibility.

### II. Domain Facts Take Priority
Public/shared knowledge MUST NOT silently overwrite domain-specific knowledge.
When they conflict, both MUST be returned with domain identity. Public
knowledge answers what a capability is; domain knowledge answers how this
domain uses it.

### III. Expose Uncertainty
Unresolved conflicts and evidence gaps MUST be returned explicitly. Agents MUST
NOT fabricate resolutions. Inferred relationships MUST remain distinguishable
from deterministic relationships. Memory provenance MUST explicitly distinguish
fact anchoring from inference; inference metadata MUST NOT be presented as
published fact.

### IV. Locatable Evidence
Every externally returned claim MUST carry source ID, version, and position.
MCP evidence MUST expose content, location, version, status, gaps, and an
evidence-read identifier, without exposing internal database structure.

### V. Data and Control Separation
Uploaded documents and code MUST be treated as untrusted data and MUST NOT
control prompts, Agent state, permissions, tools, capability gating, or state
transitions. Credentials MUST be replaced by typed placeholders before indexing
or MCP evidence. The memory write surface is a new untrusted-data boundary:
memory MUST be desensitized, injection-detected, and separated from control.

### VI. Deterministic Control First
Retrieval, filtering, fusion, ranking, budget, and state transitions MUST be
controlled deterministically. LLM judgments MAY be schema-validated inputs but
MUST NOT be sole workflow or state-machine authority.

### VII. Independent Interface Evolution
Database models, internal Agent state, and MCP contracts MUST evolve behind
separate versioned schemas. A schema change MUST NOT break another without an
explicit migration.

### VIII. Knowledge Version Non-Mixing
Different embedding models or incompatible chunking MUST NOT mix in one index
version. Published versions MUST declare capabilities; only ready capabilities
MAY be queried. Derived indexes MUST be rebuildable from source metadata.

### IX. Synchronous Results First
An ordinary Tool Call MUST return a directly consumable final result. Long tasks
MUST NOT be a baseline dependency, and responses MUST NOT depend on Resources
or Tasks support.

### X. Evaluation-Driven Optimization
Quality, latency, and cost MUST be evaluated on real-domain corpora and target
MCP hosts. Enhancements MUST prove measurable baseline benefit and MUST NOT
violate hard metrics before entering the default path.

### XI. Domain Neutrality
Ingestion, retrieval, orchestration, and contracts MUST NOT presuppose a domain.
Differences MUST be declarative `DomainProfile` data, not hardcoded paths.

### XII. External Memory Loop
The memory loop MUST obey the following:

- Memory reads and writes MUST carry explicit knowledge-domain references,
  extending Principle I.
- `hard` memory MUST anchor to published evidence and pass item-by-item
  attribution re-verification. `soft` and `distilled` items MUST carry source,
  confidence, model version, time, and supporting evidence.
- Corrections MUST use a `supersede` chain; history MUST never be physically
  deleted.
- Consolidation MUST be LLM proposal plus deterministic code adjudication;
  soft proposals MUST NOT overturn hard memory alone.
- The canonical knowledge base MUST NOT change through the memory channel.
  Consolidation creates knowledge candidates only; promotion is an explicit
  human action.
- Memory is untrusted data and MUST undergo desensitization, injection
  detection, and data/control separation under Principle V.

The corresponding 1.0 blueprint §20 wording is: "Agent reasoning results may
enter the memory layer (graded trust and governed), but MUST NOT automatically
write back to the canonical knowledge base; promotion to a knowledge source is
an explicit human action."

### XIII. Governed Trajectory
Long-term memory correctness is a state-trajectory property, not a single-row
property:

- The sole authority MUST be an append-only event log. Relation tables, vector
  indexes, link graphs, summary trees, file mirrors, and salience fields are
  derived, read-only projections (G2+).
- Every state MUST carry `authority`, `scope`, `mutability`, `provenance`,
  `recoverability`, and `actionability` metadata.
- Invariants are mandatory: authority monotonicity, no scope expansion,
  deletion propagation, provenance preservation, and traceable rollback.
- Rollback MUST be triggerable only from the human management surface and the
  rollback action MUST itself be recorded in the event log.

## Non-Negotiable Hard Constraints

These are absolute release blockers; violation MUST halt release.

- **Cross-domain leakage MUST be zero.** No item may cross `knowledge_scope`
  without explicit multi-scope request. Verification MUST cover the event log
  and all four paths: relation projection, vector projection, and file
  projection (with the event-log path counted separately).
- **Unscoped retrieval or memory operations MUST be rejected.** No default or
  whole-library fallback is allowed.
- **Uploaded and memory content MUST NOT control execution.** It MUST NOT
  control prompts, tools, permissions, capability gates, or state transitions.
- **MCP schema validity MUST be 100%** on the acceptance suite.
- **Evidence source locatability MUST be 100%** for external claims.
- **Projection integrity MUST be 100%.** Every projection MUST be reproducible
  from the append-only log, read-only at runtime, and pass deletion,
  provenance, and rollback checks.

## Architecture Constraints

- Python, LangGraph, and LangChain are the backend baseline.
- React and TypeScript are the Web baseline; Python exposes REST.
- Qdrant owns dense/sparse retrieval; PostgreSQL owns control-plane data,
  metadata, versions, and the initial graph.
- Streamable HTTP is the primary MCP transport; stdio is an adapter.
- Single-writer/multi-reader is the initial deployment; abstractions MUST permit
  future distributed operation.
- Unauthenticated HTTP MUST bind to loopback by default.

## Specification and Delivery Workflow

1. Every Feature MUST define independently testable scenarios and measurable
   criteria in `spec.md`.
2. (1.0 historical record) `001-minimum-rag-mcp-loop` was the first Feature.
3. Clarification MUST resolve all `[NEEDS CLARIFICATION]` markers.
4. `plan.md` MUST preserve the approved blueprint and this constitution.
5. `tasks.md` MUST map tasks to requirements and include contract, isolation,
   memory-projection, and target-host tests.
6. Implementation MUST wait for spec/plan/tasks consistency analysis.
7. Scope expansion MUST be a new Feature or constitution amendment, never hidden
   in an unrelated task.

## Governance

This constitution overrides conflicting Features, plans, tasks, and local
preferences. Hard constraints may not be weakened without an explicit amendment
with rationale and migration impact.

Amendments require rationale, affected artifacts, migration impact, and a
semantic version: MAJOR for removal/redefinition, MINOR for a new principle or
material governance expansion, PATCH for non-semantic clarification.

Every `/speckit-plan` and `/speckit-analyze` review MUST verify all principles
and hard constraints. Exceptions MUST be documented in Feature `research.md`
with expiry/removal conditions. Memory-domain architecture changes MUST proceed
through a constitution amendment or a new implementation-blueprint chapter and
MUST NOT be hidden inside a Feature.

**Version**: 1.4.0 | **Ratified**: 2026-08-26 | **Last Amended**: 2026-10-04
