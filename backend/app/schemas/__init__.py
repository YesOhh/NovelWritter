"""Pydantic DTO：API 出入参 + Agent 结构化输出。"""
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


# ---------- Project ----------


class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    genre: str = ""
    premise: str = ""
    style_guide: dict = Field(default_factory=dict)


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
    title: str
    outline: str
    chapters: list[ChapterOut] = []


class CharacterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    profile: dict
    arc: str


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


class ProjectDetail(ProjectOut):
    volumes: list[VolumeOut] = []
    characters: list[CharacterOut] = []
    settings: list[WorldSettingOut] = []


# ---------- Agent 生成请求/结果 ----------


class OutlineGenerateRequest(BaseModel):
    volume_count: int = Field(default=3, ge=1, le=12)
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
