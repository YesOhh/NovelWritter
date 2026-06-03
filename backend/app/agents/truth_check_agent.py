"""Truth file consistency agent: checks long-form facts against project material."""
from app.llm.claude_client import complete_json
from app.schemas import TruthFileCheckResult

TRUTH_CHECK_SYSTEM_PROMPT = """你是一位长篇小说连续性编辑，专门检查“长篇真相文件”是否被项目资料写崩。

你会收到：
- 真相文件：长期硬约束、隐藏真相、资源账本、关系弧或时间锚点。
- 项目资料：世界观设定、角色卡、章节大纲/摘要/正文片段。

检查目标：
- 找出项目资料中与真相文件存在直接冲突、明显遗漏关键限制、时间顺序相反、资源数量/归属不一致、关系状态矛盾、隐藏真相提前泄露等问题。
- 也检查真相文件之间是否互相冲突；若冲突来源是另一条真相文件，source_type 用 truth_file，source_id 用另一条真相文件 id。
- 只报告有明确证据的问题，不要为了凑数猜测。
- 如果只是信息不足、尚未提及、未来可能解释，不算矛盾。
- evidence 必须引用或概括项目资料里的具体证据。
- suggestion 给出作者可执行的修正方向，但不要替作者改写正文。
- severity 用 high / medium / low。high 表示会破坏主线或核心秘密；medium 表示影响连续性；low 表示轻微措辞或局部可调整。
- maintenance_actions 返回接下来最值得处理的维护动作，数量控制在 0-6 条；不要重复 issues 的文字，要转换成“作者下一步做什么”。
- 只有当真相文件明显不该继续作为生效约束时，才建议 update_truth_status，并填写 suggested_status。"""

_TRUTH_CHECK_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "truth_file_id": {"type": "string", "description": "相关真相文件 id"},
                    "truth_title": {"type": "string", "description": "相关真相文件标题"},
                    "severity": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "严重度",
                    },
                    "source_type": {
                        "type": "string",
                        "enum": ["chapter", "setting", "character", "truth_file", "overview"],
                        "description": "冲突来源类型",
                    },
                    "source_id": {"type": "string", "description": "冲突来源 id"},
                    "source_title": {"type": "string", "description": "冲突来源标题"},
                    "evidence": {"type": "string", "description": "项目资料中的具体证据"},
                    "description": {"type": "string", "description": "矛盾描述"},
                    "suggestion": {"type": "string", "description": "可执行修正建议"},
                },
                "required": [
                    "truth_file_id",
                    "truth_title",
                    "severity",
                    "source_type",
                    "source_id",
                    "source_title",
                    "evidence",
                    "description",
                    "suggestion",
                ],
            },
        },
        "maintenance_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": [
                            "update_truth_status",
                            "revise_truth_file",
                            "revise_chapter",
                            "update_setting",
                            "review_character",
                            "split_truth_file",
                        ],
                        "description": "维护动作类型",
                    },
                    "target_type": {
                        "type": "string",
                        "enum": ["truth_file", "chapter", "setting", "character", "project"],
                        "description": "动作目标类型",
                    },
                    "target_id": {"type": "string", "description": "动作目标 id"},
                    "target_title": {"type": "string", "description": "动作目标标题"},
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "处理优先级",
                    },
                    "title": {"type": "string", "description": "动作标题"},
                    "reason": {"type": "string", "description": "为什么需要处理"},
                    "suggestion": {"type": "string", "description": "具体处理建议"},
                    "suggested_status": {
                        "type": "string",
                        "enum": ["", "active", "draft", "resolved", "archived"],
                        "description": "若 action_type=update_truth_status，建议的新状态；否则为空",
                    },
                },
                "required": [
                    "action_type",
                    "target_type",
                    "target_id",
                    "target_title",
                    "priority",
                    "title",
                    "reason",
                    "suggestion",
                    "suggested_status",
                ],
            },
        },
    },
    "required": ["issues", "maintenance_actions"],
}


async def check_truth_file_consistency(
    truth_files: str,
    project_material: str,
    checked_truth_files: int,
    checked_chapters: int,
    model: str | None = None,
) -> TruthFileCheckResult:
    if not truth_files.strip() or not project_material.strip():
        return TruthFileCheckResult(
            checked_truth_files=checked_truth_files,
            checked_chapters=checked_chapters,
            issues=[],
            maintenance_actions=[],
        )

    prompt = f"""【真相文件】
{truth_files}

【项目资料】
{project_material}

请检查项目资料是否违背真相文件，并给出后续维护动作。调用 save_truth_conflicts 返回结果；如果没有明确矛盾，issues 返回空数组，maintenance_actions 只返回真正有必要的维护建议。"""
    data = await complete_json(
        system=TRUTH_CHECK_SYSTEM_PROMPT,
        prompt=prompt,
        tool_name="save_truth_conflicts",
        tool_schema=_TRUTH_CHECK_TOOL_SCHEMA,
        max_tokens=4000,
        model=model,
    )
    result = TruthFileCheckResult.model_validate(
        {
            "checked_truth_files": checked_truth_files,
            "checked_chapters": checked_chapters,
            "issues": data.get("issues") or [],
            "maintenance_actions": data.get("maintenance_actions") or [],
        }
    )
    known_truth_ids = {
        line.split("；", 1)[0].removeprefix("id=")
        for line in truth_files.splitlines()
        if line.startswith("id=")
    }
    result.issues = [
        issue for issue in result.issues
        if issue.truth_file_id in known_truth_ids and issue.description.strip()
    ]
    result.maintenance_actions = [
        action for action in result.maintenance_actions
        if action.title.strip() and action.suggestion.strip()
    ][:6]
    return result
