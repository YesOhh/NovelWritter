"""伏笔/支线追踪 Agent：根据章节正文给出追踪项状态建议。"""
from app.llm.claude_client import complete_json
from app.schemas import TrackingSuggestionResult

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