import { get, post, put, del } from './client';

export interface DomainProfile {
  domain_key: string;
  name: string;
  description?: string | null;
  supported_formats: string[];
  chunk_type_extensions?: Record<string, unknown> | null;
  graph_relations: Record<string, unknown>;
  prompt_overrides?: Record<string, unknown> | null;
  default_capabilities: Record<string, unknown>;
  is_builtin: boolean;
  created_at: string;
  updated_at: string;
}

export interface DomainProfileInput {
  domain_key: string;
  name: string;
  description?: string | null;
  supported_formats: string[];
  chunk_type_extensions?: Record<string, unknown> | null;
  graph_relations?: Record<string, unknown>;
  prompt_overrides?: Record<string, unknown> | null;
  default_capabilities?: Record<string, unknown>;
}

export interface DomainProfileListResponse {
  items: DomainProfile[];
  total: number;
}

export async function listDomainProfiles(): Promise<DomainProfile[]> {
  const response = await get<DomainProfileListResponse>('/api/projects/domain-profiles');
  return response.items;
}

export function createDomainProfile(data: DomainProfileInput): Promise<DomainProfile> {
  return post<DomainProfile>('/api/projects/domain-profiles', data);
}

export function updateDomainProfile(domainKey: string, data: Partial<DomainProfileInput>): Promise<DomainProfile> {
  return put<DomainProfile>('/api/projects/domain-profiles/' + encodeURIComponent(domainKey), data);
}

export function deleteDomainProfile(domainKey: string): Promise<void> {
  return del<void>('/api/projects/domain-profiles/' + encodeURIComponent(domainKey));
}
