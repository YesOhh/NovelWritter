"""伏笔/支线追踪 API：结构化追踪项 + MemoryChunk 同步。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.memory.retriever import index_chunk
from app.models import Foreshadow, MemoryChunk, Project
from app.schemas import ForeshadowCreate, ForeshadowOut, ForeshadowUpdate

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