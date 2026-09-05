<!--
Sync Impact Report
- Version change: 1.2.0 -> 1.3.0
- Rationale: MINOR. Domain-generalization amendment per the approved 2.0
  evolution blueprint (docs/通用RAG演进蓝图.md §3.1/§3.2/ADR-7): the scope
  subject is generalized from project-knowledge retrieval to knowledge-domain
  retrieval, and one new principle (XI Domain Neutrality) is added. No
  obligation was removed or weakened; `project_scope` remains a supported
  compatible reference form and all 1.0 acceptance semantics carry over, so
  the bump is MINOR, not MAJOR.
- Principle mapping (old -> new):
    I.  Explicit Knowledge Scope            -> I.   Explicit Knowledge Scope (domain-generalized:
                                                 project-knowledge retrieval -> knowledge-domain
                                                 retrieval; explicit reference = project_scope OR
                                                 domain_scope; project_scope kept as legacy form)
    II. Project Facts Take Priority         -> II.  Domain Facts Take Priority (renamed, domain-neutral
                                                 wording; same non-overwrite + dual-return + identity
                                                 obligations)
    III.Expose Uncertainty                   -> unchanged
    IV. Locatable Evidence                   -> unchanged
    V.  Data and Control Separation          -> unchanged
    VI. Deterministic Control First          -> unchanged
    VII.Independent Interface Evolution      -> unchanged
    VIII.Knowledge Version Non-Mixing        -> unchanged
    IX. Synchronous Results First            -> unchanged
    X.  Evaluation-Driven Optimization       -> X.   Evaluation-Driven Optimization (expanded: real-project
                                                 corpora -> real-domain corpora incl. software-engineering
                                                 and general domains)
    (new)                                    -> XI.  Domain Neutrality (no hardcoded domain assumptions;
                                                 domain differences expressed via DomainProfile
                                                 declarations)
