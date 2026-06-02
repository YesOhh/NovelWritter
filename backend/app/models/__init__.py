"""SQLAlchemy 模型：阶段 2 核心 5 张表（对照 docs/architecture.md §5）。"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))
    genre: Mapped[str] = mapped_column(String(100), default="")
    premise: Mapped[str] = mapped_column(Text, default="")
    style_guide: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    volumes: Mapped[list["Volume"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Volume.order_index",
    )
    characters: Mapped[list["Character"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    settings: Mapped[list["WorldSetting"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Volume(Base):
    __tablename__ = "volumes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(default=0)
    title: Mapped[str] = mapped_column(String(200), default="")
    outline: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")

    project: Mapped["Project"] = relationship(back_populates="volumes")
    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="volume",
        cascade="all, delete-orphan",
        order_by="Chapter.order_index",
    )


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    volume_id: Mapped[str] = mapped_column(ForeignKey("volumes.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(default=0)
    title: Mapped[str] = mapped_column(String(200), default="")
    outline: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    word_count: Mapped[int] = mapped_column(default=0)

    volume: Mapped["Volume"] = relationship(back_populates="chapters")
    summary_row: Mapped["ChapterSummary | None"] = relationship(
        cascade="all, delete-orphan", uselist=False
    )
    reviews: Mapped[list["ChapterReview"]] = relationship(
        back_populates="chapter",
        cascade="all, delete-orphan",
        order_by="ChapterReview.created_at",
    )

    @property
    def summary(self) -> str:
        return self.summary_row.summary if self.summary_row else ""

    @property
    def latest_review(self) -> "ChapterReview | None":
        return self.reviews[-1] if self.reviews else None

    @property
    def review(self) -> "ChapterReview | None":
        # 仅在 reviews 关系已被预加载时返回；未加载则返回 None，
        # 避免在 async 序列化时触发惰性 IO（MissingGreenlet）。
        if "reviews" in inspect(self).unloaded:
            return None
        return self.reviews[-1] if self.reviews else None


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    arc: Mapped[str] = mapped_column(Text, default="")

    project: Mapped["Project"] = relationship(back_populates="characters")


class WorldSetting(Base):
    __tablename__ = "world_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(100), default="")
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(Text, default="")

    project: Mapped["Project"] = relationship(back_populates="settings")


class ChapterSummary(Base):
    __tablename__ = "chapter_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    summary: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)


class EntityState(Base):
    __tablename__ = "entity_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    state: Mapped[dict] = mapped_column(JSON, default=dict)


class MemoryChunk(Base):
    __tablename__ = "memory_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(40))  # setting / character / chapter_summary
    source_id: Mapped[str] = mapped_column(String(36), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)


class ChapterReview(Base):
    __tablename__ = "chapter_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    # issues: [{type, severity, location, description, suggestion}]
    issues: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    ai_flavor_score: Mapped[int] = mapped_column(Integer, default=0)
    ai_flavor_hits: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)

    chapter: Mapped["Chapter"] = relationship(back_populates="reviews")
