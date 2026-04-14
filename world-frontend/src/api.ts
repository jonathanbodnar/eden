const BASE = '/world-api'

const cache = new Map<string, { data: unknown; ts: number }>()
const CACHE_TTL = 120_000

function getCached<T>(key: string): T | null {
  const entry = cache.get(key)
  if (!entry) return null
  if (Date.now() - entry.ts > CACHE_TTL) {
    cache.delete(key)
    return null
  }
  return entry.data as T
}

function setCache(key: string, data: unknown) {
  cache.set(key, { data, ts: Date.now() })
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`)
  }
  return res.json()
}

async function cachedGet<T>(path: string): Promise<T> {
  const hit = getCached<T>(path)
  if (hit) return hit
  const data = await request<T>(path)
  setCache(path, data)
  return data
}

export interface Epoch {
  id: string
  title: string
  time_start: number | null
  time_end: number | null
  summary: string | null
  version: number
  is_current: boolean
  chapter_count: number
}

export interface Chapter {
  id: string
  epoch_id: string
  title: string
  time_start: number | null
  time_end: number | null
  chapter_summary: string | null
  chapter_order: number
  version: number
  is_current: boolean
}

export interface ChapterDetail extends Chapter {
  actors: Actor[]
  events: CanonEvent[]
  places: Place[]
}

export interface Actor {
  id: string
  canonical_name: string
  actor_type: string
  summary: string | null
  time_start: number | null
  time_end: number | null
}

export interface CanonEvent {
  id: string
  canonical_name: string
  event_type: string
  summary: string | null
  time_start: number | null
  time_end: number | null
}

export interface Place {
  id: string
  canonical_name: string
  place_type: string
  summary: string | null
}

export interface EntityImage {
  id: string
  image_url: string
  caption: string | null
  alt_text: string | null
}

export interface CultureSummary {
  name: string
  source_count: number
  actor_count: number
  event_count: number
  place_count: number
  image_count: number
  explorable: boolean
}

export interface EpochOverview {
  epoch: Epoch
  cultures: CultureSummary[]
  total_sources: number
  total_actors: number
  total_events: number
  total_places: number
  total_images: number
  featured_images: EntityImage[]
  chapters: Chapter[]
}

export interface CultureDetail {
  culture: string
  actors: Actor[]
  events: CanonEvent[]
  places: Place[]
  sources: SourceSet[]
  images: ImageSet[]
}

export interface SourceSet {
  id: string
  chapter_id?: string
  source_record_id?: string
  title: string | null
  excerpt: string | null
  relevance_weight: number
  image_ref: string | null
  source_type: string | null
}

export interface ContextSet {
  id: string
  chapter_id: string
  contextual_statement_id: string
  summary: string | null
  artifact_description: string | null
  relevance_weight: number
}

export interface ArtifactSet {
  id: string
  chapter_id: string
  raw_object_id: string
  title: string | null
  description: string | null
  image_url: string | null
  location: string | null
  date_label: string | null
}

export interface ImageSet {
  id: string
  chapter_id?: string
  image_url: string | null
  caption: string | null
  image_type: string | null
  display_order?: number
}

export interface NarrationPacket {
  id: string
  chapter_id: string
  intro_summary: string | null
  core_summary: string | null
  branch_summary: string | null
  version: number
}

export interface ChatQueryResult {
  session_id: string
  answer_packet_id: string
  answer: string
  answer_mode: string
  confidence: number
  sources: AnswerSource[]
  contexts: AnswerContext[]
}

export interface AnswerSource {
  id: string
  source_record_id: string
  excerpt: string | null
  support_type: string | null
  weight: number
}

export interface AnswerContext {
  id: string
  contextual_statement_id: string
  summary: string | null
  weight: number
}

export interface ChatSession {
  id: string
  chapter_id: string | null
  created_at: string
  updated_at: string
  message_count: number
}

export interface ChatMessage {
  id: string
  session_id: string
  role: string
  content: string
  answer_packet_id: string | null
  created_at: string
}

export interface VideoScript {
  id: string
  entity_type: string
  entity_id: string
  video_type: string
  title: string | null
  raw_script: string | null
  scenes_json: VideoScene[] | null
  duration_target_seconds: number | null
  version: number
  is_current: boolean
}

export interface VideoScene {
  name: string
  tone: string
  actors?: string[]
  place?: string
  event?: string
  visual_prompt: string
  narration: string
  duration_estimate_seconds: number
}

export interface VideoOutput {
  id: string
  script_id: string
  entity_type: string
  entity_id: string
  video_type: string
  r2_key: string | null
  thumbnail_r2_key: string | null
  duration_seconds: number | null
  resolution: string | null
  file_size_bytes: number | null
  version: number
  is_current: boolean
}

export interface VideoStatus {
  entity_type: string
  entity_id: string
  has_script: boolean
  has_video: boolean
  script: VideoScript | null
  video: VideoOutput | null
}

export interface EntityDetail {
  id: string
  canonical_name: string
  actor_type?: string
  event_type?: string
  place_type?: string
  summary: string | null
  time_start: number | null
  time_end: number | null
  merge_confidence: number | null
  geo_hint_json?: Record<string, unknown> | null
  images: EntityImage[]
  chapters: {
    id: string
    title: string
    time_start: number | null
    time_end: number | null
    focus_reason: string | null
  }[]
  source_excerpts: {
    source_record_id: string
    title: string | null
    culture: string | null
    category: string | null
    excerpt: string
    support_type: string
    weight: number
    dates: { date_type: string; date_start: number | null; date_end: number | null; date_label: string | null }[]
  }[]
}

export interface ImageRecordDetail {
  id: string
  image_url: string | null
  caption: string | null
  image_type: string | null
  original_image_url?: string
  alt_text?: string
  original_caption?: string
  external_id?: string
  source_url?: string
  content_type?: string
  record_title?: string
  source_category?: string
  culture?: string
  language_family?: string
  origin_place_name?: string
  provenance_status?: string
  metadata?: Record<string, unknown>
  trusted_source_name?: string
  trust_tier?: string
  dates?: {
    date_type: string
    date_start: number | null
    date_end: number | null
    date_label: string | null
    dating_confidence: string
  }[]
  text_excerpt?: string
}

// ── Story Mode Types ──────────────────────────────────────────────────────

export interface EntityMention {
  name: string
  type: 'actor' | 'event' | 'place'
  canonical_id: string | null
  also_known_as?: string[]
  cultures?: string[]
  role_in_chapter?: string
}

export interface StoryChapter {
  id: string
  outline_id: string | null
  epoch_id: string
  epoch_title: string
  chapter_title: string
  chapter_number: number
  chapter_summary: string
  themes: string[]
  time_hint: string | null
  narrative_text: string
  claims: Array<{ claim: string; source_ids: string[]; score: number; cultures: string[] }>
  entity_mentions: EntityMention[]
  images: Array<{ url: string; caption: string; prompt: string }>
  word_count: number | null
  time_start: number | null
  time_end: number | null
  synthesis_version: number
}

export interface EntityMergeBreakdown {
  entity: {
    id: string
    name: string
    type: string
    subtype: string
    summary: string | null
    time_start?: number | null
    time_end?: number | null
    merge_confidence?: number | null
    score?: {
      final: number
      age: number
      corroboration: number
      independence: number
      ambiguity: number
    }
  }
  cultures: string[]
  equivalences: Array<{
    equivalent_id: string
    equivalent_type: string
    equivalent_name: string | null
    equivalent_summary: string | null
    cultures: string[]
    merge_basis: string
    confidence: number
    reasoning: string
    role_match?: boolean
    action_match?: boolean
    context_match?: boolean
    pattern_match?: boolean
  }>
  sources: Array<{
    source_id: string
    title: string
    culture: string | null
    excerpt: string
    weight: number
  }>
}

export interface StoryEpoch {
  id: string
  title: string
  epoch_order: number
  time_start: number | null
  time_end: number | null
  summary: string | null
  chapter_count: number
  written_count: number
}

export interface StoryEvidence {
  source_id: string
  title: string
  culture: string | null
  category: string | null
  excerpt: string
  origin_place: string | null
}

export interface CultureVariant {
  culture: string
  source_count: number
  source_texts: Array<{ title: string; text: string; culture: string | null; weight: number }>
  actors: Array<{ id: string; name: string; type: string; summary: string }>
  events: Array<{ id: string; name: string; type: string; summary: string }>
  places: Array<{ id: string; name: string; type: string; summary: string }>
}

export interface StoryStats {
  total_source_records: number
  total_images: number
  total_cultures: number
  total_languages: number
  total_segments: number
  total_story_chapters: number
  total_planned_chapters: number
  total_words: number
  total_epochs: number
  total_canonical_actors: number
  total_canonical_events: number
  total_canonical_places: number
}

export const api = {
  getEpochs: () => cachedGet<Epoch[]>('/epochs/'),
  getEpochOverview: (epochId: string) => cachedGet<EpochOverview>(`/epochs/${epochId}/overview`),
  getCultureDetail: (epochId: string, culture: string) =>
    cachedGet<CultureDetail>(`/epochs/${epochId}/culture/${encodeURIComponent(culture)}`),
  getChapters: (epochId?: string) =>
    cachedGet<Chapter[]>(epochId ? `/chapters/?epoch_id=${epochId}` : '/chapters/'),
  getChapterDetail: (id: string) => cachedGet<ChapterDetail>(`/chapters/${id}`),
  getChapterSources: (id: string) => cachedGet<SourceSet[]>(`/chapters/${id}/sources`),
  getChapterContext: (id: string) => cachedGet<ContextSet[]>(`/chapters/${id}/context`),
  getChapterArtifacts: (id: string) => cachedGet<ArtifactSet[]>(`/chapters/${id}/artifacts`),
  getChapterImages: (id: string) => cachedGet<ImageSet[]>(`/chapters/${id}/images`),
  getImageRecordDetail: (imageId: string) => cachedGet<ImageRecordDetail>(`/chapters/images/${imageId}/record`),
  getNarration: (chapterId: string) => cachedGet<NarrationPacket[]>(`/narration-packets/${chapterId}`),
  chatQuery: (query: string, chapterId?: string, sessionId?: string) =>
    request<ChatQueryResult>('/chat/query', {
      method: 'POST',
      body: JSON.stringify({
        query,
        chapter_id: chapterId || null,
        session_id: sessionId || null,
      }),
    }),
  getActorDetail: (id: string) => cachedGet<EntityDetail>(`/actors/${id}`),
  getEventDetail: (id: string) => cachedGet<EntityDetail>(`/events/${id}`),
  getPlaceDetail: (id: string) => cachedGet<EntityDetail>(`/places/${id}`),
  getEntityDetail: (type: 'actor' | 'event' | 'place', id: string) => {
    if (type === 'actor') return cachedGet<EntityDetail>(`/actors/${id}`)
    if (type === 'event') return cachedGet<EntityDetail>(`/events/${id}`)
    return cachedGet<EntityDetail>(`/places/${id}`)
  },
  getEntityVideo: (entityType: string, entityId: string) =>
    cachedGet<VideoStatus>(`/videos/${entityType}/${entityId}`),
  getScriptedChapterIds: () =>
    cachedGet<string[]>('/videos/scripts/batch?entity_type=chapter'),
  requestVideoGeneration: (entityType: string, entityId: string, videoType: string, scriptOnly = false) =>
    request<{ status: string }>('/videos/generate', {
      method: 'POST',
      body: JSON.stringify({
        entity_type: entityType,
        entity_id: entityId,
        video_type: videoType,
        script_only: scriptOnly,
      }),
    }),

  // Story Mode
  getStoryEpochs: () => cachedGet<StoryEpoch[]>('/story/epochs'),
  getStoryChapters: () => cachedGet<StoryChapter[]>('/story/chapters'),
  getStoryChapter: (id: string) => cachedGet<StoryChapter>(`/story/chapters/${id}`),
  getStoryChapterEvidence: (id: string) => cachedGet<StoryEvidence[]>(`/story/chapters/${id}/evidence`),
  getStoryStats: () => cachedGet<StoryStats>('/story/stats'),
  getEntityMergeBreakdown: (entityType: string, entityId: string) =>
    cachedGet<EntityMergeBreakdown>(`/story/entities/${entityType}/${entityId}/merge-breakdown`),
  getCultureVariants: (storyChapterId: string, q?: string) =>
    cachedGet<CultureVariant[]>(`/story/chapters/${storyChapterId}/culture-variants${q ? `?q=${encodeURIComponent(q)}` : ''}`),
}
