"""Campaign Cannon 2 — Async database engine and session factory.

Single async engine. No sync engine anywhere in the codebase.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import DATABASE_URL

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """Yield an async session for dependency injection."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create all tables. Called once at startup."""
    from src.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose engine. Called at shutdown."""
    await engine.dispose()
