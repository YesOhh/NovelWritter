"""修订 Agent：根据审校报告对章节做定向改写，闭合"审→改"循环（阶段 5）。

mode:
- fix：按 issues 修复矛盾/人设/情节/伏笔问题，尽量少动无关部分，保持文风与字数。
- anti-detect：专做去 AI 味改写（打散句式、替换疲劳词、删除解释性总结），不改情节。
"""
from app.agents.style_rules import ANTI_AI_GUIDELINES
from app.llm.claude_client import stream_completion

_FIX_SYSTEM_PROMPT = """你是一位资深小说编辑兼写手，负责按审校意见定向修订正文。
要求：
- 只针对给出的问题清单修改，未涉及的段落尽量保持原样，不要重写全文。
- 保持原有文风、人称、时态与大致字数。
- 修复设定矛盾、人设崩坏、情节漏洞、伏笔遗漏等问题，使行文连贯一致。
- 只输出修订后的完整正文，不要输出任何说明、批注或标题。"""

_ANTI_DETECT_SYSTEM_PROMPT = (
    """你是一位资深小说编辑，负责给正文去"AI 味"，使其更像人类作家手笔。
要求：
- 不改变情节、人物、设定与大致字数，只调整表达。
- 打散单调句式，替换高频套话与情绪标签词，删除解释性总结与说教式收尾。
- 句子长短错落、节奏自然；用具体动作与细节替代直白情绪说明。
- 只输出改写后的完整正文，不要输出任何说明或批注。"""
    + ANTI_AI_GUIDELINES
)


def _format_issues(issues: list[dict]) -> str:
    if not issues:
        return "（无具体问题，按去 AI 味要求润色即可）"
    order = {"high": 0, "medium": 1, "low": 2}
    ranked = sorted(issues, key=lambda i: order.get(i.get("severity", "low"), 3))
    lines = []
    for idx, it in enumerate(ranked, 1):
        lines.append(
            f"{idx}. [{it.get('type', 'other')}/{it.get('severity', 'low')}] "
            f"{it.get('description', '')}"
            + (f"\n   定位：{it.get('location')}" if it.get("location") else "")
            + (f"\n   建议：{it.get('suggestion')}" if it.get("suggestion") else "")
        )
    return "\n".join(lines)


async def revise_chapter(
    content: str,
    issues: list[dict] | None = None,
    premise: str = "",
    style: str = "",
    characters: str = "",
    entity_states: str = "",
    chapter_outline: str = "",
    mode: str = "fix",
    model: str | None = None,
) -> str:
    """返回修订后的完整正文（纯文本）。"""
    if not content:
        return content

    issues = issues or []
    system = _ANTI_DETECT_SYSTEM_PROMPT if mode == "anti-detect" else _FIX_SYSTEM_PROMPT

    if mode == "anti-detect":
        task = "请对下文做去 AI 味改写，保持情节与字数不变。"
    else:
        task = "请按问题清单定向修订下文，未涉及部分尽量保持原样。"

    prompt = f"""【故事设定】
{premise or "（未提供）"}

【文风要求】
{style or "（未指定）"}

【角色卡】
{characters or "（未提供）"}

【角色当前状态】
{entity_states or "（暂无）"}

【本章大纲】
{chapter_outline or "（未提供）"}

【审校问题清单】
{_format_issues(issues)}

【原始正文】
{content}

{task}
直接输出修订后的完整正文："""

    max_tokens = min(8192, max(1024, int(len(content) * 2.0)))
    parts: list[str] = []
    async for chunk in stream_completion(
        system=system,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=0.7,
        model=model,
    ):
        parts.append(chunk)
    return "".join(parts).strip()
