"""Transactions: record (single or batch), edit, delete, restore, re-run fee rules.

Every write takes effect at once and can be tried first with ``?dry_run=true``; edits and deletes
append to the ledger, so ``change-sets/{id}:undo`` or ``:restore`` bring things back.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_operation, run_read
from bookkeeper.api.envelope import envelope
from bookkeeper.api.pagination import decode_cursor, encode_cursor
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import transactions as service
from bookkeeper.services.inputs import BatchIn, DeleteIn, RepostIn, RestoreIn, TransactionIn, TransactionPatch

router = APIRouter(prefix="/books/{book_id}/transactions", tags=["transactions"])


@router.get("")
def list_transactions(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    status: Annotated[
        Literal["posted", "reversed"], Query(description="posted 正常（默认）；reversed 已删除")
    ] = "posted",
    type: Annotated[
        str | None, Query(description="交易类型代码；多个用逗号分隔，如 sale_refund,purchase_refund")
    ] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    counterparty: str | None = None,
    q: str | None = None,
    created_channel: str | None = None,
    channel: Annotated[str | None, Query(description="渠道代码")] = None,
    account: Annotated[str | None, Query(description="科目编码（含下级科目）")] = None,
    amount_min: Annotated[int | None, Query(description="金额下限，最小单位（分）")] = None,
    amount_max: Annotated[int | None, Query(description="金额上限，最小单位（分）")] = None,
    is_estimate: bool | None = None,
    linked_to: Annotated[str | None, Query(description="与该交易有关联（退款）的交易")] = None,
    tag: Annotated[str | None, Query(description="带有该标签的交易")] = None,
    commodity: Annotated[
        str | None, Query(description="有该币种分录行的交易（与 account 同时给出时限定在该科目）")
    ] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    position = decode_cursor(cursor)
    with db.begin():
        rows = service.search(
            db,
            auth.ctx,
            status=status,
            type_code=type,
            date_from=date_from,
            date_to=date_to,
            counterparty=counterparty,
            text=q,
            created_channel=created_channel,
            cursor=(position["d"], position["id"]) if position else None,
            limit=limit,
            channel=channel,
            account=account,
            amount_min=amount_min,
            amount_max=amount_max,
            is_estimate=is_estimate,
            linked_to=linked_to,
            tag=tag,
            commodity=commodity,
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        data = [service.header_view(t, code) for t, code in rows]
    meta = {
        "has_more": has_more,
        "next_cursor": encode_cursor({"d": rows[-1][0].effective_date.isoformat(), "id": rows[-1][0].id})
        if has_more
        else None,
    }
    return envelope(data, auth.ctx, meta=meta)


@router.post("", status_code=201)
def create_transaction(
    book_id: str, body: TransactionIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    raw = body.model_dump(mode="json", exclude_unset=True)
    return run_operation(request, db, auth.ctx, settings, "transactions.create", raw, status_code=201)


@router.post(":batch")
def create_batch(
    book_id: str, body: BatchIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Record up to 200 transactions in one call. Results keep input order."""
    raw = body.model_dump(mode="json", exclude_unset=True)
    return run_operation(request, db, auth.ctx, settings, "transactions.batch", raw)


@router.post(":repost")
def repost_transactions(
    book_id: str, body: RepostIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Re-run fee rules and rates on sales / credit purchases; append ?dry_run=true to see the effect first."""
    return run_operation(request, db, auth.ctx, settings, "transactions.repost", body.model_dump(mode="json"))


@router.get("/{ref}")
def get_transaction(book_id: str, ref: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)

    def load() -> dict[str, Any]:
        txn, code = service.load(db, auth.ctx, ref)
        return service.full_view(db, txn, code)

    return run_read(db, load, auth.ctx)


@router.get("/{ref}/explain")
def explain_transaction(book_id: str, ref: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    """How the inputs became journal lines: resolved inputs, fee rule candidates and reasons, lines, links."""
    auth.ctx.require(Scope.LEDGER_READ)

    def load() -> dict[str, Any]:
        txn, code = service.load(db, auth.ctx, ref)
        return service.explain(db, txn, code)

    return run_read(db, load, auth.ctx)


@router.patch("/{ref}")
def edit_transaction(
    book_id: str, ref: str, body: TransactionPatch, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Change any field; ``inputs`` only needs the changed keys. Affects the books → re-posted in place."""
    raw = body.model_dump(mode="json", exclude_unset=True) | {"ref": ref}
    return run_operation(request, db, auth.ctx, settings, "transactions.edit", raw)


@router.delete("/{ref}")
def delete_transaction(
    book_id: str,
    ref: str,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    body: DeleteIn | None = None,
) -> JSONResponse:
    """Delete (the entry is reversed; history stays). ``:restore`` or undoing the change set brings it back."""
    raw = (body.model_dump(mode="json", exclude_unset=True) if body else {}) | {"ref": ref}
    return run_operation(request, db, auth.ctx, settings, "transactions.delete", raw)


@router.post("/{ref}:restore")
def restore_transaction(
    book_id: str,
    ref: str,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    body: RestoreIn | None = None,
) -> JSONResponse:
    """Bring back a deleted transaction with the lines it had."""
    raw = (body.model_dump(mode="json", exclude_unset=True) if body else {}) | {"ref": ref}
    return run_operation(request, db, auth.ctx, settings, "transactions.restore", raw)
