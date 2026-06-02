"""审校 Agent：对成稿章节做一致性检测，产出结构化问题报告（阶段 4）。

输入草稿 + Context Pack（设定/角色/实体状态/前情摘要），用 tool use 强制
返回 {issues:[...], summary}。检测设定矛盾、人设崩坏、情节漏洞、伏笔遗漏、文风偏移。
"""
from app.agents.style_rules import ai_flavor_score
from app.llm.claude_client import complete_json

REVIEWER_SYSTEM_PROMPT = """你是一位严谨的小说责任编辑，负责审校连贯性与设定一致性。
请基于提供的"故事设定 / 文风 / 角色卡 / 角色当前状态 / 前情摘要 / 本章大纲"，逐条核对本章正文，找出问题。

重点检测：
- contradiction（设定矛盾）：与世界观/已确立事实冲突。
- character（人设崩坏）：言行违背角色性格、动机或既定状态（如已死复活、能力凭空变化）。
- plot（情节漏洞）：逻辑断裂、因果不成立、与前情冲突。
- foreshadow（伏笔遗漏）：该呼应/推进的线索被忽略。
- style（文风偏移）：明显偏离要求的文风。
- ai_flavor（AI 味）：高频套话与情绪标签词（如“仿佛/似乎/不禁/嘴角/眼神/空气仿佛凝固”）、句式单调、过度总结与解释性旁白、“不是…而是…”等万能句式。

要求：
- 只报告真实、具体的问题，给出定位与可执行的修订建议；不要为凑数编造。
- 若整体连贯、无明显问题，issues 返回空数组，并在 summary 给出正面评价。
- severity 用 high / medium / low 客观分级。"""

_REVIEW_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["contradiction", "character", "plot", "foreshadow", "style", "ai_flavor", "other"],
                        "description": "问题类型",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "严重度",
                    },
                    "location": {"type": "string", "description": "问题在本章中的定位（引用片段或描述位置）"},
                    "description": {"type": "string", "description": "问题描述"},
                    "suggestion": {"type": "string", "description": "可执行的修订建议"},
                },
                "required": ["type", "severity", "description", "suggestion"],
            },
        },
        "summary": {"type": "string", "description": "对本章连贯性与质量的总体评价"},
    },
    "required": ["issues", "summary"],
}


async def review_chapter(
    content: str,
    premise: str = "",
    style: str = "",
    characters: str = "",
    entity_states: str = "",
    recent_summaries: str = "",
    chapter_outline: str = "",
    model: str | None = None,
) -> dict:
    """审校单章，返回 {issues:[...], summary}。"""
    if not content:
        return {"issues": [], "summary": "（无正文，跳过审校）", "ai_flavor_score": 0, "ai_flavor_hits": []}

    prompt = f"""【故事设定】
{premise or "（未提供）"}

【文风要求】
{style or "（未指定）"}

【角色卡】
{characters or "（未提供）"}

【角色当前状态】
{entity_states or "（暂无）"}

【前情摘要】
{recent_summaries or "（暂无）"}

【本章大纲】
{chapter_outline or "（未提供）"}

【本章正文】
{content}

请逐条核对，调用 save_review 返回一致性报告。"""

    data = await complete_json(
        system=REVIEWER_SYSTEM_PROMPT,
        prompt=prompt,
        tool_name="save_review",
        tool_schema=_REVIEW_TOOL_SCHEMA,
        max_tokens=3000,
        model=model,
    )
    issues = data.get("issues") or []
    flavor = ai_flavor_score(content)
    return {
        "issues": issues,
        "summary": data.get("summary", ""),
        "ai_flavor_score": flavor["score"],
        "ai_flavor_hits": flavor["hits"],
    }
