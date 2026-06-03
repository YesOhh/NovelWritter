"""章节生成 API：通过 SSE 流式返回写作 Agent 的输出。"""
import json
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.reviewer_agent import review_chapter
from app.agents.reviser_agent import revise_chapter
from app.agents.style_stats import style_text_from_guide
from app.agents.tracking_agent import suggest_tracking_updates
from app.agents.writer_agent import write_chapter_from_context, write_chapter_stream
from app.config import settings
from app.db import AsyncSessionLocal
from app.llm.model_resolver import resolve_project_model
from app.memory import entity_tracker
from app.memory.chapter_memory import refresh_chapter_memory
from app.memory.retriever import retriever
from app.models import (
    Chapter,
    ChapterReview,
    ChapterSummary,
    Character,
    EntityState,
    Foreshadow,
    MemoryChunk,
    Project,
    TruthFile,
    Volume,
    WorldSetting,
)
from app.schemas import (
    ChapterContextPreview,
    ChapterContentResult,
    ChapterContentUpdate,
    ChapterGenerateRequest,
    ChapterReviewOut,
    ContextPreviewChapterRef,
    ContextPreviewEntityState,
    ContextPreviewMemoryChunk,
    ContextPreviewSummary,
    ReviseRequest,
    ReviseResult,
    TrackingSuggestionResult,
)

router = APIRouter(prefix="/api", tags=["generate"])


class GenerateRequest(BaseModel):
    premise: str = Field(default="", description="故事整体设定")
    style: str = Field(default="", description="文风要求")
    chapter_outline: str = Field(..., description="本章大纲")
    word_count: int = Field(default=1500, ge=200, le=6000)
    model: str | None = Field(default=None, description="指定模型，留空则用默认模型")


# 作为后备的静态模型列表（当无法从代理动态获取时）。
# 命名对齐代理暴露的短名，避免代理离线走后备时调用失败。
_FALLBACK_MODELS = [
    "claude-opus-4.8",
    "claude-sonnet-4.6",
]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _is_reference_volume(volume: Volume) -> bool:
    return (getattr(volume, "kind", "novel") or "novel") == "reference"


async def _novel_chapter_ids(session: AsyncSession, project_id: str) -> set[str]:
    result = await session.execute(
        select(Chapter.id)
        .join(Volume, Chapter.volume_id == Volume.id)
        .where(Volume.project_id == project_id, Volume.kind == "novel")
    )
    return {chapter_id for chapter_id in result.scalars().all()}


@router.get("/models")
async def list_models() -> dict:
    """返回可用模型列表。使用本地代理时，尝试从其 chatModels 接口动态获取。"""
    models: list[str] = []
    if settings.anthropic_base_url:
        # 代理地址形如 http://127.0.0.1:23333/api/anthropic，推出根地址。
        root = settings.anthropic_base_url.split("/api/")[0]
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{root}/api/v1/lm/chatModels")
                resp.raise_for_status()
                data = resp.json()
                items = data if isinstance(data, list) else data.get("data", data.get("models", []))
                for item in items:
                    name = item.get("id") or item.get("family") or item.get("name") if isinstance(item, dict) else item
                    if name:
                        models.append(name)
        except Exception:  # noqa: BLE001 - 代理不可用时静默回退
            models = []
    if not models:
        models = _FALLBACK_MODELS
    # 去重并保持原有顺序
    seen: set[str] = set()
    unique = [m for m in models if not (m in seen or seen.add(m))]
    return {"models": unique, "default": settings.claude_model}


@router.post("/chapters/generate")
async def generate_chapter(req: GenerateRequest):
    async def event_stream() -> AsyncIterator[str]:
        yield _sse("status", {"stage": "writing"})
        word_count = 0
        try:
            async for chunk in write_chapter_stream(
                premise=req.premise,
                style=req.style,
                chapter_outline=req.chapter_outline,
                word_count=req.word_count,
                model=req.model,
            ):
                word_count += len(chunk)
                yield _sse("token", {"text": chunk})
            yield _sse("done", {"word_count": word_count})
        except Exception as exc:  # noqa: BLE001 - 将错误回传前端
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _format_characters(characters: list[Character]) -> str:
    if not characters:
        return ""
    lines: list[str] = []
    for c in characters:
        p = c.profile or {}
        lines.append(
            f"- {c.name}：性格={p.get('personality', '')}；"
            f"动机={p.get('motivation', '')}；关系={p.get('relationships', '')}"
        )
    return "\n".join(lines)


def _format_world_settings(world_settings: list[WorldSetting]) -> str:
    if not world_settings:
        return ""
    lines: list[str] = []
    for setting in world_settings:
        category = f"[{setting.category}] " if setting.category else ""
        lines.append(f"- {category}{setting.key}：{setting.value}")
    return "\n".join(lines)


