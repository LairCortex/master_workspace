"""Database engine and session factory."""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _on_connect(dbapi_conn, connection_record):
    """Per-connection SQLite setup: unicode lower() + FK enforcement.

    SET NULL / RESTRICT on character_sheet_instances (and the rest of the
    schema) only fire when ``PRAGMA foreign_keys=ON`` is set on the
    connection, before any transaction starts.
    """
    dbapi_conn.create_function("lower", 1, lambda s: s.lower() if s else s)
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine(url: str, echo: bool = False):
    engine = create_async_engine(url, echo=echo)
    event.listen(engine.sync_engine, "connect", _on_connect)
    return engine


def create_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
