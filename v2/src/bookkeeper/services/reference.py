"""Reference data: commodities, price rules, FX rates, dimensions, counterparties."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bookkeeper.db.models import (
    Book,
    Commodity,
    CommodityPriceRule,
    Counterparty,
    CounterpartyAccount,
    CounterpartyAlias,
    DimensionType,
    DimensionValue,
    FxRate,
    Transaction,
    TransactionType,
)
from bookkeeper.domain.errors import DomainError, not_found, version_conflict
from bookkeeper.domain.fx import DEFAULT_PIVOTS, FxQuote, PriceRule, RateRecord, select_rate
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.money import AmountError, parse_decimal
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import audit
from bookkeeper.services.context import RequestContext

COUNTERPARTY_CATEGORIES = (
    "upstream_site",
    "ai_vendor",
    "cloud_vendor",
    "marketplace",
    "payment_provider",
    "marketing_vendor",
    "business_service",
    "customer",
    "other",
)


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


# ------------------------------------------------------------------ commodities & rates


def commodity_view(item: Commodity) -> dict[str, Any]:
    return {
        "code": item.code,
        "name": item.name,
        "kind": item.kind,
        "scale": item.scale,
        "symbol": item.symbol,
        "is_active": item.is_active,
    }


def commodity_scales(session: Session) -> dict[str, int]:
    """Every commodity (also disabled ones: existing amounts must still render)."""
    return {c: s for c, s in session.execute(select(Commodity.code, Commodity.scale)).all()}


def active_scales(session: Session) -> dict[str, int]:
    """Commodities that new amounts may use."""
    return {
        c: s
        for c, s in session.execute(select(Commodity.code, Commodity.scale).where(Commodity.is_active.is_(True))).all()
    }


def unknown_commodity(code: str) -> str:
    return f"币种 {code} 不存在或已停用（可用 get_reference kind=commodities 查看，或先新增该币种）"


COMMODITY_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,11}$")
COMMODITY_KINDS = ("fiat", "credit", "other")


def commodity_in_use(session: Session, code: str) -> bool:
    """Whether any stored amount is expressed in this commodity's minor units."""
    checks = (
        "SELECT 1 FROM journal_lines WHERE commodity = :c",
        "SELECT 1 FROM source_records WHERE commodity = :c",
        "SELECT 1 FROM fee_rules WHERE commodity = :c",
        "SELECT 1 FROM transactions WHERE inputs::text LIKE :p",
    )
    params = {"c": code, "p": f'%"commodity": "{code}"%'}
    return any(session.execute(text(sql + " LIMIT 1"), params).first() for sql in checks)


def create_commodity(
    session: Session,
    ctx: RequestContext,
    *,
    code: str,
    name: str,
    kind: str = "fiat",
    scale: int = 2,
    symbol: str | None = None,
) -> Commodity:
    """Add a currency or unit (shared by all books). Fiat currencies get daily reference rates automatically."""
    ctx.require(Scope.CONFIG_WRITE)
    code = code.strip().upper()
    if not COMMODITY_CODE.match(code):
        raise DomainError("VALIDATION_FAILED", "币种代码须为 2–12 位大写字母、数字或下划线，以字母开头（如 JPY）。")
    if kind not in COMMODITY_KINDS:
        raise DomainError("VALIDATION_FAILED", "类别只能是 fiat（法币）、credit（额度）或 other（其他）。")
    if not 0 <= scale <= 8:
        raise DomainError("VALIDATION_FAILED", "小数位须在 0–8 之间（日元 0，多数法币 2）。")
    if session.get(Commodity, code) is not None:
        raise DomainError("CONFLICT", f"币种 {code} 已存在；如需修改请用更新。")
    item = Commodity(code=code, name=name.strip(), kind=kind, scale=scale, symbol=(symbol or "").strip() or None)
    session.add(item)
    session.flush()
    audit.record(session, ctx, "commodity.create", "commodity", code, after=commodity_view(item))
    return item


