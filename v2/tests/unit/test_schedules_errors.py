from datetime import UTC, datetime

import pytest

from bookkeeper.domain import schedules
from bookkeeper.domain.errors import DomainError


def test_every_interval() -> None:
    after = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
    assert schedules.next_run("every:3600", after, "UTC") == datetime(2026, 10, 18, 1, 0, tzinfo=UTC)


def test_daily_in_book_timezone() -> None:
    # 2026-10-18 03:30 Asia/Shanghai = 2026-10-17 19:30 UTC; next 04:00 local = 20:00 UTC same day
    after = datetime(2026, 10, 17, 19, 30, tzinfo=UTC)
    assert schedules.next_run("daily:04:00", after, "Asia/Shanghai") == datetime(2026, 10, 17, 20, 0, tzinfo=UTC)
    after_run = datetime(2026, 10, 17, 20, 0, tzinfo=UTC)
    assert schedules.next_run("daily:04:00", after_run, "Asia/Shanghai") == datetime(2026, 10, 18, 20, 0, tzinfo=UTC)


@pytest.mark.parametrize("expr", ["every:5", "weekly:1", "daily:25:00"])
def test_bad_schedules(expr: str) -> None:
    with pytest.raises(ValueError, match=r"interval|unsupported|hour"):
        schedules.next_run(expr, datetime.now(UTC), "UTC")


def test_unknown_error_code_rejected() -> None:
    with pytest.raises(ValueError, match="unknown error code"):
        DomainError("NOPE", "x")


def test_error_spec() -> None:
    err = DomainError("IDEMPOTENCY_IN_PROGRESS", "busy")
    assert err.status == 409
    assert err.retryable
