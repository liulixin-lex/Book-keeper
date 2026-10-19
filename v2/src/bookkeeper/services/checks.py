"""Health checks (docs/07-reports-queries-checks.md §8): ledger integrity and things worth a look."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from bookkeeper.db.models import (
    Account,
    AccountBalance,
    CheckResult,
    CheckRun,
    JournalEntry,
    Transaction,
)
from bookkeeper.db.roles import REQUIRED_TRIGGERS
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import audit, ledger
from bookkeeper.services.context import RequestContext

SAMPLE = 50


@dataclass
class Outcome:
    code: str
    severity: str
    ok: bool
    message: str
    count: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


def unbalanced_entries(session: Session, book_id: str, limit: int = SAMPLE) -> list[dict[str, Any]]:
    rows = session.execute(
        text("""
        SELECT e.number, l.commodity, sum(l.amount) AS diff
        FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id
        WHERE l.book_id = :b GROUP BY e.number, l.commodity HAVING sum(l.amount) <> 0
        UNION ALL
        SELECT e.number, 'BASE', sum(l.base_amount)
        FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id
        WHERE l.book_id = :b GROUP BY e.number HAVING sum(l.base_amount) <> 0
        LIMIT :n
    """),
        {"b": book_id, "n": limit},
    ).all()
    return [{"entry": r[0], "commodity": r[1], "diff": int(r[2])} for r in rows]


def _trial_balance_zero(session: Session, book_id: str) -> Outcome:
    rows = session.execute(
        text("""
        SELECT commodity, sum(amount), sum(base_amount) FROM journal_lines WHERE book_id = :b GROUP BY commodity
    """),
        {"b": book_id},
    ).all()
    bad = [{"commodity": c, "sum": int(a)} for c, a, _ in rows if a != 0]
    base = sum(int(r[2]) for r in rows)
    if base:
        bad.append({"commodity": "BASE", "sum": base})
    return Outcome("trial_balance_zero", "error", not bad, "全账套各币种与本位币合计为零", len(bad), bad)


def _entries_balanced(session: Session, book_id: str) -> Outcome:
    bad = unbalanced_entries(session, book_id)
    return Outcome("entries_balanced", "error", not bad, "每张分录借贷平衡", len(bad), bad)


def _hash_chain(session: Session, book_id: str) -> Outcome:
    result = ledger.verify_chain(session, book_id)
    audit_result = audit.verify_chain(session, book_id)
    details = []
    if not result.ok:
        details.append({"chain": "ledger", "first_bad_seq": result.first_bad_seq, "reason": result.reason})
    if not audit_result.ok:
        details.append(
            {
                "chain": "audit",
                "first_bad_seq": audit_result.first_bad_seq,
                "reason": audit_result.reason,
            }
        )
    return Outcome(
        "hash_chain",
        "error",
        not details,
        f"分录哈希链（{result.entries} 张）与审计哈希链（{audit_result.events} 条）连续可重算",
        len(details),
        details,
    )


def _sequence_gaps(session: Session, book_id: str) -> Outcome:
    seq_gaps = session.execute(
        text("""
        SELECT count(*) FILTER (WHERE seq <> rn) FROM (
            SELECT seq, row_number() OVER (ORDER BY seq) AS rn FROM journal_entries WHERE book_id = :b) t
    """),
        {"b": book_id},
    ).scalar_one()
    number_gaps = session.execute(
        text("""
        SELECT journal_code, period, n, expected FROM (
            SELECT journal_code, substring(number from '-([0-9]{6})-') AS period,
                   count(*) AS n, max(split_part(number, '-', 3)::int) AS expected
            FROM journal_entries WHERE book_id = :b GROUP BY 1, 2) t WHERE n <> expected
    """),
        {"b": book_id},
    ).all()
    details = [{"journal_code": r[0], "period": r[1], "count": int(r[2]), "max": int(r[3])} for r in number_gaps]
    if seq_gaps:
        details.append({"seq_gaps": int(seq_gaps)})
    return Outcome("sequence_gaps", "error", not details, "分录序号与凭证号连续无断号", len(details), details)


def _balances_cache(session: Session, book_id: str) -> Outcome:
    rows = session.execute(
        text("""
        WITH actual AS (
            SELECT account_id, commodity, sum(amount) AS bal, sum(base_amount) AS base, count(*) AS n
            FROM journal_lines WHERE book_id = :b GROUP BY 1, 2)
        SELECT coalesce(a.account_id, c.account_id), coalesce(a.commodity, c.commodity),
               a.bal, c.balance, a.base, c.base_balance, a.n, c.line_count
        FROM actual a FULL JOIN (SELECT * FROM account_balances WHERE book_id = :b) c
          ON c.account_id = a.account_id AND c.commodity = a.commodity
        WHERE coalesce(a.bal, 0) <> coalesce(c.balance, 0) OR coalesce(a.base, 0) <> coalesce(c.base_balance, 0)
           OR coalesce(a.n, 0) <> coalesce(c.line_count, 0)
        LIMIT :n
    """),
        {"b": book_id, "n": SAMPLE},
    ).all()
    details = [{"account_id": r[0], "commodity": r[1], "lines": r[2], "cache": r[3]} for r in rows]
    return Outcome("balances_cache", "error", not details, "科目余额缓存与分录行一致", len(details), details)


def _daily_balances(session: Session, book_id: str) -> Outcome:
    rows = session.execute(
        text("""
        WITH actual AS (
            SELECT account_id, commodity, effective_date AS d,
                   sum(greatest(amount, 0)) AS dr, sum(greatest(-amount, 0)) AS cr,
                   sum(greatest(base_amount, 0)) AS bdr, sum(greatest(-base_amount, 0)) AS bcr
            FROM journal_lines WHERE book_id = :b GROUP BY 1, 2, 3)
        SELECT coalesce(a.account_id, c.account_id), coalesce(a.commodity, c.commodity), coalesce(a.d, c.date)
        FROM actual a FULL JOIN (SELECT * FROM daily_balances WHERE book_id = :b) c
          ON c.account_id = a.account_id AND c.commodity = a.commodity AND c.date = a.d
        WHERE coalesce(a.dr, 0) <> coalesce(c.debit, 0) OR coalesce(a.cr, 0) <> coalesce(c.credit, 0)
           OR coalesce(a.bdr, 0) <> coalesce(c.base_debit, 0) OR coalesce(a.bcr, 0) <> coalesce(c.base_credit, 0)
        LIMIT :n
    """),
        {"b": book_id, "n": SAMPLE},
    ).all()
    details = [{"account_id": r[0], "commodity": r[1], "date": r[2].isoformat()} for r in rows]
    return Outcome("daily_balances", "error", not details, "每日发生额与分录行一致", len(details), details)


def _immutability_guard(session: Session, book_id: str) -> Outcome:
    present = set(
        session.execute(
            text("SELECT tgname FROM pg_trigger WHERE tgname = ANY(:n) AND tgenabled <> 'D'"),
            {"n": list(REQUIRED_TRIGGERS)},
        ).scalars()
    )
    missing = sorted(set(REQUIRED_TRIGGERS) - present)
    return Outcome(
        "immutability_guard",
        "error",
        not missing,
        "数据库不变量触发器齐全且启用",
        len(missing),
        [{"missing_trigger": m} for m in missing],
    )


def _orphans(session: Session, book_id: str) -> Outcome:
    details: list[dict[str, Any]] = []
    for number, status in session.execute(
        select(Transaction.number, Transaction.status)
        .where(
            Transaction.book_id == book_id,
            Transaction.status.in_(("posted", "reversed")),
            Transaction.posted_entry_id.is_(None),
        )
        .limit(SAMPLE)
    ).all():
        details.append({"transaction": number, "problem": f"{status} 但没有入账分录"})
    for number, status in session.execute(
        select(Transaction.number, Transaction.status)
        .join(JournalEntry, JournalEntry.id == Transaction.posted_entry_id)
        .where(
            Transaction.book_id == book_id,
            ((Transaction.status == "reversed") & JournalEntry.reversed_by_entry_id.is_(None))
            | ((Transaction.status == "posted") & JournalEntry.reversed_by_entry_id.is_not(None)),
        )
        .limit(SAMPLE)
    ).all():
        problem = "已删除但当前分录没有冲销" if status == "reversed" else "正常但当前分录已被冲销"
        details.append({"transaction": number, "problem": problem})
    return Outcome("orphans", "error", not details, "交易状态与分录一致", len(details), details)


def _normal_side(session: Session, book_id: str) -> Outcome:
    rows = session.execute(
        select(
            Account.code,
            Account.name,
            AccountBalance.commodity,
            AccountBalance.balance,
            Account.normal_side,
        )
        .join(Account, Account.id == AccountBalance.account_id)
        .where(
            AccountBalance.book_id == book_id,
            Account.role.not_in(("trading", "suspense", "fx_gain_loss", "rounding", "interest")),
        )
    ).all()
    details = [
        {"account": f"{c} {n}", "commodity": cm, "balance": int(b)}
        for c, n, cm, b, side in rows
        if (side == "debit" and b < 0) or (side == "credit" and b > 0)
    ][:SAMPLE]
    return Outcome("normal_side", "warning", not details, "科目余额方向正常", len(details), details)


def _suspense_zero(session: Session, book_id: str) -> Outcome:
    total = session.execute(
        select(func.coalesce(func.sum(AccountBalance.base_balance), 0))
        .join(Account, Account.id == AccountBalance.account_id)
        .where(AccountBalance.book_id == book_id, Account.role == "suspense")
    ).scalar_one()
    return Outcome(
        "suspense_zero",
        "warning",
        total == 0,
        "待核对款项余额为 0",
        0 if total == 0 else 1,
        [] if total == 0 else [{"base_balance": int(total)}],
    )


def _duplicate_risk(session: Session, book_id: str) -> Outcome:
    """Live pairs with the same type, date, counterparty and amount that nothing tells apart: external
    refs, order numbers and recorded times all equal or missing. Adding an order number or a time to a
    genuine pair settles it."""
    rows = session.execute(
        text("""
        WITH t AS (
            SELECT x.id, x.number, x.effective_date, x.counterparty_id, x.transaction_type_id,
                   x.external_ref, x.order_no, x.occurred_at,
                   (SELECT sum(l.base_amount) FROM journal_lines l
                     WHERE l.entry_id = x.posted_entry_id AND l.base_amount > 0) AS total
            FROM transactions x WHERE x.book_id = :b AND x.status = 'posted'
        )
        SELECT a.number, b.number, a.effective_date, a.total FROM t a JOIN t b
          ON a.id < b.id
         AND a.effective_date = b.effective_date
         AND a.transaction_type_id = b.transaction_type_id
         AND a.counterparty_id IS NOT DISTINCT FROM b.counterparty_id
         AND a.total = b.total
         AND (a.external_ref IS NULL OR b.external_ref IS NULL OR a.external_ref = b.external_ref)
         AND (a.order_no IS NULL OR b.order_no IS NULL OR a.order_no = b.order_no)
         AND (a.occurred_at IS NULL OR b.occurred_at IS NULL OR a.occurred_at = b.occurred_at)
        ORDER BY a.effective_date DESC LIMIT :n
    """),
        {"b": book_id, "n": SAMPLE + 1},
    ).all()
    details = [
        {"transactions": [r[0], r[1]], "date": r[2].isoformat(), "base_amount": int(r[3])} for r in rows[:SAMPLE]
    ]
    return Outcome(
        "duplicate_risk",
        "warning",
        not rows,
        "无疑似重复的交易"
        if not rows
        else "疑似重复：同日、同类型、同往来方、同金额，单号与时间也无法区分（确是两笔的，补上订单号或时间即可）",
        len(rows),
        details,
    )


CHECKS: dict[str, Callable[[Session, str], Outcome]] = {
    "trial_balance_zero": _trial_balance_zero,
    "entries_balanced": _entries_balanced,
    "hash_chain": _hash_chain,
    "sequence_gaps": _sequence_gaps,
    "balances_cache": _balances_cache,
    "daily_balances": _daily_balances,
    "immutability_guard": _immutability_guard,
    "orphans": _orphans,
    "normal_side": _normal_side,
    "suspense_zero": _suspense_zero,
    "duplicate_risk": _duplicate_risk,
}


def _decimal_json(value: Decimal) -> int | str:
    return int(value) if value == value.to_integral_value() else str(value)


def run_checks(
    session: Session, ctx: RequestContext, codes: list[str] | None = None, trigger: str = "manual"
) -> CheckRun:
    ctx.require(Scope.LEDGER_READ)
    book_id = ctx.require_book()
    selected = codes or list(CHECKS)
    unknown = set(selected) - set(CHECKS)
    if unknown:
        raise DomainError("VALIDATION_FAILED", f"未知检查：{', '.join(sorted(unknown))}。")
    run = CheckRun(
        id=new_id("chk"),
        book_id=book_id,
        trigger=trigger,
        started_at=datetime.now(UTC),
        status="running",
        created_by=ctx.actor.user_id,
    )
    session.add(run)
    session.flush()
    outcomes = [CHECKS[code](session, book_id) for code in selected]
    for o in outcomes:
        o.details = jsonable_encoder(o.details, custom_encoder={Decimal: _decimal_json})
        session.add(
            CheckResult(
                id=new_id("chr"),
                run_id=run.id,
                check_code=o.code,
                severity=o.severity,
                status="pass" if o.ok else "fail",
                count=o.count,
                message=o.message,
                details=o.details or None,
            )
        )
    errors = [o.code for o in outcomes if not o.ok and o.severity == "error"]
    warnings = [o.code for o in outcomes if not o.ok and o.severity == "warning"]
    run.status = "failed" if errors else "passed"
    run.finished_at = datetime.now(UTC)
    run.summary = {"checks": len(outcomes), "errors": errors, "warnings": warnings}
    session.flush()
    return run


def run_view(session: Session, run: CheckRun) -> dict[str, Any]:
    results = session.execute(
        select(CheckResult).where(CheckResult.run_id == run.id).order_by(CheckResult.check_code)
    ).scalars()
    return {
        "id": run.id,
        "trigger": run.trigger,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "summary": run.summary,
        "results": [
            {
                "code": r.check_code,
                "severity": r.severity,
                "status": r.status,
                "count": r.count,
                "message": r.message,
                "details": r.details,
            }
            for r in results
        ],
    }
