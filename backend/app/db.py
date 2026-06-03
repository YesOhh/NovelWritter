"""数据库基础设施：async SQLite engine + session + 建表。"""
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

# DB 文件落在 backend/novel.db，绝对路径定位，避免受启动工作目录影响。
_DB_PATH = Path(__file__).resolve().parent.parent / "novel.db"
DATABASE_URL = f"sqlite+aiosqlite:///{_DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    # 导入模型以注册到 Base.metadata，再建表。
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        columns = await conn.execute(text("PRAGMA table_info(volumes)"))
        column_names = {row[1] for row in columns.fetchall()}
        if "kind" not in column_names:
            await conn.execute(text("ALTER TABLE volumes ADD COLUMN kind VARCHAR(40) DEFAULT 'novel' NOT NULL"))
        await conn.execute(
            text("UPDATE volumes SET kind = 'reference' WHERE outline LIKE '由参考文本分章导入%'")
        )
