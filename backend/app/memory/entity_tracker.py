"""实体状态追踪：每章成稿后抽取角色状态变更，写作时注入当前状态。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.claude_client import complete_json
from app.models import Character, EntityState

_EXTRACT_SYSTEM = """你是小说连贯性维护助手。请根据章节正文，抽取本章中各登场角色的"当前状态"，用于后续章节避免前后矛盾（如已死角色复活、位置错乱）。
只针对给定的已知角色列表抽取；未登场的角色不要输出。状态包括：所在位置、生死/健康、持有物、关系变化、本章新获知的重要信息。"""


def _tool_schema(character_names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "states": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "角色姓名，必须是已知角色之一：" + "、".join(character_names),
                        },
                        "location": {"type": "string", "description": "本章结束时所在位置"},
                        "status": {"type": "string", "description": "生死/健康状态"},
                        "possessions": {"type": "string", "description": "持有的重要物品"},
                        "knowledge": {"type": "string", "description": "本章新获知的重要信息"},
                    },
                    "required": ["name"],
                },
            }
        },
        "required": ["states"],
    }


async def extract_and_store(
    session: AsyncSession,
    chapter_id: str,
    chapter_content: str,
    characters: list[Character],
    model: str | None = None,
) -> int:
    """抽取并落库本章角色状态，返回写入条数。"""
    if not characters or not chapter_content:
        return 0
    name_to_id = {c.name: c.id for c in characters}
    names = list(name_to_id.keys())

    data = await complete_json(
        system=_EXTRACT_SYSTEM,
        prompt=f"""【已知角色】{"、".join(names)}

【本章正文】
{chapter_content}

请调用 save_states 返回本章登场角色的当前状态。""",
        tool_name="save_states",
        tool_schema=_tool_schema(names),
        max_tokens=2000,
        model=model,
    )

    count = 0
    for item in data.get("states", []):
        cid = name_to_id.get(item.get("name", ""))
        if not cid:
            continue
        state = {k: v for k, v in item.items() if k != "name" and v}
        session.add(EntityState(character_id=cid, chapter_id=chapter_id, state=state))
        count += 1
    return count


async def current_states(
    session: AsyncSession, character_ids: list[str]
) -> dict[str, dict]:
    """取每个角色最新一条状态（按插入顺序，最后写入的为最新）。"""
    if not character_ids:
        return {}
    result = await session.execute(
        select(EntityState).where(EntityState.character_id.in_(character_ids))
    )
    latest: dict[str, dict] = {}
    for es in result.scalars().all():
        latest[es.character_id] = es.state  # 后写入覆盖前者 → 最新
    return latest
