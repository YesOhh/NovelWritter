"""长篇体检 API：一键整合伏笔/支线停滞检测与真相文件一致性检查。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.foreshadows import scan_project_tracking_stall
from app.api.truth_files import check_project_truth_files
from app.db import get_session
from app.models import Project
from app.schemas import (
    ProjectHealthRequest,
    ProjectHealthResult,
    TrackingStallRequest,
    TruthFileCheckRequest,
)

router = APIRouter(prefix="/api", tags=["health"])

# 真相矛盾按严重度扣分（一致性问题影响最大）。
_TRUTH_WEIGHT = {"high": 10, "medium": 5, "low": 2}
# 停滞线索按风险扣分（影响略小于硬性矛盾）。
_STALL_WEIGHT = {"high": 8, "medium": 4, "low": 2}


def _grade(score: int) -> str:
    if score >= 85:
        return "优秀"
    if score >= 70:
        return "良好"
    if score >= 50:
        return "需关注"
    return "偏弱"


@router.post("/projects/{project_id}/health-check", response_model=ProjectHealthResult)
async def run_project_health_check(
    project_id: str,
    body: ProjectHealthRequest,
    session: AsyncSession = Depends(get_session),
) -> ProjectHealthResult:
    """串行运行停滞检测 + 真相一致性检查，汇总为长篇健康评分与问题概览。"""
    if await session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    stall = await scan_project_tracking_stall(
        project_id,
        TrackingStallRequest(model=body.model, max_chapters=body.max_chapters),
        session,
    )
    truth = await check_project_truth_files(
        project_id,
        TruthFileCheckRequest(model=body.model, max_chapters=body.max_chapters),
        session,
    )

    # 仅把需要处理的停滞线索计入问题（action == "none" 视为健康）。
    stall_items = [s for s in stall.suggestions if s.action != "none"]
    truth_items = list(truth.issues)

    high = sum(1 for s in stall_items if s.risk == "high")
    high += sum(1 for i in truth_items if i.severity == "high")
    medium = sum(1 for s in stall_items if s.risk == "medium")
    medium += sum(1 for i in truth_items if i.severity == "medium")
    low = sum(1 for s in stall_items if s.risk == "low")
    low += sum(1 for i in truth_items if i.severity == "low")

    penalty = 0
    for s in stall_items:
        penalty += _STALL_WEIGHT.get(s.risk, 2)
    for i in truth_items:
        penalty += _TRUTH_WEIGHT.get(i.severity, 2)
    score = max(0, 100 - penalty)

    total = len(stall_items) + len(truth_items)
    if total == 0:
        summary = "未发现明显的停滞线索或真相矛盾，长篇一致性良好。"
    else:
        summary = (
            f"共发现 {total} 处需关注项："
            f"真相矛盾 {len(truth_items)} 处、停滞线索 {len(stall_items)} 处"
            f"（高风险 {high} 处）。"
        )

    return ProjectHealthResult(
        score=score,
        grade=_grade(score),
        summary=summary,
        total_issues=total,
        high_issues=high,
        medium_issues=medium,
        low_issues=low,
        stall=stall,
        truth=truth,
    )
