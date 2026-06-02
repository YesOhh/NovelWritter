"""轻量 RAG：基于关键词重叠的检索片段索引与召回。

部分 LLM 端点不提供 embedding，故先用关键词打分。Retriever 设计为可替换接口，
未来可派生 VectorRetriever 换成真正的向量检索，调用方无需改动。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MemoryChunk


async def index_chunk(
    session: AsyncSession,
    project_id: str,
    source_type: str,
    source_id: str,
    text: str,
    keywords: list[str],
) -> MemoryChunk:
    chunk = MemoryChunk(
        project_id=project_id,
        source_type=source_type,
        source_id=source_id,
        text=text,
        keywords=keywords or [],
    )
    session.add(chunk)
    return chunk


def _score(query_keywords: list[str], query_text: str, chunk: MemoryChunk) -> float:
    qk = {k.lower() for k in query_keywords if k}
    ck = {k.lower() for k in (chunk.keywords or []) if k}
    # 关键词集合重叠为主分。
    overlap = len(qk & ck)
    score = float(overlap) * 2.0
    # 子串命中作为补充：query 关键词出现在片段文本里。
    text_lower = (chunk.text or "").lower()
    for k in qk:
        if k and k in text_lower:
            score += 0.5
    return score


class Retriever:
    """关键词检索器。future: VectorRetriever(Retriever)。"""

    async def retrieve(
        self,
        session: AsyncSession,
        project_id: str,
        query_text: str,
        query_keywords: list[str],
        k: int = 5,
        exclude_source_ids: set[str] | None = None,
    ) -> list[MemoryChunk]:
        result = await session.execute(
            select(MemoryChunk).where(MemoryChunk.project_id == project_id)
        )
        chunks = list(result.scalars().all())
        exclude = exclude_source_ids or set()
        scored = [
            (self._score(query_keywords, query_text, c), c)
            for c in chunks
            if c.source_id not in exclude
        ]
        scored = [sc for sc in scored if sc[0] > 0]
        scored.sort(key=lambda sc: sc[0], reverse=True)
        return [c for _, c in scored[:k]]

    _score = staticmethod(_score)


retriever = Retriever()
