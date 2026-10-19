"""Commodities, price rules, FX rates, dimensions, counterparties."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_read, run_write
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import reference as service

router = APIRouter(prefix="/books/{book_id}", tags=["reference"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriceRuleIn(Strict):
    commodity: str
    quote_commodity: str
    rate: str
    purpose: Literal["nominal_valuation", "conversion"]
    valid_from: date
    valid_to: date | None = None
    note: str | None = Field(default=None, max_length=200)


class FxRateIn(Strict):
    base: str
    quote: str
    rate_date: date
    rate: str


class DimensionTypeIn(Strict):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")
    name: str = Field(min_length=1, max_length=40)
    is_hierarchical: bool = False


class DimensionValueIn(Strict):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,47}$")
    name: str = Field(min_length=1, max_length=60)
    aliases: list[str] = Field(default_factory=list, description="其他叫法，录入时与名称、代码同样可用")
    parent_id: str | None = None
    counterparty_id: str | None = None


class DimensionValuePatch(Strict):
    expected_version: int
    name: str | None = Field(default=None, min_length=1, max_length=60)
    aliases: list[str] | None = Field(default=None, description="整体替换别名")
    is_active: bool | None = None
    parent_id: str | None = None
    counterparty_id: str | None = None


class CommodityIn(Strict):
    code: str = Field(description="代码，2–12 位大写字母 / 数字，如 JPY、USDT")
    name: str = Field(min_length=1, max_length=40)
    kind: Literal["fiat", "credit", "other"] = Field(
        default="fiat", description="fiat 法币（自动获取参考汇率）、credit 额度"
    )
    scale: int = Field(default=2, ge=0, le=8, description="小数位：日元 0，多数法币 2")
    symbol: str | None = Field(default=None, max_length=8)


class CommodityPatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    kind: Literal["fiat", "credit", "other"] | None = None
    scale: int | None = Field(default=None, ge=0, le=8, description="仅在该币种还没有任何金额时可改")
    symbol: str | None = Field(default=None, max_length=8)
    is_active: bool | None = Field(default=None, description="停用后不能用于新的金额，已有记录不受影响")


class CounterpartyIn(Strict):
    name: str = Field(min_length=1, max_length=80)
    category: str
    roles: list[Literal["customer", "supplier"]] = ["supplier"]
    domains: list[str] = []
    aliases: list[str] = []
    notes: str | None = Field(default=None, max_length=500)
    default_type: Literal["sale", "credit_purchase", "expense", "purchase_refund", "sale_refund"] | None = Field(
        default=None, description="录入或导入省略交易类型时使用"
    )
    default_channel: str | None = Field(default=None, description="省略渠道时使用（代码、名称或别名）")


class CounterpartyPatch(Strict):
    expected_version: int
    name: str | None = Field(default=None, min_length=1, max_length=80)
    category: str | None = None
    roles: list[Literal["customer", "supplier"]] | None = None
    domains: list[str] | None = None
    notes: str | None = None
    is_active: bool | None = None
    default_type: Literal["sale", "credit_purchase", "expense", "purchase_refund", "sale_refund"] | None = Field(
        default=None, description="录入或导入省略交易类型时使用；传 null 清除"
    )
    default_channel: str | None = Field(default=None, description="省略渠道时使用；传 null 清除")


class AliasIn(Strict):
    pattern: str = Field(min_length=1, max_length=200)
    match_type: Literal["exact", "contains", "regex", "domain"] = "exact"
    priority: int = Field(default=100, ge=0, le=1000)


class CounterpartyAccountIn(Strict):
    label: str = Field(min_length=1, max_length=40)
    identifier: str | None = Field(default=None, max_length=200)


@router.get("/commodities")
def list_commodities(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(db, lambda: [service.commodity_view(c) for c in service.commodities_by_code(db).values()], auth.ctx)


@router.post("/commodities", status_code=201)
def create_commodity(
    book_id: str, body: CommodityIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Add a currency or unit; it is shared by all books."""
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "commodities.create",
        body.model_dump(),
        lambda: service.commodity_view(service.create_commodity(db, auth.ctx, **body.model_dump())),
        status_code=201,
    )


@router.patch("/commodities/{code}")
def update_commodity(
    book_id: str, code: str, body: CommodityPatch, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    changes = body.model_dump(exclude_unset=True)
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "commodities.update",
        changes | {"code": code},
        lambda: service.commodity_view(service.update_commodity(db, auth.ctx, code, changes)),
    )


