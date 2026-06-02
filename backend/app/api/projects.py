"""项目 API：CRUD + 触发角色/大纲 Agent 生成并落库。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.character_agent import generate_characters
from app.agents.outline_agent import generate_outline
from app.db import get_session
from app.memory.retriever import index_chunk
from app.models import Chapter, Character, Project, Volume
from app.schemas import (
    CharacterGenerateRequest,
    CharacterOut,
    OutlineGenerateRequest,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    VolumeOut,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _get_project_or_404(session: AsyncSession, project_id: str) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate, session: AsyncSession = Depends(get_session)
) -> Project:
    project = Project(**body.model_dump())
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(session: AsyncSession = Depends(get_session)) -> list[Project]:
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> Project:
    result = await session.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.volumes)
            .selectinload(Volume.chapters)
            .selectinload(Chapter.summary_row),
            selectinload(Project.volumes)
            .selectinload(Volume.chapters)
            .selectinload(Chapter.reviews),
            selectinload(Project.characters),
            selectinload(Project.settings),
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    project = await _get_project_or_404(session, project_id)
    await session.delete(project)
    await session.commit()


@router.post("/{project_id}/characters/generate", response_model=list[CharacterOut])
async def generate_project_characters(
    project_id: str,
    body: CharacterGenerateRequest,
    session: AsyncSession = Depends(get_session),
) -> list[Character]:
    project = await _get_project_or_404(session, project_id)
    result = await generate_characters(
        premise=project.premise, genre=project.genre, count=body.count, model=body.model
    )
    created: list[Character] = []
    for item in result.characters:
        character = Character(
            project_id=project.id,
            name=item.name,
            profile=item.profile.model_dump(),
            arc=item.arc,
        )
        session.add(character)
        created.append(character)
    await session.commit()
    for c in created:
        await session.refresh(c)
        # 灌入检索片段，让 RAG 一开始就能召回角色设定。
        p = c.profile or {}
        await index_chunk(
            session,
            project_id=project.id,
            source_type="character",
            source_id=c.id,
            text=f"角色 {c.name}：{p.get('personality', '')} 动机:{p.get('motivation', '')} 关系:{p.get('relationships', '')} 弧光:{c.arc}",
            keywords=[c.name],
        )
    await session.commit()
    return created


@router.post("/{project_id}/outline/generate", response_model=list[VolumeOut])
async def generate_project_outline(
    project_id: str,
    body: OutlineGenerateRequest,
    session: AsyncSession = Depends(get_session),
) -> list[Volume]:
    project = await _get_project_or_404(session, project_id)
    style = (project.style_guide or {}).get("style", "") if isinstance(project.style_guide, dict) else ""
    result = await generate_outline(
        premise=project.premise,
        genre=project.genre,
        style=style,
        volume_count=body.volume_count,
        chapters_per_volume=body.chapters_per_volume,
        model=body.model,
    )
    created: list[Volume] = []
    for v_idx, v in enumerate(result.volumes):
        volume = Volume(
            project_id=project.id, order_index=v_idx, title=v.title, outline=v.outline
        )
        for c_idx, ch in enumerate(v.chapters):
            volume.chapters.append(
                Chapter(order_index=c_idx, title=ch.title, outline=ch.outline, status="outlined")
            )
        session.add(volume)
        created.append(volume)
    await session.commit()

    # 灌入卷大纲为检索片段（含项目设定关键词），让 RAG 召回背景。
    for v in created:
        await index_chunk(
            session,
            project_id=project.id,
            source_type="volume_outline",
            source_id=v.id,
            text=f"{v.title}：{v.outline}",
            keywords=[v.title],
        )
    await session.commit()

    # 重新查询以带出 chapters 关系，供响应序列化。
    result_q = await session.execute(
        select(Volume)
        .where(Volume.project_id == project.id)
        .options(selectinload(Volume.chapters).selectinload(Chapter.summary_row))
        .order_by(Volume.order_index)
    )
    return list(result_q.scalars().all())
