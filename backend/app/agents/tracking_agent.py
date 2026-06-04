"""伏笔/支线追踪 Agent：根据章节正文给出追踪项状态建议。"""
from app.llm.claude_client import complete_json
from app.schemas import TrackingSuggestionResult, TrackingStallResult

TRACKING_SYSTEM_PROMPT = """你是一位长篇小说连续性编辑，负责判断伏笔、支线、资源线、情感线是否在当前章节中被推进或回收。

要求：
- 只根据当前章节正文和给定追踪项判断，不要编造正文中没有出现的证据。
- 如果章节只是轻微提及、制造新信息或推动调查，可建议 progressing。
- 如果章节明确揭示答案、兑现承诺、完成情感/资源/支线目标，可建议 resolved。
- 如果没有有效证据，suggested_status 返回 no_change。
- confidence 为 0-100，越高表示证据越直接。
- evidence 必须引用或概括本章里的具体证据。"""

_TRACKING_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "foreshadow_id": {"type": "string", "description": "追踪项 id"},
                    "title": {"type": "string", "description": "追踪项标题"},
                    "current_status": {
                        "type": "string",
                        "enum": ["open", "progressing", "resolved"],
                        "description": "当前状态",
                    },
                    "suggested_status": {
                        "type": "string",
                        "enum": ["no_change", "open", "progressing", "resolved"],
                        "description": "建议状态",
                    },
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "evidence": {"type": "string", "description": "本章证据"},
                    "rationale": {"type": "string", "description": "判断理由"},
                },
                "required": [
                    "foreshadow_id",
                    "current_status",
                    "suggested_status",
                    "confidence",
                    "evidence",
                    "rationale",
                ],
            },
        }
    },
    "required": ["suggestions"],
}


def _format_tracking_items(items: list[dict]) -> str:
    lines: list[str] = []
    for item in items:
        lines.append(
            f"- id={item.get('id')}；类型={item.get('kind')}；标题={item.get('title')}；"
            f"当前状态={item.get('status')}；引入位置={item.get('introduced_at')}；"
            f"描述={item.get('description')}；回收/推进计划={item.get('payoff')}"
        )
    return "\n".join(lines)


async def suggest_tracking_updates(
    content: str,
    chapter_title: str,
    chapter_outline: str,
    tracking_items: list[dict],
    model: str | None = None,
) -> TrackingSuggestionResult:
    if not content or not tracking_items:
        return TrackingSuggestionResult(suggestions=[])

    prompt = f"""【本章标题】
{chapter_title or "（未命名章节）"}

【本章大纲】
{chapter_outline or "（未提供）"}

【追踪项】
{_format_tracking_items(tracking_items)}

【本章正文】
{content}

请逐条判断追踪项在本章中是否被推进或回收。调用 save_tracking_suggestions 返回建议。"""
    data = await complete_json(
        system=TRACKING_SYSTEM_PROMPT,
        prompt=prompt,
        tool_name="save_tracking_suggestions",
        tool_schema=_TRACKING_TOOL_SCHEMA,
        max_tokens=3000,
        model=model,
    )
    return TrackingSuggestionResult.model_validate(data)


STALL_SYSTEM_PROMPT = """你是一位长篇小说连续性编辑，专门排查“被忘记的伏笔/支线/资源线/情感线”。

你会收到：
- 待排查追踪项：每条带类型、当前状态、引入位置、回收/推进计划，以及本地统计出的“已沉默章数”和“最后出现位置”。
- 正文卷章资料：章节标题、章纲、摘要、正文片段。

判断目标：
- 找出已经长时间没有推进、或从未在正文中真正落地、有被遗忘风险的线索。
- 区分“真的被忘了/需要尽快处理”和“故意压着、节奏上仍合理”。只对前者给出处理建议。
- risk 用 high / medium / low：high=主线级伏笔长期沉默或承诺未兑现；medium=支线/资源线停滞影响连续性；low=轻微、可缓。
- action 用 remind（找机会提及保温）/ advance（安排一次实质推进）/ resolve（已到该回收的时机）/ drop（建议删除或合并，已无价值）/ none（无需处理）。
- recommended_status 仅在确有把握时给：no_change / open / progressing / resolved；drop 或不确定时用 no_change。
- evidence 必须引用正文资料里的具体依据（或指出“正文中始终未出现”）。
- suggestion 给作者下一步可执行的动作，落到“在第几卷/哪一章附近做什么”，但不要替作者写正文。
- 不要为了凑数报告节奏上仍然合理的线索。"""

_STALL_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "foreshadow_id": {"type": "string", "description": "追踪项 id"},
                    "title": {"type": "string", "description": "追踪项标题"},
                    "kind": {"type": "string", "description": "追踪项类型"},
                    "current_status": {
                        "type": "string",
                        "enum": ["open", "progressing", "resolved"],
                        "description": "当前状态",
                    },
                    "risk": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "停滞风险",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["remind", "advance", "resolve", "drop", "none"],
                        "description": "建议处理动作",
                    },
                    "recommended_status": {
                        "type": "string",
                        "enum": ["no_change", "open", "progressing", "resolved"],
                        "description": "建议状态",
                    },
                    "evidence": {"type": "string", "description": "正文依据"},
                    "suggestion": {"type": "string", "description": "可执行的下一步"},
                },
                "required": [
                    "foreshadow_id",
                    "risk",
                    "action",
                    "recommended_status",
                    "evidence",
                    "suggestion",
                ],
            },
        }
    },
    "required": ["suggestions"],
}


def _format_stall_items(items: list[dict]) -> str:
    lines: list[str] = []
    for item in items:
        lines.append(
            f"- id={item.get('id')}；类型={item.get('kind')}；标题={item.get('title')}；"
            f"当前状态={item.get('status')}；引入位置={item.get('introduced_at')}；"
            f"已沉默章数={item.get('silent_chapters')}；最后出现={item.get('last_seen')}；"
            f"描述={item.get('description')}；回收/推进计划={item.get('payoff')}"
        )
    return "\n".join(lines)


async def scan_stalled_threads(
    tracking_items: list[dict],
    chapter_material: str,
    checked_chapters: int,
    total_chapters: int,
    model: str | None = None,
) -> TrackingStallResult:
    if not tracking_items:
        return TrackingStallResult(
            checked_threads=0,
            checked_chapters=checked_chapters,
            total_chapters=total_chapters,
            suggestions=[],
        )

    prompt = f"""【正文进度】共 {total_chapters} 章，已纳入排查 {checked_chapters} 章。

【待排查追踪项】
{_format_stall_items(tracking_items)}

【正文卷章资料】
{chapter_material or "（暂无正文）"}

请逐条判断哪些线索有被遗忘/停滞风险，并调用 save_stall_suggestions 返回处理建议。只报告真正需要处理的线索。"""
    data = await complete_json(
        system=STALL_SYSTEM_PROMPT,
        prompt=prompt,
        tool_name="save_stall_suggestions",
        tool_schema=_STALL_TOOL_SCHEMA,
        max_tokens=3500,
        model=model,
    )
    result = TrackingStallResult.model_validate(data)
    result.checked_threads = len(tracking_items)
    result.checked_chapters = checked_chapters
    result.total_chapters = total_chapters
    return result