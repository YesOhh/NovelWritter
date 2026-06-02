"""世界观设定 API：WorldSetting 的增删改查。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Project, WorldSetting
from app.schemas import WorldSettingCreate, WorldSettingOut, WorldSettingUpdate

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/projects/{project_id}/settings", response_model=list[WorldSettingOut])
async def list_settings(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> list[WorldSetting]:
    result = await session.execute(
        select(WorldSetting).where(WorldSetting.project_id == project_id)
    )
    return list(result.scalars().all())


@router.post("/projects/{project_id}/settings", response_model=WorldSettingOut, status_code=201)
async def create_setting(
    project_id: str,
    body: WorldSettingCreate,
    session: AsyncSession = Depends(get_session),
) -> WorldSetting:
    if await session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    setting = WorldSetting(project_id=project_id, **body.model_dump())
    session.add(setting)
    await session.commit()
    await session.refresh(setting)
    return setting


@router.put("/settings/{setting_id}", response_model=WorldSettingOut)
async def update_setting(
    setting_id: str,
    body: WorldSettingUpdate,
    session: AsyncSession = Depends(get_session),
) -> WorldSetting:
    setting = await session.get(WorldSetting, setting_id)
    if setting is None:
        raise HTTPException(status_code=404, detail="设定不存在")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(setting, field, value)
    await session.commit()
    await session.refresh(setting)
    return setting


@router.delete("/settings/{setting_id}", status_code=204)
async def delete_setting(
    setting_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    setting = await session.get(WorldSetting, setting_id)
    if setting is None:
        raise HTTPException(status_code=404, detail="设定不存在")
    await session.delete(setting)
    await session.commit()
