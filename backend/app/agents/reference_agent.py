"""参考文本分析 Agent：抽取设定、角色、线索和文风指纹。"""
from app.llm.claude_client import complete_json
from app.schemas import ReferenceAnalyzeResult

REFERENCE_SYSTEM_PROMPT = """你是一位资深长篇小说拆书编辑。请分析用户提供的参考文本，抽象出可用于续写或风格对齐的结构化资料。

要求：
- 只提炼抽象信息，不要大段复述或照抄原文。
- 文风指纹要描述可执行的写作约束，例如叙述视角、节奏、句式、意象、对白特点、禁忌。
- 角色只提炼文本中能看出的性格、动机、关系、外貌和弧光。
- 设定提炼为世界观、组织、地点、规则、物件、历史等条目。
- 伏笔/支线提炼为可追踪的 open/progressing/resolved 线索；不确定时用 open。
- 输出应服务于原创续写，不要生成模仿原文的可替代片段。"""

_REFERENCE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "style_fingerprint": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "narrative_pov": {"type": "string"},
                "tense": {"type": "string"},
                "sentence_rhythm": {"type": "string"},
                "diction": {"type": "string"},
                "dialogue": {"type": "string"},
                "imagery": {"type": "string"},
                "pacing": {"type": "string"},
                "taboos": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary"],
        },
        "settings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
            },
        },
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "profile": {
                        "type": "object",
                        "properties": {
                            "personality": {"type": "string"},
                            "motivation": {"type": "string"},
                            "relationships": {"type": "string"},
                            "appearance": {"type": "string"},
                        },
                    },
                    "arc": {"type": "string"},
                },
                "required": ["name", "profile"],
            },
        },
        "foreshadows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["foreshadow", "subplot", "resource", "relationship"],
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["open", "progressing", "resolved"],
                    },
                    "introduced_at": {"type": "string"},
                    "payoff": {"type": "string"},
                },
                "required": ["kind", "title", "description"],
            },
        },
    },
    "required": ["style_fingerprint", "settings", "characters", "foreshadows"],
}


async def analyze_reference_text(text: str, model: str | None = None) -> ReferenceAnalyzeResult:
    prompt = f"""【参考文本】
{text}

请调用 save_reference_analysis 返回文风指纹、设定、角色和伏笔/支线。"""
    data = await complete_json(
        system=REFERENCE_SYSTEM_PROMPT,
        prompt=prompt,
        tool_name="save_reference_analysis",
        tool_schema=_REFERENCE_TOOL_SCHEMA,
        max_tokens=5000,
        model=model,
    )
    return ReferenceAnalyzeResult.model_validate({**data, "applied": False, "created_counts": {}})