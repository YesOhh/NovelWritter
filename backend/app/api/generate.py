"""章节生成 API：通过 SSE 流式返回写作 Agent 的输出。"""
import json
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.reviewer_agent import review_chapter
from app.agents.reviser_agent import revise_chapter
from app.agents.writer_agent import write_chapter_from_context, write_chapter_stream
from app.config import settings
from app.db import AsyncSessionLocal
from app.memory import entity_tracker
from app.memory.retriever import index_chunk, retriever
from app.memory.summarizer import summarize_chapter
from app.models import (
    Chapter,
    ChapterReview,
    ChapterSummary,
    Character,
    MemoryChunk,
    Project,
    Volume,
)
from app.schemas import ChapterGenerateRequest, ChapterReviewOut, ReviseRequest, ReviseResult

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
        project = await session.get(Project, volume.project_id)

        char_result = await session.execute(
            select(Character).where(Character.project_id == project.id)
        )
        characters = list(char_result.scalars().all())

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
            session, [c.id for c in characters]
        )
        id_to_name = {c.id: c.name for c in characters}
        state_lines = []
        for cid, st in states.items():
            parts = [f"{k}={v}" for k, v in st.items() if v]
            if parts:
                state_lines.append(f"- {id_to_name.get(cid, '')}：{'；'.join(parts)}")
        entity_states_text = "\n".join(state_lines)

        premise = project.premise
        genre = project.genre
        project_id = project.id
        style = (project.style_guide or {}).get("style", "") if isinstance(project.style_guide, dict) else ""
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
                model=req.model,
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
                    # 1. 章节摘要 + 关键词
                    summ = await summarize_chapter(
                        title=chap.title, content=full, model=req.model
                    )
                    ms.add(
                        ChapterSummary(
                            chapter_id=chapter_id,
                            summary=summ.get("summary", ""),
                            keywords=summ.get("keywords", []),
                        )
                    )
                    # 2. 灌入检索片段
                    await index_chunk(
                        ms,
                        project_id=project_id,
                        source_type="chapter_summary",
                        source_id=chapter_id,
                        text=f"{chap.title}：{summ.get('summary', '')}",
                        keywords=summ.get("keywords", []),
                    )
                    # 3. 实体状态抽取
                    char_objs = []
                    for cid, cname in char_snapshot:
                        c = await ms.get(Character, cid)
                        if c:
                            char_objs.append(c)
                    await entity_tracker.extract_and_store(
                        ms, chapter_id, full, char_objs, model=req.model
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
                    model=req.model,
                )
                async with AsyncSessionLocal() as rs:
                    rs.add(
                        ChapterReview(
                            chapter_id=chapter_id,
                            issues=report.get("issues", []),
                            summary=report.get("summary", ""),
                            ai_flavor_score=report.get("ai_flavor_score", 0),
                            ai_flavor_hits=report.get("ai_flavor_hits", []),
                            model=req.model or settings.claude_model,
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
                        model=req.model,
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
                        cs_res = await us.execute(
                            select(ChapterSummary).where(
                                ChapterSummary.chapter_id == chapter_id
                            )
                        )
                        cs = cs_res.scalar_one_or_none()
                        if cs is not None:
                            new_summ = await summarize_chapter(
                                title=ch.title if ch else "", content=full, model=req.model
                            )
                            cs.summary = new_summ.get("summary", cs.summary)
                            cs.keywords = new_summ.get("keywords", cs.keywords)
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
                        model=req.model,
                    )
                    async with AsyncSessionLocal() as rs:
                        rs.add(
                            ChapterReview(
                                chapter_id=chapter_id,
                                issues=report.get("issues", []),
                                summary=report.get("summary", ""),
                                ai_flavor_score=report.get("ai_flavor_score", 0),
                                ai_flavor_hits=report.get("ai_flavor_hits", []),
                                model=req.model or settings.claude_model,
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
        states = await entity_tracker.current_states(session, [c.id for c in characters])
        id_to_name = {c.id: c.name for c in characters}
        state_lines = []
        for cid, st in states.items():
            parts = [f"{k}={v}" for k, v in st.items() if v]
            if parts:
                state_lines.append(f"- {id_to_name.get(cid, '')}：{'；'.join(parts)}")

        style = (project.style_guide or {}).get("style", "") if isinstance(project.style_guide, dict) else ""
        report = await review_chapter(
            content=chapter.content,
            premise=project.premise,
            style=style or project.genre,
            characters=_format_characters(characters),
            entity_states="\n".join(state_lines),
            recent_summaries="\n".join(recent_summaries),
            chapter_outline=chapter.outline,
            model=req.model,
        )
        review = ChapterReview(
            chapter_id=chapter_id,
            issues=report.get("issues", []),
            summary=report.get("summary", ""),
            ai_flavor_score=report.get("ai_flavor_score", 0),
            ai_flavor_hits=report.get("ai_flavor_hits", []),
            model=req.model or settings.claude_model,
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

        states = await entity_tracker.current_states(session, [c.id for c in characters])
        id_to_name = {c.id: c.name for c in characters}
        state_lines = []
        for cid, st in states.items():
            parts = [f"{k}={v}" for k, v in st.items() if v]
            if parts:
                state_lines.append(f"- {id_to_name.get(cid, '')}：{'；'.join(parts)}")
        entity_states_text = "\n".join(state_lines)

        style = (project.style_guide or {}).get("style", "") if isinstance(project.style_guide, dict) else ""
        characters_text = _format_characters(characters)

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
            premise=project.premise,
            style=style or project.genre,
            characters=characters_text,
            entity_states=entity_states_text,
            chapter_outline=chapter.outline,
            mode=req.mode,
            model=req.model,
        )

        # 回写正文 + 刷新摘要。
        chapter.content = revised
        chapter.word_count = len(revised)
        cs_res = await session.execute(
            select(ChapterSummary).where(ChapterSummary.chapter_id == chapter_id)
        )
        cs = cs_res.scalar_one_or_none()
        if cs is not None:
            new_summ = await summarize_chapter(
                title=chapter.title, content=revised, model=req.model
            )
            cs.summary = new_summ.get("summary", cs.summary)
            cs.keywords = new_summ.get("keywords", cs.keywords)
        await session.commit()

        # 重新审校。
        report = await review_chapter(
            content=revised,
            premise=project.premise,
            style=style or project.genre,
            characters=characters_text,
            entity_states=entity_states_text,
            recent_summaries="\n".join(recent_summaries),
            chapter_outline=chapter.outline,
            model=req.model,
        )
        review = ChapterReview(
            chapter_id=chapter_id,
            issues=report.get("issues", []),
            summary=report.get("summary", ""),
            ai_flavor_score=report.get("ai_flavor_score", 0),
            ai_flavor_hits=report.get("ai_flavor_hits", []),
            model=req.model or settings.claude_model,
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
