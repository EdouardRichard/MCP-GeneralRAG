import { get, post } from './client';

export interface MemorySummary {
  memory_id: string;
  knowledge_scope_id: string;
  kind: string;
  provenance: string;
  status: string;
  content_excerpt?: string;
  title?: string;
  valid_from?: string | null;
  valid_to?: string | null;
  evidence_refs?: unknown[];
  injection_flags?: Record<string, unknown>;
  projection_status?: string;
}

export interface MemoryScope { scope_id: string; name: string; slug: string; domain_key: string }

export function fetchMemoryScopes(): Promise<{ items: MemoryScope[] }> {
  return get('/api/memories/scopes');
}

export function fetchMemories(scope: string, offset = 0): Promise<{ memories: MemorySummary[]; total: number }> {
  return get(`/api/memories?scope_ref=${encodeURIComponent(scope)}&offset=${offset}&limit=20`);
}

/** The browser never filters locally: every filter is a narrowing server query. */
export interface MemoryBrowseFilters {
  kind?: string;
  status?: string;
  provenance?: string;
  session_id?: string;
  min_salience?: number;
}
export interface MemoryBrowsePage {
  memories: MemorySummary[];
  total: number;
  scope_id: string;
}

export function fetchMemoryPage(
  scope: string,
  offset = 0,
  limit = 20,
  filters: MemoryBrowseFilters = {},
): Promise<MemoryBrowsePage> {
  // NOTE: `GET /api/memories` today accepts only scope_ref/limit/offset; these
  // filter parameters are the FR-036 six-dimension narrowing contract and are
  // ignored by the current backend until that endpoint declares them.
  const params = new URLSearchParams({ scope_ref: scope, offset: String(offset), limit: String(limit) });
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  return get(`/api/memories?${params.toString()}`);
}

// --- statistics readout (FR-044, 015 T039) --------------------------------

/** Half-open salience bucket; the final bucket has no upper bound. */
export interface SalienceBucket { lower: number; upper: number | null; count: number }

/** Quantiles are null for a domain with no measured salience (never a rate). */
export interface SalienceDistribution {
  p50: number | null;
  p90: number | null;
  p95: number | null;
  buckets: SalienceBucket[];
}

/** Exactly the ten keys of memory-stats-response.schema.json: counts only, no body. */
export interface MemoryStats {
  scope_id: string;
  domain_key: string;
  generated_at: string;
  total: number;
  kind_distribution: { episodic: number; semantic: number; procedural: number };
  provenance_distribution: { hard: number; soft: number; distilled: number };
  status_distribution: { active: number; superseded: number; retired: number; quarantined: number };
  salience_distribution: SalienceDistribution;
  consolidation_run_count: number;
  rollback_count: number;
}

export function fetchMemoryStats(scope: string): Promise<MemoryStats> {
  return get(`/api/memories/stats?scope_ref=${encodeURIComponent(scope)}`);
}

// --- governance: retire / purge / rollback (FR-037, FR-039) ----------------

export interface MemoryCommand {
  scope_id: number;
  memory_id: number;
  reason: string;
}

export interface MemoryImpactPreview {
  affected: number;
  projections: Record<string, number>;
}

export function retireMemory(command: MemoryCommand): Promise<unknown> {
  return post('/api/memories/retire', command);
}

export function purgeMemory(command: MemoryCommand): Promise<unknown> {
  return post('/api/memories/purge', command);
}

export function recordMemoryUsage(command: MemoryCommand): Promise<unknown> {
  return post('/api/memories/usage', command);
}

export interface RollbackCommand {
  scope_id: number;
  reason: string;
  event_point?: number;
  time_point?: string;
}

export interface MemoryGovernanceResult {
  /** Affected-entry counts per projection, as returned by the governance command. */
  affected?: MemoryImpactPreview;
  [key: string]: unknown;
}

export function rollbackMemories(command: RollbackCommand): Promise<MemoryGovernanceResult> {
  return post('/api/memories/rollback', command);
}

// --- projection rebuild (FR-040) -------------------------------------------

export interface RebuildCommand {
  scope_id: number;
  reason: string;
  since_event_id?: number;
}

export interface RebuildResult {
  scope_id: number;
  request_id: string;
  projections: Record<string, unknown>;
}

export function rebuildMemoryProjections(command: RebuildCommand): Promise<RebuildResult> {
  return post('/api/memories/rebuild', command);
}

export interface RebuildAudit {
  request_id: string;
  operation: string;
  actor: string;
  scope_id: number;
  reason: string;
  source_event_id: number | null;
  since_event_id: number | null;
  result: unknown;
  created_at: string;
}

