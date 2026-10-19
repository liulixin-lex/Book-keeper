"""Task handlers keyed by job kind."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

TaskFn = Callable[[Session, dict[str, Any]], Any]
_TASKS: dict[str, TaskFn] = {}
_OWN_SESSION: set[str] = set()


def task(kind: str, *, own_session: bool = False) -> Callable[[Any], Any]:
    """Register a handler. ``own_session`` handlers get the session factory instead of an open transaction:
    for slow outside calls (an AI read) that must not hold a database transaction while they wait."""

    def register(fn: Any) -> Any:
        if kind in _TASKS:
            raise ValueError(f"duplicate task: {kind}")
        _TASKS[kind] = fn
        if own_session:
            _OWN_SESSION.add(kind)
        return fn

    return register


def owns_session(kind: str) -> bool:
    return kind in _OWN_SESSION


def get(kind: str) -> Any:
    """The handler: ``(session, payload)``, or ``(session_factory, payload)`` when ``owns_session(kind)``."""
    return _TASKS.get(kind)


def kinds() -> list[str]:
    return sorted(_TASKS)