def _format_foreshadows(items: list[Foreshadow]) -> str:
    if not items:
        return ""
    kind_labels = {
        "foreshadow": "伏笔",
        "subplot": "支线",
        "resource": "资源线",
        "relationship": "情感线",
    }
    status_labels = {
        "open": "待回收",
        "progressing": "推进中",
        "resolved": "已回收",
    }
    status_order = {"open": 0, "progressing": 1, "resolved": 2}
    lines: list[str] = []
    for item in sorted(items, key=lambda f: (status_order.get(f.status, 9), f.created_at)):
        kind = kind_labels.get(item.kind, item.kind or "线索")
        status = status_labels.get(item.status, item.status or "open")
        details = [f"[{status}/{kind}] {item.title}：{item.description}"]
        if item.introduced_at:
            details.append(f"引入位置={item.introduced_at}")
        if item.payoff:
            details.append(f"回收/推进计划={item.payoff}")
        lines.append("；".join(details))
    return "\n".join(f"- {line}" for line in lines)


def _premise_with_settings(premise: str, world_settings: str) -> str:
    if not world_settings:
        return premise
    return f"{premise or '（未提供）'}\n\n【世界观设定】\n{world_settings}"


def _premise_with_tracking(premise: str, tracking: str) -> str:
    if not tracking:
        return premise
    return f"{premise or '（未提供）'}\n\n【伏笔/支线追踪】\n{tracking}"


def _format_truth_files(items: list[TruthFile]) -> str:
    if not items:
        return ""
    kind_labels = {
        "constraint": "硬约束",
        "resource": "资源账本",
        "relationship": "情感弧线",
        "secret": "隐藏真相",
        "timeline": "长期时间线",
    }
    status_labels = {
        "active": "生效中",
        "draft": "草稿",
        "resolved": "已兑现",
        "archived": "归档",
    }
    lines: list[str] = []
    for item in sorted(items, key=lambda truth: (truth.status == "archived", truth.created_at)):
        if item.status == "archived":
            continue
        kind = kind_labels.get(item.kind, item.kind or "真相")
        status = status_labels.get(item.status, item.status or "active")
        details = [f"[{status}/{kind}] {item.title}：{item.content}"]
        if item.scope:
            details.append(f"范围={item.scope}")
        if item.owner:
            details.append(f"相关={item.owner}")
        lines.append("；".join(details))
    return "\n".join(f"- {line}" for line in lines)


def _premise_with_truth_files(premise: str, truth_files: str) -> str:
    if not truth_files:
        return premise
    return f"{premise or '（未提供）'}\n\n【长篇真相文件 / 不可违背约束】\n{truth_files}"


def _keywords_of(text: str) -> list[str]:
    """轻量取词：按常见标点/空白切分，保留长度≥2 的词，去重。
    中文检索主要靠 MemoryChunk 的关键词集合匹配，这里作为 query 侧的粗切分。"""
    import re

    parts = re.split(r"[\s，。；、：？！,.;:?!　（）()【】\"'…—\-]+", text or "")
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if len(p) >= 2 and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _tail(text: str, limit: int) -> str:
    return (text or "")[-limit:]


def _state_line(name: str, state: dict) -> str:
    parts = [f"{key}={value}" for key, value in (state or {}).items() if value]
    return f"{name}：{'；'.join(parts)}" if parts else name


def _volume_source_label(volume: Volume) -> str:
    if (volume.kind or "novel") == "reference":
        return f"参考资料 · {volume.title}"
    return f"正文 · 第 {volume.order_index + 1} 卷 · {volume.title}"


async def _memory_chunk_preview(
    session: AsyncSession,
    chunk: MemoryChunk,
    score: float,
    matched_keywords: list[str],
) -> ContextPreviewMemoryChunk:
    source_title = ""
    source_subtitle = ""
    source_kind = ""
    target_type = ""
    target_id = ""

    if chunk.source_type == "chapter_summary":
        result = await session.execute(
            select(Chapter, Volume)
            .join(Volume, Chapter.volume_id == Volume.id)
            .where(Chapter.id == chunk.source_id)
        )
        row = result.first()
        if row:
            chapter, volume = row
            source_title = chapter.title
            source_subtitle = _volume_source_label(volume)
            source_kind = volume.kind or "novel"
            target_type = "chapter"
            target_id = chapter.id
    elif chunk.source_type == "volume_outline":
        volume = await session.get(Volume, chunk.source_id)
        if volume:
            source_title = volume.title
            source_subtitle = _volume_source_label(volume)
            source_kind = volume.kind or "novel"
            target_type = "overview"
    elif chunk.source_type == "setting":
        setting = await session.get(WorldSetting, chunk.source_id)
        if setting:
            source_title = setting.key
            source_subtitle = f"设定 · {setting.category}" if setting.category else "设定"
            source_kind = "setting"
            target_type = "overview"
    elif chunk.source_type == "character":
        character = await session.get(Character, chunk.source_id)
        if character:
            source_title = character.name
            source_subtitle = "角色"
            source_kind = "character"
            target_type = "overview"
    elif chunk.source_type == "foreshadow":
        item = await session.get(Foreshadow, chunk.source_id)
        if item:
            source_title = item.title
            source_subtitle = "线索/伏笔"
            source_kind = item.kind or "foreshadow"
            target_type = "overview"
    elif chunk.source_type == "truth_file":
        item = await session.get(TruthFile, chunk.source_id)
        if item:
            source_title = item.title
            source_subtitle = f"真相文件 · {item.kind}"
            source_kind = item.kind or "truth_file"
            target_type = "overview"

    return ContextPreviewMemoryChunk(
        source_type=chunk.source_type,
        source_id=chunk.source_id,
        source_title=source_title or chunk.source_type,
        source_subtitle=source_subtitle,
        source_kind=source_kind,
        target_type=target_type,
        target_id=target_id,
        text=chunk.text,
        keywords=chunk.keywords or [],
        matched_keywords=matched_keywords,
        score=round(score, 2),
    )