export function fetchRebuildAudit(requestId: string, scopeId?: number): Promise<RebuildAudit> {
  const params = new URLSearchParams({ request_id: requestId });
  if (scopeId !== undefined) params.set('scope_id', String(scopeId));
  return get(`/api/memories/rebuild/audit?${params.toString()}`);
}

// --- promotion (FR-041) ----------------------------------------------------

export interface PromotionCandidate {
  memory_id: string;
  kind: string | null;
  provenance: string | null;
  confidence: number | null;
  promote_candidate_at: string | null;
  candidate_version: string | null;
  evidence_attributions: unknown[];
  promotable: boolean;
  ineligibility_reasons: string[];
  promotion_pointer: unknown;
  certificate?: string;
}

export interface PromotionCandidatePage {
  scope_id: string;
  items: PromotionCandidate[];
  total: number;
}

export function fetchPromotionCandidates(scope: string, limit = 50, offset = 0): Promise<PromotionCandidatePage> {
  const params = new URLSearchParams({ scope_ref: scope, limit: String(limit), offset: String(offset) });
  return get(`/api/memories/promotion-candidates?${params.toString()}`);
}

export interface PromoteCommand {
  scope_id: number;
  memory_id: number;
  candidate_version: string;
  reason: string;
}

export interface PromotionTask {
  schema_version: number;
  scope_id: string;
  memory_id: string;
  candidate_version: string;
  task_id: string | number;
  source_id: string;
  initial_processing_run_id: string;
  status: string;
  version_id: string | null;
  request_id: string;
  reused: boolean;
}

export function promoteCandidate(command: PromoteCommand): Promise<PromotionTask> {
  return post('/api/memories/promote', command);
}

export interface PromotionReport {
  schema_version: number;
  scope_id: string;
  task_id: string | number;
  memory_id: string;
  candidate_version: string;
  source_id: string;
  initial_processing_run_id: string;
  attempt_run_ids: string[];
  status: string;
  published_version_id: string | null;
  result: unknown;
  authority_event_ids: string[];
}

export function fetchPromotionReport(taskId: string | number, scope: string): Promise<PromotionReport> {
  return get(`/api/memories/promotions/${encodeURIComponent(String(taskId))}?scope_ref=${encodeURIComponent(scope)}`);
}

// --- consolidation report (FR-042) -----------------------------------------

export interface ConsolidationRunCounts {
  input_events?: number;
  proposals?: number;
  adjudications?: number;
  outputs?: number;
}

export interface ConsolidationRun {
  schema_version: number;
  run_id?: string;
  trigger: string;
  execution_context: string;
  status: string;
  observation_seq: number;
  window: Record<string, unknown> | null;
  input_event_ids: string[];
  proposals: unknown[];
  adjudications: unknown[];
  output_memory_ids: string[];
  output_event_ids: string[];
  degradation_reasons: string[];
  counts: ConsolidationRunCounts;
  created_at: string;
  ttl_expires_at: string;
}

export interface ConsolidationRunPage {
  schema_version: number;
  scope_id: string;
  items: ConsolidationRun[];
  total: number;
}

export function fetchConsolidationRuns(scope: string, limit = 20, offset = 0): Promise<ConsolidationRunPage> {
  const params = new URLSearchParams({ scope_ref: scope, limit: String(limit), offset: String(offset) });
  return get(`/api/memories/consolidation/runs?${params.toString()}`);
}

export function fetchConsolidationRun(scope: string, runId: string, includeHistory = false): Promise<ConsolidationRun> {
  const params = new URLSearchParams({ scope_ref: scope, include_history: String(includeHistory) });
  return get(`/api/memories/consolidation/runs/${encodeURIComponent(runId)}?${params.toString()}`);
}

export interface ConsolidationCommand { scope_id: number; reason: string }

export interface ConsolidationAdmission {
  schema_version: number;
  run_id: string;
  scope_id: string;
  request_id: string;
  trigger: string;
  execution_context: string;
  status: string;
  window: null;
  report_url: string;
}

export function startConsolidation(command: ConsolidationCommand): Promise<ConsolidationAdmission> {
  return post('/api/memories/consolidation', command);
}

// --- domain policy (view 6 editor) -----------------------------------------

export function fetchMemoryPolicy(scope: string): Promise<{ scope_id: string; domain_key: string; policy: unknown }> {
  return get(`/api/memories/policy?scope_ref=${encodeURIComponent(scope)}`);
}

export interface PolicyCommand { scope_id: number; reason: string; policy: unknown }

export function updateMemoryPolicy(command: PolicyCommand): Promise<unknown> {
  return post('/api/memories/policy', command);
}
