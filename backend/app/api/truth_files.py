"""长篇真相文件 API：长期约束、资源账本、情感弧线与隐藏事实。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.truth_check_agent import check_truth_file_consistency
from app.db import get_session
from app.llm.model_resolver import resolve_project_model
from app.memory.retriever import index_chunk
from app.models import Chapter, ChapterSummary, Character, MemoryChunk, Project, TruthFile, Volume, WorldSetting
from app.schemas import (
    TruthFileCheckRequest,
    TruthFileCheckResult,
    TruthFileCreate,
    TruthFileOut,
    TruthFileUpdate,
    TruthMaintenanceLogCreate,
    TruthMaintenanceLogEntry,
)

router = APIRouter(prefix="/api", tags=["truth-files"])

_KIND_LABELS = {
    "constraint": "硬约束",
    "resource": "资源账本",
    "relationship": "情感弧线",
    "secret": "隐藏真相",
    "timeline": "长期时间线",
}

_STATUS_LABELS = {
    "active": "生效中",
    "draft": "草稿",
    "resolved": "已兑现",
    "archived": "归档",
}


def _truth_text(item: TruthFile) -> str:
    kind = _KIND_LABELS.get(item.kind, item.kind or "真相文件")
    status = _STATUS_LABELS.get(item.status, item.status or "active")
    parts = [f"{kind} {item.title}：{item.content}", f"状态：{status}"]
    if item.scope:
        parts.append(f"适用范围：{item.scope}")
    if item.owner:
        parts.append(f"相关对象：{item.owner}")
    return "；".join(parts)


def _truth_keywords(item: TruthFile) -> list[str]:
    return [word for word in [item.kind, item.status, item.title, item.scope, item.owner] if word]


def _compact_text(text: str, limit: int = 900) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    head = value[: limit // 2].rstrip()
    tail = value[-limit // 2 :].lstrip()
    return f"{head} …… {tail}"


def _truth_check_text(items: list[TruthFile]) -> str:
    lines: list[str] = []
    for item in items:
        lines.append(
            "；".join(
                [
                    f"id={item.id}",
                    f"类型={_KIND_LABELS.get(item.kind, item.kind)}",
                    f"状态={_STATUS_LABELS.get(item.status, item.status)}",
                    f"标题={item.title}",
                    f"范围={item.scope}",
                    f"相关={item.owner}",
                    f"内容={_compact_text(item.content, 700)}",
                ]
            )
        )
    return "\n".join(lines)


async def _truth_check_material(
    session: AsyncSession,
    project: Project,
    truth_files: list[TruthFile],
    max_chapters: int,
) -> tuple[str, int]:
    parts: list[str] = [f"【项目】{project.title}；题材={project.genre}；一句话设定={project.premise}"]

    setting_result = await session.execute(
        select(WorldSetting).where(WorldSetting.project_id == project.id).order_by(WorldSetting.category, WorldSetting.key)
    )
    settings = list(setting_result.scalars().all())
    if settings:
        parts.append("【设定】")
        for setting in settings:
            label = f"{setting.category}/{setting.key}" if setting.category else setting.key
            parts.append(f"source_type=setting；source_id={setting.id}；标题={label}；内容={_compact_text(setting.value, 600)}")

    character_result = await session.execute(
        select(Character).where(Character.project_id == project.id).order_by(Character.name)
    )
    characters = list(character_result.scalars().all())
    if characters:
        parts.append("【角色】")
        for character in characters:
            profile = character.profile or {}
            profile_text = "；".join(f"{key}={value}" for key, value in profile.items() if value)
            parts.append(
                f"source_type=character；source_id={character.id}；标题={character.name}；"
                f"资料={_compact_text(profile_text, 500)}；弧光={_compact_text(character.arc, 300)}"
            )

    other_truths = [item for item in truth_files if item.status != "archived"]
    if other_truths:
        parts.append("【真相文件互检资料】")
        for item in other_truths:
            parts.append(
                f"source_type=truth_file；source_id={item.id}；标题={item.title}；"
                f"内容={_compact_text(item.content, 500)}；状态={item.status}；范围={item.scope}；相关={item.owner}"
            )

    chapter_result = await session.execute(
        select(Chapter, Volume)
        .join(Volume, Chapter.volume_id == Volume.id)
        .where(Volume.project_id == project.id, Volume.kind == "novel")
        .order_by(Volume.order_index, Chapter.order_index)
        .limit(max_chapters)
    )
    chapter_rows = list(chapter_result.all())
    chapter_ids = [chapter.id for chapter, _ in chapter_rows]
    summaries_by_chapter: dict[str, ChapterSummary] = {}
    if chapter_ids:
        summary_result = await session.execute(
            select(ChapterSummary).where(ChapterSummary.chapter_id.in_(chapter_ids))
        )
        summaries_by_chapter = {summary.chapter_id: summary for summary in summary_result.scalars().all()}

    if chapter_rows:
        parts.append("【正文卷章】")
        for chapter, volume in chapter_rows:
            summary = summaries_by_chapter.get(chapter.id)
            content = chapter.content or ""
            chapter_text = content if content.strip() else chapter.outline
            parts.append(
                f"source_type=chapter；source_id={chapter.id}；标题=第{volume.order_index + 1}卷/{chapter.title}；"
                f"章纲={_compact_text(chapter.outline, 400)}；"
                f"摘要={_compact_text(summary.summary if summary else '', 500)}；"
                f"正文片段={_compact_text(chapter_text, 900)}"
            )

    return "\n".join(parts), len(chapter_rows)


async def _sync_truth_chunk(session: AsyncSession, item: TruthFile) -> None:
    chunk_res = await session.execute(
        select(MemoryChunk).where(
            MemoryChunk.source_type == "truth_file",
            MemoryChunk.source_id == item.id,
        )
    )
    chunk = chunk_res.scalar_one_or_none()
    if chunk is None:
        await index_chunk(
            session,
            project_id=item.project_id,
            source_type="truth_file",
            source_id=item.id,
            text=_truth_text(item),
            keywords=_truth_keywords(item),
        )
    else:
        chunk.text = _truth_text(item)
        chunk.keywords = _truth_keywords(item)


@router.get("/projects/{project_id}/truth-files", response_model=list[TruthFileOut])
async def list_truth_files(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> list[TruthFile]:
    result = await session.execute(
        select(TruthFile)
        .where(TruthFile.project_id == project_id)
        .order_by(TruthFile.created_at)
    )
    return list(result.scalars().all())


@router.post("/projects/{project_id}/truth-files", response_model=TruthFileOut, status_code=201)
async def create_truth_file(
    project_id: str,
    body: TruthFileCreate,
    session: AsyncSession = Depends(get_session),
) -> TruthFile:
    if await session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    item = TruthFile(project_id=project_id, **body.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    await _sync_truth_chunk(session, item)
    await session.commit()
    return item


@router.post("/projects/{project_id}/truth-files/check", response_model=TruthFileCheckResult)
async def check_project_truth_files(
    project_id: str,
    body: TruthFileCheckRequest,
    session: AsyncSession = Depends(get_session),
) -> TruthFileCheckResult:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    truth_result = await session.execute(
        select(TruthFile)
        .where(TruthFile.project_id == project_id, TruthFile.status != "archived")
        .order_by(TruthFile.created_at)
    )
    truth_files = list(truth_result.scalars().all())
    material, checked_chapters = await _truth_check_material(
        session,
        project,
        truth_files,
        body.max_chapters,
    )
    return await check_truth_file_consistency(
        truth_files=_truth_check_text(truth_files),
        project_material=material,
        checked_truth_files=len(truth_files),
        checked_chapters=checked_chapters,
        model=resolve_project_model(project, body.model),
    )


@router.post("/projects/{project_id}/truth-files/maintenance-log", response_model=list[TruthMaintenanceLogEntry])
async def append_truth_maintenance_log(
    project_id: str,
    body: TruthMaintenanceLogCreate,
    session: AsyncSession = Depends(get_session),
) -> list[TruthMaintenanceLogEntry]:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    style_guide = project.style_guide if isinstance(project.style_guide, dict) else {}
    existing = style_guide.get("truth_maintenance_log")
    log_items = existing if isinstance(existing, list) else []
    now = datetime.now(timezone.utc).isoformat()
    incoming: list[dict] = []
    for entry in body.entries[:20]:
        item = entry.model_dump()
        item["created_at"] = now
        incoming.append(item)
    next_log = (incoming + log_items)[:50]
    project.style_guide = {**style_guide, "truth_maintenance_log": next_log}
    await session.commit()
    return [TruthMaintenanceLogEntry.model_validate(item) for item in next_log]


@router.put("/truth-files/{truth_file_id}", response_model=TruthFileOut)
async def update_truth_file(
    truth_file_id: str,
    body: TruthFileUpdate,
    session: AsyncSession = Depends(get_session),
) -> TruthFile:
    item = await session.get(TruthFile, truth_file_id)
    if item is None:
        raise HTTPException(status_code=404, detail="真相文件不存在")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(item, field, value)
    item.updated_at = datetime.now(timezone.utc)
    await _sync_truth_chunk(session, item)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/truth-files/{truth_file_id}", status_code=204)
async def delete_truth_file(
    truth_file_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    item = await session.get(TruthFile, truth_file_id)
    if item is None:
        raise HTTPException(status_code=404, detail="真相文件不存在")
    await session.execute(
        delete(MemoryChunk).where(
            MemoryChunk.source_type == "truth_file",
            MemoryChunk.source_id == item.id,
        )
    )
    await session.delete(item)
    await session.commit()