@router.get("/chapters/{chapter_id}/context-preview", response_model=ChapterContextPreview)
async def preview_chapter_context(chapter_id: str) -> ChapterContextPreview:
    """返回生成本章前会使用的上下文来源，供前端解释和核对。"""
    async with AsyncSessionLocal() as session:
        chapter = await session.get(Chapter, chapter_id)
        if chapter is None:
            raise HTTPException(status_code=404, detail="章节不存在")

        volume = await session.get(Volume, chapter.volume_id)
        if volume is None:
            raise HTTPException(status_code=404, detail="章节所属卷不存在")
        if _is_reference_volume(volume):
            raise HTTPException(status_code=400, detail="参考资料章节没有正文生成上下文")

        project = await session.get(Project, volume.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="项目不存在")

        char_result = await session.execute(
            select(Character).where(Character.project_id == project.id)
        )
        characters = list(char_result.scalars().all())
        id_to_name = {character.id: character.name for character in characters}

        setting_result = await session.execute(
            select(WorldSetting).where(WorldSetting.project_id == project.id)
        )
        world_settings = list(setting_result.scalars().all())

        foreshadow_result = await session.execute(
            select(Foreshadow).where(Foreshadow.project_id == project.id)
        )
        foreshadows = list(foreshadow_result.scalars().all())

        truth_result = await session.execute(
            select(TruthFile).where(TruthFile.project_id == project.id, TruthFile.status != "archived")
        )
        truth_files = list(truth_result.scalars().all())

        notes: list[str] = []
        previous_tail = ""
        if chapter.order_index > 0:
            prev_result = await session.execute(
                select(Chapter).where(
                    Chapter.volume_id == volume.id,
                    Chapter.order_index == chapter.order_index - 1,
                )
            )
            previous = prev_result.scalar_one_or_none()
            if previous and previous.content:
                previous_tail = _tail(previous.content, 600)
            else:
                notes.append("同卷上一章还没有正文，前情尾巴为空。")
        else:
            notes.append("这是本卷第一章，没有同卷上一章尾巴。")

        style_guide = project.style_guide if isinstance(project.style_guide, dict) else {}
        anchor = style_guide.get("continuation_anchor") if isinstance(style_guide, dict) else None
        anchor_chapter_id = anchor.get("chapter_id") if isinstance(anchor, dict) else ""
        anchor_preview: ContextPreviewChapterRef | None = None
        if anchor_chapter_id:
            if anchor_chapter_id == chapter_id:
                notes.append("当前章节就是续写起点，生成时不会重复注入它自己。")
            else:
                anchor_result = await session.execute(
                    select(Chapter, Volume)
                    .join(Volume, Chapter.volume_id == Volume.id)
                    .where(Chapter.id == anchor_chapter_id, Volume.project_id == project.id)
                )
                anchor_row = anchor_result.first()
                if anchor_row:
                    anchor_chapter, anchor_volume = anchor_row
                    summary_result = await session.execute(
                        select(ChapterSummary).where(ChapterSummary.chapter_id == anchor_chapter.id)
                    )
                    anchor_summary = summary_result.scalar_one_or_none()
                    state_result = await session.execute(
                        select(EntityState).where(EntityState.chapter_id == anchor_chapter.id)
                    )
                    anchor_states = [
                        _state_line(id_to_name.get(state.character_id, ""), state.state or {})
                        for state in state_result.scalars().all()
                        if id_to_name.get(state.character_id)
                    ]
                    anchor_preview = ContextPreviewChapterRef(
                        chapter_id=anchor_chapter.id,
                        chapter_title=anchor_chapter.title,
                        volume_id=anchor_volume.id,
                        volume_title=anchor_volume.title,
                        volume_kind=anchor_volume.kind or "novel",
                        tail=_tail(anchor_chapter.content, 800),
                        summary=anchor_summary.summary if anchor_summary else "",
                        entity_states=anchor_states,
                    )
                else:
                    notes.append("已设置的续写起点不存在或不属于当前项目。")
        else:
            notes.append("尚未设置续写起点。")

        recent_summaries: list[ContextPreviewSummary] = []
        prior_result = await session.execute(
            select(Chapter)
            .where(
                Chapter.volume_id == volume.id,
                Chapter.order_index < chapter.order_index,
            )
            .order_by(Chapter.order_index.desc())
        )
        prior_chapters = list(prior_result.scalars().all())[:3]
        for prior in reversed(prior_chapters):
            summary_result = await session.execute(
                select(ChapterSummary).where(ChapterSummary.chapter_id == prior.id)
            )
            summary = summary_result.scalar_one_or_none()
            if summary and summary.summary:
                recent_summaries.append(
                    ContextPreviewSummary(
                        chapter_id=prior.id,
                        title=prior.title,
                        summary=summary.summary,
                    )
                )
        if not recent_summaries:
            notes.append("同卷暂无可用章节摘要。")

        query_keywords = _keywords_of(chapter.outline)
        recalled = await retriever.retrieve_scored(
            session,
            project_id=project.id,
            query_text=chapter.outline,
            query_keywords=query_keywords,
            k=5,
            exclude_source_ids={chapter.id},
        )
        recalled_chunks = [
            await _memory_chunk_preview(session, chunk, score, matched_keywords)
            for score, matched_keywords, chunk in recalled
        ]
        if not recalled_chunks:
            notes.append("本章大纲暂未召回相关记忆片段。")

        current_states = await entity_tracker.current_states(
            session, [character.id for character in characters], await _novel_chapter_ids(session, project.id)
        )
        entity_states = [
            ContextPreviewEntityState(
                character_id=character_id,
                character_name=id_to_name.get(character_id, ""),
                state=state,
            )
            for character_id, state in current_states.items()
            if id_to_name.get(character_id)
        ]
        if not entity_states:
            notes.append("暂无正文角色状态，生成后会逐章建立。")

        return ChapterContextPreview(
            chapter_id=chapter.id,
            chapter_title=chapter.title,
            volume_id=volume.id,
            volume_title=volume.title,
            volume_kind=volume.kind or "novel",
            previous_tail=previous_tail,
            continuation_anchor=anchor_preview,
            recent_summaries=recent_summaries,
            recalled_chunks=recalled_chunks,
            entity_states=entity_states,
            world_settings_count=len(world_settings),
            characters_count=len(characters),
            tracking_count=len(foreshadows),
            truth_files_count=len(truth_files),
            has_style_fingerprint=bool(
                style_guide.get("style") or style_guide.get("style_fingerprint") or style_guide.get("style_stats")
            ),
            notes=notes,
        )


