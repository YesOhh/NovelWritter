"""章节成稿后的记忆刷新：摘要、检索片段、实体状态。"""
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory import entity_tracker
from app.memory.retriever import index_chunk
from app.memory.summarizer import summarize_chapter
from app.models import Chapter, ChapterSummary, Character, EntityState, MemoryChunk


async def refresh_chapter_memory(
    session: AsyncSession,
    chapter: Chapter,
    project_id: str,
    characters: list[Character],
    model: str | None = None,
) -> dict:
    """刷新单章关联记忆，返回摘要与实体状态写入数量。"""
    summary_data = await summarize_chapter(
        title=chapter.title,
        content=chapter.content,
        model=model,
    )
    summary = summary_data.get("summary", "")
    keywords = summary_data.get("keywords", [])

    await session.execute(
        delete(ChapterSummary).where(ChapterSummary.chapter_id == chapter.id)
    )
    session.add(
        ChapterSummary(
            chapter_id=chapter.id,
            summary=summary,
            keywords=keywords,
        )
    )

    await session.execute(
        delete(MemoryChunk).where(
            MemoryChunk.source_type == "chapter_summary",
            MemoryChunk.source_id == chapter.id,
        )
    )
    await index_chunk(
        session,
        project_id=project_id,
        source_type="chapter_summary",
        source_id=chapter.id,
        text=f"{chapter.title}：{summary}",
        keywords=keywords,
    )

    await session.execute(
        delete(EntityState).where(EntityState.chapter_id == chapter.id)
    )
    state_count = await entity_tracker.extract_and_store(
        session=session,
        chapter_id=chapter.id,
        chapter_content=chapter.content,
        characters=characters,
        model=model,
    )

    return {
        "summary": summary,
        "keywords": keywords,
        "entity_state_count": state_count,
    }