def update_commodity(session: Session, ctx: RequestContext, code: str, changes: dict[str, Any]) -> Commodity:
    """Name, symbol, kind, enabled; the number of decimals only while nothing uses the commodity."""
    ctx.require(Scope.CONFIG_WRITE)
    item = session.get(Commodity, code.strip().upper(), with_for_update=True)
    if item is None:
        raise not_found("币种", code)
    before = commodity_view(item)
    unknown = set(changes) - {"name", "symbol", "kind", "scale", "is_active"}
    if unknown:
        raise DomainError("VALIDATION_FAILED", f"不可修改的字段：{', '.join(sorted(unknown))}。")
    if "scale" in changes and changes["scale"] != item.scale:
        if not 0 <= int(changes["scale"]) <= 8:
            raise DomainError("VALIDATION_FAILED", "小数位须在 0–8 之间。")
        if commodity_in_use(session, item.code):
            raise DomainError("INVALID_STATE", f"币种 {item.code} 已有金额记录，小数位不能再修改。")
        item.scale = int(changes["scale"])
    if "kind" in changes:
        if changes["kind"] not in COMMODITY_KINDS:
            raise DomainError("VALIDATION_FAILED", "类别只能是 fiat、credit 或 other。")
        item.kind = changes["kind"]
    if changes.get("is_active") is False:
        bases = session.execute(select(Book.name).where(Book.base_commodity == item.code)).scalars().all()
        if bases:
            raise DomainError("INVALID_STATE", f"{item.code} 是账套 {'、'.join(bases)} 的本位币，不能停用。")
    for key in ("name", "symbol", "is_active"):
        if key in changes and changes[key] is not None:
            setattr(item, key, changes[key].strip() if isinstance(changes[key], str) else changes[key])
    session.flush()
    audit.record(session, ctx, "commodity.update", "commodity", item.code, before=before, after=commodity_view(item))
    return item


def commodities_by_code(session: Session) -> dict[str, Commodity]:
    return {c.code: c for c in session.execute(select(Commodity)).scalars()}


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = parse_decimal(value)
    except AmountError as exc:
        raise DomainError("VALIDATION_FAILED", f"{field}：{exc}") from exc
    if result <= 0:
        raise DomainError("VALIDATION_FAILED", f"{field} 必须大于 0。")
    return result


def price_rule_view(rule: CommodityPriceRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "commodity": rule.commodity,
        "quote_commodity": rule.quote_commodity,
        "rate": str(rule.rate),
        "purpose": rule.purpose,
        "valid_from": _iso(rule.valid_from),
        "valid_to": _iso(rule.valid_to),
        "note": rule.note,
    }


def create_price_rule(
    session: Session,
    ctx: RequestContext,
    *,
    commodity: str,
    quote_commodity: str,
    rate: object,
    purpose: str,
    valid_from: date,
    valid_to: date | None = None,
    note: str | None = None,
) -> CommodityPriceRule:
    ctx.require(Scope.CONFIG_WRITE)
    known = active_scales(session)
    for code in (commodity, quote_commodity):
        if code not in known:
            raise DomainError("VALIDATION_FAILED", unknown_commodity(code) + "。")
    rule = CommodityPriceRule(
        id=new_id("cpr"),
        book_id=ctx.require_book(),
        commodity=commodity,
        quote_commodity=quote_commodity,
        rate=_decimal(rate, "rate"),
        purpose=purpose,
        valid_from=valid_from,
        valid_to=valid_to,
        note=note,
        created_by=ctx.actor.user_id,
    )
    session.add(rule)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise DomainError("CONFLICT", "该币种对在此期间已有价格规则（区间不能重叠）。") from exc
    audit.record(
        session,
        ctx,
        "price_rule.create",
        "commodity_price_rule",
        rule.id,
        after=price_rule_view(rule),
    )
    return rule


def list_price_rules(session: Session, ctx: RequestContext) -> list[CommodityPriceRule]:
    return list(
        session.execute(
            select(CommodityPriceRule)
            .where(CommodityPriceRule.book_id == ctx.require_book())
            .order_by(CommodityPriceRule.commodity, CommodityPriceRule.valid_from)
        ).scalars()
    )


def fx_rate_view(rate: FxRate) -> dict[str, Any]:
    return {
        "id": rate.id,
        "base": rate.base,
        "quote": rate.quote,
        "rate_date": _iso(rate.rate_date),
        "rate": str(rate.rate),
        "rate_type": rate.rate_type,
        "source": rate.source,
        "fetched_at": _iso(rate.fetched_at),
    }