@router.post("/chapters/{chapter_id}/generate")
async def generate_chapter_in_project(chapter_id: str, req: ChapterGenerateRequest):
    """项目感知写作：按 chapter_id 反查项目上下文 → 流式生成 → 成稿回写。"""
    # 先在独立 session 里把所需数据全部取出（StreamingResponse 会超出请求作用域，
    # 故不能用请求级 Depends(get_session)，在生成器内自管 session）。
    async with AsyncSessionLocal() as session:
        chapter = await session.get(Chapter, chapter_id)
        if chapter is None:
            raise HTTPException(status_code=404, detail="章节不存在")

        volume = await session.get(Volume, chapter.volume_id)
        if _is_reference_volume(volume):
            raise HTTPException(status_code=400, detail="参考资料章节不能生成正文")
        project = await session.get(Project, volume.project_id)

        char_result = await session.execute(
            select(Character).where(Character.project_id == project.id)
        )
        characters = list(char_result.scalars().all())

        setting_result = await session.execute(
            select(WorldSetting).where(WorldSetting.project_id == project.id)
        )
        world_settings = list(setting_result.scalars().all())

        foreshadow_result = await session.execute(
            select(Foreshadow).where(Foreshadow.project_id == project.id)
        )
        foreshadows = list(foreshadow_result.scalars().all())

        truth_result = await session.execute(
            select(TruthFile).where(TruthFile.project_id == project.id, TruthFile.status != "archived")
        )
        truth_files = list(truth_result.scalars().all())

        # 前情：同卷中上一章（order_index - 1）的正文结尾。
        previous_tail = ""
        if chapter.order_index > 0:
            prev_result = await session.execute(
                select(Chapter).where(
                    Chapter.volume_id == volume.id,
                    Chapter.order_index == chapter.order_index - 1,
                )
            )
            prev = prev_result.scalar_one_or_none()
            if prev and prev.content:
                previous_tail = prev.content[-600:]

        continuation_summary = ""
        continuation_tail = ""
        continuation_states = ""
        style_guide = project.style_guide if isinstance(project.style_guide, dict) else {}
        anchor = style_guide.get("continuation_anchor") if isinstance(style_guide, dict) else None
        anchor_chapter_id = anchor.get("chapter_id") if isinstance(anchor, dict) else ""
        if anchor_chapter_id and anchor_chapter_id != chapter_id:
            anchor_result = await session.execute(
                select(Chapter, Volume)
                .join(Volume, Chapter.volume_id == Volume.id)
                .where(Chapter.id == anchor_chapter_id, Volume.project_id == project.id)
            )
            anchor_row = anchor_result.first()
            if anchor_row:
                anchor_chapter, anchor_volume = anchor_row
                anchor_ref = f"第 {anchor_volume.order_index + 1} 卷 · {anchor_volume.title} / {anchor_chapter.title}"
                if anchor_chapter.content:
                    continuation_tail = f"【续写起点：{anchor_ref}】\n{anchor_chapter.content[-800:]}"
                cs_res = await session.execute(
                    select(ChapterSummary).where(ChapterSummary.chapter_id == anchor_chapter.id)
                )
                cs = cs_res.scalar_one_or_none()
                if cs and cs.summary:
                    continuation_summary = f"续写起点 {anchor_ref}：{cs.summary}"
                if characters:
                    state_result = await session.execute(
                        select(EntityState).where(EntityState.chapter_id == anchor_chapter.id)
                    )
                    id_to_anchor_name = {c.id: c.name for c in characters}
                    anchor_state_lines: list[str] = []
                    for state in state_result.scalars().all():
                        parts = [f"{k}={v}" for k, v in (state.state or {}).items() if v]
                        name = id_to_anchor_name.get(state.character_id)
                        if name and parts:
                            anchor_state_lines.append(f"- {name}：{'；'.join(parts)}")
                    if anchor_state_lines:
                        continuation_states = "【续写起点角色状态】\n" + "\n".join(anchor_state_lines)

        # L2 分层摘要：卷摘要 + 同卷最近 3 章的章节摘要。
        volume_summary = volume.summary or ""
        recent_summaries: list[str] = []
        prior_result = await session.execute(
            select(Chapter)
            .where(
                Chapter.volume_id == volume.id,
                Chapter.order_index < chapter.order_index,
            )
            .order_by(Chapter.order_index.desc())
        )
        prior_chapters = list(prior_result.scalars().all())[:3]
        for pc in reversed(prior_chapters):
            cs_res = await session.execute(
                select(ChapterSummary).where(ChapterSummary.chapter_id == pc.id)
            )
            cs = cs_res.scalar_one_or_none()
            if cs and cs.summary:
                recent_summaries.append(f"{pc.title}：{cs.summary}")
        if continuation_summary:
            recent_summaries.insert(0, continuation_summary)

        # L3 轻量 RAG：按本章大纲关键词召回历史片段（排除本章自身的摘要片段）。
        recalled = await retriever.retrieve(
            session,
            project_id=project.id,
            query_text=chapter.outline,
            query_keywords=_keywords_of(chapter.outline),
            k=5,
            exclude_source_ids={chapter.id},
        )
        recalled_text = "\n".join(f"- {c.text}" for c in recalled)

        # L4 实体状态：相关角色当前状态。
        states = await entity_tracker.current_states(
            session, [c.id for c in characters], await _novel_chapter_ids(session, project.id)
        )
        id_to_name = {c.id: c.name for c in characters}
        state_lines = []
        for cid, st in states.items():
            parts = [f"{k}={v}" for k, v in st.items() if v]
            if parts:
                state_lines.append(f"- {id_to_name.get(cid, '')}：{'；'.join(parts)}")
        entity_states_text = "\n".join(state_lines)
        if continuation_states:
            entity_states_text = (
                f"{continuation_states}\n\n【当前最新角色状态】\n{entity_states_text}"
                if entity_states_text
                else continuation_states
            )

        if continuation_tail:
            previous_tail = (
                f"{previous_tail}\n\n{continuation_tail}"
                if previous_tail
                else continuation_tail
            )

        world_settings_text = _format_world_settings(world_settings)
        premise = _premise_with_tracking(
            _premise_with_settings(project.premise, world_settings_text),
            _format_foreshadows(foreshadows),
        )
        premise = _premise_with_truth_files(premise, _format_truth_files(truth_files))
        genre = project.genre
        project_id = project.id
        model_name = resolve_project_model(project, req.model)
        style = style_text_from_guide(style_guide, genre)
        characters_text = _format_characters(characters)
        volume_outline = volume.outline
        chapter_outline = chapter.outline
        char_snapshot = [(c.id, c.name) for c in characters]

    async def event_stream() -> AsyncIterator[str]:
        yield _sse("status", {"stage": "writing", "chapter_id": chapter_id})
        full = ""
        try:
            async for chunk in write_chapter_from_context(
                premise=premise,
                style=style or genre,
                characters=characters_text,
                volume_outline=volume_outline,
                chapter_outline=chapter_outline,
                previous_tail=previous_tail,
                word_count=req.word_count,
                model=model_name,
                volume_summary=volume_summary,
                recent_summaries="\n".join(recent_summaries),
                recalled=recalled_text,
                entity_states=entity_states_text,
            ):
                full += chunk
                yield _sse("token", {"text": chunk})

            # 成稿回写（新开 session，避免跨请求作用域复用）。
            async with AsyncSessionLocal() as ws:
                ch = await ws.get(Chapter, chapter_id)
                if ch is not None:
                    ch.content = full
                    ch.word_count = len(full)
                    ch.status = "drafted"
                    await ws.commit()
            # 正文先交付：用户已看到全文。
            yield _sse("done", {"chapter_id": chapter_id, "word_count": len(full), "status": "drafted"})

            # 记忆更新流水（不阻塞正文体验）：摘要 + 索引 + 实体状态。
            yield _sse("status", {"stage": "indexing"})
            try:
                async with AsyncSessionLocal() as ms:
                    chap = await ms.get(Chapter, chapter_id)
                    char_objs = []
                    for cid, cname in char_snapshot:
                        c = await ms.get(Character, cid)
                        if c:
                            char_objs.append(c)
                    await refresh_chapter_memory(
                        session=ms,
                        chapter=chap,
                        project_id=project_id,
                        characters=char_objs,
                        model=model_name,
                    )
                    await ms.commit()
                yield _sse("indexed", {"chapter_id": chapter_id})
            except Exception as mem_exc:  # noqa: BLE001 - 记忆更新失败不影响正文
                yield _sse("index_error", {"message": str(mem_exc)})

            # 审校闭环：成稿 + 记忆就绪后，做一致性检测并落库。
            yield _sse("status", {"stage": "reviewing"})
            try:
                report = await review_chapter(
                    content=full,
                    premise=premise,
                    style=style or genre,
                    characters=characters_text,
                    entity_states=entity_states_text,
                    recent_summaries="\n".join(recent_summaries),
                    chapter_outline=chapter_outline,
                    model=model_name,
                )
                async with AsyncSessionLocal() as rs:
                    rs.add(
                        ChapterReview(
                            chapter_id=chapter_id,
                            issues=report.get("issues", []),
                            summary=report.get("summary", ""),
                            ai_flavor_score=report.get("ai_flavor_score", 0),
                            ai_flavor_hits=report.get("ai_flavor_hits", []),
                            model=model_name,
                        )
                    )
                    await rs.commit()
                yield _sse(
                    "reviewed",
                    {
                        "chapter_id": chapter_id,
                        "issues": report.get("issues", []),
                        "summary": report.get("summary", ""),
                        "ai_flavor_score": report.get("ai_flavor_score", 0),
                        "ai_flavor_hits": report.get("ai_flavor_hits", []),
                    },
                )

                # 自动修订闭环：若有 high/medium 问题且仍有重试额度，定向改写→再审。
                def _needs_fix(rep: dict) -> bool:
                    return any(
                        i.get("severity") in ("high", "medium")
                        for i in (rep.get("issues") or [])
                    )

                retries_left = settings.review_retries
                round_no = 0
                while _needs_fix(report) and retries_left > 0:
                    round_no += 1
                    retries_left -= 1
                    before_count = len(report.get("issues") or [])
                    yield _sse("status", {"stage": "revising", "round": round_no})
                    revised = await revise_chapter(
                        content=full,
                        issues=report.get("issues", []),
                        premise=premise,
                        style=style or genre,
                        characters=characters_text,
                        entity_states=entity_states_text,
                        chapter_outline=chapter_outline,
                        mode="fix",
                        model=model_name,
                    )
                    if not revised:
                        break
                    full = revised
                    # 回写修订后正文 + 刷新章节摘要，保持记忆一致。
                    async with AsyncSessionLocal() as us:
                        ch = await us.get(Chapter, chapter_id)
                        if ch is not None:
                            ch.content = full
                            ch.word_count = len(full)
                        char_objs = []
                        for cid, cname in char_snapshot:
                            c = await us.get(Character, cid)
                            if c:
                                char_objs.append(c)
                        if ch is not None:
                            await refresh_chapter_memory(
                                session=us,
                                chapter=ch,
                                project_id=project_id,
                                characters=char_objs,
                                model=model_name,
                            )
                        await us.commit()

                    # 再审一轮。
                    report = await review_chapter(
                        content=full,
                        premise=premise,
                        style=style or genre,
                        characters=characters_text,
                        entity_states=entity_states_text,
                        recent_summaries="\n".join(recent_summaries),
                        chapter_outline=chapter_outline,
                        model=model_name,
                    )
                    async with AsyncSessionLocal() as rs:
                        rs.add(
                            ChapterReview(
                                chapter_id=chapter_id,
                                issues=report.get("issues", []),
                                summary=report.get("summary", ""),
                                ai_flavor_score=report.get("ai_flavor_score", 0),
                                ai_flavor_hits=report.get("ai_flavor_hits", []),
                                model=model_name,
                            )
                        )
                        await rs.commit()
                    yield _sse(
                        "revised",
                        {
                            "chapter_id": chapter_id,
                            "round": round_no,
                            "before_issues": before_count,
                            "after_issues": len(report.get("issues") or []),
                            "content": full,
                            "word_count": len(full),
                            "issues": report.get("issues", []),
                            "summary": report.get("summary", ""),
                            "ai_flavor_score": report.get("ai_flavor_score", 0),
                            "ai_flavor_hits": report.get("ai_flavor_hits", []),
                        },
                    )
            except Exception as rev_exc:  # noqa: BLE001 - 审校失败不影响正文
                yield _sse("review_error", {"message": str(rev_exc)})
        except Exception as exc:  # noqa: BLE001 - 将错误回传前端
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chapters/{chapter_id}/review", response_model=ChapterReviewOut)
async def review_chapter_endpoint(chapter_id: str, req: ChapterGenerateRequest):
    """对已成稿章节单独重审，落库并返回最新报告。"""
    async with AsyncSessionLocal() as session:
        chapter = await session.get(Chapter, chapter_id)
        if chapter is None:
            raise HTTPException(status_code=404, detail="章节不存在")
        if not chapter.content:
            raise HTTPException(status_code=400, detail="章节尚未成稿，无法审校")

        volume = await session.get(Volume, chapter.volume_id)
        project = await session.get(Project, volume.project_id)

        char_result = await session.execute(
            select(Character).where(Character.project_id == project.id)
        )

        characters = list(char_result.scalars().all())

        setting_result = await session.execute(
            select(WorldSetting).where(WorldSetting.project_id == project.id)
        )
        world_settings = list(setting_result.scalars().all())

        foreshadow_result = await session.execute(
            select(Foreshadow).where(Foreshadow.project_id == project.id)
        )
        foreshadows = list(foreshadow_result.scalars().all())

        truth_result = await session.execute(
            select(TruthFile).where(TruthFile.project_id == project.id, TruthFile.status != "archived")
        )
        truth_files = list(truth_result.scalars().all())

        # 前情摘要：同卷此前最多 3 章。
        recent_summaries: list[str] = []
        prior_result = await session.execute(
            select(Chapter)
            .where(
                Chapter.volume_id == volume.id,
                Chapter.order_index < chapter.order_index,
            )
            .order_by(Chapter.order_index.desc())
        )
        for pc in list(reversed(list(prior_result.scalars().all())[:3])):
            cs_res = await session.execute(
                select(ChapterSummary).where(ChapterSummary.chapter_id == pc.id)
            )
            cs = cs_res.scalar_one_or_none()
            if cs and cs.summary:
                recent_summaries.append(f"{pc.title}：{cs.summary}")

        # 实体状态。
        states = await entity_tracker.current_states(
            session, [c.id for c in characters], await _novel_chapter_ids(session, project.id)
        )
        id_to_name = {c.id: c.name for c in characters}
        state_lines = []
        for cid, st in states.items():
            parts = [f"{k}={v}" for k, v in st.items() if v]
            if parts:
                state_lines.append(f"- {id_to_name.get(cid, '')}：{'；'.join(parts)}")

        style = style_text_from_guide(project.style_guide, project.genre)
        model_name = resolve_project_model(project, req.model)
        premise = _premise_with_tracking(
            _premise_with_settings(project.premise, _format_world_settings(world_settings)),
            _format_foreshadows(foreshadows),
        )
        premise = _premise_with_truth_files(premise, _format_truth_files(truth_files))
        report = await review_chapter(
            content=chapter.content,
            premise=premise,
            style=style or project.genre,
            characters=_format_characters(characters),
            entity_states="\n".join(state_lines),
            recent_summaries="\n".join(recent_summaries),
            chapter_outline=chapter.outline,
            model=model_name,
        )
        review = ChapterReview(
            chapter_id=chapter_id,
            issues=report.get("issues", []),
            summary=report.get("summary", ""),
            ai_flavor_score=report.get("ai_flavor_score", 0),
            ai_flavor_hits=report.get("ai_flavor_hits", []),
            model=model_name,
        )
        session.add(review)
        await session.commit()
        return ChapterReviewOut(
            issues=report.get("issues", []),
            summary=report.get("summary", ""),
            ai_flavor_score=report.get("ai_flavor_score", 0),
            ai_flavor_hits=report.get("ai_flavor_hits", []),
            created_at=review.created_at,
        )


