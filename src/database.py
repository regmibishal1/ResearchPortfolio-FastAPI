"""Async SQLAlchemy engine + session factory.

Only initialised when DATABASE_URL is set, so endpoints that don't need the
database (health, stats sampler) still work in dev environments without
Postgres running. The engine is created lazily so import-time failures don't
take down the whole app.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

# Module-level engine is created on first access via _engine() so a missing
# DATABASE_URL only blocks the routes that actually need it, not the whole app.
_cached_engine = None
_cached_session_factory = None


def _engine():
    global _cached_engine, _cached_session_factory
    if _cached_engine is None:
        if not settings.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set; database-backed endpoints are disabled."
            )
        _cached_engine = create_async_engine(settings.database_url, echo=False)
        _cached_session_factory = async_sessionmaker(
            _cached_engine, class_=AsyncSession, expire_on_commit=False
        )
    return _cached_engine


def session_factory():
    _engine()
    return _cached_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async session bound to the worldcup
    reader role.
    """
    factory = session_factory()
    async with factory() as session:
        yield session