def upsert_fx_rate(
    session: Session,
    *,
    base: str,
    quote: str,
    rate_date: date,
    rate: Decimal,
    rate_type: str,
    source: str,
    created_by: str | None = None,
    raw: Any = None,
) -> FxRate:
    stmt = insert(FxRate).values(
        id=new_id("fxr"),
        base=base,
        quote=quote,
        rate_date=rate_date,
        rate=rate,
        rate_type=rate_type,
        source=source,
        created_by=created_by,
        raw=raw,
    )
    upsert = stmt.on_conflict_do_update(
        index_elements=["base", "quote", "rate_date", "rate_type", "source"],
        set_={
            "rate": stmt.excluded.rate,
            "raw": stmt.excluded.raw,
            "fetched_at": stmt.excluded.fetched_at,
        },
    ).returning(FxRate.id)
    rate_id = session.execute(upsert).scalar_one()
    item = session.get(FxRate, rate_id, populate_existing=True)
    assert item is not None
    return item


def add_manual_rate(
    session: Session, ctx: RequestContext, *, base: str, quote: str, rate_date: date, rate: object
) -> FxRate:
    ctx.require(Scope.CONFIG_WRITE)
    known = active_scales(session)
    if base not in known or quote not in known or base == quote:
        raise DomainError("VALIDATION_FAILED", "汇率的两种币种必须都已启用且不相同。")
    item = upsert_fx_rate(
        session,
        base=base,
        quote=quote,
        rate_date=rate_date,
        rate=_decimal(rate, "rate"),
        rate_type="manual",
        source="manual",
        created_by=ctx.actor.user_id,
    )
    audit.record(session, ctx, "fx_rate.manual", "fx_rate", item.id, after=fx_rate_view(item))
    return item


def list_fx_rates(
    session: Session,
    *,
    base: str | None,
    quote: str | None,
    date_from: date | None,
    date_to: date | None,
    limit: int = 200,
) -> list[FxRate]:
    query = select(FxRate)
    if base:
        query = query.where(FxRate.base == base)
    if quote:
        query = query.where(FxRate.quote == quote)
    if date_from:
        query = query.where(FxRate.rate_date >= date_from)
    if date_to:
        query = query.where(FxRate.rate_date <= date_to)
    return list(session.execute(query.order_by(FxRate.rate_date.desc(), FxRate.base).limit(limit)).scalars())


class QuoteProvider:
    """Loads candidate rates once per posting and answers ``quote_for(commodity)``."""

    def __init__(self, session: Session, book: Book, on: date) -> None:
        self.session = session
        self.book = book
        self.on = on
        self._cache: dict[str, FxQuote | None] = {}

    def __call__(self, commodity: str) -> FxQuote | None:
        if commodity not in self._cache:
            self._cache[commodity] = self._load(commodity)
        return self._cache[commodity]

    def _load(self, commodity: str) -> FxQuote | None:
        base = self.book.base_commodity
        earliest = self.on - timedelta(days=self.book.fx_lookback_days)
        involved = {commodity, base, *DEFAULT_PIVOTS}
        rows = self.session.execute(
            select(FxRate).where(
                FxRate.base.in_(involved),
                FxRate.quote.in_(involved),
                FxRate.rate_date.between(earliest, self.on),
            )
        ).scalars()
        records = [RateRecord(r.base, r.quote, r.rate_date, r.rate, r.rate_type, r.source, r.id) for r in rows]
        rules = [
            PriceRule(r.commodity, r.quote_commodity, r.rate, r.valid_from, r.valid_to, r.purpose, r.id)
            for r in self.session.execute(
                select(CommodityPriceRule).where(CommodityPriceRule.book_id == self.book.id)
            ).scalars()
        ]
        return select_rate(
            commodity,
            base,
            self.on,
            lookback_days=self.book.fx_lookback_days,
            records=records,
            price_rules=rules,
        )


# ------------------------------------------------------------------ dimensions


def dimension_type_view(item: DimensionType) -> dict[str, Any]:
    return {
        "id": item.id,
        "code": item.code,
        "name": item.name,
        "is_hierarchical": item.is_hierarchical,
        "is_active": item.is_active,
        "version": item.version,
    }


def dimension_value_view(item: DimensionValue, type_code: str | None = None) -> dict[str, Any]:
    return {
        "id": item.id,
        "type_id": item.type_id,
        "type_code": type_code,
        "code": item.code,
        "name": item.name,
        "aliases": value_aliases(item),
        "parent_id": item.parent_id,
        "counterparty_id": item.counterparty_id,
        "is_active": item.is_active,
        "version": item.version,
    }


