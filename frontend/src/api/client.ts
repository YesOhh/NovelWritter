export interface Project {
  id: string;
  title: string;
  genre: string;
  premise: string;
  style_guide: Record<string, unknown>;
  created_at: string;
}

export interface ModelListResult {
  models: string[];
  default: string;
}

export interface CharacterOut {
  id: string;
  name: string;
  profile: {
    personality?: string;
    motivation?: string;
    relationships?: string;
    appearance?: string;
  };
  arc: string;
}

export interface ReviewIssue {
  type: string;
  severity: string;
  location?: string;
  description?: string;
  suggestion?: string;
}

export interface ChapterReviewOut {
  issues: ReviewIssue[];
  summary: string;
  ai_flavor_score?: number;
  ai_flavor_hits?: string[];
  created_at?: string;
}

export interface WorldSettingOut {
  id: string;
  category: string;
  key: string;
  value: string;
}

export interface ForeshadowOut {
  id: string;
  kind: string;
  title: string;
  description: string;
  status: string;
  introduced_at: string;
  payoff: string;
  created_at?: string;
}

export interface TruthFileOut {
  id: string;
  kind: string;
  title: string;
  content: string;
  status: string;
  scope: string;
  owner: string;
  created_at?: string;
  updated_at?: string;
}

export interface TruthConflictItem {
  truth_file_id: string;
  truth_title: string;
  severity: string;
  source_type: string;
  source_id: string;
  source_title: string;
  evidence: string;
  description: string;
  suggestion: string;
}

export interface TruthMaintenanceAction {
  action_type: string;
  target_type: string;
  target_id: string;
  target_title: string;
  priority: string;
  title: string;
  reason: string;
  suggestion: string;
  suggested_status: string;
}

export interface TruthMaintenanceLogEntry {
  action_type: string;
  target_type: string;
  target_id: string;
  target_title: string;
  title: string;
  suggested_status: string;
  result: string;
  created_at: string;
}

export interface TruthFileCheckResult {
  checked_truth_files: number;
  checked_chapters: number;
  issues: TruthConflictItem[];
  maintenance_actions: TruthMaintenanceAction[];
}

export interface TrackingSuggestion {
  foreshadow_id: string;
  title: string;
  current_status: string;
  suggested_status: string;
  confidence: number;
  evidence: string;
  rationale: string;
}

export interface TrackingSuggestionResult {
  suggestions: TrackingSuggestion[];
}

export interface TrackingStallSuggestion {
  foreshadow_id: string;
  title: string;
  kind: string;
  current_status: string;
  silent_chapters: number;
  last_seen: string;
  risk: string;
  action: string;
  recommended_status: string;
  evidence: string;
  suggestion: string;
}

export interface TrackingStallResult {
  checked_threads: number;
  checked_chapters: number;
  total_chapters: number;
  suggestions: TrackingStallSuggestion[];
}

export interface ForeshadowCandidate {
  kind: string;
  title: string;
  description: string;
  introduced_at: string;
  payoff: string;
  evidence: string;
}

export interface ForeshadowExtractResult {
  chapter_id: string;
  chapter_title: string;
  candidates: ForeshadowCandidate[];
}

export interface ProjectHealthResult {
  score: number;
  grade: string;
  summary: string;
  total_issues: number;
  high_issues: number;
  medium_issues: number;
  low_issues: number;
  stall: TrackingStallResult;
  truth: TruthFileCheckResult;
}

export interface StyleFingerprint {
  summary: string;
  narrative_pov: string;
  tense: string;
  sentence_rhythm: string;
  diction: string;
  dialogue: string;
  imagery: string;
  pacing: string;
  taboos: string[];
}

export interface StyleTermStat {
  term: string;
  count: number;
}

export interface StylePunctuationStat {
  mark: string;
  count: number;
  per_1000_chars: number;
}

export interface StyleStats {
  sample_chars: number;
  paragraph_count: number;
  sentence_count: number;
  avg_sentence_chars: number;
  avg_paragraph_chars: number;
  short_sentence_ratio: number;
  medium_sentence_ratio: number;
  long_sentence_ratio: number;
  dialogue_ratio: number;
  dialogue_sentence_ratio: number;
  punctuation: StylePunctuationStat[];
  top_terms: StyleTermStat[];
  overused_terms: StyleTermStat[];
  fatigue_terms: StyleTermStat[];
  prompt: string;
}

export interface StyleSample {
  kind: string;
  label: string;
  text: string;
  char_count: number;
}

export interface ReferenceSettingItem {
  category: string;
  key: string;
  value: string;
}

export interface ReferenceConflictItem {
  kind: string;
  name: string;
  status: string;
  incoming: string;
  existing: string;
  detail: string;
}

