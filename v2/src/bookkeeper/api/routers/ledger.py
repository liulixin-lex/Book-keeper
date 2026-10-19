"""Journal entries, balances, trial balance, health checks."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_read, run_write
from bookkeeper.db.models import CheckRun
from bookkeeper.domain.errors import not_found
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import checks, reports
from bookkeeper.services import transactions as txn_service

router = APIRouter(prefix="/books/{book_id}", tags=["ledger"])


class ChecksIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codes: list[str] | None = None


@router.get("/journal-entries")
def list_entries(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    after_seq: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_lines: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    def load() -> list[dict[str, Any]]:
        entries = reports.list_entries(
            db, auth.ctx, after_seq=after_seq, date_from=date_from, date_to=date_to, limit=limit
        )
        lines = txn_service.entry_lines_view(db, [e.id for e in entries]) if include_lines else {}
        return [txn_service.entry_view(e, lines.get(e.id) if include_lines else None) for e in entries]

    return run_read(db, load, auth.ctx)


@router.get("/journal-entries/{ref}")
def get_entry(book_id: str, ref: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    def load() -> dict[str, Any]:
        entry = reports.get_entry(db, auth.ctx, ref)
        return txn_service.entry_view(entry, txn_service.entry_lines_view(db, [entry.id]).get(entry.id, []))

    return run_read(db, load, auth.ctx)


@router.get("/balances")
def get_balances(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    as_of: date,
    accounts: Annotated[list[str] | None, Query()] = None,
    as_known_at: datetime | None = None,
) -> dict[str, Any]:
    return run_read(db, lambda: reports.balances(db, auth.ctx, as_of, accounts, as_known_at), auth.ctx)


@router.get("/reports/trial-balance")
def trial_balance(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    date_from: date,
    date_to: date,
    as_known_at: datetime | None = None,
    include_zero: bool = False,
) -> dict[str, Any]:
    return run_read(
        db, lambda: reports.trial_balance(db, auth.ctx, date_from, date_to, as_known_at, include_zero), auth.ctx
    )


@router.post("/checks:run")
def run_checks(
    book_id: str, body: ChecksIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "checks.run",
        body.model_dump(),
        lambda: checks.run_view(db, checks.run_checks(db, auth.ctx, body.codes)),
    )


@router.get("/check-runs")
def list_check_runs(
    book_id: str, auth: AuthDep, db: DbDep, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    query = select(CheckRun).where(CheckRun.book_id == book_id).order_by(CheckRun.started_at.desc()).limit(limit)
    return run_read(
        db,
        lambda: [
            {
                "id": r.id,
                "trigger": r.trigger,
                "status": r.status,
                "started_at": r.started_at.isoformat(),
                "summary": r.summary,
            }
            for r in db.execute(query).scalars()
        ],
        auth.ctx,
    )


@router.get("/check-runs/{run_id}")
def get_check_run(book_id: str, run_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)

    def load() -> dict[str, Any]:
        run = db.get(CheckRun, run_id)
        if run is None or run.book_id != book_id:
            raise not_found("检查记录", run_id)
        return checks.run_view(db, run)

    return run_read(db, load, auth.ctx)
