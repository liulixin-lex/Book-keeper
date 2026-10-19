"""Database job queue (``SELECT … FOR UPDATE SKIP LOCKED``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bookkeeper.db.models import Job, JobSchedule
from bookkeeper.db.session import rowcount
from bookkeeper.domain import schedules
from bookkeeper.domain.ids import new_id

STALE_AFTER = timedelta(minutes=10)


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    book_id: str | None = None,
    run_after: datetime | None = None,
    priority: int = 100,
    max_attempts: int = 5,
    created_by: str | None = None,
    change_set_id: str | None = None,
) -> Job:
    job = Job(
        id=new_id("job"),
        book_id=book_id,
        kind=kind,
        payload=payload or {},
        priority=priority,
        run_after=run_after or datetime.now(UTC),
        max_attempts=max_attempts,
        created_by=created_by,
        change_set_id=change_set_id,
    )
    session.add(job)
    session.flush()
    return job


def claim(session: Session, worker_id: str) -> Job | None:
    now = datetime.now(UTC)
    job = session.execute(
        select(Job)
        .where(Job.status == "queued", Job.run_after <= now)
        .order_by(Job.priority, Job.run_after)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.locked_by = worker_id
    job.locked_at = now
    job.heartbeat_at = now
    job.started_at = now
    job.attempts += 1
    return job


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(3600, 30 * 2 ** max(0, attempts - 1)))


def finish(session: Session, job_id: str, result: Any) -> None:
    session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status="succeeded", result=result, finished_at=datetime.now(UTC), last_error=None)
    )


def fail(session: Session, job_id: str, error: str) -> None:
    job = session.get(Job, job_id, with_for_update=True)
    if job is None:
        return
    job.last_error = error[:4000]
    if job.attempts >= job.max_attempts:
        job.status = "failed"
        job.finished_at = datetime.now(UTC)
    else:
        job.status = "queued"
        job.run_after = datetime.now(UTC) + backoff(job.attempts)
        job.locked_by = None


def touch(session: Session, job_id: str | None) -> None:
    """A long-running job says it is still alive, so no other worker takes it over as stale."""
    if job_id:
        session.execute(update(Job).where(Job.id == job_id, Job.status == "running").values(heartbeat_at=func.now()))


def recover_stale(session: Session) -> int:
    cutoff = datetime.now(UTC) - STALE_AFTER
    result = session.execute(
        update(Job)
        .where(Job.status == "running", Job.heartbeat_at < cutoff)
        .values(status="queued", locked_by=None, last_error="worker heartbeat lost")
    )
    return rowcount(result)


def upsert_schedule(
    session: Session,
    kind: str,
    expression: str,
    *,
    timezone: str = "Asia/Shanghai",
    payload: dict[str, Any] | None = None,
    book_id: str | None = None,
) -> None:
    next_at = schedules.next_run(expression, datetime.now(UTC), timezone)
    stmt = insert(JobSchedule).values(
        id=new_id("jsc"),
        kind=kind,
        schedule=expression,
        timezone=timezone,
        payload=payload or {},
        book_id=book_id,
        next_run_at=next_at,
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["kind", "book_id"],
            set_={"schedule": expression, "timezone": timezone, "payload": payload or {}},
        )
    )


def enqueue_due_schedules(session: Session) -> list[str]:
    now = datetime.now(UTC)
    due = (
        session.execute(
            select(JobSchedule)
            .where(JobSchedule.enabled.is_(True), JobSchedule.next_run_at <= now)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    created = []
    for item in due:
        job = enqueue(session, item.kind, dict(item.payload), book_id=item.book_id, priority=200)
        item.last_run_at = now
        item.last_job_id = job.id
        item.next_run_at = schedules.next_run(item.schedule, now, item.timezone)
        created.append(job.id)
    return created
