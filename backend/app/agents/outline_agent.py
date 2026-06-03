"""大纲 Agent：根据项目设定生成分卷分章大纲（结构化输出）。"""
from app.llm.claude_client import complete_json
from app.schemas import OutlineChaptersResult, OutlineResult

OUTLINE_SYSTEM_PROMPT = """你是一位资深小说大纲师。请根据故事设定，规划出结构完整、节奏得当的分卷分章大纲。

要求：
- 遵循三幕结构（建置/对抗/解决），全书有清晰的起承转合。
- 合理铺设并回收伏笔，卷与卷之间有递进与悬念钩子。
- 每卷大纲概述本卷核心冲突与转折；每章大纲是 1~2 句可直接指导写作的情节梗概。
- 严格按要求的卷数与每卷章数输出。"""

_OUTLINE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "volumes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "卷标题"},
                    "outline": {"type": "string", "description": "本卷大纲概述"},
                    "chapters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "章标题"},
                                "outline": {"type": "string", "description": "本章情节梗概"},
                            },
                            "required": ["title", "outline"],
                        },
                    },
                },
                "required": ["title", "outline", "chapters"],
            },
        }
    },
    "required": ["volumes"],
}

_CHAPTERS_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "章标题"},
                    "outline": {"type": "string", "description": "本章情节梗概"},
                },
                "required": ["title", "outline"],
            },
        }
    },
    "required": ["chapters"],
}


async def generate_outline(
    premise: str,
    genre: str,
    style: str,
    volume_count: int = 3,
    chapters_per_volume: int = 5,
    existing_outline: str = "",
    model: str | None = None,
) -> OutlineResult:
    existing_section = (
        f"\n【已有大纲】\n{existing_outline}\n\n请从已有大纲之后继续规划新卷，不要重复已有卷章。"
        if existing_outline.strip()
        else ""
    )
    prompt = f"""【题材】{genre or "（未指定）"}
【故事设定】
{premise or "（未提供，请合理发挥）"}

【文风】{style or "（未指定）"}
{existing_section}

请规划接下来的 {volume_count} 卷，每卷约 {chapters_per_volume} 章。调用 save_outline 工具只返回本次新增的大纲。"""
    data = await complete_json(
        system=OUTLINE_SYSTEM_PROMPT,
        prompt=prompt,
        tool_name="save_outline",
        tool_schema=_OUTLINE_TOOL_SCHEMA,
        max_tokens=8192,
        model=model,
    )
    return OutlineResult.model_validate(data)


async def generate_volume_chapters(
    premise: str,
    genre: str,
    style: str,
    existing_outline: str,
    volume_title: str,
    volume_outline: str,
    existing_chapters: str,
    additional_count: int,
    model: str | None = None,
) -> OutlineChaptersResult:
    prompt = f"""【题材】{genre or "（未指定）"}
【故事设定】
{premise or "（未提供，请合理发挥）"}

【文风】{style or "（未指定）"}

【整书已有大纲】
{existing_outline or "（暂无）"}

【需要补齐的卷】
卷名：{volume_title or "未命名卷"}
卷纲：{volume_outline or "（暂无）"}

【本卷已有章节】
{existing_chapters or "（暂无）"}

请为该卷继续追加 {additional_count} 章。不要重写已有章节，不要重复已有情节；新增章节要承接本卷已有章纲，并服务于整书走向。调用 save_chapters 工具只返回新增章节。"""
    data = await complete_json(
        system=OUTLINE_SYSTEM_PROMPT,
        prompt=prompt,
        tool_name="save_chapters",
        tool_schema=_CHAPTERS_TOOL_SCHEMA,
        max_tokens=4096,
        model=model,
    )
    return OutlineChaptersResult.model_validate(data)