@router.post("/chapters/{chapter_id}/tracking/suggest", response_model=TrackingSuggestionResult)
async def suggest_chapter_tracking(chapter_id: str, req: ChapterGenerateRequest):
    """根据当前章节正文，为项目伏笔/支线追踪项给出状态建议。"""
    async with AsyncSessionLocal() as session:
        chapter = await session.get(Chapter, chapter_id)
        if chapter is None:
            raise HTTPException(status_code=404, detail="章节不存在")
        if not chapter.content:
            raise HTTPException(status_code=400, detail="章节尚未成稿，无法分析线索")

        volume = await session.get(Volume, chapter.volume_id)
        project = await session.get(Project, volume.project_id)
        result = await session.execute(
            select(Foreshadow).where(Foreshadow.project_id == project.id)
        )
        items = list(result.scalars().all())
        if not items:
            return TrackingSuggestionResult(suggestions=[])

        payload = [
            {
                "id": item.id,
                "kind": item.kind,
                "title": item.title,
                "status": item.status,
                "introduced_at": item.introduced_at,
                "description": item.description,
                "payoff": item.payoff,
            }
            for item in items
        ]
        return await suggest_tracking_updates(
            content=chapter.content,
            chapter_title=chapter.title,
            chapter_outline=chapter.outline,
            tracking_items=payload,
            model=resolve_project_model(project, req.model),
        )


