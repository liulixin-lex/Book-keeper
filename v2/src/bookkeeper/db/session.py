"""Engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, Result, create_engine
from sqlalchemy.orm import Session, sessionmaker

from bookkeeper.config import get_settings


def make_engine(url: str, *, pool_size: int = 10) -> Engine:
    return create_engine(
        url,
        pool_size=pool_size,
        max_overflow=10,
        pool_pre_ping=True,
        connect_args={"options": "-c timezone=UTC"},
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def reset_engine_cache() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


def rowcount(result: Result[Any]) -> int:
    """Rows affected by an UPDATE/DELETE result."""
    return int(getattr(result, "rowcount", 0) or 0)


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction: commit on success, roll back on error."""
    session = get_sessionmaker()()
    try:
        with session.begin():
            yield session
    finally:
        session.close()
