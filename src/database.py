"""Async SQLAlchemy engine + session factory.

Only initialised when DATABASE_URL is set, so endpoints that don't need the
database (health, stats sampler) still work in dev environments without
Postgres running. The engine is created lazily so import-time failures don't
take down the whole app.
"""

from collections.abc import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

# Module-level engines are created on first access so a missing DATABASE_URL
# or WORLDCUP_DB_WRITER_URL only blocks the routes that actually need them,
# not the whole app.
_cached_engine = None
_cached_session_factory = None
_cached_writer_engine = None
_cached_writer_session_factory = None


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
    reader role. Returns 503 when the database is not configured.
    """
    try:
        factory = session_factory()
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="Database is not configured on this server.",
        )
    async with factory() as session:
        yield session


def _writer_engine():
    global _cached_writer_engine, _cached_writer_session_factory
    if _cached_writer_engine is None:
        if not settings.worldcup_db_writer_url:
            raise RuntimeError(
                "WORLDCUP_DB_WRITER_URL is not set; ingest is disabled."
            )
        _cached_writer_engine = create_async_engine(
            settings.worldcup_db_writer_url, echo=False
        )
        _cached_writer_session_factory = async_sessionmaker(
            _cached_writer_engine, class_=AsyncSession, expire_on_commit=False
        )
    return _cached_writer_engine


async def get_writer_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async session bound to the worldcup
    writer role. Intended for admin-gated endpoints only; never wire this
    into a route reachable via has_api_key. Returns 503 when the writer
    connection is not configured.
    """
    try:
        _writer_engine()
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="Ingest is not configured on this server.",
        )
    async with _cached_writer_session_factory() as session:
        yield session