export interface ReferenceAnalyzeResult {
  style_fingerprint: StyleFingerprint;
  style_stats: StyleStats;
  style_samples: StyleSample[];
  settings: ReferenceSettingItem[];
  characters: Array<{
    name: string;
    profile: CharacterOut["profile"];
    arc: string;
  }>;
  foreshadows: Array<{
    kind: string;
    title: string;
    description: string;
    status: string;
    introduced_at: string;
    payoff: string;
  }>;
  conflicts: ReferenceConflictItem[];
  applied: boolean;
  created_counts: Record<string, number>;
}

export interface ReferenceChapterTimelineItem {
  chapter_id: string;
  title: string;
  order_index: number;
  summary: string;
  keywords: string[];
  entity_states: Record<string, Record<string, string>>;
}

export interface ReferenceChapterImportResult {
  volume_id: string;
  volume_title: string;
  imported_chapters: number;
  timeline: ReferenceChapterTimelineItem[];
  style_stats: StyleStats;
  style_samples: StyleSample[];
}

export interface ReviseResult {
  content: string;
  review?: ChapterReviewOut | null;
}

export interface OcrResult {
  text: string;
  image_count: number;
}

export interface ReferenceSourceItem {
  id: string;
  label: string;
  text: string;
  char_count: number;
  created_at: string;
}

export interface ChapterContentResult {
  id: string;
  content: string;
  status: string;
  word_count: number;
  summary: string;
  memory_refreshed: boolean;
}

export interface ContextPreviewChapterRef {
  chapter_id: string;
  chapter_title: string;
  volume_id: string;
  volume_title: string;
  volume_kind: string;
  tail: string;
  summary: string;
  entity_states: string[];
}

export interface ContextPreviewSummary {
  chapter_id: string;
  title: string;
  summary: string;
}

export interface ContextPreviewMemoryChunk {
  source_type: string;
  source_id: string;
  source_title: string;
  source_subtitle: string;
  source_kind: string;
  target_type: string;
  target_id: string;
  text: string;
  keywords: string[];
  matched_keywords: string[];
  score: number;
}

export interface ContextPreviewEntityState {
  character_id: string;
  character_name: string;
  state: Record<string, string>;
}

export interface ChapterContextPreview {
  chapter_id: string;
  chapter_title: string;
  volume_id: string;
  volume_title: string;
  volume_kind: string;
  previous_tail: string;
  continuation_anchor?: ContextPreviewChapterRef | null;
  recent_summaries: ContextPreviewSummary[];
  recalled_chunks: ContextPreviewMemoryChunk[];
  entity_states: ContextPreviewEntityState[];
  world_settings_count: number;
  characters_count: number;
  tracking_count: number;
  truth_files_count: number;
  has_style_fingerprint: boolean;
  notes: string[];
}

export interface ChapterOut {
  id: string;
  order_index: number;
  title: string;
  outline: string;
  status: string;
  word_count: number;
  content?: string;
  summary?: string;
  review?: ChapterReviewOut | null;
}

export interface VolumeOut {
  id: string;
  order_index: number;
  kind: string;
  title: string;
  outline: string;
  chapters: ChapterOut[];
}

export interface ProjectDetail extends Project {
  volumes: VolumeOut[];
  characters: CharacterOut[];
  settings: WorldSettingOut[];
  foreshadows: ForeshadowOut[];
  truth_files: TruthFileOut[];
}

export type ExportFormat = "markdown" | "epub";

export interface ExportOptions {
  include_metadata: boolean;
  include_reviews: boolean;
  include_references: boolean;
  include_drafts: boolean;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`${resp.status} ${text}`);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

function filenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null;
  const utf8Name = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (utf8Name) return decodeURIComponent(utf8Name);
  const asciiName = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  return asciiName ?? null;
}

async function reqBlob(url: string): Promise<{ blob: Blob; filename?: string }> {
  const resp = await fetch(url);
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`${resp.status} ${text}`);
  }
  return {
    blob: await resp.blob(),
    filename: filenameFromDisposition(resp.headers.get("Content-Disposition")) ?? undefined,
  };
}

