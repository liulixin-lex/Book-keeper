"""Transaction type catalogue and fee rules."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_read, run_write
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import business, fees
from bookkeeper.services.inputs import FeeRuleIn

router = APIRouter(prefix="/books/{book_id}", tags=["business"])


@router.get("/transaction-types")
def transaction_types(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    """How to enter each type: input schema, an example request and the default accounts."""
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(db, lambda: business.catalogue(db, book_id), auth.ctx)


@router.get("/fee-rules")
def list_fee_rules(book_id: str, auth: AuthDep, db: DbDep, include_retired: bool = False) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(db, lambda: [fees.view(r) for r in fees.list_rules(db, book_id, include_retired)], auth.ctx)


@router.post("/fee-rules", status_code=201)
def save_fee_rule(
    book_id: str, body: FeeRuleIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Create a rule or a new version (same code, later valid_from). Existing postings keep their
    fee until reposted: POST transactions:repost."""

    def apply() -> dict[str, Any]:
        return fees.view(fees.save_rule(db, auth.ctx, body.model_dump()))

    return run_write(
        request, db, auth.ctx, settings, "fee_rules.save", body.model_dump(mode="json"), apply, status_code=201
    )


@router.post("/fee-rules/{code}:retire")
def retire_fee_rule(
    book_id: str, code: str, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    def apply() -> list[dict[str, Any]]:
        return [fees.view(r) for r in fees.retire(db, auth.ctx, code)]

    return run_write(request, db, auth.ctx, settings, "fee_rules.retire", {"code": code}, apply)


@router.get("/fee-rules:evaluate")
def evaluate_fee(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    type: Literal["sale", "credit_purchase", "expense", "transfer", "sale_refund"],
    amount: Annotated[str, Query(description="计费基数：销售毛额、采购面值、支出金额、转出金额或退款金额")],
    on: date,
    channel: str | None = None,
    counterparty: str | None = None,
    commodity: str = "CNY",
) -> dict[str, Any]:
    """Which rule applies and the fee it gives — the same selection used when posting."""
    auth.ctx.require(Scope.LEDGER_READ)

    def load() -> dict[str, Any]:
        return fees.evaluate(db, book_id, type, amount, on, channel, counterparty, commodity)

    return run_read(db, load, auth.ctx)