def create_dimension_type(
    session: Session, ctx: RequestContext, *, code: str, name: str, is_hierarchical: bool = False
) -> DimensionType:
    ctx.require(Scope.CONFIG_WRITE)
    item = DimensionType(
        id=new_id("dmt"),
        book_id=ctx.require_book(),
        code=code,
        name=name,
        is_hierarchical=is_hierarchical,
    )
    session.add(item)
    _flush_unique(session, f"维度类型 {code} 已存在。")
    audit.record(
        session,
        ctx,
        "dimension_type.create",
        "dimension_type",
        item.id,
        after=dimension_type_view(item),
    )
    return item


def get_dimension_type(session: Session, book_id: str, code_or_id: str) -> DimensionType:
    item = session.execute(
        select(DimensionType).where(
            DimensionType.book_id == book_id,
            or_(DimensionType.code == code_or_id, DimensionType.id == code_or_id),
        )
    ).scalar_one_or_none()
    if item is None:
        raise not_found("维度类型", code_or_id)
    return item


def create_dimension_value(
    session: Session,
    ctx: RequestContext,
    *,
    type_code: str,
    code: str,
    name: str,
    parent_id: str | None = None,
    counterparty_id: str | None = None,
    aliases: Sequence[str] = (),
) -> DimensionValue:
    ctx.require(Scope.REFERENCE_WRITE)
    dim_type = get_dimension_type(session, ctx.require_book(), type_code)
    cleaned = _clean_aliases(session, dim_type, [code, name, *aliases], None)[2:]  # also rejects a taken name
    item = DimensionValue(
        id=new_id("dmv"),
        book_id=dim_type.book_id,
        type_id=dim_type.id,
        code=code,
        name=name,
        parent_id=parent_id,
        counterparty_id=counterparty_id,
        metadata_={"aliases": cleaned} if cleaned else {},
    )
    session.add(item)
    _flush_unique(session, f"维度 {type_code} 下已有代码 {code}。")
    audit.record(
        session,
        ctx,
        "dimension_value.create",
        "dimension_value",
        item.id,
        after=dimension_value_view(item, dim_type.code),
    )
    return item


def update_dimension_value(
    session: Session,
    ctx: RequestContext,
    value_id: str,
    expected_version: int,
    changes: dict[str, Any],
) -> DimensionValue:
    ctx.require(Scope.REFERENCE_WRITE)
    item = session.get(DimensionValue, value_id, with_for_update=True)
    if item is None or item.book_id != ctx.require_book():
        raise not_found("维度值", value_id)
    if item.version != expected_version:
        raise version_conflict("维度值", expected_version, item.version)
    before = dimension_value_view(item)
    old_name = item.name
    for key in ("name", "is_active", "parent_id", "counterparty_id"):
        if key in changes:
            setattr(item, key, changes[key])
    if "aliases" in changes:
        dim_type = session.get(DimensionType, item.type_id)
        assert dim_type is not None
        item.metadata_ = dict(item.metadata_ or {}) | {
            "aliases": _clean_aliases(session, dim_type, changes["aliases"] or [], item.id)
        }
    item.version += 1
    session.flush()
    if item.name != old_name:
        dim_type = session.get(DimensionType, item.type_id)
        if dim_type is not None and dim_type.code == "channel":
            _follow_rename(session, ctx, old_name, item.name, channel_id=item.id)
    audit.record(
        session,
        ctx,
        "dimension_value.update",
        "dimension_value",
        item.id,
        before=before,
        after=dimension_value_view(item),
    )
    return item


def list_dimensions(session: Session, book_id: str) -> list[tuple[DimensionType, list[DimensionValue]]]:
    types = list(
        session.execute(
            select(DimensionType).where(DimensionType.book_id == book_id).order_by(DimensionType.code)
        ).scalars()
    )
    values = list(
        session.execute(
            select(DimensionValue).where(DimensionValue.book_id == book_id).order_by(DimensionValue.code)
        ).scalars()
    )
    return [(t, [v for v in values if v.type_id == t.id]) for t in types]


