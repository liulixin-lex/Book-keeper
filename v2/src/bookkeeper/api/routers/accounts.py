"""Chart of accounts."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_read, run_write
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import accounts as service

router = APIRouter(prefix="/books/{book_id}/accounts", tags=["accounts"])

Classification = Literal["asset", "liability", "equity", "revenue", "expense"]


class AccountFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=40)
    role: str | None = None
    is_group: bool | None = None
    allowed_commodities: list[str] | None = None
    open_date: date | None = None
    close_date: date | None = None
    balance_rule: Literal["any", "normal_side_only"] | None = None
    manual_entry_allowed: bool | None = None
    required_dimensions: list[str] | None = None
    forbidden_dimensions: list[str] | None = None
    standard_code: str | None = None
    is_active: bool | None = None
    description: str | None = Field(default=None, max_length=200)


class AccountCreate(AccountFields):
    code: str = Field(pattern=r"^[0-9]{4}(\.[0-9]{2})*$")
    name: str = Field(min_length=1, max_length=40)
    classification: Classification | None = None


class AccountPatch(AccountFields):
    expected_version: int


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: str = "small_enterprise_v1"


@router.get("")
def list_accounts(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    q: str | None = None,
    role: str | None = None,
    classification: str | None = None,
    postable_only: bool = False,
) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)

    def load() -> list[dict[str, Any]]:
        items = service.list_accounts(
            db, book_id, query=q, role=role, classification=classification, postable_only=postable_only
        )
        codes = {a.id: a.code for a in service.list_accounts(db, book_id)}
        return [service.account_view(a, codes.get(a.parent_id or "")) for a in items]

    return run_read(db, load, auth.ctx)


@router.post("", status_code=201)
def create_account(
    book_id: str, body: AccountCreate, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    data = body.model_dump(exclude_unset=True)
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "accounts.create",
        body.model_dump(mode="json", exclude_unset=True),
        lambda: service.account_view(service.create_account(db, auth.ctx, data)),
        status_code=201,
    )


@router.post(":apply-template")
def apply_template(
    book_id: str, body: TemplateIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "accounts.apply_template",
        body.model_dump(),
        lambda: {"created": [a.code for a in service.apply_template(db, auth.ctx, body.template)]},
    )


@router.get("/{account_ref}")
def get_account(book_id: str, account_ref: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)

    def load() -> dict[str, Any]:
        item = service.get_account(db, book_id, account_ref)
        balances = [
            {
                "commodity": b.commodity,
                "balance": b.balance,
                "base_balance": b.base_balance,
                "debit_total": b.debit_total,
                "credit_total": b.credit_total,
                "line_count": b.line_count,
            }
            for b in service.current_balances(db, item.id)
        ]
        return service.account_view(item) | {"balances": balances}

    return run_read(db, load, auth.ctx)


@router.patch("/{account_ref}")
def update_account(
    book_id: str,
    account_ref: str,
    body: AccountPatch,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "accounts.update",
        body.model_dump(mode="json", exclude_unset=True),
        lambda: service.account_view(service.update_account(db, auth.ctx, account_ref, body.expected_version, changes)),
    )
