export interface Project {
  project_id: string;
  name: string;
  alias?: string;
  repo_path?: string;
  knowledge_scope_id: string;
  scope_type?: string;
  domain_key?: string;
  slug?: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeSource {
  source_id: string;
  knowledge_scope_id?: string;
  filename: string;
  content_hash: string;
  format: 'markdown' | 'java' | 'openapi' | 'ddl' | 'go' | 'python' | 'word' | 'pdf' | 'html' | 'txt' | 'csv' | 'json' | 'yaml' | 'xml' | 'xlsx' | 'pptx' | 'eml';
  size_bytes: number;
  status: 'uploaded' | 'processing' | 'published' | 'failed' | 'deleted';
  processing_error?: string;
  created_at: string;
  updated_at: string;
}

export interface SSEEvent {
  event: 'processing_progress' | 'publish_progress' | 'delete_progress' | 'error';
  data: {
    source_id?: string;
    run_id?: string;
    stage?: string;
    progress?: number;
    message?: string;
  };
}
