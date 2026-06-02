"""写作 Agent：阶段 1 最小实现，根据章节大纲生成正文。"""
from collections.abc import AsyncIterator

from app.agents.style_rules import ANTI_AI_GUIDELINES
from app.llm.claude_client import stream_completion

WRITER_SYSTEM_PROMPT = """你是一位资深中文小说写作家。请根据用户提供的设定与本章大纲，创作出文笔细腻、节奏得当的小说正文。

写作要求：
- 用"展示而非告知"(show, don't tell)的手法，多用场景、动作、对话推动情节。
- 保持人物性格与设定一致，对话要自然、有个性。
- 段落清晰，避免空洞的总结性叙述。
- 只输出小说正文，不要输出大纲、说明或标题之外的任何元信息。""" + ANTI_AI_GUIDELINES


def build_prompt(
    premise: str,
    style: str,
    chapter_outline: str,
    word_count: int,
) -> str:
    return f"""【故事设定】
{premise or "（未提供，请自行合理发挥）"}

【文风要求】
{style or "（未指定，请采用流畅自然的现代中文叙事文风）"}

【本章大纲】
{chapter_outline}

【目标字数】
约 {word_count} 字

请开始创作本章正文："""


def build_context_pack_prompt(
    premise: str,
    style: str,
    characters: str,
    volume_outline: str,
    chapter_outline: str,
    previous_tail: str,
    word_count: int,
    volume_summary: str = "",
    recent_summaries: str = "",
    recalled: str = "",
    entity_states: str = "",
) -> str:
    """项目感知写作的上下文包（architecture.md §4.4）。"""
    return f"""【故事设定】
{premise or "（未提供，请自行合理发挥）"}

【文风要求】
{style or "（未指定，请采用流畅自然的现代中文叙事文风）"}

【相关角色】
{characters or "（暂无角色卡，请依据设定塑造人物）"}

【相关角色当前状态】
{entity_states or "（暂无状态记录）"}

【本卷大纲】
{volume_outline or "（未提供）"}

【本卷前情摘要】
{volume_summary or "（本卷刚开始）"}

【最近章节摘要】
{recent_summaries or "（无）"}

【相关历史片段（检索召回）】
{recalled or "（无）"}

【本章大纲】
{chapter_outline}

【上一章结尾】
{previous_tail or "（本章为开篇，无前情）"}

【目标字数】
约 {word_count} 字

请承接前情、保持人物与设定一致、避免与历史片段和角色状态矛盾，创作本章正文："""


async def write_chapter_stream(
    premise: str,
    style: str,
    chapter_outline: str,
    word_count: int = 1500,
    model: str | None = None,
) -> AsyncIterator[str]:
    prompt = build_prompt(premise, style, chapter_outline, word_count)
    async for chunk in _stream_prompt(prompt, word_count, model):
        yield chunk


async def write_chapter_from_context(
    premise: str,
    style: str,
    characters: str,
    volume_outline: str,
    chapter_outline: str,
    previous_tail: str,
    word_count: int = 1500,
    model: str | None = None,
    volume_summary: str = "",
    recent_summaries: str = "",
    recalled: str = "",
    entity_states: str = "",
) -> AsyncIterator[str]:
    prompt = build_context_pack_prompt(
        premise=premise,
        style=style,
        characters=characters,
        volume_outline=volume_outline,
        chapter_outline=chapter_outline,
        previous_tail=previous_tail,
        word_count=word_count,
        volume_summary=volume_summary,
        recent_summaries=recent_summaries,
        recalled=recalled,
        entity_states=entity_states,
    )
    async for chunk in _stream_prompt(prompt, word_count, model):
        yield chunk


async def _stream_prompt(
    prompt: str, word_count: int, model: str | None
) -> AsyncIterator[str]:
    # 粗略按字数估算 token 上限（中文约 1 字 ≈ 1.5~2 token），留足余量。
    max_tokens = min(8192, max(1024, int(word_count * 2.5)))
    async for chunk in stream_completion(
        system=WRITER_SYSTEM_PROMPT,
        prompt=prompt,
        max_tokens=max_tokens,
        model=model,
    ):
        yield chunk