def _label_key(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().casefold()


def value_aliases(item: DimensionValue) -> list[str]:
    return [str(a) for a in (item.metadata_ or {}).get("aliases") or []]


def find_dimension_value(session: Session, dim_type: DimensionType, ref: str) -> DimensionValue:
    """A value by code or ID, else by name or alias (case- and width-insensitive). Ambiguity is an error."""
    exact = session.execute(
        select(DimensionValue).where(
            DimensionValue.type_id == dim_type.id, or_(DimensionValue.code == ref, DimensionValue.id == ref)
        )
    ).scalar_one_or_none()
    if exact is not None:
        return exact
    key = _label_key(ref)
    values = list(session.execute(select(DimensionValue).where(DimensionValue.type_id == dim_type.id)).scalars())
    found = [v for v in values if key in {_label_key(v.name), *(_label_key(a) for a in value_aliases(v))}]
    if len(found) == 1:
        return found[0]
    if found:
        raise DomainError(
            "AMBIGUOUS_REFERENCE",
            f"{dim_type.name}“{ref}”对应多个值，请改用代码：{'、'.join(v.code for v in found)}。",
            candidates=[{"code": v.code, "name": v.name} for v in found],
        )
    available = "、".join(f"{v.name}（{v.code}）" for v in values if v.is_active)
    raise DomainError("VALIDATION_FAILED", f"{dim_type.name}“{ref}”不存在。可用：{available or '无'}。")


def resolve_dimensions(session: Session, book_id: str, given: dict[str, str]) -> dict[str, str]:
    """{type_code: value code, ID, name or alias} → {type_code: value_id}; raises on unknown or inactive values."""
    result: dict[str, str] = {}
    for type_code, value_ref in given.items():
        dim_type = get_dimension_type(session, book_id, type_code)
        value = find_dimension_value(session, dim_type, value_ref)
        if not value.is_active:
            raise DomainError("VALIDATION_FAILED", f"{dim_type.name}“{value.name}”已停用。")
        result[dim_type.code] = value.id
    return result


def _clean_aliases(session: Session, dim_type: DimensionType, aliases: Sequence[str], own_id: str | None) -> list[str]:
    cleaned: list[str] = []
    for alias in aliases:
        alias = unicodedata.normalize("NFKC", alias).strip()
        if alias and alias not in cleaned:
            cleaned.append(alias)
    taken = {
        key: v.code
        for v in session.execute(select(DimensionValue).where(DimensionValue.type_id == dim_type.id)).scalars()
        if v.id != own_id
        for key in (_label_key(v.code), _label_key(v.name), *(_label_key(a) for a in value_aliases(v)))
    }
    clash = [a for a in cleaned if _label_key(a) in taken]
    if clash:
        raise DomainError(
            "CONFLICT", f"别名 {'、'.join(clash)} 已被 {taken[_label_key(clash[0])]} 使用（代码、名称或别名）。"
        )
    return cleaned


# ------------------------------------------------------------------ counterparties


def counterparty_view(
    item: Counterparty,
    aliases: Sequence[CounterpartyAlias] = (),
    accounts: Sequence[CounterpartyAccount] = (),
) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "category": item.category,
        "roles": list(item.roles),
        "domains": list(item.domains),
        "default_transaction_type_id": item.default_transaction_type_id,
        "default_dimensions": item.default_dimensions,
        "notes": item.notes,
        "is_active": item.is_active,
        "version": item.version,
        "aliases": [
            {"id": a.id, "pattern": a.pattern, "match_type": a.match_type, "priority": a.priority} for a in aliases
        ],
        "accounts": [
            {
                "id": a.id,
                "label": a.label,
                "is_active": a.is_active,
                "identifier": "[redacted]" if a.identifier else None,
            }
            for a in accounts
        ],
    }


def normalise_domain(value: str) -> str:
    host = value.strip().lower()
    host = re.sub(r"^[a-z]+://", "", host).split("/")[0].split(":")[0]
    return host.removeprefix("www.")


