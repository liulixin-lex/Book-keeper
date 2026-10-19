"""Business analytics: one aggregate query over journal lines, and the report presets built on it.

Every row carries ``drilldown``: query parameters for ``GET transactions`` (and, for account rows,
the account register) that list exactly the transactions behind the number.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, and_, case, func, literal, select
from sqlalchemy.orm import Session, aliased

from bookkeeper.db.models import (
    Account,
    Book,
    Counterparty,
    DimensionType,
    DimensionValue,
    JournalEntry,
    JournalLine,
    JournalLineDimension,
    Transaction,
    TransactionType,
)
from bookkeeper.domain import labels
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.money import from_minor
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import accounts, reference
from bookkeeper.services.context import RequestContext
from bookkeeper.services.reports import _activity, _Fmt, _meta

PERIODS = ("year", "quarter", "month", "week", "day")
GROUPS = (
    *PERIODS,
    "account",
    "top_account",
    "classification",
    "channel",
    "counterparty",
    "transaction_type",
    "line_role",
    "commodity",
    "is_estimate",
)
MEASURES = ("base_amount", "amount", "debit", "credit", "count", "quantity")
MAX_ROWS = 5000


@dataclass
class Query:
    """``sign="natural"`` shows each account on its normal side (revenue and liabilities positive)."""

    date_from: date
    date_to: date
    group_by: Sequence[str] = ()
    measures: Sequence[str] = ("base_amount", "count")
    accounts: Sequence[str] = ()
    classifications: Sequence[str] = ()
    channels: Sequence[str] = ()
    counterparties: Sequence[str] = ()
    transaction_types: Sequence[str] = ()
    line_roles: Sequence[str] = ()
    commodities: Sequence[str] = ()
    tags: Sequence[str] = ()
    sign: str = "natural"
    as_known_at: datetime | None = None


@dataclass
class _Resolved:
    account_ids: set[str] | None = None
    channel_ids: list[str] = field(default_factory=list)
    counterparty_ids: list[str] = field(default_factory=list)


def _validate(q: Query) -> None:
    if q.date_from > q.date_to:
        raise DomainError("VALIDATION_FAILED", "开始日期不能晚于结束日期。")
    unknown = set(q.group_by) - set(GROUPS)
    if unknown:
        raise DomainError(
            "VALIDATION_FAILED", f"不支持的分组：{', '.join(sorted(unknown))}；可用 {', '.join(GROUPS)}。"
        )
    bad = set(q.measures) - set(MEASURES)
    if bad:
        raise DomainError("VALIDATION_FAILED", f"不支持的度量：{', '.join(sorted(bad))}；可用 {', '.join(MEASURES)}。")
    if len(q.group_by) > 4:
        raise DomainError("VALIDATION_FAILED", "最多按 4 个维度分组。")
    if q.sign not in ("natural", "debit"):
        raise DomainError("VALIDATION_FAILED", "sign 只能是 natural 或 debit。")


def _resolve(session: Session, book_id: str, q: Query) -> _Resolved:
    out = _Resolved()
    if q.accounts:
        ids: set[str] = set()
        for ref in q.accounts:
            acc = accounts.get_account(session, book_id, ref)
            ids |= set(
                session.execute(
                    select(Account.id).where(
                        Account.book_id == book_id, (Account.id == acc.id) | Account.code.startswith(acc.code + ".")
                    )
                ).scalars()
            )
        out.account_ids = ids
    out.channel_ids = [reference.resolve_dimensions(session, book_id, {"channel": c})["channel"] for c in q.channels]
    out.counterparty_ids = [reference.get_counterparty(session, book_id, c).id for c in q.counterparties]
    return out


def _period_bounds(kind: str, key: str) -> tuple[date, date]:
    if kind == "day":
        d = date.fromisoformat(key)
        return d, d
    if kind == "month":
        y, m = map(int, key.split("-"))
        return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    if kind == "quarter":
        y, qn = int(key[:4]), int(key[-1])
        start = date(y, 3 * qn - 2, 1)
        end_month = 3 * qn
        return start, date(y, end_month, calendar.monthrange(y, end_month)[1])
    if kind == "week":
        y, w = int(key[:4]), int(key[-2:])
        start = date.fromisocalendar(y, w, 1)
        return start, start + timedelta(days=6)
    y = int(key)
    return date(y, 1, 1), date(y, 12, 31)


def aggregate(session: Session, ctx: RequestContext, q: Query) -> dict[str, Any]:
    """Sum journal lines (posted, including reversals and reposts) grouped by the given keys."""
    ctx.require(Scope.LEDGER_READ)
    book_id = ctx.require_book()
    _validate(q)
    book = session.get(Book, book_id)
    assert book is not None
    group_by = list(q.group_by)
    if "amount" in q.measures and "commodity" not in group_by:
        group_by.append("commodity")  # native amounts of different commodities never add up
    rows = _run(session, book, q, group_by)
    fmt = _Fmt(session, book)
    names = _names(session, book_id, rows, group_by)
    out_rows = []
    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        keys = {g: names(g, row[g]) for g in group_by}
        values: dict[str, Any] = {}
        for m in q.measures:
            raw = row[m]
            if m in ("base_amount", "debit", "credit"):
                values[m] = fmt.base_money(int(raw))
                totals[m] += int(raw)
            elif m == "amount":
                values[m] = fmt.money(int(raw), row["commodity"])
            elif m == "quantity":
                values[m] = format(raw.normalize(), "f") if raw is not None else None
            else:
                values[m] = int(raw)
        out_rows.append({"keys": keys, "values": values, "drilldown": _drilldown(q, group_by, row, keys)})
    total_count = _run(session, book, q, [])[0]["count"] if "count" in q.measures and group_by else None
    params = _params(q) | {"group_by": group_by}
    return {
        "rows": out_rows,
        "totals": {k: fmt.base_money(v) for k, v in totals.items()}
        | ({"count": int(total_count)} if total_count is not None else {}),
        "truncated": len(rows) >= MAX_ROWS,
        "meta": _meta(session, "query", params, book_id, q.as_known_at),
    }


def _params(q: Query) -> dict[str, Any]:
    return {
        "date_from": q.date_from.isoformat(),
        "date_to": q.date_to.isoformat(),
        "measures": list(q.measures),
        "accounts": list(q.accounts),
        "classifications": list(q.classifications),
        "channels": list(q.channels),
        "counterparties": list(q.counterparties),
        "transaction_types": list(q.transaction_types),
        "line_roles": list(q.line_roles),
        "commodities": list(q.commodities),
        "tags": list(q.tags),
        "sign": q.sign,
        "as_known_at": q.as_known_at.isoformat() if q.as_known_at else None,
    }


def _run(session: Session, book: Book, q: Query, group_by: Sequence[str]) -> list[dict[str, Any]]:
    jl, je, t, tt, a = JournalLine, JournalEntry, Transaction, TransactionType, Account
    jld, dv = aliased(JournalLineDimension), aliased(DimensionValue)
    resolved = _resolve(session, book.id, q)
    channel_type = session.execute(
        select(DimensionType.id).where(DimensionType.book_id == book.id, DimensionType.code == "channel")
    ).scalar_one_or_none()
    flip = case((a.normal_side == "credit", -1), else_=1) if q.sign == "natural" else literal(1)
    exprs: dict[str, Any] = {
        "year": func.to_char(jl.effective_date, "YYYY"),
        "quarter": func.to_char(jl.effective_date, 'YYYY-"Q"Q'),
        "month": func.to_char(jl.effective_date, "YYYY-MM"),
        "week": func.to_char(jl.effective_date, 'IYYY-"W"IW'),
        "day": func.to_char(jl.effective_date, "YYYY-MM-DD"),
        "account": a.id,
        "top_account": func.split_part(a.code, ".", 1),
        "classification": a.classification,
        "channel": dv.id,
        "counterparty": func.coalesce(jl.counterparty_id, t.counterparty_id),
        "transaction_type": tt.code,
        "line_role": jl.line_role,
        "commodity": jl.commodity,
        "is_estimate": t.is_estimate,
    }
    signed_base = jl.base_amount * flip
    measures: dict[str, Any] = {
        "base_amount": func.coalesce(func.sum(signed_base), 0),
        "amount": func.coalesce(func.sum(jl.amount * flip), 0),
        "debit": func.coalesce(func.sum(case((jl.base_amount > 0, jl.base_amount), else_=0)), 0),
        "credit": func.coalesce(func.sum(case((jl.base_amount < 0, -jl.base_amount), else_=0)), 0),
        "count": func.count(func.distinct(case((t.status == "posted", t.id)))),
        "quantity": func.sum(jl.quantity * flip),
    }
    cols = [exprs[g].label(g) for g in group_by] + [measures[m].label(m) for m in MEASURES]
    stmt = (
        select(*cols)
        .select_from(jl)
        .join(je, je.id == jl.entry_id)
        .join(t, t.id == je.transaction_id)
        .join(tt, tt.id == t.transaction_type_id)
        .join(a, a.id == jl.account_id)
        .outerjoin(jld, and_(jld.line_id == jl.id, jld.dimension_type_id == channel_type))
        .outerjoin(dv, dv.id == jld.dimension_value_id)
        .where(jl.book_id == book.id, jl.effective_date >= q.date_from, jl.effective_date <= q.date_to)
    )
    if q.as_known_at is None:  # live figures: each transaction's current entry only (deleted ones drop out)
        stmt = stmt.where(t.status == "posted", je.id == t.posted_entry_id)
    else:  # the ledger as it stood then: every entry recorded by that time, reversals netting out
        stmt = stmt.where(je.recorded_at <= q.as_known_at)
    if resolved.account_ids is not None:
        stmt = stmt.where(jl.account_id.in_(resolved.account_ids))
    if q.classifications:
        stmt = stmt.where(a.classification.in_(q.classifications))
    if resolved.channel_ids:
        stmt = stmt.where(dv.id.in_(resolved.channel_ids))
    if resolved.counterparty_ids:
        stmt = stmt.where(func.coalesce(jl.counterparty_id, t.counterparty_id).in_(resolved.counterparty_ids))
    if q.transaction_types:
        stmt = stmt.where(tt.code.in_(q.transaction_types))
    if q.line_roles:
        stmt = stmt.where(jl.line_role.in_(q.line_roles))
    if q.commodities:
        stmt = stmt.where(jl.commodity.in_(q.commodities))
    if q.tags:
        from bookkeeper.services import tags as tag_service

        stmt = stmt.where(t.id.in_(tag_service.tagged(q.tags)))
    if group_by:
        order = {"account": a.code, "channel": dv.code}  # readable order; ids are grouped, codes depend on them
        stmt = stmt.group_by(*[exprs[g] for g in group_by]).order_by(*[order.get(g, exprs[g]) for g in group_by])
    result = session.execute(stmt.limit(MAX_ROWS)).mappings().all()
    return [dict(r) for r in result]


def _names(session: Session, book_id: str, rows: list[dict[str, Any]], group_by: Sequence[str]) -> Any:
    """Turn raw group values into {id/code, name} objects with one query per kind."""
    acc = (
        {a.id: a for a in accounts.list_accounts(session, book_id)}
        if {"account", "top_account"} & set(group_by)
        else {}
    )
    by_code = {a.code: a for a in acc.values()}
    channel_ids = {r["channel"] for r in rows if r.get("channel")}
    channels = (
        {v.id: v for v in session.execute(select(DimensionValue).where(DimensionValue.id.in_(channel_ids))).scalars()}
        if channel_ids
        else {}
    )
    cp_ids = {r["counterparty"] for r in rows if r.get("counterparty")}
    cps = (
        dict(session.execute(select(Counterparty.id, Counterparty.name).where(Counterparty.id.in_(cp_ids))).all())
        if cp_ids
        else {}
    )
    type_names = dict(
        session.execute(
            select(TransactionType.code, TransactionType.name).where(TransactionType.book_id == book_id)
        ).all()
    )

    def name(group: str, value: Any) -> Any:
        if group == "account":
            a = acc[value]
            return {"id": a.id, "code": a.code, "name": a.name}
        if group == "top_account":
            top = by_code.get(value)
            return {"code": value, "name": top.name if top else value}
        if group == "channel":
            if value is None:
                return {"code": None, "name": "未指定渠道"}
            v = channels[value]
            return {"code": v.code, "name": v.name}
        if group == "counterparty":
            return {"id": value, "name": cps.get(value, "未指定往来方") if value else "未指定往来方"}
        if group == "transaction_type":
            return {"code": value, "name": type_names.get(value, value)}
        if group == "line_role":
            return {"code": value, "name": labels.ENUM_LABELS.get("line_role", {}).get(value, value)}
        if group == "classification":
            return {"code": value, "name": labels.ENUM_LABELS.get("account_classification", {}).get(value, value)}
        return value

    return name


def _drilldown(q: Query, group_by: Sequence[str], row: dict[str, Any], keys: dict[str, Any]) -> dict[str, Any]:
    """Parameters for GET transactions (codes, not ids, where a code exists) behind one row."""
    params: dict[str, Any] = {"date_from": q.date_from.isoformat(), "date_to": q.date_to.isoformat()}
    for g in group_by:
        if g in PERIODS:
            start, end = _period_bounds(g, row[g])
            params["date_from"] = max(start, q.date_from).isoformat()
            params["date_to"] = min(end, q.date_to).isoformat()
    for name, values in (
        ("channel", q.channels),
        ("account", q.accounts),
        ("type", q.transaction_types),
        ("counterparty", q.counterparties),
    ):
        if len(values) == 1:
            params[name] = values[0]
    if "account" in group_by:
        params["account"] = keys["account"]["code"]
    if "top_account" in group_by:
        params["account"] = keys["top_account"]["code"]
    if "channel" in group_by and keys["channel"]["code"]:
        params["channel"] = keys["channel"]["code"]
    if "counterparty" in group_by and keys["counterparty"]["id"]:
        params["counterparty"] = keys["counterparty"]["id"]
    if "transaction_type" in group_by:
        params["type"] = keys["transaction_type"]["code"]
    return {"transactions": params}


CATALOGUE: list[dict[str, Any]] = [
    {
        "path": "reports/summary",
        "name": "概览",
        "params": ["date_from", "date_to"],
        "description": "利润、各币种资金余额、前五渠道与站点、需留意事项（估算手续费、待核对款项）",
    },
    {
        "path": "reports/income-statement",
        "name": "利润表",
        "params": ["date_from", "date_to", "columns"],
        "description": "营业收入、营业成本、毛利、期间费用、营业利润、净利润；columns=month 输出逐月列",
    },
    {
        "path": "reports/operations",
        "name": "经营日报",
        "params": ["date_from", "date_to", "period"],
        "description": "按日 / 周 / 月：销售收入、手续费、额度成本、其他成本、期间费用、利润与笔数",
    },
    {
        "path": "reports/sales",
        "name": "销售分析",
        "params": ["date_from", "date_to", "period"],
        "description": "按渠道：订单数、毛额、退款、净销售、手续费、到账、费率、客单价",
    },
    {
        "path": "reports/fees",
        "name": "手续费分析",
        "params": ["date_from", "date_to"],
        "description": "按渠道 × 交易类型：手续费、计费基数、实际费率、其中估算部分",
    },
    {
        "path": "reports/credit-purchases",
        "name": "额度采购分析",
        "params": ["date_from", "date_to", "period"],
        "description": "按上游站点：采购笔数、面值、手续费、实付、退款、额度数量、单位额度成本",
    },
    {
        "path": "reports/trial-balance",
        "name": "试算平衡表",
        "params": ["date_from", "date_to", "as_known_at"],
        "description": "各科目期初、借方、贷方、期末（原币与本位币）",
    },
    {
        "path": "reports/query",
        "name": "自定义汇总",
        "params": [
            "date_from",
            "date_to",
            "group_by",
            "measures",
            "accounts",
            "classifications",
            "channels",
            "counterparties",
            "transaction_types",
            "line_roles",
            "commodities",
            "tags",
            "sign",
            "as_known_at",
        ],
        "description": "对分录行按任意维度汇总；group_by 可选 "
        + "、".join(GROUPS)
        + "；measures 可选 "
        + "、".join(MEASURES),
        "examples": [
            {"title": "各支出分类金额", "query": "classifications=expense&group_by=account"},
            {"title": "按月按渠道的销售收入", "query": "accounts=5001&group_by=month,channel"},
            {"title": "按往来方的支出", "query": "classifications=expense&group_by=counterparty"},
            {
                "title": "各币种资金流入流出",
                "query": "accounts=1012.01&group_by=commodity&measures=amount,debit,credit",
            },
        ],
    },
]


# ------------------------------------------------------------------ presets


def _line(fmt: _Fmt, code: str, name: str, amount: int, level: int = 1, **extra: Any) -> dict[str, Any]:
    return {"code": code, "name": name, "level": level, "amount": fmt.base_money(amount)} | extra


def income_statement(
    session: Session, ctx: RequestContext, date_from: date, date_to: date, columns: str | None = None
) -> dict[str, Any]:
    """利润表: revenue, cost, period expenses, non-operating items, profit; optional per-period columns."""
    if columns is not None and columns not in PERIODS:
        raise DomainError("VALIDATION_FAILED", f"columns 只能是 {', '.join(PERIODS)}。")
    q = Query(
        date_from,
        date_to,
        group_by=["account", *([columns] if columns else [])],
        measures=["base_amount"],
        classifications=["revenue", "expense"],
    )
    data = aggregate(session, ctx, q)
    book = session.get(Book, ctx.require_book())
    assert book is not None
    fmt = _Fmt(session, book)
    info = {a.id: a for a in accounts.list_accounts(session, book.id)}
    by_account: dict[str, int] = defaultdict(int)
    by_period: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in data["rows"]:
        acc_id = row["keys"]["account"]["id"]
        amount = row["values"]["base_amount"]["minor"]
        by_account[acc_id] += amount
        if columns:
            by_period[row["keys"][columns]][acc_id] += amount
    period_keys = sorted(by_period)

    def bucket(acc: Account) -> str:
        if acc.role == "non_operating_income":
            return "non_operating_income"
        if acc.role == "non_operating_expense":
            return "non_operating_expense"
        if acc.classification == "revenue":
            return "revenue"
        return {"5401": "cost", "5601": "selling", "5602": "admin", "5603": "finance"}.get(
            acc.code.split(".")[0], "other_expense"
        )

    sections = [
        ("revenue", "营业收入"),
        ("cost", "营业成本"),
        ("selling", "销售费用"),
        ("admin", "管理费用"),
        ("finance", "财务费用"),
        ("other_expense", "其他费用"),
        ("non_operating_income", "营业外收入"),
        ("non_operating_expense", "营业外支出"),
    ]

    def total(key: str, amounts: dict[str, int]) -> int:
        return sum(v for k, v in amounts.items() if bucket(info[k]) == key)

    def figures(amounts: dict[str, int]) -> dict[str, int]:
        f = {key: total(key, amounts) for key, _ in sections}
        f["gross_profit"] = f["revenue"] - f["cost"]
        f["operating_profit"] = f["gross_profit"] - f["selling"] - f["admin"] - f["finance"] - f["other_expense"]
        f["net_profit"] = f["operating_profit"] + f["non_operating_income"] - f["non_operating_expense"]
        return f

    overall = figures(by_account)
    per_period = {p: figures(by_period[p]) for p in period_keys}
    lines: list[dict[str, Any]] = []
    for key, title in sections:
        members = sorted((info[k] for k in by_account if bucket(info[k]) == key), key=lambda a: a.code)
        if not members and key in ("other_expense", "non_operating_income", "non_operating_expense"):
            continue
        lines.append(_line(fmt, key, title, overall[key], 1, columns=_cols(fmt, per_period, key)))
        for acc in members:
            lines.append(
                _line(
                    fmt,
                    acc.code,
                    acc.name,
                    by_account[acc.id],
                    2,
                    account_id=acc.id,
                    columns={p: fmt.base_money(by_period[p].get(acc.id, 0)) for p in period_keys} if columns else None,
                    drilldown={
                        "transactions": {"account": acc.code, "date_from": str(date_from), "date_to": str(date_to)}
                    },
                )
            )
        if key == "cost":
            lines.append(
                _line(
                    fmt,
                    "gross_profit",
                    "毛利",
                    overall["gross_profit"],
                    0,
                    columns=_cols(fmt, per_period, "gross_profit"),
                )
            )
        if key == "other_expense" or (
            key == "finance" and not any(bucket(info[k]) == "other_expense" for k in by_account)
        ):
            lines.append(
                _line(
                    fmt,
                    "operating_profit",
                    "营业利润",
                    overall["operating_profit"],
                    0,
                    columns=_cols(fmt, per_period, "operating_profit"),
                )
            )
    lines.append(
        _line(fmt, "net_profit", "净利润", overall["net_profit"], 0, columns=_cols(fmt, per_period, "net_profit"))
    )
    return {
        "title": f"利润表（{date_from} 至 {date_to}）",
        "columns": period_keys,
        "lines": lines,
        "summary": {k: fmt.base_money(v) for k, v in overall.items()},
        "meta": data["meta"] | {"report": "income_statement"},
    }


def _cols(fmt: _Fmt, per_period: dict[str, dict[str, int]], key: str) -> dict[str, Any] | None:
    return {p: fmt.base_money(v[key]) for p, v in per_period.items()} or None


OPERATION_COLUMNS = (
    ("sales", "销售收入"),
    ("other_income", "其他收入"),
    ("fees", "手续费"),
    ("credit_cost", "额度成本"),
    ("other_cost", "其他成本"),
    ("expenses", "期间费用"),
    ("profit", "利润"),
)


def operations(
    session: Session, ctx: RequestContext, date_from: date, date_to: date, period: str = "day"
) -> dict[str, Any]:
    """经营日报 / 月报: per period sales, fees, credit cost, other cost, expenses, profit and counts."""
    if period not in PERIODS:
        raise DomainError("VALIDATION_FAILED", f"period 只能是 {', '.join(PERIODS)}。")
    book = session.get(Book, ctx.require_book())
    assert book is not None
    fmt = _Fmt(session, book)
    data = aggregate(
        session,
        ctx,
        Query(
            date_from,
            date_to,
            group_by=[period, "account"],
            measures=["base_amount"],
            classifications=["revenue", "expense"],
        ),
    )
    counts = aggregate(
        session,
        ctx,
        Query(
            date_from,
            date_to,
            group_by=[period, "transaction_type"],
            measures=["count"],
            transaction_types=["sale", "credit_purchase", "expense"],
        ),
    )
    info = {a.id: a for a in accounts.list_accounts(session, book.id)}
    credit_cost = accounts.default_for_role(session, book.id, "cost_operating")
    table: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in data["rows"]:
        acc = info[row["keys"]["account"]["id"]]
        amount = row["values"]["base_amount"]["minor"]
        bucket = (
            ("sales" if acc.role == "revenue_operating" else "other_income")
            if acc.classification == "revenue"
            else "fees"
            if acc.role == "expense_finance_fee"
            else "credit_cost"
            if credit_cost is not None and acc.id == credit_cost.id
            else "other_cost"
            if acc.code.startswith("5401")
            else "expenses"
        )
        table[row["keys"][period]][bucket] += amount
    count_table: dict[str, dict[str, int]] = defaultdict(dict)
    for row in counts["rows"]:
        count_table[row["keys"][period]][row["keys"]["transaction_type"]["code"]] = row["values"]["count"]
    rows = []
    totals = dict.fromkeys((k for k, _ in OPERATION_COLUMNS), 0)
    for key in sorted(set(table) | set(count_table)):
        cell = {k: table[key].get(k, 0) for k, _ in OPERATION_COLUMNS}
        cell["profit"] = (
            cell["sales"]
            + cell["other_income"]
            - sum(cell[k] for k in ("fees", "credit_cost", "other_cost", "expenses"))
        )
        start, end = _period_bounds(period, key)
        rows.append(
            {
                "period": key,
                "values": {k: fmt.base_money(cell[k]) for k, _ in OPERATION_COLUMNS},
                "counts": count_table.get(key, {}),
                "drilldown": {
                    "transactions": {
                        "date_from": max(start, date_from).isoformat(),
                        "date_to": min(end, date_to).isoformat(),
                        "status": "posted",
                    }
                },
            }
        )
        for k in totals:
            totals[k] += cell[k]
    return {
        "title": f"经营{'日' if period == 'day' else ''}报（{date_from} 至 {date_to}）",
        "columns": [{"key": k, "name": n} for k, n in OPERATION_COLUMNS],
        "rows": rows,
        "totals": {k: fmt.base_money(v) for k, v in totals.items()},
        "meta": data["meta"] | {"report": "operations"},
    }


def _ratio(numerator: int, denominator: int) -> str | None:
    if not denominator:
        return None
    return f"{numerator / denominator:.4f}"


def sales(
    session: Session, ctx: RequestContext, date_from: date, date_to: date, period: str | None = None
) -> dict[str, Any]:
    """销售分析 by channel: orders, gross, refunds, fees, net received, fee rate, average order."""
    book = session.get(Book, ctx.require_book())
    assert book is not None
    fmt = _Fmt(session, book)
    group = ["channel", *([period] if period else []), "transaction_type", "line_role"]
    data = aggregate(
        session,
        ctx,
        Query(
            date_from,
            date_to,
            group_by=group,
            measures=["base_amount", "count"],
            transaction_types=["sale", "sale_refund"],
        ),
    )
    cells: dict[tuple[Any, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    names: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in data["rows"]:
        k = row["keys"]
        key = (k["channel"]["code"], k.get(period) if period else None)
        names[key] = k["channel"]
        role, ttype = k["line_role"]["code"], k["transaction_type"]["code"]
        amount = row["values"]["base_amount"]["minor"]
        c = cells[key]
        if role == "gross" and ttype == "sale":
            c["gross"] += amount
            c["orders"] += row["values"]["count"]
        elif role == "gross":
            c["refunds"] -= amount
            c["refund_count"] += row["values"]["count"]
        elif role == "fee":
            c["fees"] += amount
        elif role == "net":
            c["net_received"] += amount
    rows = []
    for key in sorted(cells, key=lambda k: (k[1] or "", -cells[k]["gross"])):
        c = cells[key]
        if not any(c[k] for k in ("gross", "refunds", "fees", "net_received", "orders")):
            continue  # e.g. currency rounding lines, which carry no channel
        params = {"channel": key[0], "date_from": str(date_from), "date_to": str(date_to)}
        if period and key[1]:
            start, end = _period_bounds(period, key[1])
            params |= {"date_from": max(start, date_from).isoformat(), "date_to": min(end, date_to).isoformat()}
        rows.append(
            {
                "channel": names[key],
                "period": key[1],
                "orders": c["orders"],
                "refund_count": c["refund_count"],
                "gross": fmt.base_money(c["gross"]),
                "refunds": fmt.base_money(c["refunds"]),
                "net_sales": fmt.base_money(c["gross"] - c["refunds"]),
                "fees": fmt.base_money(c["fees"]),
                "net_received": fmt.base_money(c["net_received"]),
                "fee_rate": _ratio(c["fees"], c["gross"] - c["refunds"]),
                "average_order": fmt.base_money(c["gross"] // c["orders"]) if c["orders"] else None,
                "drilldown": {"transactions": params},
            }
        )
    sums = {k: sum(c[k] for c in cells.values()) for k in ("gross", "refunds", "fees", "net_received", "orders")}
    return {
        "title": f"销售分析（{date_from} 至 {date_to}）",
        "rows": rows,
        "totals": {
            "orders": sums["orders"],
            "gross": fmt.base_money(sums["gross"]),
            "refunds": fmt.base_money(sums["refunds"]),
            "net_sales": fmt.base_money(sums["gross"] - sums["refunds"]),
            "fees": fmt.base_money(sums["fees"]),
            "net_received": fmt.base_money(sums["net_received"]),
            "fee_rate": _ratio(sums["fees"], sums["gross"] - sums["refunds"]),
        },
        "meta": data["meta"] | {"report": "sales"},
    }


def fees(session: Session, ctx: RequestContext, date_from: date, date_to: date) -> dict[str, Any]:
    """手续费分析 by channel × type: fee, fee base, effective rate, and how much is still estimated."""
    book = session.get(Book, ctx.require_book())
    assert book is not None
    fmt = _Fmt(session, book)
    fee_account = accounts.default_for_role(session, book.id, "expense_finance_fee")
    if fee_account is None:
        raise DomainError("ACCOUNT_NOT_POSTABLE", "账套缺少手续费科目。")
    fee_rows = aggregate(
        session,
        ctx,
        Query(
            date_from,
            date_to,
            group_by=["channel", "transaction_type", "is_estimate"],
            measures=["base_amount", "count"],
            accounts=[fee_account.code],
        ),
    )["rows"]
    base_rows = aggregate(
        session,
        ctx,
        Query(
            date_from,
            date_to,
            group_by=["channel", "transaction_type"],
            measures=["base_amount"],
            line_roles=["gross", "cost"],
            transaction_types=["sale", "sale_refund", "credit_purchase", "expense"],
        ),
    )["rows"]
    cells: dict[tuple[Any, Any], dict[str, Any]] = {}
    for row in fee_rows:
        k = row["keys"]
        key = (k["channel"]["code"], k["transaction_type"]["code"])
        c = cells.setdefault(
            key,
            {"channel": k["channel"], "type": k["transaction_type"], "fee": 0, "estimated": 0, "count": 0, "base": 0},
        )
        c["fee"] += row["values"]["base_amount"]["minor"]
        c["count"] += row["values"]["count"]
        if k["is_estimate"]:
            c["estimated"] += row["values"]["base_amount"]["minor"]
    for row in base_rows:  # refunds give negative base and negative fee, so the rate stays meaningful
        k = row["keys"]
        key = (k["channel"]["code"], k["transaction_type"]["code"])
        if key in cells:
            cells[key]["base"] += row["values"]["base_amount"]["minor"]
    rows = []
    for key in sorted(cells, key=lambda k: -cells[k]["fee"]):
        c = cells[key]
        rows.append(
            {
                "channel": c["channel"],
                "transaction_type": c["type"],
                "count": c["count"],
                "fee": fmt.base_money(c["fee"]),
                "estimated_fee": fmt.base_money(c["estimated"]),
                "base": fmt.base_money(c["base"]),
                "effective_rate": _ratio(c["fee"], c["base"]),
                "drilldown": {
                    "transactions": {
                        "channel": key[0],
                        "type": key[1],
                        "account": fee_account.code,
                        "date_from": str(date_from),
                        "date_to": str(date_to),
                    }
                },
            }
        )
    total_fee = sum(c["fee"] for c in cells.values())
    return {
        "title": f"手续费分析（{date_from} 至 {date_to}）",
        "rows": rows,
        "totals": {
            "fee": fmt.base_money(total_fee),
            "estimated_fee": fmt.base_money(sum(c["estimated"] for c in cells.values())),
        },
        "meta": _meta(session, "fees", {"date_from": str(date_from), "date_to": str(date_to)}, book.id, None),
    }


def credit_purchases(
    session: Session, ctx: RequestContext, date_from: date, date_to: date, period: str | None = None
) -> dict[str, Any]:
    """额度采购分析 by upstream site: purchases, face value, fees, total paid, credits, unit cost, refunds."""
    book = session.get(Book, ctx.require_book())
    assert book is not None
    fmt = _Fmt(session, book)
    group = ["counterparty", *([period] if period else []), "transaction_type", "line_role"]
    data = aggregate(
        session,
        ctx,
        Query(
            date_from,
            date_to,
            group_by=group,
            measures=["base_amount", "count", "quantity"],
            transaction_types=["credit_purchase", "purchase_refund"],
        ),
    )
    credit_account = accounts.default_for_role(session, book.id, "cost_operating")
    cells: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in data["rows"]:
        k = row["keys"]
        key = (k["counterparty"]["id"], k.get(period) if period else None)
        c = cells.setdefault(
            key, {"site": k["counterparty"], "count": 0, "face": 0, "fee": 0, "quantity": Decimal(0), "refunds": 0}
        )
        role, ttype = k["line_role"]["code"], k["transaction_type"]["code"]
        amount = row["values"]["base_amount"]["minor"]
        if ttype == "credit_purchase" and role == "cost":
            c["face"] += amount
            c["count"] += row["values"]["count"]
            if row["values"]["quantity"] is not None:
                c["quantity"] += Decimal(row["values"]["quantity"])
        elif ttype == "credit_purchase" and role == "fee":
            c["fee"] += amount
        elif ttype == "purchase_refund" and role == "cost":
            c["refunds"] -= amount
    rows = []
    for key in sorted(cells, key=lambda k: (k[1] or "", -(cells[k]["face"] + cells[k]["fee"]))):
        c = cells[key]
        total = c["face"] + c["fee"]
        params: dict[str, Any] = {"type": "credit_purchase", "date_from": str(date_from), "date_to": str(date_to)}
        if key[0]:
            params["counterparty"] = key[0]
        if period and key[1]:
            start, end = _period_bounds(period, key[1])
            params |= {"date_from": max(start, date_from).isoformat(), "date_to": min(end, date_to).isoformat()}
        qty = c["quantity"]
        net = from_minor(total - c["refunds"], fmt.scales[fmt.base])
        rows.append(
            {
                "site": c["site"],
                "period": key[1],
                "purchases": c["count"],
                "face": fmt.base_money(c["face"]),
                "fees": fmt.base_money(c["fee"]),
                "total_paid": fmt.base_money(total),
                "refunds": fmt.base_money(c["refunds"]),
                "net_cost": fmt.base_money(total - c["refunds"]),
                "credit_quantity": format(qty.normalize(), "f") if qty else None,
                "cost_per_credit": str((net / qty).quantize(Decimal("0.0001"))) if qty else None,
                "fee_rate": _ratio(c["fee"], c["face"]),
                "drilldown": {"transactions": params},
            }
        )
    return {
        "title": f"额度采购分析（{date_from} 至 {date_to}）",
        "rows": rows,
        "totals": {
            "purchases": sum(c["count"] for c in cells.values()),
            "face": fmt.base_money(sum(c["face"] for c in cells.values())),
            "fees": fmt.base_money(sum(c["fee"] for c in cells.values())),
            "total_paid": fmt.base_money(sum(c["face"] + c["fee"] for c in cells.values())),
            "refunds": fmt.base_money(sum(c["refunds"] for c in cells.values())),
        },
        "credit_account": credit_account.code if credit_account else None,
        "meta": data["meta"] | {"report": "credit_purchases"},
    }


def summary(session: Session, ctx: RequestContext, date_from: date, date_to: date) -> dict[str, Any]:
    """Dashboard: profit, funds by currency, top channels and sites, and what needs attention."""
    book = session.get(Book, ctx.require_book())
    assert book is not None
    fmt = _Fmt(session, book)
    pnl = income_statement(session, ctx, date_from, date_to)["summary"]
    funds_ids = {a.id for a in accounts.list_accounts(session, book.id) if a.role == "funds"}
    funds: dict[str, dict[str, int]] = defaultdict(lambda: {"amount": 0, "base": 0})
    for act in _activity(session, book.id, None, date_to, None, funds_ids):
        funds[act.commodity]["amount"] += act.closing
        funds[act.commodity]["base"] += act.base_closing
    suspense = accounts.default_for_role(session, book.id, "suspense")
    suspense_base = (
        sum(a.base_closing for a in _activity(session, book.id, None, date_to, None, {suspense.id})) if suspense else 0
    )

    def count(*conditions: ColumnElement[bool]) -> int:
        return int(
            session.execute(
                select(func.count()).select_from(Transaction).where(Transaction.book_id == book.id, *conditions)
            ).scalar_one()
        )

    channel_rows = sales(session, ctx, date_from, date_to)["rows"][:5]
    site_rows = credit_purchases(session, ctx, date_from, date_to)["rows"][:5]
    return {
        "title": f"概览（{date_from} 至 {date_to}）",
        "profit": {k: pnl[k] for k in ("revenue", "cost", "gross_profit", "operating_profit", "net_profit")},
        "funds": [
            {"commodity": c, "amount": fmt.money(v["amount"], c), "base": fmt.base_money(v["base"])}
            for c, v in sorted(funds.items())
            if v["amount"] or v["base"]
        ],
        "top_channels": [
            {"channel": r["channel"], "net_sales": r["net_sales"], "orders": r["orders"]} for r in channel_rows
        ],
        "top_sites": [
            {"site": r["site"], "total_paid": r["total_paid"], "purchases": r["purchases"]} for r in site_rows
        ],
        "attention": {
            "estimated": count(Transaction.status == "posted", Transaction.is_estimate.is_(True)),
            "suspense_balance": fmt.base_money(suspense_base),
        },
        "meta": _meta(session, "summary", {"date_from": str(date_from), "date_to": str(date_to)}, book.id, None),
    }
