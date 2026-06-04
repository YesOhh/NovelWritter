"""伏笔/支线追踪 API：结构化追踪项 + MemoryChunk 同步。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tracking_agent import scan_stalled_threads
from app.db import get_session
from app.llm.model_resolver import resolve_project_model
from app.memory.retriever import index_chunk
from app.models import (
    Chapter,
    ChapterSummary,
    Foreshadow,
    MemoryChunk,
    Project,
    Volume,
)
from app.schemas import (
    ForeshadowCreate,
    ForeshadowOut,
    ForeshadowUpdate,
    TrackingBatchStatusRequest,
    TrackingStallRequest,
    TrackingStallResult,
)

router = APIRouter(prefix="/api", tags=["foreshadows"])

_KIND_LABELS = {
    "foreshadow": "伏笔",
    "subplot": "支线",
    "resource": "资源线",
    "relationship": "情感线",
}

_STATUS_LABELS = {
    "open": "待回收",
    "progressing": "推进中",
    "resolved": "已回收",
}


def _thread_text(item: Foreshadow) -> str:
    kind = _KIND_LABELS.get(item.kind, item.kind or "线索")
    status = _STATUS_LABELS.get(item.status, item.status or "open")
    parts = [f"{kind} {item.title}：{item.description}", f"状态：{status}"]
    if item.introduced_at:
        parts.append(f"引入位置：{item.introduced_at}")
    if item.payoff:
        parts.append(f"回收/推进计划：{item.payoff}")
    return "；".join(parts)


def _thread_keywords(item: Foreshadow) -> list[str]:
    return [word for word in [item.kind, item.status, item.title] if word]


@router.get("/projects/{project_id}/foreshadows", response_model=list[ForeshadowOut])
async def list_foreshadows(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> list[Foreshadow]:
    result = await session.execute(
        select(Foreshadow)
        .where(Foreshadow.project_id == project_id)
        .order_by(Foreshadow.created_at)
    )
    return list(result.scalars().all())


@router.post("/projects/{project_id}/foreshadows", response_model=ForeshadowOut, status_code=201)
async def create_foreshadow(
    project_id: str,
    body: ForeshadowCreate,
    session: AsyncSession = Depends(get_session),
) -> Foreshadow:
    if await session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    item = Foreshadow(project_id=project_id, **body.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    await index_chunk(
        session,
        project_id=project_id,
        source_type="foreshadow",
        source_id=item.id,
        text=_thread_text(item),
        keywords=_thread_keywords(item),
    )
    await session.commit()
    return item


@router.put("/foreshadows/{foreshadow_id}", response_model=ForeshadowOut)
async def update_foreshadow(
    foreshadow_id: str,
    body: ForeshadowUpdate,
    session: AsyncSession = Depends(get_session),
) -> Foreshadow:
    item = await session.get(Foreshadow, foreshadow_id)
    if item is None:
        raise HTTPException(status_code=404, detail="追踪项不存在")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(item, field, value)

    chunk_res = await session.execute(
        select(MemoryChunk).where(
            MemoryChunk.source_type == "foreshadow",
            MemoryChunk.source_id == item.id,
        )
    )
    chunk = chunk_res.scalar_one_or_none()
    if chunk is None:
        await index_chunk(
            session,
            project_id=item.project_id,
            source_type="foreshadow",
            source_id=item.id,
            text=_thread_text(item),
            keywords=_thread_keywords(item),
        )
    else:
        chunk.text = _thread_text(item)
        chunk.keywords = _thread_keywords(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/foreshadows/{foreshadow_id}", status_code=204)
async def delete_foreshadow(
    foreshadow_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    item = await session.get(Foreshadow, foreshadow_id)
    if item is None:
        raise HTTPException(status_code=404, detail="追踪项不存在")
    await session.execute(
        delete(MemoryChunk).where(
            MemoryChunk.source_type == "foreshadow",
            MemoryChunk.source_id == item.id,
        )
    )
    await session.delete(item)
    await session.commit()


def _compact(text: str, limit: int = 600) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


async def _ordered_novel_chapters(
    session: AsyncSession, project_id: str, max_chapters: int
) -> list[tuple[Chapter, Volume]]:
    result = await session.execute(
        select(Chapter, Volume)
        .join(Volume, Chapter.volume_id == Volume.id)
        .where(Volume.project_id == project_id, Volume.kind == "novel")
        .order_by(Volume.order_index, Chapter.order_index)
        .limit(max_chapters)
    )
    return list(result.all())


@router.post(
    "/projects/{project_id}/tracking/stall-scan",
    response_model=TrackingStallResult,
)
async def scan_project_tracking_stall(
    project_id: str,
    body: TrackingStallRequest,
    session: AsyncSession = Depends(get_session),
) -> TrackingStallResult:
    """跨章排查未回收线索：本地统计沉默章数 + LLM 判定停滞风险与处理建议。"""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    thread_result = await session.execute(
        select(Foreshadow)
        .where(Foreshadow.project_id == project_id, Foreshadow.status != "resolved")
        .order_by(Foreshadow.created_at)
    )
    threads = list(thread_result.scalars().all())
    if not threads:
        return TrackingStallResult(checked_threads=0, checked_chapters=0, total_chapters=0)

    chapter_rows = await _ordered_novel_chapters(session, project_id, body.max_chapters)
    total_chapters = len(chapter_rows)
    chapter_ids = [chapter.id for chapter, _ in chapter_rows]
    summaries: dict[str, ChapterSummary] = {}
    if chapter_ids:
        summary_result = await session.execute(
            select(ChapterSummary).where(ChapterSummary.chapter_id.in_(chapter_ids))
        )
        summaries = {s.chapter_id: s for s in summary_result.scalars().all()}

    # 本地沉默统计：找出每条线索最后一次在卷章中命中的位置。
    haystacks: list[str] = []
    for chapter, volume in chapter_rows:
        summary = summaries.get(chapter.id)
        haystacks.append(
            "\n".join(
                [
                    chapter.title or "",
                    chapter.outline or "",
                    summary.summary if summary else "",
                    chapter.content or "",
                ]
            ).lower()
        )

    payload: list[dict] = []
    for item in threads:
        needle = item.title.strip().lower()
        last_index = -1
        if needle:
            for idx, hay in enumerate(haystacks):
                if needle in hay:
                    last_index = idx
        silent = total_chapters - last_index - 1 if last_index >= 0 else total_chapters
        if last_index >= 0:
            chapter, volume = chapter_rows[last_index]
            last_seen = f"第{volume.order_index + 1}卷/{chapter.title}"
        else:
            last_seen = "正文中未出现"
        payload.append(
            {
                "id": item.id,
                "kind": item.kind,
                "title": item.title,
                "status": item.status,
                "introduced_at": item.introduced_at,
                "description": item.description,
                "payoff": item.payoff,
                "silent_chapters": silent,
                "last_seen": last_seen,
            }
        )

    material_parts: list[str] = []
    for chapter, volume in chapter_rows:
        summary = summaries.get(chapter.id)
        content = chapter.content or ""
        body_text = content if content.strip() else chapter.outline
        material_parts.append(
            f"第{volume.order_index + 1}卷/{chapter.title}："
            f"章纲={_compact(chapter.outline, 300)}；"
            f"摘要={_compact(summary.summary if summary else '', 400)}；"
            f"正文片段={_compact(body_text, 600)}"
        )

    result = await scan_stalled_threads(
        tracking_items=payload,
        chapter_material="\n".join(material_parts),
        checked_chapters=total_chapters,
        total_chapters=total_chapters,
        model=resolve_project_model(project, body.model),
    )

    # 回填本地统计字段（LLM 不负责沉默章数/最后出现位置/类型/当前状态）。
    metrics = {item["id"]: item for item in payload}
    for suggestion in result.suggestions:
        meta = metrics.get(suggestion.foreshadow_id)
        if meta:
            suggestion.silent_chapters = meta["silent_chapters"]
            suggestion.last_seen = meta["last_seen"]
            suggestion.kind = meta["kind"]
            suggestion.current_status = meta["status"]
            if not suggestion.title:
                suggestion.title = meta["title"]
    return result


@router.post(
    "/projects/{project_id}/tracking/batch-status",
    response_model=list[ForeshadowOut],
)
async def batch_update_tracking_status(
    project_id: str,
    body: TrackingBatchStatusRequest,
    session: AsyncSession = Depends(get_session),
) -> list[Foreshadow]:
    """批量应用追踪项状态建议，并同步 MemoryChunk。"""
    if await session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    allowed = {"open", "progressing", "resolved"}
    updated: list[Foreshadow] = []
    for entry in body.items[:50]:
        if entry.status not in allowed:
            continue
        item = await session.get(Foreshadow, entry.foreshadow_id)
        if item is None or item.project_id != project_id:
            continue
        item.status = entry.status
        chunk_res = await session.execute(
            select(MemoryChunk).where(
                MemoryChunk.source_type == "foreshadow",
                MemoryChunk.source_id == item.id,
            )
        )
        chunk = chunk_res.scalar_one_or_none()
        if chunk is None:
            await index_chunk(
                session,
                project_id=item.project_id,
                source_type="foreshadow",
                source_id=item.id,
                text=_thread_text(item),
                keywords=_thread_keywords(item),
            )
        else:
            chunk.text = _thread_text(item)
            chunk.keywords = _thread_keywords(item)
        updated.append(item)
    await session.commit()
    for item in updated:
        await session.refresh(item)
    return updated