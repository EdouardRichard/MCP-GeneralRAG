# Data Model: 012 记忆基座与写读回路

## 1. Authority and Event Log

### `memory_events` (authority)

| Field | Type / rule | Notes |
|---|---|---|
| `event_id` | Snowflake `BIGINT` PK | Monotonic tie-breaker; immutable |
| `event_type` | wide CHECK text | `assert`, `revise`, `retract`, `consolidate`, `access`, `grant`, `rollback` |
| `aggregate_id` | `BIGINT` NOT NULL | Memory id; grant/rollback use affected aggregate or transaction subject |
| `knowledge_scope_id` | FK `knowledge_scopes.scope_id`, NOT NULL | Sole isolation key |
| `payload` | JSONB NOT NULL | Event-specific fields; redacted before insert |
| `authority` | JSONB NOT NULL | Evidence/actor authority envelope |
| `scope_meta` | JSONB NOT NULL | Visibility/scope declaration |
| `mutability` | JSONB NOT NULL | Revision/decay/lock declaration |
| `provenance_meta` | JSONB NOT NULL | Source, transformations, inference metadata |
| `recoverability` | JSONB NOT NULL | Snapshot/replay/affected projection metadata |
| `actionability` | wide text | `evidence`, `preference`, `policy`, `skill`, `commitment` |
| `actor` | text NOT NULL | Agent or management principal |
| `session_id` | UUID nullable | Activity dimension, not isolation |
| `request_id` | UUID/text NOT NULL | Cross-surface audit key |
| `occurred_at` | timestamptz NOT NULL | System/event order timestamp |
| `valid_from` / `valid_to` | timestamptz nullable | Fact-time interval; valid_to open means infinity |
| `created_at` | timestamptz NOT NULL | DB insertion timestamp |

Indexes: `(knowledge_scope_id, aggregate_id, occurred_at)`, `(knowledge_scope_id, event_type, occurred_at)`, and event-point lookup `(knowledge_scope_id, event_id)`. Repository API exposes insert/replay only; no update/delete method.

### Segment and snapshot metadata

Snapshots are immutable records (same authority store or an explicitly versioned snapshot store) containing `snapshot_id`, `scope_id`, `covered_through_event_id`, `covered_through_occurred_at`, six projection fingerprints, schema/index/policy versions, created_at, and status. Snapshot cadence is 10,000 authority events or 24 hours. Access events are a separate 90-day TTL segment. Truncation may remove only ordinary assert events covered by a valid snapshot and not referenced by a retained correction/governance dependency chain.

## 2. Current-State Relation Projection

### `memory_entries`

| Field | Type / rule |
|---|---|
| `memory_id` | Snowflake PK; Qdrant point id |
| `knowledge_scope_id` | FK NOT NULL; scope-local isolation |
| `kind` | wide CHECK; app validator accepts episodic/semantic/procedural |
| `provenance` | wide CHECK; app validator accepts hard/soft/distilled |
| `title` | nullable text |
| `content_text` | redacted text, max 4000 chars |
| `content_hash` | SHA-256 or existing hashing helper; unique within scope |
| `evidence_refs` | JSONB; hard requires at least one published same-scope ref |
| `inference_meta` | JSONB; soft/distilled five required keys |
| `confidence` | numeric 0..1; hard NULL |
| `status` | active/superseded/retired/quarantined via app validator |
| `supersedes_memory_id` / `superseded_by` | nullable self references, same scope |
| `valid_from` / `valid_to` | fact interval |
| `observed_at` / `invalidated_at` | system observation interval |
| `session_id` / `agent_id` | activity metadata |
| `task_context` | JSONB |
| `injection_flags` | JSONB; detector output |
| `expires_at` | derived policy TTL |
| `promote_candidate_at` | nullable; no automatic KB writeback |
| `created_at` / `updated_at` | timestamps |

Indexes: `(knowledge_scope_id, status, observed_at DESC)`, `(knowledge_scope_id, kind, status)`, `(session_id)`, scope-local unique `(knowledge_scope_id, content_hash)`.

### `scope_bindings`

`binding_id` PK, `binding_kind` (`workdir_prefix|git_remote|dir_name`), normalized `binding_value`, `knowledge_scope_id` FK, integer `priority`, `status` (`active|disabled`), creator/timestamps, unique `(binding_kind, binding_value)`. Only management REST may write; MCP reads through `ScopeBindingService`.

### `sessions`

`session_id` UUID PK, `agent_id`, nullable `primary_scope_id` FK (default only), `started_at`, `last_active_at`, `status`, `expires_at`. Session can visit multiple scopes and never grants cross-scope access.

### `memory_salience`

`memory_id` PK/FK, `salience`, `access_count`, `last_access_at`, `reinforced_at`, `decay_rate`. Cold start is 0; β is the policy decay rate (default 0.05/day), γ is 1.0/access. Salience participates in RRF only after decay and at default weight 0.2.

### `memory_recall_runs`

`request_id`, tool, channel (`start_work|recall|attached`), session_id, `scope_ids`, mode, returned_count, package_fingerprint, degraded, failed_paths, latency_ms, created_at, expires_at. TTL 7 days; append-only runtime audit.

## 3. Derived Projection Contracts

1. **Relation**: materialized current `memory_entries`; online write and replay share reducer.
2. **Dense vector**: Qdrant `memories_dense_{index_version}`, point id `memory_id`; payload includes scope, memory_id, kind, session_id and optionally stale status for diagnostics. Scope/kind/session filters may be sent; status/valid/agent are PG post-filters.
3. **Typed links**: future `memory_links` keyed by from/to/relation, provenance and adjudication run; replay adapter required now.
4. **Digest/index tree**: deterministic versioned `DIGEST.md`/`INDEX.md` output; no direct writes from callers.
5. **File mirror**: `memory_projection/{scope}/{kind}/*.md`; path includes normalized scope and projection version.
6. **Salience**: `memory_salience` from access replay and decay; never modifies facts.

Each projection exposes `projection_version`, `source_event_id`, `scope_id`, `fingerprint`, `status` (`complete|partial|failed`) and `updated_at` to the rebuild validator.

## 4. State and Temporal Rules

```text
assert -> active
active --revise--> superseded (valid_to = new.valid_from)
active|superseded --retract/retire--> retired
assert + high-risk injection -> quarantined
active episodic --TTL--> compressed -> archived -> tombstone/retract
```

`as_of` uses valid time only: visible iff `valid_from <= as_of < valid_to` (open valid_to = infinity). Superseded history requires `include_superseded=true`; observed time remains for audit and timeline ordering. Rollback is single-scope, event/time-point based, preserves access events, and replays only state events through the target point.

## 5. Validation Invariants

- Scope is mandatory on every event, entry, vector point and projection path.
- Hard evidence refs are same-scope, existent and published; no anchor means no successful write.
- Soft/distilled inference metadata has source, confidence, model version, time and supporting evidence keys.
- `content_text` is redacted before hashing and persistence.
- Projection writes are reachable only through transaction/reducer services; tests assert no direct repository update/delete API.
- Snapshot+delta replay fingerprint equals full replay fingerprint; retained correction/governance dependencies are never truncated.
