"""数据库连接管理 —— SQLite 本地模式（免 Docker）"""

import os
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event
from app.core.config import get_settings

settings = get_settings()

# 确保数据目录存在
Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)

# SQLite 需要 check_same_thread=False，PostgreSQL 不需要
_connect_args = {}
if "sqlite" in settings.database_url:
    _connect_args.update({
        "check_same_thread": False,
        "timeout": 30,  # sqlite3 busy timeout（秒）：并发写入时排队而不是直接报错
    })

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args=_connect_args,
)

if "sqlite" in settings.database_url:
    # WAL 模式：读写不互相阻塞，配合 busy_timeout 避免流式回答等并发场景的 database is locked
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库会话"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """创建所有表（首次启动调用）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