def create_counterparty(
    session: Session,
    ctx: RequestContext,
    *,
    name: str,
    category: str,
    roles: Sequence[str] = ("supplier",),
    domains: Sequence[str] = (),
    aliases: Sequence[str] = (),
    notes: str | None = None,
    default_type: str | None = None,
    default_channel: str | None = None,
) -> Counterparty:
    ctx.require(Scope.REFERENCE_WRITE)
    if category not in COUNTERPARTY_CATEGORIES:
        raise DomainError("VALIDATION_FAILED", f"往来方分类 {category} 无效。")
    bad_roles = set(roles) - {"customer", "supplier"}
    if bad_roles:
        raise DomainError("VALIDATION_FAILED", f"角色只能是 customer / supplier：{', '.join(sorted(bad_roles))}。")
    book_id = ctx.require_book()
    item = Counterparty(
        id=new_id("cpt"),
        book_id=book_id,
        name=name.strip(),
        category=category,
        roles=sorted(set(roles)),
        domains=sorted({normalise_domain(d) for d in domains if d.strip()}),
        notes=notes,
    )
    _set_defaults(
        session,
        item,
        {k: v for k, v in (("default_type", default_type), ("default_channel", default_channel)) if v is not None},
    )
    session.add(item)
    _flush_unique(session, f"往来方 {name} 已存在。")
    for domain in item.domains:
        _add_alias(session, item, domain, "domain")
    for alias in aliases:
        _add_alias(session, item, alias.strip(), "exact")
    audit.record(session, ctx, "counterparty.create", "counterparty", item.id, after=counterparty_view(item))
    return item


def _add_alias(
    session: Session, item: Counterparty, pattern: str, match_type: str, priority: int = 100
) -> CounterpartyAlias:
    if match_type == "regex":
        try:
            re.compile(pattern)
        except re.error as exc:
            raise DomainError("VALIDATION_FAILED", f"正则表达式无效：{exc}") from exc
    alias = CounterpartyAlias(
        id=new_id("cal"),
        book_id=item.book_id,
        counterparty_id=item.id,
        pattern=normalise_domain(pattern) if match_type == "domain" else pattern,
        match_type=match_type,
        priority=priority,
    )
    session.add(alias)
    _flush_unique(session, f"别名 {pattern} 已被其他往来方使用。")
    return alias


def add_alias(
    session: Session,
    ctx: RequestContext,
    counterparty_id: str,
    pattern: str,
    match_type: str,
    priority: int = 100,
) -> CounterpartyAlias:
    ctx.require(Scope.REFERENCE_WRITE)
    item = get_counterparty(session, ctx.require_book(), counterparty_id)
    alias = _add_alias(session, item, pattern, match_type, priority)
    audit.record(
        session,
        ctx,
        "counterparty.alias_add",
        "counterparty",
        item.id,
        after={"pattern": alias.pattern, "match_type": match_type},
    )
    return alias


def add_counterparty_account(
    session: Session,
    ctx: RequestContext,
    counterparty_id: str,
    label: str,
    identifier: str | None = None,
) -> CounterpartyAccount:
    ctx.require(Scope.REFERENCE_WRITE)
    item = get_counterparty(session, ctx.require_book(), counterparty_id)
    account = CounterpartyAccount(
        id=new_id("cpa"),
        book_id=item.book_id,
        counterparty_id=item.id,
        label=label,
        identifier=identifier,
    )
    session.add(account)
    _flush_unique(session, f"往来方 {item.name} 已有子账户 {label}。")
    audit.record(session, ctx, "counterparty.account_add", "counterparty", item.id, after={"label": label})
    return account


def get_counterparty(session: Session, book_id: str, ref: str) -> Counterparty:
    item = session.execute(
        select(Counterparty).where(
            Counterparty.book_id == book_id, or_(Counterparty.id == ref, Counterparty.name == ref)
        )
    ).scalar_one_or_none()
    if item is None:
        raise not_found("往来方", ref)
    return item


def update_counterparty(
    session: Session,
    ctx: RequestContext,
    counterparty_id: str,
    expected_version: int,
    changes: dict[str, Any],
) -> Counterparty:
    ctx.require(Scope.REFERENCE_WRITE)
    item = session.get(Counterparty, counterparty_id, with_for_update=True)
    if item is None or item.book_id != ctx.require_book():
        raise not_found("往来方", counterparty_id)
    if item.version != expected_version:
        raise version_conflict("往来方", expected_version, item.version)
    before = counterparty_view(item)
    old_name = item.name
    if "category" in changes and changes["category"] not in COUNTERPARTY_CATEGORIES:
        raise DomainError("VALIDATION_FAILED", "往来方分类无效。")
    for key in ("name", "category", "roles", "notes", "is_active"):
        if key in changes:
            setattr(item, key, changes[key])
    _set_defaults(session, item, changes)
    if "domains" in changes:
        item.domains = sorted({normalise_domain(d) for d in changes["domains"]})
    item.version += 1
    _flush_unique(session, "往来方名称已存在。")
    if item.name != old_name:
        _follow_rename(session, ctx, old_name, item.name, counterparty_id=item.id)
    audit.record(
        session,
        ctx,
        "counterparty.update",
        "counterparty",
        item.id,
        before=before,
        after=counterparty_view(item),
    )
    return item