- Added sections: Core Principle XI
- Modified sections: Core Principles I, II, X; Non-Negotiable Hard Constraints
  (constraints 1-2 domain-neutralized: "cross-project leakage" -> "cross-domain
  leakage", "explicit project_scope" -> "explicit knowledge-domain reference
  (project_scope or domain_scope)"); Specification and Delivery Workflow item 2
  marked as a 1.0 historical record
- Removed sections: none
- Affected artifacts: .specify/memory/constitution.md (this file); downstream
  consumers are the upcoming Features 007-011 specs/plans/tasks, which will be
  verified against v1.3.0 by /speckit-plan and /speckit-analyze; delivered
  Features 001-006 artifacts remain governed by their ratification-time
  version and require no retrofit
- Migration impact: none for existing code, data, or MCP clients — v1.3.0 only
  widens the scope-reference surface (adds the optional domain_scope form);
  project_scope behavior, legacy error codes, and every hard-constraint
  verification ritual are unchanged for legacy-only callers
- Deferred items: none
-->
# AI Engineering RAG MCP Constitution

## Core Principles

### I. Explicit Knowledge Scope
Every knowledge-domain retrieval request MUST carry one or more explicit
knowledge-domain references (in `project_scope` or `domain_scope` form;
either form suffices). The system MUST NOT infer an implicit active domain,
MUST NOT default to whole-library search, and MUST refuse retrieval when no
scope reference resolves. A reference that cannot be resolved to a unique
knowledge scope MUST stop retrieval and return candidate scopes. Public
knowledge MUST use a distinct public scope and MUST NOT masquerade as a
project. The legacy `project_scope` parameter remains a supported compatible
reference form.

### II. Domain Facts Take Priority
Public/shared knowledge MUST NOT silently overwrite domain-specific knowledge.
When public and domain-specific evidence conflict, the system MUST return both
concurrently, each retaining its domain identity. Public knowledge participates
only when a query involves a relevant public capability; domain-specific
knowledge answers how this domain uses that capability, and public knowledge
answers what that capability is.

### III. Expose Uncertainty
Conflicts that cannot be adjudicated and evidence gaps MUST be returned to the
caller explicitly. Internal Agents MUST NOT fabricate a resolution or fill a gap
by inference. Inferred graph relationships MUST remain distinguishable from
deterministic relationships.

### IV. Locatable Evidence
Every externally returned claim MUST be backed by source-locatable evidence
carrying a source ID, version, and position. Evidence returned through MCP MUST
expose content, source location, version, status, gaps, and an evidence read
identifier, and MUST NOT expose internal database structure.

### V. Data and Control Separation
Uploaded documents and code MUST be treated as untrusted data. Untrusted
content MUST NOT directly control prompts, Agent state, permissions, tool
selection, capability gating, or state-machine transitions. Credential values
MUST be replaced with typed placeholders before entering retrieval indexes or
MCP evidence, while field names, structure, authentication method, and source
locations remain available for retrieval.

### VI. Deterministic Control First
Retrieval, filtering, fusion, ranking, budget, and state transitions MUST be
controlled by deterministic components. LLM Agents MAY provide schema-validated
judgments but MUST NOT own workflow control. An LLM judgment MUST NOT be the
sole authority over a state-machine transition.

### VII. Independent Interface Evolution
Database models, internal Agent state, and the externally-facing MCP contract
MUST evolve behind separate versioned schemas. A change to one schema MUST NOT
impose a breaking change on another without an explicit migration.

### VIII. Knowledge Version Non-Mixing
Data produced by different embedding models or incompatible chunking strategies
MUST NOT be mixed into the same index version. Each published knowledge version
MUST declare its available index capabilities, and only capabilities marked
ready MAY be queried. All derived indexes MUST be rebuildable from the source
object and version metadata.

### IX. Synchronous Results First
A single ordinary Tool Call from a target client MUST return a directly
consumable final result. Long-running task extensions MUST NOT be a baseline
dependency for the core retrieval path. A Tool response MUST contain directly
usable core evidence and MUST NOT depend on Resources or Tasks support.

### X. Evaluation-Driven Optimization
Retrieval quality, latency, and cost MUST be determined by evaluation on
real-domain corpora (software-engineering and general knowledge domains alike)
and target MCP hosts, not by theoretical assumption. Enhancements (lexical,
rerank, graph, and Agent orchestration) MUST prove measurable benefit against a
fixed baseline AND MUST NOT violate any hard acceptance metric before entering
the default retrieval path.

### XI. Domain Neutrality
Ingestion, retrieval, orchestration, and externally-facing contracts MUST NOT
presuppose a specific knowledge domain. Domain differences — supported formats,
chunk-type vocabularies, graph relation vocabularies, planner prompt content,
and default capabilities — MUST be expressed declaratively through domain
profiles (DomainProfile) and MUST NOT be hardcoded in code paths. The
software-engineering domain is the first built-in domain profile, not a default
assumption of the system.

## Non-Negotiable Hard Constraints

These invariants are absolute and non-violable. Derived from the blueprint
acceptance criteria (Chapter 24.2) and the scope/data principles, each is a
release blocker; violation by any feature, task, or implementation MUST halt
release until corrected.

- **Cross-domain leakage MUST be zero.** No retrieval result, evidence item,
  graph relationship, or chunk from one `knowledge_scope` may surface in
  another domain's retrieval unless an explicit multi-scope request
  (`project_scope` or `domain_scope`) included that scope. *Verification:
  the count of cross-domain leakage events in the acceptance suite MUST equal
  zero.*
- **Retrieval without an explicit knowledge-domain reference MUST be
  rejected.** A knowledge retrieval request carrying no explicit scope
  reference (neither `project_scope` nor `domain_scope`) MUST be refused; it
  MUST NOT fall back to any default or whole-library search. *Verification: a
  request with no scope reference returns a rejection, never results.*
- **Uploaded content MUST NOT act as a control instruction.** Uploaded
  documents and code are untrusted data only; they MUST NOT control prompts,
  tool selection, permissions, capability gating, or state transitions.
  *Verification: a malicious upload cannot alter control flow, tool
  availability, or prompt scaffolding.*
- **MCP schema validity MUST be 100% on the acceptance suite.** Every Tool
  response in the acceptance test set MUST validate against its declared MCP
  schema. *Verification: the schema-validity rate over the suite MUST equal
  100%.*
- **Evidence source locatability MUST be 100% on the acceptance suite.**
  Every externally returned claim in the acceptance test set MUST carry a
  source ID, version, and position resolvable to the originating knowledge
  source. *Verification: the source-locatability rate over the suite MUST
  equal 100%.*

## Architecture Constraints

- Python, LangGraph, and LangChain form the backend orchestration baseline.
- React and TypeScript form the Web management baseline; Python exposes the REST
  management API.
- Qdrant owns Dense and Sparse/BM25 retrieval. PostgreSQL owns control-plane data,
  chunk metadata, version state, and the initial lightweight graph.
- Local defaults are `BAAI/bge-m3` and `BAAI/bge-reranker-v2-m3`. Provider
  interfaces MUST permit local CPU, local GPU, and remote API execution.
- Streamable HTTP is the primary shared MCP transport; stdio is an adapter.
- The initial deployment is single-writer/multi-reader, but storage and write
  coordination abstractions MUST permit future distributed operation.
- Unauthenticated HTTP MUST bind to loopback by default.

## Specification and Delivery Workflow

1. Every delivery Feature MUST have independently testable user scenarios and
   measurable success criteria in `spec.md`.
2. (1.0 historical record) The first delivery Feature was
   `001-minimum-rag-mcp-loop`; it covered the Web management path, Markdown
   and Java ingestion, Dense retrieval, both MCP Tools, and baseline
   evaluation.
3. Feature clarification MUST resolve all `[NEEDS CLARIFICATION]` markers before
   planning.
4. `plan.md` MUST preserve the approved system blueprint and this constitution.
5. `tasks.md` MUST map every task to a requirement or user story and MUST include
   contract, isolation, and target-host tests.
6. Implementation MUST NOT begin before the applicable spec, plan, and tasks have
   passed consistency analysis.
7. Scope expansion MUST be created as a new Feature or an explicit constitution
   amendment; it MUST NOT be hidden inside an unrelated task.

## Governance

This constitution overrides conflicting Feature specs, plans, tasks, and local
implementation preferences. The Non-Negotiable Hard Constraints are
release-blocker invariants: no Feature, plan, task, or local implementation may
weaken or suspend them; an apparent need to do so requires an explicit
constitution amendment with rationale and migration impact.

Amendments require an explicit rationale, affected artifacts, migration impact,
and semantic version change:

- MAJOR for incompatible principle removal or redefinition.
- MINOR for a new principle or materially expanded governance.
- PATCH for non-semantic clarification.

Every `/speckit-plan` and `/speckit-analyze` review MUST verify constitutional
compliance, including every Non-Negotiable Hard Constraint. Exceptions MUST be
documented in the relevant Feature `research.md` with an expiry or removal
condition; silent exceptions are prohibited.

**Version**: 1.3.0 | **Ratified**: 2026-08-26 | **Last Amended**: 2026-09-05
