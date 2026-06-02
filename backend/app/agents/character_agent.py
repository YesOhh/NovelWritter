"""角色 Agent：根据项目设定生成立体的核心角色卡（结构化输出）。"""
from app.llm.claude_client import complete_json
from app.schemas import CharacterResult

CHARACTER_SYSTEM_PROMPT = """你是一位资深小说角色设计师。请根据故事设定，塑造立体、可信、彼此关联的核心角色。

要求：
- 每个角色有鲜明的性格、清晰且自洽的核心动机。
- 角色之间构成有张力的关系网（盟友/对手/羁绊），而非各自孤立。
- 为每个角色设计成长弧光（arc）：从起点到终点会发生怎样的转变。
- 外貌简洁有辨识度，服务于人物气质。"""

_CHARACTER_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "角色姓名"},
                    "profile": {
                        "type": "object",
                        "properties": {
                            "personality": {"type": "string", "description": "性格"},
                            "motivation": {"type": "string", "description": "核心动机"},
                            "relationships": {"type": "string", "description": "与其他角色的关系"},
                            "appearance": {"type": "string", "description": "外貌"},
                        },
                        "required": ["personality", "motivation", "relationships", "appearance"],
                    },
                    "arc": {"type": "string", "description": "角色成长弧光"},
                },
                "required": ["name", "profile", "arc"],
            },
        }
    },
    "required": ["characters"],
}


async def generate_characters(
    premise: str,
    genre: str,
    count: int = 4,
    model: str | None = None,
) -> CharacterResult:
    prompt = f"""【题材】{genre or "（未指定）"}
【故事设定】
{premise or "（未提供，请合理发挥）"}

请设计 {count} 个核心角色，构成彼此关联的关系网。调用 save_characters 工具返回。"""
    data = await complete_json(
        system=CHARACTER_SYSTEM_PROMPT,
        prompt=prompt,
        tool_name="save_characters",
        tool_schema=_CHARACTER_TOOL_SCHEMA,
        max_tokens=6144,
        model=model,
    )
    return CharacterResult.model_validate(data)