export const api = {
  listModels: () => req<ModelListResult>("/api/models"),
  listProjects: () => req<Project[]>("/api/projects"),
  createProject: (body: {
    title: string;
    genre?: string;
    premise?: string;
  }) => req<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  getProject: (id: string) => req<ProjectDetail>(`/api/projects/${id}`),
  updateProjectModel: (id: string, model: string) =>
    req<Project>(`/api/projects/${id}/model`, {
      method: "PUT",
      body: JSON.stringify({ model }),
    }),
  updateContinuationAnchor: (id: string, chapterId: string | null) =>
    req<Project>(`/api/projects/${id}/continuation-anchor`, {
      method: "PUT",
      body: JSON.stringify({ chapter_id: chapterId }),
    }),
  deleteProject: (id: string) =>
    req<void>(`/api/projects/${id}`, { method: "DELETE" }),
  generateCharacters: (id: string, count: number, model?: string) =>
    req<CharacterOut[]>(`/api/projects/${id}/characters/generate`, {
      method: "POST",
      body: JSON.stringify({ count, model }),
    }),
  createCharacter: (
    id: string,
    body: { name: string; profile?: CharacterOut["profile"]; arc?: string }
  ) =>
    req<CharacterOut>(`/api/projects/${id}/characters`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateCharacter: (
    characterId: string,
    body: { name?: string; profile?: CharacterOut["profile"]; arc?: string }
  ) =>
    req<CharacterOut>(`/api/projects/characters/${characterId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteCharacter: (characterId: string) =>
    req<void>(`/api/projects/characters/${characterId}`, { method: "DELETE" }),
  updateChapterOutline: (
    chapterId: string,
    body: { title?: string; outline?: string }
  ) =>
    req<VolumeOut>(`/api/projects/chapters/${chapterId}/outline`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  updateVolumeOutline: (
    volumeId: string,
    body: { title?: string; outline?: string }
  ) =>
    req<VolumeOut>(`/api/projects/volumes/${volumeId}/outline`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteChapter: (chapterId: string) =>
    req<void>(`/api/projects/chapters/${chapterId}`, { method: "DELETE" }),
  deleteVolume: (volumeId: string) =>
    req<void>(`/api/projects/volumes/${volumeId}`, { method: "DELETE" }),
  generateOutline: (
    id: string,
    volume_count: number,
    chapters_per_volume: number,
    model?: string
  ) =>
    req<VolumeOut[]>(`/api/projects/${id}/outline/generate`, {
      method: "POST",
      body: JSON.stringify({ volume_count, chapters_per_volume, model }),
    }),
  fillOutline: (id: string, chapters_per_volume: number, model?: string) =>
    req<VolumeOut[]>(`/api/projects/${id}/outline/fill`, {
      method: "POST",
      body: JSON.stringify({ chapters_per_volume, model }),
    }),
  createSetting: (projectId: string, body: { category?: string; key: string; value?: string }) =>
    req<WorldSettingOut>(`/api/projects/${projectId}/settings`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateSetting: (
    settingId: string,
    body: { category?: string; key?: string; value?: string }
  ) =>
    req<WorldSettingOut>(`/api/settings/${settingId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteSetting: (settingId: string) =>
    req<void>(`/api/settings/${settingId}`, { method: "DELETE" }),
  createForeshadow: (
    projectId: string,
    body: {
      kind?: string;
      title: string;
      description?: string;
      status?: string;
      introduced_at?: string;
      payoff?: string;
    }
  ) =>
    req<ForeshadowOut>(`/api/projects/${projectId}/foreshadows`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateForeshadow: (
    foreshadowId: string,
    body: {
      kind?: string;
      title?: string;
      description?: string;
      status?: string;
      introduced_at?: string;
      payoff?: string;
    }
  ) =>
    req<ForeshadowOut>(`/api/foreshadows/${foreshadowId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteForeshadow: (foreshadowId: string) =>
    req<void>(`/api/foreshadows/${foreshadowId}`, { method: "DELETE" }),
  extractChapterForeshadows: (chapterId: string, model?: string) =>
    req<ForeshadowExtractResult>(`/api/chapters/${chapterId}/foreshadows/extract`, {
      method: "POST",
      body: JSON.stringify({ model }),
    }),
  createTruthFile: (
    projectId: string,
    body: {
      kind?: string;
      title: string;
      content?: string;
      status?: string;
      scope?: string;
      owner?: string;
    }
  ) =>
    req<TruthFileOut>(`/api/projects/${projectId}/truth-files`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateTruthFile: (
    truthFileId: string,
    body: {
      kind?: string;
      title?: string;
      content?: string;
      status?: string;
      scope?: string;
      owner?: string;
    }
  ) =>
    req<TruthFileOut>(`/api/truth-files/${truthFileId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteTruthFile: (truthFileId: string) =>
    req<void>(`/api/truth-files/${truthFileId}`, { method: "DELETE" }),
  checkTruthFiles: (projectId: string, model?: string, max_chapters = 80) =>
    req<TruthFileCheckResult>(`/api/projects/${projectId}/truth-files/check`, {
      method: "POST",
      body: JSON.stringify({ model, max_chapters }),
    }),
  appendTruthMaintenanceLog: (projectId: string, entries: TruthMaintenanceLogEntry[]) =>
    req<TruthMaintenanceLogEntry[]>(`/api/projects/${projectId}/truth-files/maintenance-log`, {
      method: "POST",
      body: JSON.stringify({ entries }),
    }),
  suggestTracking: (chapterId: string, model?: string) =>
    req<TrackingSuggestionResult>(`/api/chapters/${chapterId}/tracking/suggest`, {
      method: "POST",
      body: JSON.stringify({ model }),
    }),
  scanTrackingStall: (projectId: string, model?: string, max_chapters = 80) =>
    req<TrackingStallResult>(`/api/projects/${projectId}/tracking/stall-scan`, {
      method: "POST",
      body: JSON.stringify({ model, max_chapters }),
    }),
  batchTrackingStatus: (
    projectId: string,
    items: Array<{ foreshadow_id: string; status: string }>
  ) =>
    req<ForeshadowOut[]>(`/api/projects/${projectId}/tracking/batch-status`, {
      method: "POST",
      body: JSON.stringify({ items }),
    }),
  runHealthCheck: (projectId: string, model?: string, max_chapters = 80) =>
    req<ProjectHealthResult>(`/api/projects/${projectId}/health-check`, {
      method: "POST",
      body: JSON.stringify({ model, max_chapters }),
    }),
  analyzeReference: (
    projectId: string,
    text: string,
    opts: { apply_style?: boolean; apply_resources?: boolean } = {},
    model?: string
  ) =>
    req<ReferenceAnalyzeResult>(`/api/projects/${projectId}/reference/analyze`, {
      method: "POST",
      body: JSON.stringify({
        text,
        apply_style: opts.apply_style ?? true,
        apply_resources: opts.apply_resources ?? false,
        model,
      }),
    }),
  applyReference: (
    projectId: string,
    body: {
      apply_style?: boolean;
      style_fingerprint?: StyleFingerprint;
      style_stats?: StyleStats;
      style_samples?: StyleSample[];
      settings?: ReferenceSettingItem[];
      characters?: ReferenceAnalyzeResult["characters"];
      foreshadows?: ReferenceAnalyzeResult["foreshadows"];
      redact_names?: string[];
      source_text?: string;
    }
  ) =>
    req<{ applied: boolean; created_counts: Record<string, number> }>(
      `/api/projects/${projectId}/reference/apply`,
      { method: "POST", body: JSON.stringify(body) }
    ),
  ocrImages: (
    images: { media_type: string; data: string }[],
    instruction = "",
    model?: string
  ) =>
    req<OcrResult>(`/api/ocr`, {
      method: "POST",
      body: JSON.stringify({ images, instruction, model }),
    }),
  renameReferenceSource: (projectId: string, sourceId: string, label: string) =>
    req<ReferenceSourceItem>(
      `/api/projects/${projectId}/reference/sources/${sourceId}`,
      { method: "PATCH", body: JSON.stringify({ label }) }
    ),
  deleteReferenceSource: (projectId: string, sourceId: string) =>
    req<void>(`/api/projects/${projectId}/reference/sources/${sourceId}`, {
      method: "DELETE",
    }),
  importReferenceChapters: (
    projectId: string,
    text: string,
    volume_title = "参考拆书",
    refresh_memory = true,
    max_chapters = 12,
    model?: string
  ) =>
    req<ReferenceChapterImportResult>(`/api/projects/${projectId}/reference/chapters/import`, {
      method: "POST",
      body: JSON.stringify({ text, volume_title, refresh_memory, max_chapters, model }),
    }),
  getChapterContextPreview: (chapterId: string) =>
    req<ChapterContextPreview>(`/api/chapters/${chapterId}/context-preview`),
  reviewChapter: (chapterId: string, model?: string) =>
    req<ChapterReviewOut>(`/api/chapters/${chapterId}/review`, {
      method: "POST",
      body: JSON.stringify({ model }),
    }),
  reviseChapter: (
    chapterId: string,
    mode: "fix" | "anti-detect" = "fix",
    model?: string
  ) =>
    req<ReviseResult>(`/api/chapters/${chapterId}/revise`, {
      method: "POST",
      body: JSON.stringify({ mode, model }),
    }),
  updateChapterContent: (
    chapterId: string,
    content: string,
    refresh_memory = true,
    model?: string
  ) =>
    req<ChapterContentResult>(`/api/chapters/${chapterId}/content`, {
      method: "PUT",
      body: JSON.stringify({ content, refresh_memory, model }),
    }),
  exportProject: (projectId: string, format: ExportFormat, options?: ExportOptions) => {
    const params = new URLSearchParams({ format });
    if (options) {
      params.set("include_metadata", String(options.include_metadata));
      params.set("include_reviews", String(options.include_reviews));
      params.set("include_references", String(options.include_references));
      params.set("include_drafts", String(options.include_drafts));
    }
    return reqBlob(`/api/projects/${projectId}/export?${params.toString()}`);
  },
};