@router.put("/chapters/{chapter_id}/content", response_model=ChapterContentResult)
async def update_chapter_content(chapter_id: str, req: ChapterContentUpdate):
    """手动保存章节正文，并可刷新摘要/RAG/实体状态。"""
    async with AsyncSessionLocal() as session:
        chapter = await session.get(Chapter, chapter_id)
        if chapter is None:
            raise HTTPException(status_code=404, detail="章节不存在")

        volume = await session.get(Volume, chapter.volume_id)
        project = await session.get(Project, volume.project_id)
        char_result = await session.execute(
            select(Character).where(Character.project_id == project.id)
        )
        characters = list(char_result.scalars().all())

        chapter.content = req.content
        chapter.word_count = len(req.content)
        chapter.status = "drafted" if req.content else "outlined"
        summary = ""
        memory_refreshed = False
        if req.content and req.refresh_memory:
            memory = await refresh_chapter_memory(
                session=session,
                chapter=chapter,
                project_id=project.id,
                characters=characters,
                model=resolve_project_model(project, req.model),
            )
            summary = memory.get("summary", "")
            memory_refreshed = True
        await session.commit()
        return ChapterContentResult(
            id=chapter.id,
            content=chapter.content,
            status=chapter.status,
            word_count=chapter.word_count,
            summary=summary,
            memory_refreshed=memory_refreshed,
        )


