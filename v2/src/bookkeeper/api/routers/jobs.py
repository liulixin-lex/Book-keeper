"""Job status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from bookkeeper.api.deps import AuthDep, DbDep, run_read
from bookkeeper.db.models import Job
from bookkeeper.domain.errors import not_found
from bookkeeper.domain.scopes import Scope

router = APIRouter(prefix="/books/{book_id}/jobs", tags=["jobs"])


def job_view(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "run_after": job.run_after.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "last_error": job.last_error,
        "result": job.result,
    }


@router.get("/{job_id}")
def get_job(book_id: str, job_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)

    def load() -> dict[str, Any]:
        job = db.get(Job, job_id)
        if job is None or job.book_id != book_id:
            raise not_found("任务", job_id)
        return job_view(job)

    return run_read(db, load, auth.ctx)
