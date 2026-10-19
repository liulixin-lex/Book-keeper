"""Fixed-window rate limits stored in PostgreSQL, so every worker process shares the same counters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bookkeeper.db.models import RateCounter
from bookkeeper.db.session import rowcount
from bookkeeper.domain.errors import DomainError

WINDOW = 60
WRITE_LIMIT_PER_MIN = 30


def hit(session: Session, key: str, limit: int, window: int = WINDOW) -> int:
    """Count one request for ``key``; raise RATE_LIMITED once the window's limit is exceeded."""
    now = datetime.now(UTC)
    start = datetime.fromtimestamp(int(now.timestamp()) // window * window, UTC)
    stmt = (
        insert(RateCounter)
        .values(key=key, window_start=start, count=1)
        .on_conflict_do_update(
            index_elements=[RateCounter.key, RateCounter.window_start], set_={"count": RateCounter.count + 1}
        )
        .returning(RateCounter.count)
    )
    count = int(session.execute(stmt).scalar_one())
    if count > limit:
        retry = max(1, int((start + timedelta(seconds=window) - now).total_seconds()) + 1)
        raise DomainError(
            "RATE_LIMITED",
            f"请求过于频繁（每 {window} 秒最多 {limit} 次），请 {retry} 秒后重试。",
            extra={"retry_after": retry, "limit": limit},
        )
    return count


def purge(session: Session, older_than: timedelta = timedelta(hours=1)) -> int:
    cutoff = datetime.now(UTC) - older_than
    return rowcount(session.execute(delete(RateCounter).where(RateCounter.window_start < cutoff)))
