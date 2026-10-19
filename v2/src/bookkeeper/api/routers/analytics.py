"""Operating reports: generic aggregate query and presets (summary, operations, sales, fees, …)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from bookkeeper.api.deps import AuthDep, DbDep, run_read
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import analytics as service

router = APIRouter(prefix="/books/{book_id}/reports", tags=["reports"])

ListParam = Annotated[list[str], Query(description="可重复传参，或用逗号分隔")]
Period = Literal["year", "quarter", "month", "week", "day"]


def _split(values: list[str]) -> list[str]:
    return [part.strip() for value in values for part in value.split(",") if part.strip()]


@router.get("")
def catalogue(book_id: str, auth: AuthDep) -> dict[str, Any]:
    """Available reports with their parameters; every report row carries a ``drilldown``."""
    auth.ctx.require(Scope.LEDGER_READ)
    return {"data": service.CATALOGUE, "meta": {"request_id": auth.ctx.request_id}, "warnings": []}


@router.get("/query")
def query(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    date_from: date,
    date_to: date,
    group_by: ListParam = [],  # noqa: B006 - FastAPI query default
    measures: ListParam = ["base_amount", "count"],  # noqa: B006
    accounts: ListParam = [],  # noqa: B006
    classifications: ListParam = [],  # noqa: B006
    channels: ListParam = [],  # noqa: B006
    counterparties: ListParam = [],  # noqa: B006
    transaction_types: ListParam = [],  # noqa: B006
    line_roles: ListParam = [],  # noqa: B006
    commodities: ListParam = [],  # noqa: B006
    tags: ListParam = [],  # noqa: B006
    sign: Literal["natural", "debit"] = "natural",
    as_known_at: datetime | None = None,
) -> dict[str, Any]:
    q = service.Query(
        date_from=date_from,
        date_to=date_to,
        group_by=_split(group_by),
        measures=_split(measures),
        accounts=_split(accounts),
        classifications=_split(classifications),
        channels=_split(channels),
        counterparties=_split(counterparties),
        transaction_types=_split(transaction_types),
        line_roles=_split(line_roles),
        commodities=_split(commodities),
        tags=_split(tags),
        sign=sign,
        as_known_at=as_known_at,
    )
    return run_read(db, lambda: service.aggregate(db, auth.ctx, q), auth.ctx)


@router.get("/income-statement")
def income_statement(
    book_id: str, auth: AuthDep, db: DbDep, date_from: date, date_to: date, columns: Period | None = None
) -> dict[str, Any]:
    return run_read(db, lambda: service.income_statement(db, auth.ctx, date_from, date_to, columns), auth.ctx)


@router.get("/operations")
def operations(
    book_id: str, auth: AuthDep, db: DbDep, date_from: date, date_to: date, period: Period = "day"
) -> dict[str, Any]:
    return run_read(db, lambda: service.operations(db, auth.ctx, date_from, date_to, period), auth.ctx)


@router.get("/sales")
def sales(
    book_id: str, auth: AuthDep, db: DbDep, date_from: date, date_to: date, period: Period | None = None
) -> dict[str, Any]:
    return run_read(db, lambda: service.sales(db, auth.ctx, date_from, date_to, period), auth.ctx)


@router.get("/fees")
def fees(book_id: str, auth: AuthDep, db: DbDep, date_from: date, date_to: date) -> dict[str, Any]:
    return run_read(db, lambda: service.fees(db, auth.ctx, date_from, date_to), auth.ctx)


@router.get("/credit-purchases")
def credit_purchases(
    book_id: str, auth: AuthDep, db: DbDep, date_from: date, date_to: date, period: Period | None = None
) -> dict[str, Any]:
    return run_read(db, lambda: service.credit_purchases(db, auth.ctx, date_from, date_to, period), auth.ctx)


@router.get("/summary")
def summary(book_id: str, auth: AuthDep, db: DbDep, date_from: date, date_to: date) -> dict[str, Any]:
    return run_read(db, lambda: service.summary(db, auth.ctx, date_from, date_to), auth.ctx)