def _follow_rename(
    session: Session, ctx: RequestContext, old: str, new: str, *, counterparty_id: str = "", channel_id: str = ""
) -> None:
    """Automatic descriptions name the party or the channel where the templates put them: "api.relay-a.example ·
    额度采购 · 面值 ¥10 · 链动", "链动 · API 额度销售". Carry a rename over to those nobody wrote by hand (no
    locked description), so the lists keep reading right without re-editing anything."""
    head, tail = f"{old} · ", f" · {old}"
    owner = (
        Transaction.counterparty_id == counterparty_id
        if counterparty_id
        else Transaction.inputs["channel_id"].astext == channel_id
    )
    rows = session.execute(
        select(Transaction, TransactionType.code)
        .join(TransactionType, TransactionType.id == Transaction.transaction_type_id)
        .where(
            Transaction.book_id == ctx.require_book(),
            owner,
            or_(
                Transaction.description.startswith(head, autoescape=True),
                Transaction.description.endswith(tail, autoescape=True),
            ),
        )
        .with_for_update(of=Transaction)
    ).all()
    for txn, code in rows:
        mark = (txn.provenance or {}).get("description")
        if (isinstance(mark, dict) and mark.get("locked")) or not txn.description:
            continue
        inputs = txn.inputs or {}
        # Who leads the description: the channel for sales (and refunds of them), the party otherwise; an expense
        # with no party names its channel first.
        channel_leads = (
            code == "sale"
            or (code == "sale_refund" and bool(inputs.get("channel_id")))
            or (code == "expense" and not txn.counterparty_id)
        )
        text = before = txn.description
        if text.startswith(head) and channel_leads == bool(channel_id):
            text = f"{new} · {text[len(head) :]}"
        if channel_id and code == "credit_purchase" and text.endswith(tail):  # "… · 面值 ¥10 · 链动"
            text = f"{text[: -len(tail)]} · {new}"
        if text == before:
            continue
        txn.description = text
        txn.version += 1
        audit.record(
            session,
            ctx,
            "transaction.update",
            "transaction",
            txn.id,
            before={"description": before},
            after={"description": text},
        )


def list_counterparties(
    session: Session,
    book_id: str,
    query: str | None = None,
    category: str | None = None,
    limit: int = 100,
) -> list[Counterparty]:
    stmt = select(Counterparty).where(Counterparty.book_id == book_id)
    if category:
        stmt = stmt.where(Counterparty.category == category)
    if query:
        like = f"%{query.strip()}%"
        alias_match = select(CounterpartyAlias.counterparty_id).where(
            CounterpartyAlias.book_id == book_id, CounterpartyAlias.pattern.ilike(like)
        )
        stmt = stmt.where(or_(Counterparty.name.ilike(like), Counterparty.id.in_(alias_match)))
    return list(session.execute(stmt.order_by(Counterparty.name).limit(limit)).scalars())


DEFAULTABLE_TYPES = ("sale", "credit_purchase", "expense", "purchase_refund", "sale_refund")


def counterparty_defaults(session: Session, item: Counterparty) -> dict[str, Any]:
    """{"type": code | None, "channel": {"id", "code", "name"} | None} — filled in when an entry omits them."""
    type_code = None
    if item.default_transaction_type_id:
        found = session.get(TransactionType, item.default_transaction_type_id)
        type_code = found.code if found else None
    channel = None
    channel_id = (item.default_dimensions or {}).get("channel")
    if channel_id:
        value = session.get(DimensionValue, channel_id)
        if value is not None:
            channel = {"id": value.id, "code": value.code, "name": value.name}
    return {"type": type_code, "channel": channel}