@router.get("/commodity-price-rules")
def list_price_rules(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(db, lambda: [service.price_rule_view(r) for r in service.list_price_rules(db, auth.ctx)], auth.ctx)


@router.post("/commodity-price-rules", status_code=201)
def create_price_rule(
    book_id: str, body: PriceRuleIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "price_rules.create",
        body.model_dump(mode="json"),
        lambda: service.price_rule_view(service.create_price_rule(db, auth.ctx, **body.model_dump())),
        status_code=201,
    )


@router.get("/fx-rates")
def list_fx_rates(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    base: str | None = None,
    quote: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(
        db,
        lambda: [
            service.fx_rate_view(r)
            for r in service.list_fx_rates(
                db, base=base, quote=quote, date_from=date_from, date_to=date_to, limit=limit
            )
        ],
        auth.ctx,
    )


@router.post("/fx-rates", status_code=201)
def add_fx_rate(
    book_id: str, body: FxRateIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "fx_rates.manual",
        body.model_dump(mode="json"),
        lambda: service.fx_rate_view(service.add_manual_rate(db, auth.ctx, **body.model_dump())),
        status_code=201,
    )


@router.get("/dimensions")
def list_dimensions(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(
        db,
        lambda: [
            service.dimension_type_view(t) | {"values": [service.dimension_value_view(v, t.code) for v in values]}
            for t, values in service.list_dimensions(db, book_id)
        ],
        auth.ctx,
    )


@router.post("/dimension-types", status_code=201)
def create_dimension_type(
    book_id: str, body: DimensionTypeIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "dimension_types.create",
        body.model_dump(),
        lambda: service.dimension_type_view(service.create_dimension_type(db, auth.ctx, **body.model_dump())),
        status_code=201,
    )


@router.post("/dimension-types/{type_code}/values", status_code=201)
def create_dimension_value(
    book_id: str,
    type_code: str,
    body: DimensionValueIn,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "dimension_values.create",
        body.model_dump() | {"type": type_code},
        lambda: service.dimension_value_view(
            service.create_dimension_value(db, auth.ctx, type_code=type_code, **body.model_dump()), type_code
        ),
        status_code=201,
    )


@router.patch("/dimension-values/{value_id}")
def update_dimension_value(
    book_id: str,
    value_id: str,
    body: DimensionValuePatch,
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
        "dimension_values.update",
        body.model_dump(exclude_unset=True),
        lambda: service.dimension_value_view(
            service.update_dimension_value(db, auth.ctx, value_id, body.expected_version, changes)
        ),
    )


@router.get("/counterparties")
def list_counterparties(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    q: str | None = None,
    category: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(
        db,
        lambda: [
            service.counterparty_details(db, c) for c in service.list_counterparties(db, book_id, q, category, limit)
        ],
        auth.ctx,
    )


@router.get("/counterparties:resolve")
def resolve_counterparty(
    book_id: str, auth: AuthDep, db: DbDep, text: Annotated[str, Query(min_length=1, max_length=500)]
) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(db, lambda: service.resolve_counterparty_text(db, book_id, text), auth.ctx)


@router.get("/counterparties/{counterparty_id}")
def get_counterparty(book_id: str, counterparty_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(
        db, lambda: service.counterparty_details(db, service.get_counterparty(db, book_id, counterparty_id)), auth.ctx
    )


@router.post("/counterparties", status_code=201)
def create_counterparty(
    book_id: str, body: CounterpartyIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    def apply() -> dict[str, Any]:
        item = service.create_counterparty(db, auth.ctx, **body.model_dump())
        return service.counterparty_details(db, item)

    return run_write(
        request, db, auth.ctx, settings, "counterparties.create", body.model_dump(), apply, status_code=201
    )


@router.patch("/counterparties/{counterparty_id}")
def update_counterparty(
    book_id: str,
    counterparty_id: str,
    body: CounterpartyPatch,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})

    def apply() -> dict[str, Any]:
        item = service.update_counterparty(db, auth.ctx, counterparty_id, body.expected_version, changes)
        return service.counterparty_details(db, item)

    return run_write(
        request, db, auth.ctx, settings, "counterparties.update", body.model_dump(exclude_unset=True), apply
    )


@router.post("/counterparties/{counterparty_id}/aliases", status_code=201)
def add_alias(
    book_id: str, counterparty_id: str, body: AliasIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    def apply() -> dict[str, Any]:
        alias = service.add_alias(db, auth.ctx, counterparty_id, body.pattern, body.match_type, body.priority)
        return {"id": alias.id, "pattern": alias.pattern, "match_type": alias.match_type, "priority": alias.priority}

    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "counterparties.alias",
        body.model_dump() | {"cp": counterparty_id},
        apply,
        status_code=201,
    )


@router.post("/counterparties/{counterparty_id}/accounts", status_code=201)
def add_counterparty_account(
    book_id: str,
    counterparty_id: str,
    body: CounterpartyAccountIn,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    def apply() -> dict[str, Any]:
        account = service.add_counterparty_account(db, auth.ctx, counterparty_id, body.label, body.identifier)
        return {"id": account.id, "label": account.label, "identifier": "[redacted]" if account.identifier else None}

    payload = {"label": body.label, "cp": counterparty_id}
    return run_write(request, db, auth.ctx, settings, "counterparties.account", payload, apply, status_code=201)


@router.get("/tags")
def list_tags(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    """Tags in use with their transaction counts (set them on transactions via create / PATCH ``tags``)."""
    from bookkeeper.services import tags

    return run_read(db, lambda: tags.list_tags(db, auth.ctx), auth.ctx)