@router.post("/chapters/{chapter_id}/revise", response_model=ReviseResult)
async def revise_chapter_endpoint(chapter_id: str, req: ReviseRequest):
    """对已成稿章节手动修订（fix=按最新审校报告修；anti-detect=去 AI 味），
    回写正文、刷新摘要并重新审校，返回新正文 + 最新报告。"""
    async with AsyncSessionLocal() as session:
        chapter = await session.get(Chapter, chapter_id)
        if chapter is None:
            raise HTTPException(status_code=404, detail="章节不存在")
        if not chapter.content:
            raise HTTPException(status_code=400, detail="章节尚未成稿，无法修订")

        volume = await session.get(Volume, chapter.volume_id)
        project = await session.get(Project, volume.project_id)

        char_result = await session.execute(
            select(Character).where(Character.project_id == project.id)
        )
        characters = list(char_result.scalars().all())

        setting_result = await session.execute(
            select(WorldSetting).where(WorldSetting.project_id == project.id)
        )
        world_settings = list(setting_result.scalars().all())

        foreshadow_result = await session.execute(
            select(Foreshadow).where(Foreshadow.project_id == project.id)
        )
        foreshadows = list(foreshadow_result.scalars().all())

        truth_result = await session.execute(
            select(TruthFile).where(TruthFile.project_id == project.id, TruthFile.status != "archived")
        )
        truth_files = list(truth_result.scalars().all())

        # 前情摘要：同卷此前最多 3 章。
        recent_summaries: list[str] = []
        prior_result = await session.execute(
            select(Chapter)
            .where(
                Chapter.volume_id == volume.id,
                Chapter.order_index < chapter.order_index,
            )
            .order_by(Chapter.order_index.desc())
        )
        for pc in list(reversed(list(prior_result.scalars().all())[:3])):
            cs_res = await session.execute(
                select(ChapterSummary).where(ChapterSummary.chapter_id == pc.id)
            )
            cs = cs_res.scalar_one_or_none()
            if cs and cs.summary:
                recent_summaries.append(f"{pc.title}：{cs.summary}")

        states = await entity_tracker.current_states(
            session, [c.id for c in characters], await _novel_chapter_ids(session, project.id)
        )
        id_to_name = {c.id: c.name for c in characters}
        state_lines = []
        for cid, st in states.items():
            parts = [f"{k}={v}" for k, v in st.items() if v]
            if parts:
                state_lines.append(f"- {id_to_name.get(cid, '')}：{'；'.join(parts)}")
        entity_states_text = "\n".join(state_lines)

        style = style_text_from_guide(project.style_guide, project.genre)
        model_name = resolve_project_model(project, req.model)
        characters_text = _format_characters(characters)
        premise = _premise_with_tracking(
            _premise_with_settings(project.premise, _format_world_settings(world_settings)),
            _format_foreshadows(foreshadows),
        )
        premise = _premise_with_truth_files(premise, _format_truth_files(truth_files))

        # fix 模式取该章最新审校报告作为修订依据。
        issues: list = []
        if req.mode != "anti-detect":
            last_res = await session.execute(
                select(ChapterReview)
                .where(ChapterReview.chapter_id == chapter_id)
                .order_by(ChapterReview.created_at.desc())
            )
            last = last_res.scalars().first()
            if last:
                issues = last.issues or []

        revised = await revise_chapter(
            content=chapter.content,
            issues=issues,
            premise=premise,
            style=style or project.genre,
            characters=characters_text,
            entity_states=entity_states_text,
            chapter_outline=chapter.outline,
            mode=req.mode,
            model=model_name,
        )

        # 回写正文 + 刷新摘要。
        chapter.content = revised
        chapter.word_count = len(revised)
        await refresh_chapter_memory(
            session=session,
            chapter=chapter,
            project_id=project.id,
            characters=characters,
            model=model_name,
        )
        await session.commit()

        # 重新审校。
        report = await review_chapter(
            content=revised,
            premise=premise,
            style=style or project.genre,
            characters=characters_text,
            entity_states=entity_states_text,
            recent_summaries="\n".join(recent_summaries),
            chapter_outline=chapter.outline,
            model=model_name,
        )
        review = ChapterReview(
            chapter_id=chapter_id,
            issues=report.get("issues", []),
            summary=report.get("summary", ""),
            ai_flavor_score=report.get("ai_flavor_score", 0),
            ai_flavor_hits=report.get("ai_flavor_hits", []),
            model=model_name,
        )
        session.add(review)
        await session.commit()
        return ReviseResult(
            content=revised,
            review=ChapterReviewOut(
                issues=report.get("issues", []),
                summary=report.get("summary", ""),
                ai_flavor_score=report.get("ai_flavor_score", 0),
                ai_flavor_hits=report.get("ai_flavor_hits", []),
                created_at=review.created_at,
            ),
        )
