import { get } from './client';

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
