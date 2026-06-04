"""Pydantic DTO：API 出入参 + Agent 结构化输出。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------- Review (阶段 4) ----------


class ReviewIssue(BaseModel):
    type: str = "other"
    severity: str = "low"
    location: str = ""
    description: str = ""
    suggestion: str = ""


class ChapterReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    issues: list[ReviewIssue] = []
    summary: str = ""
    ai_flavor_score: int = 0
    ai_flavor_hits: list[str] = []
    created_at: datetime | None = None


class ReviseRequest(BaseModel):
    mode: str = "fix"  # fix | anti-detect
    model: str | None = None


class ReviseResult(BaseModel):
    content: str = ""
    review: ChapterReviewOut | None = None


class ChapterContentUpdate(BaseModel):
    content: str = ""
    refresh_memory: bool = True
    model: str | None = None


class ChapterContentResult(BaseModel):
    id: str
    content: str = ""
    status: str = "drafted"
    word_count: int = 0
    summary: str = ""
    memory_refreshed: bool = False


class ContextPreviewChapterRef(BaseModel):
    chapter_id: str = ""
    chapter_title: str = ""
    volume_id: str = ""
    volume_title: str = ""
    volume_kind: str = "novel"
    tail: str = ""
    summary: str = ""
    entity_states: list[str] = []


class ContextPreviewSummary(BaseModel):
    chapter_id: str = ""
    title: str = ""
    summary: str = ""


class ContextPreviewMemoryChunk(BaseModel):
    source_type: str = ""
    source_id: str = ""
    source_title: str = ""
    source_subtitle: str = ""
    source_kind: str = ""
    target_type: str = ""  # chapter | overview | ""
    target_id: str = ""
    text: str = ""
    keywords: list[str] = []
    matched_keywords: list[str] = []
    score: float = 0.0


class ContextPreviewEntityState(BaseModel):
    character_id: str = ""
    character_name: str = ""
    state: dict = Field(default_factory=dict)


class ChapterContextPreview(BaseModel):
    chapter_id: str = ""
    chapter_title: str = ""
    volume_id: str = ""
    volume_title: str = ""
    volume_kind: str = "novel"
    previous_tail: str = ""
    continuation_anchor: ContextPreviewChapterRef | None = None
    recent_summaries: list[ContextPreviewSummary] = []
    recalled_chunks: list[ContextPreviewMemoryChunk] = []
    entity_states: list[ContextPreviewEntityState] = []
    world_settings_count: int = 0
    characters_count: int = 0
    tracking_count: int = 0
    truth_files_count: int = 0
    has_style_fingerprint: bool = False
    notes: list[str] = []


# ---------- Project ----------


class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    genre: str = ""
    premise: str = ""
    style_guide: dict = Field(default_factory=dict)


class ProjectModelUpdate(BaseModel):
    model: str = Field(default="", max_length=200)


class ProjectContinuationAnchorUpdate(BaseModel):
    chapter_id: str | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    genre: str
    premise: str
    style_guide: dict
    created_at: datetime


class ChapterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_index: int
    title: str
    outline: str
    status: str
    word_count: int
    content: str = ""
    summary: str = ""
    review: "ChapterReviewOut | None" = None


class VolumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_index: int
    kind: str = "novel"
    title: str
    outline: str
    chapters: list[ChapterOut] = []


class CharacterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    profile: dict
    arc: str


class CharacterCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    profile: dict = Field(default_factory=dict)
    arc: str = ""


class CharacterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    profile: dict | None = None
    arc: str | None = None


class ChapterOutlineUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    outline: str | None = None


class VolumeOutlineUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    outline: str | None = None


class WorldSettingCreate(BaseModel):
    category: str = ""
    key: str = Field(..., min_length=1, max_length=200)
    value: str = ""


class WorldSettingUpdate(BaseModel):
    category: str | None = None
    key: str | None = None
    value: str | None = None


class WorldSettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category: str
    key: str
    value: str


class ForeshadowCreate(BaseModel):
    kind: str = "foreshadow"
    title: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    status: str = "open"
    introduced_at: str = ""
    payoff: str = ""


class ForeshadowUpdate(BaseModel):
    kind: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = None
    introduced_at: str | None = None
    payoff: str | None = None


class ForeshadowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    title: str
    description: str
    status: str
    introduced_at: str
    payoff: str
    created_at: datetime | None = None


class TruthFileCreate(BaseModel):
    kind: str = "constraint"
    title: str = Field(..., min_length=1, max_length=200)
    content: str = ""
    status: str = "active"
    scope: str = "全书"
    owner: str = ""


class TruthFileUpdate(BaseModel):
    kind: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    status: str | None = None
    scope: str | None = None
    owner: str | None = None


class TruthFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    title: str
    content: str
    status: str
    scope: str
    owner: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TruthFileCheckRequest(BaseModel):
    model: str | None = None
    max_chapters: int = Field(default=60, ge=1, le=160)


class TruthConflictItem(BaseModel):
    truth_file_id: str = ""
    truth_title: str = ""
    severity: str = "medium"  # high | medium | low
    source_type: str = ""  # chapter | setting | character | truth_file | overview
    source_id: str = ""
    source_title: str = ""
    evidence: str = ""
    description: str = ""
    suggestion: str = ""


class TruthMaintenanceAction(BaseModel):
    action_type: str = "revise_truth_file"
    target_type: str = "truth_file"  # truth_file | chapter | setting | character | project
    target_id: str = ""
    target_title: str = ""
    priority: str = "medium"  # high | medium | low
    title: str = ""
    reason: str = ""
    suggestion: str = ""
    suggested_status: str = ""  # active | draft | resolved | archived | ""


class TruthFileCheckResult(BaseModel):
    checked_truth_files: int = 0
    checked_chapters: int = 0
    issues: list[TruthConflictItem] = []
    maintenance_actions: list[TruthMaintenanceAction] = []


class TruthMaintenanceLogEntry(BaseModel):
    action_type: str = ""
    target_type: str = ""
    target_id: str = ""
    target_title: str = ""
    title: str = ""
    suggested_status: str = ""
    result: str = "applied"
    created_at: str = ""


class TruthMaintenanceLogCreate(BaseModel):
    entries: list[TruthMaintenanceLogEntry] = []


class TrackingSuggestion(BaseModel):
    foreshadow_id: str
    title: str = ""
    current_status: str = "open"
    suggested_status: str = "no_change"
    confidence: int = Field(default=0, ge=0, le=100)
    evidence: str = ""
    rationale: str = ""


class TrackingSuggestionResult(BaseModel):
    suggestions: list[TrackingSuggestion] = []


class TrackingStallRequest(BaseModel):
    model: str | None = None
    max_chapters: int = Field(default=60, ge=1, le=160)


class TrackingStallSuggestion(BaseModel):
    foreshadow_id: str = ""
    title: str = ""
    kind: str = "foreshadow"
    current_status: str = "open"
    silent_chapters: int = 0
    last_seen: str = ""
    risk: str = "medium"  # high | medium | low
    action: str = "remind"  # remind | advance | resolve | drop | none
    recommended_status: str = "no_change"  # no_change | open | progressing | resolved
    evidence: str = ""
    suggestion: str = ""


class TrackingStallResult(BaseModel):
    checked_threads: int = 0
    checked_chapters: int = 0
    total_chapters: int = 0
    suggestions: list[TrackingStallSuggestion] = []


class TrackingBatchStatusItem(BaseModel):
    foreshadow_id: str
    status: str  # open | progressing | resolved


class TrackingBatchStatusRequest(BaseModel):
    items: list[TrackingBatchStatusItem] = []


class ForeshadowExtractRequest(BaseModel):
    model: str | None = None


class ForeshadowCandidate(BaseModel):
    kind: str = "foreshadow"  # foreshadow | subplot | resource | relationship
    title: str = ""
    description: str = ""
    introduced_at: str = ""
    payoff: str = ""
    evidence: str = ""


class ForeshadowExtractResult(BaseModel):
    chapter_id: str = ""
    chapter_title: str = ""
    candidates: list[ForeshadowCandidate] = []


class ProjectHealthRequest(BaseModel):
    model: str | None = None
    max_chapters: int = Field(default=80, ge=1, le=160)


class ProjectHealthResult(BaseModel):
    score: int = Field(default=100, ge=0, le=100)
    grade: str = ""  # 优秀 | 良好 | 需关注 | 偏弱
    summary: str = ""
    total_issues: int = 0
    high_issues: int = 0
    medium_issues: int = 0
    low_issues: int = 0
    stall: TrackingStallResult = Field(default_factory=TrackingStallResult)
    truth: TruthFileCheckResult = Field(default_factory=TruthFileCheckResult)


class StyleFingerprint(BaseModel):
    summary: str = ""
    narrative_pov: str = ""
    tense: str = ""
    sentence_rhythm: str = ""
    diction: str = ""
    dialogue: str = ""
    imagery: str = ""
    pacing: str = ""
    taboos: list[str] = []


class StyleTermStat(BaseModel):
    term: str = ""
    count: int = 0


class StylePunctuationStat(BaseModel):
    mark: str = ""
    count: int = 0
    per_1000_chars: float = 0.0


class StyleStats(BaseModel):
    sample_chars: int = 0
    paragraph_count: int = 0
    sentence_count: int = 0
    avg_sentence_chars: float = 0.0
    avg_paragraph_chars: float = 0.0
    short_sentence_ratio: float = 0.0
    medium_sentence_ratio: float = 0.0
    long_sentence_ratio: float = 0.0
    dialogue_ratio: float = 0.0
    dialogue_sentence_ratio: float = 0.0
    punctuation: list[StylePunctuationStat] = []
    top_terms: list[StyleTermStat] = []
    overused_terms: list[StyleTermStat] = []
    fatigue_terms: list[StyleTermStat] = []
    prompt: str = ""


class StyleSample(BaseModel):
    kind: str = "narration"
    label: str = "叙述"
    text: str = ""
    char_count: int = 0


class ReferenceSettingItem(BaseModel):
    category: str = ""
    key: str = ""
    value: str = ""


class ReferenceForeshadowItem(BaseModel):
    kind: str = "foreshadow"
    title: str = ""
    description: str = ""
    status: str = "open"
    introduced_at: str = ""
    payoff: str = ""


class ReferenceAnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=50, max_length=60000)
    # 是否把抽取到的文风指纹/统计/样例写入项目（学习文风，默认开）。
    apply_style: bool = True
    # 是否把抽取到的设定/角色/伏笔写入项目当成本书正典（会照搬参考书内容，默认关）。
    apply_resources: bool = False
    model: str | None = None


class ReferenceConflictItem(BaseModel):
    kind: str = "setting"  # setting | character | foreshadow
    name: str = ""
    status: str = "duplicate"  # duplicate | conflict
    incoming: str = ""
    existing: str = ""
    detail: str = ""


class ReferenceSourceItem(BaseModel):
    id: str = ""
    label: str = ""
    text: str = ""
    char_count: int = 0
    created_at: str = ""


class ReferenceSourceRenameRequest(BaseModel):
    label: str = Field(default="", max_length=120)


class ReferenceApplyRequest(BaseModel):
    """用户在拆书结果里勾选/编辑后，要写入项目的精选内容。"""

    apply_style: bool = False
    style_fingerprint: StyleFingerprint = Field(default_factory=StyleFingerprint)
    style_stats: StyleStats = Field(default_factory=StyleStats)
    style_samples: list[StyleSample] = []
    settings: list[ReferenceSettingItem] = []
    characters: list[CharacterItem] = []
    foreshadows: list[ReferenceForeshadowItem] = []
    # 用于从文风/样例中清洗的原书专名（通常是全部被识别的角色名）。
    redact_names: list[str] = []
    # 一并保留的本次拆书原文（便于回看），留空则不保存。
    source_text: str = Field(default="", max_length=60000)


class ReferenceApplyResult(BaseModel):
    applied: bool = True
    created_counts: dict = Field(default_factory=dict)


class ReferenceAnalyzeResult(BaseModel):
    style_fingerprint: StyleFingerprint = Field(default_factory=StyleFingerprint)
    style_stats: StyleStats = Field(default_factory=StyleStats)
    style_samples: list[StyleSample] = []
    settings: list[ReferenceSettingItem] = []
    characters: list[CharacterItem] = []
    foreshadows: list[ReferenceForeshadowItem] = []
    conflicts: list[ReferenceConflictItem] = []
    applied: bool = False
    created_counts: dict = Field(default_factory=dict)


class ReferenceChapterImportRequest(BaseModel):
    text: str = Field(..., min_length=50, max_length=160000)
    volume_title: str = Field(default="参考拆书", max_length=200)
    refresh_memory: bool = True
    max_chapters: int = Field(default=12, ge=1, le=30)
    model: str | None = None


class ReferenceChapterTimelineItem(BaseModel):
    chapter_id: str
    title: str
    order_index: int
    summary: str = ""
    keywords: list[str] = []
    entity_states: dict[str, dict] = Field(default_factory=dict)


class ReferenceChapterImportResult(BaseModel):
    volume_id: str
    volume_title: str
    imported_chapters: int = 0
    timeline: list[ReferenceChapterTimelineItem] = []
    style_stats: StyleStats = Field(default_factory=StyleStats)
    style_samples: list[StyleSample] = []


class ProjectDetail(ProjectOut):
    volumes: list[VolumeOut] = []
    characters: list[CharacterOut] = []
    settings: list[WorldSettingOut] = []
    foreshadows: list[ForeshadowOut] = []
    truth_files: list[TruthFileOut] = []


# ---------- OCR 图片识别 ----------


class OcrImageItem(BaseModel):
    media_type: str = Field(..., max_length=64)
    data: str = Field(..., min_length=1, description="图片的 base64 编码（不含 data URL 前缀）")


class OcrRequest(BaseModel):
    images: list[OcrImageItem] = Field(..., min_length=1, max_length=20)
    instruction: str = Field(default="", max_length=2000)
    model: str | None = None


class OcrResult(BaseModel):
    text: str = ""
    image_count: int = 0


# ---------- Agent 生成请求/结果 ----------


class OutlineGenerateRequest(BaseModel):
    volume_count: int = Field(default=3, ge=1, le=12)
    chapters_per_volume: int = Field(default=5, ge=1, le=30)
    model: str | None = None


class OutlineFillRequest(BaseModel):
    chapters_per_volume: int = Field(default=5, ge=1, le=30)
    model: str | None = None


class CharacterGenerateRequest(BaseModel):
    count: int = Field(default=4, ge=1, le=12)
    model: str | None = None


class ChapterGenerateRequest(BaseModel):
    word_count: int = Field(default=1500, ge=200, le=6000)
    model: str | None = None


class OutlineChapter(BaseModel):
    title: str
    outline: str


class OutlineVolume(BaseModel):
    title: str
    outline: str
    chapters: list[OutlineChapter]


class OutlineResult(BaseModel):
    volumes: list[OutlineVolume]


class OutlineChaptersResult(BaseModel):
    chapters: list[OutlineChapter]


class CharacterProfile(BaseModel):
    personality: str = ""
    motivation: str = ""
    relationships: str = ""
    appearance: str = ""


class CharacterItem(BaseModel):
    name: str
    profile: CharacterProfile
    arc: str = ""


class CharacterResult(BaseModel):
    characters: list[CharacterItem]