def _set_defaults(session: Session, item: Counterparty, changes: dict[str, Any]) -> None:
    if "default_type" in changes:
        code = changes["default_type"]
        if code is None:
            item.default_transaction_type_id = None
        else:
            if code not in DEFAULTABLE_TYPES:
                raise DomainError("VALIDATION_FAILED", f"默认交易类型只能是 {', '.join(DEFAULTABLE_TYPES)}。")
            found = session.execute(
                select(TransactionType).where(TransactionType.book_id == item.book_id, TransactionType.code == code)
            ).scalar_one()
            item.default_transaction_type_id = found.id
    if "default_channel" in changes:
        dims = dict(item.default_dimensions or {})
        if changes["default_channel"] is None:
            dims.pop("channel", None)
        else:
            dims["channel"] = resolve_dimensions(session, item.book_id, {"channel": changes["default_channel"]})[
                "channel"
            ]
        item.default_dimensions = dims


def fee_rules_for(session: Session, item: Counterparty) -> list[dict[str, Any]]:
    """Current fee rules scoped to this counterparty (how much this site charges, by channel)."""
    from bookkeeper.db.models import FeeRuleRow
    from bookkeeper.services import fees

    rows = session.execute(
        select(FeeRuleRow)
        .where(
            FeeRuleRow.book_id == item.book_id,
            FeeRuleRow.status == "active",
            FeeRuleRow.counterparty_ids.contains([item.id]),
        )
        .order_by(FeeRuleRow.code, FeeRuleRow.version)
    ).scalars()
    return [fees.view(r) for r in rows]


def counterparty_details(session: Session, item: Counterparty) -> dict[str, Any]:
    aliases = (
        session.execute(
            select(CounterpartyAlias)
            .where(CounterpartyAlias.counterparty_id == item.id)
            .order_by(CounterpartyAlias.priority)
        )
        .scalars()
        .all()
    )
    accounts = (
        session.execute(
            select(CounterpartyAccount)
            .where(CounterpartyAccount.counterparty_id == item.id)
            .order_by(CounterpartyAccount.label)
        )
        .scalars()
        .all()
    )
    return counterparty_view(item, aliases, accounts) | {
        "defaults": counterparty_defaults(session, item),
        "fee_rules": fee_rules_for(session, item),
    }


def site_hosts(session: Session, book_id: str) -> list[str]:
    """The hosts of the upstream sites the book knows (their names)."""
    return [
        name.lower()
        for name in session.execute(
            select(Counterparty.name).where(
                Counterparty.book_id == book_id,
                Counterparty.is_active.is_(True),
                Counterparty.category == "upstream_site",
                Counterparty.name.contains("."),
            )
        ).scalars()
    ]


def resolve_counterparty_text(session: Session, book_id: str, text_value: str) -> list[dict[str, Any]]:
    """Candidates for free text (site host, shop name…): exact name → alias rules → domain. A domain matches only
    its own host (``www.`` aside): api.relay-a.example and x.relay-a.example are different sites."""
    raw = text_value.strip()
    if not raw:
        return []
    lowered = raw.lower()
    host = normalise_domain(raw)
    candidates: dict[str, dict[str, Any]] = {}

    def add(cp_id: str, name: str, method: str, score: float) -> None:
        current = candidates.get(cp_id)
        if current is None or current["score"] < score:
            candidates[cp_id] = {
                "counterparty_id": cp_id,
                "name": name,
                "method": method,
                "score": score,
            }

    for cp in session.execute(
        select(Counterparty).where(Counterparty.book_id == book_id, Counterparty.is_active.is_(True))
    ).scalars():
        if cp.name.lower() == lowered:
            add(cp.id, cp.name, "name", 1.0)
    rows = session.execute(
        select(CounterpartyAlias, Counterparty.name)
        .join(Counterparty, Counterparty.id == CounterpartyAlias.counterparty_id)
        .where(CounterpartyAlias.book_id == book_id, Counterparty.is_active.is_(True))
    ).all()
    for alias, name in rows:
        pattern = alias.pattern
        if alias.match_type == "exact" and pattern.lower() == lowered:
            add(alias.counterparty_id, name, "alias_exact", 0.98)
        elif alias.match_type == "domain" and host == pattern:
            add(alias.counterparty_id, name, "domain", 0.97)
        elif alias.match_type == "contains" and pattern.lower() in lowered:
            add(alias.counterparty_id, name, "alias_contains", 0.8)
        elif alias.match_type == "regex":
            try:
                if re.search(pattern, raw[:500]):
                    add(alias.counterparty_id, name, "alias_regex", 0.85)
            except re.error:
                continue
    return sorted(candidates.values(), key=lambda c: (-c["score"], c["name"]))


def _flush_unique(session: Session, message: str) -> None:
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise DomainError("CONFLICT", message) from exc
