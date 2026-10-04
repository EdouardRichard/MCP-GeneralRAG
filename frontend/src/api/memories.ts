import { get } from './client';

export interface MemorySummary {
  memory_id: number;
  knowledge_scope_id: number;
  kind: string;
  provenance: string;
  status: string;
  content_excerpt?: string;
  evidence_refs?: unknown[];
  injection_flags?: Record<string, unknown>;
  projection_status?: string;
}

export async function fetchMemories(scope?: string): Promise<MemorySummary[]> {
  const query = scope ? `?scope=${encodeURIComponent(scope)}` : '';
  const response = await get<{ memories?: MemorySummary[] } | MemorySummary[]>(`/api/memories${query}`);
  return Array.isArray(response) ? response : response.memories ?? [];
}
