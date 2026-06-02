export interface Project {
  id: string;
  title: string;
  genre: string;
  premise: string;
  style_guide: Record<string, unknown>;
  created_at: string;
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

export interface ReviseResult {
  content: string;
  review?: ChapterReviewOut | null;
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
  title: string;
  outline: string;
  chapters: ChapterOut[];
}

export interface ProjectDetail extends Project {
  volumes: VolumeOut[];
  characters: CharacterOut[];
  settings: { id: string; category: string; key: string; value: string }[];
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

export const api = {
  listProjects: () => req<Project[]>("/api/projects"),
  createProject: (body: {
    title: string;
    genre?: string;
    premise?: string;
  }) => req<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  getProject: (id: string) => req<ProjectDetail>(`/api/projects/${id}`),
  deleteProject: (id: string) =>
    req<void>(`/api/projects/${id}`, { method: "DELETE" }),
  generateCharacters: (id: string, count: number, model?: string) =>
    req<CharacterOut[]>(`/api/projects/${id}/characters/generate`, {
      method: "POST",
      body: JSON.stringify({ count, model }),
    }),
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
};
