const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export interface TrustedSource {
  id: string;
  name: string;
  slug: string;
  domain: string;
  base_url: string;
  source_category: string;
  trust_tier: string;
  ingestion_method: string;
  parser_type: string;
  content_types_supported: string[] | null;
  robots_or_access_notes: string | null;
  license_notes: string | null;
  default_language: string | null;
  active: boolean;
  priority: number;
  rate_limit_rpm: number | null;
  crawl_frequency_hours: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface QueuedJob {
  id: string;
  source_run_id: string | null;
  trusted_source_id: string;
  job_type: string;
  status: string;
  priority: number;
  scheduled_for: string | null;
  started_at: string | null;
  completed_at: string | null;
  worker_id: string | null;
  attempt_count: number;
  max_attempts: number;
  payload_jsonb: Record<string, unknown> | null;
  error_log: string | null;
  last_heartbeat_at: string | null;
  created_at: string;
}

export interface Overview {
  total_trusted_sources: number;
  active_trusted_sources: number;
  total_raw_objects: number;
  total_source_records: number;
  total_versions: number;
  total_segments: number;
  total_embeddings: number;
  total_bytes_stored: number;
  jobs_running: number;
  jobs_queued: number;
  jobs_failed: number;
}

export interface SourceProgress {
  id: string;
  trusted_source_id: string;
  last_run_id: string | null;
  discovered_count: number;
  fetched_count: number;
  normalized_count: number;
  segmented_count: number;
  embedded_count: number;
  failed_count: number;
  skipped_count: number;
  total_bytes_stored: number;
  last_successful_checkpoint: string | null;
  last_updated_at: string;
  source_name: string;
  source_slug: string;
  active: boolean;
}

export interface ContextualStatement {
  id: string;
  source_record_id: string;
  source_version_id: string | null;
  segment_id: string | null;
  raw_object_id: string | null;
  statement_text: string;
  context_type: string;
  confidence: string;
  extraction_method: string;
  classifier_model: string | null;
  classifier_version: string | null;
  source_reference: string | null;
  supporting_quote: string | null;
  review_status: string;
  notes_jsonb: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface ContextStats {
  total: number;
  by_type: Record<string, number>;
  by_confidence: Record<string, number>;
  by_review_status: Record<string, number>;
  by_extraction_method: Record<string, number>;
}

export interface IntakeSuggestedSource {
  name: string;
  slug: string;
  domain: string;
  base_url: string;
  source_category: string;
  trust_tier: string;
  ingestion_method: string;
  parser_type: string;
  priority: number;
  default_language: string;
  rate_limit_rpm: number;
  crawl_frequency_hours: number;
  license_notes: string;
  notes: string;
  is_secondary_source: boolean;
}

export interface FieldConfidence {
  [key: string]: number;
}

export interface IntakeDomainGroup {
  domain: string;
  urls: string[];
  suggested_source: IntakeSuggestedSource;
  confidence: FieldConfidence;
  evidence: string[];
}

export interface IntakeAnalyzeResponse {
  id: string;
  groups: IntakeDomainGroup[];
  status: string;
}

export interface CollectionImage {
  id: string;
  image_url: string;
  r2_key: string | null;
  alt_text: string | null;
  caption: string | null;
  image_order: number;
}

export interface CollectionVersion {
  id: string;
  version_type: string;
  language: string | null;
  text_extracted: string | null;
  is_preferred: boolean;
}

export interface CollectionDate {
  id: string;
  date_type: string;
  date_start: number | null;
  date_end: number | null;
  date_label: string | null;
  dating_confidence: string;
}

export interface CollectionSegment {
  id: string;
  segment_type: string;
  segment_order: number;
  original_text: string | null;
  normalized_text: string | null;
}

export interface CollectionContext {
  id: string;
  statement_text: string;
  context_type: string;
  confidence: string;
  review_status: string;
}

export interface CollectionItem {
  id: string;
  canonical_title: string;
  source_category: string;
  culture: string | null;
  language_family: string | null;
  origin_place_name: string | null;
  repository_institution: string | null;
  provenance_status: string;
  record_status: string;
  metadata_jsonb: Record<string, unknown> | null;
  created_at: string;
  source_url: string | null;
  source_name: string;
  source_slug: string;
  images: CollectionImage[];
  versions: CollectionVersion[];
  dates: CollectionDate[];
  segment_count: number;
  context_count: number;
}

export interface CollectionItemDetail extends CollectionItem {
  segments: CollectionSegment[];
  context_statements: CollectionContext[];
}

export interface CollectionStats {
  total_records: number;
  total_images: number;
  total_versions: number;
  total_segments: number;
  total_contexts: number;
  by_source: { name: string; slug: string; count: number }[];
  by_category: Record<string, number>;
  by_culture: Record<string, number>;
}

export const api = {
  // Sources
  listSources: (activeOnly = false) =>
    request<{ items: TrustedSource[]; total: number }>(
      `/sources?active_only=${activeOnly}&limit=200`
    ),
  getSource: (id: string) => request<TrustedSource>(`/sources/${id}`),
  createSource: (data: Record<string, unknown>) =>
    request<TrustedSource>("/sources", { method: "POST", body: JSON.stringify(data) }),
  updateSource: (id: string, data: Record<string, unknown>) =>
    request<TrustedSource>(`/sources/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  pauseSource: (id: string) =>
    request<void>(`/sources/${id}/pause`, { method: "POST" }),
  resumeSource: (id: string) =>
    request<void>(`/sources/${id}/resume`, { method: "POST" }),
  runSource: (id: string, runType = "full_ingest") =>
    request<unknown>(`/sources/${id}/run`, {
      method: "POST",
      body: JSON.stringify({ run_type: runType }),
    }),
  reprocessSource: (id: string) =>
    request<unknown>(`/sources/${id}/reprocess`, { method: "POST" }),

  // Source Intake
  analyzeIntake: (urls: string[]) =>
    request<IntakeAnalyzeResponse>("/sources/intake/analyze", {
      method: "POST",
      body: JSON.stringify({ urls }),
    }),
  approveAllIntake: (groups: IntakeDomainGroup[]) =>
    request<{ created: TrustedSource[]; skipped: string[] }>("/sources/intake/approve-all", {
      method: "POST",
      body: JSON.stringify({ groups }),
    }),

  // Jobs
  listJobs: (params?: { status?: string; job_type?: string; trusted_source_id?: string }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.job_type) qs.set("job_type", params.job_type);
    if (params?.trusted_source_id) qs.set("trusted_source_id", params.trusted_source_id);
    qs.set("limit", "200");
    return request<{ items: QueuedJob[]; total: number }>(`/jobs?${qs}`);
  },
  getJob: (id: string) => request<QueuedJob>(`/jobs/${id}`),
  getJobCheckpoints: (id: string) => request<unknown[]>(`/jobs/${id}/checkpoints`),
  pauseJob: (id: string) => request<void>(`/jobs/${id}/pause`, { method: "POST" }),
  resumeJob: (id: string) => request<void>(`/jobs/${id}/resume`, { method: "POST" }),
  retryJob: (id: string) => request<void>(`/jobs/${id}/retry`, { method: "POST" }),
  cancelJob: (id: string) => request<void>(`/jobs/${id}/cancel`, { method: "POST" }),
  recoverStalled: () => request<{ recovered: number }>("/jobs/recover-stalled", { method: "POST" }),

  // Progress
  getOverview: () => request<Overview>("/progress/overview"),
  getAllSourceProgress: () => request<SourceProgress[]>("/progress/sources"),
  getSourceProgress: (id: string) => request<SourceProgress>(`/progress/sources/${id}`),

  // Context
  listContextStatements: (params?: Record<string, string>) => {
    const qs = new URLSearchParams();
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        if (v) qs.set(k, v);
      }
    }
    qs.set("limit", "100");
    return request<{ items: ContextualStatement[]; total: number }>(`/context/statements?${qs}`);
  },
  getContextStatement: (id: string) => request<ContextualStatement>(`/context/statements/${id}`),
  updateContextStatement: (id: string, data: Record<string, unknown>) =>
    request<ContextualStatement>(`/context/statements/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  batchReviewStatements: (ids: string[], review_status: string) =>
    request<{ updated: number; ids: string[] }>("/context/statements/review", {
      method: "POST",
      body: JSON.stringify({ ids, review_status }),
    }),
  getContextStats: () => request<ContextStats>("/context/stats"),

  // Collection
  listCollection: (params?: Record<string, string>) => {
    const qs = new URLSearchParams();
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        if (v) qs.set(k, v);
      }
    }
    if (!qs.has("limit")) qs.set("limit", "40");
    return request<{ items: CollectionItem[]; total: number }>(`/collection?${qs}`);
  },
  getCollectionItem: (id: string) => request<CollectionItemDetail>(`/collection/${id}`),
  getCollectionStats: () => request<CollectionStats>("/collection/stats"),
};
