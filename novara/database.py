"""Database engine and session factory setup."""

from collections.abc import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from novara.config import get_settings

log = structlog.get_logger(__name__)

settings = get_settings()

# Async engine used by the API and async tasks
engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    echo=settings.novara_env == "development",
)

# Session factory — use as async context manager
async_session_factory = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)

# Separate engine without connection pooling for Alembic and CLI tools
# that run in synchronous contexts.
null_pool_engine = create_async_engine(
    settings.database_url,
    poolclass=NullPool,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
