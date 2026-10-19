"""Ledger reports: trial balance and balances (docs/07)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, case, func, literal, select
from sqlalchemy.orm import Session

from bookkeeper.db.models import (
    Book,
    DailyBalance,
    JournalEntry,
    JournalLine,
    LedgerHead,
)
from bookkeeper.domain.canonical import canonical_json, sha256_hex
from bookkeeper.domain.errors import DomainError, not_found
from bookkeeper.domain.ledger import ENGINE_VERSION
from bookkeeper.domain.money import format_amount
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import accounts, reference
from bookkeeper.services.context import RequestContext


@dataclass
class Activity:
    account_id: str
    commodity: str
    opening: int = 0
    debit: int = 0
    credit: int = 0
    base_opening: int = 0
    base_debit: int = 0
    base_credit: int = 0

    @property
    def closing(self) -> int:
        return self.opening + self.debit - self.credit

    @property
    def base_closing(self) -> int:
        return self.base_opening + self.base_debit - self.base_credit


def _activity(
    session: Session,
    book_id: str,
    date_from: date | None,
    date_to: date,
    as_known_at: datetime | None = None,
    account_ids: set[str] | None = None,
) -> list[Activity]:
    """Opening (before date_from) and period debit/credit per account × commodity."""
    if as_known_at is None:
        d = DailyBalance
        before = d.date < date_from if date_from else literal(False)
        within = d.date >= date_from if date_from else literal(True)
        stmt: Select[Any] = (
            select(
                d.account_id,
                d.commodity,
                func.coalesce(func.sum(case((before, d.debit - d.credit), else_=0)), 0),
                func.coalesce(func.sum(case((within, d.debit), else_=0)), 0),
                func.coalesce(func.sum(case((within, d.credit), else_=0)), 0),
                func.coalesce(func.sum(case((before, d.base_debit - d.base_credit), else_=0)), 0),
                func.coalesce(func.sum(case((within, d.base_debit), else_=0)), 0),
                func.coalesce(func.sum(case((within, d.base_credit), else_=0)), 0),
            )
            .where(d.book_id == book_id, d.date <= date_to)
            .group_by(d.account_id, d.commodity)
        )
        if account_ids is not None:
            stmt = stmt.where(d.account_id.in_(account_ids))
    else:
        jl = JournalLine
        before = jl.effective_date < date_from if date_from else literal(False)
        within = jl.effective_date >= date_from if date_from else literal(True)
        pos, neg = (
            case((jl.amount > 0, jl.amount), else_=0),
            case((jl.amount < 0, -jl.amount), else_=0),
        )
        bpos, bneg = (
            case((jl.base_amount > 0, jl.base_amount), else_=0),
            case((jl.base_amount < 0, -jl.base_amount), else_=0),
        )
        stmt = (
            select(
                jl.account_id,
                jl.commodity,
                func.coalesce(func.sum(case((before, jl.amount), else_=0)), 0),
                func.coalesce(func.sum(case((within, pos), else_=0)), 0),
                func.coalesce(func.sum(case((within, neg), else_=0)), 0),
                func.coalesce(func.sum(case((before, jl.base_amount), else_=0)), 0),
                func.coalesce(func.sum(case((within, bpos), else_=0)), 0),
                func.coalesce(func.sum(case((within, bneg), else_=0)), 0),
            )
            .join(JournalEntry, JournalEntry.id == jl.entry_id)
            .where(
                jl.book_id == book_id,
                jl.effective_date <= date_to,
                JournalEntry.recorded_at <= as_known_at,
            )
            .group_by(jl.account_id, jl.commodity)
        )
        if account_ids is not None:
            stmt = stmt.where(jl.account_id.in_(account_ids))
    return [Activity(*(row[0:2]), *(int(v) for v in row[2:])) for row in session.execute(stmt).all()]


def _ledger_state(session: Session, book_id: str, as_known_at: datetime | None) -> tuple[int, str | None]:
    if as_known_at is None:
        head = session.get(LedgerHead, book_id)
        return (head.last_seq, bytes(head.last_entry_hash).hex()) if head else (0, None)
    row = session.execute(
        select(JournalEntry.seq, JournalEntry.hash)
        .where(JournalEntry.book_id == book_id, JournalEntry.recorded_at <= as_known_at)
        .order_by(JournalEntry.seq.desc())
        .limit(1)
    ).first()
    return (row[0], bytes(row[1]).hex()) if row else (0, None)


def fingerprint(report: str, params: dict[str, Any], book_id: str, ledger_seq: int, head_hash: str | None) -> str:
    return sha256_hex(
        canonical_json(
            {
                "report": report,
                "params": params,
                "book_id": book_id,
                "ledger_seq": ledger_seq,
                "head_hash": head_hash,
                "engine": ENGINE_VERSION,
            }
        )
    )


def _meta(
    session: Session,
    report: str,
    params: dict[str, Any],
    book_id: str,
    as_known_at: datetime | None,
) -> dict[str, Any]:
    seq, head = _ledger_state(session, book_id, as_known_at)
    return {
        "report": report,
        "params": params,
        "ledger_seq": seq,
        "fingerprint": fingerprint(report, params, book_id, seq, head),
    }


class _Fmt:
    def __init__(self, session: Session, book: Book) -> None:
        self.scales = reference.commodity_scales(session)
        self.symbols = {c: x.symbol for c, x in reference.commodities_by_code(session).items()}
        self.base = book.base_commodity

    def money(self, minor: int, commodity: str) -> dict[str, Any]:
        return {
            "minor": minor,
            "commodity": commodity,
            "display": format_amount(minor, self.scales[commodity], self.symbols.get(commodity), commodity),
        }

    def base_money(self, minor: int) -> dict[str, Any]:
        return self.money(minor, self.base)


def trial_balance(
    session: Session,
    ctx: RequestContext,
    date_from: date,
    date_to: date,
    as_known_at: datetime | None = None,
    include_zero: bool = False,
) -> dict[str, Any]:
    ctx.require(Scope.LEDGER_READ)
    book_id = ctx.require_book()
    if date_from > date_to:
        raise DomainError("VALIDATION_FAILED", "开始日期不能晚于结束日期。")
    book = session.get(Book, book_id)
    assert book is not None
    fmt = _Fmt(session, book)
    rows = _activity(session, book_id, date_from, date_to, as_known_at)
    info = {a.id: a for a in accounts.list_accounts(session, book_id)}
    lines = []
    totals = {"base_opening": 0, "base_debit": 0, "base_credit": 0, "base_closing": 0}
    per_commodity: dict[str, dict[str, int]] = defaultdict(
        lambda: {"opening": 0, "debit": 0, "credit": 0, "closing": 0}
    )
    for act in sorted(rows, key=lambda a: (info[a.account_id].code, a.commodity)):
        if (
            not include_zero
            and act.opening == 0
            and act.debit == 0
            and act.credit == 0
            and act.base_opening == 0
            and act.base_debit == 0
            and act.base_credit == 0
        ):
            continue
        acc = info[act.account_id]
        lines.append(
            {
                "account_id": acc.id,
                "account_code": acc.code,
                "account_name": acc.name,
                "classification": acc.classification,
                "role": acc.role,
                "commodity": act.commodity,
                "opening": fmt.money(act.opening, act.commodity),
                "debit": fmt.money(act.debit, act.commodity),
                "credit": fmt.money(act.credit, act.commodity),
                "closing": fmt.money(act.closing, act.commodity),
                "base_opening": fmt.base_money(act.base_opening),
                "base_debit": fmt.base_money(act.base_debit),
                "base_credit": fmt.base_money(act.base_credit),
                "base_closing": fmt.base_money(act.base_closing),
            }
        )
        totals["base_opening"] += act.base_opening
        totals["base_debit"] += act.base_debit
        totals["base_credit"] += act.base_credit
        totals["base_closing"] += act.base_closing
        c = per_commodity[act.commodity]
        c["opening"] += act.opening
        c["debit"] += act.debit
        c["credit"] += act.credit
        c["closing"] += act.closing
    params = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "as_known_at": as_known_at.isoformat() if as_known_at else None,
        "include_zero": include_zero,
    }
    balanced = (
        totals["base_debit"] == totals["base_credit"]
        and totals["base_closing"] == 0
        and all(v["closing"] == 0 and v["debit"] == v["credit"] for v in per_commodity.values())
    )
    return {
        "title": f"试算平衡表（{date_from} 至 {date_to}）",
        "lines": lines,
        "totals": {k: fmt.base_money(v) for k, v in totals.items()},
        "per_commodity": {c: {k: fmt.money(v, c) for k, v in vals.items()} for c, vals in per_commodity.items()},
        "balanced": balanced,
        "meta": _meta(session, "trial_balance", params, book_id, as_known_at),
    }


def balances(
    session: Session,
    ctx: RequestContext,
    as_of: date,
    account_refs: list[str] | None = None,
    as_known_at: datetime | None = None,
) -> dict[str, Any]:
    ctx.require(Scope.LEDGER_READ)
    book_id = ctx.require_book()
    book = session.get(Book, book_id)
    assert book is not None
    fmt = _Fmt(session, book)
    ids = {accounts.get_account(session, book_id, ref).id for ref in account_refs} if account_refs else None
    info = {a.id: a for a in accounts.list_accounts(session, book_id)}
    rows = _activity(session, book_id, None, as_of, as_known_at, ids)
    data = [
        {
            "account_id": a.account_id,
            "account_code": info[a.account_id].code,
            "account_name": info[a.account_id].name,
            "commodity": a.commodity,
            "balance": fmt.money(a.closing, a.commodity),
            "base_balance": fmt.base_money(a.base_closing),
        }
        for a in sorted(rows, key=lambda x: (info[x.account_id].code, x.commodity))
        if a.closing != 0 or a.base_closing != 0
    ]
    params = {
        "as_of": as_of.isoformat(),
        "accounts": sorted(account_refs) if account_refs else None,
        "as_known_at": as_known_at.isoformat() if as_known_at else None,
    }
    return {
        "as_of": as_of.isoformat(),
        "balances": data,
        "meta": _meta(session, "balances", params, book_id, as_known_at),
    }


def get_entry(session: Session, ctx: RequestContext, ref: str) -> JournalEntry:
    ctx.require(Scope.LEDGER_READ)
    book_id = ctx.require_book()
    stmt = select(JournalEntry).where(JournalEntry.book_id == book_id)
    stmt = stmt.where(JournalEntry.id == ref) if ref.startswith("jen_") else stmt.where(JournalEntry.number == ref)
    entry = session.execute(stmt).scalar_one_or_none()
    if entry is None:
        raise not_found("分录", ref)
    return entry


def list_entries(
    session: Session,
    ctx: RequestContext,
    *,
    after_seq: int | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
) -> list[JournalEntry]:
    ctx.require(Scope.LEDGER_READ)
    stmt = select(JournalEntry).where(JournalEntry.book_id == ctx.require_book())
    if after_seq is not None:
        stmt = stmt.where(JournalEntry.seq > after_seq)
    if date_from:
        stmt = stmt.where(JournalEntry.effective_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.effective_date <= date_to)
    return list(session.execute(stmt.order_by(JournalEntry.seq).limit(limit)).scalars())
