"""Fee rules: versioned data (a new rate = a new version from a date)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookkeeper.db.models import FeeRuleRow
from bookkeeper.domain import fees as domain_fees
from bookkeeper.domain.errors import DomainError, not_found
from bookkeeper.domain.fees import FeeRule, fee_on, select_rule
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.money import AmountError, format_amount, parse_decimal, to_minor
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import audit, reference
from bookkeeper.services.context import RequestContext

FEE_TYPES = domain_fees.FEE_TYPES


def view(row: FeeRuleRow) -> dict[str, Any]:
    rule = to_domain(row)
    return {
        "id": row.id,
        "code": row.code,
        "version": row.version,
        "name": row.name,
        "method": rule.method,
        "rate": format(row.rate.normalize(), "f") if row.rate is not None else None,
        "fixed_minor": row.fixed_minor,
        "min_minor": row.min_minor,
        "max_minor": row.max_minor,
        "commodity": row.commodity,
        "transaction_types": list(row.transaction_types),
        "channel_ids": list(row.channel_ids),
        "counterparty_ids": list(row.counterparty_ids),
        "priority": row.priority,
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "is_estimate": row.is_estimate,
        "status": row.status,
        "note": row.note,
    }


def to_domain(row: FeeRuleRow) -> FeeRule:
    return FeeRule(
        id=row.id,
        code=row.code,
        version=row.version,
        rate=row.rate,
        fixed_minor=row.fixed_minor,
        min_minor=row.min_minor,
        max_minor=row.max_minor,
        commodity=row.commodity,
        transaction_types=tuple(row.transaction_types),
        channels=tuple(row.channel_ids),
        counterparties=tuple(row.counterparty_ids),
        priority=row.priority,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        is_estimate=row.is_estimate,
    )


def active_rules(session: Session, book_id: str) -> list[FeeRule]:
    rows = session.execute(
        select(FeeRuleRow).where(FeeRuleRow.book_id == book_id, FeeRuleRow.status == "active")
    ).scalars()
    return [to_domain(r) for r in rows]


def save_rule(session: Session, ctx: RequestContext, data: dict[str, Any]) -> FeeRuleRow:
    """Create a rule, or a new version of ``code`` effective from ``valid_from`` (closing the previous one).

    ``data``: code, name, rate ("0.03"), fixed ("0.30"), min, max, commodity, transaction_types,
    channels (codes), counterparties (names / ids), priority, valid_from, is_estimate, note.
    """
    ctx.require(Scope.CONFIG_WRITE)
    book_id = ctx.require_book()
    types = data.get("transaction_types") or []
    if set(types) - set(FEE_TYPES):
        raise DomainError("VALIDATION_FAILED", f"手续费规则只适用于 {', '.join(FEE_TYPES)}。")
    if data.get("rate") in (None, "") and data.get("fixed") in (None, ""):
        raise DomainError("VALIDATION_FAILED", "rate（比例）与 fixed（固定额）至少填写一项。")
    scales = reference.active_scales(session)
    commodity = data.get("commodity")
    if commodity is not None and commodity not in scales:
        raise DomainError("VALIDATION_FAILED", reference.unknown_commodity(commodity) + "。")
    if commodity is None and any(data.get(k) not in (None, "") for k in ("fixed", "min", "max")):
        raise DomainError("VALIDATION_FAILED", "设置了固定额或上下限时必须指定 commodity（金额的币种）。")

    def minor(key: str) -> int | None:
        if data.get(key) in (None, ""):
            return None
        assert commodity is not None
        value = to_minor(data[key], scales[commodity])
        if value < 0:
            raise DomainError("VALIDATION_FAILED", f"{key} 不能为负数。")
        return value

    try:
        rate = parse_decimal(data["rate"]) if data.get("rate") not in (None, "") else None
        fixed, low, high = minor("fixed"), minor("min"), minor("max")
    except AmountError as exc:
        raise DomainError("VALIDATION_FAILED", f"手续费数值无效：{exc}") from exc
    if rate is not None and not Decimal(0) <= rate < 1:
        raise DomainError("VALIDATION_FAILED", "比例须在 0 到 1 之间，如 0.03 表示 3%。")
    if low is not None and high is not None and low > high:
        raise DomainError("VALIDATION_FAILED", "下限不能大于上限。")
    channels = [
        reference.resolve_dimensions(session, book_id, {"channel": c})["channel"] for c in data.get("channels") or []
    ]
    counterparties = [reference.get_counterparty(session, book_id, c).id for c in data.get("counterparties") or []]
    valid_from: date = data["valid_from"]
    previous = session.execute(
        select(FeeRuleRow)
        .where(FeeRuleRow.book_id == book_id, FeeRuleRow.code == data["code"])
        .order_by(FeeRuleRow.version.desc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()
    if previous is not None:
        if valid_from <= previous.valid_from:
            raise DomainError("VALIDATION_FAILED", f"新版本生效日须晚于上一版本（{previous.valid_from}）。")
        before = view(previous)
        previous.valid_to = valid_from - timedelta(days=1)
        audit.record(session, ctx, "fee_rule.close", "fee_rule", previous.id, before=before, after=view(previous))
    row = FeeRuleRow(
        id=new_id("fee"),
        book_id=book_id,
        code=data["code"],
        version=(previous.version + 1) if previous else 1,
        name=data.get("name") or (previous.name if previous else data["code"]),
        rate=rate,
        fixed_minor=fixed,
        min_minor=low,
        max_minor=high,
        commodity=commodity,
        transaction_types=types,
        channel_ids=channels,
        counterparty_ids=counterparties,
        priority=data.get("priority") or 0,
        valid_from=valid_from,
        is_estimate=bool(data.get("is_estimate")),
        note=data.get("note"),
        created_by=ctx.actor.user_id,
    )
    session.add(row)
    session.flush()
    audit.record(session, ctx, "fee_rule.create", "fee_rule", row.id, after=view(row))
    return row


def retire(session: Session, ctx: RequestContext, code: str) -> list[FeeRuleRow]:
    ctx.require(Scope.CONFIG_WRITE)
    rows = list(
        session.execute(
            select(FeeRuleRow)
            .where(FeeRuleRow.book_id == ctx.require_book(), FeeRuleRow.code == code, FeeRuleRow.status == "active")
            .with_for_update()
        ).scalars()
    )
    if not rows:
        raise not_found("手续费规则", code)
    for row in rows:
        row.status = "retired"
    audit.record(session, ctx, "fee_rule.retire", "fee_rule", rows[0].id, after={"code": code})
    return rows


def list_rules(session: Session, book_id: str, include_retired: bool = False) -> list[FeeRuleRow]:
    stmt = select(FeeRuleRow).where(FeeRuleRow.book_id == book_id)
    if not include_retired:
        stmt = stmt.where(FeeRuleRow.status == "active")
    return list(session.execute(stmt.order_by(FeeRuleRow.code, FeeRuleRow.version)).scalars())


def evaluate(
    session: Session,
    book_id: str,
    type_code: str,
    amount: str,
    on: date,
    channel: str | None = None,
    counterparty: str | None = None,
    commodity: str = "CNY",
) -> dict[str, Any]:
    """Which rule applies and the fee it gives — the same selection used when posting."""
    scales = reference.active_scales(session)
    if commodity not in scales:
        raise DomainError("VALIDATION_FAILED", reference.unknown_commodity(commodity) + "。")
    if type_code not in FEE_TYPES:
        raise DomainError("VALIDATION_FAILED", f"手续费规则只适用于 {', '.join(FEE_TYPES)}。")
    try:
        base = to_minor(amount, scales[commodity])
    except AmountError as exc:
        raise DomainError("VALIDATION_FAILED", str(exc)) from exc
    channel_id = reference.resolve_dimensions(session, book_id, {"channel": channel})["channel"] if channel else None
    cp_id = reference.get_counterparty(session, book_id, counterparty).id if counterparty else None
    rule = select_rule(active_rules(session, book_id), type_code, channel_id, cp_id, on, commodity)
    fee = fee_on(rule, base) if rule else 0
    return {
        "rule": {"id": rule.id, "code": rule.code, "version": rule.version, "method": rule.method} if rule else None,
        "base_minor": base,
        "fee_minor": fee,
        "fee": format_amount(fee, scales[commodity], None, commodity),
        "is_estimate": bool(rule and rule.is_estimate),
    }


def rule_brief(row: FeeRuleRow | None) -> dict[str, Any] | None:
    """What a person needs to recognise a rule: its name, code@version and the rate or fixed amount."""
    if row is None:
        return None
    return {
        "id": row.id,
        "code": row.code,
        "version": row.version,
        "name": row.name or row.code,
        "rate": format(row.rate.normalize(), "f") if row.rate is not None else None,
        "fixed_minor": row.fixed_minor,
        "commodity": row.commodity,
    }


def basis(type_code: str, inputs: dict[str, Any], rule_id: str | None) -> str | None:
    """Where a fee comes from: ``actual`` (given on the entry), ``rule``, or ``none`` (no rule matched: fee 0).
    None for types that carry no fee."""
    if type_code not in FEE_TYPES:
        return None
    if "fee" in inputs or (type_code == "credit_purchase" and "face" in inputs and "total" in inputs):
        return "actual"
    return "rule" if rule_id else "none"


def proposed_rule(
    session: Session,
    book_id: str,
    type_code: str,
    channel_id: str | None,
    counterparty_id: str | None,
    on: date,
    commodity: str,
    rules: list[FeeRule] | None = None,
) -> FeeRuleRow | None:
    """The rule a transaction with these facts would use on that date — the same selection as posting."""
    rule = select_rule(
        rules if rules is not None else active_rules(session, book_id),
        type_code,
        channel_id,
        counterparty_id,
        on,
        commodity,
    )
    return session.get(FeeRuleRow, rule.id) if rule else None
