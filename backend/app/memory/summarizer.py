"""分层摘要：章节摘要（含关键词）与卷摘要。"""
from app.llm.claude_client import complete_json
from app.llm.claude_client import stream_completion  # noqa: F401  (保留以便未来流式摘要)

_SUMMARY_SYSTEM = """你是小说编辑助手。请为给定章节正文生成简明摘要，并抽取关键实体与情节关键词，用于后续检索与连贯性维护。
要求：摘要 200~400 字，覆盖本章关键事件、人物动向、新出现的设定/伏笔；关键词为人名/地名/物品/事件等检索词。"""

_SUMMARY_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "本章摘要，200~400字"},
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "关键实体与情节关键词（人名/地名/物品/事件），5~15个",
        },
    },
    "required": ["summary", "keywords"],
}


async def summarize_chapter(
    title: str, content: str, model: str | None = None
) -> dict:
    prompt = f"""【章节标题】{title}

【章节正文】
{content}

请调用 save_summary 返回摘要与关键词。"""
    return await complete_json(
        system=_SUMMARY_SYSTEM,
        prompt=prompt,
        tool_name="save_summary",
        tool_schema=_SUMMARY_TOOL_SCHEMA,
        max_tokens=1500,
        model=model,
    )


_VOLUME_SYSTEM = """你是小说编辑助手。请把若干章节摘要聚合成一段连贯的卷摘要，概括本卷主线、转折与悬念，300~500字。"""


async def summarize_volume(
    volume_title: str, chapter_summaries: list[str], model: str | None = None
) -> str:
    joined = "\n\n".join(f"- {s}" for s in chapter_summaries if s)
    prompt = f"""【卷标题】{volume_title}

【各章摘要】
{joined}

请直接输出卷摘要正文（不要列表、不要额外说明）："""
    text = ""
    async for chunk in stream_completion(
        system=_VOLUME_SYSTEM, prompt=prompt, max_tokens=1200, model=model
    ):
        text += chunk
    return text.strip()
