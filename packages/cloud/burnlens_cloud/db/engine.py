"""SQLAlchemy async engine and session factory."""

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://burnlens:burnlens_dev@localhost:5433/burnlens",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with async_session_factory() as session:
        yield session
