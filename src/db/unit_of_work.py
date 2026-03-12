"""Campaign Cannon 2 — Unit of Work (transaction context manager).

Guarantees atomic commit or rollback. Use for any multi-step write operation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import AsyncSessionLocal


@asynccontextmanager
async def unit_of_work() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional scope.

    Commits on clean exit, rolls back on any exception.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            yield session
            # commit happens automatically when begin() context exits cleanly
        # rollback happens automatically on exception
