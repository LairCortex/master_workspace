"""Database engine and session factory."""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _register_unicode_lower(dbapi_conn, connection_record):
    """Override SQLite's lower() with Python's str.lower() for Unicode support."""
    dbapi_conn.create_function("lower", 1, lambda s: s.lower() if s else s)


def create_engine(url: str, echo: bool = False):
    engine = create_async_engine(url, echo=echo)
    event.listen(engine.sync_engine, "connect", _register_unicode_lower)
    return engine


def create_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
