"""参考文本导入/拆书分析 API。"""
import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.reference_agent import analyze_reference_text
from app.agents.style_stats import (
    analyze_style_stats,
    extract_style_samples,
    format_style_samples_prompt,
    redact_names,
)
from app.db import get_session
from app.llm.model_resolver import resolve_project_model
from app.memory.chapter_memory import refresh_chapter_memory
from app.memory.retriever import index_chunk
from app.models import Chapter, Character, EntityState, Foreshadow, Project, Volume, WorldSetting
from app.schemas import (
    ReferenceAnalyzeRequest,
    ReferenceConflictItem,
    ReferenceAnalyzeResult,
    ReferenceChapterImportRequest,
    ReferenceChapterImportResult,
    ReferenceChapterTimelineItem,
    ReferenceSourceItem,
    ReferenceSourceRenameRequest,
)

router = APIRouter(prefix="/api", tags=["reference"])

_CHAPTER_HEADING_RE = re.compile(
    r"^\s*(第[零〇一二三四五六七八九十百千万两\d]+[章节回]\s*[^\n]{0,80}|Chapter\s+\d+[^\n]{0,80}|\d{1,4}[\.、]\s*[^\n]{1,80})\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _style_prompt(result: ReferenceAnalyzeResult) -> str:
    fp = result.style_fingerprint
    lines = [line for line in [
        f"总体风格：{fp.summary}",
        f"叙述视角：{fp.narrative_pov}",
        f"时态/叙事距离：{fp.tense}",
        f"句式节奏：{fp.sentence_rhythm}",
        f"用词倾向：{fp.diction}",
        f"对白特点：{fp.dialogue}",
        f"意象系统：{fp.imagery}",
        f"节奏推进：{fp.pacing}",
    ] if line.split("：", 1)[-1]]
    if fp.taboos:
        lines.append("避免：" + "；".join(fp.taboos))
    return "\n".join(lines)


def _style_stats_of(text: str) -> dict:
    return analyze_style_stats(text[:160000])


def _style_samples_of(text: str) -> list[dict]:
    return extract_style_samples(text[:160000])


def _merge_style_guide(
    project: Project,
    result: ReferenceAnalyzeResult | None = None,
    style_stats: dict | None = None,
    style_samples: list[dict] | None = None,
    redact: list[str] | None = None,
) -> None:
    existing_style = project.style_guide if isinstance(project.style_guide, dict) else {}
    next_style = {**existing_style}
    if result is not None:
        next_style["style"] = _style_prompt(result)
        next_style["style_fingerprint"] = result.style_fingerprint.model_dump()
    if style_stats:
        next_style["style_stats"] = style_stats
        next_style["style_stats_prompt"] = style_stats.get("prompt", "")
    if style_samples:
        names = [name for name in (redact or []) if (name or "").strip()]
        # 存储前先把样例里的原书专名匿名化，避免后续生成/展示泄露旧姓名。
        cleaned_samples = [
            {**sample, "text": redact_names(sample.get("text", ""), names)}
            for sample in style_samples
        ]
        next_style["style_samples"] = cleaned_samples
        next_style["style_samples_prompt"] = format_style_samples_prompt(cleaned_samples, names)
        if names:
            next_style["style_sample_names"] = sorted(set(names))
    project.style_guide = next_style


# 最多保留的拆书原文条数与单条字数上限。
_MAX_REFERENCE_SOURCES = 10
_MAX_REFERENCE_SOURCE_CHARS = 60000


def _store_reference_source(project: Project, text: str) -> None:
    """把本次拆书使用的原文保存到 style_guide，便于之后回看。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return
    existing_style = project.style_guide if isinstance(project.style_guide, dict) else {}
    next_style = {**existing_style}
    sources = list(next_style.get("reference_sources") or [])
    entry = {
        "id": str(uuid4()),
        "label": "",
        "text": cleaned[:_MAX_REFERENCE_SOURCE_CHARS],
        "char_count": len(cleaned),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    sources.insert(0, entry)
    next_style["reference_sources"] = sources[:_MAX_REFERENCE_SOURCES]
    project.style_guide = next_style



def _setting_text(setting: WorldSetting) -> str:
    category = f"[{setting.category}] " if setting.category else ""
    return f"设定 {category}{setting.key}：{setting.value}"


def _setting_keywords(setting: WorldSetting) -> list[str]:
    return [word for word in [setting.category, setting.key] if word]


def _thread_text(item: Foreshadow) -> str:
    return (
        f"{item.kind} {item.title}：{item.description}；状态：{item.status}；"
        f"引入位置：{item.introduced_at}；回收/推进计划：{item.payoff}"
    )


def _thread_keywords(item: Foreshadow) -> list[str]:
    return [word for word in [item.kind, item.status, item.title] if word]


def _norm(text: str) -> str:
    return " ".join((text or "").split()).strip().lower()


def _compact(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _profile_text(profile: dict) -> str:
    return "；".join(
        part for part in [
            f"性格：{profile.get('personality', '')}",
            f"动机：{profile.get('motivation', '')}",
            f"关系：{profile.get('relationships', '')}",
            f"外貌：{profile.get('appearance', '')}",
        ] if part.split("：", 1)[-1]
    )


def _character_text(character: Character) -> str:
    profile = character.profile or {}
    return _compact(f"{_profile_text(profile)}；弧光：{character.arc}")


def _incoming_character_text(item) -> str:
    return _compact(f"{_profile_text(item.profile.model_dump())}；弧光：{item.arc}")


def _foreshadow_text(item) -> str:
    return _compact(
        f"类型：{item.kind}；状态：{item.status}；引入：{item.introduced_at}；"
        f"说明：{item.description}；计划：{item.payoff}"
    )


def _conflict_status(existing: str, incoming: str) -> str:
    existing_norm = _norm(existing)
    incoming_norm = _norm(incoming)
    if not existing_norm or not incoming_norm:
        return "duplicate"
    if existing_norm == incoming_norm:
        return "duplicate"
    if existing_norm in incoming_norm or incoming_norm in existing_norm:
        return "duplicate"
    return "conflict"


def _split_reference_chapters(text: str, max_chapters: int) -> list[tuple[str, str]]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    matches = list(_CHAPTER_HEADING_RE.finditer(normalized))
    if not matches:
        return [("参考文本", normalized[:30000].strip())]

    chapters: list[tuple[str, str]] = []
    preface = normalized[:matches[0].start()].strip()
    if preface:
        chapters.append(("导入前言", preface[:30000].strip()))

    for index, match in enumerate(matches):
        if len(chapters) >= max_chapters:
            break
        title = " ".join(match.group(1).split()).strip() or f"参考章节 {index + 1}"
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        content = normalized[start:end].strip()
        if not content:
            continue
        chapters.append((title[:200], content[:30000]))
    return chapters[:max_chapters]


async def _timeline_item(
    session: AsyncSession,
    chapter: Chapter,
    characters: list[Character],
    summary: str,
    keywords: list[str],
) -> ReferenceChapterTimelineItem:
    states: dict[str, dict] = {}
    if characters:
        result = await session.execute(
            select(EntityState).where(EntityState.chapter_id == chapter.id)
        )
        id_to_name = {character.id: character.name for character in characters}
        for item in result.scalars().all():
            name = id_to_name.get(item.character_id)
            if name:
                states[name] = item.state or {}
    return ReferenceChapterTimelineItem(
        chapter_id=chapter.id,
        title=chapter.title,
        order_index=chapter.order_index,
        summary=summary,
        keywords=keywords,
        entity_states=states,
    )


@router.post("/projects/{project_id}/reference/analyze", response_model=ReferenceAnalyzeResult)
async def analyze_project_reference(
    project_id: str,
    body: ReferenceAnalyzeRequest,
    session: AsyncSession = Depends(get_session),
) -> ReferenceAnalyzeResult:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    style_stats = _style_stats_of(body.text)
    style_samples = _style_samples_of(body.text)
    result = await analyze_reference_text(body.text, model=resolve_project_model(project, body.model))
    result.style_stats = style_stats
    result.style_samples = style_samples
    existing_setting_res = await session.execute(
        select(WorldSetting).where(WorldSetting.project_id == project_id)
    )
    existing_settings = {
        (s.category.strip().lower(), s.key.strip().lower()): s
        for s in existing_setting_res.scalars().all()
    }

    existing_character_res = await session.execute(
        select(Character).where(Character.project_id == project_id)
    )
    existing_characters = {
        c.name.strip().lower(): c for c in existing_character_res.scalars().all()
    }

    existing_thread_res = await session.execute(
        select(Foreshadow).where(Foreshadow.project_id == project_id)
    )
    existing_threads = {
        f.title.strip().lower(): f for f in existing_thread_res.scalars().all()
    }

    conflicts: list[ReferenceConflictItem] = []
    for item in result.settings:
        key = item.key.strip()
        if not key:
            continue
        marker = (item.category.strip().lower(), key.lower())
        existing = existing_settings.get(marker)
        if not existing:
            continue
        status = _conflict_status(existing.value, item.value)
        conflicts.append(
            ReferenceConflictItem(
                kind="setting",
                name=f"{item.category} / {key}" if item.category.strip() else key,
                status=status,
                existing=_compact(existing.value),
                incoming=_compact(item.value),
                detail="同分类同设定名已存在，已跳过写入" if status == "duplicate" else "同分类同设定名已有不同内容，请人工确认",
            )
        )

    for item in result.characters:
        name = item.name.strip()
        if not name:
            continue
        existing = existing_characters.get(name.lower())
        if not existing:
            continue
        existing_text = _character_text(existing)
        incoming_text = _incoming_character_text(item)
        status = _conflict_status(existing_text, incoming_text)
        conflicts.append(
            ReferenceConflictItem(
                kind="character",
                name=name,
                status=status,
                existing=existing_text,
                incoming=incoming_text,
                detail="同名角色已存在，已跳过写入" if status == "duplicate" else "同名角色已有不同设定，请人工确认",
            )
        )

    for item in result.foreshadows:
        title = item.title.strip()
        if not title:
            continue
        existing = existing_threads.get(title.lower())
        if not existing:
            continue
        existing_text = _foreshadow_text(existing)
        incoming_text = _foreshadow_text(item)
        status = _conflict_status(existing_text, incoming_text)
        conflicts.append(
            ReferenceConflictItem(
                kind="foreshadow",
                name=title,
                status=status,
                existing=existing_text,
                incoming=incoming_text,
                detail="同名线索已存在，已跳过写入" if status == "duplicate" else "同名线索已有不同内容，请人工确认",
            )
        )

    result.conflicts = conflicts
    if not (body.apply_style or body.apply_resources):
        return result

    created_counts = {
        "settings": 0,
        "characters": 0,
        "foreshadows": 0,
        "style": 0,
        "duplicates": len([item for item in conflicts if item.status == "duplicate"]),
        "conflicts": len([item for item in conflicts if item.status == "conflict"]),
    }

    if body.apply_style:
        _merge_style_guide(
            project,
            result=result,
            style_stats=style_stats,
            style_samples=style_samples,
            redact=[item.name for item in result.characters if item.name.strip()],
        )
        created_counts["style"] = 1
    # 无论是学文风还是导入设定，都保留本次拆书原文以便回看。
    _store_reference_source(project, body.text)

    # 设定/角色/伏笔属于参考书自身内容，仅在用户明确选择“导入为本书正典”时才写入。
    settings_to_apply = result.settings if body.apply_resources else []
    characters_to_apply = result.characters if body.apply_resources else []
    foreshadows_to_apply = result.foreshadows if body.apply_resources else []

    for item in settings_to_apply:
        key = item.key.strip()
        if not key:
            continue
        marker = (item.category.strip().lower(), key.lower())
        if marker in existing_settings:
            continue
        setting = WorldSetting(
            project_id=project_id,
            category=item.category.strip(),
            key=key,
            value=item.value.strip(),
        )
        session.add(setting)
        await session.flush()
        await index_chunk(
            session,
            project_id=project_id,
            source_type="setting",
            source_id=setting.id,
            text=_setting_text(setting),
            keywords=_setting_keywords(setting),
        )
        existing_settings[marker] = setting
        created_counts["settings"] += 1

    for item in characters_to_apply:
        name = item.name.strip()
        if not name or name.lower() in existing_characters:
            continue
        character = Character(
            project_id=project_id,
            name=name,
            profile=item.profile.model_dump(),
            arc=item.arc.strip(),
        )
        session.add(character)
        await session.flush()
        p = character.profile or {}
        await index_chunk(
            session,
            project_id=project_id,
            source_type="character",
            source_id=character.id,
            text=f"角色 {character.name}：{p.get('personality', '')} 动机:{p.get('motivation', '')} 关系:{p.get('relationships', '')} 弧光:{character.arc}",
            keywords=[character.name],
        )
        existing_characters[name.lower()] = character
        created_counts["characters"] += 1

    for item in foreshadows_to_apply:
        title = item.title.strip()
        if not title or title.lower() in existing_threads:
            continue
        thread = Foreshadow(
            project_id=project_id,
            kind=item.kind or "foreshadow",
            title=title,
            description=item.description.strip(),
            status=item.status or "open",
            introduced_at=item.introduced_at.strip(),
            payoff=item.payoff.strip(),
        )
        session.add(thread)
        await session.flush()
        await index_chunk(
            session,
            project_id=project_id,
            source_type="foreshadow",
            source_id=thread.id,
            text=_thread_text(thread),
            keywords=_thread_keywords(thread),
        )
        existing_threads[title.lower()] = thread
        created_counts["foreshadows"] += 1

    await session.commit()
    result.applied = body.apply_resources
    result.created_counts = created_counts
    return result


def _reference_sources_list(project: Project) -> list[dict]:
    style = project.style_guide if isinstance(project.style_guide, dict) else {}
    sources = style.get("reference_sources")
    return list(sources) if isinstance(sources, list) else []


def _to_source_item(entry: dict) -> ReferenceSourceItem:
    return ReferenceSourceItem(
        id=str(entry.get("id", "")),
        label=str(entry.get("label", "")),
        text=str(entry.get("text", "")),
        char_count=int(entry.get("char_count", 0) or 0),
        created_at=str(entry.get("created_at", "")),
    )


@router.get(
    "/projects/{project_id}/reference/sources",
    response_model=list[ReferenceSourceItem],
)
async def list_reference_sources(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[ReferenceSourceItem]:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return [_to_source_item(item) for item in _reference_sources_list(project)]


@router.patch(
    "/projects/{project_id}/reference/sources/{source_id}",
    response_model=ReferenceSourceItem,
)
async def rename_reference_source(
    project_id: str,
    source_id: str,
    body: ReferenceSourceRenameRequest,
    session: AsyncSession = Depends(get_session),
) -> ReferenceSourceItem:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    style = project.style_guide if isinstance(project.style_guide, dict) else {}
    next_style = {**style}
    sources = list(next_style.get("reference_sources") or [])
    target: dict | None = None
    updated: list[dict] = []
    for item in sources:
        if isinstance(item, dict) and str(item.get("id", "")) == source_id:
            target = {**item, "label": body.label.strip()}
            updated.append(target)
        else:
            updated.append(item)
    if target is None:
        raise HTTPException(status_code=404, detail="拆书原文记录不存在")
    next_style["reference_sources"] = updated
    project.style_guide = next_style
    await session.commit()
    return _to_source_item(target)


@router.delete(
    "/projects/{project_id}/reference/sources/{source_id}",
    status_code=204,
)
async def delete_reference_source(
    project_id: str,
    source_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    style = project.style_guide if isinstance(project.style_guide, dict) else {}
    next_style = {**style}
    sources = list(next_style.get("reference_sources") or [])
    remaining = [
        item
        for item in sources
        if not (isinstance(item, dict) and str(item.get("id", "")) == source_id)
    ]
    if len(remaining) == len(sources):
        raise HTTPException(status_code=404, detail="拆书原文记录不存在")
    next_style["reference_sources"] = remaining
    project.style_guide = next_style
    await session.commit()


@router.post("/projects/{project_id}/reference/chapters/import", response_model=ReferenceChapterImportResult)
async def import_project_reference_chapters(
    project_id: str,
    body: ReferenceChapterImportRequest,
    session: AsyncSession = Depends(get_session),
) -> ReferenceChapterImportResult:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    chunks = _split_reference_chapters(body.text, body.max_chapters)
    if not chunks:
        raise HTTPException(status_code=400, detail="未识别到可导入的章节内容")
    style_stats = _style_stats_of(body.text)
    style_samples = _style_samples_of(body.text)

    result = await session.execute(select(Volume).where(Volume.project_id == project_id))
    existing_volumes = list(result.scalars().all())
    volume_offset = max((volume.order_index for volume in existing_volumes), default=-1) + 1
    volume_title = body.volume_title.strip() or "参考拆书"
    volume = Volume(
        project_id=project_id,
        order_index=volume_offset,
        kind="reference",
        title=volume_title,
        outline="由参考文本分章导入，用于续写前情、实体状态和检索召回。",
    )
    session.add(volume)
    await session.flush()

    imported: list[Chapter] = []
    for index, (title, content) in enumerate(chunks):
        chapter = Chapter(
            volume_id=volume.id,
            order_index=index,
            title=title,
            outline=f"参考导入章节：{title}",
            content=content,
            status="drafted",
            word_count=len(content),
        )
        session.add(chapter)
        await session.flush()
        imported.append(chapter)

    char_result = await session.execute(select(Character).where(Character.project_id == project_id))
    characters = list(char_result.scalars().all())
    model_name = resolve_project_model(project, body.model)
    timeline: list[ReferenceChapterTimelineItem] = []
    if body.refresh_memory:
        for chapter in imported:
            memory = await refresh_chapter_memory(
                session=session,
                chapter=chapter,
                project_id=project_id,
                characters=characters,
                model=model_name,
            )
            timeline.append(
                await _timeline_item(
                    session=session,
                    chapter=chapter,
                    characters=characters,
                    summary=memory.get("summary", ""),
                    keywords=memory.get("keywords", []),
                )
            )
    else:
        for chapter in imported:
            await index_chunk(
                session,
                project_id=project_id,
                source_type="chapter_summary",
                source_id=chapter.id,
                text=f"{chapter.title}：{chapter.outline}",
                keywords=[chapter.title],
            )
            timeline.append(
                ReferenceChapterTimelineItem(
                    chapter_id=chapter.id,
                    title=chapter.title,
                    order_index=chapter.order_index,
                    keywords=[chapter.title],
                )
            )

    _merge_style_guide(project, style_stats=style_stats, style_samples=style_samples)
    await session.commit()
    return ReferenceChapterImportResult(
        volume_id=volume.id,
        volume_title=volume.title,
        imported_chapters=len(imported),
        timeline=timeline,
        style_stats=style_stats,
        style_samples=style_samples,
    )